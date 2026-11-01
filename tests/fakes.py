"""In-memory stand-ins for the store, the endpoint and Telegram's bot object."""

from __future__ import annotations

import asyncio
import copy
import dataclasses
from types import SimpleNamespace
from typing import Any

from telegram_bot_gateway.application.model import DeviceLogin, Link, PairingRequest, Session
from telegram_bot_gateway.application.ports import (
    ActionError, DeviceAuthorization, DevicePoll, Facts, IdentityRefused, IdentityUnavailable, Tokens,
)


class FakeVault:
    def encrypt(self, plaintext: str) -> str:
        return "enc:" + plaintext

    def decrypt(self, ciphertext: str) -> str:
        return ciphertext.removeprefix("enc:")


class FakeStore:
    def __init__(self) -> None:
        self.links: dict[int, Link] = {}
        self.pairings: dict[str, PairingRequest] = {}
        self.sessions: dict[str, Session] = {}
        self.texts: dict[tuple[int, int], str] = {}
        self.logins: dict[int, DeviceLogin] = {}
        self.deliveries: dict[str, str] = {}
        self.reply_refs: dict[tuple[int, int], str] = {}

    async def get_link(self, uid): return self.links.get(uid)
    async def save_link(self, link): self.links[link.telegram_user_id] = link

    async def delete_links(self, *, telegram_user_id=None, username=None):
        gone = [u for u, l in self.links.items() if u == telegram_user_id or l.username == username]
        for u in gone:
            del self.links[u]
        return len(gone)

    async def list_links(self): return list(self.links.values())
    async def update_oidc_tokens(self, uid, refresh_token_enc, *, refreshed_at):
        link = self.links.get(uid)
        if link is None or link.kind != "oidc" or link.status != "active":
            return False
        self.links[uid] = dataclasses.replace(link, refresh_token_enc=refresh_token_enc, refreshed_at=refreshed_at)
        return True

    async def expire_link(self, uid):
        link = self.links.get(uid)
        if link is None or link.kind != "oidc":
            return False
        self.links[uid] = dataclasses.replace(link, status="expired", refresh_token_enc=None)
        return True

    async def save_device_login(self, login): self.logins[login.telegram_user_id] = login
    async def get_device_login(self, uid): return self.logins.get(uid)
    async def list_device_logins(self): return list(self.logins.values())

    async def delete_device_login(self, uid, *, user_code=None):
        if uid in self.logins and (user_code is None or self.logins[uid].user_code == user_code):
            del self.logins[uid]

    async def prune_device_logins(self, *, before):
        gone = [u for u, l in self.logins.items() if l.expires_at < before]
        for u in gone:
            del self.logins[u]
        return len(gone)

    async def create_pairing(self, r): self.pairings[r.code] = r
    async def get_pairing(self, code): return self.pairings.get(code)
    async def pairings_of(self, uid): return [p for p in self.pairings.values() if p.telegram_user_id == uid]
    async def list_pairings(self, *, since): return [p for p in self.pairings.values() if p.created_at >= since]
    async def delete_pairing(self, code): self.pairings.pop(code, None)

    async def prune_pairings(self, *, before):
        gone = [c for c, p in self.pairings.items() if p.created_at < before]
        for c in gone:
            del self.pairings[c]
        return len(gone)
    async def load_session(self, key): return copy.deepcopy(self.sessions.get(key))
    async def save_session(self, s): self.sessions[s.key] = copy.deepcopy(s)
    async def delete_session(self, key): self.sessions.pop(key, None)

    async def delete_sessions_of(self, uid):
        for k in [k for k, s in self.sessions.items() if s.telegram_user_id == uid]:
            del self.sessions[k]

    async def find_pending(self, chat_id, card_message_id):
        for s in self.sessions.values():
            p = s.pending
            if p and p.chat_id == chat_id and p.card_message_id == card_message_id:
                return copy.deepcopy(s)
        return None

    async def save_text(self, chat_id, message_id, text): self.texts[(chat_id, message_id)] = text
    async def get_text(self, chat_id, message_id): return self.texts.get((chat_id, message_id))
    async def prune_texts(self, *, older_than_days): return 0

    async def inbox_delivered(self, item_id): return self.deliveries.get(item_id)
    async def save_inbox_delivered(self, item_id, external_ref): self.deliveries.setdefault(item_id, external_ref)
    async def save_inbox_reply(self, chat_id, message_id, ref): self.reply_refs[(chat_id, message_id)] = ref
    async def inbox_reply_ref(self, chat_id, message_id): return self.reply_refs.get((chat_id, message_id))
    async def prune_inbox_deliveries(self, *, older_than_days): return 0


