# Project Creation Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the user presses `n` on the Projects tab of the launcher, a three-step full-screen wizard guides them through naming, adding instructions, and selecting files for a new project, then drops them into a chat.

**Architecture:** A new `ProjectWizard` class in `termchat/tui/project_wizard.py` runs as a single prompt_toolkit `Application` with three steps (`name → instructions → files`) managed via internal state and `ConditionalContainer`. The launcher emits `("new_project", None)` when `n` is pressed on the Projects tab; `_run_launcher` in `chat_commands.py` calls the wizard and opens a chat with the resulting project.

**Tech Stack:** Python, prompt_toolkit (`Application`, `Buffer`, `BufferControl`, `FormattedTextControl`, `ConditionalContainer`, `KeyBindings`), existing `termchat.storage.database`, existing `_STYLE`/`_SEP` from `launcher.py`.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| **Create** | `termchat/tui/project_wizard.py` | Full wizard: 3-step UI, file browser, DB creation |
| **Modify** | `termchat/tui/launcher.py` | Make `n` tab-aware; emit `"new_project"` on Projects tab |
| **Modify** | `termchat/cli/chat_commands.py` | Handle `"new_project"` action in `_run_launcher` |

---

## Task 1: Create `project_wizard.py` — scaffold + name step

**Files:**
- Create: `termchat/tui/project_wizard.py`

- [ ] **Step 1: Create the file with scaffold, name step layout and bindings**

