"""Linking a Telegram user to the endpoint: by an API key the operator approves, or by signing in at an issuer."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from telegram_bot_gateway.application.model import DeviceLogin, Link, PairingRequest
from telegram_bot_gateway.application.ports import (
    IdentityProvider, IdentityRefused, IdentityUnavailable, Store, Vault,
)
from telegram_bot_gateway.domain import oidc, pairing


class KeyUnreadable(Exception):
    """A stored API key cannot be decrypted with the configured key."""


@dataclass(frozen=True)
class Paired:
    code: str


@dataclass(frozen=True)
class Refused:
    reason: str  # "too_soon" | "too_many"


async def request(
    store: Store, *, telegram_user_id: int, username: str, telegram_name: str, chat_id: int, now: float
) -> Paired | Refused:
    await store.prune_pairings(before=now - pairing.TTL_SECONDS)
    live = [p for p in await store.pairings_of(telegram_user_id) if now - p.created_at < pairing.TTL_SECONDS]
    if live and now - max(p.created_at for p in live) < pairing.REQUEST_INTERVAL_SECONDS:
        return Refused("too_soon")
    if len(live) >= pairing.MAX_PENDING:
        return Refused("too_many")
    code = pairing.new_code()
    await store.create_pairing(PairingRequest(code, telegram_user_id, username, telegram_name, chat_id, now))
    return Paired(code)


async def approve(store: Store, vault: Vault, code: str, api_key: str, *, now: float) -> PairingRequest:
    """Link the user behind ``code`` to ``api_key``; raises LookupError for an unknown or expired code."""
    found = await store.get_pairing(pairing.normalise(code))
    if found is None or now - found.created_at >= pairing.TTL_SECONDS:
        raise LookupError("unknown or expired code")
    await store.save_link(Link(found.telegram_user_id, found.username, found.telegram_name, vault.encrypt(api_key)))
    await store.delete_pairing(found.code)
    return found


async def api_key_for(store: Store, vault: Vault, telegram_user_id: int) -> str | None:
    link = await store.get_link(telegram_user_id)
    if link is None or link.kind != "api_key" or link.api_key_enc is None:
        return None
    try:
        return vault.decrypt(link.api_key_enc)
    except ValueError as exc:
        raise KeyUnreadable(str(exc)) from exc


async def unlink(store: Store, *, telegram_user_id: int | None = None, username: str | None = None) -> int:
    """Remove links; returns how many. Their sessions go too, so nothing keeps working."""
    victims = [l for l in await store.list_links()
               if (telegram_user_id is not None and l.telegram_user_id == telegram_user_id)
               or (username is not None and l.username == username)]
    for link in victims:
        await store.delete_sessions_of(link.telegram_user_id)
        await store.delete_device_login(link.telegram_user_id)
    return await store.delete_links(telegram_user_id=telegram_user_id, username=username)


# -- device sign-in ------------------------------------------------------------------------------
class LinkExpired(Exception):
    """The issuer no longer honours the user's sign-in; they must /login again."""


@dataclass(frozen=True)
class Waiting:
    delay: int


@dataclass(frozen=True)
class SignedIn:
    link: Link


@dataclass(frozen=True)
class Ended:
    reason: str  # "denied" | "expired" | "incomplete" | "replaced"


LoginProgress = Waiting | SignedIn | Ended


async def start_login(
    store: Store, vault: Vault, identity: IdentityProvider, *,
    telegram_user_id: int, chat_id: int, username: str, telegram_name: str, now: float,
) -> DeviceLogin:
    """Begin a device authorization; replaces the user's earlier pending login. Raises IdentityUnavailable."""
    auth = await identity.start_device()
    login = DeviceLogin(
        telegram_user_id, chat_id, username, telegram_name, vault.encrypt(auth.device_code), auth.user_code,
        auth.verification_uri, auth.verification_uri_complete, max(1, auth.interval), now + auth.expires_in,
    )
    await store.save_device_login(login)
    return login


async def poll_login(store: Store, vault: Vault, identity: IdentityProvider, login: DeviceLogin, *, now: float) -> LoginProgress:
    """Ask the issuer once. Ends the login (and removes it) on any outcome but waiting."""
    uid = login.telegram_user_id
    current = await store.get_device_login(uid)
    if current is None or current.user_code != login.user_code:
        return Ended("replaced")
    if now >= login.expires_at:
        await store.delete_device_login(uid, user_code=login.user_code)
        return Ended("expired")
    try:
        answer = await identity.poll(vault.decrypt(login.device_code_enc))
    except IdentityUnavailable:
        return Waiting(current.interval_seconds)  # try again at the same pace until the code expires
    if answer.status == "pending":
        return Waiting(current.interval_seconds)
    if answer.status == "slow_down":
        slower = dataclasses.replace(current, interval_seconds=oidc.next_interval(current.interval_seconds, slow_down=True))
        await store.save_device_login(slower)
        return Waiting(slower.interval_seconds)
    await store.delete_device_login(uid, user_code=login.user_code)
    if answer.status in ("denied", "expired"):
        return Ended(answer.status)
    tokens = answer.tokens
    if tokens is None or not tokens.refresh_token or not tokens.subject:
        return Ended("incomplete")
    link = Link(
        uid, tokens.username or login.telegram_name, login.telegram_name, kind="oidc", subject=tokens.subject,
        refresh_token_enc=vault.encrypt(tokens.refresh_token), refreshed_at=now,
    )
    await store.save_link(link)
    return SignedIn(link)


