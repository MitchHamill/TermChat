# Contributing to termchat

Thank you for your interest in contributing! This document covers how to set up the development environment, the project's conventions, and the process for submitting changes.

---

## Table of contents

1. [Development setup](#development-setup)
2. [Project structure](#project-structure)
3. [Coding conventions](#coding-conventions)
4. [Running the app locally](#running-the-app-locally)
5. [Common tasks](#common-tasks)
   - [Adding a CLI command](#adding-a-cli-command)
   - [Adding an AI provider](#adding-an-ai-provider)
   - [Changing the database schema](#changing-the-database-schema)
6. [Submitting a pull request](#submitting-a-pull-request)

---

## Development setup

```bash
# 1. Fork and clone
git clone https://github.com/<your-fork>/termchat.git
cd termchat

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install dependencies + the package in editable mode
pip install -r requirements.txt
pip install -e .

# 4. Configure a test API key
termchat setup
# or: export ANTHROPIC_API_KEY="sk-ant-…"
```

Because the package is installed with `-e`, any change to a `.py` file is immediately reflected the next time you run `termchat`.

---

## Project structure

```
termchat/
├── cli/        ← Click commands + interactive REPL (see cli/README.md)
├── core/       ← Provider calls + context management (see core/README.md)
│   └── providers/  (see core/providers/README.md)
└── storage/    ← SQLite persistence (see storage/README.md)
```

The three layers are intentionally decoupled:

- `storage/` has no imports from `core/` or `cli/`.
- `core/` can import from `storage/` (for compression) but not from `cli/`.
- `cli/` imports from both.

Keep this direction of dependencies. If you find yourself importing upward (e.g. `core/` importing from `cli/`), that is a sign the logic belongs elsewhere.

---

## Coding conventions

- **Python 3.9+** — use `from __future__ import annotations` in every file so `X | Y` union syntax works everywhere.
- **Type hints everywhere** — all function signatures should be fully annotated.
- **Dataclasses for data** — prefer `@dataclass` over dicts or namedtuples for structured data.
- **No SQL outside `storage/database.py`** — all database logic lives in one file. The rest of the codebase works with dataclass models.
- **Rich for all output** — use the shared `console` from `cli/formatting.py`. Do not call `print()`.
- **`success()`, `warn()`, `error()`** — use these formatting helpers for consistency instead of raw `console.print()` for status messages.
- **Not-found UX** — when a command accepts an ID or key and the lookup fails, show the relevant list (chats or projects) before aborting. See `_show_chat_list()` and `_show_project_list()` for the pattern.

---

## Running the app locally

```bash
# Normal usage
termchat chat new

# Isolated — won't touch your real database or config
TERMCHAT_CONFIG_DIR=/tmp/tc termchat chat new

# Use a specific model
termchat chat new --model claude-opus-4-7
```

There are no automated tests. Manual testing via the CLI with an isolated `TERMCHAT_CONFIG_DIR` is the primary verification path.

---

## Common tasks

### Adding a CLI command

1. Find the appropriate `*_commands.py` file (or create a new group).
2. Add a function decorated with `@<group>.command("name")`.
3. Accept IDs/keys as arguments and show the relevant list on a failed lookup.
4. Use only `storage/database.*` for persistence — no raw SQL.
5. Use helpers from `cli/formatting.py` for all output.

See [`cli/README.md`](termchat/cli/README.md) for a full reference.

### Adding an AI provider

See the step-by-step guide in [`core/providers/README.md`](termchat/core/providers/README.md). Summary:

1. Create `termchat/core/providers/<name>_provider.py`, subclass `BaseProvider`, implement `complete()` and `stream()`.
2. Register in `providers/__init__.py`.
3. Add to `PROVIDER_DEFAULTS` in `config.py`.

### Changing the database schema

1. Add the new columns/tables/indexes to the `_SCHEMA` string in `database.py`.
2. Add a migration in `_migrate()` so existing databases are upgraded automatically. Use `contextlib.suppress(Exception)` around DDL that may fail on already-upgraded databases (e.g. `ALTER TABLE ADD COLUMN`).
3. Update the relevant `_row_to_*` helper to map the new columns.
4. Add or update the public functions in `database.py`.
5. Update the models in `models.py`.
6. Update [`storage/README.md`](termchat/storage/README.md) with the new schema and API.

---

## Submitting a pull request

1. **Branch from `main`:** `git checkout -b feat/my-feature`
2. **Keep commits focused** — one logical change per commit.
3. **Test manually** with `TERMCHAT_CONFIG_DIR=/tmp/tc` to avoid touching your real database.
4. **Update documentation** — if you add or change a command, update the relevant README(s) and the root `README.md`.
5. **Open the PR** against `main` with a clear description of *what* changed and *why*.

---

## Questions?

Open an issue and tag it `question`. We are happy to discuss design decisions or help you find the right place for a change before you invest time writing it.