```python
"""Guided project creation wizard built on prompt_toolkit.

Returns a Project on success, or None if cancelled.
"""

from __future__ import annotations

from pathlib import Path

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import ConditionalContainer, HSplit, Layout, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl

from termchat.storage import database
from termchat.storage.models import Project
from termchat.tui.launcher import _SEP, _STYLE


class ProjectWizard:
    """Three-step project creation wizard: Name → Instructions → Files."""

    def __init__(self) -> None:
        self.step: str = "name"
        self._error: str = ""

        # Step 1
        self._name_buf: Buffer = Buffer(name="wiz-name", multiline=False)

        # Step 2 (added in Task 2)
        self._instr_buf: Buffer = Buffer(name="wiz-instr", multiline=True)

        # Step 3 (added in Task 3)
        self._fb_cwd: Path = Path.cwd()
        self._fb_entries: list[Path] = []
        self._fb_cursor: int = 0
        self._fb_selected: set[Path] = set()
        self._files_window: Window | None = None

        self.result: Project | None = None
        self._skipped_count: int = 0

        self._fb_refresh()

    def _fb_refresh(self) -> None:
        """Rebuild file-browser entries for the current directory."""
        try:
            all_entries = sorted(self._fb_cwd.iterdir())
        except PermissionError:
            self._error = f"Permission denied: {self._fb_cwd}"
            return
        visible = [e for e in all_entries if not e.name.startswith(".")]
        dirs  = [e for e in visible if e.is_dir()]
        files = [e for e in visible if e.is_file()]
        if self._fb_cwd != self._fb_cwd.parent:
            self._fb_entries = [self._fb_cwd.parent] + dirs + files
        else:
            self._fb_entries = dirs + files
        self._fb_cursor = 0

    def _fb_current_entry(self) -> Path | None:
        if not self._fb_entries:
            return None
        return self._fb_entries[self._fb_cursor]

    def _is_parent_entry(self, entry: Path) -> bool:
        return (
            self._fb_cwd != self._fb_cwd.parent
            and entry == self._fb_cwd.parent
        )

    def _toggle_file(self, entry: Path) -> None:
        resolved = entry.resolve()
        if resolved in self._fb_selected:
            self._fb_selected.discard(resolved)
        else:
            self._fb_selected.add(resolved)

    # ── Text getters ─────────────────────────────────────────────────────────

    def _header_text(self) -> StyleAndTextTuples:
        step_num  = {"name": 1, "instructions": 2, "files": 3}.get(self.step, 1)
        step_name = {"name": "Name", "instructions": "Instructions", "files": "Files"}.get(self.step, "")
        optional  = "" if self.step == "name" else "  (optional)"
        return [
            ("class:title",  "\n  termchat — New Project\n\n"),
            ("class:tab-on", f"  Step {step_num} of 3: {step_name}"),
            ("class:dim",    f"{optional}\n"),
            ("class:sep",    f"  {_SEP}\n\n"),
        ]

    def _files_body(self) -> StyleAndTextTuples:
        lines: StyleAndTextTuples = []
        if not self._fb_entries:
            lines.append(("class:dim", "  (empty directory)\n"))
            return lines
        for i, entry in enumerate(self._fb_entries):
            is_cursor   = i == self._fb_cursor
            is_parent   = self._is_parent_entry(entry)
            is_dir      = entry.is_dir()
            is_selected = (not is_dir) and entry.resolve() in self._fb_selected

            check_part  = ("class:checked", "✓") if is_selected else ("", " ")
            cursor_part = ("class:cursor", " ❯ ") if is_cursor else ("", "   ")

            if is_parent:
                type_label = "[dir]"
                name_label = ".."
            elif is_dir:
                type_label = "[dir]"
                name_label = entry.name + "/"
            else:
                type_label = "[✓]" if is_selected else "[ ]"
                name_label = entry.name

            lines += [
                ("", "  "),
                check_part,
                cursor_part,
                ("class:dim", f"{type_label}  "),
                ("", f"{name_label}\n"),
            ]
        return lines

    def _footer_text(self) -> StyleAndTextTuples:
        lines: StyleAndTextTuples = []
        if self._error:
            lines.append(("class:warn", f"  {self._error}\n"))
        if self.step == "name":
            lines += [
                ("class:cursor", "  [enter]"), ("class:footer", " continue   "),
                ("class:cursor", "[esc]"),     ("class:footer", " cancel  "),
            ]
        elif self.step == "instructions":
            lines += [
                ("class:cursor", "  [enter]"),     ("class:footer", " confirm   "),
                ("class:cursor", "[alt-enter]"),   ("class:footer", " new line   "),
                ("class:cursor", "[esc]"),          ("class:footer", " skip  "),
            ]
        else:  # files
            n = len(self._fb_selected)
            if n:
                lines.append(("class:footer", f"  [{n} selected]   "))
            lines += [
                ("class:cursor", "[↑↓/jk]"), ("class:footer", " nav   "),
                ("class:cursor", "[→/l]"),    ("class:footer", " enter dir   "),
                ("class:cursor", "[←/h]"),    ("class:footer", " back   "),
                ("class:cursor", "[space]"),  ("class:footer", " toggle   "),
                ("class:cursor", "[tab]"),    ("class:footer", " done   "),
                ("class:cursor", "[esc]"),    ("class:footer", " skip files  "),
            ]
        return lines

    # ── Layout ───────────────────────────────────────────────────────────────

    def _build_layout(self) -> Layout:
        self._files_window = Window(
            content=FormattedTextControl(self._files_body, focusable=True),
        )
        return Layout(
            HSplit([
                Window(content=FormattedTextControl(self._header_text), height=4),
                ConditionalContainer(
                    Window(content=BufferControl(buffer=self._name_buf), height=3),
                    filter=Condition(lambda: self.step == "name"),
                ),
                ConditionalContainer(
                    Window(content=BufferControl(buffer=self._instr_buf)),
                    filter=Condition(lambda: self.step == "instructions"),
                ),
                ConditionalContainer(
                    self._files_window,
                    filter=Condition(lambda: self.step == "files"),
                ),
                Window(content=FormattedTextControl(self._footer_text), height=2),
            ]),
            focused_element=self._name_buf,
        )

    # ── Key bindings ─────────────────────────────────────────────────────────

    def _build_bindings(self, app_ref: list) -> KeyBindings:
        kb = KeyBindings()

        def inv():
            app_ref[0].invalidate()

        is_name  = Condition(lambda: self.step == "name")
        is_instr = Condition(lambda: self.step == "instructions")
        is_files = Condition(lambda: self.step == "files")

        # ── Name step ────────────────────────────────────────────────────────
        @kb.add("escape", filter=is_name, eager=True)
        def _name_cancel(_event):
            self.result = None
            app_ref[0].exit()

        @kb.add("enter", filter=is_name, eager=True)
        def _name_enter(_event):
            name = self._name_buf.text.strip()
            if not name:
                self._error = "Name cannot be empty."
                inv()
                return
            self._error = ""
            self.step = "instructions"
            app_ref[0].layout.focus(self._instr_buf)
            inv()

        # ── Instructions step ────────────────────────────────────────────────
        @kb.add("enter", filter=is_instr, eager=True)
        def _instr_confirm(_event):
            self._error = ""
            self.step = "files"
            app_ref[0].layout.focus(self._files_window)
            inv()

        @kb.add("escape", "enter", filter=is_instr)
        def _instr_newline(event):
            event.current_buffer.insert_text("\n")

        @kb.add("escape", filter=is_instr)   # no eager: must not preempt escape+enter chord
        def _instr_skip(_event):
            self._instr_buf.text = ""
            self._error = ""
            self.step = "files"
            app_ref[0].layout.focus(self._files_window)
            inv()

        # ── Files step ───────────────────────────────────────────────────────
        @kb.add("up",   filter=is_files)
        @kb.add("k",    filter=is_files)
        def _files_up(_event):
            if self._fb_entries:
                self._fb_cursor = max(0, self._fb_cursor - 1)
            inv()

        @kb.add("down", filter=is_files)
        @kb.add("j",    filter=is_files)
        def _files_down(_event):
            if self._fb_entries:
                self._fb_cursor = min(len(self._fb_entries) - 1, self._fb_cursor + 1)
            inv()

        @kb.add("right", filter=is_files)
        @kb.add("l",     filter=is_files)
        def _files_right(_event):
            entry = self._fb_current_entry()
            if entry and entry.is_dir():
                self._fb_cwd = entry
                self._fb_refresh()
                inv()

        @kb.add("left",  filter=is_files)
        @kb.add("h",     filter=is_files)
        def _files_left(_event):
            if self._fb_cwd != self._fb_cwd.parent:
                self._fb_cwd = self._fb_cwd.parent
                self._fb_refresh()
                inv()

        @kb.add("enter", filter=is_files, eager=True)
        def _files_enter(_event):
            entry = self._fb_current_entry()
            if entry is None:
                return
            if entry.is_dir():
                self._fb_cwd = entry
                self._fb_refresh()
            else:
                self._toggle_file(entry)
            inv()

        @kb.add("space", filter=is_files)
        def _files_space(_event):
            entry = self._fb_current_entry()
            if entry and not entry.is_dir():
                self._toggle_file(entry)
            inv()

        @kb.add("tab",    filter=is_files)
        def _files_done(_event):
            self._create_and_exit(app_ref[0])

        @kb.add("escape", filter=is_files, eager=True)
        def _files_skip(_event):
            self._fb_selected = set()
            self._create_and_exit(app_ref[0])

        # ── Global ───────────────────────────────────────────────────────────
        @kb.add("c-c")
        @kb.add("c-d")
        def _force_quit(_event):
            self.result = None
            app_ref[0].exit()

        return kb

    # ── Project creation ─────────────────────────────────────────────────────

    def _create_and_exit(self, app: Application) -> None:
        name         = self._name_buf.text.strip()
        instructions = self._instr_buf.text.strip()

        try:
            project = database.create_project(name, instructions)
        except Exception as exc:
            self._error = (
                f"A project named '{name}' already exists."
                if "UNIQUE" in str(exc) else str(exc)
            )
            self.step = "name"
            app.layout.focus(self._name_buf)
            app.invalidate()
            return

        skipped = 0
        for path in sorted(self._fb_selected):
            try:
                content = path.read_text(errors="replace")
                database.add_project_file(project.id, path.name, content)
            except Exception:
                skipped += 1

        self._skipped_count = skipped
        self.result = project
        app.exit()

    # ── Run ──────────────────────────────────────────────────────────────────

    def run(self) -> Project | None:
        app_ref: list = [None]
        layout = self._build_layout()
        kb     = self._build_bindings(app_ref)

        app: Application = Application(
            layout=layout,
            key_bindings=kb,
            full_screen=True,
            style=_STYLE,
            mouse_support=False,
        )
        app_ref[0] = app
        app.run()

        if self.result and self._skipped_count > 0:
            from termchat.cli.formatting import warn
            warn(f"{self._skipped_count} file(s) could not be read and were skipped.")

        return self.result
```

