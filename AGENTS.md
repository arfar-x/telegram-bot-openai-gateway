# Agent instructions: telegram-bot-openai-gateway

A Telegram bot that is a client of any OpenAI-compatible Chat Completions endpoint. This file governs
changes to the repository; [`.specify/memory/constitution.md`](.specify/memory/constitution.md) holds the
principles it follows.

## Rules

- **The spec comes first.** Change [`docs/spec.md`](docs/spec.md) and the capability specs under
  [`specs/`](specs/glossary.md) (a reviewed diff), then the code, in the same change. Every requirement
  has an id and a status; a test claims one with a `# Covers: FR-XXX-NN` line.
  `tests/test_spec_coverage.py` fails on a `done` requirement without a test, a claim of an undefined id,
  or a test for something still marked `planned`.
- **Hexagonal.** `domain/` and `application/` do no I/O and import nothing from `adapters/`
  (`tests/test_boundaries.py`). New outside dependencies are a port in `application/ports.py` and an adapter.
- **Endpoint-agnostic.** Talk plain Chat Completions. Nothing may depend on one provider: no import of
  another product, no request header or field only one endpoint understands.
- **The key is the user.** Each linked user has their own API key. The code never shares one across users.
- **Secrets** come from the environment only and never reach a log, a reply or an error. API keys are stored
  encrypted with `CREDS_KEY`. `/whoami` and `links` never show one.
- **No allowlist.** Who may use the bot is decided by linking, not by a list of Telegram ids.
- **Queue, never interrupt.** A running turn is cancelled only by `/stop`.
- The service publishes no port and its database role reaches only its own database.

## Specs

Behaviour is specified under [`specs/`](specs/glossary.md), one numbered directory per capability.
[`docs/spec.md`](docs/spec.md) stays the test-gated registry of requirement ids and maps them to the specs.
Defects found when the specs were written are listed in each spec's `Known Defects and Gaps` and are scheduled
for correction; the strict expected-failure tests in `tests/test_known_defects.py` turn into failures when a
defect is fixed, and the marker is then removed with the fix.

## Commands

```bash
make dev               # .venv with the development dependencies
make test              # unit tests
make test-services     # PostgreSQL tests in a throwaway container
make up                # run it (needs .env, see make setup)
```

Commit messages follow Conventional Commits. The body says what changed and why, not how, and nothing
specific to the conversation that produced it.
