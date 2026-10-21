"""Regression tests for the defects and gaps that were recorded in the specs and then fixed.

Each test names the entry it closed (KD = defect, GAP = gap).
"""

# Covers: FR-LNK-10, FR-TRN-10, FR-OUT-12, FR-OPS-05, FR-OPS-08, FR-OPS-09

import asyncio
import time
from types import SimpleNamespace

import pytest
from telegram.error import NetworkError, TimedOut

from telegram_bot_gateway import config as config_mod
from telegram_bot_gateway.adapters.inbound.telegram import bot as handlers
from telegram_bot_gateway.adapters.inbound.telegram import runtime as runtime_mod
from telegram_bot_gateway.adapters.inbound.telegram import sender as sender_mod
from telegram_bot_gateway.adapters.inbound.telegram import serve as serve_mod
from telegram_bot_gateway.adapters.inbound.telegram.sender import Sender, Target
from telegram_bot_gateway.application import linking
from telegram_bot_gateway.application.model import Link, PairingRequest, Pending, Session
from tests.adapters.test_bot import Env, Query, update
from tests.adapters.test_runtime import job, make, settle, texts
from tests.fakes import FakeBot, FakeStore, FakeVault, ScriptedLlm, say

REAL_SLEEP = asyncio.sleep


@pytest.fixture
def fast_sleep(monkeypatch):
    async def quick(seconds, *args, **kwargs):
        await REAL_SLEEP(0.001)

    monkeypatch.setattr(sender_mod.asyncio, "sleep", quick)


async def test_kd001_an_answer_that_could_not_be_sent_is_not_kept_in_the_history(fast_sleep):
    bot, store, rt = await make(ScriptedLlm(say("an answer the user never sees")))
    bot.fail_next = [NetworkError("down") for _ in range(10)]
    rt.submit(job())
    await settle(lambda: not bot.fail_next or len(bot.fail_next) <= 5)
    await REAL_SLEEP(0.2)
    saved = store.sessions.get("5")
    assert saved is None or all(m["role"] != "assistant" for m in saved.messages)


async def test_kd001_a_connection_failure_is_retried_and_the_answer_arrives_once(fast_sleep):
    bot, store = FakeBot(), FakeStore()
    bot.fail_next = [NetworkError("All connection attempts failed"), NetworkError("All connection attempts failed")]
    ids = await Sender(bot, store).send(Target(1, "private"), "hello")
    assert len(bot.sent) == 1 and len(ids) == 1 and bot.fail_next == []


async def test_kd001_a_timeout_is_not_retried_because_the_message_may_have_arrived(fast_sleep):
    bot, store = FakeBot(), FakeStore()
    bot.fail_next = [TimedOut("slow")]
    with pytest.raises(TimedOut):
        await Sender(bot, store).send(Target(1, "private"), "hello")
    assert bot.sent == []


async def test_kd001_the_reply_is_saved_after_it_was_sent():
    bot, store, rt = await make(ScriptedLlm(say("fine")))
    order = []
    real_send, real_save = rt._sender.send, store.save_session

    async def send(*a, **k):
        order.append("send")
        return await real_send(*a, **k)

    async def save(session):
        order.append("save")
        return await real_save(session)

    rt._sender.send, store.save_session = send, save
    rt.submit(job())
    await settle(lambda: "save" in order)
    assert order == ["send", "save"]


async def test_kd004_a_card_older_than_a_day_is_refused_at_the_tap():
    env = Env()
    session = Session("5", 5, pending=Pending("call_1", "Run it?", ["Approve", "Reject"], 5, time.time() - 90_000, card_message_id=77))
    await env.store.save_session(session)
    message = SimpleNamespace(chat=SimpleNamespace(id=5, type="private", is_forum=False), message_id=77,
                              message_thread_id=None, is_topic_message=False)
    tap = Query("a:0", 5, message)
    await handlers.on_button(SimpleNamespace(callback_query=tap), env.ctx)
    assert env.rec.jobs == [] and tap.answers and tap.answers[0][1] is True
    assert "expired" in tap.answers[0][0] and "Expired" in env.bot.edits[-1]["text"].replace("\\", "")


