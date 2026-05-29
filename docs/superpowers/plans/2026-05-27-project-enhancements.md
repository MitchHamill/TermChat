# Project Enhancements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Four targeted improvements to the Projects experience:

1. **Edit project settings** — allow renaming a project and updating its instructions from inside the TUI launcher.
2. **Verify project attachments work** — confirm that files attached to a project are actually injected into the system prompt when a chat starts.
3. **Selected-files sidebar in the file browser** — while adding files in the project wizard (or a new file-picker), show a live "Selected Files" panel so the user always knows what they've picked.
4. **See project chats** — from the Projects tab in the launcher, open a filtered chat list scoped to the selected project.

**Architecture baseline:** The launcher lives in `termchat/tui/launcher.py`, the wizard in `termchat/tui/project_wizard.py`, the REPL wiring in `termchat/cli/chat_commands.py`, context building in `termchat/core/context.py`, and the DB layer in `termchat/storage/database.py`.

---

## Task 1 — Edit project settings from the launcher

### Goal
When the user is on the **Projects tab** and presses `e`, a two-field edit form opens (name + instructions). On save, the project row is updated in the DB and the launcher refreshes.

### Files
| Action   | File                              | Change                                           |
|----------|-----------------------------------|--------------------------------------------------|
| Create   | `termchat/tui/project_editor.py`  | New `ProjectEditor` class (prompt_toolkit App)   |
| Modify   | `termchat/tui/launcher.py`        | Bind `e` on Projects tab → emit `"edit_project"` |
| Modify   | `termchat/cli/chat_commands.py`   | Handle `"edit_project"` in `_run_launcher`       |

### Steps

- [ ] **1.1 — Create `termchat/tui/project_editor.py`**

  Model it after `project_wizard.py` but with two steps instead of three: **Name** → **Instructions** (skip the file browser). Pre-populate both buffers from the existing `Project` object passed in. Return the updated `Project` on save or `None` on cancel.

  Key behaviours:
  - Step 1 (Name): `[enter]` → advance, `[esc]` → cancel editor entirely.
  - Step 2 (Instructions): `[enter]` → save (call `database.update_project`), `[alt-enter]` → newline, `[esc]` → back to Step 1.
  - Header shows `"Edit Project"` and the project name in dim text.
  - On UNIQUE constraint error (rename collision) → show error, stay on Step 1.

  ```python
  # termchat/tui/project_editor.py  (scaffold only — fill in body)
  class ProjectEditor:
      def __init__(self, project: Project) -> None: ...
      def run(self) -> Project | None: ...
  ```

  Ensure `database.update_project(project_id, *, name=None, instructions=None)` exists; add it to `database.py` if missing.

- [ ] **1.2 — Add `update_project` to `database.py` (if absent)**

  ```python
  def update_project(project_id: int, *, name: str | None = None, instructions: str | None = None) -> Project:
      """Update name and/or instructions for a project. Returns the updated project."""
  ```

  Use `UPDATE projects SET ... WHERE id = ?` with only the provided columns.

- [ ] **1.3 — Wire `e` in `launcher.py`**

  In the Projects tab's normal-mode bindings, add:
  ```python
  @kb.add("e", filter=is_normal & is_projects & has_selection)
  def _edit_project(_event):
      self.result = ("edit_project", self._current_item())
      app_ref[0].exit()
  ```
  Update `_footer_text` to show `[e] edit` in the Projects tab hint line.

- [ ] **1.4 — Handle `"edit_project"` in `_run_launcher`**

  ```python
  elif action == "edit_project":
      from termchat.tui.project_editor import ProjectEditor
      ProjectEditor(item).run()   # result ignored; DB updated inside editor
      # outer while loop re-shows launcher with fresh data
  ```

- [ ] **1.5 — Manual test**

  ```bash
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat chat new
  ```
  1. Create a project via wizard (`n` on Projects tab).
  2. On Projects tab, highlight the project and press `e`.
  3. Editor opens pre-filled with current name + instructions.
  4. Change the name → Enter → change instructions → Enter → saved.
  5. Launcher refreshes; confirm updated name appears.
  6. Try renaming to a name that already exists → error shown, stays on Step 1.

