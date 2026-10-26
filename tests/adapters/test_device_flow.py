"""The whole device sign-in against a fake issuer: the handlers, the poller, the runtime and the real HTTP adapter."""

import asyncio
from types import SimpleNamespace

from telegram.ext import CommandHandler

from telegram_bot_gateway.adapters.inbound.telegram import bot as handlers
from telegram_bot_gateway.adapters.inbound.telegram.logins import DeviceLogins
from telegram_bot_gateway.adapters.inbound.telegram.runtime import Runtime
from telegram_bot_gateway.adapters.inbound.telegram.sender import Sender
from telegram_bot_gateway.adapters.outbound.oidc import OidcIdentity
from telegram_bot_gateway.application import linking
from telegram_bot_gateway.application.model import Link
from telegram_bot_gateway.config import Settings
from tests.adapters.fake_issuer import BASE, FakeIssuer
from tests.adapters.test_bot import update
from tests.fakes import FakeBot, FakeStore, FakeVault, ScriptedLlm, settle

# Covers: AS-06, AS-07, FR-LNK-11, FR-LNK-12, FR-LNK-13, FR-LNK-14, FR-LNK-15, FR-LNK-16, FR-LNK-17, FR-LNK-18
# Covers: FR-LNK-19
# Covers: FR-CMD-08, FR-CMD-09, FR-CMD-10, FR-CFG-05, FR-LNK-10, FR-LNK-01


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


class Ticker:
    """Stands in for the poller's sleep: each wait ends when the test says so."""

    def __init__(self):
        self.delays: list[float] = []
        self._go: asyncio.Queue = asyncio.Queue()

    async def sleep(self, delay):
        self.delays.append(delay)
        await self._go.get()

    async def tick(self):
        """End the current wait and let the poller ask the issuer once."""
        self._go.put_nowait(None)
        await asyncio.sleep(0.05)


class Flow:
    def __init__(self, mode="device", issuer=None, store=None):
        self.issuer = issuer or FakeIssuer()
        self.clock, self.ticker = Clock(), Ticker()
        self.bot, self.store = FakeBot(), store or FakeStore()
        self.llm = ScriptedLlm()
        self.cfg = Settings("t", "http://x", "dflt", "d", "k", link_mode=mode, oidc_issuer=BASE, oidc_client_id="bot-client",
                            reaction_delay=60, reactions=False)
        self.vault = FakeVault()
        self.sender = Sender(self.bot, self.store)
        self.identity = OidcIdentity(BASE, "bot-client", client=self.issuer.client())
        self.bearer = linking.Bearer(self.store, self.vault, self.identity, clock=self.clock, lock_factory=asyncio.Lock)
        self.runtime = Runtime(bot=self.bot, store=self.store, llm=self.llm, vault=self.vault, sender=self.sender,
                               config=self.cfg, bearer=self.bearer)
        self.start_logins()
        self.ctx = SimpleNamespace(bot=self.bot, args=[], application=SimpleNamespace(bot_data={"deps": self.deps}))

    def start_logins(self):
        self.logins = DeviceLogins(store=self.store, vault=self.vault, identity=self.identity, bearer=self.bearer,
                                   sender=self.sender, clock=self.clock, sleep=self.ticker.sleep)
        self.deps = handlers.Deps(self.cfg, self.store, self.llm, self.vault, self.sender, self.runtime,
                                  self.identity, self.logins, self.bearer)

    async def say(self, handler, text, *, chat="private", user=5, message_id=10):
        await handler(update(text, chat=chat, user=user, message_id=message_id), self.ctx)

    def replies(self):
        return [m["text"].replace("\\", "") for m in self.bot.sent]

    async def sign_in(self, user=5):
        self.issuer.approved = False
        await self.say(handlers.cmd_login, "/login", user=user)
        await settle(lambda: self.ticker.delays)
        self.issuer.approved = True
        before = len(self.bot.sent)
        await self.ticker.tick()
        await settle(lambda: len(self.bot.sent) > before)

    async def message(self, text, user=5, message_id=20):
        before = len(self.bot.sent)
        await self.say(handlers.on_message, text, user=user, message_id=message_id)
        await settle(lambda: len(self.bot.sent) > before)

    async def close(self):
        await self.logins.shutdown()


