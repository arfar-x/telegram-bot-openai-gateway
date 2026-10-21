# Feature Specification: Operations

**Created**: 2026-10-21

**Status**: Accepted

**Input**: Existing system behavior

Terms follow [`../glossary.md`](../glossary.md).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Start the bot from configuration (Priority: P1)

The operator sets variables in one file and starts the bot. It prepares its database, announces itself, and begins to receive messages. A missing variable stops it with a message that names it.

**Why this priority**: Nothing else works until the bot starts.

**Independent Test**: Start with each required variable removed in turn and see a message naming it; start with all of them and see "ready as @<username>" in the log.

**Acceptance Scenarios**:

1. **Given** a missing required variable, **When** the bot is started, **Then** it prints `error: missing required variable(s): <names>` and exits with status 2.
2. **Given** a webhook address and no webhook secret, **When** the bot is started, **Then** it prints `error: WEBHOOK_URL is set, so WEBHOOK_SECRET is required` and exits with status 2.
3. **Given** a valid configuration, **When** the bot starts, **Then** it connects to its database, applies pending migrations, registers its command menu with Telegram, starts a heartbeat, and logs `ready as @<username>`.
4. **Given** migrations already applied, **When** the bot starts again, **Then** they are not applied again.
5. **Given** two bot processes starting together, **When** both apply migrations, **Then** one waits for the other.

---

### User Story 2 - Keep running through trouble (Priority: P1)

The bot receives updates by polling, ignores what was queued while it was off, recovers from network errors by itself, and reports plainly when another process polls with the same token.

**Why this priority**: It is meant to run unattended.

**Independent Test**: Cut the network for a minute and see polling resume; start a second process with the same token and see the plain message in the log.

**Acceptance Scenarios**:

1. **Given** the default configuration, **When** the bot starts, **Then** it polls for new messages and button taps only, and drops updates that queued while it was off.
2. **Given** a webhook address and secret, **When** the bot starts, **Then** it listens for webhook calls on the configured port (8443 by default) with that secret and drops queued updates.
3. **Given** a network error while polling, **When** it happens, **Then** the error is logged and polling continues.
4. **Given** a second process polling with the same token, **When** Telegram reports the conflict, **Then** the log says "Telegram reports another bot instance is polling this token; stop the other one."
5. **Given** an error inside a handler, **When** it happens, **Then** it is logged with its details and the bot keeps running.

---

### User Story 3 - Know that it is alive (Priority: P2)

The container reports healthy only while the bot can reach Telegram.

**Why this priority**: Container tooling depends on it to report status.

**Independent Test**: Start the container and see it become healthy within 40 seconds; cut its route to Telegram and see it become unhealthy within about two minutes, and healthy again when the route returns.

**Acceptance Scenarios**:

1. **Given** a running bot that can reach Telegram, **When** 30 seconds pass, **Then** the health file is written again.
2. **Given** a bot that cannot reach Telegram, **When** 30 seconds pass, **Then** the health file is not written, a warning is logged, and the file ages.
3. **Given** a health file written less than 90 seconds ago, **When** the container is checked, **Then** it is healthy; otherwise unhealthy.

---

### User Story 4 - Deploy it without widening access (Priority: P2)

The bot runs with its own database and no published port, and can be set up, started and stopped with a few commands. The database role it uses reaches only its own database.

**Why this priority**: The bot holds users' API keys; its reach must stay small.

**Independent Test**: Set up the database, check that the role connects only to its own database; start the service and check that no port is published.

**Acceptance Scenarios**:

1. **Given** the compose file in the repository root, **When** the operator starts it, **Then** the bot and its own PostgreSQL start, nothing is published to the host, and the database is reachable only from the bot.
2. **Given** an operator without an env file, **When** the preparation step runs, **Then** the file is created from the template with mode 600, with a database password, the matching database address and an encryption key generated, and the step reports the variables still to be set (bot token, default model).
3. **Given** a PostgreSQL instance shared with other services, **When** the operator points the bot at a database of its own on it, **Then** the bot creates only its own tables there (through its migrations) and needs no rights outside that database.
4. **Given** the operator guide, **When** the operator backs up the bot, **Then** it tells them to save the database dump and the env file together, because the stored API keys are readable only with the encryption key in that file.

### Edge Cases