- [ ] **Step 2: Smoke-test the wizard standalone (no DB needed yet)**

Run this one-liner in the project root (venv active via `source .venv/bin/activate` or use `./venv/bin/python`):

```bash
TERMCHAT_CONFIG_DIR=/tmp/tc .venv/bin/python -c "
from termchat import config; from termchat.storage import database
config.ensure_config_dir(); database.init(config.DB_FILE)
from termchat.tui.project_wizard import ProjectWizard
r = ProjectWizard().run()
print('result:', r)
"
```

Expected: full-screen wizard opens showing "Step 1 of 3: Name". Type a name, press Enter → advances to "Step 2 of 3: Instructions". Press Enter → advances to "Step 3 of 3: Files". Navigate dirs, select a file, press Tab → wizard exits and prints `result: Project(id=..., name=..., ...)`. Press Esc on Step 1 → wizard cancels, `result: None`.

- [ ] **Step 3: Commit**

```bash
git add termchat/tui/project_wizard.py
git commit -m "feat: add ProjectWizard three-step TUI (no DB wiring yet)"
```

---

## Task 2: Modify `launcher.py` — tab-aware `n` binding

**Files:**
- Modify: `termchat/tui/launcher.py`

The `_new` key binding currently always emits `("new_chat", None)`. Make it context-aware. Also update the footer hints to show the right label per tab.

