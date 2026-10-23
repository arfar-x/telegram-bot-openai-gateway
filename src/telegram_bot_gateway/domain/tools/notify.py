"""``notify``: a short note while the turn goes on."""

from __future__ import annotations

from telegram_bot_gateway.domain.tools.base import MAX_TEXT, function, load, text

NAME = "notify"

TOOL = function(
    NAME,
    "Tell the user briefly what you are doing while you keep working, for example before a slow step. "
    "It is silent and does not end your turn.",
    {"text": {"type": "string"}},
    ["text"],
)


def parse(arguments: str) -> str:
    return text(load(arguments), "text", limit=MAX_TEXT) or ""
