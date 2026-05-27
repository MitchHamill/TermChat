"""Textual app for termchat."""

from __future__ import annotations

from rich.panel import Panel
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header, ListView

from termchat import config
from termchat.core import chat as chat_engine
from termchat.core import context as ctx
from termchat.core.providers import get_provider
from termchat.storage import database
from termchat.storage.models import Chat, Project
from termchat.tui.widgets.chat_pane import ChatPane, MessageInput
from termchat.tui.widgets.modals import BulkDeleteModal, ConfirmModal
from termchat.tui.widgets.sidebar import ChatItem, ProjectItem, Sidebar


class TermchatApp(App):
    """Root Textual application for termchat TUI."""

    CSS_PATH = "app.tcss"
    TITLE = "termchat"

    BINDINGS = [
        Binding("n", "new_chat", "New chat", show=True),
        Binding("d", "delete_chat", "Delete", show=True),
        Binding("D", "bulk_delete", "Bulk delete", show=True),
        Binding("q", "quit", "Quit", show=True),
        Binding("tab", "toggle_focus", "Focus", show=False),
        Binding("1", "tab_chats", "Chats", show=False),
        Binding("2", "tab_projects", "Projects", show=False),
    ]

    def __init__(
        self,
        *,
        chat: Chat | None = None,
        provider=None,
        project: Project | None = None,
        cfg=None,
    ) -> None:
        super().__init__()
        self._initial_chat = chat
        self._initial_project = project
        # Current state
        self._active_chat: Chat | None = None
        self._active_project: Project | None = None
        self._provider = provider
        self._streaming: bool = False
        self._bulk_mode: bool = False
        self._bulk_selected: set[int] = set()

    # ── Layout ──────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield Sidebar(id="sidebar")
            yield ChatPane()
        yield Footer()

    async def on_mount(self) -> None:
        chats = database.list_chats(limit=50)
        projects = database.list_projects()
        self.sidebar.refresh_chats(chats)
        self.sidebar.refresh_projects(projects)

        # Verify API key for default provider
        default_provider = config.get_default_provider()
        if not config.get_api_key(default_provider):
            self.notify(
                "No API key configured. Run: termchat setup",
                severity="error",
                timeout=10,
            )

        if self._initial_chat is not None:
            await self._open_chat(self._initial_chat.id)
        elif chats:
            await self._open_chat(chats[0].id)
        else:
            self.chat_pane.show_empty_state()

    # ── Properties ──────────────────────────────────────────────────────────────

    @property
    def sidebar(self) -> Sidebar:
        return self.query_one(Sidebar)

    @property
    def chat_pane(self) -> ChatPane:
        return self.query_one(ChatPane)

    # ── Chat lifecycle ──────────────────────────────────────────────────────────

    async def _open_chat(self, chat_id: int) -> None:
        """Load *chat_id* into the chat pane and make it the active chat."""
        if self._streaming:
            # Clear the flag so the input is re-enabled when the stream finishes,
            # but do NOT kill the worker — the post-stream guard in _send_message
            # will discard its results once it sees the active chat has changed.
            self._streaming = False

        chat = database.get_chat(chat_id)
        if chat is None:
            return

        project: Project | None = None
        if chat.project_id is not None:
            project = database.get_project(chat.project_id)

        # Build a fresh provider matching this chat's provider/model
        api_key = config.get_api_key(chat.provider)
        if not api_key:
            self.notify(
                f"No API key configured for '{chat.provider}'. Run: termchat setup",
                severity="error",
            )
            return
        try:
            provider = get_provider(chat.provider, api_key, chat.model)
        except Exception as e:
            self.notify(f"Failed to initialise provider: {e}", severity="error")
            return

        self._active_chat = chat
        self._active_project = project
        self._provider = provider

        messages = database.get_messages(chat_id)
        self.chat_pane.load_messages(messages)

        label = chat.key or (f"#{chat.id}")
        self.sub_title = f"{chat.model}  •  {label}"

        # Refresh sidebar to reflect active selection
        chats = database.list_chats(limit=50)
        self.sidebar.refresh_chats(chats, active_id=chat.id)

        self.chat_pane.message_input.focus()

    # ── Message submission ──────────────────────────────────────────────────────

    async def on_message_input_submit(self, message: MessageInput.Submit) -> None:
        """Fires when the MessageInput posts a Submit message."""
        text = message.text.strip()
        if not text or not self._active_chat or self._streaming:
            return
        await self._send_message(text)

    async def _send_message(self, text: str) -> None:
        if self._active_chat is None or self._provider is None:
            return

        # Render the user's message immediately so they see it appear
        self.chat_pane.message_log.write(
            Panel(
                text,
                title="[bold blue]You[/]",
                border_style="blue",
                title_align="left",
                padding=(0, 1),
            )
        )

        self._streaming = True
        self.chat_pane.set_input_enabled(False)
        self.chat_pane.begin_stream()
        # Show typing indicator in the subtitle so the user knows we're waiting
        _prev_subtitle = self.sub_title
        self.sub_title = f"{self.sub_title}  •  Claude is typing…"

        # Capture the chat ID before launching the worker so we can detect a
        # mid-stream chat switch and discard stale post-stream mutations.
        streaming_chat_id = self._active_chat.id

        # Capture for the thread closure
        chat = self._active_chat
        provider = self._provider
        project = self._active_project
        chat_pane = self.chat_pane

        result_container: list = []
        error_container: list = []

        def _do_send() -> None:
            try:
                user_msg, asst_msg, compressed = chat_engine.send_message(
                    chat,
                    text,
                    provider,
                    project=project,
                    on_chunk=lambda chunk: self.call_from_thread(
                        chat_pane.append_chunk, chunk
                    ),
                    auto_compress=True,
                )
                result_container.append((user_msg, asst_msg, compressed))
            except Exception as e:  # noqa: BLE001
                error_container.append(e)

        worker = self.run_worker(_do_send, thread=True, exclusive=True)
        await worker.wait()

        self._streaming = False
        self.sub_title = _prev_subtitle  # restore subtitle (removes "typing…")

        # If the user switched chats while this stream was running, discard results
        if self._active_chat is None or self._active_chat.id != streaming_chat_id:
            return

        if error_container:
            self.chat_pane.message_log.write(
                Text(f"⚠ Error: {error_container[0]}", style="bold red")
            )
        elif result_container:
            _user_msg, asst_msg, compressed = result_container[0]
            self.chat_pane.end_stream(asst_msg)
            if compressed:
                self.notify("Context auto-compressed.", severity="information")
            # Generate a chat key from the first message if needed
            if self._active_chat is not None and self._active_chat.key is None:
                try:
                    raw = ctx.generate_chat_key(text, provider)
                    if raw:
                        new_key = database.update_chat_key(
                            self._active_chat.id, database.unique_chat_key(raw)
                        )
                        self._active_chat.key = new_key
                        label = self._active_chat.key or f"#{self._active_chat.id}"
                        self.sub_title = f"{self._active_chat.model}  •  {label}"
                except Exception:
                    pass
            # Refresh sidebar to bump the active chat to the top
            chats = database.list_chats(limit=50)
            active_id = self._active_chat.id if self._active_chat else None
            self.sidebar.refresh_chats(chats, active_id=active_id)

        self.chat_pane.set_input_enabled(True)
        self.chat_pane.message_input.focus()

    # ── Actions ─────────────────────────────────────────────────────────────────

    async def action_new_chat(self) -> None:
        """Create a new chat using defaults and open it."""
        pname = config.get_default_provider()
        mname = config.get_default_model(pname)
        api_key = config.get_api_key(pname)
        if not api_key:
            self.notify(
                "No API key configured. Run: termchat setup",
                severity="error",
            )
            return
        chat = database.create_chat(mname, pname)
        chats = database.list_chats(limit=50)
        self.sidebar.refresh_chats(chats, active_id=chat.id)
        await self._open_chat(chat.id)

    async def action_delete_chat(self) -> None:
        """Delete the highlighted (or active) chat after confirmation."""
        if self._streaming:
            self.notify("Cannot delete while a response is streaming.", severity="warning")
            return
        chat_id = self.sidebar.get_highlighted_chat_id()
        if chat_id is None and self._active_chat is not None:
            chat_id = self._active_chat.id
        if chat_id is None:
            return

        target = database.get_chat(chat_id)
        if target is None:
            return
        label = target.key or target.title or f"#{target.id}"
        target_id = target.id

        def _on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return
            database.delete_chat(target_id)
            chats = database.list_chats(limit=50)
            self.sidebar.refresh_chats(chats)
            if self._active_chat is not None and self._active_chat.id == target_id:
                self._active_chat = None
                self._active_project = None
                if chats:
                    self.call_after_refresh(
                        lambda: self.run_worker(self._open_chat(chats[0].id))
                    )
                else:
                    self.chat_pane.show_empty_state()
                    self.sub_title = ""

        self.push_screen(ConfirmModal(f"Delete '{label}'?"), _on_confirm)

    async def action_bulk_delete(self) -> None:
        """Toggle bulk-select mode, or confirm deletion if already in bulk mode."""
        if self._streaming:
            self.notify("Cannot delete while a response is streaming.", severity="warning")
            return
        if not self._bulk_mode:
            self._bulk_mode = True
            self._bulk_selected = set()
            self.notify(
                "Bulk select mode. Space to toggle, D to confirm, Esc to cancel.",
                severity="information",
            )
            return

        if not self._bulk_selected:
            self.notify("No chats selected.", severity="warning")
            return

        selected_ids = set(self._bulk_selected)
        count = len(selected_ids)

        def _on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return
            for chat_id in selected_ids:
                database.delete_chat(chat_id)
            self._bulk_mode = False
            self._bulk_selected = set()
            self.sidebar.set_bulk_selected(set())
            chats = database.list_chats(limit=50)
            self.sidebar.refresh_chats(chats)
            if (
                self._active_chat is not None
                and self._active_chat.id in selected_ids
            ):
                self._active_chat = None
                self._active_project = None
                if chats:
                    self.call_after_refresh(
                        lambda: self.run_worker(self._open_chat(chats[0].id))
                    )
                else:
                    self.chat_pane.show_empty_state()
                    self.sub_title = ""

        self.push_screen(BulkDeleteModal(count), _on_confirm)

    def action_toggle_focus(self) -> None:
        """Toggle focus between the chat input and the sidebar list."""
        if self.chat_pane.message_input.has_focus:
            self.sidebar.chat_list.focus()
        else:
            self.chat_pane.message_input.focus()

    def action_tab_chats(self) -> None:
        self.sidebar.switch_to_tab("chats")

    def action_tab_projects(self) -> None:
        self.sidebar.switch_to_tab("projects")

    # ── Sidebar selection ───────────────────────────────────────────────────────

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """User picked an item from the sidebar (Enter or click)."""
        item = event.item
        if isinstance(item, ChatItem):
            chat_id = item.chat_id
            self.run_worker(self._open_chat(chat_id), exclusive=False)
        elif isinstance(item, ProjectItem):
            project_id = item.project_id
            project = database.get_project(project_id)
            if project is None:
                return
            pname = config.get_default_provider()
            mname = config.get_default_model(pname)
            api_key = config.get_api_key(pname)
            if not api_key:
                self.notify(
                    "No API key configured. Run: termchat setup",
                    severity="error",
                )
                return
            chat = database.create_chat(mname, pname, project_id=project_id)
            self.sidebar.switch_to_tab("chats")
            chats = database.list_chats(limit=50)
            self.sidebar.refresh_chats(chats, active_id=chat.id)
            self.run_worker(self._open_chat(chat.id), exclusive=False)

    # ── Bulk mode key handling ──────────────────────────────────────────────────

    def on_key(self, event: events.Key) -> None:
        """Handle bulk-select hot keys when the sidebar's chat list is focused."""
        if not self._bulk_mode:
            return
        if event.key == "space":
            chat_id = self.sidebar.get_highlighted_chat_id()
            if chat_id is not None:
                if chat_id in self._bulk_selected:
                    self._bulk_selected.discard(chat_id)
                else:
                    self._bulk_selected.add(chat_id)
                self.sidebar.set_bulk_selected(self._bulk_selected)
                self.notify(
                    f"{len(self._bulk_selected)} selected",
                    severity="information",
                    timeout=1,
                )
                event.stop()
        elif event.key == "escape":
            self._bulk_mode = False
            self._bulk_selected = set()
            self.sidebar.set_bulk_selected(set())
            self.notify("Bulk select cancelled.", severity="information")
            event.stop()
