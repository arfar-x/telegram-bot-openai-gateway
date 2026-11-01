import asyncio
import logging
from types import SimpleNamespace

import pytest
from telegram.error import Forbidden, RetryAfter
from telegram.ext import Application, CommandHandler

from telegram_bot_gateway.adapters.inbound.telegram import bot as handlers
from telegram_bot_gateway.adapters.inbound.telegram.inbox import InboxPoller, TelegramMessenger
from telegram_bot_gateway.adapters.inbound.telegram.sender import Sender
from telegram_bot_gateway.application.model import Link
from telegram_bot_gateway.application.ports import DeliveryFailed, InboxError, Press
from telegram_bot_gateway.config import ConfigError, Settings
from tests.adapters.test_bot import Env as BotEnv
from tests.adapters.test_bot import Query, update
from telegram_bot_gateway.application.ports import ReplyResult
from tests.fakes import FakeBot, FakeStore, FakeVault

# Covers: FR-INX-10, FR-INX-11, FR-INX-12, FR-INX-01, FR-INX-02, FR-INX-03, FR-INX-04, FR-INX-05, FR-INX-06, FR-INX-07, FR-INX-08, FR-INX-09, FR-CFG-06


def settings(**env):
    base = {"BOT_TOKEN": "t", "OPENAI_BASE_URL": "http://x", "DEFAULT_MODEL": "m", "DATABASE_URL": "d", "CREDS_KEY": "k"}
    return Settings.from_env({**base, **env})


class ScriptedInbox:
    def __init__(self, *batches):
        self.batches, self.acks, self.releases, self.presses, self.links = list(batches), [], [], [], []
        self.press_result, self.link_result = Press("decided"), True
        self.replies, self.reply_result = [], ReplyResult(True)

    async def lease(self, limit, lease_seconds):
        batch = self.batches.pop(0) if self.batches else []
        if isinstance(batch, Exception):
            raise batch
        return batch

    async def ack(self, item_id, external_ref): self.acks.append((item_id, external_ref))
    async def release(self, item_id, retry_in, error): self.releases.append((item_id, retry_in, error))

    async def press(self, bearer, button):
        self.presses.append((bearer, button))
        return self.press_result

    async def reply(self, bearer, ref, text):
        self.replies.append((bearer, ref, text))
        return self.reply_result

    async def link(self, code, address, label):
        self.links.append((code, address, label))
        if isinstance(self.link_result, Exception):
            raise self.link_result
        return self.link_result


def raw(id, kind="text", body="hi", address="55", buttons=(), ref=""):
    return {"id": id, "kind": kind, "body": body, "external_ref": ref, "buttons": list(buttons), "channel": {"address": address}}


# -- configuration and switch --------------------------------------------------------------------
def test_the_inbox_is_off_unless_its_url_is_set_and_then_needs_a_credential():
    off = settings()
    assert not off.inbox_enabled and off.inbox_poll_interval == 5.0
    on = settings(INBOX_URL="http://svc/api/v1/", INBOX_TOKEN="t", INBOX_POLL_INTERVAL="2", INBOX_LEASE_LIMIT="3", INBOX_LEASE_SECONDS="9")
    assert on.inbox_enabled and on.inbox_url == "http://svc/api/v1" and (on.inbox_poll_interval, on.inbox_lease_limit, on.inbox_lease_seconds) == (2.0, 3, 9)
    assert settings(INBOX_URL="http://x", INBOX_TOKEN_URL="http://t", INBOX_CLIENT_ID="c", INBOX_CLIENT_SECRET="s").inbox_enabled
    with pytest.raises(ConfigError, match="INBOX_TOKEN"):
        settings(INBOX_URL="http://x")


def _commands(app):
    return {c for h in app.handlers[0] if isinstance(h, CommandHandler) for c in h.commands}


def test_without_the_inbox_there_is_no_link_command_and_with_it_there_is():
    for config, expected in ((settings(), False), (settings(INBOX_URL="http://x", INBOX_TOKEN="t"), True)):
        app = Application.builder().token("1:abc").build()
        handlers.register(app, config)
        assert ("link" in _commands(app)) is expected
        assert any(c.command == "link" for c in handlers.menu(config)) is expected


