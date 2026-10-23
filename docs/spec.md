# Telegram bot gateway — software requirements specification

| | |
|---|---|
| **Spec ID** | SPEC-TG-001 |
| **Status** | Implemented; not yet run against the live Telegram API |
| **Version** | 0.5.0 |
| **Last updated** | 2026-10-21 |
| **Implements** | this repository |
| **Related** | [`specs/`](../specs/glossary.md) |

Requirement keywords (**MUST**, **MUST NOT**, **SHOULD**, **MAY**) are used as defined in RFC 2119.

This specification is **executable**. Every requirement carries a stable id; `tests/test_spec_coverage.py` fails when a requirement marked *done* has no test claiming it, or when a test claims an id this document does not define. A test claims a requirement with a `# Covers: FR-LNK-01` line. Behavior changes here first, then in code. A requirement is `planned` until it is built and tested.

---

## 1. Purpose

A Telegram bot that is a client of any OpenAI-compatible Chat Completions endpoint. It works with any endpoint that speaks the same API (a model or an agent behind a gateway is just a `model` name) and depends on nothing specific to one provider. Its user experience follows the Hermes Agent Telegram adapter: DMs, groups, forum topics, replies, reactions, media and inline-button prompts. It adds forwarded-message handling, which Hermes lacks.

## 2. Glossary

| Term | Meaning |
|---|---|
| **Endpoint** | The OpenAI-compatible service the bot calls (`OPENAI_BASE_URL`). |
| **Link** | The record tying one Telegram user to one API key of the endpoint. |
| **Session** | One conversation: a message history plus settings, keyed by chat, topic and (in groups) user. |
| **Turn** | One request to the endpoint, including the tool-call round trips it needs. |
| **Trigger** | An incoming message the bot answers. |
| **Operator** | The person who runs the bot and approves links. |

## 3. Decisions of record

| Decision | Reason |
|---|---|
| Plain Chat Completions, no gateway-specific fields | Works with any endpoint; some endpoints drop images on their Responses route. |
| One API key per Telegram user | With an endpoint that identifies callers by key (some gateways do), stored credentials, threads and approvals belong to the key, so a shared key would merge everyone. With an endpoint that does not, the operator may give everyone the same key. |
| No allowlist; a user must be linked | Who may use the bot comes from the operator's approval of a link, not from a list of Telegram ids kept in the bot. |
| Operator approves every link | The approval is what stops a user claiming someone else's account. |
| State in a PostgreSQL database of its own | The bundled compose file runs a PostgreSQL container for it; any PostgreSQL database it owns will do. |
| Queue, never interrupt | A turn may run write tools on the endpoint's side; aborting mid-turn can hide a side effect. |
| No live-edit streaming | Costs an edit loop and a rate budget; the typing indicator covers the wait. |

## 4. Acceptance scenarios

| id | Scenario | Status |
|---|---|---|
| AS-01 | **Given** a linked user, **when** they DM the bot, **then** they get an answer from the endpoint under their own key. | done |
| AS-02 | **Given** an unlinked user, **when** they DM the bot, **then** they get a pairing code and nothing reaches the endpoint. | done |
| AS-03 | **Given** a group, **when** a member replies to the bot, **then** the bot answers in the same topic. | done |
| AS-04 | **Given** a write the endpoint asks to approve, **when** the owner taps Reject, **then** the endpoint receives the rejection and nothing is written. | done |
| AS-05 | **Given** a forwarded message, **when** it is sent to the bot, **then** the model sees where it came from. | done |

## 5. Requirements

### 5.1 Linking — `FR-LNK`

