"""Inline (non-full-screen) file picker built on prompt_toolkit.

Run it between PromptSession calls — it renders in the current terminal
position, lets the user navigate and select files, then erases itself and
returns the selected paths.
"""

from __future__ import annotations

import sys
from pathlib import Path

from prompt_toolkit import Application
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import D

from termchat.cli.launcher import _STYLE

_BROWSER_LINES = 8
_TOTAL_LINES = 2 + _BROWSER_LINES + 1   # header + body + footer


class FilePicker:
    """Non-full-screen inline file browser. Returns a sorted list of selected Paths."""

    def __init__(self, start_dir: Path | None = None) -> None:
        self._cwd: Path = (start_dir or Path.cwd()).resolve()
        self._entries: list[Path] = []
        self._cursor: int = 0
        self._scroll: int = 0
        self._selected: set[Path] = set()
        self._error: str = ""
        self.result: list[Path] = []
        self._refresh()

    # ── File browser helpers ──────────────────────────────────────────────────

    def _refresh(self) -> None:
        try:
            all_entries = sorted(self._cwd.iterdir())
        except OSError as exc:
            self._error = str(exc)
            return
        self._error = ""
        visible = [e for e in all_entries if not e.name.startswith(".")]
        dirs  = [e for e in visible if e.is_dir()]
        files = [e for e in visible if e.is_file()]
        parent = [self._cwd.parent] if self._cwd != self._cwd.parent else []
        self._entries = parent + dirs + files
        self._cursor = 0
        self._scroll = 0

    def _current(self) -> Path | None:
        return self._entries[self._cursor] if self._entries else None

    def _is_parent(self, entry: Path) -> bool:
        return self._cwd != self._cwd.parent and entry == self._cwd.parent

    def _toggle(self, entry: Path) -> None:
        r = entry.resolve()
        if r in self._selected:
            self._selected.discard(r)
        else:
            self._selected.add(r)

    def _sync_scroll(self) -> None:
        if self._cursor < self._scroll:
            self._scroll = self._cursor
        elif self._cursor >= self._scroll + _BROWSER_LINES:
            self._scroll = self._cursor - _BROWSER_LINES + 1

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _header_text(self) -> StyleAndTextTuples:
        cwd_str = str(self._cwd)
        if len(cwd_str) > 54:
            cwd_str = "…" + cwd_str[-53:]
        return [
            ("class:dim", f"\n  Attach files  ─  {cwd_str}\n"),
        ]

    def _browser_text(self) -> StyleAndTextTuples:
        lines: StyleAndTextTuples = []
        if not self._entries:
            lines.append(("class:dim", "  (empty directory)\n"))
            return lines

        self._sync_scroll()
        start = self._scroll
        end   = min(start + _BROWSER_LINES, len(self._entries))

        for i in range(start, end):
            entry = self._entries[i]
            is_cursor   = i == self._cursor
            is_parent   = self._is_parent(entry)
            is_dir      = entry.is_dir()
            is_selected = (not is_dir) and entry.resolve() in self._selected

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
                cursor_part,
                ("class:dim", f"{type_label}  "),
                ("", f"{name_label}\n"),
            ]
        return lines

    def _sidebar_text(self) -> StyleAndTextTuples:
        n = len(self._selected)
        heading = "bold" if n else "class:dim"
        lines: StyleAndTextTuples = [
            (heading, f"\n  Selected ({n})\n"),
            ("class:sep", f"  {'─' * 18}\n"),
        ]
        if not self._selected:
            lines.append(("class:dim", "  (none)\n"))
        else:
            ordered = sorted(self._selected, key=lambda p: p.name)
            for path, label in disambiguate(ordered).items():
                lines.append(("class:checked", f"  {label}\n"))
        return lines

    def _footer_text(self) -> StyleAndTextTuples:
        lines: StyleAndTextTuples = []
        if self._error:
            lines.append(("class:warn", f"  {self._error}  "))
        n = len(self._selected)
        if n:
            lines.append(("class:footer", f"  [{n} selected]   "))
        lines += [
            ("class:cursor", "[↑↓/jk]"), ("class:footer", " nav   "),
            ("class:cursor", "[→/l]"),    ("class:footer", " enter dir   "),
            ("class:cursor", "[←/h]"),    ("class:footer", " back   "),
            ("class:cursor", "[space]"),  ("class:footer", " toggle   "),
            ("class:cursor", "[tab]"),    ("class:footer", " attach   "),
            ("class:cursor", "[esc]"),    ("class:footer", " cancel  "),
        ]
        return lines

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_layout(self) -> Layout:
        self._browser_window = Window(
            content=FormattedTextControl(self._browser_text, focusable=True),
            width=D(weight=3),
            height=_BROWSER_LINES,
        )
        body = VSplit([
            self._browser_window,
            Window(width=1, char="│", style="class:sep"),
            Window(
                content=FormattedTextControl(self._sidebar_text),
                width=D(weight=2),
                height=_BROWSER_LINES,
            ),
        ])
        return Layout(
            HSplit([
                Window(content=FormattedTextControl(self._header_text), height=2),
                body,
                Window(content=FormattedTextControl(self._footer_text), height=1),
            ]),
            focused_element=self._browser_window,
        )

    # ── Key bindings ──────────────────────────────────────────────────────────

    def _build_bindings(self, app_ref: list) -> KeyBindings:
        kb = KeyBindings()

        def inv() -> None:
            app_ref[0].invalidate()

        @kb.add("up")
        @kb.add("k")
        def _up(_event):
            if self._entries:
                self._cursor = max(0, self._cursor - 1)
            inv()

        @kb.add("down")
        @kb.add("j")
        def _down(_event):
            if self._entries:
                self._cursor = min(len(self._entries) - 1, self._cursor + 1)
            inv()

        @kb.add("right")
        @kb.add("l")
        def _right(_event):
            entry = self._current()
            if entry and entry.is_dir():
                self._cwd = entry
                self._refresh()
                inv()

        @kb.add("left")
        @kb.add("h")
        def _left(_event):
            if self._cwd != self._cwd.parent:
                self._cwd = self._cwd.parent
                self._refresh()
                inv()

        @kb.add("enter", eager=True)
        def _enter(_event):
            entry = self._current()
            if entry is None:
                return
            if entry.is_dir():
                self._cwd = entry
                self._refresh()
            else:
                self._toggle(entry)
            inv()

        @kb.add("space")
        def _space(_event):
            entry = self._current()
            if entry and not entry.is_dir():
                self._toggle(entry)
            inv()

        @kb.add("tab", eager=True)
        def _done(_event):
            self.result = sorted(self._selected)
            app_ref[0].exit()

        @kb.add("escape", eager=True)
        @kb.add("c-c")
        def _cancel(_event):
            self.result = []
            app_ref[0].exit()

        return kb

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self) -> list[Path]:
        app_ref: list = [None]
        layout = self._build_layout()
        kb     = self._build_bindings(app_ref)

        app: Application = Application(
            layout=layout,
            key_bindings=kb,
            full_screen=False,
            style=_STYLE,
            mouse_support=False,
        )
        app_ref[0] = app
        app.run()

        # Erase the picker from the terminal so it doesn't litter the chat history
        sys.stdout.write(f"\033[{_TOTAL_LINES}A\033[J")
        sys.stdout.flush()

        return self.result


# ── Shared helper ─────────────────────────────────────────────────────────────

def disambiguate(paths: list[Path]) -> dict[Path, str]:
    """Return display labels; prefix parent dir when two paths share a filename."""
    from collections import Counter
    counts = Counter(p.name for p in paths)
    return {
        p: (f"{p.parent.name}/{p.name}" if counts[p.name] > 1 else p.name)
        for p in paths
    }
