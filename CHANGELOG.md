# Changelog

All notable changes to termchat are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added

- **Chat keys** — after the first exchange, the AI generates a memorable 2–3 word slug (e.g. `fix-auth`) stored as a unique chat key. Chats can be resumed by key (`termchat chat resume fix-auth`) instead of numeric ID.
- **Key column in chat list** — the chat list table now displays the key with `overflow="fold"` so long keys wrap rather than being truncated.
- **Projects** — create named projects with system instructions and attached files; every chat started under a project automatically receives that context.
- **Context compression** — when a conversation exceeds 50 000 characters, old messages are automatically summarised and replaced by a single summary entry. Manual compression available via `termchat chat compress` or the `/compress` REPL command.
- **Token tracking** — per-message `input_tokens` and `output_tokens` stored in the database; `termchat chat tokens <id>` and `/tokens` show breakdowns.
- **In-REPL `/switch`** — jump to another chat by key or ID without leaving the REPL.
- **In-REPL `/rename`** — rename the current chat or any other chat by reference.
- **In-REPL `/delete`** — delete the current or another chat with a confirmation prompt.
- **In-REPL `/chats`** — show the 15 most recent chats without leaving the session.
- **Unknown `/` command guard** — if a message starts with `/` but is not a recognised command, the REPL asks for confirmation before forwarding it to the AI.
- **"Not found" list UX** — commands that accept an ID or key (`chat resume`, `chat new --project`, `project show`, `project edit`, etc.) now show the relevant list whenever the lookup fails, rather than exiting with a bare error.
- **`termchat new` alias** — top-level shortcut for `termchat chat new`.
- **`tc` CLI alias** — `tc` is registered as an alternative entry point alongside `termchat`.
- **WAL mode + foreign keys** — the SQLite database runs in WAL journal mode with foreign key constraints enforced.
- **Automatic database migration** — the `_migrate()` function in `database.py` applies schema changes to existing databases on startup.

### Changed

- `chat resume` now accepts both a numeric ID and a chat key (previously ID only).
- The Key column in `termchat chat list` wraps rather than truncating.
- Project "not found" errors in `chat new --project` include the full project list.

### Fixed

- `chat resume` used the undefined variable `chat_id` instead of `chat.id` when fetching history to display before entering the REPL.

---

## [0.1.0] — Initial release

### Added

- `termchat chat new` — interactive REPL backed by the Anthropic API.
- `termchat chat list` / `show` / `delete` — chat management.
- `termchat project new` / `list` / `show` / `edit` / `delete` — project management.
- `termchat project add-file` / `remove-file` — attach files to projects.
- `termchat project add-instructions` — set or append project system instructions.
- `termchat setup` / `termchat config` — API key and model configuration.
- SQLite storage with four tables: `projects`, `project_files`, `chats`, `messages`.
- Rich terminal UI with Markdown rendering, panels, and paged history.
- `prompt_toolkit` REPL with multiline input and in-memory history.
- `TERMCHAT_CONFIG_DIR` environment variable for isolated testing.