- [ ] **1.6 — Commit**

  ```bash
  git add termchat/tui/project_editor.py termchat/tui/launcher.py \
          termchat/cli/chat_commands.py termchat/storage/database.py
  git commit -m "feat: edit project name/instructions from Projects tab (e key)"
  ```

---

## Task 2 — Verify project attachments are injected into context

### Goal
Confirm (and fix if broken) that files stored in `project_files` are read and included in the system prompt when a chat is started under that project.

### Files
| Action   | File                               | Change                                                       |
|----------|------------------------------------|--------------------------------------------------------------|
| Inspect  | `termchat/core/context.py`         | Check `build_system_prompt` actually includes file content   |
| Inspect  | `termchat/storage/database.py`     | Check `get_project_files` is called and returns content      |
| Fix      | Either file, if broken             | Correct the gap                                              |

### Steps

- [ ] **2.1 — Audit `build_system_prompt` in `context.py`**

  Locate `build_system_prompt(project)`. Confirm it:
  - Calls `database.get_project_files(project.id)`.
  - Appends each file as a `<file name="…">…</file>` block (or equivalent) to the system prompt string.
  - Returns the full string.

  If the call is absent or the content is empty, fix it.

- [ ] **2.2 — Audit `get_project_files` in `database.py`**

  Confirm the query returns rows including the `content` column. Check that `ProjectFile.content` is populated (not `None`).

- [ ] **2.3 — End-to-end smoke test**

  ```bash
  # Create isolated environment
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat setup   # enter any key
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat project new verify-attach \
      --instructions "You always end replies with ATTACH_OK."
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat project add-file 1 README.md

  # Start a chat under that project and confirm the file content is visible to the model
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat chat new --project verify-attach
  ```

  Inside the REPL, send: `"What file was attached to this project and what is its first line?"`

  The model should reference `README.md` and its content. If it cannot, the attachment pipeline is broken.

- [ ] **2.4 — Add a debug helper (optional, dev-only)**

  In `termchat/core/context.py`, add a `dump_system_prompt(project)` function (or expose via `termchat config debug-context --project <id>`) that prints the full resolved system prompt without starting a chat. Useful for future debugging.

- [ ] **2.5 — Commit any fixes**

  ```bash
  git add termchat/core/context.py termchat/storage/database.py
  git commit -m "fix: ensure project file attachments are included in system prompt"
  ```

---

## Task 3 — "Selected Files" sidebar in the file browser

### Goal
In the file-browser step of `ProjectWizard` (Step 3), split the screen horizontally: left pane = directory listing (existing), right pane = **Selected Files** list. The right pane updates live as the user toggles files with Space/Enter.

### Files
| Action  | File                              | Change                                                    |
|---------|-----------------------------------|-----------------------------------------------------------|
| Modify  | `termchat/tui/project_wizard.py`  | Split `_files_window` into `VSplit(browser, sidebar)`    |

### Steps

- [ ] **3.1 — Redesign the files-step layout**

  Replace the single `self._files_window` with a `VSplit`:

  ```
  ┌───────────────────────────────┬───────────────────────┐
  │  [dir]  ..                    │  Selected Files (2)   │
  │  [dir]  src/                  │  ─────────────────   │
  │❯ [ ]    main.py               │  main.py              │
  │  [✓]    README.md             │  utils.py             │
  │  [ ]    utils.py              │                       │
  └───────────────────────────────┴───────────────────────┘
  ```

  The sidebar `FormattedTextControl` calls a new `_sidebar_text()` method:
  - Header: `"  Selected Files ({n})\n  ──────────\n"` using `class:sep` style.
  - One line per selected file showing just the filename (not full path).
  - If nothing selected: `"  (none)\n"` in `class:dim`.

  Width split: browser gets `~60 %` (or `weight=3`), sidebar gets `~40 %` (or `weight=2`).

- [ ] **3.2 — Update `_sidebar_text` to be reactive**

  Since `app.invalidate()` is already called on every toggle, the sidebar redraws automatically. No extra wiring needed.

- [ ] **3.3 — Update footer hint**

  The footer already shows `[{n} selected]` when files are chosen. Keep that and remove any redundancy if both say the count.

