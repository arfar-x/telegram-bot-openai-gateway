# Day-to-day commands for running the bot on its own. Every operator command runs inside the bot's
# container, so nothing needs to be installed on the host besides Docker and make.
.DEFAULT_GOAL := help
SHELL := /usr/bin/env bash
BOT := docker compose exec -T bot python -m telegram_bot_gateway

.PHONY: help setup up down restart ps logs codes pair links unlink dev test test-services

help: ## Show this list
	@grep -hE '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: ## Create .env from the template and generate the secrets (set BOT_TOKEN and DEFAULT_MODEL yourself)
	scripts/prepare.sh || test $$? -eq 3

up: ## Build and start the bot and its database
	scripts/prepare.sh
	docker compose up -d --build

down: ## Stop the bot and its database (the data stays in the db_data volume)
	docker compose down

restart: ## Restart the bot, e.g. after editing .env
	docker compose restart bot

ps: ## Service status and health
	docker compose ps

logs: ## Follow the bot's log
	docker compose logs -f bot

codes: ## Open pairing codes and who asked for them
	$(BOT) pair list

pair: ## Link a user: `make pair CODE=ABCD2345` (asks for the API key that user will act under)
	@test -n "$(CODE)" || { echo "Usage: make pair CODE=<code from 'make codes'>" >&2; exit 1; }
	@$(BOT) pair show $(CODE)
	@read -rsp "API key for this user: " key; echo; printf '%s\n' "$$key" | $(BOT) pair approve $(CODE)

links: ## Linked Telegram users
	$(BOT) links

unlink: ## Unlink: `make unlink TG_ID=123` or `make unlink USER_NAME=alice@example.org` (the API key itself is not revoked)
	@test -n "$(TG_ID)$(USER_NAME)" || { echo "Usage: make unlink TG_ID=<telegram id> | USER_NAME=<username>" >&2; exit 1; }
	$(BOT) unlink $(if $(TG_ID),--telegram-id $(TG_ID),) $(if $(USER_NAME),--username $(USER_NAME),)

dev: ## Create .venv with the development dependencies
	python3 -m venv .venv && . .venv/bin/activate && pip install -e '.[serve,dev]'

test: ## Unit tests (no services needed)
	. .venv/bin/activate && python -m pytest -q

test-services: ## The PostgreSQL tests, against a throwaway container
	. .venv/bin/activate && scripts/test-services.sh -q
