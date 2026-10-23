"""``send_file``: a document the user can keep."""

from __future__ import annotations

import re
from dataclasses import dataclass

from telegram_bot_gateway.domain.tools.base import MAX_CAPTION, ToolError, function, load, text

NAME = "send_file"
MAX_NAME = 100

TOOL = function(
    NAME,
    "Send the user a file, for a long or structured result such as a report, a script or a table. "
    "Give the file name with its extension and the full text content.",
    {
        "filename": {"type": "string"},
        "content": {"type": "string", "description": "The text of the file."},
        "caption": {"type": "string"},
    },
    ["filename", "content"],
)


@dataclass(frozen=True)
class File:
    name: str
    data: bytes
    caption: str | None


def clean_name(raw: str) -> str:
    name = re.split(r"[\\/]", raw)[-1]
    name = "".join(c for c in name if c.isprintable()).strip().lstrip(".").strip()[:MAX_NAME]
    if not name:
        return "file.txt"
    return name if "." in name else name + ".txt"


def parse(arguments: str, *, max_bytes: int) -> File:
    data = load(arguments)
    name = clean_name(text(data, "filename", limit=1000) or "")
    content = data.get("content")
    if not isinstance(content, str) or not content:
        raise ToolError("content is required")
    raw = content.encode("utf-8")
    if len(raw) > max_bytes:
        raise ToolError(f"the file is {len(raw)} bytes; the limit is {max_bytes}")
    return File(name, raw, text(data, "caption", limit=MAX_CAPTION, required=False))


def size(n: int) -> str:
    return f"{n} bytes" if n < 1024 else f"{n / 1024:.1f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"