| id | Requirement | Status |
|---|---|---|
| FR-LNK-01 | A message from a user with no link MUST NOT reach the endpoint. | done |
| FR-LNK-02 | In a DM, `/start <username>` MUST create a pairing code (8 characters, no `0 O 1 I`, valid 1 hour) and show it to the user. | done |
| FR-LNK-03 | Pairing requests MUST be limited to one per user per 10 minutes and three pending per user. | done |
| FR-LNK-04 | The operator MUST be able to list pending codes, showing the claimed username and Telegram name, and approve one by supplying an API key on standard input. | done |
| FR-LNK-05 | An API key MUST be stored encrypted with a key from the environment and MUST NOT appear in a log, a reply or an error. | done |
| FR-LNK-06 | The operator MUST be able to unlink by Telegram id or username; the user's sessions MUST then stop working. | done |
| FR-LNK-07 | In a group, an unlinked user who triggers the bot MUST get one short "message me privately to link" reply, at most once per 10 minutes per user. | done |
| FR-LNK-08 | Linking MUST sit behind a port so another identity source can replace pairing without changing the rest. | done |
| FR-LNK-09 | The package MUST NOT import another product's code; a deployment script outside the package may issue the API key and pass it in. | done |
| FR-LNK-10 | A turn of a user whose stored key cannot be decrypted MUST be answered with a message saying the link must be renewed, not left without a reply. | done |

### 5.2 Sessions — `FR-SES`

| id | Requirement | Status |
|---|---|---|
| FR-SES-01 | A session key MUST be `chat[:thread]` in a DM and `chat[:thread]:user` in a group. | done |
| FR-SES-02 | Message history MUST be stored in the bot's own database and replayed to the endpoint exactly, including assistant `tool_calls`. | done |
| FR-SES-03 | A session MUST NOT expire; `/new` MUST start an empty one. | done |
| FR-SES-04 | The bot MUST store, per session, the model and the generation parameters set by the user, and send them on every request. | done |
| FR-SES-05 | The bot MUST store the text of messages it sent and received, by Telegram message id, so a reply can quote them. | done |
| FR-SES-06 | Replaying history MUST keep an assistant message byte-for-byte as returned; images in earlier turns MAY be replaced by a text placeholder. | done |

### 5.3 Incoming messages — `FR-INB`

| id | Requirement | Status |
|---|---|---|
| FR-INB-01 | In a DM every message from a linked user MUST be a trigger. | done |
| FR-INB-02 | In a group, a message MUST be a trigger only when it @mentions the bot, replies to a message of the bot, or is a `/command@bot`. | done |
| FR-INB-03 | In a group, a message that @mentions other bots but not this one MUST be ignored. | done |
| FR-INB-04 | Messages from other bots MUST be ignored, and a bot MUST NOT answer itself. | done |
| FR-INB-05 | A reply MUST be prefixed `[Replying to: "<text>"]`, using the user's own quote if they made one, else the text or caption of the replied message; media of the replied message MUST be attached. | done |
| FR-INB-06 | A forwarded message MUST be prefixed `[Forwarded from <name or title>, <date>]`, built from `forward_origin`, with a neutral name when the origin is hidden. | done |
| FR-INB-07 | `message_thread_id` MUST be kept only for real topic messages; the General topic MUST be thread `1`; a reply's thread id outside a topic MUST be dropped. | done |
| FR-INB-08 | A photo, an image document or an album MUST be sent as `image_url` data URLs; an album and photos sent within 0.8 s MUST become one message. | done |
| FR-INB-09 | A text document up to 100 KB MUST be inlined as `[Content of <name>]:`; any other document MUST become a text placeholder with its name and size. | done |
| FR-INB-10 | A sticker MUST become a text placeholder with its emoji; a location or venue MUST become text with coordinates. | done |
| FR-INB-11 | A caption MUST be treated as the message text. | done |
| FR-INB-12 | A voice note or audio file MUST get a short reply saying it is not supported, and MUST NOT reach the endpoint. | done |
| FR-INB-13 | Text messages arriving while the session is idle MUST be merged after a short quiet period; a chunk near 4,000 characters MUST wait longer for the next part of a split message. | done |
| FR-INB-14 | A media download failure MUST be reported to the user. | done |

### 5.4 Turns and busy sessions — `FR-TRN`

