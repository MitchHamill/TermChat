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
    """Accept a numeric ID and return the Chat."""
    try:
        return database.get_chat(int(ref))
    except ValueError:
        return None


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
  [cyan]/switch[/] ID           — switch to another chat by numeric ID
  [cyan]/rename[/] [ID] TEXT    — rename this chat, or another chat by numeric ID
  [cyan]/delete[/] [ID]         — delete this chat (exits) or another chat by numeric ID
  [cyan]/menu[/]                — return to the chat selection screen (also: Tab)
  [cyan]/quit[/]                — quit termchat (also: /exit, Ctrl-C, Ctrl-D)

[dim]Alt-Enter (Esc then Enter) inserts a new line without sending.[/]
"""

_REPL_COMMANDS = {
    "/help", "/history", "/tokens", "/compress", "/title", "/clear",
    "/chats", "/switch", "/rename", "/delete",
    "/menu", "/quit", "/exit",
}

_TOOLBAR = (
    " [Tab] launcher   [/help] commands   [Ctrl-C] quit   [Alt-Enter] newline "
)

# ── Input: prompt strings & key bindings ─────────────────────────────────────

_PROMPT = "You › "
_PROMPT_CONT = " " * len(_PROMPT)   # aligns continuation lines under the first


class _MenuRequest(Exception):
    """Raised by the Tab key binding to signal a return to the launcher."""


def _make_keybindings() -> KeyBindings:
    """Enter submits; Alt/Meta+Enter inserts a newline; Tab returns to launcher."""
    kb = KeyBindings()

    @kb.add("enter", eager=True)
    def _submit(event) -> None:
        event.current_buffer.validate_and_handle()

    @kb.add("escape", "enter")
    def _newline(event) -> None:
        event.current_buffer.insert_text("\n")

    @kb.add("tab")
    def _go_to_menu(event) -> None:
        event.app.exit(exception=_MenuRequest())

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

def _run_repl(chat: Chat, provider, project=None, initial_message: str | None = None) -> int | str | None:
    """Interactive REPL for a chat session.

    Returns:
      int   — chat ID to switch to (/switch command)
      "menu" — user wants to return to the launcher
      None  — session ended (caller should exit or return to launcher)
    """
    session: PromptSession = PromptSession(
        history=InMemoryHistory(),
        key_bindings=_KB,
        multiline=True,
        prompt_continuation=lambda _w, _ln, _sw: _PROMPT_CONT,
        bottom_toolbar=_TOOLBAR,
    )

    _initial_message = (initial_message or "").strip() or None

    _HINT = "[dim]Type a message and press Enter · [bold]/help[/] for commands · [bold]Tab[/] to go back[/]"

    def _print_header() -> None:
        label = chat.title or f"#{chat.id}"
        console.print(Rule(f"[bold]{label}[/]  [dim]{chat.model}[/]"))
        if project:
            console.print(f"[dim]Project: [bold]{project.name}[/][/]")
        console.print(_HINT + "\n")

    def _erase_prompt(text: str) -> None:
        """Remove the prompt_toolkit echo from the terminal before re-rendering."""
        import math
        import shutil
        cols = shutil.get_terminal_size().columns or 80
        rows = 0
        for i, part in enumerate(text.split("\n")):
            prefix = len(_PROMPT) if i == 0 else len(_PROMPT_CONT)
            rows += max(1, math.ceil((prefix + len(part)) / cols))
        sys.stdout.write(f"\033[{rows}A\033[J")
        sys.stdout.flush()

    # ── AI turn helper (closure over chat, provider, project) ─────────────
    def _do_ai_turn(user_input: str) -> bool:
        """Render user message, call AI, render response.

        Returns True on success, False on API error (caller should continue).
        """
        console.print(Rule("[bold blue]You[/]", align="left", style="blue dim"))
        console.print(user_input)
        console.print()

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

        return True

    # ── New chat: collect first message, name it, then show a clean header ────
    if not chat.title:
        if _initial_message is not None:
            first_input = _initial_message
            _initial_message = None
        else:
            console.print(_HINT + "\n")
            first_input = None
            while first_input is None:
                try:
                    raw = session.prompt(_PROMPT).strip()
                except _MenuRequest:
                    return "menu"
                except KeyboardInterrupt:
                    console.print()
                    try:
                        confirmed = click.confirm("  Quit termchat?", default=False)
                    except click.Abort:
                        confirmed = False
                    if confirmed:
                        console.print("[dim]Goodbye.[/]")
                        sys.exit(0)
                    continue
                except EOFError:
                    console.print("\n[dim]Goodbye.[/]")
                    sys.exit(0)
                if not raw:
                    continue
                _erase_prompt(raw)
                if raw.lower() in ("/quit", "/exit"):
                    console.print("[dim]Goodbye.[/]")
                    sys.exit(0)
                if raw.lower() == "/menu":
                    return "menu"
                first_input = raw

        with console.status("[dim]Starting chat…[/]"):
            title = ctx.generate_chat_title(first_input, provider, project=project)
            database.update_chat_title(chat.id, title)
            chat.title = title

        console.clear()
        _print_header()
        _do_ai_turn(first_input)

    else:
        # Resumed chat — header goes at the very top
        _print_header()
        if _initial_message:
            _do_ai_turn(_initial_message)

    while True:
        # ── Prompt ────────────────────────────────────────────────────────────
        try:
            user_input = session.prompt(_PROMPT).strip()
        except _MenuRequest:
            return "menu"
        except KeyboardInterrupt:
            console.print()
            try:
                confirmed = click.confirm("  Quit termchat?", default=False)
            except click.Abort:
                confirmed = False
            if confirmed:
                console.print("[dim]Goodbye.[/]")
                sys.exit(0)
            continue
        except EOFError:
            console.print("\n[dim]Goodbye.[/]")
            sys.exit(0)

        if not user_input:
            continue

        _erase_prompt(user_input)

        # ── REPL commands ──────────────────────────────────────────────────────
        cmd, _, rest = user_input.partition(" ")
        cmd = cmd.lower()

        if cmd in ("/quit", "/exit"):
            console.print("[dim]Goodbye.[/]")
            sys.exit(0)

        if cmd == "/menu":
            return "menu"

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
                warn("Usage: /switch <id>")
                continue
            target = _resolve_chat_ref(arg)
            if target is None:
                error(f"Chat '{arg}' not found.")
                _show_chat_list(current_id=chat.id)
                continue
            if target.id == chat.id:
                warn("Already in this chat.")
                continue
            label = target.title or f"#{target.id}"
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
            label = target_chat.title or f"#{target_chat.id}"
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
            label = target_chat.title or f"#{target_chat.id}"
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
                return "menu"
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

def _handle_switch(next_id) -> str | None:
    """Loop through /switch requests until the user exits or goes to menu.

    Returns "menu" if the user issued /menu, None otherwise.
    """
    while isinstance(next_id, int):
        target_chat = database.get_chat(next_id)
        if target_chat is None:
            error(f"Chat '{next_id}' not found.")
            return None
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

    return next_id  # "menu" or None


# ── Launcher ──────────────────────────────────────────────────────────────────

def _run_launcher(pname: str, mname: str, prov) -> None:
    """Show the full-screen chat/project picker and loop until the user quits."""
    from termchat.cli.launcher import Launcher

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

        elif action == "new_project":
            from termchat.cli.project_wizard import ProjectWizard
            project = ProjectWizard().run()
            if project:
                chat = database.create_chat(mname, pname, project.id)
                _handle_switch(_run_repl(chat, prov, project=project))
            # project is None → wizard was cancelled; outer while loop re-shows launcher

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

        elif action == "edit_project":
            from termchat.cli.project_editor import ProjectEditor
            ProjectEditor(item).run()
            # DB updated inside editor; outer loop re-shows launcher with fresh data

        elif action == "open_project":
            project = database.get_project(item.id)  # fetch with files populated
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
    """Resume an existing chat by numeric ID."""
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

    with console.pager(styles=True):
        console.print(Panel(
            f"[bold]{chat.title or '(untitled)'}[/]\n"
            f"[dim]Model: {chat.model}  •  Project: {proj_name}  •  "
            f"Created: {_format_dt(chat.created_at)}[/]",
            title=f"#{chat.id}",
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
