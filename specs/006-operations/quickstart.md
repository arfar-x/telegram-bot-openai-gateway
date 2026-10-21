# Quickstart: Operations

End-to-end scenarios that confirm the behaviour as specified. They assume Docker and `make`, and a bot token.

## 1. First start

1. Run `make setup`. Expect: `.env` is created with mode 600, `POSTGRES_PASSWORD`, `DATABASE_URL` and `CREDS_KEY` are filled, and the step lists `BOT_TOKEN` and `DEFAULT_MODEL` as still needed.
2. Set `BOT_TOKEN`, `DEFAULT_MODEL` and, unless the endpoint is OpenAI, `OPENAI_BASE_URL` in `.env`.
3. Run `make up`. Expect: within about 40 seconds the bot is healthy and `make logs` ends with `ready as @<username>`.
4. In Telegram, open the bot's command menu. Expect nine commands: new, stop, model, reasoning, set, unset, settings, whoami, help.

## 2. Configuration errors

1. Start the bot once with `OPENAI_BASE_URL` empty. Expect `error: missing required variable(s): OPENAI_BASE_URL` and exit status 2.
2. Start it with `WEBHOOK_URL` set and `WEBHOOK_SECRET` empty. Expect the secret message and exit status 2.

## 3. Link a user and chat

1. As an unlinked user in a private chat send `/start <username>`. Expect a code of 8 characters.
2. Run `make codes`. Expect the code with the username and name.
3. Run `make pair CODE=<code>` and give an API key at the prompt. Expect `linked <username>` and a message "You are linked. Send me a message to begin." in the chat.
4. Send a message. Expect an answer from the endpoint.

## 4. Isolation

1. Run `docker compose ps`. Expect no published port for either service.
2. Run `docker compose ps`. Expect the database port to be listed as exposed (`5432/tcp`) but not published to the host.

## 5. Recovery

1. Cut the network to Telegram for a minute while the bot runs. Expect errors in the log and polling to resume afterwards.
2. Start a second process with the same token. Expect "Telegram reports another bot instance is polling this token; stop the other one." in the log.

## 6. Backup

1. Run `docker compose exec -T db pg_dump -U telegram_bot telegram_bot > backup.sql` and copy `.env` beside it. Expect both files; restoring the dump with the same `.env` brings every link and session back.
