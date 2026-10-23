"""``request_approval``: ask the user to allow or reject an action."""

from __future__ import annotations

from telegram_bot_gateway.domain.clarify import Question
from telegram_bot_gateway.domain.tools.base import function, load, text

NAME = "request_approval"
CHOICES = ("Allow", "Reject")

TOOL = function(
    NAME,
    "Ask the user to allow or reject an action before you do it, for example one that changes something. "
    "Say what the action is and, if useful, what it will affect. Wait for the answer.",
    {"action": {"type": "string"}, "effect": {"type": "string"}},
    ["action"],
)


def parse(arguments: str) -> Question:
    args = load(arguments)
    action = text(args, "action", limit=300) or "?"
    effect = text(args, "effect", limit=1000, required=False)
    return Question(f"**{action}**" + (f"\n{effect}" if effect else ""), CHOICES, other=False)