| id | Requirement | Status |
|---|---|---|
| FR-TRN-01 | A turn MUST call `POST /v1/chat/completions` with the stored history and the session's model and parameters. | done |
| FR-TRN-02 | Tool-call round trips MUST be resolved by the bot only for the client tools it declares (`clarify`, and those of capability 007); any other tool call from the endpoint MUST be reported to the user as unsupported. | done |
| FR-TRN-03 | Messages arriving during a turn MUST be queued and merged into the next turn of the same session. | done |
| FR-TRN-04 | `/stop` MUST cancel the running request, discard the queue, and MUST NOT leave an unanswered tool call in the stored history. | done |
| FR-TRN-05 | Different sessions MUST run concurrently; turns of one session MUST run in order. | done |
| FR-TRN-06 | An endpoint error MUST be shown to the user with its message, and the history MUST stay as it was before the turn. | done |
| FR-TRN-07 | A request MUST NOT outlive a configurable timeout (default 10 minutes). | done |
| FR-TRN-08 | Every request MUST begin with a system message telling the model it is talking in Telegram: keep answers short unless asked, use only Telegram-friendly Markdown and a few emojis, do not name the sources of an answer unless asked, reply in the user's language, and shorter still in a group. The message MUST NOT be stored in the history. | done |
| FR-TRN-09 | The history sent to the endpoint MUST stay within `HISTORY_MAX_CHARS` by dropping the oldest whole turns, never the turn being answered. | done |
| FR-TRN-10 | One user MUST NOT have more than `MAX_CONCURRENT_TURNS` turns running at once across chats; further turns wait. | done |

### 5.5 Outgoing messages — `FR-OUT`

| id | Requirement | Status |
|---|---|---|
| FR-OUT-01 | While a turn runs the bot MUST send a `typing` action every 2 seconds. | done |
| FR-OUT-02 | When reactions are enabled (default), the bot MUST react 👀 only to a message that waits behind a running turn or whose turn has run longer than `REACTION_DELAY` seconds (default 10), and MUST remove the reaction when that message's turn ends or is stopped. It MUST NOT react to a message answered promptly. A failure to react MUST be ignored. | done |
| FR-OUT-03 | Markdown MUST be converted to MarkdownV2 following Hermes's rules: code protected, headings as bold, tables as bullets or code, all other special characters escaped. | done |
| FR-OUT-04 | When Telegram rejects the formatting, the same text MUST be re-sent as plain text. | done |
| FR-OUT-05 | A message over 4,096 UTF-16 units MUST be split, each part suffixed `(i/n)`. | done |
| FR-OUT-06 | Only the first part MUST be a reply to the trigger; in a group forum topic no part is a reply. | done |
| FR-OUT-07 | Sending MUST pass `message_thread_id`, and on "thread not found" MUST retry without it. | done |
| FR-OUT-08 | Final answers and prompts MUST notify; status messages MUST be silent. | done |
| FR-OUT-09 | When progress display is enabled (default off), `reasoning_content` of the endpoint MUST appear as one silent message edited in place and removed after the answer. | done |
| FR-OUT-10 | Telegram flood control MUST be honored by waiting the `retry_after` it states. | done |
| FR-OUT-11 | An empty answer MUST send nothing and MUST NOT count as a failure. | done |
| FR-OUT-12 | A send that failed because the connection could not be made MUST be retried after 1, 2, 4 and 8 seconds, a timed-out send MUST NOT, and the session MUST be saved only after the reply was sent. | done |

### 5.6 Questions and approvals — `FR-ASK`

| id | Requirement | Status |
|---|---|---|
| FR-ASK-01 | Every request MUST declare the function tool `clarify`, taking `questions`, a list of `{question, choices}`; the first question is shown. | done |
| FR-ASK-02 | A call to `clarify` MUST be shown as a message with one inline button per option and a button for a free-text answer. | done |
| FR-ASK-03 | A tap MUST be sent to the endpoint as the tool message answering that call; a free-text answer MUST be the user's next message. | done |
| FR-ASK-04 | An approval card (options Approve and Reject) MUST be rendered like any other `clarify` call. | done |
| FR-ASK-05 | Only the user the session belongs to MUST be able to answer; a tap by anyone else MUST be refused with an alert. | done |
| FR-ASK-06 | After an answer the card MUST be edited to show the outcome and the buttons removed. | done |
| FR-ASK-07 | A pending question MUST survive a restart of the bot; one older than 24 hours MUST be shown as expired and cancelled. | done |

