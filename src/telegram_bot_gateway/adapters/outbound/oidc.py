"""The issuer over HTTP: discovery, the device grant, refresh and revocation (RFC 8628, RFC 7009).

Nothing a request or reply carries (device codes, access and refresh tokens, the client secret) is ever
logged or put in an error message.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

from telegram_bot_gateway.application.ports import (
    DeviceAuthorization, DevicePoll, IdentityRefused, IdentityUnavailable, Tokens,
)

log = logging.getLogger(__name__)

DISCOVERY_PATH = "/.well-known/openid-configuration"
DISCOVERY_TTL_SECONDS = 3600
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
REFUSED_ERRORS = {"invalid_grant", "unauthorized_client"}
TIMEOUT_SECONDS = 15


class IssuerMisconfigured(Exception):
    """The issuer's discovery document cannot support device sign-in."""


def claims_of(jwt: str | None) -> dict[str, Any]:
    """The payload of a token received straight from the token endpoint over TLS; the signature is not checked."""
    if not jwt or jwt.count(".") != 2:
        return {}
    try:
        payload = jwt.split(".")[1]
        decoded = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (ValueError, binascii.Error):
        return {}
    return decoded if isinstance(decoded, dict) else {}


class OidcIdentity:
    def __init__(
        self, issuer: str, client_id: str, client_secret: str = "", scope: str = "openid offline_access",
        client: httpx.AsyncClient | None = None, clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._issuer = issuer.rstrip("/")
        self._client_id, self._secret, self._scope = client_id, client_secret, scope
        self._http = client or httpx.AsyncClient(timeout=TIMEOUT_SECONDS)
        self._clock = clock
        self._document: dict[str, Any] | None = None
        self._fetched = 0.0

    async def close(self) -> None:
        await self._http.aclose()

    # -- discovery -----------------------------------------------------------------------------
    async def discovery(self) -> dict[str, Any]:
        if self._document is not None and self._clock() - self._fetched < DISCOVERY_TTL_SECONDS:
            return self._document
        try:
            reply = await self._http.get(self._issuer + DISCOVERY_PATH)
            reply.raise_for_status()
            document = reply.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise IdentityUnavailable(f"the issuer's discovery document cannot be read ({exc.__class__.__name__})") from None
        if not isinstance(document, dict):
            raise IdentityUnavailable("the issuer's discovery document is not an object")
        self._document, self._fetched = document, self._clock()
        return document

    async def ensure_device_flow(self) -> None:
        """Raises IssuerMisconfigured when the issuer cannot do the device grant, IdentityUnavailable when unreachable."""
        document = await self.discovery()
        if not document.get("device_authorization_endpoint") or not document.get("token_endpoint"):
            raise IssuerMisconfigured("the issuer's discovery document has no device authorization endpoint")

    async def _endpoint(self, name: str) -> str:
        url = (await self.discovery()).get(name)
        if not url:
            raise IdentityUnavailable(f"the issuer has no {name}")
        return url

    # -- requests ------------------------------------------------------------------------------
    async def _post(self, endpoint: str, form: dict[str, str]) -> tuple[int, dict[str, Any]]:
        data = {"client_id": self._client_id, **form}
        auth = (self._client_id, self._secret) if self._secret else None
        try:
            reply = await self._http.post(endpoint, data=data, auth=auth, headers={"Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise IdentityUnavailable(f"the issuer did not answer ({exc.__class__.__name__})") from None
        try:
            body = reply.json()
        except ValueError:
            body = {}
        if reply.status_code >= 500:
            raise IdentityUnavailable(f"the issuer answered {reply.status_code}")
        return reply.status_code, body if isinstance(body, dict) else {}

    # -- the port ------------------------------------------------------------------------------
    async def start_device(self) -> DeviceAuthorization:
        status, body = await self._post(
            await self._endpoint("device_authorization_endpoint"), {"scope": self._scope}
        )
        try:
            if status != 200:
                raise KeyError
            return DeviceAuthorization(
                device_code=body["device_code"], user_code=body["user_code"],
                verification_uri=body.get("verification_uri") or body["verification_uri_complete"],
                verification_uri_complete=body.get("verification_uri_complete"),
                interval=int(body.get("interval") or 5), expires_in=int(body.get("expires_in") or 600),
            )
        except (KeyError, TypeError, ValueError):
            raise IdentityUnavailable(f"the issuer refused to start a sign-in (status {status}, {body.get('error', 'no error')})") from None

    async def poll(self, device_code: str) -> DevicePoll:
        status, body = await self._post(
            await self._endpoint("token_endpoint"), {"grant_type": DEVICE_GRANT, "device_code": device_code}
        )
        if status == 200 and body.get("access_token"):
            return DevicePoll("approved", await self._tokens(body))
        error = body.get("error")
        if error == "authorization_pending":
            return DevicePoll("pending")
        if error == "slow_down":
            return DevicePoll("slow_down")
        if error == "access_denied":
            return DevicePoll("denied")
        if error == "expired_token":
            return DevicePoll("expired")
        raise IdentityUnavailable(f"unexpected answer while waiting for approval (status {status}, {error or 'no error'})")

    async def refresh(self, refresh_token: str) -> Tokens:
        status, body = await self._post(
            await self._endpoint("token_endpoint"), {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )
        if status == 200 and body.get("access_token"):
            return Tokens(
                access_token=body["access_token"], expires_in=int(body.get("expires_in") or 60),
                refresh_token=body.get("refresh_token"),
            )
        if body.get("error") in REFUSED_ERRORS:
            raise IdentityRefused()
        raise IdentityUnavailable(f"the issuer did not refresh the token (status {status}, {body.get('error', 'no error')})")

    async def revoke(self, refresh_token: str) -> bool:
        endpoint = (await self.discovery()).get("revocation_endpoint")
        if not endpoint:
            return False
        status, body = await self._post(endpoint, {"token": refresh_token, "token_type_hint": "refresh_token"})
        if status != 200:
            raise IdentityUnavailable(f"the issuer did not revoke the token (status {status})")
        return True

    # -- tokens --------------------------------------------------------------------------------
    async def _tokens(self, body: dict[str, Any]) -> Tokens:
        claims = claims_of(body.get("id_token"))
        subject, username = claims.get("sub"), claims.get("preferred_username")
        if not subject:
            claims = await self._userinfo(body["access_token"])
            subject, username = claims.get("sub"), username or claims.get("preferred_username")
        return Tokens(
            access_token=body["access_token"], expires_in=int(body.get("expires_in") or 60),
            refresh_token=body.get("refresh_token"), subject=subject or None,
            username=username if isinstance(username, str) and username else None,
        )

    async def _userinfo(self, access_token: str) -> dict[str, Any]:
        endpoint = (await self.discovery()).get("userinfo_endpoint")
        if not endpoint:
            return {}
        try:
            reply = await self._http.get(endpoint, headers={"Authorization": f"Bearer {access_token}"})
            body = reply.json() if reply.status_code == 200 else {}
        except (httpx.HTTPError, ValueError):
            return {}
        return body if isinstance(body, dict) else {}
