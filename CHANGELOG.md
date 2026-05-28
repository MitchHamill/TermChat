# Changelog

All notable changes to termchat are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added

- **Full-screen launcher** — `termchat` now opens a keyboard-driven picker showing all projects and chats in a single unified pane. Projects are collapsible; chats are grouped beneath their project. Orphan chats appear in a separate section below.
- **AI-generated chat titles** — before the first message is sent, the AI generates a descriptive title (up to ~8 words). Project name and instructions are passed as context so titles reflect the project.
- **`termchat ask <message>`** — new top-level command that seeds the opening message and drops into the REPL.
- **Root-level message shortcut** — `termchat "What is a monad?"` works without a subcommand.
- **Tab / `/menu` to return to launcher** — press Tab or type `/menu` inside any chat to jump back to the launcher without quitting.
- **Ctrl-C confirmation** — pressing Ctrl-C in a chat now asks "Quit termchat?" before exiting, consistent regardless of entry path.
- **Persistent bottom toolbar** — the REPL shows a one-line hint bar with all hotkeys at all times.
- **Project editor** — press `e` on a project in the launcher to open an inline editor for name, instructions, and file attachments.
- **Project wizard** — press `N` in the launcher to run a guided 3-step wizard (Name → Instructions → Files) that creates a project and opens a chat.
- **Selected-files sidebar** — the file-picker step of the project wizard shows a live "Selected Files" panel alongside the directory browser.

### Changed

- Chat keys (short AI-generated slugs) replaced by full AI-generated titles. `chat resume` now accepts numeric IDs only.
- `termchat chat list` shows a **Name** column (AI title or `(untitled)`) instead of a **Key** column.
- Ctrl-C exit is now consistent: always prompts for confirmation rather than returning to launcher or exiting silently depending on entry path.

### Security

- `termchat.db` is now created with `chmod 600` (owner read/write only), matching `config.json`.
- File browser `_fb_refresh` now catches `OSError` broadly instead of `PermissionError` only, preventing unhandled crashes on removed directories or broken symlinks.

---

## [0.1.0] — Previous release

### Added

- **Chat keys** — after the first exchange, the AI generates a memorable 2–3 word slug (e.g. `fix-auth`) stored as a unique chat key.
- **Projects** — create named projects with system instructions and attached files; every chat started under a project automatically receives that context.
- **Context compression** — when a conversation exceeds 50 000 characters, old messages are automatically summarised and replaced by a single summary entry. Manual compression available via `termchat chat compress` or the `/compress` REPL command.
- **Token tracking** — per-message `input_tokens` and `output_tokens` stored in the database; `termchat chat tokens <id>` and `/tokens` show breakdowns.
- **In-REPL `/switch`**, **`/rename`**, **`/delete`**, **`/chats`** — chat management without leaving the session.
- **Unknown `/` command guard** — confirmation prompt before forwarding unrecognised slash-words to the AI.
- **"Not found" list UX** — failed ID/name lookups show the relevant list rather than a bare error.
- **`termchat new` alias** and **`tc` entry point**.
- **WAL mode + foreign keys** — SQLite database with automatic migration on startup.

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