async def test_login_poll_message_refresh_and_logout_against_the_issuer():
    f = Flow()
    await f.say(handlers.cmd_login, "/login")
    shown = f.replies()[0]
    assert "WDJB-MJHT" in shown and "10 minutes" in shown and "DEVICE-SECRET" not in shown
    rows = f.bot.sent[0]["reply_markup"].inline_keyboard                 # nothing to copy by hand
    assert rows[0][0].text == "Sign in" and rows[0][0].url == "https://idp.test/realms/r/device?user_code=WDJB-MJHT"
    assert rows[1][0].text == "Copy code" and rows[1][0].copy_text.text == "WDJB-MJHT"
    assert "DEVICE-SECRET" not in shown
    await settle(lambda: f.ticker.delays)
    assert f.ticker.delays == [5]

    await f.ticker.tick()                       # pending: nothing is said
    await settle(lambda: len(f.ticker.delays) == 2)
    f.issuer.slow_down_next = 1
    await f.ticker.tick()                       # slow_down: five seconds slower, and it stays so
    await settle(lambda: len(f.ticker.delays) == 3)
    assert f.ticker.delays[-1] == 10 and (await f.store.get_device_login(5)).interval_seconds == 10
    assert len(f.bot.sent) == 1

    f.issuer.approved = True
    await f.ticker.tick()
    await settle(lambda: len(f.bot.sent) == 2)
    assert "signed in as ann" in f.replies()[1]
    link = f.store.links[5]
    assert (link.kind, link.status, link.subject) == ("oidc", "active", "sub-ann") and link.api_key_enc is None
    assert link.refresh_token_enc.startswith("enc:refresh-") and await f.store.get_device_login(5) is None

    await f.message("hello")                    # AS-06: the endpoint sees the issuer's access token
    assert f.llm.calls[-1]["api_key"].startswith("access-")
    first = f.llm.calls[-1]["api_key"]
    await f.message("again", message_id=21)     # still valid: no second refresh
    refreshes = lambda: [1 for p, form in f.issuer.requests if form.get("grant_type") == "refresh_token"]
    assert f.llm.calls[-1]["api_key"] == first and len(refreshes()) == 1

    f.clock.now += 250                          # less than a minute left: refreshed, and the new refresh token kept
    old_refresh = f.store.links[5].refresh_token_enc
    await f.message("later", message_id=22)
    assert f.llm.calls[-1]["api_key"] != first and f.store.links[5].refresh_token_enc != old_refresh and len(refreshes()) == 2

    await f.say(handlers.cmd_whoami, "/whoami", message_id=23)
    who = f.replies()[-1]
    assert "Link: oidc" in who and "Subject: sub-ann" in who and "Status: active" in who and "refresh" not in who

    token = f.store.links[5].refresh_token_enc.removeprefix("enc:")
    await f.say(handlers.cmd_logout, "/logout", message_id=24)
    assert f.issuer.revoked == [token] and f.store.links == {} and "revoked" in f.replies()[-1]
    await f.close()


async def test_a_disabled_account_is_told_to_sign_in_again_and_nothing_reaches_the_endpoint():
    f = Flow()
    await f.sign_in()
    await f.message("hello")
    assert len(f.llm.calls) == 1
    f.issuer.disabled = True
    f.clock.now += 400
    await f.message("hello?", message_id=21)
    assert "sign-in has expired" in f.replies()[-1] and "/login" in f.replies()[-1]
    assert len(f.llm.calls) == 1
    link = f.store.links[5]
    assert link.status == "expired" and link.refresh_token_enc is None
    await f.message("and now?", message_id=22)   # an expired link is no link at all
    assert len(f.llm.calls) == 1
    await f.say(handlers.cmd_settings, "/settings", message_id=23)
    assert "/login" in f.replies()[-1]
    await f.say(handlers.cmd_whoami, "/whoami", message_id=24)
    assert "Status: expired" in f.replies()[-1]
    await f.close()


async def test_an_issuer_outage_is_a_try_again_and_the_link_stays():
    f = Flow()
    await f.sign_in()
    f.clock.now += 400
    f.issuer.down = True
    await f.message("hello", message_id=21)
    assert "try again" in f.replies()[-1] and f.llm.calls == []
    assert f.store.links[5].status == "active" and f.store.links[5].refresh_token_enc
    f.issuer.down = False
    await f.message("hello", message_id=22)
    assert len(f.llm.calls) == 1
    await f.close()


async def test_login_in_a_group_shows_no_code():
    f = Flow()
    await f.say(handlers.cmd_login, "/login", chat="supergroup")
    assert "privately" in f.replies()[0] and "WDJB" not in f.replies()[0]
    assert f.issuer.requests == [] and f.store.logins == {}
    await f.close()


async def test_login_while_the_issuer_is_unreachable_says_so():
    issuer = FakeIssuer()
    issuer.down = True
    f = Flow(issuer=issuer)
    await f.say(handlers.cmd_login, "/login")
    assert "unavailable" in f.replies()[0] and f.store.logins == {}
    await f.close()