- [ ] **3.4 — Manual test**

  ```bash
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat chat new
  ```
  On Step 3:
  1. Right pane shows `Selected Files (0)` / `(none)`.
  2. Press Space on a file → right pane immediately shows the filename, count becomes 1.
  3. Navigate into a subdir, toggle another file → right pane shows both.
  4. Toggle the first file off → right pane shrinks back to 1.

- [ ] **3.5 — Commit**

  ```bash
  git add termchat/tui/project_wizard.py
  git commit -m "feat: selected-files sidebar in project wizard file browser"
  ```

---

## Task 4 — See project chats from the launcher

### Goal
From the **Projects tab**, pressing `Enter` on a project currently starts a new chat. Change this so `Enter` opens a **filtered chat list** scoped to that project — a sub-view inside the launcher showing only chats under that project. Pressing `n` inside this sub-view opens a new chat in the project; `Esc` returns to the Projects tab.

### Files
| Action  | File                              | Change                                                              |
|---------|-----------------------------------|---------------------------------------------------------------------|
| Modify  | `termchat/tui/launcher.py`        | `Enter` on Projects tab emits `"open_project"` (already exists)    |
| Modify  | `termchat/cli/chat_commands.py`   | `"open_project"` branch shows a project-scoped chat picker          |

> **Note:** The `"open_project"` action already exists but jumps directly to a new chat. We are replacing that with an intermediate project-chat view.

### Steps

- [ ] **4.1 — Add `list_chats_for_project(project_id)` to `database.py` (if absent)**

  ```python
  def list_chats_for_project(project_id: int, *, limit: int = 50) -> list[Chat]:
      """Return chats belonging to a given project, newest first."""
  ```

  If `list_chats` already accepts a `project_id` filter, use that instead.

- [ ] **4.2 — Design the project-chat sub-view**

  Two options — choose the simpler:

  **Option A (recommended): reuse the Launcher with a project filter**
  Pass a `project` keyword arg to `Launcher.__init__`. When set:
  - Only the Chats tab is shown (no Projects tab).
  - The header/title reads `"Project: {project.name}"`.
  - `n` emits `("new_chat_in_project", project)` instead of `("new_chat", None)`.
  - `Esc` emits `("back", None)` so `_run_launcher` can loop back to the Projects list.

  **Option B:** Create a separate `ProjectChatPicker` TUI class. More code, same result.

- [ ] **4.3 — Update `_run_launcher` to handle the project-chat flow**

  ```python
  elif action == "open_project":
      project = item
      while True:
          project_chats = database.list_chats_for_project(project.id)
          action2, item2 = Launcher(project_chats, [], project=project).run()

          if action2 in ("back", "quit"):
              break   # return to outer Projects launcher loop

          elif action2 == "new_chat_in_project":
              chat = database.create_chat(mname, pname, project.id)
              _handle_switch(_run_repl(chat, prov, project=project))

          elif action2 == "open_chat":
              chat = item2
              _, _, chat_prov = _resolve_provider(chat.provider, chat.model)
              messages = database.get_messages(chat.id)
              if messages:
                  console.print(Rule("[dim]Previous messages[/]"))
                  for msg in messages:
                      render_message(msg)
                  console.print()
              _handle_switch(_run_repl(chat, chat_prov, project=project))
  ```

- [ ] **4.4 — Update `_footer_text` and bindings in `launcher.py`**

  When in project-scoped mode (`self.project is not None`):
  - Show `[esc] back` instead of `[q] quit`.
  - Bind `escape` to emit `("back", None)`.
  - Suppress the Projects tab switcher.

- [ ] **4.5 — Manual test**

  ```bash
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat chat new
  ```
  1. Create a project, start two chats under it, exit.
  2. Re-open `termchat chat new` → Projects tab → highlight the project → Enter.
  3. Sub-view opens showing only that project's chats, header reads `"Project: <name>"`.
  4. Press `n` → new chat in project opens (model receives project context).
  5. Press `Esc` → returns to the Projects tab.
  6. A project with no chats shows the empty-state message.

- [ ] **4.6 — Commit**

  ```bash
  git add termchat/tui/launcher.py termchat/cli/chat_commands.py \
          termchat/storage/database.py
  git commit -m "feat: see project chats — Enter on project opens filtered chat list"
  ```

