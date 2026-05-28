"""Inline project editor: edit name, instructions, and attachments."""

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
from termchat.storage.models import Project, ProjectFile
from termchat.cli.launcher import _SEP, _STYLE


class ProjectEditor:
    """Three-step editor: Name → Instructions → Attachments."""

    def __init__(self, project: Project) -> None:
        # Re-fetch to ensure files are populated
        full = database.get_project(project.id) or project
        self._project = full
        self.step: str = "name"
        self._error: str = ""

        self._name_buf = Buffer(name="edit-name", multiline=False,
                                document=_doc(full.name))
        self._instr_buf = Buffer(name="edit-instr", multiline=True,
                                 document=_doc(full.instructions))

        # ── Attachments state ────────────────────────────────────────────────
        self._attach_items: list[ProjectFile] = list(full.files)
        self._attach_cursor: int = 0
        self._attach_remove: set[int] = set()   # ProjectFile.id values to remove

        # ── File browser state (for adding new files) ────────────────────────
        self._files_substate: str = "attachments"  # "attachments" | "browser"
        self._fb_cwd: Path = Path.cwd()
        self._fb_entries: list[Path] = []
        self._fb_cursor: int = 0
        self._fb_selected: set[Path] = set()    # resolved paths to add
        self._files_main_window: Window | None = None
        self._fb_refresh()

        self._skipped_count: int = 0
        self.result: Project | None = None

    # ── File browser helpers ──────────────────────────────────────────────────

    def _fb_refresh(self) -> None:
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
        return self._fb_entries[self._fb_cursor] if self._fb_entries else None

    def _is_parent_entry(self, entry: Path) -> bool:
        return self._fb_cwd != self._fb_cwd.parent and entry == self._fb_cwd.parent

    def _toggle_file(self, entry: Path) -> None:
        resolved = entry.resolve()
        if resolved in self._fb_selected:
            self._fb_selected.discard(resolved)
        else:
            self._fb_selected.add(resolved)

    # ── Text getters ─────────────────────────────────────────────────────────

    def _header_text(self) -> StyleAndTextTuples:
        step_map = {
            "name":         (1, "Name",         ""),
            "instructions": (2, "Instructions", "  (optional)"),
            "files":        (3, "Attachments",  "  (optional)"),
        }
        num, name, opt = step_map.get(self.step, (1, "Name", ""))
        return [
            ("class:title",  "\n  termchat — Edit Project\n\n"),
            ("class:tab-on", f"  Step {num} of 3: {name}"),
            ("class:dim",    f"{opt}\n"),
            ("class:sep",    f"  {_SEP}\n\n"),
        ]

    def _attach_body(self) -> StyleAndTextTuples:
        lines: StyleAndTextTuples = []
        if not self._attach_items:
            lines.append(("class:dim", "  (no attachments)\n"))
            return lines
        for i, pf in enumerate(self._attach_items):
            is_cursor  = i == self._attach_cursor
            is_removed = pf.id in self._attach_remove
            cursor_part = ("class:cursor", " ❯ ") if is_cursor else ("", "   ")
            check_style = "class:warn"    if is_removed else "class:checked"
            check_char  = "✕"            if is_removed else "✓"
            name_style  = "class:dim"    if is_removed else ""
            lines += [
                ("", "  "),
                (check_style, check_char),
                cursor_part,
                (name_style, f"{pf.filename}\n"),
            ]
        return lines

    def _fb_body(self) -> StyleAndTextTuples:
        lines: StyleAndTextTuples = []
        if not self._fb_entries:
            lines.append(("class:dim", "  (empty directory)\n"))
            return lines
        for i, entry in enumerate(self._fb_entries):
            is_cursor   = i == self._fb_cursor
            is_parent   = self._is_parent_entry(entry)
            is_dir      = entry.is_dir()
            is_selected = (not is_dir) and entry.resolve() in self._fb_selected
            cursor_part = ("class:cursor", " ❯ ") if is_cursor else ("", "   ")
            if is_parent:
                type_label, name_label = "[dir]", ".."
            elif is_dir:
                type_label, name_label = "[dir]", entry.name + "/"
            else:
                type_label = "[✓]" if is_selected else "[ ]"
                name_label = entry.name
            lines += [
                ("", "  "),
                ("", ""),
                cursor_part,
                ("class:dim", f"{type_label}  "),
                ("", f"{name_label}\n"),
            ]
        return lines

    def _files_main_content(self) -> StyleAndTextTuples:
        return self._fb_body() if self._files_substate == "browser" else self._attach_body()

    def _changes_sidebar(self) -> StyleAndTextTuples:
        to_remove = [pf for pf in self._attach_items if pf.id in self._attach_remove]
        to_add    = sorted(self._fb_selected, key=lambda p: p.name)
        lines: StyleAndTextTuples = [
            ("class:tab-on", "  Changes\n"),
            ("class:sep",    f"  {'─' * 20}\n"),
        ]
        if not to_remove and not to_add:
            lines.append(("class:dim", "  (none)\n"))
            return lines
        if to_remove:
            lines.append(("class:warn", f"  Remove ({len(to_remove)}):\n"))
            for pf in to_remove:
                lines.append(("class:dim", f"    {pf.filename}\n"))
        if to_add:
            labels = _disambiguate(to_add)
            lines.append(("class:checked", f"  Add ({len(to_add)}):\n"))
            for p in to_add:
                lines.append(("", f"    {labels[p]}\n"))
        return lines

    def _footer_text(self) -> StyleAndTextTuples:
        lines: StyleAndTextTuples = []
        if self._error:
            lines.append(("class:warn", f"  {self._error}\n"))
        if self.step == "name":
            lines += [
                ("class:cursor", "  [enter]"), ("class:footer", " continue   "),
                ("class:cursor", "[esc]"),      ("class:footer", " cancel  "),
            ]
        elif self.step == "instructions":
            lines += [
                ("class:cursor", "  [enter]"),   ("class:footer", " continue   "),
                ("class:cursor", "[alt-enter]"), ("class:footer", " new line   "),
                ("class:cursor", "[esc]"),        ("class:footer", " back  "),
            ]
        elif self.step == "files":
            if self._files_substate == "attachments":
                lines += [
                    ("class:cursor", "  [↑↓/jk]"), ("class:footer", " nav   "),
                    ("class:cursor", "[space]"),    ("class:footer", " toggle remove   "),
                    ("class:cursor", "[a]"),         ("class:footer", " add files   "),
                    ("class:cursor", "[tab]"),       ("class:footer", " save   "),
                    ("class:cursor", "[esc]"),       ("class:footer", " back  "),
                ]
            else:
                lines += [
                    ("class:cursor", "  [↑↓/jk]"), ("class:footer", " nav   "),
                    ("class:cursor", "[→/l]"),       ("class:footer", " enter dir   "),
                    ("class:cursor", "[←/h]"),       ("class:footer", " back   "),
                    ("class:cursor", "[space]"),     ("class:footer", " toggle   "),
                    ("class:cursor", "[esc]"),       ("class:footer", " done adding  "),
                ]
        return lines

    # ── Layout ───────────────────────────────────────────────────────────────

    def _build_layout(self) -> Layout:
        self._files_main_window = Window(
            content=FormattedTextControl(self._files_main_content, focusable=True),
            width=D(weight=3),
        )
        files_split = VSplit([
            self._files_main_window,
            Window(width=1, char="│", style="class:sep"),
            Window(
                content=FormattedTextControl(self._changes_sidebar),
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

        is_name    = Condition(lambda: self.step == "name")
        is_instr   = Condition(lambda: self.step == "instructions")
        is_attach  = Condition(lambda: self.step == "files" and self._files_substate == "attachments")
        is_browser = Condition(lambda: self.step == "files" and self._files_substate == "browser")

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
        @kb.add("escape", "enter", filter=is_instr)
        def _instr_newline(event):
            event.current_buffer.insert_text("\n")

        @kb.add("enter", filter=is_instr, eager=True)
        def _instr_next(_event):
            self._error = ""
            self.step = "files"
            app_ref[0].layout.focus(self._files_main_window)
            inv()

        # No eager=True: must not preempt escape+enter chord above
        @kb.add("escape", filter=is_instr)
        def _instr_back(_event):
            self._error = ""
            self.step = "name"
            app_ref[0].layout.focus(self._name_buf)
            inv()

        # ── Attachments sub-step ─────────────────────────────────────────────
        @kb.add("up", filter=is_attach)
        @kb.add("k",  filter=is_attach)
        def _attach_up(_event):
            if self._attach_items:
                self._attach_cursor = max(0, self._attach_cursor - 1)
            inv()

        @kb.add("down", filter=is_attach)
        @kb.add("j",    filter=is_attach)
        def _attach_down(_event):
            if self._attach_items:
                self._attach_cursor = min(len(self._attach_items) - 1, self._attach_cursor + 1)
            inv()

        @kb.add("space", filter=is_attach)
        def _attach_toggle(_event):
            if self._attach_items:
                pf = self._attach_items[self._attach_cursor]
                if pf.id in self._attach_remove:
                    self._attach_remove.discard(pf.id)
                else:
                    self._attach_remove.add(pf.id)
            inv()

        @kb.add("a", filter=is_attach)
        def _attach_add(_event):
            self._files_substate = "browser"
            inv()

        @kb.add("tab", filter=is_attach)
        def _attach_save(_event):
            self._save_and_exit(app_ref[0])

        @kb.add("escape", filter=is_attach, eager=True)
        def _attach_back(_event):
            self._error = ""
            self.step = "instructions"
            app_ref[0].layout.focus(self._instr_buf)
            inv()

        # ── Browser sub-step ─────────────────────────────────────────────────
        @kb.add("up",   filter=is_browser)
        @kb.add("k",    filter=is_browser)
        def _browser_up(_event):
            if self._fb_entries:
                self._fb_cursor = max(0, self._fb_cursor - 1)
            inv()

        @kb.add("down", filter=is_browser)
        @kb.add("j",    filter=is_browser)
        def _browser_down(_event):
            if self._fb_entries:
                self._fb_cursor = min(len(self._fb_entries) - 1, self._fb_cursor + 1)
            inv()

        @kb.add("right", filter=is_browser)
        @kb.add("l",     filter=is_browser)
        def _browser_right(_event):
            entry = self._fb_current_entry()
            if entry and entry.is_dir():
                self._fb_cwd = entry
                self._fb_refresh()
                inv()

        @kb.add("left", filter=is_browser)
        @kb.add("h",    filter=is_browser)
        def _browser_left(_event):
            if self._fb_cwd != self._fb_cwd.parent:
                self._fb_cwd = self._fb_cwd.parent
                self._fb_refresh()
                inv()

        @kb.add("enter", filter=is_browser, eager=True)
        def _browser_enter(_event):
            entry = self._fb_current_entry()
            if entry is None:
                return
            if entry.is_dir():
                self._fb_cwd = entry
                self._fb_refresh()
            else:
                self._toggle_file(entry)
            inv()

        @kb.add("space", filter=is_browser)
        def _browser_space(_event):
            entry = self._fb_current_entry()
            if entry and not entry.is_dir():
                self._toggle_file(entry)
            inv()

        @kb.add("escape", filter=is_browser, eager=True)
        def _browser_done(_event):
            self._files_substate = "attachments"
            inv()

        @kb.add("tab", filter=is_browser)
        def _browser_save(_event):
            self._files_substate = "attachments"
            self._save_and_exit(app_ref[0])

        # ── Global ───────────────────────────────────────────────────────────
        @kb.add("c-c")
        @kb.add("c-d")
        def _force_quit(_event):
            self.result = None
            app_ref[0].exit()

        return kb

    # ── Save ─────────────────────────────────────────────────────────────────

    def _save_and_exit(self, app: Application) -> None:
        name         = self._name_buf.text.strip()
        instructions = self._instr_buf.text.strip()

        try:
            database.update_project(
                self._project.id, name=name, instructions=instructions
            )
        except Exception as exc:
            self._error = (
                f"A project named '{name}' already exists."
                if "UNIQUE" in str(exc) else str(exc)
            )
            self.step = "name"
            app.layout.focus(self._name_buf)
            app.invalidate()
            return

        for pf in self._attach_items:
            if pf.id in self._attach_remove:
                database.remove_project_file(self._project.id, pf.filename)

        skipped = 0
        for path in sorted(self._fb_selected):
            try:
                content = path.read_text(errors="replace")
                database.add_project_file(self._project.id, path.name, content)
            except Exception:
                skipped += 1

        self._skipped_count = skipped
        self.result = database.get_project(self._project.id)
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


# ── Helpers ──────────────────────────────────────────────────────────────────

def _doc(text: str):
    from prompt_toolkit.document import Document
    return Document(text, cursor_position=len(text))


def _disambiguate(paths: list[Path]) -> dict[Path, str]:
    """Return display labels; show parent/name when two paths share a filename."""
    from collections import Counter
    counts = Counter(p.name for p in paths)
    return {
        p: (f"{p.parent.name}/{p.name}" if counts[p.name] > 1 else p.name)
        for p in paths
    }