# -- the messenger -------------------------------------------------------------------------------
def messenger():
    bot, store = FakeBot(), FakeStore()
    return bot, TelegramMessenger(Sender(bot, store))


async def test_text_is_sent_in_pieces_and_named_by_its_first_message():
    bot, m = messenger()
    ref = await m.send_text(55, "word " * 2000)
    assert len(bot.sent) > 1 and ref == f"55:{100}"


async def test_buttons_are_attached_to_the_message_and_carry_their_callback_data():
    bot, m = messenger()
    ref = await m.send_buttons(-100, "Run it?", [("Approve", "i:a"), ("Reject", "i:b")])
    rows = bot.sent[0]["reply_markup"].inline_keyboard
    assert [(k.text, k.callback_data) for k in rows[0]] == [("Approve", "i:a"), ("Reject", "i:b")] and ref == "-100:100"


async def test_replacing_edits_the_named_message_without_a_keyboard():
    bot, m = messenger()
    await m.replace(55, 42, "Approved")
    assert bot.edits[0]["chat_id"] == 55 and bot.edits[0]["message_id"] == 42 and bot.edits[0]["reply_markup"] is None


async def test_telegram_asking_to_wait_becomes_a_release_delay():
    class Slow:
        async def send(self, *a, **k):
            raise RetryAfter(12)
    with pytest.raises(DeliveryFailed) as caught:
        await TelegramMessenger(Slow()).send_text(55, "x")
    assert caught.value.retry_in == 13
    bot, m = messenger()
    bot.fail_next = [Forbidden("bot was blocked by the user")]
    with pytest.raises(DeliveryFailed, match="blocked"):
        await m.send_text(55, "x")


# -- the poller ----------------------------------------------------------------------------------
async def test_the_poller_delivers_acknowledges_and_survives_a_failing_service():
    bot, m = messenger()
    store = FakeStore()
    inbox = ScriptedInbox(InboxError("down"), [raw("1"), raw("2", "approval", "?", buttons=[{"id": "b", "label": "Go"}])])
    poller = InboxPoller(inbox, store, m, interval=0.01, limit=10, lease_seconds=60)
    poller.start()
    for _ in range(300):
        if len(inbox.acks) == 2:
            break
        await asyncio.sleep(0.01)
    await poller.stop()
    assert inbox.acks == [("1", "55:100"), ("2", "55:101")]


async def test_an_item_redelivered_after_a_restart_is_not_sent_twice():
    bot, m = messenger()
    store, inbox = FakeStore(), ScriptedInbox()
    poller = InboxPoller(inbox, store, m, interval=1, limit=1, lease_seconds=1)
    inbox.batches = [[raw("1")], [raw("1")]]
    await poller.poll_once()
    await poller.poll_once()
    assert len(bot.sent) == 1 and inbox.acks == [("1", "55:100")] * 2


# -- buttons and /link ---------------------------------------------------------------------------
class InboxEnv(BotEnv):
    def __init__(self):
        super().__init__()
        deps = self.ctx.application.bot_data["deps"]
        deps.config = settings(INBOX_URL="http://x", INBOX_TOKEN="t")
        deps.inbox = ScriptedInbox()
        self.inbox = deps.inbox
        self.message = SimpleNamespace(chat=SimpleNamespace(id=-100, type="supergroup"), message_id=7, message_thread_id=None, is_topic_message=False)

    async def press(self, data="i:btn", user=5):
        query = Query(data, user, self.message)
        await handlers.on_button(SimpleNamespace(callback_query=query), self.ctx)
        return query.answers


async def test_a_press_is_reported_under_the_pressing_persons_own_key():
    env = InboxEnv()
    await env.link(5)
    await env.store.save_link(Link(6, "user6", "U", "enc:other-key"))
    assert await env.press(user=5) == [("Decided.", False)]
    await env.press(user=6)
    assert env.inbox.presses == [("k", "btn"), ("other-key", "btn")]


@pytest.mark.parametrize("outcome,words", [
    ("forbidden", "not allowed"), ("already_decided", "Already decided"), ("gone", "no longer exists"),
    ("unauthorized", "Sign in again"), ("failed", "Try again"),
])
async def test_each_answer_of_the_service_becomes_a_short_alert(outcome, words):
    env = InboxEnv()
    await env.link(5)
    env.inbox.press_result = Press(outcome)
    (text, alert), = await env.press()
    assert words in text and alert is True


