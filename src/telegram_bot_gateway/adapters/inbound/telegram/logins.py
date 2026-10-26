"""Pending device sign-ins: the task that polls the issuer for each and tells the user how it ended."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from telegram import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup

from telegram_bot_gateway.adapters.inbound.telegram.sender import Sender, Target
from telegram_bot_gateway.application import linking
from telegram_bot_gateway.application.model import DeviceLogin
from telegram_bot_gateway.application.ports import IdentityProvider, Store, Vault
from telegram_bot_gateway.domain import oidc

log = logging.getLogger(__name__)

SIGNED_IN = "You are signed in as {name}. Send me a message to begin."
ENDINGS = {
    "denied": "The sign-in was denied.",
    "expired": "The sign-in code expired. Send /login to start again.",
    "incomplete": "The sign-in service did not give me what I need to keep you signed in. Ask the operator to check its configuration.",
}


def _minutes(login: DeviceLogin, now: float) -> str:
    minutes = oidc.minutes_left(login.expires_at, now)
    return f"{minutes} minute{'' if minutes == 1 else 's'}"


def sign_in_card(login: DeviceLogin, now: float) -> tuple[str, InlineKeyboardMarkup]:
    """The sign-in message with a button that opens the page and one that copies the code, so nothing is typed."""
    step = ("Tap Sign in and approve in the page that opens." if login.verification_uri_complete
            else "Tap Sign in, then enter this code in the page that opens.")
    text = (f"{step}\nYour code: `{login.user_code}`\nIt expires in {_minutes(login, now)}. "
            "I will tell you when you are signed in.")
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("Sign in", url=login.verification_uri_complete or login.verification_uri)],
        [InlineKeyboardButton("Copy code", copy_text=CopyTextButton(login.user_code))],
    ])
    return text, markup


def instructions(login: DeviceLogin, now: float) -> str:
    """The same message as plain text with the address in it, for when Telegram refuses the button."""
    where = login.verification_uri_complete or login.verification_uri
    code = "" if login.verification_uri_complete else f" and enter the code `{login.user_code}`"
    shown = f"Code: `{login.user_code}`\n" if login.verification_uri_complete else ""
    return (f"To sign in, open {where}{code}.\n{shown}It expires in {_minutes(login, now)}. "
            "I will tell you when you are signed in.")


class DeviceLogins:
    def __init__(
        self, *, store: Store, vault: Vault, identity: IdentityProvider, bearer: linking.Bearer, sender: Sender,
        clock: Callable[[], float] = time.time, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._store, self._vault, self._identity, self._bearer = store, vault, identity, bearer
        self._sender, self._clock, self._sleep = sender, clock, sleep
        self._tasks: dict[int, asyncio.Task] = {}

    async def begin(self, *, telegram_user_id: int, chat_id: int, username: str, telegram_name: str) -> DeviceLogin:
        """Start a login (replacing a pending one) and watch it. Raises IdentityUnavailable."""
        login = await linking.start_login(
            self._store, self._vault, self._identity, telegram_user_id=telegram_user_id, chat_id=chat_id,
            username=username, telegram_name=telegram_name, now=self._clock(),
        )
        self._watch(login)
        return login

    async def resume(self) -> int:
        """Watch every login stored before a restart."""
        logins = await self._store.list_device_logins()
        for login in logins:
            self._watch(login)
        return len(logins)

    def now(self) -> float:
        return self._clock()

    def cancel(self, telegram_user_id: int) -> None:
        task = self._tasks.pop(telegram_user_id, None)
        if task is not None:
            task.cancel()

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _watch(self, login: DeviceLogin) -> None:
        self.cancel(login.telegram_user_id)
        task = asyncio.create_task(self._poll(login))
        self._tasks[login.telegram_user_id] = task
        task.add_done_callback(lambda t: self._tasks.get(login.telegram_user_id) is t and self._tasks.pop(login.telegram_user_id, None))

    async def _poll(self, login: DeviceLogin) -> None:
        target = Target(login.chat_id, "private")
        delay = login.interval_seconds
        while True:
            await self._sleep(delay)
            try:
                progress = await linking.poll_login(self._store, self._vault, self._identity, login, now=self._clock())
            except Exception as exc:  # never log the reply: it may hold a token
                log.warning("polling a sign-in failed (%s)", exc.__class__.__name__)
                if self._clock() >= login.expires_at:
                    return
                continue
            if isinstance(progress, linking.Waiting):
                delay = progress.delay
                continue
            if isinstance(progress, linking.SignedIn):
                self._bearer.forget(login.telegram_user_id)
                text = SIGNED_IN.format(name=progress.link.username)
            elif progress.reason == "replaced":
                return
            else:
                text = ENDINGS[progress.reason]
            try:
                await self._sender.send(target, text)
            except Exception as exc:
                log.warning("could not tell a user how their sign-in ended (%s)", exc.__class__.__name__)
            return
