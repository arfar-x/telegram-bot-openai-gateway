# Feature Specification: Account Linking

**Created**: 2026-10-21

**Status**: Accepted

**Input**: Existing system behavior

Terms follow [`../glossary.md`](../glossary.md).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ask to be linked (Priority: P1)

A person who is not yet linked opens a private chat with the bot and asks to be linked, giving the username the endpoint knows them by. The bot gives them a pairing code to hand to the operator.

**Why this priority**: Nobody can use the bot until they are linked, and the bot has no list of allowed users; linking is the only way in.

**Independent Test**: In a private chat with an unlinked user, send `/start ann@example.org` and receive a code of 8 characters; nothing reaches the endpoint.

**Acceptance Scenarios**:

1. **Given** an unlinked user in a private chat, **When** they send `/start <username>`, **Then** the bot replies with a pairing code and says it is valid for one hour and that the operator links them.
2. **Given** an unlinked user, **When** they send `/start` with no username, **Then** the bot replies that they are not linked and tells them to send `/start <your username>`.
3. **Given** a user who received a code less than 10 minutes ago, **When** they send `/start <username>` again, **Then** the bot replies that they asked recently and creates no new code.
4. **Given** a user with three codes that are less than one hour old and the newest is at least 10 minutes old, **When** they send `/start <username>`, **Then** the bot replies that they have too many open codes and creates no new code.
5. **Given** an unlinked user in a group, **When** they send `/start <username>`, **Then** the bot replies that they must message it privately and creates no code.
6. **Given** a linked user, **When** they send `/start`, **Then** the bot replies with the username they are linked as and invites them to send a message.

---

### User Story 2 - Operator approves a code (Priority: P1)

The operator sees who asked for each open code, checks that the person is who they say they are, and approves the code with an API key for that username. The user is told they are linked.

**Why this priority**: The operator's approval is the only thing that stops a person claiming another person's account.

**Independent Test**: Create a code as an unlinked user, list open codes as the operator, approve the code with an API key, and confirm the user can now chat and receives a confirmation message.

**Acceptance Scenarios**:

1. **Given** open codes, **When** the operator lists them, **Then** each shows the code, the username given, the Telegram name and the Telegram id; with no open codes the operator sees "no open codes".
2. **Given** a live code, **When** the operator approves it with an API key, **Then** the user is linked, the code is removed, the key is stored encrypted, and the user receives "You are linked. Send me a message to begin."
3. **Given** a code typed in lower case or with spaces or hyphens, **When** the operator approves it, **Then** it is matched as if typed in upper case without spaces or hyphens.
4. **Given** a code that is unknown or at least one hour old, **When** the operator approves or shows it, **Then** the command fails with "unknown or expired code" and nothing changes.
5. **Given** no API key on standard input, **When** the operator approves a code, **Then** the command fails with "expected the API key on standard input" and the code stays open.
6. **Given** a user who is already linked, **When** the operator approves a new code from that user, **Then** the link is replaced: the new username, name and key take over.
7. **Given** the operator's make target, **When** it runs for a live code, **Then** it shows who asked, asks for the API key at a prompt that does not echo it, and approves the code with it, so the key is not shown or written anywhere else.

---

### User Story 3 - Unlinked users are kept out (Priority: P1)

Whatever an unlinked person sends, nothing reaches the endpoint, and they are told how to get linked.

**Why this priority**: Who may use the bot is decided by the operator's approval; a message from a stranger must not run work under anyone's key.

**Independent Test**: As an unlinked user, send a message, a command and a button tap; confirm the endpoint receives nothing and each gets the linking reply.

**Acceptance Scenarios**:

1. **Given** an unlinked user in a private chat, **When** they send any message that is not a command, **Then** the bot replies "You are not linked yet. Send /start <your username> here and I will give you a code for the operator." and the message is not queued.
2. **Given** an unlinked user in a group who triggers the bot, **When** the bot replies, **Then** it says "Message me privately to link your account first.", and it says this at most once per 10 minutes for that user.
3. **Given** an unlinked user, **When** they use `/new`, `/model`, `/reasoning`, `/set`, `/unset` or `/settings`, **Then** they get the linking reply and nothing changes.
4. **Given** an unlinked user, **When** they use `/stop`, `/help` or `/whoami`, **Then** the command answers (`/whoami` shows that they are not linked).
5. **Given** any user, **When** they send `/whoami`, **Then** they see their Telegram id, whether they are linked and as whom, and the session key (the identifier of the session in that chat), and never an API key.
6. **Given** an unlinked user who taps a settings button, **When** the tap arrives, **Then** an alert says to link the account first.
7. **Given** a message already waiting for its turn, **When** the user's link is removed before the turn starts, **Then** the bot sends the linking reply instead of calling the endpoint.

---

### User Story 4 - Operator removes a link (Priority: P2)

The operator removes a link by Telegram id or by username, and the user's sessions are removed with it.

**Why this priority**: Access has to be revocable, but it is used far less than linking.

**Independent Test**: Link a user, give them a session, unlink by username, and confirm the link and every session of that user are gone and their next message gets the linking reply.

**Acceptance Scenarios**:

1. **Given** a linked user, **When** the operator unlinks by Telegram id, **Then** the link and all sessions of that user are removed and the command reports "removed 1 link(s)".
2. **Given** several links with the same username, **When** the operator unlinks by that username, **Then** all of them are removed.
3. **Given** no matching link, **When** the operator unlinks, **Then** the command reports "removed 0 link(s)" and fails.
4. **Given** neither an id nor a username, **When** the operator unlinks, **Then** the command fails with "give --telegram-id or --username".
5. **Given** the operator lists links, **When** the list is shown, **Then** it has the Telegram id, username and name of each, and never an API key.

---

### User Story 5 - Sign in with the issuer (Priority: P1)

When the bot runs with `LINK_MODE=device`, a person links themselves: they send `/login`, open the address the bot shows on another screen, enter the code and approve at the issuer. The bot then answers their messages under an access token that identifies them, and they can sign out with `/logout`.

**Why this priority**: The operator approving every pairing code does not scale, and the issuer's approval is the user's own.

**Independent Test**: With a fake issuer, send `/login`, approve, send a message and see the endpoint receive the issuer's access token; make the issuer refuse the next refresh and see the user told to sign in again with nothing sent to the endpoint.

**Acceptance Scenarios**:

1. **Given** device mode and an unlinked user in a private chat, **When** they send `/login`, **Then** the bot shows the verification address, the code and the minutes left, and later tells them they are signed in once the issuer approves.
2. **Given** a login in progress, **When** the issuer answers `authorization_pending`, **Then** the bot waits the interval; on `slow_down` it adds 5 seconds; on `access_denied` or `expired_token` it tells the user which and removes the login.
3. **Given** a signed-in user, **When** they message the bot, **Then** the endpoint receives a valid access token as the bearer, refreshed only when the one held has less than 60 seconds left.
4. **Given** the issuer refuses a refresh with `invalid_grant`, **When** the user messages the bot, **Then** the link is marked expired, the stored refresh token is cleared, the user is told to `/login` again and nothing reaches the endpoint.
5. **Given** the issuer is unreachable, **When** the user messages the bot, **Then** they are asked to try again and the link stays active.
6. **Given** a signed-in user, **When** they send `/logout`, **Then** the refresh token is revoked at the issuer when it has a revocation endpoint, the link is deleted either way, and the bot says which happened.
7. **Given** device mode and an unlinked user, **When** they send any message, **Then** they are invited to send `/login` and receive no pairing code.

---

### Edge Cases

