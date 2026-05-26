# termchat — package overview

This directory is the `termchat` Python package. It is composed of three independent layers that communicate through well-defined interfaces.

```
termchat/
├── config.py          ← global configuration (paths, API keys, limits)
├── cli/               ← Click commands and the interactive REPL
├── core/              ← AI provider calls, context management, orchestration
└── storage/           ← SQLite persistence (the only code that touches the DB)
```

---

## Layer responsibilities

### `storage/`

The only code in the entire codebase that reads or writes SQLite. Public functions accept and return plain Python dataclasses — no SQL, no `sqlite3.Row` objects, and no database handles leak outside this layer.

→ [`storage/README.md`](storage/README.md)

### `core/`

Provider-agnostic AI logic:

- **`providers/`** — the `BaseProvider` ABC and concrete implementations. The registry maps short names (e.g. `"anthropic"`) to provider classes.
- **`context.py`** — builds the system prompt from a project, converts stored `Message` objects to the `[{role, content}]` format providers expect, and owns all compression logic.
- **`chat.py`** — the single orchestration entry point: persist user turn → build context → stream response → persist assistant turn → maybe auto-compress.

→ [`core/README.md`](core/README.md)

### `cli/`

Click command groups and the interactive REPL. Imports from `core/` and `storage/` — never touches SQLite directly.

→ [`cli/README.md`](cli/README.md)

---

## `config.py`

Centralises every path and tunable constant:

| Symbol                | Default                                      | Description                        |
|-----------------------|----------------------------------------------|------------------------------------|
| `CONFIG_DIR`          | `~/.config/termchat`                         | Overridable via `TERMCHAT_CONFIG_DIR` |
| `CONFIG_FILE`         | `CONFIG_DIR/config.json`                     | JSON key/model preferences         |
| `DB_FILE`             | `CONFIG_DIR/termchat.db`                     | SQLite database                    |
| `PROVIDER_DEFAULTS`   | `{"anthropic": "claude-sonnet-4-6"}`         | Default model per provider         |
| `CONTEXT_CHAR_LIMIT`  | `50_000`                                     | Auto-compress threshold (chars)    |
| `CONTEXT_KEEP_RECENT` | `6`                                          | Messages preserved from compression|

API keys are read from environment variables first (`ANTHROPIC_API_KEY`, etc.) and fall back to `config.json`.

---

## Data flow (one chat turn)

```
User types a message
       │
       ▼
cli/chat_commands.py  (_run_repl)
       │  calls
       ▼
core/chat.py  (send_message)
       │
       ├─ storage/database.py  (add_message — persist user turn)
       ├─ core/context.py      (build_system_prompt, messages_to_api_format)
       ├─ core/providers/…     (stream — yields chunks to the REPL)
       ├─ storage/database.py  (add_message — persist assistant turn)
       └─ core/context.py      (maybe_auto_compress)
```

---

## Import conventions

- `cli/` imports from `core/` and `storage/` — never the reverse.
- `core/` imports from `storage/` for compression but not for chat orchestration setup.
- `storage/` imports nothing from `core/` or `cli/`.
