# Changelog

All notable changes to this project are recorded here.

The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Client tools the endpoint can call, carried out by the bot in Telegram and chosen with `TOOLS`
  (all by default, `none`, or a comma list): `request_approval` (an Allow / Reject card), `send_file`,
  `send_image`, `send_buttons` (link and copy-to-clipboard buttons), `notify` (a silent note), `react`
  and `get_context`. `TOOL_MAX_FILE_BYTES` caps a file. Specified in `specs/007-client-tools`.
- Answers can use underline (`<u>x</u>`) and spoiler (`||x||`).

### Changed

- The system note asks for plain text by default and for marks (bold, `code`, underline, strike,
  spoiler) only where they help the reader.
- A request now declares `clarify` followed by the enabled client tools, not `clarify` alone. An
  endpoint that rejects several tools in `tools` needs `TOOLS=none`.

## [0.1.0] - 2026-10-21

### Added

- A Telegram bot that is a client of any OpenAI-compatible Chat Completions endpoint: account linking
  by pairing code and operator approval, one API key per user stored encrypted, sessions per chat and
  topic, text, image and document input, streamed replies in Telegram MarkdownV2, queued messages,
  `/stop`, `/new`, `/model`, `/reasoning`, `/set` and `/settings`.
- The `clarify` tool: questions and approvals shown as cards with inline buttons.
- Long polling or webhook, PostgreSQL storage, a container image and a compose file.

### Fixed

- The known defects and gaps recorded in the specs.

[Unreleased]: https://github.com/arfar-x/telegram-bot-openai-gateway/compare/9d7fdcc...HEAD
[0.1.0]: https://github.com/arfar-x/telegram-bot-openai-gateway/commits/9d7fdcc
