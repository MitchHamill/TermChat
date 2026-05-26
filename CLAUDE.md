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
termchat chat new                        # interactive REPL
termchat chat new --model claude-opus-4-7
termchat chat list
TERMCHAT_CONFIG_DIR=/tmp/tc termchat chat new   # isolated test environment
```

There are no automated tests; manual testing via the CLI is the current verification path. Use `TERMCHAT_CONFIG_DIR` to avoid touching your real database.

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
- `main.py` — root Click group; calls `database.init()` on every invocation; registers the three sub-groups (`chat`, `project`, `config`) and a top-level `termchat new` alias.
- `chat_commands.py` — `chat new` creates a DB row then hands off to `_run_repl`; `chat resume` loads history before entering the REPL. The REPL uses `prompt_toolkit` for input and Rich panels/Live for output.
- `project_commands.py` — CRUD for projects and their attached files.
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
