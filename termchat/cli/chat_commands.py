"""Chat commands — new, list, show, delete, compress, resume."""

from __future__ import annotations

import sys

import click
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from termchat import config
from termchat.cli.formatting import (
    _format_dt,
    console,
    error,
    render_chat_list,
    render_message,
    render_token_summary,
    success,
    token_badge,
    warn,
)
from termchat.core import context as ctx
from termchat.core import chat as chat_engine
from termchat.core.providers import get_provider
from termchat.storage import database
from termchat.storage.models import Chat, Message


def _resolve_chat_ref(ref: str) -> Chat | None:
    """Accept either a numeric ID or a chat key and return the Chat."""
    try:
        return database.get_chat(int(ref))
    except ValueError:
        return database.get_chat_by_key(ref)


def _show_chat_list(*, current_id: int | None = None) -> None:
    """Print a brief chat list — used after a failed lookup."""
    chats = database.list_chats(limit=15)
    projects_map: dict[int, str] = {p.id: p.name for p in database.list_projects()}
    render_chat_list(chats, projects_map, current_id=current_id)
    if len(chats) == 15:
        console.print("[dim]Showing 15 most recent. Use [bold]termchat chat list[/] to see all.[/]")

# ── REPL helpers ──────────────────────────────────────────────────────────────

_REPL_HELP = """\
[bold]In-chat commands[/]
  [cyan]/help[/]                — show this message
  [cyan]/history[/]             — browse full conversation history in a pager
  [cyan]/tokens[/]              — show token usage for this chat
  [cyan]/compress[/]            — manually compress conversation context
  [cyan]/title[/] TEXT          — set a title for this chat
  [cyan]/clear[/]               — clear the terminal
  [cyan]/chats[/]               — list recent chats
  [cyan]/switch[/] ID           — switch to another chat by ID
  [cyan]/rename[/] [ID] TEXT    — rename this chat, or another chat by ID
  [cyan]/delete[/] [ID]         — delete this chat (exits) or another chat by ID
  [cyan]/quit[/]                — exit the chat (also: /exit, Ctrl-D)

[dim]Alt-Enter (Esc then Enter) inserts a new line without sending.[/]
"""

_REPL_COMMANDS = {
    "/help", "/history", "/tokens", "/compress", "/title", "/clear",
    "/chats", "/switch", "/rename", "/delete",
    "/quit", "/exit",
}

# ── Input: prompt strings & key bindings ─────────────────────────────────────

_PROMPT = "You › "
_PROMPT_CONT = " " * len(_PROMPT)   # aligns continuation lines under the first


def _make_keybindings() -> KeyBindings:
    """Enter submits; Alt/Meta+Enter inserts a newline.

    Most terminal emulators cannot distinguish Shift+Enter from plain Enter at
    the escape-sequence level.  Alt+Enter (escape + enter) is the universally
    reliable way to insert a newline without submitting.
    """
    kb = KeyBindings()

    @kb.add("enter", eager=True)
    def _submit(event) -> None:
        event.current_buffer.validate_and_handle()

    @kb.add("escape", "enter")
    def _newline(event) -> None:
        event.current_buffer.insert_text("\n")

    return kb


_KB = _make_keybindings()


def _resolve_provider(provider_name: str | None, model: str | None) -> tuple[str, str, object]:
    """Return (provider_name, model, provider_instance)."""
    pname = provider_name or config.get_default_provider()
    mname = model or config.get_default_model(pname)
    key = config.get_api_key(pname)
    if not key:
        error(
            f"No API key for provider '{pname}'.\n"
            f"Run [bold]termchat setup[/] or set [bold]{pname.upper()}_API_KEY[/] env var."
        )
        raise click.Abort()
    prov = get_provider(pname, key, mname)
    return pname, mname, prov


# ── REPL loop ─────────────────────────────────────────────────────────────────