### 5.6.1 Client tools — `FR-TLS`

| id | Requirement | Status |
|---|---|---|
| FR-TLS-01 | Every request MUST declare `clarify` followed by the client tools named in `TOOLS` (all by default, none for `none`), and the bot MUST refuse to start when `TOOLS` names an unknown tool. | done |
| FR-TLS-02 | An immediate client tool call MUST be carried out in the chat of the turn, never one taken from its arguments, answered with a tool message holding the result, and the turn MUST continue; invalid arguments or a failed delivery MUST be that result and MUST NOT fail the turn. | done |
| FR-TLS-03 | `send_file` MUST send a document named by the last path part of `filename` with the `content` as UTF-8, refusing empty content and content over `TOOL_MAX_FILE_BYTES`. | done |
| FR-TLS-04 | `send_image` MUST take exactly one of `url` (http or https, fetched by Telegram, never by the bot) and `base64` (at most 10 MiB) and send a photo. | done |
| FR-TLS-05 | `send_buttons` MUST send `text` with 1 to 8 buttons, one per row, each opening an http(s) `url` or copying a `copy` text. | done |
| FR-TLS-06 | `notify` MUST send `text` as a silent message and the turn MUST continue. | done |
| FR-TLS-07 | `react` MUST set an emoji Telegram allows on the user's latest message and the reaction MUST survive the end of the turn and the 👀 chrome. | done |
| FR-TLS-08 | `get_context` MUST return the chat type, whether it is a topic, the user's language and the UTC time, and nothing that identifies the user. | done |
| FR-TLS-09 | `request_approval` MUST show a card with the action, the effect when given, and exactly the buttons Allow and Reject, answered through the open-question mechanism of `clarify`. | done |
| FR-TLS-10 | At most 10 immediate calls MUST be carried out in one turn; the rest MUST be answered with a refusal. | done |
| FR-TLS-11 | The immediate calls of a round MUST run before a suspending call is shown, and a second suspending call MUST be answered as unsupported. | done |

### 5.7 Commands and settings — `FR-CMD`

| id | Requirement | Status |
|---|---|---|
| FR-CMD-01 | The bot MUST support `/start`, `/new`, `/stop`, `/whoami`, `/help`, and MUST register its command menu with Telegram. | done |
| FR-CMD-02 | `/model` MUST show the endpoint's `GET /v1/models` as buttons; `/model <id>` MUST set it without the picker. | done |
| FR-CMD-03 | `/reasoning` MUST set `reasoning_effort` with buttons none, minimal, low, medium, high and default. | done |
| FR-CMD-04 | `/set <param> <value>` and `/unset <param>` MUST change one of `temperature`, `top_p`, `max_tokens`, `seed`, `verbosity`, `presence_penalty`, `frequency_penalty`, `stop`. | done |
| FR-CMD-05 | `/settings` MUST show the model and every parameter in effect, with a reset button. | done |
| FR-CMD-06 | Values MUST be checked for type and range before storing; a refusal by the endpoint MUST be shown unchanged. | done |
| FR-CMD-07 | In a group a command MUST act on the sender's own session. | done |
| FR-CMD-08 | `/whoami` MUST show the Telegram id, the linked username and the session key, and no secret. | done |

### 5.8 Transport and operation — `FR-OPS`

| id | Requirement | Status |
|---|---|---|
| FR-OPS-01 | The bot MUST receive updates by long polling; webhook mode MAY be enabled with `WEBHOOK_URL` and MUST then require `WEBHOOK_SECRET`. | done |
| FR-OPS-02 | Updates queued while the bot was offline MUST be dropped on a cold start. | done |
| FR-OPS-03 | A repeated `update_id` MUST be ignored. | done |
| FR-OPS-04 | The bot MUST apply its own SQL migrations at startup, in order, once. | done |
| FR-OPS-05 | The bot MUST publish no port and answer a health check for the container that fails while Telegram is unreachable. | done |
| FR-OPS-06 | Secrets MUST come from the environment only and MUST NOT be logged. | done |
| FR-OPS-07 | Two bots polling one token MUST be reported plainly in the log. | done |
| FR-OPS-08 | When the bot stops, each chat with an unanswered message MUST be told once to send it again. | done |
| FR-OPS-09 | Message texts older than `MESSAGE_TEXT_DAYS` and expired pairing codes MUST be deleted at start and daily. | done |

### 5.9 Configuration — `FR-CFG`

| id | Requirement | Status |
|---|---|---|
| FR-CFG-01 | Variables: `BOT_TOKEN`, `OPENAI_BASE_URL`, `OPENAI_API_KEY` (optional, for `/v1/models` before a user is linked), `DEFAULT_MODEL`, `DATABASE_URL`, `CREDS_KEY`, `REACTIONS`, `REACTION_DELAY`, `SHOW_PROGRESS`, `REQUEST_TIMEOUT`, `TOOLS`, `TOOL_MAX_FILE_BYTES`, `WEBHOOK_URL`, `WEBHOOK_SECRET`. | done |
| FR-CFG-02 | The module MUST NOT name a model, an organization or a user in a tracked file. | done |
| FR-CFG-03 | A missing required variable MUST stop the start with a message naming it. | done |

### 5.10 Architecture — `NFR-ARC`

| id | Requirement | Status |
|---|---|---|
| NFR-ARC-01 | The code MUST be hexagonal: `domain/` → `application/` → `adapters/`, and `tests/test_boundaries.py` MUST fail if `domain/` or `application/` import anything that does I/O. | done |
| NFR-ARC-02 | The repository MUST carry its own compose file, env template, make targets, scripts and docs. | done |
| NFR-ARC-03 | The service MUST publish no port, and its database role MUST reach only its own database. | done |
| NFR-ARC-04 | The repository MUST run on its own, with no file outside it and no dependency on any other product. | done |

## 6. Out of scope (v1)

| Item | Reason |
|---|---|
| Voice notes and speech-to-text | Decided out for v1 (FR-INB-12 refuses them). |
| Live-edit streaming | Costs an edit loop and a rate budget; typing is enough. |
| `/retry` | Rarely needed. |
| Detecting `approve <code>` in reply text | The declared `clarify` tool makes an endpoint that asks for approval do so by tool call. |
| Interrupt and steer modes | Aborting a turn that runs write tools can hide a side effect. |
| Hermes `/topic` DM lobby, skill-bound topics, `/compress`, `/undo`, `/bg`, `/usage` | Not part of the experience we want to copy first. |
| Crash-redelivery ledger | Cost exceeds value for a chat client. |
| `sendRichMessage` | MarkdownV2 with a plain fallback is enough. |
| Observing unmentioned group messages | Privacy cost; the bot answers only when addressed. |
| Sticker vision | Placeholder is enough. |
| Keycloak linking | Planned as a second adapter of FR-LNK-08. |

## 7. Repository layout

```
./
  AGENTS.md  README.md  pyproject.toml  Dockerfile  Makefile
  compose.yaml          # the bot and its own PostgreSQL
  .env.example          # copied to .env by `make setup` (ignored by git)
  docs/spec.md  docs/OPERATOR_GUIDE.md
  migrations/001_init.sql
  scripts/              # prepare.sh, test-services.sh, lib/env.sh
  specs/                # capability specs and glossary
  .specify/memory/constitution.md
  src/telegram_bot_gateway/{domain,application,adapters,cli}
  tests/
```

`make setup` creates `.env`, `make up` starts the bot and its database, `make pair CODE=…` links a user with an API key given at a prompt.

## 8. Open points

| # | Question | Default |
|---|---|---|
| 1 | Is the bot's `OPENAI_API_KEY` needed before linking, only to list models for `/model`? | Use the user's own key; keep the variable optional. |
| 2 | Group sender identity: should the model see who wrote each message in a group topic shared by users? | No; sessions are per user. |
| 3 | `clarify` for endpoints that never call it: does declaring it change their behavior? | Declared always; checked against mock servers and one gateway only. An endpoint that rejects `tools` is not compatible. |

## 9. Baseline specs and traceability

This document stays the short, test-gated registry of requirement ids. The behaviour is specified in detail, with stories, exact rules, data model, contracts, decisions and known defects, in the Spec Kit directories under [`../specs/`](../specs/glossary.md), whose terms follow [`../specs/glossary.md`](../specs/glossary.md). A requirement of a directory is cited as `<number>/FR-###`.

| Directory | Capability |
|---|---|
| `001-account-linking` | Pairing, operator approval, unlinking, the gate on unlinked users |
| `002-conversations` | Turns, history, queue, stop, new, settings and commands |
| `003-incoming-messages` | Triggers, groups, topics, replies, forwards, media, batching |
| `004-replies-and-feedback` | Formatting, splitting, typing, reactions, progress, delivery fallbacks |
| `005-questions-and-approvals` | The `clarify` tool, cards, answers, expiry |
| `006-operations` | Configuration, start-up, health, deployment, database role |
| `007-client-tools` | The tools the bot carries out itself: approval, files, images, buttons, notes, reactions, context |

