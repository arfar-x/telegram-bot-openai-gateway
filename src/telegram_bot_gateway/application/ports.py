"""What the application needs from the outside."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from telegram_bot_gateway.application.model import DeviceLogin, Link, PairingRequest, Pending, Session
from telegram_bot_gateway.domain.tools.buttons import Buttons
from telegram_bot_gateway.domain.tools.files import File
from telegram_bot_gateway.domain.tools.images import Image


class Store(Protocol):
    async def get_link(self, telegram_user_id: int) -> Link | None: ...
    async def save_link(self, link: Link) -> None: ...
    async def delete_links(self, *, telegram_user_id: int | None = None, username: str | None = None) -> int: ...
    async def list_links(self) -> list[Link]: ...
    async def update_oidc_tokens(self, telegram_user_id: int, refresh_token_enc: str, *, refreshed_at: float) -> bool:
        """Store a rotated refresh token on an active oidc link; False when there is no such link."""
        ...
    async def expire_link(self, telegram_user_id: int) -> bool:
        """Mark an oidc link expired and clear its refresh token; False when there is no such link."""
        ...

    async def save_device_login(self, login: DeviceLogin) -> None:
        """Store a login, replacing the user's earlier one."""
        ...
    async def get_device_login(self, telegram_user_id: int) -> DeviceLogin | None: ...
    async def list_device_logins(self) -> list[DeviceLogin]: ...
    async def delete_device_login(self, telegram_user_id: int, *, user_code: str | None = None) -> None: ...
    async def prune_device_logins(self, *, before: float) -> int: ...

    async def create_pairing(self, request: PairingRequest) -> None: ...
    async def get_pairing(self, code: str) -> PairingRequest | None: ...
    async def pairings_of(self, telegram_user_id: int) -> list[PairingRequest]: ...
    async def list_pairings(self, *, since: float) -> list[PairingRequest]: ...
    async def delete_pairing(self, code: str) -> None: ...
    async def prune_pairings(self, *, before: float) -> int: ...

    async def load_session(self, key: str) -> Session | None: ...
    async def save_session(self, session: Session) -> None: ...
    async def delete_session(self, key: str) -> None: ...
    async def delete_sessions_of(self, telegram_user_id: int) -> None: ...
    async def find_pending(self, chat_id: int, card_message_id: int) -> Session | None: ...

    async def save_text(self, chat_id: int, message_id: int, text: str) -> None: ...
    async def get_text(self, chat_id: int, message_id: int) -> str | None: ...
    async def prune_texts(self, *, older_than_days: int) -> int: ...


class Vault(Protocol):
    def encrypt(self, plaintext: str) -> str: ...
    def decrypt(self, ciphertext: str) -> str: ...


ReasoningSink = Callable[[str], Awaitable[None]]


class Llm(Protocol):
    async def chat(
        self,
        api_key: str,
        model: str,
        messages: list[dict[str, Any]],
        params: dict[str, Any],
        tools: list[dict[str, Any]],
        on_reasoning: ReasoningSink | None = None,
    ) -> dict[str, Any]:
        """One assistant message, as the endpoint returned it."""
        ...

    async def models(self, api_key: str) -> list[str]: ...


class ActionError(Exception):
    """A client tool could not be carried out; the message goes back to the endpoint."""


@dataclass(frozen=True)
class Facts:
    chat_type: str
    topic: bool
    language: str | None


class Actions(Protocol):
    """What the client tools do in the chat of one turn. Each raises ActionError when it cannot."""

    async def send_file(self, file: File) -> None: ...
    async def send_image(self, image: Image) -> None: ...
    async def send_buttons(self, buttons: Buttons) -> None: ...
    async def notify(self, text: str) -> None: ...
    async def react(self, emoji: str) -> None: ...
    def facts(self) -> Facts: ...


class IdentityError(Exception):
    """Base of what an issuer can answer wrongly."""


class IdentityRefused(IdentityError):
    """The issuer refused a refresh token for good (``invalid_grant``, ``unauthorized_client``)."""


class IdentityUnavailable(IdentityError):
    """The issuer did not answer usefully (network error, 5xx, an unexpected reply); trying again may work."""


@dataclass(frozen=True)
class DeviceAuthorization:
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None
    interval: int
    expires_in: int


@dataclass(frozen=True)
class Tokens:
    access_token: str
    expires_in: int
    refresh_token: str | None = None
    subject: str | None = None
    username: str | None = None


@dataclass(frozen=True)
class DevicePoll:
    """One answer of the token endpoint: ``status`` is pending, slow_down, approved, denied or expired."""

    status: str
    tokens: Tokens | None = None


class IdentityProvider(Protocol):
    """An OpenID Connect issuer, reached by the device grant. Nothing it returns is ever logged."""

    async def start_device(self) -> DeviceAuthorization: ...
    async def poll(self, device_code: str) -> DevicePoll: ...
    async def refresh(self, refresh_token: str) -> Tokens: ...
    async def revoke(self, refresh_token: str) -> bool:
        """True when revoked; False when the issuer advertises no revocation endpoint."""
        ...