---

## Task 5 — Better copying

### Goal
Copying text from the terminal currently includes Rich panel borders and sidebar chrome. Provide a way to copy the last assistant response (or any message) as clean plain text, without decorations.

### Options
Two approaches — pick the simpler based on scope:

**Option A (recommended): clipboard shortcut in the REPL**
Add a `Ctrl+Y` binding in the REPL that copies the last assistant message's raw text to the system clipboard via `pyperclip`. No UI change needed; a status line flash confirms the copy.

**Option B: `/copy` slash command**
Let the user type `/copy` in the input box to copy the last assistant response. Easier to discover but requires command parsing in the REPL input handler.

### Files
| Action  | File                             | Change                                                        |
|---------|----------------------------------|---------------------------------------------------------------|
| Modify  | `termchat/cli/chat_commands.py`  | Add `Ctrl+Y` binding (or `/copy` handler) in `_run_repl`     |
| Modify  | `requirements.txt`               | Add `pyperclip` if not present                                |

### Steps

- [ ] **5.1 — Add `pyperclip` dependency**

  ```bash
  pip install pyperclip
  ```

  Add `pyperclip` to `requirements.txt`. Note: `pyperclip` requires `xclip`/`xsel` on Linux or `pbcopy` on macOS — no extra Python deps.

- [ ] **5.2 — Implement `Ctrl+Y` copy binding in `_run_repl`**

  After the REPL's key-binding setup, add:

  ```python
  @kb.add("c-y")
  def _copy_last(_event):
      # Find the last assistant message in the current chat's message list
      last = next((m for m in reversed(messages) if m.role == "assistant"), None)
      if last:
          import pyperclip
          pyperclip.copy(last.content)
          # Flash a one-line status below the input
          session.message = "  Copied to clipboard"   # or use a status bar
  ```

  If `pyperclip` raises `PyperclipException` (no clipboard backend), catch it and print a warning: `"Clipboard not available — install xclip or xsel"`.

- [ ] **5.3 — Show a brief confirmation**

  Use the existing Rich `console` to print a dim `"[dim]✓ Copied to clipboard[/dim]"` line immediately after copying (same pattern as other REPL status messages). It scrolls naturally with the conversation.

- [ ] **5.4 — Manual test**

  ```bash
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat chat new
  ```
  1. Send a message and receive a multi-line response.
  2. Press `Ctrl+Y` → `"✓ Copied to clipboard"` appears.
  3. Paste into a text editor — confirm plain text only, no `│` borders or sidebar characters.
  4. Test at the start of a new chat (no messages yet) → graceful no-op or hint.

- [ ] **5.5 — Commit**

  ```bash
  git add termchat/cli/chat_commands.py requirements.txt
  git commit -m "feat: Ctrl+Y copies last assistant response as plain text to clipboard"
  ```

---

## Task 6 — Bottom help bar in the REPL

### Goal
Add a persistent one-line status/help bar at the bottom of the REPL (just above the input prompt) showing the active mode indicators and all key bindings at a glance — so users never need to remember hotkeys.

### Design

```
 [Ctrl+T] think  [Ctrl+Y] copy  [Ctrl+C] copy-mode  [/help] commands  [Esc] quit
```

- The bar is rendered as a `prompt_toolkit` `FormattedText` bottom toolbar (the `bottom_toolbar` kwarg on `PromptSession`).
- Active modes (e.g. thinking enabled) are highlighted differently — e.g. `[Ctrl+T] think ✓` in a bold/green style vs dim when off.
- The copy-mode entry updates to reflect whether copy mode is currently active.
- The bar takes one terminal line and does not interfere with scrollback.

### Files
| Action  | File                             | Change                                                          |
|---------|----------------------------------|-----------------------------------------------------------------|
| Modify  | `termchat/cli/chat_commands.py`  | Add `bottom_toolbar` callable to `PromptSession` in `_run_repl` |
| Modify  | `termchat/cli/formatting.py`     | Add `make_bottom_toolbar(state)` helper returning `FormattedText` |

### Steps

