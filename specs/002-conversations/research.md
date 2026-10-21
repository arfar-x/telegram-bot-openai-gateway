# Research: Conversations

## Plain Chat Completions, not a vendor-specific API

**Decision**: The bot sends standard Chat Completions requests and reads standard streams, with one declared tool.

**Rationale**: The bot must work with any model or agent behind any OpenAI-compatible endpoint. Some endpoints drop images on their Responses route and keep them on this one.

**Alternatives considered**: The Responses API (rejected: images are dropped there).

## The history is stored and replayed exactly

**Decision**: Assistant messages, including tool calls, are stored as returned and sent back unchanged.

**Rationale**: Some endpoints find a conversation again by hashing the visible history they receive; any change to an earlier message starts a new conversation there.

**Alternatives considered**: none recorded.

## The system note is sent with each request and never stored

**Decision**: The note is added in front of the history on every request and is not part of the stored history.

**Rationale**: The endpoint treats a client's system message as lower-priority client instructions and leaves it out of the history it matches on. Keeping it out of the stored history lets its wording change without touching earlier conversations.

**Alternatives considered**: none recorded.

## Messages sent during a turn wait; they never interrupt

**Decision**: Messages arriving during a turn are queued and answered together after it; only `/stop` cancels.

**Rationale**: A turn may run write tools on the endpoint's side, so aborting one can hide a side effect.

**Alternatives considered**: Restarting the turn with the new message (rejected for that reason); injecting the message after the next tool call (not chosen).

## State lives in a PostgreSQL database of the bot's own

**Decision**: Sessions and links are stored in a PostgreSQL database with its own role. The bundled compose file runs a container for it; any PostgreSQL database the bot owns will do.

**Rationale**: One small, well-understood store that survives restarts, with a role that reaches only the bot's own database.

**Alternatives considered**: A file-based database inside the bot's container (the first design, replaced at the operator's request).

## Each user has their own session even in a group

**Decision**: In a group the session key includes the user.

**Rationale**: A conversation in the endpoint belongs to one key, and each user has their own.

**Alternatives considered**: One shared session per chat (rejected for that reason).
