"""The inbox on Telegram: delivering what the service leases, and the poll loop that does it."""

from __future__ import annotations

import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError

from telegram_bot_gateway.adapters.inbound.telegram.sender import Sender, Target, _seconds
from telegram_bot_gateway.application import inbox as delivery
from telegram_bot_gateway.application.ports import DeliveryFailed, Inbox, InboxError, Store
from telegram_bot_gateway.domain import inbox as model
from telegram_bot_gateway.domain.formatting import shorten_card

log = logging.getLogger(__name__)

EDIT_LIMIT = 4000
BACKOFF_SECONDS = 30
BLOCKED_RETRY_SECONDS = 300
GONE_REASONS = ("message to edit not found", "message can't be edited", "message is not modified")


def keyboard(buttons: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """Up to three buttons share a row; more are stacked, one per row."""
    keys = [InlineKeyboardButton(label, callback_data=data) for label, data in buttons]
    return InlineKeyboardMarkup([keys] if len(keys) <= 3 else [[key] for key in keys])


class TelegramMessenger:
    def __init__(self, sender: Sender) -> None:
        self._sender = sender

    @staticmethod
    def _target(chat_id: int) -> Target:
        return Target(chat_id, "private" if chat_id > 0 else "group")

    async def send_text(self, chat_id: int, text: str) -> str:
        ids = await self._guard(self._sender.send(self._target(chat_id), text))
        return model.format_ref(chat_id, ids[0])

    async def send_buttons(self, chat_id: int, text: str, buttons: list[tuple[str, str]]) -> str:
        markup = keyboard(buttons) if buttons else None
        ids = await self._guard(self._sender.send(self._target(chat_id), shorten_card(text), reply_markup=markup))
        return model.format_ref(chat_id, ids[-1])

    async def replace(self, chat_id: int, message_id: int, text: str) -> None:
        text = text if len(text) <= EDIT_LIMIT else text[: EDIT_LIMIT - 1] + "…"
        try:
            await self._guard(self._sender.edit(chat_id, message_id, text))
        except DeliveryFailed as exc:
            if any(reason in exc.reason.lower() for reason in GONE_REASONS):
                log.info("the message to update is gone; nothing to edit")
                return
            raise

    @staticmethod
    async def _guard(call):
        try:
            return await call
        except RetryAfter as exc:
            raise DeliveryFailed("Telegram asked to slow down", int(_seconds(exc.retry_after)) + 1) from None
        except Forbidden as exc:
            raise DeliveryFailed(f"Telegram refused: {exc.message}", BLOCKED_RETRY_SECONDS) from None
        except BadRequest as exc:
            raise DeliveryFailed(f"Telegram rejected the message: {exc.message}", BLOCKED_RETRY_SECONDS) from None
        except (NetworkError, TelegramError) as exc:
            raise DeliveryFailed(f"Telegram failed ({exc.__class__.__name__})", BACKOFF_SECONDS) from None


class InboxPoller:
    """Leases items on an interval and delivers each. A failing service is waited out, never fatal."""

    def __init__(self, inbox: Inbox, store: Store, messenger: Messenger, *, interval: float, limit: int, lease_seconds: int) -> None:
        self._inbox, self._store, self._messenger = inbox, store, messenger
        self._interval, self._limit, self._lease = interval, limit, lease_seconds
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def poll_once(self) -> int:
        """Lease and deliver one batch; returns how many items were leased."""
        items = await self._inbox.lease(self._limit, self._lease)
        for raw in items:
            await delivery.deliver(raw, inbox=self._inbox, store=self._store, messenger=self._messenger)
        return len(items)

    async def _run(self) -> None:
        failures = 0
        while True:
            try:
                await self.poll_once()
                failures = 0
            except InboxError as exc:
                failures += 1
                if failures == 1 or failures % 20 == 0:
                    log.warning("the message inbox is not answering (%s); still trying", exc)
            except Exception:
                log.exception("the inbox poll failed")
            await asyncio.sleep(self._interval)
