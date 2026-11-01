"""Starting the bot: wiring, polling or webhook, housekeeping, and the container's health file."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

import httpx
from telegram import Update
from telegram.ext import Application

from telegram_bot_gateway.adapters.inbound.telegram import bot
from telegram_bot_gateway.adapters.inbound.telegram.inbox import InboxPoller, TelegramMessenger
from telegram_bot_gateway.adapters.inbound.telegram.logins import DeviceLogins
from telegram_bot_gateway.adapters.inbound.telegram.runtime import Runtime
from telegram_bot_gateway.adapters.inbound.telegram.sender import Sender
from telegram_bot_gateway.adapters.outbound.crypto import Vault
from telegram_bot_gateway.adapters.outbound.inbox import HttpInbox, ServiceToken
from telegram_bot_gateway.adapters.outbound.oidc import IssuerMisconfigured, OidcIdentity
from telegram_bot_gateway.adapters.outbound.openai import OpenAIChat
from telegram_bot_gateway.adapters.outbound.postgres import PostgresStore
from telegram_bot_gateway.application import linking
from telegram_bot_gateway.application.ports import IdentityUnavailable
from telegram_bot_gateway.config import ConfigError, Settings
from telegram_bot_gateway.domain import pairing

log = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 30
HOUSEKEEPING_SECONDS = 24 * 3600


def build_application(config: Settings, post_init, post_stop, post_shutdown) -> Application:
    """The Telegram application, with timeouts and a proxy suited to a slow or filtered route."""
    builder = (
        Application.builder().token(config.bot_token).concurrent_updates(True)
        .connect_timeout(config.telegram_connect_timeout).read_timeout(config.telegram_read_timeout)
        .write_timeout(config.telegram_read_timeout).pool_timeout(config.telegram_connect_timeout)
        .get_updates_connect_timeout(config.telegram_connect_timeout).get_updates_read_timeout(config.telegram_read_timeout)
        .post_init(post_init).post_stop(post_stop).post_shutdown(post_shutdown)
    )
    if config.telegram_proxy:
        builder = builder.proxy(config.telegram_proxy).get_updates_proxy(config.telegram_proxy)
    return builder.build()


def serve(config: Settings) -> None:
    async def post_init(app: Application) -> None:
        store = await PostgresStore.open(config.database_url, config.migrations_dir)
        llm = OpenAIChat(config.openai_base_url, config.request_timeout)
        vault = Vault(config.creds_key)
        sender = Sender(app.bot, store)
        identity = logins = None
        if config.device_mode:
            identity = OidcIdentity(config.oidc_issuer, config.oidc_client_id, config.oidc_client_secret, config.oidc_scope)
            try:
                await identity.ensure_device_flow()
            except IssuerMisconfigured as exc:
                raise ConfigError(str(exc)) from None
            except IdentityUnavailable as exc:
                log.warning("the issuer cannot be reached yet; /login will say so until it can (%s)", exc)
        bearer = linking.Bearer(store, vault, identity, clock=time.time, lock_factory=asyncio.Lock)
        runtime = Runtime(bot=app.bot, store=store, llm=llm, vault=vault, sender=sender, config=config, bearer=bearer)
        if identity is not None:
            logins = DeviceLogins(store=store, vault=vault, identity=identity, bearer=bearer, sender=sender)
            log.info("resuming %s sign-in(s) in progress", await logins.resume())
        inbox = None
        if config.inbox_enabled:
            http = httpx.AsyncClient(timeout=15)
            token = ServiceToken(
                config.inbox_token, token_url=config.inbox_token_url, client_id=config.inbox_client_id,
                client_secret=config.inbox_client_secret, client=http,
            )
            inbox = HttpInbox(config.inbox_url, token, http)
            poller = InboxPoller(
                inbox, store, TelegramMessenger(sender), interval=config.inbox_poll_interval,
                limit=config.inbox_lease_limit, lease_seconds=config.inbox_lease_seconds,
            )
            poller.start()
            app.bot_data["inbox_poller"] = poller
            log.info("message inbox enabled, polling every %ss", config.inbox_poll_interval)
        app.bot_data["deps"] = bot.Deps(config, store, llm, vault, sender, runtime, identity, logins, bearer, inbox)
        await app.bot.set_my_commands(bot.menu(config))
        app.bot_data["heartbeat"] = asyncio.create_task(_heartbeat(config.health_file, app.bot))
        app.bot_data["housekeeping"] = asyncio.create_task(_housekeeping(store, config.message_text_days))
        log.info("ready as @%s", app.bot.username)

    async def post_stop(app: Application) -> None:
        poller = app.bot_data.get("inbox_poller")
        if poller:
            await poller.stop()
        deps = app.bot_data.get("deps")
        if deps:
            await deps.runtime.shutdown()
            if deps.logins:
                await deps.logins.shutdown()

    async def post_shutdown(app: Application) -> None:
        deps = app.bot_data.get("deps")
        if deps:
            await deps.llm.close()
            if deps.identity:
                await deps.identity.close()
            if deps.inbox:
                await deps.inbox.close()
            await deps.store.close()

    app = build_application(config, post_init, post_stop, post_shutdown)
    bot.register(app, config)
    allowed = [Update.MESSAGE, Update.CALLBACK_QUERY]
    if config.webhook_url:
        app.run_webhook(
            listen="0.0.0.0", port=config.webhook_port, webhook_url=config.webhook_url,
            secret_token=config.webhook_secret, drop_pending_updates=True, allowed_updates=allowed,
        )
    else:
        app.run_polling(drop_pending_updates=True, allowed_updates=allowed)


async def _heartbeat(path: str, bot: Any) -> None:
    """Write the health file only while Telegram answers, so a bot that cannot reach it stops looking healthy."""
    while True:
        try:
            await asyncio.wait_for(bot.get_me(), 20)
            Path(path).write_text(str(time.time()))
        except OSError:
            log.warning("cannot write the health file %s", path)
        except Exception as exc:  # unreachable, refused, timed out: leave the file to age
            log.warning("Telegram did not answer the health check (%s)", exc.__class__.__name__)
        await asyncio.sleep(HEARTBEAT_SECONDS)


async def _housekeeping(store: Any, text_days: int) -> None:
    """Forget what is no longer needed: message texts past their days and pairing codes past their hour."""
    while True:
        try:
            texts = await store.prune_texts(older_than_days=text_days)
            codes = await store.prune_pairings(before=time.time() - pairing.TTL_SECONDS)
            await store.prune_device_logins(before=time.time())
            await store.prune_inbox_deliveries(older_than_days=text_days)
            log.info("housekeeping removed %s message text(s) and %s expired code(s)", texts, codes)
        except Exception:
            log.exception("housekeeping failed")
        await asyncio.sleep(HOUSEKEEPING_SECONDS)
