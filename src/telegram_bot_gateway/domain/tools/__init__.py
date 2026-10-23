"""The client tools: functions the bot declares and carries out itself, in Telegram.

``clarify`` (domain/clarify.py) is always declared. The others are chosen by the operator.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from telegram_bot_gateway.domain.tools import approval, buttons, context, files, images, notify, reaction

_TOOLS: dict[str, dict[str, Any]] = {
    approval.NAME: approval.TOOL,
    files.NAME: files.TOOL,
    images.NAME: images.TOOL,
    buttons.NAME: buttons.TOOL,
    notify.NAME: notify.TOOL,
    reaction.NAME: reaction.TOOL,
    context.NAME: context.TOOL,
}

#: Every client tool except ``clarify``, in the order it is declared.
ALL: tuple[str, ...] = tuple(_TOOLS)
#: The ones that end the turn with a question the user answers.
SUSPENDING: frozenset[str] = frozenset({approval.NAME})
IMMEDIATE: frozenset[str] = frozenset(ALL) - SUSPENDING


def declarations(enabled: Iterable[str]) -> list[dict[str, Any]]:
    wanted = set(enabled)
    return [_TOOLS[name] for name in ALL if name in wanted]


def parse_names(raw: str) -> tuple[str, ...]:
    """The tools a ``TOOLS`` value names: empty for all, ``none`` for none."""
    raw = raw.strip()
    if not raw:
        return ALL
    if raw.lower() == "none":
        return ()
    names = tuple(n.strip() for n in raw.split(",") if n.strip())
    unknown = [n for n in names if n not in _TOOLS]
    if unknown:
        raise ValueError(f"unknown tool(s) in TOOLS: {', '.join(unknown)}; choose from {', '.join(ALL)}")
    return tuple(n for n in ALL if n in names)
