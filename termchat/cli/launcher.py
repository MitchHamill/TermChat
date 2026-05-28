"""Full-screen chat/project picker built on prompt_toolkit.

Single unified pane: projects (with collapsible chat lists) above a Chats
section for project-less chats. All navigation, delete, and bulk-delete
happen inside the full-screen app.

Returns a (action, item) tuple:
    ("open_chat",    chat)
    ("open_project", project)   — create new chat inside project
    ("new_chat",     None)
    ("new_project",  None)
    ("edit_project", project)
    ("quit",         None)
"""

from __future__ import annotations

from dataclasses import dataclass

from prompt_toolkit import Application
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style

from termchat.storage import database
from termchat.storage.models import Chat, Project

# ── Style & constants ─────────────────────────────────────────────────────────

_STYLE = Style.from_dict({
    "title":    "bold",
    "project":  "bold",
    "section":  "fg:ansigray",
    "cursor":   "bold fg:ansiblue",
    "checked":  "fg:ansigreen",
    "dim":      "fg:ansigray",
    "footer":   "fg:ansigray",
    "sep":      "fg:ansigray",
    "warn":     "fg:ansired bold",
})

_SEP = "─" * 60


# ── Row types ─────────────────────────────────────────────────────────────────

@dataclass
class _ProjectRow:
    project: Project
    collapsed: bool


@dataclass
class _ChatRow:
    chat: Chat
    project: Project | None   # None → orphan chat


@dataclass
class _SectionRow:
    """Visual separator — not selectable, cursor skips over it."""
    label: str


# ── Launcher ──────────────────────────────────────────────────────────────────

