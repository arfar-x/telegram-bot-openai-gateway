# Contract: Client tools

All declared as `{"type": "function", "function": {name, description, parameters}}` with the arguments below, after `clarify`, in this order. The result of an immediate tool is a message `{"role": "tool", "tool_call_id": <id>, "content": <text>}`.

| Tool | Kind | Arguments (required in bold) | Result |
|---|---|---|---|
| `request_approval` | suspending | **`action`** (string, at most 300), `effect` (string, at most 1000) | `Allow`, `Reject`, or the user's own message |
| `send_file` | immediate | **`filename`**, **`content`** (text), `caption` (at most 1024) | `Sent <name> (<size>).` |
| `send_image` | immediate | one of **`url`**, **`base64`**; `caption` (at most 1024) | `Sent the image.` |
| `send_buttons` | immediate | **`text`** (at most 4096), **`buttons`**: list of `{label, url}` or `{label, copy}` | `Sent the buttons.` |
| `notify` | immediate | **`text`** (at most 4096) | `Sent.` |
| `react` | immediate | **`emoji`** | `Reacted <emoji>.` |
| `get_context` | immediate | none | `{"chat_type": "private", "topic": false, "language": "en", "utc_now": "2026-10-23T10:00:00Z"}` |

## Rules

- A failure is a result starting with `Could not` followed by the reason, or `Invalid arguments:` followed by the reason. It is never an error of the request.
- `filename`: the part after the last `/` or `\`, control characters removed, leading dots removed, at most 100 characters; `file.txt` when nothing is left; `.txt` added when there is no extension.
- `react`: the emoji is compared without U+FE0F. Allowed: 👍 👎 ❤ 🔥 🥰 👏 😁 🤔 🤯 😱 🤬 😢 🎉 🤩 🤮 💩 🙏 👌 🕊 🤡 🥱 🥴 😍 🐳 ❤‍🔥 🌚 🌭 💯 🤣 ⚡ 🍌 🏆 💔 🤨 😐 🍓 🍾 💋 🖕 😈 😴 😭 🤓 👻 👨‍💻 👀 🎃 🙈 😇 😨 🤝 ✍ 🤗 🫡 🎅 🎄 ☃ 💅 🤪 🗿 🆒 💘 🙉 🦄 😘 💊 🙊 😎 👾 🤷‍♂ 🤷 🤷‍♀ 😡.
- `request_approval` stores an open question whose options are `Allow` and `Reject` and whose text is `**<action>**` and, when given, a new line and `<effect>`.