- [ ] **Step 1: Replace the `_new` binding and update `_footer_text` hints**

In `termchat/tui/launcher.py`, find the `_new` handler (currently bound to `"n"` with `filter=is_normal`) and replace:

```python
@kb.add("n", filter=is_normal)
def _new(_event):
    self.result = ("new_chat", None)
    app_ref[0].exit()
```

with:

```python
@kb.add("n", filter=is_normal)
def _new(_event):
    if self.tab == "projects":
        self.result = ("new_project", None)
    else:
        self.result = ("new_chat", None)
    app_ref[0].exit()
```

Then in `_footer_text`, find the `# Normal` section and update the `[n]` hint to be tab-aware. Replace:

```python
        # Normal
        hints: StyleAndTextTuples = [
            ("class:cursor", "[↑↓/jk]"), ("class:footer", " navigate   "),
            ("class:cursor", "[enter]"),  ("class:footer", " open   "),
            ("class:cursor", "[n]"),      ("class:footer", " new   "),
        ]
        if self.tab == "chats":
            hints += [
                ("class:cursor", "[d]"), ("class:footer", " delete   "),
                ("class:cursor", "[D]"), ("class:footer", " bulk delete   "),
            ]
        hints += [("class:cursor", "[q]"), ("class:footer", " quit  ")]
        return hints
```

with:

```python
        # Normal
        new_label = " new project  " if self.tab == "projects" else " new   "
        hints: StyleAndTextTuples = [
            ("class:cursor", "[↑↓/jk]"), ("class:footer", " navigate   "),
            ("class:cursor", "[enter]"),  ("class:footer", " open   "),
            ("class:cursor", "[n]"),      ("class:footer", new_label),
        ]
        if self.tab == "chats":
            hints += [
                ("class:cursor", "[d]"), ("class:footer", " delete   "),
                ("class:cursor", "[D]"), ("class:footer", " bulk delete   "),
            ]
        hints += [("class:cursor", "[q]"), ("class:footer", " quit  ")]
        return hints
```

- [ ] **Step 2: Manual test — confirm new action emitted**

```bash
TERMCHAT_CONFIG_DIR=/tmp/tc .venv/bin/python -c "
from termchat import config; from termchat.storage import database
config.ensure_config_dir(); database.init(config.DB_FILE)
from termchat.storage import database as db
from termchat.tui.launcher import Launcher
chats = db.list_chats(limit=50)
projects = db.list_projects()
action, item = Launcher(chats, projects).run()
print('action:', action, '  item:', item)
"
```

Steps to test:
1. Press `2` to switch to the Projects tab — footer should show `[n] new project`
2. Press `n` → launcher exits → printed output shows `action: new_project  item: None`
3. Press `1` to switch to Chats tab — footer shows `[n] new` (original)
4. Press `n` → `action: new_chat  item: None`

- [ ] **Step 3: Commit**

```bash
git add termchat/tui/launcher.py
git commit -m "feat: launcher emits new_project action when n pressed on Projects tab"
```

---

## Task 3: Modify `chat_commands.py` — handle `"new_project"` in `_run_launcher`

**Files:**
- Modify: `termchat/cli/chat_commands.py`

- [ ] **Step 1: Add the `"new_project"` branch to `_run_launcher`**

