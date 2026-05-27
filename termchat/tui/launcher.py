"""Full-screen chat/project picker built on prompt_toolkit.

All navigation, single-delete, and bulk-delete happen inside the full-screen
application — the terminal is never briefly restored for a confirmation prompt.

Returns a (action, item) tuple to the caller:
    ("open_chat",    chat)
    ("open_project", project)
    ("new_chat",     None)
    ("quit",         None)
"""

from __future__ import annotations

from prompt_toolkit import Application
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style

from termchat.storage import database
from termchat.storage.models import Chat, Project

# ── Style ─────────────────────────────────────────────────────────────────────

_STYLE = Style.from_dict({
    "title":    "bold",
    "tab-on":   "bold",
    "tab-off":  "",
    "cursor":   "bold fg:ansiblue",
    "checked":  "fg:ansigreen",
    "dim":      "fg:ansigray",
    "footer":   "fg:ansigray",
    "sep":      "fg:ansigray",
    "warn":     "fg:ansired bold",
})

_SEP = "─" * 60


class Launcher:
    """prompt_toolkit full-screen launcher with inline delete and bulk-delete."""

    def __init__(self, chats: list[Chat], projects: list[Project]) -> None:
        self.chats = chats
        self.projects = projects
        self.tab: str = "chats"
        self.index: int = 0

        # Single-delete confirm state
        self._confirming: bool = False

        # Bulk-delete state
        self._bulk_mode: bool = False
        self._bulk_selected: set[int] = set()
        self._bulk_confirming: bool = False

        # Result to return to caller after app.exit()
        self.result: tuple | None = None

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _current_list(self) -> list:
        return self.chats if self.tab == "chats" else self.projects

    def _label(self, item) -> str:
        if isinstance(item, Chat):
            return (item.key or item.title or f"#{item.id}")[:55]
        return item.name[:55]

    def _refresh_chats(self) -> None:
        self.chats = database.list_chats(limit=50)
        # Keep cursor in bounds
        self.index = min(self.index, max(0, len(self._current_list()) - 1))

    # ── Text getters ──────────────────────────────────────────────────────────

    def _body_text(self) -> StyleAndTextTuples:
        lines: StyleAndTextTuples = []
        lines.append(("class:title", "\n  termchat\n\n"))

        # Tab bar
        for name, key in (("Chats", "1"), ("Projects", "2")):
            active = (name.lower() == self.tab)
            lines.append((f"class:tab-{'on' if active else 'off'}", f"  [{key}] {name}  "))
        lines.append(("", "\n"))
        lines.append(("class:sep", f"  {_SEP}\n\n"))

        items = self._current_list()
        if not items:
            lines.append(("class:dim", f"  No {self.tab} yet.\n"))
        else:
            for i, item in enumerate(items):
                label = self._label(item)
                is_cursor = (i == self.index)
                is_checked = (
                    self._bulk_mode
                    and isinstance(item, Chat)
                    and item.id in self._bulk_selected
                )
                if is_checked and is_cursor:
                    lines.append(("class:checked", f"  ✓ {label}\n"))
                elif is_checked:
                    lines.append(("class:checked", f"  ✓ {label}\n"))
                elif is_cursor:
                    lines.append(("class:cursor", f"  ❯ {label}\n"))
                else:
                    lines.append(("", f"    {label}\n"))

        return lines

    def _footer_text(self) -> StyleAndTextTuples:
        # Bulk-delete confirm takes priority
        if self._bulk_confirming:
            n = len(self._bulk_selected)
            noun = "chat" if n == 1 else "chats"
            return [
                ("class:warn",   f"  Delete {n} {noun}?  "),
                ("class:cursor", "[y]"),
                ("class:footer", " yes   "),
                ("class:cursor", "[n]"),
                ("class:footer", " no  "),
            ]

        # Bulk mode (selecting)
        if self._bulk_mode:
            n = len(self._bulk_selected)
            return [
                ("class:footer", f"  [{n} selected]  "),
                ("class:cursor", "[space]"),
                ("class:footer", " toggle   "),
                ("class:cursor", "[D]"),
                ("class:footer", " delete selected   "),
                ("class:cursor", "[esc]"),
                ("class:footer", " cancel  "),
            ]

        # Single-delete confirm
        if self._confirming:
            items = self._current_list()
            label = self._label(items[self.index]) if items else "?"
            return [
                ("class:warn",   f"  Delete '{label}'?  "),
                ("class:cursor", "[y]"),
                ("class:footer", " yes   "),
                ("class:cursor", "[n]"),
                ("class:footer", " no  "),
            ]

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

    # ── Key bindings ──────────────────────────────────────────────────────────

    def _build_bindings(self, app_ref: list) -> KeyBindings:
        kb = KeyBindings()

        def inv():
            app_ref[0].invalidate()

        # Pre-build Condition objects (prompt_toolkit requires these, not raw lambdas)
        is_confirming       = Condition(lambda: self._confirming)
        is_bulk_confirming  = Condition(lambda: self._bulk_confirming)
        is_bulk_selecting   = Condition(lambda: self._bulk_mode and not self._bulk_confirming)
        is_normal           = Condition(lambda: not self._confirming and not self._bulk_mode)

        # ── Confirm-mode keys (single delete) ──────────────────────────────
        @kb.add("y", filter=is_confirming)
        def _confirm_yes(_event):
            items = self._current_list()
            if items and self.tab == "chats":
                database.delete_chat(items[self.index].id)
                self._refresh_chats()
            self._confirming = False
            inv()

        @kb.add("n",      filter=is_confirming)
        @kb.add("escape", filter=is_confirming)
        def _confirm_no(_event):
            self._confirming = False
            inv()

        # ── Bulk-confirm keys ───────────────────────────────────────────────
        @kb.add("y", filter=is_bulk_confirming)
        def _bulk_confirm_yes(_event):
            for cid in self._bulk_selected:
                database.delete_chat(cid)
            self._bulk_selected = set()
            self._bulk_mode = False
            self._bulk_confirming = False
            self._refresh_chats()
            inv()

        @kb.add("n",      filter=is_bulk_confirming)
        @kb.add("escape", filter=is_bulk_confirming)
        def _bulk_confirm_no(_event):
            self._bulk_confirming = False
            inv()

        # ── Bulk-mode keys (selecting) ──────────────────────────────────────
        @kb.add("space", filter=is_bulk_selecting)
        def _bulk_toggle(_event):
            items = self._current_list()
            if items and self.tab == "chats":
                cid = items[self.index].id
                if cid in self._bulk_selected:
                    self._bulk_selected.discard(cid)
                else:
                    self._bulk_selected.add(cid)
            inv()

        @kb.add("D", filter=is_bulk_selecting)
        def _bulk_delete(_event):
            if self._bulk_selected:
                self._bulk_confirming = True
                inv()

        @kb.add("escape", filter=is_bulk_selecting)
        def _bulk_cancel(_event):
            self._bulk_mode = False
            self._bulk_selected = set()
            inv()

        # ── Normal keys ────────────────────────────────────────────────────
        @kb.add("up",   filter=is_normal)
        @kb.add("k",    filter=is_normal)
        def _up(_event):
            items = self._current_list()
            if items:
                self.index = max(0, self.index - 1)
            inv()

        @kb.add("down", filter=is_normal)
        @kb.add("j",    filter=is_normal)
        def _down(_event):
            items = self._current_list()
            if items:
                self.index = min(len(items) - 1, self.index + 1)
            inv()

        @kb.add("1", filter=is_normal)
        def _tab1(_event):
            self.tab = "chats"
            self.index = 0
            inv()

        @kb.add("2", filter=is_normal)
        def _tab2(_event):
            self.tab = "projects"
            self.index = 0
            inv()

        @kb.add("enter", filter=is_normal)
        def _open(_event):
            items = self._current_list()
            if not items:
                return
            item = items[self.index]
            self.result = (
                "open_chat" if self.tab == "chats" else "open_project",
                item,
            )
            app_ref[0].exit()

        @kb.add("n", filter=is_normal)
        def _new(_event):
            self.result = ("new_chat", None)
            app_ref[0].exit()

        @kb.add("d", filter=is_normal)
        def _delete(_event):
            if self.tab == "chats" and self._current_list():
                self._confirming = True
                inv()

        @kb.add("D", filter=is_normal)
        def _bulk_start(_event):
            if self.tab == "chats":
                self._bulk_mode = True
                self._bulk_selected = set()
                inv()

        @kb.add("q",   filter=is_normal)
        @kb.add("c-c", filter=is_normal)
        @kb.add("c-d", filter=is_normal)
        def _quit(_event):
            self.result = ("quit", None)
            app_ref[0].exit()

        return kb

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self) -> tuple:
        app_ref: list = [None]
        kb = self._build_bindings(app_ref)

        layout = Layout(
            HSplit([
                Window(
                    content=FormattedTextControl(self._body_text, focusable=True),
                ),
                Window(
                    height=1,
                    content=FormattedTextControl(self._footer_text),
                ),
            ])
        )

        app: Application = Application(
            layout=layout,
            key_bindings=kb,
            full_screen=True,
            style=_STYLE,
            mouse_support=False,
        )
        app_ref[0] = app
        app.run()
        return self.result or ("quit", None)
