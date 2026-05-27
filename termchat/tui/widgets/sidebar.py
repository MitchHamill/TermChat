"""Sidebar widget for termchat TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView

from termchat.storage.models import Chat, Project


class ChatItem(ListItem):
    def __init__(self, chat: Chat) -> None:
        raw = chat.key or chat.title or f"#{chat.id}"
        if len(raw) > 18:
            raw = raw[:17] + "…"
        self._raw_label = raw
        super().__init__(Label(f"  {raw}"))  # two-space indent; "✓ " replaces it when selected
        self.chat_id = chat.id

    def set_selected(self, selected: bool) -> None:
        prefix = "✓ " if selected else "  "
        self.query_one(Label).update(prefix + self._raw_label)


class ProjectItem(ListItem):
    def __init__(self, project: Project) -> None:
        label = project.name
        if len(label) > 18:
            label = label[:17] + "…"
        super().__init__(Label(label))
        self.project_id = project.id


class ChatList(ListView):
    # Override Textual's built-in filled highlight — colour only, no background
    DEFAULT_CSS = """
    ChatList > ListItem.--highlight {
        background: transparent;
        color: $accent;
        text-style: bold;
    }
    ChatList > ListItem {
        background: transparent;
    }
    """
    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
    ]

    def populate(self, chats: list[Chat], active_id: int | None = None) -> None:
        """Clear and repopulate the list, restoring cursor to active_id."""
        self.clear()
        active_index = 0
        for i, chat in enumerate(chats):
            self.append(ChatItem(chat))
            if active_id is not None and chat.id == active_id:
                active_index = i
        if chats:
            self.index = active_index


class ProjectList(ListView):
    DEFAULT_CSS = """
    ProjectList > ListItem.--highlight {
        background: transparent;
        color: $accent;
        text-style: bold;
    }
    ProjectList > ListItem {
        background: transparent;
    }
    """
    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
    ]

    def populate(self, projects: list[Project]) -> None:
        self.clear()
        for project in projects:
            self.append(ProjectItem(project))


class Sidebar(Widget):
    """Left sidebar with Chats and Projects tabs."""

    active_tab: reactive[str] = reactive("chats")

    def compose(self) -> ComposeResult:
        yield Label("termchat", id="sidebar-title")
        yield Label("[1] Chats  [2] Projects", id="tab-bar")
        yield ChatList(id="chat-list")
        yield ProjectList(id="project-list")
        yield Label("[n] New  [?] Help", id="sidebar-footer")

    def on_mount(self) -> None:
        self.query_one("#project-list").display = False

    def watch_active_tab(self, tab: str) -> None:
        """Called when active_tab changes — swap visible list."""
        self.query_one(ChatList).display = (tab == "chats")
        self.query_one(ProjectList).display = (tab == "projects")

    def switch_to_tab(self, tab: str) -> None:
        self.active_tab = tab

    def refresh_chats(self, chats: list[Chat], active_id: int | None = None) -> None:
        self.query_one(ChatList).populate(chats, active_id)

    def refresh_projects(self, projects: list[Project]) -> None:
        self.query_one(ProjectList).populate(projects)

    @property
    def chat_list(self) -> ChatList:
        return self.query_one(ChatList)

    @property
    def project_list(self) -> ProjectList:
        return self.query_one(ProjectList)

    def get_highlighted_chat_id(self) -> int | None:
        """Return the chat_id of the currently highlighted item, or None."""
        item = self.query_one(ChatList).highlighted_child
        if isinstance(item, ChatItem):
            return item.chat_id
        return None

    def get_highlighted_project_id(self) -> int | None:
        item = self.query_one(ProjectList).highlighted_child
        if isinstance(item, ProjectItem):
            return item.project_id
        return None

    def set_bulk_selected(self, selected_ids: set[int]) -> None:
        """Toggle the ✓ prefix on ChatItems to show bulk-selection state."""
        for item in self.query_one(ChatList).query(ChatItem):
            item.set_selected(item.chat_id in selected_ids)
