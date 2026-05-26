# termchat

> A terminal-native CLI for managing AI chat conversations — with projects, token tracking, persistent history, and automatic context compression.

---

## Features

- **Persistent chat history** — every conversation is stored locally in SQLite; resume any chat by name or ID
- **Short chat keys** — after your first message, the AI generates a memorable slug (e.g. `fix-auth`) so you never need to remember numeric IDs
- **Projects** — attach system instructions and files to a project; every chat under that project automatically receives them as context
- **Token tracking** — per-message input/output counts and session totals
- **Auto-compression** — when a conversation grows past 50 000 characters, old messages are automatically summarised so the context window stays manageable
- **Provider-agnostic core** — the storage, context engine, and CLI are decoupled from the AI provider; adding a new one is a single file
- **Rich terminal UI** — coloured panels, Markdown rendering, paged history, Live streaming output

---

## Table of contents

1. [Requirements](#requirements)
2. [Installation](#installation)
3. [Quick start](#quick-start)
4. [Chat commands](#chat-commands)
5. [In-chat REPL commands](#in-chat-repl-commands)
6. [Projects](#projects)
7. [Configuration](#configuration)
8. [Context compression](#context-compression)
9. [Data storage](#data-storage)
10. [Adding a new provider](#adding-a-new-provider)
11. [Project layout](#project-layout)
12. [Contributing](#contributing)
13. [License](#license)

---

## Requirements

- **Python 3.9 or later**
- An [Anthropic API key](https://console.anthropic.com/) (or set the `ANTHROPIC_API_KEY` environment variable)

---

## Installation

### 1 — Clone the repository

```bash
git clone https://github.com/<you>/termchat.git
cd termchat
```

### 2 — Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows (cmd)
# .venv\Scripts\Activate.ps1     # Windows (PowerShell)
```

### 3 — Install dependencies

```bash
pip install -r requirements.txt
pip install -e .
```

The `-e` (editable) flag means changes to the source files are reflected immediately in the `termchat` command — no reinstall needed during development.

### 4 — Configure your API key

```bash
termchat setup
```

You will be prompted for your Anthropic API key and a default model.  
The key is written to `~/.config/termchat/config.json` with `600` permissions (owner read/write only).

**Skip this step** if you already export `ANTHROPIC_API_KEY` in your shell — termchat reads it automatically.

### 5 — Verify the installation

```bash
termchat --version
termchat --help
```

---

## Quick start

```bash
termchat setup                          # one-time key setup
termchat chat new                       # open a new conversation
termchat chat new --model claude-opus-4-7
termchat chat list                      # browse history
termchat chat resume fix-auth           # resume a chat by key
termchat chat resume 3                  # or by numeric ID
```

Both `termchat chat new` and `termchat new` (alias) open the interactive REPL.

---

## Chat commands

### `termchat chat new`

Start a new interactive chat session.

```
Options:
  -p, --project TEXT   Associate this chat with a project (name or id)
  -m, --model TEXT     Override the default model for this session
  --provider TEXT      Override the default provider
  -t, --title TEXT     Set a title immediately (before the first message)
```

```bash
termchat chat new
termchat chat new --model claude-opus-4-7
termchat chat new --project myapp
termchat chat new --project myapp --title "Sprint planning"
```

If a project name or ID is not found, the full project list is shown so you can pick the right one.

### `termchat chat resume <ref>`

Resume a previous chat. `<ref>` can be:
- A **key** (short AI-generated slug, e.g. `fix-auth`)
- A **numeric ID** (e.g. `3`)

```bash
termchat chat resume fix-auth
termchat chat resume 3
```

Previous messages are printed before the prompt opens. If the ref is not found, the recent chat list is shown.

### `termchat chat list`

List recent chats.

```
Options:
  -p, --project-id INTEGER   Filter by project id
  --limit INTEGER            Maximum rows to show [default: 25]
```

### `termchat chat show <chat_id>`

Print the full history of a chat in a paged view.

```
Options:
  --no-markdown   Render plain text instead of Markdown
```

### `termchat chat tokens <chat_id>`

Show a per-message token breakdown and session totals.

### `termchat chat compress <chat_id>`

Manually trigger context compression on a chat.

```
Options:
  --keep INTEGER   Number of recent messages to preserve [default: 6]
```

### `termchat chat delete <chat_id>`

Delete a chat and all its messages (prompts for confirmation).

```
Options:
  --yes   Skip the confirmation prompt
```

---

## In-chat REPL commands

While inside a chat session, anything starting with `/` is treated as a command. If you type a `/`-prefixed word that isn't recognised, termchat will ask **"'/<word>' isn't a command — send to AI? [y/N]"** before forwarding it, so typos don't accidentally pollute the conversation.

| Command              | Effect                                                |
|----------------------|-------------------------------------------------------|
| `/help`              | Show the command reference                            |
| `/history`           | Browse the full conversation in a pager               |
| `/tokens`            | Show token counts for this chat                       |
| `/compress`          | Force-compress old messages into a summary            |
| `/title TEXT`        | Set or update the chat title                          |
| `/clear`             | Clear the terminal screen                             |
| `/chats`             | List the 15 most recent chats                         |
| `/switch KEY_OR_ID`  | Switch to another chat without leaving the REPL       |
| `/rename [REF] TEXT` | Rename this chat, or another chat by key/id           |
| `/delete [REF]`      | Delete this chat (exits) or another chat by key/id    |
| `/quit` / `/exit`    | Exit the session (also Ctrl-D)                        |

**Multi-line input:** press **Alt-Enter** (Esc then Enter) to insert a newline without submitting. Plain Enter always sends.

---

## Projects

Projects let you attach persistent context — system instructions and files — to a group of chats. Every chat created under a project automatically receives that context in its system prompt.

### Create a project

```bash
# Opens $EDITOR for instructions
termchat project new myapp

# Instructions inline
termchat project new myapp --instructions "You are a senior Go engineer focused on clarity."

# Instructions from a file
termchat project new myapp --instructions-file AGENTS.md
```

### Attach files

```bash
# Attach a source file (included verbatim in the system prompt)
termchat project add-file 1 src/main.py

# Override the stored filename
termchat project add-file 1 README.md --name project-readme.md
```

### Inspect and edit

```bash
termchat project list
termchat project show 1

# Edit instructions interactively (opens $EDITOR)
termchat project edit 1

# Or non-interactively
termchat project edit 1 --name "new-name"
termchat project edit 1 --instructions "Updated prompt"
termchat project edit 1 --instructions-file new-instructions.md
```

### Manage files

```bash
# Append more instructions without replacing existing ones
termchat project add-instructions 1 extra.md --append

# Remove an attached file
termchat project remove-file 1 main.py
```

### Start a chat in a project

```bash
termchat chat new --project myapp
# or by numeric id
termchat chat new --project 1
```

### Delete a project

```bash
termchat project delete 1        # prompts for confirmation
termchat project delete 1 --yes  # skip prompt
```

Deleting a project does **not** delete its chats — they are detached and remain accessible.

---

## Configuration

```bash
termchat setup                           # interactive setup wizard
termchat config show                     # print settings (API keys redacted)
termchat config set-model claude-haiku-4-5-20251001   # change default model
```

### Configuration file

Settings are stored in `~/.config/termchat/config.json`:

```json
{
  "api_keys": {
    "anthropic": "sk-ant-…"
  },
  "default_models": {
    "anthropic": "claude-sonnet-4-6"
  },
  "default_provider": "anthropic"
}
```

The file is created with `chmod 600` (owner read/write only).

### Environment variables

| Variable               | Effect                                          |
|------------------------|-------------------------------------------------|
| `ANTHROPIC_API_KEY`    | Overrides the stored Anthropic API key          |
| `TERMCHAT_CONFIG_DIR`  | Override config + database directory            |

```bash
# Isolated test environment — won't touch your real database
TERMCHAT_CONFIG_DIR=/tmp/tc termchat chat new
```

---

## Context compression

termchat tracks the total **character count** of every message in a chat. When the running total exceeds **50 000 characters**, the oldest messages are automatically summarised by the AI into a single `[Conversation summary]` block, and the raw messages are deleted. The most recent 6 messages are always kept verbatim.

The summary is inserted at the front of the context window so it is always visible to the model.

### Manual compression

```bash
termchat chat compress <chat_id>            # via CLI
termchat chat compress <chat_id> --keep 10  # keep more recent messages
# or inside the REPL:
/compress
```

### Tuning the limits

Edit `termchat/config.py`:

```python
CONTEXT_CHAR_LIMIT = 50_000   # character count that triggers auto-compress
CONTEXT_KEEP_RECENT = 6       # messages always preserved verbatim
```

---

## Data storage

Everything is stored in a local SQLite database at:

```
~/.config/termchat/termchat.db
```

Override the directory with `TERMCHAT_CONFIG_DIR`. No data is ever sent to a server other than the message content you send to the AI provider.

The database uses **WAL mode** and **foreign key constraints**. Four tables:

| Table           | Contents                                  |
|-----------------|-------------------------------------------|
| `projects`      | Name and system instructions per project  |
| `project_files` | Files attached to projects                |
| `chats`         | One row per conversation                  |
| `messages`      | All messages, with token counts           |

See [`termchat/storage/README.md`](termchat/storage/README.md) for the full schema.

---

## Adding a new provider

The storage layer, context engine, and CLI are completely provider-agnostic. Adding support for a new AI backend takes three steps:

1. **Create the provider file** — `termchat/core/providers/<name>_provider.py`:

```python
from termchat.core.providers.base import BaseProvider, CompletionResult
from typing import Generator

class MyProvider(BaseProvider):
    def complete(self, messages, *, system="", max_tokens=8096) -> CompletionResult:
        ...

    def stream(self, messages, *, system="", max_tokens=8096) -> Generator[str, None, CompletionResult]:
        ...
        return CompletionResult(...)
```

2. **Register it** — `termchat/core/providers/__init__.py`:

```python
from termchat.core.providers.my_provider import MyProvider
_REGISTRY["my-provider"] = MyProvider
```

3. **Optionally set a default model** — `termchat/config.py`:

```python
PROVIDER_DEFAULTS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-6",
    "my-provider": "my-model-id",
}
```

Then use it:

```bash
termchat setup --provider my-provider
termchat chat new --provider my-provider --model my-model-id
```

See [`termchat/core/providers/README.md`](termchat/core/providers/README.md) for the full `BaseProvider` contract.

---

## Project layout

```
termchat/
├── README.md                       ← you are here
├── CONTRIBUTING.md
├── CHANGELOG.md
├── LICENSE
├── pyproject.toml
├── requirements.txt
└── termchat/                       ← Python package
    ├── README.md                   ← package overview
    ├── config.py                   ← paths, API keys, compression limits
    ├── cli/
    │   ├── README.md               ← CLI layer docs
    │   ├── main.py                 ← Click root group + DB init
    │   ├── chat_commands.py        ← `chat` sub-group + interactive REPL
    │   ├── project_commands.py     ← `project` sub-group
    │   ├── config_commands.py      ← `setup` and `config` commands
    │   └── formatting.py          ← all Rich rendering helpers
    ├── core/
    │   ├── README.md               ← core layer docs
    │   ├── chat.py                 ← orchestration (send_message)
    │   ├── context.py              ← system prompt builder + compression
    │   └── providers/
    │       ├── README.md           ← provider contract + how to add one
    │       ├── base.py             ← BaseProvider ABC + CompletionResult
    │       ├── anthropic_provider.py
    │       └── __init__.py         ← registry + get_provider()
    └── storage/
        ├── README.md               ← storage layer docs + schema
        ├── database.py             ← all SQLite operations
        └── models.py               ← dataclass models
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

MIT — see [LICENSE](LICENSE).
