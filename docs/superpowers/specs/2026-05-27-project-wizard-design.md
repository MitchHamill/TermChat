# Design: Project Creation Wizard from Launcher

**Date:** 2026-05-27  
**Status:** Approved

## Overview

When the user is on the **Projects tab** of the full-screen launcher and presses `n`, a guided multi-step project creation wizard launches (instead of the current behaviour of always creating a new chat). After the wizard completes, a new chat scoped to the project opens immediately. On the **Chats tab**, `n` keeps its current behaviour (new chat).

---

## Architecture

### New file: `termchat/tui/project_wizard.py`

A self-contained `ProjectWizard` class that runs as a single prompt_toolkit `Application`. Returns `Project | None` (None = wizard was cancelled).

Internal step state machine: `"name"` → `"instructions"` → `"files"` → create and return.

Body content and footer swap between steps using `ConditionalContainer` keyed on a `Condition(lambda: self.step == "...")` filter. Focus is directed to the active `Buffer` or `Window` when transitioning steps.

### Changes to `termchat/tui/launcher.py`

- The `_new` key binding becomes tab-aware:
  - Chats tab → `self.result = ("new_chat", None)` (unchanged)
  - Projects tab → `self.result = ("new_project", None)`
- Footer hints update per-tab so `[n]` shows the right label (`new chat` vs `new project`).

### Changes to `termchat/cli/chat_commands.py`

`_run_launcher` gets a new branch:

```python
elif action == "new_project":
    from termchat.tui.project_wizard import ProjectWizard
    project = ProjectWizard().run()
    if project:
        chat = database.create_chat(mname, pname, project.id)
        _handle_switch(_run_repl(chat, prov, project=project))
    # If cancelled (None), fall through — outer while loop re-shows launcher
```

No other files require changes.

---

## Wizard Steps

All three steps run inside a single Application; the outer while-loop in `_run_launcher` keeps the launcher alive on cancel.

### Step 1 — Name

```
  termchat — New Project
  Step 1 of 3: Name
  ────────────────────────────────────────────────────

  Name: my-api-wrapper|


  [enter] continue   [esc] cancel
```

- Single-line `Buffer` (multiline=False) rendered via `BufferControl`
- Enter: validates non-empty, advances to step 2
- Esc: exits wizard (returns None to caller)

### Step 2 — Instructions *(optional)*

```
  termchat — New Project
  Step 2 of 3: Instructions
  ────────────────────────────────────────────────────

  You are an expert Python developer.
  Always write type hints.|


  [enter] confirm   [alt-enter] new line   [esc] skip
```

- Multiline `Buffer` rendered via `BufferControl`
- Same Enter/Alt-Enter pattern as the chat REPL:
  - `@kb.add("enter", eager=True)` → advance to step 3 (instructions saved, even if empty)
  - `@kb.add("escape", "enter")` → insert `\n` into buffer
- Esc: skip (instructions stored as empty string), advance to step 3

### Step 3 — Files *(optional)*

```
  termchat — New Project
  Step 3 of 3: Files
  ────────────────────────────────────────────────────

      [dir]  ..
    ❯ [dir]  termchat/
          [ ] launcher.py
      ✓   [✓] README.md
          [ ] requirements.txt

  [↑↓/jk] nav  [→/l] enter dir  [←/h] back  [space] toggle  [tab] done  [esc] skip
```

**Rendering:** `FormattedTextControl` (same approach as the launcher list). Two fixed-width columns precede each label: selection indicator and cursor indicator.

**File browser state:**
- `_fb_cwd: Path` — current directory (starts at `Path.cwd()`)
- `_fb_entries: list[Path]` — sorted entries (dirs first, then files; dotfiles excluded)
- `_fb_cursor: int` — cursor position within entries
- `_fb_selected: set[Path]` — absolute paths of selected files

**Entry list construction:** Each time the directory changes, rebuild `_fb_entries` by calling `sorted(path.iterdir())`, filter out dotfiles (`name.startswith(".")`), partition into dirs and files, concat.

If not at the filesystem root, prepend a synthetic `..` entry (displayed as `[dir]  ..`).

**Key bindings (all scoped to step=="files" Condition):**

| Key | Action |
|-----|--------|
| `up` / `k` | Move cursor up |
| `down` / `j` | Move cursor down |
| `right` / `l` / `enter` (on dir) | Enter directory, reset cursor to 0 |
| `left` / `h` | Go to parent directory, reset cursor to 0 |
| `space` / `enter` (on file) | Toggle file selection |
| `tab` | Confirm selection, proceed to create |
| `esc` | Skip files (no files attached), proceed to create |

**Distinction between dir and file on Enter/→:** The binding checks whether the entry at `_fb_cursor` is a directory before deciding whether to enter it or toggle selection. The `..` entry is treated as a directory — Enter or → on it navigates up one level (same as ← / `h`).

### Project creation (after step 3)

```python
project = database.create_project(name, instructions)
for path in sorted(self._fb_selected):
    content = path.read_text(errors="replace")
    database.add_project_file(project.id, path.name, content)
return project
```

If `database.create_project` raises a UNIQUE constraint error (duplicate name), display an inline error and return the user to step 1 rather than crashing.

---

## Layout Structure

```
HSplit([
    Window(FormattedTextControl(_header_text), height=4),  # title + step line
    ConditionalContainer(
        Window(BufferControl(name_buffer), height=3),
        filter=Condition(lambda: self.step == "name"),
    ),
    ConditionalContainer(
        Window(BufferControl(instructions_buffer)),
        filter=Condition(lambda: self.step == "instructions"),
    ),
    ConditionalContainer(
        Window(FormattedTextControl(_files_body), focusable=True),
        filter=Condition(lambda: self.step == "files"),
    ),
    Window(FormattedTextControl(_footer_text), height=2),  # key hints + error line
])
```

Focus transitions:
- On start: `layout.focus(name_buffer)`
- Name → Instructions: `layout.focus(instructions_buffer)`
- Instructions → Files: `layout.focus(files_window)` (the focusable FormattedTextControl window)

---

## Error Handling

- **Empty name on Enter (step 1):** Show inline error in footer (`"Name cannot be empty"`), stay on step 1.
- **Duplicate project name:** Show inline error in footer (`"A project with that name already exists"`), return to step 1.
- **File read error (step 3, on create):** Skip the unreadable file, continue attaching others. After all files are processed, if any were skipped, show a `class:warn` message in the wizard footer ("N file(s) could not be read and were skipped") before the wizard exits and returns the project.
- **Permission error entering a directory:** Show inline error in footer, stay in current directory.

---

## Visual Style

Follows the launcher's existing style dict (`_STYLE`) exactly — same colour classes (`class:cursor`, `class:checked`, `class:footer`, `class:warn`, etc.) and separator line. The wizard imports and reuses `_STYLE` and `_SEP` from `launcher.py`.

---

## Out of Scope

- Editing an existing project from the Projects tab (separate feature)
- Deleting projects from the launcher (separate feature)
- Recursive directory selection (select a whole folder)
- Hidden file toggle