- [ ] **6.1 — Add `make_bottom_toolbar(state)` to `formatting.py`**

  `state` is a small dict (or dataclass) holding current toggle values: `thinking_enabled`, `copy_mode_active`. Returns a `prompt_toolkit` `FormattedText` list:

  ```python
  def make_bottom_toolbar(state: dict) -> list:
      think_style = "bold fg:ansigreen" if state["thinking"] else "fg:ansibrightblack"
      copy_style  = "bold fg:ansiyellow" if state["copy_mode"] else "fg:ansibrightblack"
      return [
          (think_style, " [Ctrl+T] think "),
          ("", " · "),
          ("fg:ansibrightblack", "[Ctrl+Y] copy "),
          ("", " · "),
          (copy_style, "[Ctrl+X] copy-mode "),
          ("", " · "),
          ("fg:ansibrightblack", "[/help] commands "),
          ("", " · "),
          ("fg:ansibrightblack", "[Esc] quit "),
      ]
  ```

- [ ] **6.2 — Wire toolbar into `PromptSession` in `_run_repl`**

  Pass a lambda so it re-evaluates on each render:

  ```python
  session = PromptSession(
      ...,
      bottom_toolbar=lambda: make_bottom_toolbar(repl_state),
  )
  ```

  `repl_state` is a plain `dict` updated whenever a toggle fires (same object the key bindings already mutate for Task 7's thinking toggle).

- [ ] **6.3 — Ensure toolbar updates on mode toggle**

  `prompt_toolkit` redraws `bottom_toolbar` automatically on each new prompt render. For in-flight updates (e.g. toggling thinking mid-session), call `session.app.invalidate()` after mutating `repl_state`.

- [ ] **6.4 — Manual test**

  ```bash
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat chat new
  ```
  1. Bottom bar appears with all labels in dim style.
  2. Press `Ctrl+T` → `think` entry turns green with `✓`.
  3. Press `Ctrl+T` again → reverts to dim.
  4. Resize terminal → bar reflows correctly on one line.

- [ ] **6.5 — Commit**

  ```bash
  git add termchat/cli/chat_commands.py termchat/cli/formatting.py
  git commit -m "feat: persistent bottom help bar in REPL showing hotkeys and active modes"
  ```

---

## Task 7 — Extended thinking mode (toggle with Ctrl+T)

### Goal
Add an optional "thinking" mode that enables the Anthropic extended-thinking feature for the next (or all subsequent) requests. When active, the model reasons step-by-step before answering — similar to the Claude.ai app's "extended thinking" toggle. Off by default; toggled with `Ctrl+T`; status visible in the bottom help bar.

### How extended thinking works in the API
Pass `thinking={"type": "enabled", "budget_tokens": N}` in the `messages.create` call. The response may include `thinking` content blocks before the `text` block. These blocks contain the model's internal reasoning and should be rendered differently (collapsed or visually distinct) from the final answer.

Note: extended thinking requires a model that supports it (currently `claude-opus-4-*` and `claude-sonnet-4-*`). If the current model does not support thinking, the toggle should warn and no-op.

### Files
| Action  | File                                              | Change                                                         |
|---------|---------------------------------------------------|----------------------------------------------------------------|
| Modify  | `termchat/core/providers/anthropic_provider.py`   | Accept `thinking` kwarg; pass `thinking` param to API call     |
| Modify  | `termchat/core/providers/base.py`                 | Add optional `thinking: bool` param to `stream()` / `complete()` signatures |
| Modify  | `termchat/core/chat.py`                           | Forward `thinking` flag from REPL state to provider call       |
| Modify  | `termchat/cli/chat_commands.py`                   | Add `Ctrl+T` binding; update `repl_state`; pass flag into `send_message` |
| Modify  | `termchat/cli/formatting.py`                      | Render `thinking` content blocks in a collapsed/dim panel      |

### Steps

- [ ] **7.1 — Add `thinking` param to provider interface**

  In `base.py`, update signatures:
  ```python
  def stream(self, messages, system=None, *, thinking: bool = False) -> Generator: ...
  def complete(self, messages, system=None, *, thinking: bool = False) -> CompletionResult: ...
  ```

- [ ] **7.2 — Implement thinking in `anthropic_provider.py`**

  In `stream()`, when `thinking=True`:
  ```python
  thinking_param = {"type": "enabled", "budget_tokens": 8000} if thinking else {"type": "disabled"}
  with client.messages.stream(
      ...,
      thinking=thinking_param,
      # Note: temperature must be 1 when thinking is enabled
      temperature=1 if thinking else self._temperature,
  ) as stream:
      ...
  ```

  Thinking blocks arrive as `content_block_start` events with `type="thinking"`. Collect their `thinking` text separately from the `text` blocks. Return both in `CompletionResult` (add a `thinking_content: str | None` field).

- [ ] **7.3 — Update `CompletionResult` in `base.py`**

  ```python
  @dataclass
  class CompletionResult:
      content: str
      input_tokens: int
      output_tokens: int
      thinking_content: str | None = None
  ```

- [ ] **7.4 — Forward flag through `chat.py`**

  `send_message(chat_id, user_text, provider, *, thinking=False)` → pass `thinking` to `provider.stream(...)`.

- [ ] **7.5 — Render thinking blocks in `formatting.py`**

  Add `render_thinking(text)` that prints a collapsible dim panel:
  ```
  ╭─ Thinking ──────────────────────╮
  │ (collapsed — press T to expand) │
  ╰──────────────────────────────────╯
  ```
  Or, simpler for v1: just print the thinking text in a dim italic `Rule`-separated block above the answer. Keep it visually distinct from the final response.

- [ ] **7.6 — Add `Ctrl+T` toggle in `_run_repl`**

  ```python
  @kb.add("c-t")
  def _toggle_thinking(_event):
      repl_state["thinking"] = not repl_state["thinking"]
      # invalidate so bottom toolbar updates immediately
      _event.app.invalidate()
  ```

  Before toggling on, check if the current model supports thinking (check model name contains `opus` or `sonnet`). If not, print a warning and leave `thinking=False`.

- [ ] **7.7 — Manual test**

  ```bash
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat chat new --model claude-opus-4-7
  ```
  1. Bottom bar shows `[Ctrl+T] think` in dim.
  2. Press `Ctrl+T` → bar shows `[Ctrl+T] think ✓` in green.
  3. Send a message → response renders a dim "Thinking" block followed by the answer.
  4. Press `Ctrl+T` again → thinking off; next response has no thinking block.
  5. Test on a model that doesn't support thinking → warning, no crash.

- [ ] **7.8 — Commit**

  ```bash
  git add termchat/core/providers/anthropic_provider.py \
          termchat/core/providers/base.py \
          termchat/core/chat.py \
          termchat/cli/chat_commands.py \
          termchat/cli/formatting.py
  git commit -m "feat: extended thinking mode toggle (Ctrl+T) with visual thinking block rendering"
  ```

---

## Task 8 — Final integration pass

- [ ] **8.1 — Run the full manual test suite**

  Test each feature end-to-end in a clean `TERMCHAT_CONFIG_DIR=/tmp/tc` environment:
  - Edit a project (rename + instructions).
  - Attach a file, open a chat, verify the file content appears in model responses.
  - Wizard file browser shows selected-files sidebar.
  - Projects tab → Enter → see scoped chats → new chat → back.
  - `Ctrl+Y` copies last assistant message as clean plain text.
  - Bottom help bar visible; labels update when modes toggle.
  - `Ctrl+T` enables thinking; response includes rendered thinking block.

- [ ] **8.2 — Clean up test environment**

  ```bash
  rm -rf /tmp/tc
  ```

- [ ] **8.3 — Final commit**

  ```bash
  git add -A
  git commit -m "feat: project enhancements — edit settings, attachment verification, selected-files sidebar, project chat view, clipboard copy, help bar, thinking mode

  - e key on Projects tab opens inline project editor (name + instructions)
  - Verified project file attachments are correctly injected into system prompt
  - File browser in wizard shows live 'Selected Files' sidebar on the right
  - Enter on a project in Projects tab opens a filtered chat list for that project
  - Ctrl+Y copies last assistant response as plain text to clipboard
  - Persistent bottom help bar shows all hotkeys and active mode indicators
  - Ctrl+T toggles extended thinking mode with visual thinking block rendering

  Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
  ```
