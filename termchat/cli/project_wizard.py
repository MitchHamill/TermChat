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
from prompt_toolkit.layout import ConditionalContainer, HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import D

from termchat.storage import database
from termchat.storage.models import Project
from termchat.cli.launcher import _SEP, _STYLE
from termchat.cli.file_picker import disambiguate


class ProjectWizard:
    """Three-step project creation wizard: Name → Instructions → Files."""

    def __init__(self) -> None:
        self.step: str = "name"
        self._error: str = ""

        # Step 1
        self._name_buf: Buffer = Buffer(name="wiz-name", multiline=False)

        # Step 2
        self._instr_buf: Buffer = Buffer(name="wiz-instr", multiline=True)

        # Step 3: file browser state
        self._fb_cwd: Path = Path.cwd()
        self._fb_entries: list[Path] = []
        self._fb_cursor: int = 0
        self._fb_selected: set[Path] = set()
        self._files_window: Window | None = None

        self.result: Project | None = None
        self._skipped_count: int = 0

        self._fb_refresh()

    # ── File browser helpers ──────────────────────────────────────────────────

    def _fb_refresh(self) -> None:
        """Rebuild file-browser entries for the current directory."""
        try:
            all_entries = sorted(self._fb_cwd.iterdir())
        except OSError as exc:
            self._error = str(exc)
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
        step_name = {
            "name": "Name",
            "instructions": "Instructions",
            "files": "Files",
        }.get(self.step, "")
        optional = "" if self.step == "name" else "  (optional)"
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

    def _sidebar_text(self) -> StyleAndTextTuples:
        n = len(self._fb_selected)
        lines: StyleAndTextTuples = [
            ("class:tab-on", "  Selected Files"),
            ("class:dim", f" ({n})\n" if n else " (0)\n"),
            ("class:sep", f"  {'─' * 20}\n"),
        ]
        if not self._fb_selected:
            lines.append(("class:dim", "  (none)\n"))
        else:
            ordered = sorted(self._fb_selected, key=lambda p: p.name)
            labels = disambiguate(ordered)
            for path in ordered:
                lines.append(("", f"  {labels[path]}\n"))
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
                ("class:cursor", "  [enter]"),   ("class:footer", " confirm   "),
                ("class:cursor", "[alt-enter]"), ("class:footer", " new line   "),
                ("class:cursor", "[esc]"),        ("class:footer", " skip  "),
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
            width=D(weight=3),
        )
        files_split = VSplit([
            self._files_window,
            Window(width=1, char="│", style="class:sep"),
            Window(
                content=FormattedTextControl(self._sidebar_text),
                width=D(weight=2),
            ),
        ])
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
                    files_split,
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

        # No eager=True here: must not preempt the escape+enter chord above
        @kb.add("escape", filter=is_instr)
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
        # Re-fetch so project.files is populated before the REPL uses it
        self.result = database.get_project(project.id)
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

