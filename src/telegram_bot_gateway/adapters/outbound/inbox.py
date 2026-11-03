"""The message inbox over HTTP, with a service bearer that is static or fetched by client credentials.

No bearer, client secret or token reply is ever logged or put in an error message.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

from telegram_bot_gateway.application.ports import InboxError, Press, ReplyResult, ReplyPrompt

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 15
TOKEN_MARGIN_SECONDS = 60
DEFAULT_TOKEN_LIFETIME = 300


class ServiceToken:
    """The bearer the bot itself presents to the inbox."""

    def __init__(
        self, static: str = "", *, token_url: str = "", client_id: str = "", client_secret: str = "",
        client: httpx.AsyncClient, clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._static, self._url, self._id, self._secret = static, token_url, client_id, client_secret
        self._http, self._clock = client, clock
        self._token = ""
        self._expires = 0.0

    def forget(self) -> None:
        """Drop the cached token (the inbox refused it); a static token cannot be refreshed."""
        self._token, self._expires = "", 0.0

    async def get(self) -> str:
        if self._static:
            return self._static
        if self._token and self._clock() < self._expires - TOKEN_MARGIN_SECONDS:
            return self._token
        try:
            reply = await self._http.post(self._url, data={
                "grant_type": "client_credentials", "client_id": self._id, "client_secret": self._secret,
            })
            body = reply.json() if reply.status_code == 200 else {}
        except (httpx.HTTPError, ValueError) as exc:
            raise InboxError(f"the token endpoint did not answer ({exc.__class__.__name__})") from None
        token = body.get("access_token") if isinstance(body, dict) else None
        if not token:
            raise InboxError(f"the token endpoint refused the client credentials (HTTP {reply.status_code})")
        lifetime = body.get("expires_in")
        self._token = str(token)
        self._expires = self._clock() + (float(lifetime) if isinstance(lifetime, (int, float)) else DEFAULT_TOKEN_LIFETIME)
        return self._token


class HttpInbox:
    def __init__(self, base_url: str, token: ServiceToken, client: httpx.AsyncClient | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._http = client or httpx.AsyncClient(timeout=TIMEOUT_SECONDS)

    async def close(self) -> None:
        await self._http.aclose()

    async def _service(self, path: str, body: dict[str, Any]) -> httpx.Response:
        """A call with the service bearer; a refused cached token is dropped and the call repeated once."""
        for attempt in (0, 1):
            bearer = await self._token.get()
            try:
                reply = await self._http.post(self._base + path, json=body, headers={"Authorization": f"Bearer {bearer}"})
            except httpx.HTTPError as exc:
                raise InboxError(f"{path}: no answer ({exc.__class__.__name__})") from None
            if reply.status_code == 401 and attempt == 0:
                self._token.forget()
                continue
            return reply
        raise AssertionError("unreachable")

    async def lease(self, limit: int, lease_seconds: int) -> list[dict[str, Any]]:
        reply = await self._service("/outbox/lease", {"limit": limit, "lease_seconds": lease_seconds})
        if reply.status_code != 200:
            raise InboxError(f"/outbox/lease: HTTP {reply.status_code}")
        try:
            items = reply.json().get("items", [])
        except (ValueError, AttributeError):
            raise InboxError("/outbox/lease: not a JSON object") from None
        return items if isinstance(items, list) else []

    async def ack(self, item_id: str, external_ref: str) -> None:
        reply = await self._service(f"/outbox/{item_id}/ack", {"external_ref": external_ref})
        if reply.status_code >= 300:
            raise InboxError(f"ack: HTTP {reply.status_code}")

    async def release(self, item_id: str, retry_in: int, error: str) -> None:
        reply = await self._service(f"/outbox/{item_id}/release", {"retry_in": retry_in, "error": error[:500]})
        if reply.status_code >= 300:
            raise InboxError(f"release: HTTP {reply.status_code}")

    async def press(self, bearer: str, button: str) -> Press:
        try:
            reply = await self._http.post(
                self._base + "/buttons/press", json={"button": button}, headers={"Authorization": f"Bearer {bearer}"},
            )
        except httpx.HTTPError as exc:
            log.warning("a button press did not reach the inbox (%s)", exc.__class__.__name__)
            return Press("failed")
        status = reply.status_code
        if 200 <= status < 300:
            return Press("decided", _prompt(reply))
        if status == 401:
            return Press("unauthorized")
        if status == 403:
            return Press("forbidden")
        if status == 404:
            return Press("gone")
        if status == 409 and _error_code(reply) == "already_decided":
            return Press("already_decided")
        log.warning("a button press was answered with HTTP %s", status)
        return Press("failed")

    async def reply(self, bearer: str, ref: str, text: str) -> ReplyResult:
        try:
            reply = await self._http.post(
                self._base + "/replies", json={"ref": ref, "text": text}, headers={"Authorization": f"Bearer {bearer}"},
            )
        except httpx.HTTPError as exc:
            log.warning("a reply did not reach the inbox (%s)", exc.__class__.__name__)
            return ReplyResult(False, "")
        if 200 <= reply.status_code < 300:
            return ReplyResult(True)
        if reply.status_code == 401:
            return ReplyResult(False, "")
        if 400 <= reply.status_code < 500:
            return ReplyResult(False, _error_message(reply) or "Your reply was not accepted.")
        log.warning("a reply was answered with HTTP %s", reply.status_code)
        return ReplyResult(False, "")

    async def link(self, code: str, address: str, label: str) -> bool:
        reply = await self._service("/outbox/link", {"code": code, "address": address, "label": label})
        if reply.status_code < 300:
            return True
        if reply.status_code in (400, 404, 409, 410, 422):
            return False
        raise InboxError(f"link: HTTP {reply.status_code}")


def _prompt(reply: httpx.Response) -> ReplyPrompt | None:
    try:
        data = reply.json()["reply_prompt"]
        ref, text = str(data["ref"]), str(data["text"])
    except (ValueError, KeyError, TypeError):
        return None
    return ReplyPrompt(ref, text[:500]) if ref and text else None


def _error_code(reply: httpx.Response) -> str:
    try:
        return str(reply.json()["error"]["code"])
    except (ValueError, KeyError, TypeError):
        return ""


def _error_message(reply: httpx.Response) -> str:
    try:
        return str(reply.json()["error"]["message"])[:300]
    except (ValueError, KeyError, TypeError):
        return ""
