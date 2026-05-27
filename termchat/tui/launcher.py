"""Full-screen chat/project picker built on prompt_toolkit.

Displays a navigable list of chats and projects. Returns a (action, item) tuple:
    ("open_chat",    chat)
    ("open_project", project)
    ("new_chat",     None)
    ("quit",         None)
"""

from __future__ import annotations

from prompt_toolkit import Application
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style

from termchat.storage.models import Chat, Project

# ── Style ─────────────────────────────────────────────────────────────────────

_STYLE = Style.from_dict({
    "title":      "bold",
    "tab-active": "bold",
    "tab":        "",
    "cursor":     "bold fg:ansiblue",
    "dim":        "fg:ansigray",
    "footer":     "fg:ansigray",
    "sep":        "fg:ansigray",
})

_SEP = "─" * 60


class Launcher:
    """Prompt-toolkit full-screen launcher."""

    def __init__(self, chats: list[Chat], projects: list[Project]) -> None:
        self.chats = chats
        self.projects = projects
        self.tab: str = "chats"
        self.index: int = 0
        self.result: tuple | None = None

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _current_list(self) -> list:
        return self.chats if self.tab == "chats" else self.projects

    def _item_label(self, item) -> str:
        if isinstance(item, Chat):
            raw = item.key or item.title or f"#{item.id}"
        else:
            raw = item.name
        return raw[:55]

    # ── Text getters (called on every redraw) ─────────────────────────────────

    def _body_text(self) -> StyleAndTextTuples:
        lines: StyleAndTextTuples = []

        # Title
        lines.append(("class:title", "\n  termchat\n\n"))

        # Tab bar
        for name, key in (("Chats", "1"), ("Projects", "2")):
            active = (name.lower() == self.tab)
            style = "class:tab-active" if active else "class:tab"
            lines.append((style, f"  [{key}] {name}  "))
        lines.append(("", "\n"))
        lines.append(("class:sep", f"  {_SEP}\n\n"))

        # List
        items = self._current_list()
        if not items:
            noun = self.tab
            lines.append(("class:dim", f"  No {noun} yet.\n"))
        else:
            for i, item in enumerate(items):
                label = self._item_label(item)
                if i == self.index:
                    lines.append(("class:cursor", f"  ❯ {label}\n"))
                else:
                    lines.append(("", f"    {label}\n"))

        return lines

    def _footer_text(self) -> StyleAndTextTuples:
        hints = "  [↑↓/jk] navigate  [enter] open  [n] new chat"
        if self.tab == "chats":
            hints += "  [d] delete"
        hints += "  [q] quit  "
        return [("class:footer", hints)]

    # ── Key bindings ──────────────────────────────────────────────────────────

    def _build_bindings(self, app_ref: list) -> KeyBindings:
        kb = KeyBindings()

        def _invalidate():
            app_ref[0].invalidate()

        @kb.add("up")
        @kb.add("k")
        def _up(_event):
            items = self._current_list()
            if items:
                self.index = max(0, self.index - 1)
            _invalidate()

        @kb.add("down")
        @kb.add("j")
        def _down(_event):
            items = self._current_list()
            if items:
                self.index = min(len(items) - 1, self.index + 1)
            _invalidate()

        @kb.add("1")
        def _tab_chats(_event):
            self.tab = "chats"
            self.index = 0
            _invalidate()

        @kb.add("2")
        def _tab_projects(_event):
            self.tab = "projects"
            self.index = 0
            _invalidate()

        @kb.add("enter")
        def _open(_event):
            items = self._current_list()
            if not items:
                return
            item = items[self.index]
            if self.tab == "chats":
                self.result = ("open_chat", item)
            else:
                self.result = ("open_project", item)
            app_ref[0].exit()

        @kb.add("n")
        def _new(_event):
            self.result = ("new_chat", None)
            app_ref[0].exit()

        @kb.add("d")
        def _delete(_event):
            if self.tab != "chats":
                return
            items = self._current_list()
            if not items:
                return
            self.result = ("delete_chat", items[self.index])
            app_ref[0].exit()

        @kb.add("q")
        @kb.add("c-c")
        @kb.add("c-d")
        def _quit(_event):
            self.result = ("quit", None)
            app_ref[0].exit()

        return kb

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self) -> tuple:
        app_ref: list[Application] = [None]  # type: ignore[list-item]
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
            color_depth=None,  # inherit from terminal
        )
        app_ref[0] = app
        app.run()
        return self.result or ("quit", None)
