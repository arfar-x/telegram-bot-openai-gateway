"""Records the application works with."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PENDING_TTL_SECONDS = 24 * 3600


@dataclass
class Pending:
    """A question waiting for the user: the history ends with the assistant's tool call."""

    tool_call_id: str
    question: str
    options: list[str]
    chat_id: int
    created_at: float
    card_message_id: int | None = None


@dataclass
class Session:
    key: str
    telegram_user_id: int
    model: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)
    pending: Pending | None = None


@dataclass(frozen=True)
class Link:
    """One Telegram user tied to one way of calling the endpoint: an API key or an issuer's refresh token."""

    telegram_user_id: int
    username: str
    telegram_name: str
    api_key_enc: str | None = None
    kind: str = "api_key"  # "api_key" | "oidc"
    subject: str | None = None
    refresh_token_enc: str | None = None
    status: str = "active"  # "active" | "expired"
    refreshed_at: float | None = None

    @property
    def usable(self) -> bool:
        return self.status == "active"


@dataclass(frozen=True)
class DeviceLogin:
    """A sign-in in progress; the device code is held encrypted."""

    telegram_user_id: int
    chat_id: int
    username: str
    telegram_name: str
    device_code_enc: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None
    interval_seconds: int
    expires_at: float


@dataclass(frozen=True)
class PairingRequest:
    code: str
    telegram_user_id: int
    username: str
    telegram_name: str
    chat_id: int
    created_at: float