In `termchat/cli/chat_commands.py`, find `_run_launcher` and locate the `elif action == "open_project":` block. Add the new branch directly **before** it:

```python
        elif action == "new_project":
            from termchat.tui.project_wizard import ProjectWizard
            project = ProjectWizard().run()
            if project:
                chat = database.create_chat(mname, pname, project.id)
                _handle_switch(_run_repl(chat, prov, project=project))
            # project is None → wizard was cancelled; outer while loop re-shows launcher
```

The full updated `_run_launcher` function body (after the change) looks like this — confirm it matches after editing:

```python
def _run_launcher(pname: str, mname: str, prov) -> None:
    """Show the full-screen chat/project picker and loop until the user quits."""
    from termchat.tui.launcher import Launcher

    while True:
        chats = database.list_chats(limit=50)
        projects = database.list_projects()

        action, item = Launcher(chats, projects).run()

        if action == "quit":
            break

        elif action == "new_chat":
            chat = database.create_chat(mname, pname)
            _handle_switch(_run_repl(chat, prov))

        elif action == "new_project":
            from termchat.tui.project_wizard import ProjectWizard
            project = ProjectWizard().run()
            if project:
                chat = database.create_chat(mname, pname, project.id)
                _handle_switch(_run_repl(chat, prov, project=project))

        elif action == "open_chat":
            chat = item
            _, _, chat_prov = _resolve_provider(chat.provider, chat.model)
            project = database.get_project(chat.project_id) if chat.project_id else None
            messages = database.get_messages(chat.id)
            if messages:
                console.print(Rule("[dim]Previous messages[/]"))
                for msg in messages:
                    render_message(msg)
                console.print()
            _handle_switch(_run_repl(chat, chat_prov, project=project))

        elif action == "open_project":
            project = item
            chat = database.create_chat(mname, pname, project.id)
            _handle_switch(_run_repl(chat, prov, project=project))
```

- [ ] **Step 2: End-to-end integration test**

```bash
TERMCHAT_CONFIG_DIR=/tmp/tc termchat chat new
```

Walk through the full flow:
1. Launcher opens on Chats tab
2. Press `2` → Projects tab, footer shows `[n] new project`
3. Press `n` → wizard opens: "Step 1 of 3: Name"
4. Type `test-proj`, press Enter → "Step 2 of 3: Instructions"
5. Type some instructions, press Enter → "Step 3 of 3: Files"
6. Navigate with ↑↓, enter a dir with →, go back with ←
7. Press Space on a file → `✓` appears in the selection indicator and footer shows `[1 selected]`
8. Press Tab → wizard exits, chat REPL opens showing `Project: test-proj`
9. Verify in another terminal: `TERMCHAT_CONFIG_DIR=/tmp/tc termchat project list` → `test-proj` appears with the selected file

**Test cancel path:**
```bash
TERMCHAT_CONFIG_DIR=/tmp/tc termchat chat new
```
1. Projects tab → `n` → wizard opens
2. Press Esc on Step 1 → wizard closes, launcher re-appears (not a crash, not a new chat)

**Test duplicate name:**
```bash
TERMCHAT_CONFIG_DIR=/tmp/tc termchat chat new
```
1. Projects tab → `n` → type `test-proj` (the one created above) → Enter → through instructions → files → Tab
2. Footer should show `A project named 'test-proj' already exists.` and return to Step 1

**Test empty name:**
1. Projects tab → `n` → press Enter immediately (empty name)
2. Footer should show `Name cannot be empty.` and stay on Step 1

- [ ] **Step 3: Commit**

```bash
git add termchat/cli/chat_commands.py
git commit -m "feat: wire new_project launcher action to ProjectWizard"
```

---

## Task 4: Final cleanup commit

- [ ] **Step 1: Clean up the isolated test DB**

```bash
rm -rf /tmp/tc
```

- [ ] **Step 2: Verify with real config (no API call needed for this)**

```bash
termchat chat list   # confirm no accidental writes to real DB
```

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat: project creation wizard from launcher

- Press n on Projects tab to open a guided 3-step wizard
- Step 1: project name (validated, duplicate-safe)
- Step 2: optional instructions (inline multiline, alt-enter for newline, esc to skip)
- Step 3: directory-browser file picker (navigate, space/enter to select, tab to confirm)
- On completion: creates project in DB, attaches files, opens chat

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```