async def test_denial_and_expiry_are_reported_and_a_new_login_replaces_the_pending_one():
    f = Flow()
    await f.say(handlers.cmd_login, "/login")
    await settle(lambda: f.ticker.delays)
    await f.say(handlers.cmd_login, "/login", message_id=11)   # replaces: one pending login per user
    assert f.issuer.requests.count(("/device", {"client_id": "bot-client", "scope": "openid offline_access"})) == 2
    assert len(f.store.logins) == 1
    f.issuer.denied = True
    await f.ticker.tick()
    await settle(lambda: any("denied" in r for r in f.replies()))
    await settle(lambda: not f.store.logins)
    f.issuer.denied, f.issuer.expired_code = False, True
    await f.say(handlers.cmd_login, "/login", message_id=12)
    await settle(lambda: len(f.ticker.delays) >= 3)
    await f.ticker.tick()
    await settle(lambda: any("expired" in r for r in f.replies()))
    assert f.store.links == {}
    await f.close()


async def test_a_pending_login_survives_a_restart():
    f = Flow()
    await f.say(handlers.cmd_login, "/login")
    await f.close()                                # the process stops
    g = Flow(issuer=f.issuer, store=f.store)       # and starts again on the same database
    assert await g.logins.resume() == 1
    await settle(lambda: g.ticker.delays)
    f.issuer.approved = True
    await g.ticker.tick()
    await settle(lambda: g.bot.sent)
    assert "signed in" in g.replies()[0] and g.store.links[5].kind == "oidc"
    await g.close()


async def test_pairing_mode_is_unchanged_and_lists_no_login():
    f = Flow(mode="pairing")
    assert [c.command for c in handlers.menu(f.cfg)] == [c.command for c in handlers.MENU]
    assert "login" not in [c.command for c in handlers.menu(f.cfg)]
    f.deps.logins = f.deps.identity = None
    await f.say(handlers.on_message, "hello")
    assert "Send /start <your username>" in f.replies()[0]
    f.ctx.args = ["ann"]
    await f.say(handlers.cmd_start, "/start ann", message_id=11)
    assert "Your code is" in f.replies()[1]
    await f.close()


async def test_device_mode_invites_to_login_gives_no_code_and_keeps_pairing_links_working():
    f = Flow()
    await f.say(handlers.on_message, "hello")
    f.ctx.args = ["ann"]
    await f.say(handlers.cmd_start, "/start ann", message_id=11)
    assert all("/login" in r for r in f.replies()) and f.store.pairings == {}
    assert not any("code" in r.lower() and "Your code" in r for r in f.replies())
    await f.say(handlers.on_message, "hello", chat="supergroup", message_id=12)  # a group message is not a trigger
    await f.store.save_link(Link(5, "ann", "Ann", "enc:paired-key"))
    await f.message("hello", message_id=13)
    assert f.llm.calls[-1]["api_key"] == "paired-key"            # a pairing link still sends its stored key
    await f.sign_in()                                               # /login replaces it
    await f.message("hello", message_id=14)
    assert f.store.links[5].kind == "oidc" and f.llm.calls[-1]["api_key"].startswith("access-")
    await f.close()


async def test_the_menu_and_the_handlers_offer_login_and_logout_only_in_device_mode():
    f = Flow()
    assert {"login", "logout"} <= {c.command for c in handlers.menu(f.cfg)}

    class App:
        def __init__(self):
            self.commands = set()

        def add_handler(self, h, group=0):
            if isinstance(h, CommandHandler):
                self.commands |= set(h.commands)

        def add_error_handler(self, fn):
            pass

    device, pairing = App(), App()
    handlers.register(device, f.cfg)
    handlers.register(pairing, Settings("t", "http://x", "dflt", "d", "k"))
    assert {"login", "logout"} <= device.commands and not ({"login", "logout"} & pairing.commands)
    await f.close()


async def test_logout_of_a_signed_out_user_and_of_a_pairing_link():
    f = Flow()
    await f.say(handlers.cmd_logout, "/logout")
    assert "not signed in" in f.replies()[0]
    await f.store.save_link(Link(5, "ann", "Ann", "enc:k"))
    await f.say(handlers.cmd_logout, "/logout", message_id=11)
    assert f.store.links == {} and f.issuer.revoked == []
    await f.close()


async def test_an_issuer_without_revocation_still_signs_the_user_out_and_says_so():
    f = Flow(issuer=FakeIssuer(revocation=False))
    await f.sign_in()
    await f.say(handlers.cmd_logout, "/logout", message_id=30)
    assert f.store.links == {} and "no revocation" in f.replies()[-1]
    await f.close()


async def test_the_address_is_sent_as_text_when_telegram_refuses_the_button():
    from telegram.error import BadRequest

    f = Flow()
    f.bot.fail_next.append(BadRequest("Wrong HTTP URL"))
    await f.say(handlers.cmd_login, "/login")
    shown = f.replies()[0]
    assert "idp.test/realms/r/device?user_code=WDJB-MJHT" in shown and "reply_markup" not in f.bot.sent[0]
