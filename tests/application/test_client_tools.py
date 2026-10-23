import json

from telegram_bot_gateway.application import turn
from telegram_bot_gateway.application.model import Session
from telegram_bot_gateway.domain import tools
from tests.fakes import FakeActions, ScriptedLlm, call, say

# Covers: FR-TLS-01, FR-TLS-02, FR-TLS-03, FR-TLS-04, FR-TLS-05, FR-TLS-06, FR-TLS-07, FR-TLS-08, FR-TLS-09
# Covers: FR-TLS-10, FR-TLS-11, FR-TRN-02

NOW = 1_761_213_600.0  # 2025-10-23T10:00:00Z


async def run(llm, actions, enabled=tools.ALL, **kw):
    work, _ = turn.begin(Session("7", 7), "hi", now=NOW)
    outcome = await turn.run(work, llm, "k", default_model="m", chat_id=7, now=NOW, actions=actions, enabled=enabled, **kw)
    return work, outcome


def several(*calls):
    return {"role": "assistant", "content": None, "tool_calls": [c["tool_calls"][0] for c in calls]}


def tool_messages(work):
    return [(m["tool_call_id"], m["content"]) for m in work.messages if m["role"] == "tool"]


async def test_clarify_comes_first_then_the_enabled_tools():
    llm = ScriptedLlm(say("x"), say("x"), say("x"))
    await run(llm, FakeActions())
    await run(llm, FakeActions(), enabled=["notify"])
    await run(llm, None)
    names = [[t["function"]["name"] for t in c["tools"]] for c in llm.calls]
    assert names[0] == ["clarify", *tools.ALL] and names[1] == ["clarify", "notify"] and names[2] == ["clarify"]


async def test_a_file_is_sent_and_the_turn_goes_on_with_the_result():
    actions = FakeActions()
    args = json.dumps({"filename": "../r.md", "content": "# R"})
    llm = ScriptedLlm(call("send_file", args, "c1"), say("done"))
    work, outcome = await run(llm, actions)
    assert outcome.text == "done"
    (kind, file), = actions.done
    assert kind == "file" and file.name == "r.md" and file.data == b"# R"
    assert tool_messages(work) == [("c1", "Sent r.md (3 bytes).")]
    assert llm.calls[1]["messages"][-1] == {"role": "tool", "tool_call_id": "c1", "content": "Sent r.md (3 bytes)."}


async def test_each_immediate_tool_reaches_the_chat():
    actions = FakeActions()
    llm = ScriptedLlm(
        several(
            call("send_image", '{"url":"https://x.io/a.png"}', "a"),
            call("send_buttons", '{"text":"t","buttons":[{"label":"l","copy":"c"}]}', "b"),
            call("notify", '{"text":"working"}', "c"),
            call("react", '{"emoji":"👍"}', "d"),
        ),
        say("ok"),
    )
    work, _ = await run(llm, actions)
    assert [k for k, _ in actions.done] == ["image", "buttons", "notify", "react"]
    assert tool_messages(work) == [("a", "Sent the image."), ("b", "Sent the buttons."), ("c", "Sent."), ("d", "Reacted 👍.")]


async def test_the_context_comes_from_the_chat_and_the_clock():
    llm = ScriptedLlm(call("get_context", "", "g"), say("ok"))
    work, _ = await run(llm, FakeActions())
    assert json.loads(tool_messages(work)[0][1]) == {
        "chat_type": "private", "topic": False, "language": "en", "utc_now": "2025-10-23T10:00:00Z",
    }


async def test_bad_arguments_and_failed_deliveries_are_results_not_errors():
    actions = FakeActions()
    llm = ScriptedLlm(
        several(call("send_file", "oops", "a"), call("react", '{"emoji":"🦖"}', "b"), call("notify", '{"text":"x"}', "c")),
        say("ok"),
    )
    actions.fail = "chat not found"
    work, outcome = await run(llm, actions)
    results = dict(tool_messages(work))
    assert results["a"] == "Invalid arguments: the arguments are not valid JSON"
    assert results["b"].startswith("Invalid arguments: 🦖 is not an emoji")
    assert results["c"] == "Could not notify: chat not found"
    assert actions.done == [] and outcome.text == "ok"


async def test_a_tool_that_is_not_enabled_is_unsupported():
    actions = FakeActions()
    llm = ScriptedLlm(call("send_file", '{"filename":"a","content":"b"}', "a"), say("ok"))
    work, outcome = await run(llm, actions, enabled=["notify"])
    assert tool_messages(work) == [("a", turn.UNSUPPORTED_TOOL)] and actions.done == []
    assert outcome.notices == ["The endpoint asked for an unsupported tool: send_file"]


async def test_no_actions_means_no_client_tools():
    llm = ScriptedLlm(call("notify", '{"text":"x"}', "a"), say("ok"))
    work, _ = await run(llm, None)
    assert tool_messages(work) == [("a", turn.UNSUPPORTED_TOOL)]


async def test_only_ten_actions_run_in_a_turn():
    actions = FakeActions()
    llm = ScriptedLlm(several(*[call("notify", '{"text":"x"}', f"n{i}") for i in range(12)]), say("ok"))
    work, _ = await run(llm, actions)
    assert len(actions.done) == 10
    assert [r for _, r in tool_messages(work)][-2:] == [turn.TOO_MANY_ACTIONS] * 2


async def test_the_size_limit_comes_from_the_caller():
    llm = ScriptedLlm(call("send_file", '{"filename":"a.txt","content":"abcdef"}', "a"), say("ok"))
    work, _ = await run(llm, FakeActions(), max_file_bytes=5)
    assert tool_messages(work) == [("a", "Invalid arguments: the file is 6 bytes; the limit is 5")]


async def test_an_approval_ends_the_turn_with_a_question_after_the_immediate_calls_ran():
    actions = FakeActions()
    llm = ScriptedLlm(several(
        call("request_approval", '{"action":"Delete it","effect":"Gone for good"}', "ap"),
        call("notify", '{"text":"asking"}', "n"),
        call("request_approval", '{"action":"Second"}', "ap2"),
    ))
    work, outcome = await run(llm, actions)
    assert isinstance(outcome, turn.Ask) and outcome.question.options == ("Allow", "Reject")
    assert outcome.question.text == "**Delete it**\nGone for good" and not outcome.question.show_other
    assert work.pending.tool_call_id == "ap" and work.pending.options == ["Allow", "Reject"]
    assert actions.done == [("notify", "asking")]
    assert dict(tool_messages(work)) == {"n": "Sent.", "ap2": turn.UNSUPPORTED_TOOL}
    answered, _ = turn.begin(work, "Allow", now=NOW + 1)
    assert answered.messages[-1] == {"role": "tool", "tool_call_id": "ap", "content": "Allow"}


async def test_an_approval_with_bad_arguments_is_answered_and_the_turn_goes_on():
    llm = ScriptedLlm(call("request_approval", "{}", "ap"), say("ok"))
    work, outcome = await run(llm, FakeActions())
    assert tool_messages(work) == [("ap", "Invalid arguments: action is required")] and outcome.text == "ok"


async def test_the_old_clarify_still_works_beside_the_new_tools():
    llm = ScriptedLlm(call("clarify", '{"question":"Which?","choices":["a","b"]}', "q"))
    _, outcome = await run(llm, FakeActions())
    assert isinstance(outcome, turn.Ask) and outcome.question.options == ("a", "b") and outcome.question.show_other