- A code is made of 8 characters drawn from the letters A–Z without I and O and the digits 2–9. Two users cannot hold the same code; a clash is not handled (the creation fails).
- The username in a request is free text, taken as the words after `/start` joined by single spaces. It is not checked against the endpoint.
- Expired codes are deleted: at the next pairing request, and by a daily clean-up.
- Approving a code does not check that the key works.
- If the user cannot be told that they are linked (no bot token in the operator's environment, or Telegram refuses), the link is still made; the operator sees "linked, but the user could not be notified" only when sending was attempted and failed.
- The notice for unlinked group users is remembered in memory only; after a restart it can repeat sooner.
- A stored key that cannot be decrypted with the configured key is reported to the user as a link that must be renewed. So is a refresh token that cannot be.
- The access token of a signed-in user is held in memory only; after a restart the first turn refreshes.
- A user whose link is `expired` is treated as unlinked, except that the invitation says their sign-in expired.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST ignore, for every purpose except linking itself, any message from a user who has no link, and MUST NOT call the endpoint for them.
- **FR-002**: System MUST create a pairing code only for a `/start` sent in a private chat by an unlinked user who gave a username.
- **FR-003**: System MUST make a pairing code of 8 characters chosen uniformly from the letters A–Z without I and O and the digits 2–9, valid for 3,600 seconds from creation.
- **FR-004**: System MUST refuse a new code when the user's newest live code is less than 600 seconds old, and otherwise when the user already holds 3 live codes; the first rule is checked first.
- **FR-005**: System MUST reply to a refused code request with the reply for its reason and MUST leave stored codes unchanged.
- **FR-006**: System MUST store with each code the Telegram id, the username given, the user's full Telegram name, the chat id and the creation time.
- **FR-007**: System MUST let the operator list the codes younger than 3,600 seconds, and show one code in full or as one field (username, Telegram name or Telegram id).
- **FR-008**: System MUST match a code case-insensitively and ignore spaces and hyphens in it.
- **FR-009**: System MUST approve a code only with an API key read from the first line of standard input, trimmed, and MUST fail without changing anything when that line is empty.
- **FR-010**: System MUST, on approval, store the key encrypted with the configured key, record the username, name and Telegram id from the code, remove the code, and replace any earlier link of the same Telegram id.
- **FR-011**: System MUST, on approval, send the user "You are linked. Send me a message to begin." to the chat the code came from, and MUST NOT fail the approval when that message cannot be sent.
- **FR-012**: System MUST let the operator approve a code from a prompt that does not echo the API key, and the key MUST NOT be printed or written to a file by that target.
- **FR-013**: System MUST let the operator remove links by Telegram id or username, remove the sessions of every removed user, and report the number of links removed.
- **FR-014**: System MUST NOT show an API key in any list, reply or log.
- **FR-015**: System MUST answer `/start`, `/stop`, `/help` and `/whoami` for unlinked users, and MUST require a link for every other command and for the settings buttons.
- **FR-016**: System MUST tell an unlinked user in a private chat how to link on every message or gated command, and an unlinked user in a group at most once per 600 seconds per user.
- **FR-017**: System MUST re-check the link when a queued message's turn starts, and MUST answer with the linking reply instead of calling the endpoint when the link is gone.
- **FR-018**: System MUST answer `/whoami` with the Telegram id, `linked as <username>` or `not linked`, the link kind (`api_key` or `oidc`) and, for an `oidc` link, the issuer's subject and the link's status, then the session key, and MUST NOT include a secret.
- **FR-019**: System MUST delete pairing codes that are 3,600 seconds old or older when it handles the next pairing request, and in the daily clean-up.
- **FR-020**: System MUST answer a turn of a user whose stored key cannot be decrypted with "Your link can no longer be read. Ask the operator to link you again.", and write the failure to its log.

- **FR-021**: System MUST, with `LINK_MODE=device`, answer `/login` in a private chat by starting a device authorization at the issuer and showing the verification address (the complete one when offered), the user code and the minutes remaining; in a group it MUST show no code and ask the user to message the bot privately.
- **FR-022**: System MUST poll the token endpoint at the interval the issuer gave, add 5 seconds to it on `slow_down` and keep the new interval, and stop on approval, `access_denied`, `expired_token` or the code's expiry, telling the user which; a network error or a 5xx answer MUST be retried at the same interval until the code expires.
- **FR-023**: System MUST keep at most one pending login per Telegram user, replaced by a new `/login`, store it with the device code encrypted, and resume polling every stored login at start.
- **FR-024**: System MUST, on approval, store the refresh token encrypted, the subject, and a display name (the issuer's `preferred_username`, else the Telegram name), replace any earlier link of the user, and MUST NOT store a password or an access token; an approval without a refresh token or without a subject MUST fail the login with a message to the user.
- **FR-025**: System MUST send for each turn of an `oidc` link a valid access token as the bearer, obtained by the refresh grant when none is held that is valid for at least 60 more seconds, and MUST send the stored key for an `api_key` link as before.
- **FR-026**: System MUST store a new refresh token returned by a refresh before the access token is used, and MUST NOT let concurrent turns of one user both refresh.
- **FR-027**: System MUST, when a refresh is refused with `invalid_grant` or `unauthorized_client`, mark the link `expired`, clear its refresh token, answer "Your sign-in has expired. Send /login to sign in again." and send nothing to the endpoint.
- **FR-028**: System MUST, when a refresh fails for a transient reason, answer "The sign-in service did not answer. Please try again in a moment." and leave the link unchanged.
- **FR-029**: System MUST, with `/logout` in device mode, revoke the refresh token at the issuer's revocation endpoint when one is advertised, delete the link and the user's sessions and any pending login whether or not revocation succeeded, and say whether the sign-in was revoked, could not be revoked or the issuer has no revocation.
- **FR-030**: System MUST, in pairing mode, behave as before this capability had device sign-in.
- **FR-031**: System MUST, in device mode, answer a private message of a user with no usable link (none, or `expired`) with an invitation to `/login` and no pairing code, keep honouring `api_key` links, and let `/login` by such a user replace the link when approved.
- **FR-032**: System MUST read the issuer's endpoints from its discovery document (`/.well-known/openid-configuration`) and cache it for one hour, and MAY read the claims of tokens received directly from the token endpoint without checking their signature; a login without a `sub` MUST fail.
- **FR-033**: System MUST NOT write a refresh token, a device code or an access token to a log, a reply or an error.
- **FR-034**: System MUST show the `/login` message with a **Sign in** button that opens the verification address (the complete one when offered) and a **Copy code** button that copies the user code, and keep the code and the minutes remaining in the text; when Telegram refuses the button address it MUST send the message again with the address in the text.


### Key Entities

- **Link**: ties one Telegram user to one way of calling the endpoint with the username and name recorded at approval: an API key (`api_key`, from pairing) or an issuer's refresh token and subject (`oidc`, from device sign-in), active or expired.
- **Device login**: a sign-in in progress for one Telegram user: the encrypted device code, what the user was shown, the polling interval and the expiry.
- **Pairing code**: a request to be linked, naming the Telegram user, the username they claim and the chat to answer in.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A pairing code is exactly 8 characters long and never contains `0`, `O`, `1` or `I`.
- **SC-002**: A code stops working 3,600 seconds after it was created.
- **SC-003**: One user can create at most one code per 600 seconds and never holds more than 3 live codes.
- **SC-004**: No stored API key is readable in the database without the configured encryption key.
- **SC-005**: A message from an unlinked user is answered without any request to the endpoint.

## Assumptions

- The operator can reach the bot's operator commands from the host that runs it, and holds the API key to give each user.
- Telegram delivers the user's `/start` with the user's id and full name; both are taken as given.
- The configured encryption key stays the same for the life of the stored links.

## Known Defects and Gaps

None.
