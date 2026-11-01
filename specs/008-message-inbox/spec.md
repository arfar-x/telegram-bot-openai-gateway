# Feature Specification: Message Inbox

**Created**: 2026-10-31

**Status**: Accepted

**Input**: A request to let any compatible service reach people on Telegram, and let them answer it with a button, without the service ever calling Telegram.

Terms follow [`../glossary.md`](../glossary.md).

A **message inbox** is an optional HTTP service the bot pulls messages from. The bot leases items, delivers each to a Telegram chat, and tells the service what happened; the service never calls the bot or Telegram. It is off unless `INBOX_URL` is set. The service address is the base of its API (for example `https://host/api/v1`); every route below is relative to it.

## Contract

| Call | Bearer | Body | Purpose |
|---|---|---|---|
| `POST /outbox/lease` | the bot's service bearer | `{limit, lease_seconds}` | `{items}` to deliver |
| `POST /outbox/{id}/ack` | service | `{external_ref}` | the item was delivered |
| `POST /outbox/{id}/release` | service | `{retry_in, error}` | it was not; offer it again later |
| `POST /outbox/link` | service | `{code, address, label}` | a chat becomes a person's destination |
| `POST /replies` | the replying person's own | `{ref, text}` | a person replied to a delivered message |
| `POST /buttons/press` | the pressing person's own | `{button}` | a person pressed a button |

An **item** is `{id, kind, body, external_ref, buttons: [{id, label}], channel: {address}}`. `kind` is `text`, `approval` or `update`. A button's `id` is opaque to the bot. The service bearer is a static token (`INBOX_TOKEN`) or an OAuth 2.0 client-credentials grant (`INBOX_TOKEN_URL`, `INBOX_CLIENT_ID`, `INBOX_CLIENT_SECRET`), cached until a minute before it expires.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Receive a message (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a `text` item for a chat, **When** the bot leases it, **Then** the chat receives the text (split when long) and the service receives an ack whose `external_ref` is `<chat_id>:<message_id>`.
2. **Given** Telegram refuses the message, **When** delivery fails, **Then** the service receives a release with a retry delay (Telegram's own when it asked the bot to wait).
3. **Given** the service offers an item the bot already delivered, **When** it is leased again, **Then** it is acknowledged under the original reference and nothing is sent twice.

---

### User Story 2 - Decide with a button (Priority: P1)

**Acceptance Scenarios**:

1. **Given** an `approval` item with two buttons, **When** it is delivered, **Then** one message carries a button per entry, labelled with its `label`; two approvals in one chat are two independent messages.
2. **Given** a person who is linked, **When** they press a button, **Then** the bot reports the press under that person's own bearer and answers: decided (200), not allowed (403), already decided (409 `already_decided`), no longer exists (404).
3. **Given** a person who is not linked, **When** they press a button, **Then** they are told to link, and nothing reaches the service.
4. **Given** an `update` item naming a delivered message, **When** it is delivered, **Then** that message's text is replaced and its buttons removed.

---

### User Story 3 - Link a chat (Priority: P2)

**Acceptance Scenarios**:

1. **Given** a code, **When** a person sends `/link CODE` in a private chat, **Then** the bot reports the code with the chat id and their username, and says it linked or that the code is not valid or has expired.
2. **Given** a group, **When** someone sends `/link`, **Then** the bot asks them to do it privately and reports nothing.

### User Story 4 - Answer by replying (Priority: P2)

An item may carry an opaque `reply` reference, and its kind may be `question` (delivered like `approval`).

**Acceptance Scenarios**:

1. **Given** a delivered item with a `reply`, **When** a linked person replies to its message, **Then** the bot calls `POST /replies {ref, text}` under their own bearer, does not pass the text to the chat agent, and answers "Sent." (2xx) or shows the service's error message (4xx).
2. **Given** a reply to a message with no stored reference, **When** it arrives, **Then** it is handled as any other message.

## Known Defects and Gaps

- Forum topics are not addressed: an item goes to the chat, not to a topic.
- A button id must fit Telegram's 64-byte callback limit together with the two-character prefix; an item with a longer one is released with an error until the service stops offering it.