async def test_a_press_by_someone_who_is_not_linked_reaches_nothing(caplog):
    env = InboxEnv()
    with caplog.at_level(logging.DEBUG):
        (text, alert), = await env.press(user=9)
    assert "privately" in text and alert is True and env.inbox.presses == []
    assert "enc:" not in caplog.text


async def test_two_approvals_are_pressed_independently():
    env = InboxEnv()
    await env.link(5)
    await env.press("i:first")
    env.inbox.press_result = Press("already_decided")
    await env.press("i:second")
    assert [b for _, b in env.inbox.presses] == ["first", "second"]


async def test_link_in_a_private_chat_reports_the_chat_and_the_username():
    env = InboxEnv()
    env.ctx.args = ["ABCD2345"]
    await env.send(handlers.cmd_link, update("/link ABCD2345", user=5))
    assert env.inbox.links == [("ABCD2345", "5", "Ann")] and "linked" in env.replies()[0]
    env.inbox.link_result = False
    await env.send(handlers.cmd_link, update("/link BAD", user=5, message_id=11))
    assert "not valid or has expired" in env.replies()[1]


async def test_link_is_refused_in_a_group_and_without_a_code_and_when_the_service_is_down():
    env = InboxEnv()
    env.ctx.args = ["ABCD2345"]
    await env.send(handlers.cmd_link, update("/link ABCD2345", chat="supergroup"))
    assert env.inbox.links == [] and "private" in env.replies()[0]
    env.ctx.args = []
    await env.send(handlers.cmd_link, update("/link", message_id=11))
    assert env.inbox.links == [] and "code" in env.replies()[1]
    env.ctx.args = ["X"]
    env.inbox.link_result = InboxError("down")
    await env.send(handlers.cmd_link, update("/link X", message_id=12))
    assert "did not answer" in env.replies()[2]


# -- replies -------------------------------------------------------------------------------------
BOT_MESSAGE = {"message_id": 100, "date": 1, "chat": {"id": 5, "type": "private"}, "from": {"id": 999, "is_bot": True, "first_name": "B"}, "text": "Which?"}


async def test_a_question_is_delivered_with_buttons_and_its_reply_reference_is_kept():
    bot, m = messenger()
    store, inbox = FakeStore(), ScriptedInbox()
    inbox.batches = [[{**raw("q", "question", "Which?", buttons=[{"id": "x1", "label": "A"}]), "reply": "ask:7"}]]
    await InboxPoller(inbox, store, m, interval=1, limit=1, lease_seconds=1).poll_once()
    assert bot.sent[0]["reply_markup"].inline_keyboard[0][0].callback_data == "i:x1"
    assert store.reply_refs == {(55, 100): "ask:7"}
    inbox.batches = [[raw("t")]]
    await InboxPoller(inbox, store, m, interval=1, limit=1, lease_seconds=1).poll_once()
    assert list(store.reply_refs) == [(55, 100)]


async def test_a_reply_to_such_a_message_goes_to_the_service_under_the_persons_key_and_not_to_the_agent():
    env = InboxEnv()
    await env.link(5)
    env.store.reply_refs[(5, 100)] = "ask:7"
    await env.send(handlers.on_message, update("the second one", reply=BOT_MESSAGE))
    assert env.inbox.replies == [("k", "ask:7", "the second one")] and env.rec.jobs == []
    assert env.replies() == ["Sent."]


async def test_a_refused_reply_shows_the_services_message():
    env = InboxEnv()
    await env.link(5)
    env.store.reply_refs[(5, 100)] = "run:3"
    env.inbox.reply_result = ReplyResult(False, "This conversation is closed.")
    await env.send(handlers.on_message, update("more", reply=BOT_MESSAGE))
    assert env.replies() == ["This conversation is closed."] and env.rec.jobs == []


async def test_a_reply_to_any_other_message_is_handled_as_before():
    env = InboxEnv()
    await env.link(5)
    await env.send(handlers.on_message, update("and then?", reply=BOT_MESSAGE))
    assert env.inbox.replies == [] and len(env.rec.jobs) == 1