async def test_kd006_set_and_unset_accept_the_same_names():
    env = Env()
    await env.link()
    env.ctx.args = ["reasoning_effort", "high"]
    await env.send(handlers.cmd_set, update("/set reasoning_effort high"))
    assert env.store.sessions["5"].params == {"reasoning_effort": "high"}
    env.ctx.args = ["reasoning_effort", "extreme"]
    await env.send(handlers.cmd_set, update("/set reasoning_effort extreme", message_id=11))
    assert "must be one of" in env.replies()[-1] and env.store.sessions["5"].params == {"reasoning_effort": "high"}
    env.ctx.args = ["reasoning_effort"]
    await env.send(handlers.cmd_unset, update("/unset reasoning_effort", message_id=12))
    assert env.store.sessions["5"].params == {}


async def test_kd007_a_cut_model_list_says_how_many_there_are():
    env = Env()
    await env.link()

    async def many(api_key):
        return [f"model-{i}" for i in range(50)]

    env.ctx.application.bot_data["deps"].llm.models = many
    await env.send(handlers.cmd_model, update("/model"))
    assert "40 of 50" in env.replies()[-1]
    assert len([b for row in env.bot.sent[-1]["reply_markup"].inline_keyboard for b in row]) == 40


async def test_gap005_new_marks_an_open_card_as_cancelled():
    env = Env()
    await env.link()
    await env.store.save_session(Session("5", 5, pending=Pending("c1", "Which?", ["a", "b"], 5, time.time(), card_message_id=77)))
    await env.send(handlers.cmd_new, update("/new"))
    assert "5" not in env.store.sessions
    assert env.bot.edits[0]["message_id"] == 77 and "Cancelled" in env.bot.edits[0]["text"].replace("\\", "")


def _group(text, *, reply_from_bot=False, message_id=10, user=5):
    entities = [{"type": "mention", "offset": text.index("@"), "length": len(text.split()[0])}]
    reply = None
    if reply_from_bot:
        reply = {"message_id": 3, "date": 1, "chat": {"id": -100, "type": "supergroup"}, "from": {"id": 999, "is_bot": True, "first_name": "B"}, "text": "earlier"}
    return update(text, chat="supergroup", entities=entities, reply=reply, message_id=message_id, user=user)


async def test_kd005_a_person_whose_name_ends_in_bot_does_not_silence_the_bot():
    handlers._known_bots.clear()
    env = Env()
    await env.link()
    await env.send(handlers.on_message, _group("@robbot what do you think", reply_from_bot=True))
    assert len(env.rec.jobs) == 1


async def test_kd005_a_bot_that_was_seen_is_recognised_as_another_bot():
    handlers._known_bots.clear()
    env = Env()
    await env.link()
    other = {"message_id": 4, "date": 1, "chat": {"id": -100, "type": "supergroup"}, "from": {"id": 77, "is_bot": True, "first_name": "H", "username": "helperbot"}, "text": "hi"}
    seen = update("ping", chat="supergroup", reply=other, message_id=9)
    await env.send(handlers.on_message, seen)  # a reply to another bot teaches its name; it is no trigger
    assert env.rec.jobs == []
    await env.send(handlers.on_message, _group("@helperbot summarise", reply_from_bot=True, message_id=11))
    assert env.rec.jobs == []


async def test_gap001_everyone_with_an_unanswered_message_is_told_when_the_bot_stops():
    gate = asyncio.Event()

    async def slow():
        await gate.wait()
        return say("never")

    llm = ScriptedLlm(slow)
    bot, store, rt = await make(llm, reactions=True, reaction_delay=0.01)
    rt.submit(job(user=5, text="running", msg_id=10))
    await settle(lambda: rt.busy("5") and llm.calls)
    rt.submit(job(user=5, text="queued", msg_id=11))
    await settle(lambda: len(bot.reactions) >= 1)
    await rt.shutdown()
    assert any("restarted" in t for t in texts(bot))
    assert sum("restarted" in t for t in texts(bot)) == 1  # once per chat, not once per message
    assert bot.sent[-1]["disable_notification"] is True
    await REAL_SLEEP(0.05)
    assert "5" not in store.sessions and bot.reactions[-1][1] == []  # nothing saved, the 👀 removed


