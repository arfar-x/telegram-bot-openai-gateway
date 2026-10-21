# Operator guide

For running the bot with the compose file in the repository root.

## First run

1. Create a bot with @BotFather and copy its token.
2. `make setup` creates `.env` from the template (mode 600), generating `POSTGRES_PASSWORD`, `DATABASE_URL`
   and `CREDS_KEY`, and lists what is still needed.
3. Set `BOT_TOKEN`, `DEFAULT_MODEL` (a model or agent name the endpoint serves) and, unless you use OpenAI,
   `OPENAI_BASE_URL` in `.env`.
4. `make up` builds and starts the bot and its PostgreSQL. `make logs` follows the log; the bot is ready when it
   says `ready as @<username>`.

An endpoint on the same machine is reached from the container through the host's address (for example
`http://host.docker.internal:11434/v1`; add `extra_hosts: ["host.docker.internal:host-gateway"]` to the `bot`
service on Linux), not through `localhost`.

## Linking a user

1. The user opens the bot in a private chat and sends `/start <username>`: the name you know them by, for
   example their email. They get a code valid for one hour.
2. `make codes` lists open codes with the username and Telegram name they gave. Check that it is who it says
   it is: **this check is the only thing that stops someone claiming another person's account.**
3. `make pair CODE=ABCD2345` asks for the API key that person will act under and links them. They are told.

Use a key per person when the endpoint can tell callers apart by key; with an endpoint that cannot, give every
person the same key.

`make links` lists linked users. `make unlink TG_ID=123` (or `USER_NAME=alice@example.org`) removes the link and
the user's sessions. It does not revoke the API key at the endpoint.

## What users can do

`/new`, `/stop`, `/model`, `/reasoning`, `/set <name> <value>`, `/unset <name>`, `/settings`, `/whoami`,
`/help`. Settings are per session and sent with every request; an endpoint that refuses a value says so and
the message is shown unchanged.

## Switches

| Variable | Effect |
|---|---|
| `REACTIONS` | A 👀 on a message only when it is worth it: it waits behind a running turn, or its answer takes longer than `REACTION_DELAY` seconds (default 10). Removed once answered. Default on. |
| `SHOW_PROGRESS` | Show the endpoint's reasoning as one silent message, edited in place and removed after the answer (default off). |
| `REQUEST_TIMEOUT` | Seconds without data from the endpoint before a request is abandoned. |
| `WEBHOOK_URL`, `WEBHOOK_SECRET` | Webhook instead of long polling; the secret is mandatory with the URL. The container listens on `WEBHOOK_PORT` (8443) but the compose file publishes nothing, so put your own HTTPS front end in front of it and add the port mapping you need. |

A change to `.env` takes effect after `make restart`.

## Backup and restore

State is in the PostgreSQL volume `db_data`, and the stored API keys are readable only with `CREDS_KEY`: back
up both together.

```bash
docker compose exec -T db pg_dump -U telegram_bot telegram_bot > backup.sql
```

To restore, start the bot with the same `.env`, then `docker compose exec -T db psql -U telegram_bot telegram_bot < backup.sql`.
Restoring the database next to a different `CREDS_KEY` leaves every stored key unreadable: everyone has to be
linked again.

## When it looks wrong

- **No answer, log says another instance is polling:** a second process uses the same token; stop it.
- **A user gets "not linked":** their link was removed or never approved; check `make links`.
- **"The endpoint answered 401":** the key stored for that user is no longer valid; unlink and pair again.
- **"The endpoint answered 400" about tools or a system message:** the endpoint does not accept what the bot
  sends; see [the endpoint contract](../specs/002-conversations/contracts/endpoint.md).
- **Container unhealthy:** the bot writes a heartbeat file every 30 seconds; none means it is not running.
  `make logs` shows why (a wrong token or an unreachable database are the usual causes).
- **Telegram unreachable from your network:** configure a proxy in the environment of the `bot` service.
