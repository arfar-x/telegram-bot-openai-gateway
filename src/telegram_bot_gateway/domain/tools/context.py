"""``get_context``: where the model is talking."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from telegram_bot_gateway.domain.tools.base import function

NAME = "get_context"

TOOL = function(
    NAME,
    "Get facts about this chat: its type, whether it is a topic, the user's language and the current UTC time.",
    {},
    [],
)


def render(*, chat_type: str, topic: bool, language: str | None, now: datetime) -> str:
    return json.dumps(
        {
            "chat_type": chat_type,
            "topic": topic,
            "language": language,
            "utc_now": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )
