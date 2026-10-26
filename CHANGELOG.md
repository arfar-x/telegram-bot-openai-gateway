# Changelog

All notable changes to this project are recorded here.

The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Device sign-in as a second way to link: with `LINK_MODE=device`, `/login` shows an address and a code, the
  person approves at an OpenID Connect issuer (`OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`,
  `OIDC_SCOPE`), and the bot calls the endpoint with their own fresh access token on every turn. `/logout`
  revokes the sign-in at the issuer. A sign-in the issuer stops honouring expires and asks the person to
  `/login` again. `/whoami` and `make links` show the link kind and status. Pairing stays the default. The `/login` message has a **Sign in** button and a **Copy code** button, so
  the address and code need not be copied by hand.
  Specified in `specs/001-account-linking`. Applies migration `002_oidc_links.sql`.
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
