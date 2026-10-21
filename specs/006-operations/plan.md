# Implementation Plan: Operations

**Spec**: [`spec.md`](spec.md) | **Status**: As built

## Summary

A single container runs the bot next to its own PostgreSQL. Settings come from one env file. At start it opens its database, applies its migrations, registers its commands and begins long polling (or a webhook).

## Technical Context

**Language/Version**: Python 3.12 (base image `python:3.12-slim`)

**Primary Dependencies**: python-telegram-bot (application, polling, webhook), psycopg 3 with a pool, httpx, cryptography

**Storage**: a PostgreSQL 16 database `telegram_bot` with its own role `telegram_bot`, in the bundled container (see [`data-model.md`](data-model.md))

**Testing**: pytest for configuration, the operator commands, start-up wiring (polling and webhook arguments), the health file and the layout of the module; PostgreSQL tests with a throwaway container; the database role script was checked against a throwaway PostgreSQL

**Target Platform**: Linux container started from the repository's compose file

**Project Type**: service (a Python package run in a container)

**Performance Goals**: not stated by the code

**Constraints**: 256 MB of memory; no published port; unprivileged user; one process (two processes with the same token conflict)

**Scale/Scope**: not stated by the code

## Constitution Check

- Secrets in the environment: all secrets come from the env file, which is ignored by version control. Satisfied.
- No published port, least privilege: the service publishes nothing, and the database role reaches only its own database. Satisfied.
- Small footprint: the only infrastructure is PostgreSQL. Satisfied.
- Pinned versions: dependency ranges and the base image tag are not pinned. Divergence recorded below.
- The repository stands on its own: its compose file, env template, make targets, scripts and docs are in it, and nothing refers to any other product. Satisfied.

## Project Structure

```text
Dockerfile, compose.yaml, Makefile, .env.example
migrations/              numbered SQL files
scripts/prepare.sh       env file and generated secrets
scripts/lib/env.sh       reading values from the env file
scripts/test-services.sh PostgreSQL tests against a throwaway container
compose.webhook.yaml     opt-in: publishes the webhook port on loopback
src/telegram_bot_gateway/
  config.py, cli.py
  adapters/inbound/telegram/serve.py   start-up, polling or webhook, heartbeat
```

## Configuration

See FR-001 of the spec for the full list and defaults; the webhook port is published only with `compose.webhook.yaml`. `.env.example` is the tracked template; `.env` is the ignored file the service reads.

## Complexity Tracking

| Divergence from the constitution | Why accepted |
|---|---|
| Dependencies are version ranges and the base image tag floats | Pinning is not yet done |