class FakeIdentity:
    """An issuer with a script: ``polls`` are the answers to successive polls (a status, a DevicePoll or an Exception);
    ``refreshes`` likewise for refresh (a Tokens or an Exception). Records what it was asked."""

    def __init__(self, *, polls=(), refreshes=(), revokes=(True,), interval=5, expires_in=600) -> None:
        self.polls, self.refreshes, self.revokes = list(polls), list(refreshes), list(revokes)
        self.interval, self.expires_in = interval, expires_in
        self.started = 0
        self.polled: list[str] = []
        self.refreshed: list[str] = []
        self.revoked: list[str] = []
        self.unavailable = False

    async def start_device(self):
        if self.unavailable:
            raise IdentityUnavailable("down")
        self.started += 1
        return DeviceAuthorization(f"dev-{self.started}", "WDJB-MJHT", "https://idp.test/device",
                                   "https://idp.test/device?user_code=WDJB-MJHT", self.interval, self.expires_in)

    async def poll(self, device_code):
        self.polled.append(device_code)
        step = self.polls.pop(0) if self.polls else "pending"
        if isinstance(step, Exception):
            raise step
        return step if isinstance(step, DevicePoll) else DevicePoll(step)

    async def refresh(self, refresh_token):
        self.refreshed.append(refresh_token)
        step = self.refreshes.pop(0) if self.refreshes else Tokens(f"access-{len(self.refreshed)}", 300)
        if isinstance(step, Exception):
            raise step
        return step

    async def revoke(self, refresh_token):
        self.revoked.append(refresh_token)
        step = self.revokes.pop(0) if self.revokes else True
        if isinstance(step, Exception):
            raise step
        return step


def approved(*, refresh="rt-1", subject="sub-1", username="ann", access="at-0", expires_in=300) -> DevicePoll:
    return DevicePoll("approved", Tokens(access, expires_in, refresh, subject, username))


class ScriptedLlm:
    """Answers from a script: each item is a message dict, an Exception, or an async callable."""

    def __init__(self, *script: Any) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    async def chat(self, api_key, model, messages, params, tools, on_reasoning=None):
        system = messages[0]["content"] if messages and messages[0]["role"] == "system" else None
        body = messages[1:] if system is not None else messages
        self.calls.append({"api_key": api_key, "model": model, "messages": copy.deepcopy(body), "system": system,
                           "params": params, "tools": tools})
        step = self.script.pop(0) if self.script else {"role": "assistant", "content": "ok"}
        if callable(step):
            step = await step()
        if isinstance(step, Exception):
            raise step
        return step

    async def models(self, api_key):
        return ["agent-a", "agent-b"]


def say(text: str) -> dict[str, Any]:
    return {"role": "assistant", "content": text}


def call(name: str, arguments: str, id: str = "call_1") -> dict[str, Any]:
    return {"role": "assistant", "content": None, "tool_calls": [{"id": id, "type": "function", "function": {"name": name, "arguments": arguments}}]}


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.edits: list[dict[str, Any]] = []
        self.actions: list[dict[str, Any]] = []
        self.reactions: list[tuple[int, list]] = []
        self.deleted: list[tuple[int, int]] = []
        self.documents: list[dict[str, Any]] = []
        self.photos: list[dict[str, Any]] = []
        self.fail_next: list[Exception] = []
        self._ids = iter(range(100, 10_000))
        self.id = 999
        self.username = "agentbot"

    async def send_message(self, **kw):
        if self.fail_next:
            raise self.fail_next.pop(0)
        self.sent.append(kw)
        return SimpleNamespace(message_id=next(self._ids))

    async def edit_message_text(self, **kw):
        self.edits.append(kw)

    async def send_document(self, **kw):
        if self.fail_next:
            raise self.fail_next.pop(0)
        self.documents.append(kw)
        return SimpleNamespace(message_id=next(self._ids))

    async def send_photo(self, **kw):
        if self.fail_next:
            raise self.fail_next.pop(0)
        self.photos.append(kw)
        return SimpleNamespace(message_id=next(self._ids))

    async def send_chat_action(self, **kw):
        self.actions.append(kw)

    async def set_message_reaction(self, chat_id, message_id, reaction):
        self.reactions.append((message_id, [r.emoji for r in reaction]))

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))


class FakeActions:
    """Records what the client tools did; ``fail`` makes the next action refuse with that reason."""

    def __init__(self, facts: Facts | None = None) -> None:
        self.done: list[tuple[str, Any]] = []
        self.fail: str | None = None
        self._facts = facts or Facts("private", False, "en")

    def _do(self, what: str, arg: Any) -> None:
        if self.fail:
            raise ActionError(self.fail)
        self.done.append((what, arg))

    async def send_file(self, file): self._do("file", file)
    async def send_image(self, image): self._do("image", image)
    async def send_buttons(self, buttons): self._do("buttons", buttons)
    async def notify(self, text): self._do("notify", text)
    async def react(self, emoji): self._do("react", emoji)
    def facts(self): return self._facts


async def settle(predicate, timeout: float = 3.0) -> None:
    """Wait until ``predicate()`` is true."""
    for _ in range(int(timeout / 0.01)):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached in time")
