"""``send_image``: a picture from a web address or from data."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass

from telegram_bot_gateway.domain.tools.base import MAX_CAPTION, ToolError, function, load, text, web_url

NAME = "send_image"
MAX_IMAGE_BYTES = 10 * 1024 * 1024

TOOL = function(
    NAME,
    "Send the user an image. Give either a web address (Telegram fetches it) or the image as base64.",
    {"url": {"type": "string"}, "base64": {"type": "string"}, "caption": {"type": "string"}},
    [],
)


@dataclass(frozen=True)
class Image:
    url: str | None
    data: bytes | None
    caption: str | None


def parse(arguments: str) -> Image:
    args = load(arguments)
    url = text(args, "url", limit=2048, required=False)
    encoded = text(args, "base64", limit=MAX_IMAGE_BYTES * 2, required=False)
    if (url is None) == (encoded is None):
        raise ToolError("give exactly one of url and base64")
    caption = text(args, "caption", limit=MAX_CAPTION, required=False)
    if url is not None:
        return Image(web_url(url), None, caption)
    try:
        raw = base64.b64decode(encoded.split(",", 1)[-1] if encoded.startswith("data:") else encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ToolError("base64 is not valid") from exc
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise ToolError(f"the image must be between 1 byte and {MAX_IMAGE_BYTES} bytes")
    return Image(None, raw, caption)
