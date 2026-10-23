"""``send_buttons``: a message whose buttons open a link or copy a text."""

from __future__ import annotations

from dataclasses import dataclass

from telegram_bot_gateway.domain.tools.base import MAX_TEXT, ToolError, function, load, text, web_url

NAME = "send_buttons"
MAX_BUTTONS = 8
MAX_LABEL = 64
MAX_COPY = 256

TOOL = function(
    NAME,
    "Send a message with buttons under it. A button either opens a web address (url) or copies a text to "
    "the user's clipboard (copy), for example a command or a code to paste. Use it for sources and snippets.",
    {
        "text": {"type": "string"},
        "buttons": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"label": {"type": "string"}, "url": {"type": "string"}, "copy": {"type": "string"}},
                "required": ["label"],
            },
        },
    },
    ["text", "buttons"],
)


@dataclass(frozen=True)
class Button:
    label: str
    url: str | None = None
    copy: str | None = None


@dataclass(frozen=True)
class Buttons:
    text: str
    buttons: tuple[Button, ...]


def parse(arguments: str) -> Buttons:
    args = load(arguments)
    body = text(args, "text", limit=MAX_TEXT) or ""
    raw = args.get("buttons")
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_BUTTONS:
        raise ToolError(f"buttons must be a list of 1 to {MAX_BUTTONS}")
    out: list[Button] = []
    for i, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise ToolError(f"button {i} must be an object")
        label = text(item, "label", limit=MAX_LABEL)
        url, copy = text(item, "url", limit=2048, required=False), text(item, "copy", limit=MAX_COPY, required=False)
        if (url is None) == (copy is None):
            raise ToolError(f"button {i} needs exactly one of url and copy")
        out.append(Button(label or "", web_url(url, f"button {i} url") if url else None, copy))
    return Buttons(body, tuple(out))
