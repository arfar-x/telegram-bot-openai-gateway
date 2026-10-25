"""A fake OpenID Connect issuer behind httpx's mock transport, enough for the device flow."""

from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs

import httpx

BASE = "https://idp.test/realms/r"


def jwt(claims: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"e30.{body}.sig"


class FakeIssuer:
    def __init__(self, *, revocation=True, device=True, interval=5, expires_in=600, rotate=True) -> None:
        self.revocation, self.device, self.interval, self.expires_in, self.rotate = revocation, device, interval, expires_in, rotate
        self.approved = False
        self.denied = False
        self.slow_down_next = 0
        self.disabled = False
        self.down = False
        self.expired_code = False
        self.requests: list[tuple[str, dict[str, str]]] = []
        self.auth_headers: list[str | None] = []
        self.refresh_tokens: set[str] = set()
        self.revoked: list[str] = []
        self._n = 0
        self.discovery_hits = 0

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle))

    def _mint(self, kind: str) -> str:
        self._n += 1
        return f"{kind}-{self._n}"

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/realms/r")
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        self.requests.append((path, form))
        self.auth_headers.append(request.headers.get("authorization"))
        if self.down:
            return httpx.Response(503, text="down")
        if path == "/.well-known/openid-configuration":
            self.discovery_hits += 1
            doc = {"issuer": BASE, "token_endpoint": BASE + "/token", "userinfo_endpoint": BASE + "/userinfo"}
            if self.device:
                doc["device_authorization_endpoint"] = BASE + "/device"
            if self.revocation:
                doc["revocation_endpoint"] = BASE + "/revoke"
            return httpx.Response(200, json=doc)
        if path == "/device":
            return httpx.Response(200, json={
                "device_code": "DEVICE-SECRET", "user_code": "WDJB-MJHT", "verification_uri": BASE + "/device",
                "verification_uri_complete": BASE + "/device?user_code=WDJB-MJHT",
                "expires_in": self.expires_in, "interval": self.interval,
            })
        if path == "/revoke":
            self.revoked.append(form["token"])
            self.refresh_tokens.discard(form["token"])
            return httpx.Response(200)
        if path == "/userinfo":
            return httpx.Response(200, json={"sub": "sub-ann", "preferred_username": "ann"})
        if path == "/token":
            return self._token(form)
        return httpx.Response(404)

    def _token(self, form: dict[str, str]) -> httpx.Response:
        def error(name: str, status: int = 400) -> httpx.Response:
            return httpx.Response(status, json={"error": name})

        if form["grant_type"].endswith("device_code"):
            if self.slow_down_next:
                self.slow_down_next -= 1
                return error("slow_down")
            if self.expired_code:
                return error("expired_token")
            if self.denied:
                return error("access_denied")
            if not self.approved:
                return error("authorization_pending")
            refresh = self._mint("refresh")
            self.refresh_tokens.add(refresh)
            return httpx.Response(200, json={
                "access_token": self._mint("access"), "expires_in": 300, "refresh_token": refresh,
                "id_token": jwt({"sub": "sub-ann", "preferred_username": "ann"}),
            })
        if self.disabled or form["refresh_token"] not in self.refresh_tokens:
            return error("invalid_grant")
        body = {"access_token": self._mint("access"), "expires_in": 300}
        if self.rotate:
            self.refresh_tokens.discard(form["refresh_token"])
            body["refresh_token"] = self._mint("refresh")
            self.refresh_tokens.add(body["refresh_token"])
        return httpx.Response(200, json=body)