class Launcher:
    def __init__(self, chats: list[Chat], projects: list[Project]) -> None:
        self._projects: list[Project] = list(projects)
        self._collapsed: set[int] = set()   # project IDs that are collapsed
        self._sel_cursor: int = 0           # index into selectable items

        # Confirm / bulk-delete state
        self._confirming: bool = False
        self._bulk_mode: bool = False
        self._bulk_selected: set[int] = set()
        self._bulk_confirming: bool = False

        self.result: tuple | None = None

        self._index_chats(chats)

    # ── Data helpers ──────────────────────────────────────────────────────────

    def _index_chats(self, chats: list[Chat]) -> None:
        project_ids = {p.id for p in self._projects}
        self._project_chats: dict[int, list[Chat]] = {p.id: [] for p in self._projects}
        self._orphan_chats: list[Chat] = []
        for chat in chats:
            if chat.project_id and chat.project_id in project_ids:
                self._project_chats[chat.project_id].append(chat)
            else:
                self._orphan_chats.append(chat)

    def _refresh(self) -> None:
        self._projects = database.list_projects()
        self._index_chats(database.list_chats(limit=50))
        self._clamp()

    # ── Flat item list ────────────────────────────────────────────────────────

    def _flat(self) -> list:
        """Build the visible ordered list of rows."""
        rows: list = []
        for project in self._projects:
            collapsed = project.id in self._collapsed
            rows.append(_ProjectRow(project, collapsed))
            if not collapsed:
                for chat in self._project_chats.get(project.id, []):
                    rows.append(_ChatRow(chat, project))
        if self._orphan_chats:
            if self._projects:
                rows.append(_SectionRow("Chats"))
            for chat in self._orphan_chats:
                rows.append(_ChatRow(chat, None))
        return rows

    def _sel_indices(self, flat: list) -> list[int]:
        return [i for i, row in enumerate(flat) if not isinstance(row, _SectionRow)]

    def _cursor_item(self, flat: list | None = None):
        if flat is None:
            flat = self._flat()
        sel = self._sel_indices(flat)
        if not sel or self._sel_cursor >= len(sel):
            return None
        return flat[sel[self._sel_cursor]]

    def _clamp(self) -> None:
        n = len(self._sel_indices(self._flat()))
        self._sel_cursor = min(self._sel_cursor, max(0, n - 1))

    def _move(self, delta: int, flat: list | None = None) -> None:
        if flat is None:
            flat = self._flat()
        n = len(self._sel_indices(flat))
        if n:
            self._sel_cursor = (self._sel_cursor + delta) % n

    def _context_project(self, flat: list | None = None) -> Project | None:
        """Return the project in context of the cursor (header or child chat)."""
        item = self._cursor_item(flat)
        if isinstance(item, _ProjectRow):
            return item.project
        if isinstance(item, _ChatRow) and item.project is not None:
            return item.project
        return None

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _body_text(self) -> StyleAndTextTuples:
        lines: StyleAndTextTuples = []
        lines.append(("class:title", "\n  termchat\n\n"))

        flat = self._flat()
        sel = self._sel_indices(flat)
        flat_to_sel_pos = {flat_idx: sel_pos for sel_pos, flat_idx in enumerate(sel)}

        if not flat:
            lines.append(("class:dim", "  No chats or projects yet.\n"))
            return lines

        for flat_idx, row in enumerate(flat):
            sel_pos = flat_to_sel_pos.get(flat_idx)
            is_cursor = (sel_pos == self._sel_cursor)

            if isinstance(row, _SectionRow):
                label = row.label
                fill = "─" * max(0, 54 - len(label))
                lines.append(("class:section", f"\n  ── {label} {fill}\n\n"))

            elif isinstance(row, _ProjectRow):
                arrow = "▶" if row.collapsed else "▼"
                name = row.project.name
                count = len(self._project_chats.get(row.project.id, []))
                count_str = f" ({count})" if count else ""
                label = name + count_str
                if len(label) > 48:
                    label = label[:47] + "…"
                cursor_part = ("class:cursor", " ❯ ") if is_cursor else ("", "   ")
                lines.append(("", "  "))
                lines.append(cursor_part)
                lines.append(("class:project", f"{arrow} {label}\n"))

            elif isinstance(row, _ChatRow):
                title = row.chat.title or f"#{row.chat.id}"
                is_project_chat = row.project is not None
                pad = "    " if is_project_chat else "  "
                max_len = 46 if is_project_chat else 50
                if len(title) > max_len:
                    title = title[:max_len - 1] + "…"

                is_checked = self._bulk_mode and row.chat.id in self._bulk_selected
                check = ("class:checked", "✓") if is_checked else ("", " ")
                cursor_part = ("class:cursor", " ❯ ") if is_cursor else ("", "   ")

                lines.append(("", pad))
                lines.append(check)
                lines.append(cursor_part)
                lines.append(("", f"{title}\n"))

        return lines

    def _footer_text(self) -> StyleAndTextTuples:
        # Bulk-delete confirm
        if self._bulk_confirming:
            n = len(self._bulk_selected)
            return [
                ("class:warn",   f"  Delete {n} chat{'s' if n != 1 else ''}?  "),
                ("class:cursor", "[y]"), ("class:footer", " yes   "),
                ("class:cursor", "[n]"), ("class:footer", " no  "),
            ]

        # Bulk-select mode
        if self._bulk_mode:
            n = len(self._bulk_selected)
            return [
                ("class:footer", f"  [{n} selected]  "),
                ("class:cursor", "[space]"), ("class:footer", " toggle   "),
                ("class:cursor", "[D]"),     ("class:footer", " delete selected   "),
                ("class:cursor", "[esc]"),   ("class:footer", " cancel  "),
            ]

        # Single-delete confirm
        if self._confirming:
            flat = self._flat()
            item = self._cursor_item(flat)
            if isinstance(item, _ProjectRow):
                label, kind = item.project.name, "project"
            elif isinstance(item, _ChatRow):
                label, kind = item.chat.title or f"#{item.chat.id}", "chat"
            else:
                label, kind = "?", "item"
            return [
                ("class:warn",   f"  Delete {kind} '{label}'?  "),
                ("class:cursor", "[y]"), ("class:footer", " yes   "),
                ("class:cursor", "[n]"), ("class:footer", " no  "),
            ]

        # Normal hints — context-sensitive
        flat = self._flat()
        item = self._cursor_item(flat)
        hints: StyleAndTextTuples = []

        if isinstance(item, _ProjectRow):
            toggle = "expand" if item.collapsed else "collapse"
            hints += [
                ("class:cursor", "[enter]"), ("class:footer", f" {toggle}   "),
                ("class:cursor", "[n]"),     ("class:footer", " new chat   "),
                ("class:cursor", "[e]"),     ("class:footer", " edit   "),
                ("class:cursor", "[d]"),     ("class:footer", " delete   "),
            ]
        elif isinstance(item, _ChatRow):
            hints += [
                ("class:cursor", "[enter]"), ("class:footer", " open   "),
                ("class:cursor", "[n]"),     ("class:footer", " new chat   "),
                ("class:cursor", "[d]"),     ("class:footer", " delete   "),
                ("class:cursor", "[D]"),     ("class:footer", " bulk delete   "),
            ]
        else:
            hints += [("class:cursor", "[n]"), ("class:footer", " new chat   ")]

        hints += [
            ("class:cursor", "[N]"),      ("class:footer", " new project   "),
            ("class:cursor", "[↑↓/jk]"), ("class:footer", " navigate   "),
            ("class:cursor", "[q]"),      ("class:footer", " quit  "),
        ]
        return hints

    # ── Key bindings ──────────────────────────────────────────────────────────

    def _build_bindings(self, app_ref: list) -> KeyBindings:
        kb = KeyBindings()

        def inv() -> None:
            app_ref[0].invalidate()

        is_confirming      = Condition(lambda: self._confirming)
        is_bulk_confirming = Condition(lambda: self._bulk_confirming)
        is_bulk_selecting  = Condition(lambda: self._bulk_mode and not self._bulk_confirming)
        is_normal          = Condition(lambda: not self._confirming and not self._bulk_mode)

        # ── Single-delete confirm ─────────────────────────────────────────────
        @kb.add("y", filter=is_confirming)
        def _confirm_yes(_event):
            flat = self._flat()
            item = self._cursor_item(flat)
            if isinstance(item, _ProjectRow):
                database.delete_project(item.project.id)
            elif isinstance(item, _ChatRow):
                database.delete_chat(item.chat.id)
            self._confirming = False
            self._refresh()
            inv()

        @kb.add("n",      filter=is_confirming)
        @kb.add("escape", filter=is_confirming)
        def _confirm_no(_event):
            self._confirming = False
            inv()

        # ── Bulk-delete confirm ───────────────────────────────────────────────
        @kb.add("y", filter=is_bulk_confirming)
        def _bulk_yes(_event):
            for cid in self._bulk_selected:
                database.delete_chat(cid)
            self._bulk_selected = set()
            self._bulk_mode = False
            self._bulk_confirming = False
            self._refresh()
            inv()

        @kb.add("n",      filter=is_bulk_confirming)
        @kb.add("escape", filter=is_bulk_confirming)
        def _bulk_no(_event):
            self._bulk_confirming = False
            inv()

        # ── Bulk-select mode ──────────────────────────────────────────────────
        @kb.add("up",   filter=is_bulk_selecting)
        @kb.add("k",    filter=is_bulk_selecting)
        def _bulk_up(_event):
            self._move(-1)
            inv()

        @kb.add("down", filter=is_bulk_selecting)
        @kb.add("j",    filter=is_bulk_selecting)
        def _bulk_down(_event):
            self._move(1)
            inv()

        @kb.add("space", filter=is_bulk_selecting)
        def _bulk_toggle(_event):
            item = self._cursor_item()
            if isinstance(item, _ChatRow):
                cid = item.chat.id
                self._bulk_selected.discard(cid) if cid in self._bulk_selected else self._bulk_selected.add(cid)
            inv()

        @kb.add("D", filter=is_bulk_selecting)
        def _bulk_confirm(_event):
            if self._bulk_selected:
                self._bulk_confirming = True
                inv()

        @kb.add("escape", filter=is_bulk_selecting)
        def _bulk_cancel(_event):
            self._bulk_mode = False
            self._bulk_selected = set()
            inv()

        # ── Normal mode ───────────────────────────────────────────────────────
        @kb.add("up",   filter=is_normal)
        @kb.add("k",    filter=is_normal)
        def _up(_event):
            self._move(-1)
            inv()

        @kb.add("down", filter=is_normal)
        @kb.add("j",    filter=is_normal)
        def _down(_event):
            self._move(1)
            inv()

        @kb.add("right", filter=is_normal)
        @kb.add("l",     filter=is_normal)
        def _expand(_event):
            flat = self._flat()
            item = self._cursor_item(flat)
            if isinstance(item, _ProjectRow) and item.collapsed:
                self._collapsed.discard(item.project.id)
                self._clamp()
                inv()

        @kb.add("left", filter=is_normal)
        @kb.add("h",    filter=is_normal)
        def _collapse(_event):
            flat = self._flat()
            item = self._cursor_item(flat)
            if isinstance(item, _ProjectRow) and not item.collapsed:
                self._collapsed.add(item.project.id)
                self._clamp()
                inv()
            elif isinstance(item, _ChatRow) and item.project is not None:
                pid = item.project.id
                self._collapsed.add(pid)
                # Move cursor to the parent project header
                new_flat = self._flat()
                new_sel = self._sel_indices(new_flat)
                for sel_pos, flat_idx in enumerate(new_sel):
                    r = new_flat[flat_idx]
                    if isinstance(r, _ProjectRow) and r.project.id == pid:
                        self._sel_cursor = sel_pos
                        break
                inv()

        @kb.add("enter", filter=is_normal)
        def _enter(_event):
            flat = self._flat()
            item = self._cursor_item(flat)
            if isinstance(item, _ProjectRow):
                if item.collapsed:
                    self._collapsed.discard(item.project.id)
                else:
                    self._collapsed.add(item.project.id)
                self._clamp()
                inv()
            elif isinstance(item, _ChatRow):
                self.result = ("open_chat", item.chat)
                app_ref[0].exit()

        @kb.add("n", filter=is_normal)
        def _new_chat(_event):
            project = self._context_project()
            self.result = ("open_project", project) if project else ("new_chat", None)
            app_ref[0].exit()

        @kb.add("N", filter=is_normal)
        def _new_project(_event):
            self.result = ("new_project", None)
            app_ref[0].exit()

        @kb.add("e", filter=is_normal)
        def _edit(_event):
            project = self._context_project()
            if project is not None:
                self.result = ("edit_project", project)
                app_ref[0].exit()

        @kb.add("d", filter=is_normal)
        def _delete(_event):
            if self._cursor_item() is not None:
                self._confirming = True
                inv()

        @kb.add("D", filter=is_normal)
        def _bulk_start(_event):
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