@dataclass(frozen=True)
class LoggedOut:
    had_link: bool
    revocation: str  # "revoked" | "failed" | "unsupported" | "none" (an api_key link, or nothing to revoke)


async def logout(store: Store, vault: Vault, identity: IdentityProvider | None, telegram_user_id: int) -> LoggedOut:
    """Revoke the user's refresh token at the issuer if it can, then delete the link whatever happened."""
    link = await store.get_link(telegram_user_id)
    revocation = "none"
    if link is not None and link.kind == "oidc" and link.refresh_token_enc:
        revocation = "failed"
        if identity is not None:
            try:
                revocation = "revoked" if await identity.revoke(vault.decrypt(link.refresh_token_enc)) else "unsupported"
            except (IdentityRefused, IdentityUnavailable, ValueError):
                revocation = "failed"
    await store.delete_device_login(telegram_user_id)
    if link is not None:
        await store.delete_sessions_of(telegram_user_id)
        await store.delete_links(telegram_user_id=telegram_user_id)
    return LoggedOut(link is not None, revocation)


class Bearer:
    """What a turn sends the endpoint as its bearer: the stored key, or a fresh access token of the issuer.

    An access token is held in memory only, per user, and reused while it has at least a minute left;
    concurrent turns of one user share one refresh.
    """

    def __init__(
        self, store: Store, vault: Vault, identity: IdentityProvider | None = None, *,
        clock: Callable[[], float], lock_factory: Callable[[], AbstractAsyncContextManager] | None = None,
    ) -> None:
        self._store, self._vault, self._identity, self._clock = store, vault, identity, clock
        self._lock_factory = lock_factory
        self._locks: dict[int, AbstractAsyncContextManager] = {}
        self._held: dict[int, tuple[str, str, float]] = {}  # user -> (subject, access token, expires at)

    def forget(self, telegram_user_id: int) -> None:
        self._held.pop(telegram_user_id, None)

    async def for_user(self, telegram_user_id: int) -> str | None:
        """The bearer, or None when the user has no usable link.

        Raises KeyUnreadable, LinkExpired, or IdentityUnavailable (a transient failure; the link is untouched).
        """
        link = await self._store.get_link(telegram_user_id)
        if link is None:
            return None
        if link.kind == "api_key":
            return await api_key_for(self._store, self._vault, telegram_user_id)
        if not link.usable:
            raise LinkExpired()
        held = self._held.get(telegram_user_id)
        if held and held[0] == link.subject and oidc.token_usable(held[2], self._clock()):
            return held[1]
        if self._identity is None:
            raise IdentityUnavailable("sign-in is not enabled")
        lock = self._lock_for(telegram_user_id)
        if lock is None:
            return await self._refresh(telegram_user_id)
        async with lock:
            return await self._refresh(telegram_user_id)

    def _lock_for(self, uid: int):
        if self._lock_factory is None:
            return None
        return self._locks.setdefault(uid, self._lock_factory())

    async def _refresh(self, uid: int) -> str:
        link = await self._store.get_link(uid)  # read again: another turn may have refreshed or expired it
        if link is None or link.kind != "oidc":
            raise LinkExpired()
        if not link.usable or not link.refresh_token_enc:
            raise LinkExpired()
        held = self._held.get(uid)
        if held and held[0] == link.subject and oidc.token_usable(held[2], self._clock()):
            return held[1]
        try:
            token = self._vault.decrypt(link.refresh_token_enc)
        except ValueError as exc:
            raise KeyUnreadable(str(exc)) from exc
        try:
            tokens = await self._identity.refresh(token)
        except IdentityRefused:
            await self._store.expire_link(uid)
            self.forget(uid)
            raise LinkExpired() from None
        now = self._clock()
        stored = self._vault.encrypt(tokens.refresh_token) if tokens.refresh_token and tokens.refresh_token != token else link.refresh_token_enc
        await self._store.update_oidc_tokens(uid, stored, refreshed_at=now)  # before the access token is used
        self._held[uid] = (link.subject or "", tokens.access_token, now + tokens.expires_in)
        return tokens.access_token
