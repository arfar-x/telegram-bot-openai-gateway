"""Delivering message-inbox items, and turning a button press into words for the person who pressed."""

from __future__ import annotations

import logging

from telegram_bot_gateway.application.ports import DeliveryFailed, Inbox, InboxError, Messenger, Store
from telegram_bot_gateway.domain import inbox as model

log = logging.getLogger(__name__)

PRESS_TEXTS = {
    "decided": "Decided.",
    "forbidden": "You are not allowed to decide this.",
    "already_decided": "Already decided.",
    "gone": "This no longer exists.",
    "unauthorized": "Your sign-in is no longer valid. Sign in again.",
    "failed": "Could not record your decision. Try again in a moment.",
}
UNDELIVERABLE_RETRY = 3600


async def deliver(raw: object, *, inbox: Inbox, store: Store, messenger: Messenger) -> None:
    """Deliver one leased item and acknowledge it, or release it with a delay.

    Delivery is at least once on the service's side: an item already delivered is acknowledged under the ref it
    got, not sent again. Every item is independent; nothing is shared between two approvals in one chat.
    """
    item = model.parse_item(raw)
    if item is None:
        log.warning("ignoring an inbox item this bot cannot read")
        return
    try:
        ref = await store.inbox_delivered(item.id)
        if ref is None:
            ref = await _send(item, messenger)
            target = model.parse_ref(ref)
            if item.reply and item.kind != "update" and target is not None:
                await store.save_inbox_reply(target[0], target[1], item.reply)
            await store.save_inbox_delivered(item.id, ref)
    except DeliveryFailed as exc:
        log.warning("inbox item %s not delivered: %s", item.id, exc.reason)
        await _release(inbox, item.id, exc)
        return
    try:
        await inbox.ack(item.id, ref)
    except InboxError as exc:
        log.warning("inbox item %s delivered but not acknowledged yet (%s)", item.id, exc)


async def _release(inbox: Inbox, item_id: str, exc: DeliveryFailed) -> None:
    try:
        await inbox.release(item_id, exc.retry_in, exc.reason)
    except InboxError as err:
        log.warning("inbox item %s not released (%s); it will be offered again when its lease ends", item_id, err)


async def _send(item: model.InboxItem, messenger: Messenger) -> str:
    chat_id = model.parse_address(item.address)
    if chat_id is None:
        raise DeliveryFailed("the address is not a chat id", UNDELIVERABLE_RETRY)
    if item.kind == "text":
        return await messenger.send_text(chat_id, item.body)
    if item.kind in ("approval", "question"):
        keys: list[tuple[str, str]] = []
        for button in item.buttons:
            data = model.callback_data(button.id)
            if data is None:
                raise DeliveryFailed("a button id is too long for a Telegram button", UNDELIVERABLE_RETRY)
            keys.append((button.label, data))
        return await messenger.send_buttons(chat_id, item.body, keys)
    target = model.parse_ref(item.external_ref)
    if target is None:
        raise DeliveryFailed("the message to update is not named by a chat and message id", UNDELIVERABLE_RETRY)
    await messenger.replace(target[0], target[1], item.body)
    return item.external_ref
