"""Chat pane widget for termchat TUI."""

from __future__ import annotations

from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message as TxtMessage
from textual.widget import Widget
from textual.widgets import RichLog, TextArea

from termchat.storage.models import Message


class MessageLog(RichLog):
    """Scrollable log of chat messages rendered as Rich panels."""

    def __init__(self) -> None:
        super().__init__(markup=True, highlight=False, wrap=True)

    def render_message(self, msg: Message) -> None:
        """Render a single Message as a Rich panel and write it to the log."""
        if msg.role == "user":
            panel = Panel(
                msg.content,
                title="[bold blue]You[/]",
                border_style="blue",
                title_align="left",
                padding=(0, 1),
            )
        elif msg.role == "assistant":
            token_text = Text()
            token_text.append("⬆ ", style="dim")
            token_text.append(f"{msg.input_tokens or 0:,}", style="cyan dim")
            token_text.append("  ⬇ ", style="dim")
            token_text.append(f"{msg.output_tokens or 0:,}", style="green dim")
            token_text.append(" tokens", style="dim")

            panel = Panel(
                Markdown(msg.content),
                title="[bold green]Claude[/]",
                border_style="green",
                title_align="left",
                subtitle=token_text,
                subtitle_align="right",
                padding=(0, 1),
            )
        elif msg.role == "summary":
            panel = Panel(
                f"[italic dim]{msg.content}[/]",
                title="[yellow]📋 Conversation Summary[/]",
                border_style="yellow dim",
                title_align="left",
                padding=(0, 1),
            )
        else:
            return

        self.write(panel)


class MessageInput(TextArea):
    """Multi-line text input that submits on plain Enter."""

    BINDINGS = [Binding("enter", "submit", "Send", show=False)]

    class Submit(TxtMessage):
        """Posted when the user submits a message."""

        def __init__(self, *, text: str) -> None:
            super().__init__()
            self.text = text

    def __init__(self) -> None:
        super().__init__("", show_line_numbers=False, id="message-input")

    def action_submit(self) -> None:
        """Submit the current text and clear the input."""
        text = self.text
        if text:
            self.post_message(MessageInput.Submit(text=text))
            self.clear()

    def _on_key(self, event: events.Key) -> None:
        """Allow Alt+Enter to insert a newline; plain Enter submits."""
        if event.key in ("alt+enter", "shift+enter"):
            event.prevent_default()
            self.insert("\n")
        # Plain "enter" is handled by BINDINGS → action_submit


class ChatPane(Widget):
    """Main chat pane: message log above, input below."""

    def compose(self) -> ComposeResult:
        yield MessageLog()
        yield MessageInput()

    @property
    def message_log(self) -> MessageLog:
        return self.query_one(MessageLog)

    @property
    def message_input(self) -> MessageInput:
        return self.query_one(MessageInput)

    # ── History ────────────────────────────────────────────────────────────────

    def load_messages(self, messages: list[Message]) -> None:
        """Clear the log and render a full message history."""
        self.message_log.clear()
        for msg in messages:
            self.message_log.render_message(msg)

    # ── Streaming support ──────────────────────────────────────────────────────

    def begin_stream(self) -> None:
        """Prepare to receive a streamed assistant response."""
        self._stream_chunks: list[str] = []

    def append_chunk(self, chunk: str) -> None:
        """Accumulate a streamed text chunk (not displayed until end_stream)."""
        if not hasattr(self, "_stream_chunks"):
            self._stream_chunks = []
        self._stream_chunks.append(chunk)

    def end_stream(self, msg: Message) -> None:
        """Finalize streaming by rendering the completed message panel."""
        self._stream_chunks = []
        self.message_log.render_message(msg)

    # ── Misc ───────────────────────────────────────────────────────────────────

    def show_empty_state(self) -> None:
        """Clear the log and show a hint when no chat is active."""
        self.message_log.clear()
        hint = Text("Press ", style="dim")
        hint.append("n", style="bold dim")
        hint.append(" to start a new chat", style="dim")
        self.message_log.write(hint)

    def set_input_enabled(self, enabled: bool) -> None:
        """Enable or disable the message input."""
        self.message_input.disabled = not enabled
