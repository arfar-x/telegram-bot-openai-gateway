# Telegram Bot OpenAI Gateway Constitution

## Core Principles

### I. Endpoint-agnostic

The bot is a client of any service that speaks the OpenAI Chat Completions API.

- It MUST talk plain Chat Completions and model listing. Nothing in the code or the configuration
  MAY depend on one provider, one model name, or a request field only one product understands.
- It MUST NOT import another product's code. A deployment script outside the package MAY use another
  product's tooling (for example to issue an API key), never the package itself.
- No tracked file MAY name a specific model, organization or person.

Rationale: the same bot has to work with a hosted API, a self-hosted server and a gateway in front of either.

### II. The spec leads

`docs/spec.md` is the registry of requirement ids and statuses, and `specs/` holds the behaviour in
detail, one numbered directory per capability.

- A behaviour change MUST land in the spec in the same change as the code, never after it.
- Every requirement MUST carry a stable id and a status.
- A requirement marked `done` MUST have a test that claims it (`# Covers: <id>`);
  `tests/test_spec_coverage.py` enforces this and MUST stay green.
- A known defect is recorded in the `Known Defects and Gaps` section of its spec, and its fix
  removes the entry in the same change.

Rationale: the code follows the spec; when they disagree, one of them is wrong, and only a written
spec makes that visible in review.

### III. Hexagonal, provable core (NON-NEGOTIABLE)

- The package keeps `domain/` → `application/` → `adapters/`.
- `domain/` and `application/` MUST NOT import anything that does I/O (a database driver, an HTTP
  client, the Telegram library, a cryptography library or standard-library I/O modules);
  `tests/test_boundaries.py` enforces it.
- Use cases MUST be provable with in-memory fakes, without a database, network or Telegram.
- New behaviour arrives with tests; unit tests run with no services.

Rationale: the rules of a chat bot have to be checkable in a second, on a laptop.

### IV. Secrets stay in the environment; each user acts under their own key

- Every secret (the bot token, the encryption key, the database password) lives in the environment
  or an ignored env file. Tracked files hold placeholders only.
- A user is linked to one API key by the operator. There is no allowlist of Telegram ids, and no key
  is shared by the code itself.
- A stored API key MUST be encrypted and MUST NOT appear in a log, a reply or an error. The HTTP
  client's request lines, which contain the bot token, MUST stay out of the log.

Rationale: a leaked token or key is the most likely way this service is compromised.

### V. Least privilege

- The service publishes no port. It polls Telegram, and a webhook, if enabled, is reached through a
  front end the operator provides.
- The database role reaches only the bot's own database.
- In a larger deployment the service joins only the networks it needs and never one shared with
  unrelated services.

Rationale: a component that cannot reach something cannot leak it.

## Additional Constraints

- **Small footprint.** The only infrastructure is PostgreSQL. A change that needs more MUST say so in
  its plan and justify it.
- **Pinned versions.** Dependencies and the base image SHOULD be pinned. Until they are, the plans'
  Complexity Tracking records the divergence.
- **Replaceable linking.** Linking sits behind a small interface so another identity source can
  replace pairing without touching the rest.

## Development Workflow

- **Branches.** Work happens on a branch cut from the current `main`, never on `main` itself.
- **Commits.** Each commit is one logical step, written as a Conventional Commit. The body says what
  changed and why, not how, and nothing specific to the conversation that produced it.
- **Spec Kit order.** For a change big enough to design: specify, clarify (when anything is
  ambiguous), plan, tasks, analyze, implement; each artifact is committed on its own.
- **Gates before a pull request.**
  - `make test` (spec coverage and boundaries included);
  - `make test-services` when storage changes;
  - the docs, `.env.example` and `docs/OPERATOR_GUIDE.md` updated in the same change when operator
    behaviour changes.
- **Merging.** A pull request is opened, not merged, by whoever wrote it. Merging is a human review
  decision.

## Governance

- This constitution governs how changes are designed and reviewed; where `AGENTS.md` disagrees with
  it, this document wins until one of them is amended.
- An amendment is a reviewed pull request that edits this file and states its version bump:
  MAJOR when a principle is removed or redefined, MINOR when one is added or materially expanded,
  PATCH for wording.
- Plans MUST include a constitution check; a violation is removed or recorded with its justification.

**Version**: 1.0.0 | **Ratified**: 2026-10-21 | **Last Amended**: 2026-10-21