async def test_gap006_one_person_runs_at_most_the_allowed_turns_at_once():
    running = {"now": 0, "max": 0}

    async def slow():
        running["now"] += 1
        running["max"] = max(running["max"], running["now"])
        await REAL_SLEEP(0.1)
        running["now"] -= 1
        return say("ok")

    llm = ScriptedLlm(slow, slow, slow)
    bot, store, rt = await make(llm, max_concurrent_turns=1)
    for chat in (5, 105, 205):
        await store.save_link(Link(chat, "u", "U", "enc:k"))
    for n, key in enumerate(("a", "b", "c")):
        rt.submit(runtime_mod.Job(Target(5, "private", None, 10 + n), 5, key, runtime_mod.Item(f"q{n}"), 0.01))
    await settle(lambda: len(bot.sent) == 3, timeout=5)
    assert running["max"] == 1


async def test_gap007_expired_pairing_codes_are_deleted_when_the_next_request_arrives():
    store = FakeStore()
    await store.create_pairing(PairingRequest("OLDCODE2", 9, "x", "X", 9, 1000.0))
    result = await linking.request(store, telegram_user_id=5, username="a", telegram_name="A", chat_id=5, now=1000.0 + 3601)
    assert isinstance(result, linking.Paired) and "OLDCODE2" not in store.pairings


async def test_gap008_a_key_that_cannot_be_decrypted_is_reported_to_the_user():
    class BrokenVault(FakeVault):
        def decrypt(self, ciphertext):
            raise ValueError("cannot be decrypted")

    bot, store, rt = await make(ScriptedLlm(say("never")))
    rt._vault = BrokenVault()
    rt.submit(job())
    await settle(lambda: bot.sent)
    assert runtime_mod.UNREADABLE_KEY in texts(bot)[0].replace("\\", "") and rt._llm.calls == []


async def test_kd002_the_health_file_is_written_only_while_telegram_answers(tmp_path, monkeypatch):
    target = tmp_path / "healthy"
    answers = {"ok": True}

    class Bot:
        async def get_me(self):
            if not answers["ok"]:
                raise NetworkError("down")

    async def fake_sleep(seconds):
        await REAL_SLEEP(0.01)

    monkeypatch.setattr(serve_mod.asyncio, "sleep", fake_sleep)
    task = asyncio.create_task(serve_mod._heartbeat(str(target), Bot()))
    await settle(target.exists)
    first = target.read_text()
    answers["ok"] = False
    await REAL_SLEEP(0.1)
    assert target.read_text() == first  # not rewritten while Telegram is unreachable
    answers["ok"] = True
    await settle(lambda: target.read_text() != first)
    task.cancel()


async def test_gap003_housekeeping_prunes_message_texts_and_expired_codes(monkeypatch):
    calls = []

    class Store:
        async def prune_texts(self, *, older_than_days):
            calls.append(("texts", older_than_days))
            return 3

        async def prune_pairings(self, *, before):
            calls.append(("codes", before))
            return 1

    task = asyncio.create_task(serve_mod._housekeeping(Store(), 30))
    await settle(lambda: len(calls) == 2)
    task.cancel()
    assert calls[0] == ("texts", 30) and calls[1][0] == "codes"


def test_gap004_the_telegram_timeouts_and_proxy_come_from_the_environment():
    env = {"BOT_TOKEN": "1:a", "OPENAI_BASE_URL": "http://x", "DEFAULT_MODEL": "m", "DATABASE_URL": "d", "CREDS_KEY": "k"}
    s = config_mod.Settings.from_env(env)
    assert (s.telegram_proxy, s.telegram_connect_timeout, s.telegram_read_timeout) == ("", 20.0, 30.0)
    s = config_mod.Settings.from_env({**env, "TELEGRAM_PROXY": "http://127.0.0.1:3128", "TELEGRAM_CONNECT_TIMEOUT": "40", "TELEGRAM_READ_TIMEOUT": "50"})
    assert (s.telegram_proxy, s.telegram_connect_timeout, s.telegram_read_timeout) == ("http://127.0.0.1:3128", 40.0, 50.0)
    app = serve_mod.build_application(s, None, None, None)
    assert app.bot.token == "1:a"


def test_gap002_the_webhook_addition_publishes_the_port_on_loopback_only():
    from pathlib import Path
    text = (Path(__file__).resolve().parent.parent / "compose.webhook.yaml").read_text()
    assert '"127.0.0.1:${WEBHOOK_PORT:-8443}:${WEBHOOK_PORT:-8443}"' in text
