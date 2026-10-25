# Data Model: Account Linking

Storage is the bot's own database. Terms follow [`../glossary.md`](../glossary.md).

## Entities

### Link

| Field | Type | Rules |
|---|---|---|
| telegram user id | integer (64-bit) | Primary key. One link per Telegram user. |
| username | text, required | The name the endpoint knows the user by, as given in the pairing request. Not unique. |
| Telegram name | text, required | The user's full name when the code was created. |
| kind | text, `api_key` or `oidc` | `api_key` from pairing (default), `oidc` from device sign-in. |
| API key (encrypted) | text, `api_key` links only | The endpoint API key, encrypted with the configured key. Never returned by any list. |
| subject | text, `oidc` links only | The issuer's `sub`. Not unique: one person may link several Telegram accounts. |
| refresh token (encrypted) | text, `oidc` links only | Encrypted with the configured key; cleared when the link expires. Never returned by any list. |
| status | text, `active` or `expired` | `expired` after the issuer refused a refresh. |
| refreshed at | timestamp with time zone, optional | The last successful refresh. |
| created at | timestamp with time zone | Set when the link is first made; a replacement keeps it. |

Saving a link for an existing Telegram user replaces username, name and credentials. A database check keeps the shape: an `oidc` link has a subject and no API key; an `api_key` link has a key and neither subject nor refresh token.

### Pairing code

| Field | Type | Rules |
|---|---|---|
| code | text | Primary key. 8 characters from `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`. |
| telegram user id | integer (64-bit) | Indexed. |
| username | text, required | Free text from the request. |
| Telegram name | text, required | The user's full name. |
| chat id | integer (64-bit) | The chat the confirmation is sent to. |
| created at | double precision | Seconds since the Unix epoch. Rules compare against it; there is no expiry column. |

### Device login

| Field | Type | Rules |
|---|---|---|
| telegram user id | integer (64-bit) | Primary key: one pending login per user; a new one replaces it. |
| chat id | integer (64-bit) | The private chat the result is reported to. |
| username, Telegram name | text | For the link that results. |
| device code (encrypted) | text | Encrypted with the configured key. |
| user code, verification uri, verification uri complete | text | What the user was shown. |
| interval seconds | integer | Polling interval, raised by `slow_down`. |
| expires at | timestamp with time zone | The issuer's expiry. |

## State transitions

```mermaid
stateDiagram-v2
    [*] --> Open: user sends /start username
    Open --> Linked: operator approves with a key (code removed)
    Open --> Expired: 3,600 s pass (row kept, ignored)
    Linked --> Linked: a new approval for the same Telegram id replaces the link
    Linked --> [*]: operator unlinks (link and sessions removed)
    [*] --> LoggingIn: /login in device mode
    LoggingIn --> Linked: the issuer approves (oidc link)
    LoggingIn --> [*]: denied or expired
    Linked --> Expired: the issuer refuses a refresh
    Expired --> LoggingIn: /login
    Linked --> [*]: /logout (revoked at the issuer, link and sessions removed)
```

## Relationships

- A Link and the Sessions of the same user are related by the Telegram user id; removing a link removes those sessions (see capability 002).
- A pairing code is independent of a link until approval consumes it.
