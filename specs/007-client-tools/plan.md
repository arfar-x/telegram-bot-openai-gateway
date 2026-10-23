# Implementation Plan: Client Tools

**Spec**: [`spec.md`](spec.md) | **Status**: As built

## Summary

Each tool is a pure module in `domain/tools/` (declaration, argument parsing, limits). `application/turn.py` declares the enabled tools, carries out immediate calls through an `Actions` port, and treats `request_approval` as a second way to open a question. `adapters/inbound/telegram/actions.py` implements the port with python-telegram-bot, and the runtime builds one per turn.

## Constitution Check

- Hexagonal core: parsing and limits in `domain/tools/`; the loop in `application/turn.py`; every Telegram call in the adapter. Satisfied.
- Endpoint-agnostic: plain function tools in the standard `tools` array; nothing provider-specific. Satisfied.
- Queue, never interrupt: a file already sent is a side effect `/stop` does not undo. Satisfied.

## Project Structure

```text
domain/tools/__init__.py     registry, declarations(enabled), names
domain/tools/base.py         ToolError, argument loading, limits
domain/tools/{files,images,buttons,notify,reaction,context,approval}.py
application/ports.py         Actions, ActionError
application/turn.py          dispatch of immediate and suspending calls
adapters/inbound/telegram/actions.py   TelegramActions
adapters/inbound/telegram/runtime.py   builds actions; keeps the model's reaction
config.py                    TOOLS, TOOL_MAX_FILE_BYTES
```

## Configuration

`TOOLS` (comma list; default all; `none`), `TOOL_MAX_FILE_BYTES` (default 1048576).

## Complexity Tracking

None.