def _run_repl(chat: Chat, provider, project=None, initial_message: str | None = None) -> int | None:
    """Interactive REPL for a chat session.

    Returns a chat ID if the user issued /switch, otherwise None.
    """
    session: PromptSession = PromptSession(
        history=InMemoryHistory(),
        key_bindings=_KB,
        multiline=True,
        prompt_continuation=lambda _w, _ln, _sw: _PROMPT_CONT,
    )

    chat_label = chat.key or f"#{chat.id}"
    console.print(Rule(f"[bold]{chat_label}[/]  [dim]{chat.model}[/]"))
    if project:
        console.print(f"[dim]Project: [bold]{project.name}[/][/]")
    console.print(
        "[dim]Type a message and press Enter. "
        "[bold]/help[/] for in-chat commands · "
        "Alt-Enter for a new line · "
        "Ctrl-D or [bold]/quit[/] to exit · "
        "[bold]tc -h[/] for all commands.[/]\n"
    )

    # Pre-seed: send the initial message before entering the loop
    _initial_message = (initial_message or "").strip() or None

    # ── AI turn helper (closure over chat, provider, project) ─────────────
    def _do_ai_turn(user_input: str) -> bool:
        """Render user message, call AI, render response.

        Returns True on success, False on API error (caller should continue).
        """
        console.print(Panel(
            user_input,
            title="[bold blue]You[/]",
            border_style="blue",
            title_align="left",
            padding=(0, 1),
        ))

        with console.status("[green]Thinking…[/]", spinner="dots"):
            try:
                user_msg, asst_msg, compressed = chat_engine.send_message(
                    chat,
                    user_input,
                    provider,
                    project=project,
                    auto_compress=True,
                )
            except Exception as exc:
                error(f"API error: {exc}")
                return False

        render_message(asst_msg)

        if compressed:
            console.print(
                "[yellow dim]⚡ Context auto-compressed (50 k char limit reached).[/]"
            )

        if chat.key is None:
            with console.status("[dim]Naming chat…[/]"):
                raw = ctx.generate_chat_key(user_input, provider)
                chat.key = database.update_chat_key(
                    chat.id, database.unique_chat_key(raw)
                )
            console.print(Rule(f"[bold]{chat.key}[/]  [dim]{chat.model}[/]"))

        return True

    if _initial_message:
        _do_ai_turn(_initial_message)

    while True:
        # ── Prompt ────────────────────────────────────────────────────────────
        try:
            user_input = session.prompt(_PROMPT).strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye.[/]")
            break

        if not user_input:
            continue

        # ── REPL commands ──────────────────────────────────────────────────────
        cmd, _, rest = user_input.partition(" ")
        cmd = cmd.lower()

        if cmd in ("/quit", "/exit"):
            console.print("[dim]Goodbye.[/]")
            break

        if cmd == "/help":
            console.print(_REPL_HELP)
            continue

        if cmd == "/clear":
            import os
            os.system("clear" if sys.platform != "win32" else "cls")
            continue

        if cmd == "/history":
            messages = database.get_messages(chat.id)
            if not messages:
                console.print("[dim](no messages yet)[/]")
            else:
                with console.pager(styles=True):
                    for msg in messages:
                        render_message(msg)
            continue

        if cmd == "/tokens":
            totals = database.chat_token_totals(chat.id)
            render_token_summary(totals)
            continue

        if cmd == "/compress":
            with console.status("Compressing context…"):
                did, n = ctx.compress_chat(chat.id, provider, force=True)
            if did:
                success(f"Compressed {n} messages into a summary.")
            else:
                warn("Nothing to compress (too few messages).")
            continue

        if cmd == "/title":
            title = rest.strip()
            if title:
                database.update_chat_title(chat.id, title)
                chat.title = title
                success(f"Title set to '{title}'.")
            else:
                warn("Usage: /title <new title>")
            continue

        if cmd == "/chats":
            chats = database.list_chats(limit=15)
            projects_map: dict[int, str] = {p.id: p.name for p in database.list_projects()}
            render_chat_list(chats, projects_map, current_id=chat.id)
            if len(chats) == 15:
                console.print("[dim]Showing 15 most recent. Use [bold]termchat chat list[/] to see all.[/]")
            continue

        if cmd == "/switch":
            arg = rest.strip()
            if not arg:
                warn("Usage: /switch <key or id>")
                continue
            target = _resolve_chat_ref(arg)
            if target is None:
                error(f"Chat '{arg}' not found.")
                _show_chat_list(current_id=chat.id)
                continue
            if target.id == chat.id:
                warn("Already in this chat.")
                continue
            label = target.key or f"#{target.id}"
            console.print(f"[dim]Switching to {label}…[/]")
            return target.id

        if cmd == "/rename":
            parts = rest.strip().split(None, 1)
            if not parts:
                warn("Usage: /rename [<key or id>] <new title>")
                continue
            # If the first token resolves to a chat AND a second token exists,
            # treat it as a chat reference; otherwise rename the current chat.
            referenced = _resolve_chat_ref(parts[0]) if len(parts) > 1 else None
            if referenced is not None:
                target_chat = referenced
                new_title = parts[1].strip()
            else:
                target_chat = chat
                new_title = rest.strip()
            if not new_title:
                warn("Usage: /rename [<key or id>] <new title>")
                continue
            database.update_chat_title(target_chat.id, new_title)
            if target_chat.id == chat.id:
                chat.title = new_title
            label = target_chat.key or f"#{target_chat.id}"
            success(f"'{label}' renamed to '{new_title}'.")
            continue

        if cmd == "/delete":
            arg = rest.strip()
            if arg:
                target_chat = _resolve_chat_ref(arg)
                if target_chat is None:
                    error(f"Chat '{arg}' not found.")
                    continue
            else:
                target_chat = chat
            label = target_chat.key or f"#{target_chat.id}"
            try:
                confirmed = click.confirm(f"  Delete '{label}'?", default=False)
            except click.Abort:
                console.print()
                continue
            if not confirmed:
                continue
            database.delete_chat(target_chat.id)
            success(f"'{label}' deleted.")
            if target_chat.id == chat.id:
                console.print("[dim]Current chat deleted. Goodbye.[/]")
                return None
            continue

        # ── Unknown slash-command guard ────────────────────────────────────────
        if user_input.startswith("/") and cmd not in _REPL_COMMANDS:
            try:
                confirmed = click.confirm(
                    f"  '{cmd}' isn't a command — send to AI?", default=False
                )
            except click.Abort:
                console.print()
                continue
            if not confirmed:
                continue

        # ── AI turn ────────────────────────────────────────────────────────────
        if not _do_ai_turn(user_input):
            continue

    return None


