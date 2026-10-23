"""What every client tool shares: loading arguments and saying what is wrong with them."""

from __future__ import annotations

import json
from typing import Any

MAX_CAPTION = 1024
MAX_TEXT = 4096


class ToolError(ValueError):
    """Arguments the bot cannot act on; the message goes back to the endpoint as the result."""


def load(arguments: str) -> dict[str, Any]:
    try:
        data = json.loads(arguments or "{}")
    except ValueError as exc:
        raise ToolError("the arguments are not valid JSON") from exc
    if not isinstance(data, dict):
        raise ToolError("the arguments must be a JSON object")
    return data


def text(data: dict[str, Any], name: str, *, limit: int, required: bool = True) -> str | None:
    value = data.get(name)
    if value is None or value == "":
        if required:
            raise ToolError(f"{name} is required")
        return None
    if not isinstance(value, str):
        raise ToolError(f"{name} must be a string")
    if len(value) > limit:
        raise ToolError(f"{name} is longer than {limit} characters")
    return value


def web_url(value: str, name: str = "url") -> str:
    if len(value) > 2048 or not value.lower().startswith(("http://", "https://")) or " " in value:
        raise ToolError(f"{name} must be an http or https address")
    return value


def function(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }
