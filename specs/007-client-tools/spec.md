# Feature Specification: Client Tools

**Created**: 2026-10-23

**Status**: Accepted

**Input**: A request to let the endpoint use Telegram features through tools, as it already does for questions.

Terms follow [`../glossary.md`](../glossary.md).

A **client tool** is a function the bot declares in the request and carries out itself, in Telegram. It is not a skill, a script or a tool of the endpoint: the bot runs nothing else. `clarify` (capability 005) is the first client tool; this capability adds `request_approval`, `send_file`, `send_image`, `send_buttons`, `notify`, `react` and `get_context`.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Receive a file (Priority: P1)

The endpoint can hand the user a document: a report, a script, a table.

**Why this priority**: Long or structured output does not belong in a chat bubble.

**Independent Test**: Have the endpoint call `send_file` with a name and text; see a document with that name arrive, and the turn go on.

**Acceptance Scenarios**:

1. **Given** a call to `send_file` with `report.md` and text, **When** the bot runs it, **Then** the chat receives a document named `report.md` holding the text, and the endpoint receives "Sent report.md (<size>)".
2. **Given** a file name with a path (`../../etc/x`), **When** the bot runs the call, **Then** only the last part is used.
3. **Given** content over the limit, **When** the bot runs the call, **Then** nothing is sent and the endpoint receives the reason.

---

### User Story 2 - Allow or reject an action (Priority: P1)

The endpoint asks permission for an action with a plain description, and the user answers with one of two buttons.

**Why this priority**: Approvals guard writes. A dedicated tool is clearer for the model than a question with two special choices.

**Independent Test**: Call `request_approval` with an action; tap Reject as another member (refused), then as the owner (the endpoint receives `Reject`).

**Acceptance Scenarios**:

1. **Given** a call to `request_approval`, **When** the turn ends, **Then** the chat shows a card with the action in bold, the effect below it, and exactly the buttons `Allow` and `Reject`.
2. **Given** that card, **When** the owner taps a button, **Then** the endpoint receives `Allow` or `Reject`, and the card shows the outcome like any card.
3. **Given** that card, **When** the owner sends a message instead, **Then** the message is the answer, as for any open question.

---

### User Story 3 - Show an image, links and copyable text (Priority: P2)

The endpoint can send a picture, and a message with buttons that open a link or copy a text.

**Independent Test**: Call `send_image` with a URL and `send_buttons` with a link and a copy button; see both in the chat.

**Acceptance Scenarios**:

1. **Given** `send_image` with a URL, **When** the bot runs it, **Then** Telegram fetches the image from the URL; the bot never does.
2. **Given** `send_image` with base64 data, **When** the bot runs it, **Then** the decoded bytes are sent as a photo.
3. **Given** `send_buttons` with a text, a link button and a copy button, **When** the bot runs it, **Then** one message shows one button per row, the link opening the URL and the copy button copying its text.
4. **Given** a link that does not start with `http://` or `https://`, **When** the bot runs the call, **Then** nothing is sent and the endpoint receives the reason.

---

### User Story 4 - Report progress and react (Priority: P2)

The endpoint can tell the user what it is doing during a long turn, and can react to the user's message.

**Independent Test**: Call `notify` and `react` in one turn; see a silent note and a reaction on the user's message that stays after the turn.

**Acceptance Scenarios**:

1. **Given** `notify` with a text, **When** the bot runs it, **Then** a silent message with that text is sent and the turn goes on.
2. **Given** `react` with an allowed emoji, **When** the bot runs it, **Then** the user's latest message carries that reaction, and the bot's own 👀 chrome neither replaces nor removes it.
3. **Given** `react` with an emoji Telegram does not allow, **When** the bot runs it, **Then** the endpoint receives the reason.

---

### User Story 5 - Know where it is talking (Priority: P3)

`get_context` tells the endpoint the chat type, whether it is a topic, the user's language and the time in UTC.

**Acceptance Scenarios**:

1. **Given** a call to `get_context`, **When** the bot runs it, **Then** the endpoint receives these four facts as JSON and nothing that identifies the user.

---

### User Story 6 - Choose which tools are offered (Priority: P3)

The operator decides which client tools are declared.

**Acceptance Scenarios**:

1. **Given** `TOOLS` unset, **When** a request is made, **Then** it declares `clarify` and every client tool.
2. **Given** `TOOLS=send_file,notify`, **Then** it declares `clarify`, `send_file` and `notify`. A call to any other name is answered "This client cannot run that tool."
3. **Given** `TOOLS=none`, **Then** it declares `clarify` alone.
4. **Given** `TOOLS` naming a tool that does not exist, **Then** the bot refuses to start and names it.

### Edge Cases

- A delivery failure (Telegram refuses the file, the user blocked the bot) is the tool's result; the turn goes on so the endpoint can adapt.
- More than 10 immediate calls in one turn: the rest are answered "Too many actions in one turn."
- A round may mix immediate calls with one suspending call (`clarify` or `request_approval`); the immediate ones run first, and a second suspending call is answered "This client cannot run that tool."
- After a button answer there is no message of the user to react to; `react` then answers "There is no message to react to."
- `/stop` during a turn: files already sent stay sent (queue, never interrupt); the session is not saved.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST declare, on every request, `clarify` followed by the client tools named in `TOOLS` (all by default, none for `none`), in the order of `contracts/tools.md`.
- **FR-002**: System MUST refuse to start when `TOOLS` names an unknown tool.
- **FR-003**: System MUST carry out an immediate tool call in the chat of the turn, answer it with a tool message holding the result text, and continue the turn. The chat MUST NOT come from the arguments.
- **FR-004**: System MUST answer a call whose arguments are not valid JSON, lack a required field or break a limit with a tool message giving the reason, and MUST send nothing.
- **FR-005**: System MUST answer a failed delivery with a tool message giving the reason, and MUST continue the turn.
- **FR-006**: `send_file` MUST send a document named by the last path part of `filename`, with the text `content` encoded as UTF-8, refusing empty content and content over `TOOL_MAX_FILE_BYTES`.
- **FR-007**: `send_image` MUST take exactly one of `url` (http or https, passed to Telegram) and `base64` (decoded, at most 10 MiB) and send a photo.
- **FR-008**: `send_buttons` MUST send `text` with 1 to 8 buttons, one per row, each with a label of at most 64 characters and exactly one of `url` (http or https) and `copy` (at most 256 characters).
- **FR-009**: `notify` MUST send `text` as a silent message.
- **FR-010**: `react` MUST set one of Telegram's allowed emoji on the user's latest message and MUST keep the reaction when the turn ends.
- **FR-011**: `get_context` MUST return `chat_type`, `topic`, `language` (null when unknown) and `utc_now`, and nothing else.
- **FR-012**: `request_approval` MUST show a card with `action` in bold, `effect` when given, and exactly the buttons `Allow` and `Reject`, and MUST answer through the open-question mechanism of capability 005 (owner only, 24-hour expiry, restart-proof, cancelled by `/new`).
- **FR-013**: System MUST carry out at most 10 immediate calls in one turn and answer the rest "Too many actions in one turn."
- **FR-014**: System MUST run the immediate calls of a round before showing a suspending one, and MUST answer a second suspending call "This client cannot run that tool."

### Key Entities

- **Client tool**: a declared function the bot carries out itself; *immediate* when the turn continues after it, *suspending* when it waits for the user.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: No request carries a tool the operator did not enable, except `clarify`.
- **SC-002**: No tool sends to a chat other than the one of the turn.
- **SC-003**: No tool makes the bot fetch a URL.

## Assumptions

- Telegram has no timezone for a user, so `get_context` gives the time in UTC only.
- The endpoint accepts a `tools` array with several functions.

## Known Defects and Gaps

None.