# ── Switch helper ─────────────────────────────────────────────────────────────

def _handle_switch(next_id: int | None) -> None:
    """Loop through /switch requests until the user exits normally."""
    while next_id is not None:
        target_chat = database.get_chat(next_id)
        if target_chat is None:
            error(f"Chat '{next_id}' not found.")
            return
        project = database.get_project(target_chat.project_id) if target_chat.project_id else None
        _, _, prov = _resolve_provider(target_chat.provider, target_chat.model)

        # Show history before entering the REPL
        messages = database.get_messages(next_id)
        if messages:
            console.print(Rule("[dim]Previous messages[/]"))
            for msg in messages:
                render_message(msg)
            console.print()

        next_id = _run_repl(target_chat, prov, project=project)


# ── Launcher ──────────────────────────────────────────────────────────────────

def _run_launcher(pname: str, mname: str, prov) -> None:
    """Show the full-screen chat/project picker and loop until the user quits."""
    from termchat.tui.launcher import Launcher

    while True:
        chats = database.list_chats(limit=50)
        projects = database.list_projects()

        action, item = Launcher(chats, projects).run()

        if action == "quit":
            break

        elif action == "new_chat":
            chat = database.create_chat(mname, pname)
            _handle_switch(_run_repl(chat, prov))
            # After REPL exits, loop back to launcher

        elif action == "open_chat":
            chat = item
            _, _, chat_prov = _resolve_provider(chat.provider, chat.model)
            project = database.get_project(chat.project_id) if chat.project_id else None
            messages = database.get_messages(chat.id)
            if messages:
                console.print(Rule("[dim]Previous messages[/]"))
                for msg in messages:
                    render_message(msg)
                console.print()
            _handle_switch(_run_repl(chat, chat_prov, project=project))

        elif action == "open_project":
            project = item
            chat = database.create_chat(mname, pname, project.id)
            _handle_switch(_run_repl(chat, prov, project=project))

        # delete_chat is handled entirely inside the launcher (no terminal drop-out)


