"""The message inbox: what an item is, and how its message and buttons are named. No I/O."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CALLBACK_PREFIX = "i:"
CALLBACK_LIMIT = 64  # bytes, Telegram's limit on callback_data
KINDS = ("text", "approval", "question", "update")


@dataclass(frozen=True)
class InboxButton:
    id: str
    label: str


@dataclass(frozen=True)
class InboxItem:
    id: str
    kind: str
    body: str
    address: str
    external_ref: str = ""
    buttons: tuple[InboxButton, ...] = ()
    reply: str = ""


def parse_item(raw: Any) -> InboxItem | None:
    """An item from the service's JSON, or None when it is not one this bot can deliver."""
    if not isinstance(raw, dict) or not raw.get("id") or raw.get("kind") not in KINDS:
        return None
    channel = raw.get("channel")
    address = str(channel.get("address", "")) if isinstance(channel, dict) else ""
    buttons = tuple(
        InboxButton(str(b["id"]), str(b.get("label") or b["id"]))
        for b in raw.get("buttons") or () if isinstance(b, dict) and b.get("id")
    )
    return InboxItem(str(raw["id"]), raw["kind"], str(raw.get("body") or ""), address, str(raw.get("external_ref") or ""), buttons, str(raw.get("reply") or ""))


def format_ref(chat_id: int, message_id: int) -> str:
    return f"{chat_id}:{message_id}"


def parse_ref(ref: str) -> tuple[int, int] | None:
    """``"<chat_id>:<message_id>"`` as numbers, or None."""
    chat, _, message = ref.rpartition(":")
    try:
        return int(chat), int(message)
    except ValueError:
        return None


def parse_address(address: str) -> int | None:
    try:
        return int(address)
    except ValueError:
        return None


def callback_data(button_id: str) -> str | None:
    """The callback data of a button, or None when it would not fit Telegram's limit."""
    data = CALLBACK_PREFIX + button_id
    return data if len(data.encode()) <= CALLBACK_LIMIT else None
