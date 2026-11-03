# Changelog

All notable changes to this project are recorded here.

The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Inbox buttons can ask for a reply: when the service answers a button press with a prompt, the bot opens Telegram's
  reply box for it, passes the person's reply back to the service, and removes the prompt afterwards. Applies migration
  `005_inbox_reply_prompts.sql`.

## [0.2.0] - 2026-10-31

### Added

- An optional message inbox, off unless `INBOX_URL` is set: the bot leases items from an HTTP service
  (`INBOX_POLL_INTERVAL`, `INBOX_LEASE_LIMIT`, `INBOX_LEASE_SECONDS`; a bearer from `INBOX_TOKEN` or from
  OAuth 2.0 client credentials `INBOX_TOKEN_URL`, `INBOX_CLIENT_ID`, `INBOX_CLIENT_SECRET`) and delivers them to
  chats as text, as messages with approval buttons, or as an edit of an earlier message. It acknowledges
  each delivery and releases a failed one with a retry delay. A button press is reported under the pressing
  person's own sign-in, and `/link CODE` in a private chat links the chat with the service. A person's Telegram reply to a delivered message can be passed back to the service instead of the chat
  agent, and `question` items show choice buttons. Specified in `specs/008-message-inbox`. Applies migrations
  `003_inbox_deliveries.sql` and `004_inbox_replies.sql`.

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

- A question or approval card is one message with its buttons under the whole text (long text is shortened); on a long message the buttons sit on the last piece, not the first.

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

[Unreleased]: https://github.com/arfar-x/telegram-bot-openai-gateway/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/arfar-x/telegram-bot-openai-gateway/compare/9d7fdcc...v0.2.0
[0.1.0]: https://github.com/arfar-x/telegram-bot-openai-gateway/commits/9d7fdcc