# ── Commands ──────────────────────────────────────────────────────────────────


@click.group("chat")
def chat_group() -> None:
    """Start and manage chat conversations."""


@chat_group.command("new")
@click.option("--project", "-p", "project_name", default=None,
              help="Associate with a project by name or id.")
@click.option("--model", "-m", default=None, help="Model override.")
@click.option("--provider", default=None, type=str, help="Provider override.")
@click.option("--title", "-t", default=None, help="Set a title immediately.")
@click.option("--initial-message", "initial_message", default=None, hidden=True,
              help="Pre-seed the chat with this message (used programmatically).")
def chat_new(project_name: str | None, model: str | None, provider: str | None, title: str | None, initial_message: str | None = None) -> None:
    """Start a new chat (opens an interactive session)."""
    pname, mname, prov = _resolve_provider(provider, model)

    # Resolve project
    project = None
    project_id = None
    if project_name:
        # Try by id first, then by name
        try:
            project = database.get_project(int(project_name))
        except ValueError:
            project = database.get_project_by_name(project_name)
        if project is None:
            error(f"Project '{project_name}' not found.")
            from termchat.cli.formatting import render_project_list
            projects = database.list_projects()
            for p in projects:
                p.files = database.get_project_files(p.id)
            render_project_list(projects)
            raise click.Abort()
        project_id = project.id

    if initial_message:
        # Non-interactive path (termchat ask "...") — skip launcher
        chat = database.create_chat(mname, pname, project_id, title)
        _handle_switch(_run_repl(chat, prov, project=project, initial_message=initial_message))
        return

    # Interactive path — show the launcher first
    _run_launcher(pname, mname, prov)


@chat_group.command("resume")
@click.argument("chat_ref")
@click.option("--model", "-m", default=None, help="Model override.")
def chat_resume(chat_ref: str, model: str | None) -> None:
    """Resume an existing chat by key or numeric ID."""
    chat = _resolve_chat_ref(chat_ref)
    if chat is None:
        error(f"Chat '{chat_ref}' not found.")
        _show_chat_list()
        raise click.Abort()

    model = model or chat.model
    _, _, prov = _resolve_provider(chat.provider, model)

    project = database.get_project(chat.project_id) if chat.project_id else None

    # Show existing history first
    messages = database.get_messages(chat.id)
    if messages:
        console.print(Rule("[dim]Previous messages[/]"))
        for msg in messages:
            render_message(msg)
        console.print()

    _handle_switch(_run_repl(chat, prov, project=project))


@chat_group.command("list")
@click.option("--project", "-p", "project_id", type=int, default=None,
              help="Filter by project id.")
@click.option("--limit", default=25, show_default=True, help="Maximum rows to show.")
def chat_list(project_id: int | None, limit: int) -> None:
    """List recent chats."""
    chats = database.list_chats(project_id=project_id, limit=limit)
    projects_map: dict[int, str] = {}
    for p in database.list_projects():
        projects_map[p.id] = p.name
    render_chat_list(chats, projects_map)


