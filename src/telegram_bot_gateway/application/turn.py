"""One turn: the user's message in, the endpoint's answer or question out."""

from __future__ import annotations

import copy
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from telegram_bot_gateway.application.model import PENDING_TTL_SECONDS, Pending, Session
from telegram_bot_gateway.application.ports import ActionError, Actions, Llm, ReasoningSink
from telegram_bot_gateway.domain import clarify, tools
from telegram_bot_gateway.domain.tools import approval, buttons, context, files, images, notify, reaction
from telegram_bot_gateway.domain.tools.base import ToolError
from telegram_bot_gateway.domain.content import drop_images, text_of
from telegram_bot_gateway.domain.history import trim

DEFAULT_HISTORY_MAX_CHARS = 200_000

MAX_ROUNDS = 8
MAX_ACTIONS = 10
DEFAULT_MAX_FILE_BYTES = 1_048_576
UNSUPPORTED_TOOL = "This client cannot run that tool."
TOO_MANY_ACTIONS = "Too many actions in one turn."


@dataclass
class Answer:
    text: str
    notices: list[str] = field(default_factory=list)


@dataclass
class Ask:
    question: clarify.Question
    tool_call_id: str
    notices: list[str] = field(default_factory=list)


Outcome = Answer | Ask


def begin(
    session: Session, content: str | list[dict[str, Any]], *, now: float, max_chars: int = DEFAULT_HISTORY_MAX_CHARS
) -> tuple[Session, Pending | None]:
    """A copy of the session with the user's message added, and any question that went stale.

    A message sent while a question is open answers it; a question older than a day is dropped
    together with the assistant turn that asked it.
    """
    work = copy.deepcopy(session)
    stale: Pending | None = None
    pending = work.pending
    if pending is not None and now - pending.created_at > PENDING_TTL_SECONDS:
        stale = pending
        work.pending = None
        while work.messages and work.messages[-1].get("role") == "tool":
            work.messages.pop()
        if work.messages and work.messages[-1].get("role") == "assistant" and work.messages[-1].get("tool_calls"):
            work.messages.pop()
        pending = None
    if pending is not None:
        work.messages.append({"role": "tool", "tool_call_id": pending.tool_call_id, "content": text_of(content) or "(no answer)"})
        work.pending = None
    else:
        work.messages = drop_images(work.messages)
        work.messages.append({"role": "user", "content": content})
    work.messages = trim(work.messages, max_chars)
    return work, stale


async def run(
    work: Session,
    llm: Llm,
    api_key: str,
    *,
    default_model: str,
    chat_id: int,
    now: float,
    on_reasoning: ReasoningSink | None = None,
    system: str | None = None,
    actions: Actions | None = None,
    enabled: Collection[str] = (),
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> Outcome:
    """Call the endpoint until it answers or asks. ``work`` is changed; the caller saves it on success.

    ``system`` is sent first on every call and never stored, so it can change without touching history.
    ``enabled`` names the client tools declared besides ``clarify``; without ``actions`` there are none.
    """
    params = dict(work.params)
    notices: list[str] = []
    active = set(enabled) if actions is not None else set()
    declared = [clarify.TOOL, *tools.declarations(active)]
    performed = 0
    for _ in range(MAX_ROUNDS):
        sent = [{"role": "system", "content": system}, *work.messages] if system else work.messages
        message = await llm.chat(api_key, work.model or default_model, sent, params, declared, on_reasoning)
        work.messages.append(message)
        calls = message.get("tool_calls") or []
        if not calls:
            return Answer(text_of(message.get("content")), notices)
        asked: tuple[dict[str, Any], clarify.Question] | None = None
        for call in calls:
            name = call.get("function", {}).get("name")
            arguments = call.get("function", {}).get("arguments", "")
            if name == clarify.NAME and asked is None:
                asked = (call, clarify.parse(arguments))
            elif name in tools.SUSPENDING and name in active and asked is None:
                try:
                    asked = (call, approval.parse(arguments))
                except ToolError as exc:
                    work.messages.append({"role": "tool", "tool_call_id": call["id"], "content": f"Invalid arguments: {exc}"})
            elif name in tools.IMMEDIATE and name in active:
                if performed >= MAX_ACTIONS:
                    result = TOO_MANY_ACTIONS
                else:
                    performed += 1
                    result = await _carry_out(name, arguments, actions, max_file_bytes, now)
                work.messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
            else:
                notices.append(f"The endpoint asked for an unsupported tool: {name}")
                work.messages.append({"role": "tool", "tool_call_id": call["id"], "content": UNSUPPORTED_TOOL})
        if asked is not None:
            call, question = asked
            work.pending = Pending(call["id"], question.text, list(question.options), chat_id, now)
            return Ask(question, call["id"], notices)
    notices.append("Stopped: the endpoint kept calling tools.")
    return Answer("", notices)


async def _carry_out(name: str, arguments: str, actions: Actions, max_file_bytes: int, now: float) -> str:
    """Run one immediate client tool; the result text is what the endpoint is told."""
    try:
        if name == files.NAME:
            file = files.parse(arguments, max_bytes=max_file_bytes)
            await actions.send_file(file)
            return f"Sent {file.name} ({files.size(len(file.data))})."
        if name == images.NAME:
            await actions.send_image(images.parse(arguments))
            return "Sent the image."
        if name == buttons.NAME:
            await actions.send_buttons(buttons.parse(arguments))
            return "Sent the buttons."
        if name == notify.NAME:
            await actions.notify(notify.parse(arguments))
            return "Sent."
        if name == reaction.NAME:
            emoji = reaction.parse(arguments)
            await actions.react(emoji)
            return f"Reacted {emoji}."
        facts = actions.facts()
        return context.render(
            chat_type=facts.chat_type, topic=facts.topic, language=facts.language,
            now=datetime.fromtimestamp(now, timezone.utc),
        )
    except ToolError as exc:
        return f"Invalid arguments: {exc}"
    except ActionError as exc:
        return f"Could not {name.replace('_', ' ')}: {exc}"
