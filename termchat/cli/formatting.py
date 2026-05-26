"""Shared Rich rendering helpers."""

from __future__ import annotations

from datetime import datetime

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Column, Table
from rich.text import Text
from rich import box

from termchat.storage.models import Chat, Message, Project

console = Console()
err_console = Console(stderr=True, style="bold red")


# ── Token badge ───────────────────────────────────────────────────────────────

def token_badge(input_tokens: int | None, output_tokens: int | None) -> Text:
    t = Text()
    t.append("⬆ ", style="dim")
    t.append(f"{input_tokens or 0:,}", style="cyan dim")
    t.append("  ⬇ ", style="dim")
    t.append(f"{output_tokens or 0:,}", style="green dim")
    t.append(" tokens", style="dim")
    return t


# ── Message rendering ─────────────────────────────────────────────────────────

def render_message(msg: Message, *, markdown: bool = True) -> None:
    if msg.role == "user":
        panel = Panel(
            msg.content,
            title="[bold blue]You[/]",
            border_style="blue",
            title_align="left",
            padding=(0, 1),
        )
        console.print(panel)
    elif msg.role == "assistant":
        body = Markdown(msg.content) if markdown else msg.content
        footer = token_badge(msg.input_tokens, msg.output_tokens)
        panel = Panel(
            body,
            title="[bold green]Claude[/]",
            subtitle=footer,
            border_style="green",
            title_align="left",
            subtitle_align="right",
            padding=(0, 1),
        )
        console.print(panel)
    elif msg.role == "summary":
        panel = Panel(
            f"[italic dim]{msg.content}[/]",
            title="[yellow]📋 Conversation Summary[/]",
            border_style="yellow dim",
            title_align="left",
            padding=(0, 1),
        )
        console.print(panel)


# ── Chat list ─────────────────────────────────────────────────────────────────

def render_chat_list(
    chats: list[Chat],
    projects: dict[int, str],
    *,
    current_id: int | None = None,
) -> None:
    if not chats:
        console.print("[dim]No chats yet. Start one with: termchat chat new[/]")
        return

    table = Table(
        Column(""), Column("Key", overflow="fold"), "Title", "Project", "Model", "Updated",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold",
    )
    for c in chats:
        marker = "[green]●[/]" if c.id == current_id else ""
        key_cell = f"[bold]{c.key}[/]" if c.key else f"[dim]#{c.id}[/]"
        title = c.title or "[dim]—[/]"
        proj = projects.get(c.project_id or 0, "—")
        updated = _format_dt(c.updated_at)
        table.add_row(marker, key_cell, title, proj, c.model, updated)

    console.print(table)


# ── Project list ──────────────────────────────────────────────────────────────

def render_project_list(projects: list[Project]) -> None:
    if not projects:
        console.print("[dim]No projects yet. Create one with: termchat project new <name>[/]")
        return

    table = Table(
        "ID", "Name", "Instructions", "Files", "Created",
        box=box.ROUNDED,
        header_style="bold",
    )
    for p in projects:
        instr = (p.instructions[:40] + "…") if len(p.instructions) > 40 else p.instructions
        table.add_row(
            str(p.id),
            p.name,
            instr or "[dim](none)[/]",
            str(len(p.files)),
            _format_dt(p.created_at),
        )
    console.print(table)


# ── Token summary ─────────────────────────────────────────────────────────────

def render_token_summary(totals: dict[str, int]) -> None:
    console.print(
        f"[bold]Session tokens[/]  "
        f"input [cyan]{totals['input']:,}[/]  "
        f"output [green]{totals['output']:,}[/]  "
        f"total [white]{totals['input'] + totals['output']:,}[/]"
    )


# ── Misc ──────────────────────────────────────────────────────────────────────

def _format_dt(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M")


def success(msg: str) -> None:
    console.print(f"[bold green]✓[/] {msg}")


def warn(msg: str) -> None:
    console.print(f"[bold yellow]⚠[/]  {msg}")


def error(msg: str) -> None:
    err_console.print(f"✗ {msg}")
