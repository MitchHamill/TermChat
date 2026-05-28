# termchat/cli — command-line interface layer

This package contains all Click commands and the interactive REPL. It is the only layer that renders output to the terminal. It delegates all AI work to `core/` and all persistence to `storage/`.

```
cli/
├── main.py              ← Click root group, DB initialisation, top-level aliases
├── chat_commands.py     ← `chat` sub-group and the interactive REPL (_run_repl)
├── launcher.py          ← full-screen chat/project picker (prompt_toolkit Application)
├── project_wizard.py    ← 3-step new-project wizard (prompt_toolkit Application)
├── project_editor.py    ← inline project editor (prompt_toolkit Application)
├── project_commands.py  ← `project` sub-group (CRUD)
├── config_commands.py   ← `termchat setup` and `termchat config`
└── formatting.py        ← all Rich rendering helpers (shared console, tables, panels)
```

---

## Command groups

### Root — `termchat`

Defined in `main.py`. The `@click.group()` callback calls `database.init()` on every invocation so subcommands never need to think about DB setup.

Top-level aliases registered here:

| Alias                      | Maps to                                    |
|----------------------------|--------------------------------------------|
| `termchat new`             | `termchat chat new`                        |
| `termchat ask <message>`   | `termchat chat new --initial-message ...`  |
| `termchat "message"`       | root catch-all → `termchat chat new`       |
| `termchat setup`           | `termchat setup` cmd                       |

### `chat` group — `chat_commands.py`

| Command                     | Description                                    |
|-----------------------------|------------------------------------------------|
| `chat new`                  | Start a new session; opens the REPL            |
| `chat resume <ref>`         | Resume a chat by key or numeric ID             |
| `chat list`                 | List recent chats                              |
| `chat show <id>`            | Print full history (paged)                     |
| `chat tokens <id>`          | Per-message token breakdown                    |
| `chat compress <id>`        | Manually compress context                      |
| `chat delete <id>`          | Delete a chat and all its messages             |

### `project` group — `project_commands.py`

| Command                            | Description                              |
|------------------------------------|------------------------------------------|
| `project new <name>`               | Create a project (opens $EDITOR)         |
| `project list`                     | List all projects                        |
| `project show <id>`                | Show details and attached files          |
| `project edit <id>`                | Edit name or instructions                |
| `project add-instructions <id>`    | Set/append instructions from file        |
| `project add-file <id> <path>`     | Attach a file                            |
| `project remove-file <id> <name>`  | Detach a file                            |
| `project delete <id>`              | Delete a project (chats detached)        |

### `config` group — `config_commands.py`

| Command              | Description                                  |
|----------------------|----------------------------------------------|
| `setup`              | Interactive API-key and model wizard         |
| `config show`        | Print current settings (keys redacted)       |
| `config set-model`   | Change the default model                     |

---

## The interactive REPL (`_run_repl`)

`_run_repl(chat, provider, project)` lives in `chat_commands.py` and drives the main chat loop. Its lifecycle:

1. **New chat title** — if the chat has no title yet, prompts for the first message, calls `core.context.generate_chat_title()`, stores the result, then clears the screen and prints the header.
2. **Print the header** — shows the AI-generated title (or `#id`) and model name.
3. **Prompt loop** — uses `prompt_toolkit.PromptSession` with `InMemoryHistory`, custom key bindings, multiline mode, and a persistent `bottom_toolbar`.
4. **Command dispatch** — if the input starts with `/`, it is matched against `_REPL_COMMANDS`. Unknown `/` words trigger a confirmation prompt before being forwarded to the AI.
5. **AI turn** — calls `core.chat.send_message()`, renders a spinner while waiting, then prints the completed response with Markdown.
6. **`/switch` return** — if the user issues `/switch`, `_run_repl` returns the target chat ID. The outer `_handle_switch` loop re-enters `_run_repl` for the new chat.
7. **`"menu"` return** — Tab or `/menu` raises `_MenuRequest`, which `_run_repl` catches and returns `"menu"` so `_run_launcher` can re-show the picker.

### Key bindings

| Key         | Effect                                        |
|-------------|-----------------------------------------------|
| `Enter`     | Submit the message                            |
| `Alt-Enter` | Insert a newline                              |
| `Tab`       | Return to the launcher                        |
| `Ctrl-C`    | Prompt "Quit termchat?" — exits if confirmed  |
| `Ctrl-D`    | Exit immediately (EOF)                        |

---

## `formatting.py`

Shared Rich rendering helpers. All output goes through the module-level `console = Console()` instance so that paging, live rendering, and stderr are consistent.

| Function / object        | Purpose                                           |
|--------------------------|---------------------------------------------------|
| `console`                | Shared `rich.Console` instance                    |
| `err_console`            | Stderr console (bold red)                         |
| `token_badge(...)`       | Returns a `Text` object with ⬆/⬇ token counts    |
| `render_message(msg)`    | Renders a user/assistant/summary message          |
| `render_chat_list(...)`  | Renders the chat list table (ID + Name columns)   |
| `render_project_list(…)` | Renders the project list table                    |
| `render_token_summary(…)`| Prints session token totals                       |
| `success(msg)`           | Green ✓ message                                   |
| `warn(msg)`              | Yellow ⚠ message                                  |
| `error(msg)`             | Red ✗ message (to stderr)                         |

---

## "Not found" UX pattern

Commands that accept an ID or key show the relevant list when the lookup fails, rather than exiting with a bare error:

```
✗ Chat '99' not found.
╭───────────────────────────────────────────────╮
│ ID   Name                  Model   Updated   │
│  1   Fix Auth Bug          …       …         │
│ …                                            │
╰───────────────────────────────────────────────╯
```

This is implemented via `_show_chat_list()` (in `chat_commands.py`) and `_show_project_list()` (in `project_commands.py`), both called immediately before `raise click.Abort()`.

---

## Adding a new command

1. Add the function to the appropriate `*_commands.py` file, decorated with `@<group>.command("name")`.
2. If it accepts a chat ID/key or project ID that might be wrong, call `_show_chat_list()` / `_show_project_list()` on failure before aborting.
3. Use the helpers in `formatting.py` (`success`, `warn`, `error`) for output consistency.
4. No direct database calls — go through `termchat.storage.database`.
