from telegram_bot_gateway.application import turn
from telegram_bot_gateway.application.model import Pending, Session
from telegram_bot_gateway.domain.history import size, trim

# Covers: FR-TRN-09
# Regression tests for KD-003: the history sent to the endpoint stays within a budget.


def pair(n: int, chars: int = 100):
    return [{"role": "user", "content": f"q{n} " + "x" * chars}, {"role": "assistant", "content": f"a{n} " + "y" * chars}]


def test_the_oldest_whole_turns_are_dropped_first_and_the_newest_are_kept():
    history = [m for n in range(10) for m in pair(n)]
    kept = trim(history, 1000)
    assert sum(size(m) for m in kept) <= 1000
    assert kept[-1]["content"].startswith("a9") and kept[0]["role"] == "user"
    assert len(kept) < len(history) and len(kept) % 2 == 0


def test_a_history_within_the_budget_is_untouched():
    history = [m for n in range(3) for m in pair(n)]
    assert trim(history, 10_000) == history


def test_the_turn_being_answered_is_kept_even_when_it_alone_exceeds_the_budget():
    history = pair(0) + [{"role": "user", "content": "z" * 5000}]
    assert trim(history, 100) == [{"role": "user", "content": "z" * 5000}]


def test_a_tool_call_is_never_separated_from_its_answer():
    call = {"id": "c1", "type": "function", "function": {"name": "clarify", "arguments": "{}"}}
    history = pair(0) + [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": None, "tool_calls": [call]},
        {"role": "tool", "tool_call_id": "c1", "content": "unsupported"},
        {"role": "assistant", "content": "done"},
    ] + pair(2)
    kept = trim(history, 150)
    ids = [m.get("tool_call_id") for m in kept if m["role"] == "tool"]
    calls = [c["id"] for m in kept for c in (m.get("tool_calls") or [])]
    assert set(ids) <= set(calls)


def test_an_open_question_survives_a_long_history_when_the_owner_answers():
    call = {"id": "c1", "type": "function", "function": {"name": "clarify", "arguments": "{}"}}
    long = [m for n in range(50) for m in pair(n, 500)]
    session = Session("5", 5, messages=long + [{"role": "user", "content": "start"}, {"role": "assistant", "content": None, "tool_calls": [call]}],
                      pending=Pending("c1", "Which?", ["a"], 5, 1000.0, 7))
    work, _ = turn.begin(session, "a", now=1000.0, max_chars=2000)
    assert work.messages[-1] == {"role": "tool", "tool_call_id": "c1", "content": "a"}
    assert any(c["id"] == "c1" for m in work.messages for c in (m.get("tool_calls") or []))
    assert sum(size(m) for m in work.messages) <= 2000 + 100


def test_a_new_message_trims_the_stored_history_to_the_configured_budget():
    session = Session("5", 5, messages=[m for n in range(40) for m in pair(n, 500)])
    work, _ = turn.begin(session, "next", now=1.0, max_chars=3000)
    assert sum(size(m) for m in work.messages) <= 3000 + 10
    assert work.messages[-1] == {"role": "user", "content": "next"}