- The bot token is only needed to serve; the operator commands for linking read the same file and work without it.
- A missing migrations directory or an unreachable database makes the bot fail to start (it is then restarted by the container policy).
- Boolean variables are true for `1`, `true`, `yes` or `on` in any letter case, false for anything else, and the default when empty or unset.
- A change to the env file takes effect at the next start of the bot.
- Webhook mode publishes nothing by default; the opt-in `compose.webhook.yaml` publishes its port on the loopback interface for a reverse proxy that terminates HTTPS.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST read every setting from the process environment: `BOT_TOKEN`, `OPENAI_BASE_URL`, `DEFAULT_MODEL`, `DATABASE_URL`, `CREDS_KEY` (required to serve), and `OPENAI_API_KEY` (empty), `REACTIONS` (true), `REACTION_DELAY` (10), `SHOW_PROGRESS` (false), `REQUEST_TIMEOUT` (600), `WEBHOOK_URL` (empty), `WEBHOOK_SECRET` (empty), `WEBHOOK_PORT` (8443), `MIGRATIONS_DIR` (`migrations`), `HEALTH_FILE` (`/tmp/healthy`), `HISTORY_MAX_CHARS` (200000), `MESSAGE_TEXT_DAYS` (30), `MAX_CONCURRENT_TURNS` (2), `TELEGRAM_PROXY` (empty), `TELEGRAM_CONNECT_TIMEOUT` (20), `TELEGRAM_READ_TIMEOUT` (30).
- **FR-002**: System MUST treat a required variable that is unset or empty as missing, name every missing one in one message, and exit with status 2; the operator commands MUST NOT require `BOT_TOKEN`.
- **FR-003**: System MUST refuse a webhook address without a secret, with the message `WEBHOOK_URL is set, so WEBHOOK_SECRET is required`.
- **FR-004**: System MUST read a boolean variable as true for `1`, `true`, `yes` or `on` in any letter case and false for any other non-empty value.
- **FR-005**: System MUST poll for updates by default, asking Telegram for new messages and button taps only, and drop the updates queued while it was off.
- **FR-006**: System MUST, when a webhook address is set, serve webhook calls on all interfaces at the configured port with the secret as Telegram's secret token, asking for the same update kinds and dropping queued updates.
- **FR-007**: System MUST at start connect to its database (a pool of 1 to 8 connections, waiting up to 30 seconds), apply the migration files not yet recorded, in name order, one at a time under a lock shared by all processes, and record each after it is applied.
- **FR-008**: System MUST register these commands with Telegram at start: new, stop, model, reasoning, set, unset, settings, whoami, help, each with a one-line description.
- **FR-009**: System MUST every 30 seconds ask Telegram who the bot is and, only when it answers within 20 seconds, write the current time to the health file; otherwise it MUST log a warning and leave the file as it is, and it MUST ignore a failure to write the file with a warning.
- **FR-010**: System MUST log at information level with the time, level, source and message, and MUST keep the HTTP client's request lines, which contain the bot token, out of the log.
- **FR-011**: System MUST log "Telegram reports another bot instance is polling this token; stop the other one." when Telegram reports two pollers, and log every other handler error with its details without stopping.
- **FR-012**: System MUST log `ready as @<username>` once the start-up steps have finished.
- **FR-013**: System MUST close the endpoint client and the database pool when it stops.
- **FR-014**: System MUST publish no port, run as an unprivileged user, be limited to 256 MB of memory, and be restarted unless stopped.
- **FR-015**: System MUST report the container healthy when the health file was written less than 90 seconds ago, checked every 30 seconds with a 5-second timeout, 3 retries and a 40-second start period.
- **FR-016**: System MUST need no rights outside its own database: its migrations create only its own tables, and the bundled compose file gives it a role that owns a database of its own and no other.
- **FR-017**: System MUST, when the env file is created, generate the database password (48 hexadecimal characters), write the database address that uses it, generate the encryption key, set the file's mode to 600, and never replace a value already set.
- **FR-018**: System MUST tell the operator, in the operator guide, to back up the database and the env file together.
- **FR-019**: System MUST start with the repository's `make up`, which creates the env file first when it is missing.
- **FR-020**: System MUST, when it stops, send each chat that has a message waiting, queued or running one quiet message, "I was restarted before I could answer. Please send your message again.", cancel those turns without saving them, and remove the reactions it set, giving up on any chat after 3 seconds.
- **FR-021**: System MUST at start and then daily delete message texts older than the configured number of days and pairing codes older than 3,600 seconds.
- **FR-022**: System MUST offer an opt-in addition to the compose file for webhook mode that publishes the webhook port on the loopback interface only.
- **FR-023**: System MUST use the configured connection and read timeouts (defaults 20 and 30 seconds) for its calls to Telegram, and the configured proxy for them when one is set.

### Key Entities

- **Configuration**: the environment variables above.
- **Migration**: a numbered SQL file applied once, recorded by name.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Start-up with a valid configuration reaches "ready" without any manual step after the database exists.
- **SC-002**: The container is unhealthy at most 90 seconds after the bot last reached Telegram.
- **SC-003**: The bot's database role cannot connect to any database but its own.
- **SC-004**: The service publishes 0 ports.
- **SC-005**: A secret never appears in the log: the bot token, the encryption key and users' API keys.

## Assumptions

- Docker and `make` are available on the host that runs the bot.
- The host can reach Telegram's API; a proxy is configured in the environment of the container if it cannot.

## Known Defects and Gaps

None.