@chat_group.command("show")
@click.argument("chat_id", type=int)
@click.option("--no-markdown", is_flag=True, help="Disable Markdown rendering.")
def chat_show(chat_id: int, no_markdown: bool) -> None:
    """Print full history for CHAT_ID."""
    chat, messages = chat_engine.get_chat_with_messages(chat_id)
    if chat is None:
        error(f"Chat {chat_id} not found.")
        _show_chat_list()
        raise click.Abort()

    proj_name = "—"
    if chat.project_id:
        p = database.get_project(chat.project_id)
        proj_name = p.name if p else "—"

    chat_label = chat.key or f"#{chat.id}"
    with console.pager(styles=True):
        console.print(Panel(
            f"[bold]{chat.title or '(untitled)'}[/]\n"
            f"[dim]Model: {chat.model}  •  Project: {proj_name}  •  "
            f"Created: {_format_dt(chat.created_at)}[/]",
            title=chat_label,
            border_style="blue",
        ))

        if not messages:
            console.print("[dim](no messages)[/]")
        else:
            for msg in messages:
                render_message(msg, markdown=not no_markdown)

            totals = database.chat_token_totals(chat_id)
            console.print()
            render_token_summary(totals)


@chat_group.command("tokens")
@click.argument("chat_id", type=int)
def chat_tokens(chat_id: int) -> None:
    """Show token usage breakdown for CHAT_ID."""
    chat = database.get_chat(chat_id)
    if chat is None:
        error(f"Chat {chat_id} not found.")
        _show_chat_list()
        raise click.Abort()

    messages = database.get_messages(chat_id)
    if not messages:
        console.print("[dim]No messages.[/]")
        return

    from rich.table import Table
    from rich import box as rbox

    table = Table("#", "Role", "Preview", "Input ↑", "Output ↓", "Total",
                  box=rbox.SIMPLE, header_style="bold")
    for m in messages:
        preview = (m.content[:50] + "…") if len(m.content) > 50 else m.content
        preview = preview.replace("\n", " ")
        table.add_row(
            str(m.id),
            m.role,
            preview,
            str(m.input_tokens or "—"),
            str(m.output_tokens or "—"),
            str(m.total_tokens or "—"),
        )
    console.print(table)

    totals = database.chat_token_totals(chat_id)
    render_token_summary(totals)


@chat_group.command("compress")
@click.argument("chat_id", type=int)
@click.option("--keep", default=None, type=int,
              help=f"Number of recent messages to preserve (default: {config.CONTEXT_KEEP_RECENT}).")
def chat_compress(chat_id: int, keep: int | None) -> None:
    """Manually compress the context of CHAT_ID."""
    chat = database.get_chat(chat_id)
    if chat is None:
        error(f"Chat {chat_id} not found.")
        _show_chat_list()
        raise click.Abort()

    _, _, prov = _resolve_provider(chat.provider, chat.model)

    with console.status("Summarising old messages…"):
        did, n = ctx.compress_chat(chat_id, prov, keep_recent=keep, force=True)

    if did:
        success(f"Compressed {n} messages into a summary.")
        totals = database.chat_token_totals(chat_id)
        render_token_summary(totals)
    else:
        warn("Nothing to compress (too few messages).")


@chat_group.command("delete")
@click.argument("chat_id", type=int)
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def chat_delete(chat_id: int, yes: bool) -> None:
    """Delete CHAT_ID and all its messages."""
    chat = database.get_chat(chat_id)
    if chat is None:
        error(f"Chat {chat_id} not found.")
        _show_chat_list()
        raise click.Abort()

    if not yes:
        click.confirm(
            f"Delete chat #{chat.id} '{chat.title or '(untitled)'}' and all its messages?",
            abort=True,
        )

    database.delete_chat(chat_id)
    success(f"Chat #{chat_id} deleted.")
