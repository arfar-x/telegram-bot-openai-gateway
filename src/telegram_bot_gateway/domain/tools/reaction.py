"""``react``: an emoji on the user's latest message."""

from __future__ import annotations

from telegram_bot_gateway.domain.tools.base import ToolError, function, load, text

NAME = "react"

#: The emoji Telegram lets a bot set, without U+FE0F.
ALLOWED = frozenset(
    "👍 👎 ❤ 🔥 🥰 👏 😁 🤔 🤯 😱 🤬 😢 🎉 🤩 🤮 💩 🙏 👌 🕊 🤡 🥱 🥴 😍 🐳 ❤‍🔥 🌚 🌭 💯 🤣 ⚡ 🍌 🏆 💔 🤨 😐 🍓 "
    "🍾 💋 🖕 😈 😴 😭 🤓 👻 👨‍💻 👀 🎃 🙈 😇 😨 🤝 ✍ 🤗 🫡 🎅 🎄 ☃ 💅 🤪 🗿 🆒 💘 🙉 🦄 😘 💊 🙊 😎 👾 "
    "🤷‍♂ 🤷 🤷‍♀ 😡".replace("️", "").split()
)

TOOL = function(
    NAME,
    "React to the user's latest message with one emoji, for a quick acknowledgement.",
    {"emoji": {"type": "string"}},
    ["emoji"],
)


def parse(arguments: str) -> str:
    emoji = (text(load(arguments), "emoji", limit=20) or "").strip().replace("️", "")
    if emoji not in ALLOWED:
        raise ToolError(f"{emoji} is not an emoji Telegram allows as a reaction")
    return emoji
