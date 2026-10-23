"""The client tools in Telegram: what the endpoint's tool calls do in the chat of one turn."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from telegram import Bot, CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, ReactionTypeEmoji
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError

from telegram_bot_gateway.adapters.inbound.telegram.sender import Sender, Target
from telegram_bot_gateway.application.ports import ActionError, Facts
from telegram_bot_gateway.domain.tools.buttons import Buttons
from telegram_bot_gateway.domain.tools.files import File
from telegram_bot_gateway.domain.tools.images import Image

log = logging.getLogger(__name__)

UNREACHABLE = "Telegram could not be reached."


class TelegramActions:
    def __init__(self, bot: Bot, sender: Sender, target: Target, *, on_react: Callable[[], None] | None = None) -> None:
        self._bot, self._sender, self._target = bot, sender, target
        self._quiet = Target(target.chat_id, target.chat_type, target.thread_id, None)
        self._on_react = on_react

    def facts(self) -> Facts:
        return Facts(self._target.chat_type, self._target.thread_id is not None, self._target.language)

    async def send_file(self, file: File) -> None:
        await self._post(self._bot.send_document, document=InputFile(file.data, filename=file.name), caption=file.caption)

    async def send_image(self, image: Image) -> None:
        photo = image.url if image.url is not None else InputFile(image.data, filename="image")
        await self._post(self._bot.send_photo, photo=photo, caption=image.caption)

    async def send_buttons(self, buttons: Buttons) -> None:
        rows = [
            [InlineKeyboardButton(b.label, url=b.url) if b.url else InlineKeyboardButton(b.label, copy_text=CopyTextButton(b.copy or ""))]
            for b in buttons.buttons
        ]
        await self._guard(self._sender.send(self._quiet, buttons.text, reply_markup=InlineKeyboardMarkup(rows)))

    async def notify(self, text: str) -> None:
        await self._guard(self._sender.send(self._quiet, text, notify=False))

    async def react(self, emoji: str) -> None:
        if self._target.reply_to is None:
            raise ActionError("there is no message to react to")
        await self._guard(
            self._bot.set_message_reaction(
                chat_id=self._target.chat_id, message_id=self._target.reply_to, reaction=[ReactionTypeEmoji(emoji)]
            )
        )
        if self._on_react is not None:
            self._on_react()

    async def _post(self, method: Any, **kwargs: Any) -> None:
        """A media send, into the topic when there is one, with the retries ``Sender`` makes for text."""
        kwargs["chat_id"] = self._target.chat_id
        thread = self._target.thread_id
        for _ in range(3):
            attempt = dict(kwargs, **({"message_thread_id": thread} if thread is not None else {}))
            try:
                await method(**attempt)
                return
            except RetryAfter as exc:
                wait = exc.retry_after.total_seconds() if hasattr(exc.retry_after, "total_seconds") else float(exc.retry_after)
                await asyncio.sleep(wait + 0.5)
            except BadRequest as exc:
                if "thread not found" in str(exc).lower() and thread is not None:
                    thread = None
                    continue
                raise ActionError(str(exc)) from exc
            except Forbidden as exc:
                raise ActionError(str(exc)) from exc
            except TelegramError as exc:
                log.info("a client tool could not reach Telegram", exc_info=True)
                raise ActionError(UNREACHABLE) from exc
        raise ActionError("Telegram kept refusing it")

    @staticmethod
    async def _guard(awaitable: Awaitable[Any]) -> None:
        try:
            await awaitable
        except (BadRequest, Forbidden) as exc:
            raise ActionError(str(exc)) from exc
        except TelegramError as exc:
            log.info("a client tool could not reach Telegram", exc_info=True)
            raise ActionError(UNREACHABLE) from exc
