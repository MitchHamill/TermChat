"""Modal dialogs for termchat TUI — terminal-style text prompts, no buttons."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label


class ConfirmModal(ModalScreen[bool]):
    """A yes/no confirmation modal. Dismisses with True (confirmed) or False (cancelled)."""

    BINDINGS = [
        Binding("y", "confirm", "yes", show=True),
        Binding("n", "cancel", "no", show=True),
        Binding("escape", "cancel", "cancel", show=False),
    ]

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label(self._message, id="confirm-message")
            yield Label("[ y ] yes    [ n ] no", id="confirm-keys")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class BulkDeleteModal(ModalScreen[bool]):
    """Confirm deletion of multiple chats."""

    BINDINGS = [
        Binding("y", "confirm", "yes", show=True),
        Binding("n", "cancel", "no", show=True),
        Binding("escape", "cancel", "cancel", show=False),
    ]

    def __init__(self, count: int) -> None:
        super().__init__()
        self._count = count

    def compose(self) -> ComposeResult:
        noun = "chat" if self._count == 1 else "chats"
        with Vertical(id="confirm-dialog"):
            yield Label(f"Delete {self._count} {noun}?", id="confirm-message")
            yield Label("[ y ] yes    [ n ] no", id="confirm-keys")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
