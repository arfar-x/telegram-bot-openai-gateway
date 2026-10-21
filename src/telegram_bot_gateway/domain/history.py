"""Keeping the history sent to the endpoint within a budget."""

from __future__ import annotations

from typing import Any

from telegram_bot_gateway.domain.content import text_of


def size(message: dict[str, Any]) -> int:
    """Characters of text a message adds to a request; images are not counted."""
    total = len(text_of(message.get("content")))
    for call in message.get("tool_calls") or []:
        function = call.get("function", {})
        total += len(function.get("name", "")) + len(function.get("arguments", ""))
    return total


def _turns(messages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Whole turns: each starts at a user message and holds everything up to the next one, so a
    tool call is never separated from its answer."""
    turns: list[list[dict[str, Any]]] = []
    for message in messages:
        if message.get("role") == "user" or not turns:
            turns.append([])
        turns[-1].append(message)
    return turns


def trim(messages: list[dict[str, Any]], max_chars: int) -> list[dict[str, Any]]:
    """The newest whole turns that fit ``max_chars``. The last turn is always kept, because it is the
    one being answered, and it carries an open question when there is one."""
    turns = _turns(messages)
    total = sum(size(m) for t in turns for m in t)
    while len(turns) > 1 and total > max_chars:
        total -= sum(size(m) for m in turns.pop(0))
    return [m for t in turns for m in t]