| Id here | Specified in |
|---|---|
| FR-LNK-01 | 001/FR-001, 001/FR-015, 001/FR-017 |
| FR-LNK-02 | 001/FR-002, 001/FR-003 |
| FR-LNK-03 | 001/FR-004, 001/FR-005 |
| FR-LNK-04 | 001/FR-007, 001/FR-009, 001/FR-010, 001/FR-011 |
| FR-LNK-05 | 001/FR-010, 001/FR-014 |
| FR-LNK-06 | 001/FR-013 |
| FR-LNK-07 | 001/FR-016 |
| FR-LNK-08 | 001 research (replaceable step), constitution (Additional Constraints) |
| FR-LNK-09 | 001/FR-012, constitution I |
| FR-LNK-10 | 001/FR-020 |
| FR-SES-01 | 002/FR-019 |
| FR-SES-02 | 002/FR-001, 002/FR-002, 002/FR-018 |
| FR-SES-03 | 002/FR-017, 002/FR-018 |
| FR-SES-04 | 002/FR-025 |
| FR-SES-05 | 003/FR-022, 004/FR-019 |
| FR-SES-06 | 002/FR-002, 002/FR-003 |
| FR-INB-01 | 003/FR-002 |
| FR-INB-02 | 003/FR-003 |
| FR-INB-03 | 003/FR-004 |
| FR-INB-04 | 003/FR-005 |
| FR-INB-05 | 003/FR-011 |
| FR-INB-06 | 003/FR-012 |
| FR-INB-07 | 003/FR-021 |
| FR-INB-08 | 003/FR-013, 003/FR-020 |
| FR-INB-09 | 003/FR-014, 003/FR-015 |
| FR-INB-10 | 003/FR-016 |
| FR-INB-11 | 003/FR-010 |
| FR-INB-12 | 003/FR-009 |
| FR-INB-13 | 003/FR-020, 002/FR-013 |
| FR-INB-14 | 003/FR-018 |
| FR-TRN-01 | 002/FR-001 |
| FR-TRN-02 | 002/FR-006 |
| FR-TRN-03 | 002/FR-014 |
| FR-TRN-04 | 002/FR-016, 002/FR-009 |
| FR-TRN-05 | 002/FR-015 |
| FR-TRN-06 | 002/FR-009, 002/FR-010, 002/FR-011 |
| FR-TRN-07 | 002/FR-012 |
| FR-TRN-08 | 002/FR-001, 002 `contracts/endpoint.md` (system note) |
| FR-TRN-09 | 002/FR-029 |
| FR-TRN-10 | 002/FR-030 |
| FR-OUT-01 | 004/FR-001 |
| FR-OUT-02 | 004/FR-002, 004/FR-003, 004/FR-004 |
| FR-OUT-03 | 004/FR-010, 004/FR-011 |
| FR-OUT-04 | 004/FR-012 |
| FR-OUT-05 | 004/FR-006, 004/FR-007, 004/FR-008, 004/FR-009 |
| FR-OUT-06 | 004/FR-013 |
| FR-OUT-07 | 004/FR-014 |
| FR-OUT-08 | 004/FR-017 |
| FR-OUT-09 | 004/FR-005 |
| FR-OUT-10 | 004/FR-015 |
| FR-OUT-11 | 004/FR-020, 002/FR-007 |
| FR-OUT-12 | 004/FR-022, 002/FR-008 |
| FR-ASK-01 | 005 `contracts/clarify-tool.md`, 005/FR-001 |
| FR-ASK-02 | 005/FR-003 |
| FR-ASK-03 | 005/FR-005, 005/FR-008, 005/FR-009 |
| FR-ASK-04 | 005/FR-003 |
| FR-ASK-05 | 005/FR-005, 005/FR-006 |
| FR-ASK-06 | 005/FR-005 |
| FR-ASK-07 | 005/FR-010, 005/FR-011, 005/FR-013 |
| FR-TLS-01 | 007/FR-001, 007/FR-002 |
| FR-TLS-02 | 007/FR-003, 007/FR-004, 007/FR-005 |
| FR-TLS-03 | 007/FR-006 |
| FR-TLS-04 | 007/FR-007 |
| FR-TLS-05 | 007/FR-008 |
| FR-TLS-06 | 007/FR-009 |
| FR-TLS-07 | 007/FR-010 |
| FR-TLS-08 | 007/FR-011 |
| FR-TLS-09 | 007/FR-012 |
| FR-TLS-10 | 007/FR-013 |
| FR-TLS-11 | 007/FR-014 |
| FR-CMD-01 | 002/FR-028, 006/FR-008, 001/FR-018 |
| FR-CMD-02 | 002/FR-021 |
| FR-CMD-03 | 002/FR-022 |
| FR-CMD-04 | 002/FR-023, 002/FR-024, 002/FR-027 |
| FR-CMD-05 | 002/FR-026 |
| FR-CMD-06 | 002/FR-024 |
| FR-CMD-07 | 002/FR-020 |
| FR-CMD-08 | 001/FR-018 |
| FR-OPS-01 | 006/FR-005, 006/FR-006 |
| FR-OPS-02 | 006/FR-005 |
| FR-OPS-03 | 003/FR-001 |
| FR-OPS-04 | 006/FR-007 |
| FR-OPS-05 | 006/FR-014, 006/FR-015, 006/FR-009 |
| FR-OPS-06 | 006/FR-010, 006 SC-005 |
| FR-OPS-07 | 006/FR-011 |
| FR-OPS-08 | 006/FR-020 |
| FR-OPS-09 | 006/FR-021, 002/FR-031, 001/FR-019 |
| FR-CFG-01 | 006/FR-001 |
| FR-CFG-02 | constitution I |
| FR-CFG-03 | 006/FR-002 |
| NFR-ARC-01 to NFR-ARC-04 | constitution I, III, V and each plan's Constitution Check |
| AS-01 | 002 User Story 1 |
| AS-02 | 001 User Stories 1 and 3 |
| AS-03 | 003 User Story 2, 004 User Story 5 |
| AS-04 | 005 User Story 1 |
| AS-05 | 003 User Story 3 |

No known defects or gaps are open. Each directory's `Known Defects and Gaps` section lists any that are found later, and a fix removes its entry; `tests/test_fixed_defects.py` holds the regression tests of the ones fixed so far.
