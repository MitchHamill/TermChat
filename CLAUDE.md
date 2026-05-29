# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .          # installs the `termchat` CLI entry point
termchat setup            # stores API key at ~/.config/termchat/config.json
```

The `.venv` is already present in the repo root. The package is installed in editable mode, so changes to source files are immediately reflected in the `termchat` command.

## Running

```bash
termchat                                         # full-screen launcher
termchat chat new                                # same — opens launcher
termchat "What is a monad?"                      # seed opening message, drop into REPL
termchat ask "Explain Rust lifetimes"            # explicit ask command
termchat chat new --model claude-opus-4-7
termchat chat list
TERMCHAT_CONFIG_DIR=/tmp/tc termchat chat new   # isolated test environment
```

Manual testing via the CLI remains an option. Use `TERMCHAT_CONFIG_DIR` to avoid touching your real database.

## Testing

Install dev dependencies and run the suite:

```bash
pip install -e ".[dev]"   # adds pytest
pytest                    # run all tests
pytest tests/test_database.py   # single file
pytest -k "compress"     # filter by name
```

The suite is pure unit/integration — no network calls, no API key required.

### Test layout

```
tests/
├── conftest.py        — MockProvider (deterministic, no-op) + db fixture (fresh SQLite per test)
├── test_models.py     — Message.total_tokens, char_count, Project.files defaults
├── test_database.py   — CRUD for projects, project_files, chats, messages
├── test_context.py    — build_system_prompt, messages_to_api_format, compression, title gen
├── test_chat.py       — send_message + get_chat_with_messages via MockProvider
└── test_config.py     — get/set API key, model, provider; env override; corrupt JSON
```

### Key conventions

- **`db` fixture** — each test that touches the database receives an isolated SQLite file in `tmp_path`; `database._db_path` is reset to `None` on teardown so tests never share state.
- **`MockProvider`** — implements `BaseProvider` with a fixed `response` string; records calls to `.complete_calls` and `.stream_calls` for assertions; raises no network errors.
- **`isolated_config` fixture** (auto-used in `test_config.py`) — redirects `CONFIG_DIR` / `CONFIG_FILE` to `tmp_path` and clears `ANTHROPIC_API_KEY` from the environment so tests never read or write real config files.

## Architecture

The codebase has three layers that compose through clear interfaces:

### Storage (`termchat/storage/`)
- `database.py` — the only file that touches SQLite. All public functions accept/return dataclass models; no SQL leaks outside. Uses WAL mode and foreign keys.
- `models.py` — plain dataclasses mirroring the four tables: `Project`, `ProjectFile`, `Chat`, `Message`. `Message.role` is constrained to `"user" | "assistant" | "summary"`.

### Core (`termchat/core/`)
- `providers/base.py` — `BaseProvider` ABC with two required methods: `complete()` (non-streaming) and `stream()` (a generator that yields text chunks and returns a `CompletionResult` via `StopIteration`). Both provider-agnostic.
- `providers/anthropic_provider.py` — wraps the Anthropic SDK. `stream()` uses `client.messages.stream()` and captures accurate token counts from the final message.
- `providers/__init__.py` — a `_REGISTRY` dict maps provider short names (e.g. `"anthropic"`) to provider classes; `get_provider()` is the factory.
- `context.py` — builds the system prompt from a `Project` (instructions + `<file>` blocks), converts `Message` objects to the `[{role, content}]` format providers expect, and owns the compression logic. Summary messages are always sorted to the front of the API payload.
- `chat.py` — the orchestration entry point: persists the user turn, builds context, streams the provider response, persists the assistant turn, auto-sets the chat title from the first message, then calls `maybe_auto_compress`.

### CLI (`termchat/cli/`)
- `main.py` — root Click group; calls `database.init()` on every invocation; registers sub-groups (`chat`, `project`, `config`), top-level aliases (`new`, `ask`), and a catch-all that treats bare positional args as an opening message.
- `chat_commands.py` — `chat new` opens the launcher; `chat resume` loads history before entering the REPL. The REPL uses `prompt_toolkit` with a persistent toolbar, Tab-to-launcher, and Ctrl-C quit confirmation.
- `launcher.py` — full-screen prompt_toolkit `Application`; single unified pane with collapsible project groups and orphan chats below; returns action tuples to `_run_launcher`.
- `project_wizard.py` — 3-step guided wizard (Name → Instructions → Files) for creating a project from the launcher.
- `project_editor.py` — inline editor for updating a project's name, instructions, and file attachments.
- `project_commands.py` — CRUD for projects and their attached files (CLI commands).
- `config_commands.py` — `termchat setup` and `termchat config`.
- `formatting.py` — all Rich rendering helpers (shared console, `render_message`, `render_chat_list`, etc.).

### Configuration (`termchat/config.py`)
- Paths: `~/.config/termchat/config.json` (key + model prefs) and `~/.config/termchat/termchat.db` (SQLite). Both overridable via `TERMCHAT_CONFIG_DIR`.
- Compression knobs: `CONTEXT_CHAR_LIMIT = 50_000` and `CONTEXT_KEEP_RECENT = 6`.

## Adding a new provider

1. Create `termchat/core/providers/<name>_provider.py`, subclass `BaseProvider`, implement `complete()` and `stream()`.
2. Register in `termchat/core/providers/__init__.py`: add to `_REGISTRY`.
3. Optionally add a `PROVIDER_DEFAULTS` entry in `config.py`.

The storage layer, context engine, and CLI are provider-agnostic.
