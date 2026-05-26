"""Project management commands."""

from __future__ import annotations

from pathlib import Path

import click
from rich.panel import Panel
from rich.table import Table
from rich import box

from termchat.cli.formatting import (
    console,
    error,
    render_project_list,
    success,
    warn,
    _format_dt,
)
from termchat.storage import database


@click.group("project")
def project_group() -> None:
    """Create and manage projects (custom instructions + file attachments)."""


def _show_project_list() -> None:
    """Print the project list — used after a failed lookup."""
    projects = database.list_projects()
    for p in projects:
        p.files = database.get_project_files(p.id)
    render_project_list(projects)


# ── new ───────────────────────────────────────────────────────────────────────


@project_group.command("new")
@click.argument("name")
@click.option("--instructions", "-i", default="", help="System instructions for every chat in this project.")
@click.option("--instructions-file", "-f", type=click.Path(exists=True), default=None,
              help="Read instructions from a file instead.")
def project_new(name: str, instructions: str, instructions_file: str | None) -> None:
    """Create a new project called NAME."""
    if instructions_file:
        instructions = Path(instructions_file).read_text()

    if not instructions:
        # Drop into $EDITOR if no instructions provided
        instructions = click.edit("") or ""

    try:
        proj = database.create_project(name, instructions)
    except Exception as exc:
        if "UNIQUE" in str(exc):
            error(f"A project named '{name}' already exists.")
        else:
            error(str(exc))
        raise click.Abort()

    success(f"Project '{name}' created (id={proj.id}).")
    if proj.instructions:
        console.print(Panel(proj.instructions[:200] + ("…" if len(proj.instructions) > 200 else ""),
                            title="Instructions preview", border_style="dim"))


# ── list ──────────────────────────────────────────────────────────────────────


@project_group.command("list")
def project_list() -> None:
    """List all projects."""
    projects = database.list_projects()
    for p in projects:
        p.files = database.get_project_files(p.id)
    render_project_list(projects)


# ── show ──────────────────────────────────────────────────────────────────────


@project_group.command("show")
@click.argument("project_id", type=int)
def project_show(project_id: int) -> None:
    """Show details and files for PROJECT_ID."""
    proj = database.get_project(project_id)
    if proj is None:
        error(f"Project {project_id} not found.")
        _show_project_list()
        raise click.Abort()

    console.print(Panel(
        f"[bold]{proj.name}[/]\n"
        f"[dim]Created {_format_dt(proj.created_at)}  •  Updated {_format_dt(proj.updated_at)}[/]",
        title=f"Project #{proj.id}",
        border_style="blue",
    ))

    if proj.instructions:
        console.print(Panel(proj.instructions, title="Instructions", border_style="dim"))
    else:
        console.print("[dim](no instructions)[/]")

    if proj.files:
        table = Table("Filename", "Size", "Added", box=box.SIMPLE)
        for f in proj.files:
            table.add_row(f.filename, f"{len(f.content):,} chars", _format_dt(f.created_at))
        console.print(table)
    else:
        console.print("[dim](no attached files)[/]")


# ── edit ──────────────────────────────────────────────────────────────────────


@project_group.command("edit")
@click.argument("project_id", type=int)
@click.option("--name", default=None)
@click.option("--instructions", default=None)
@click.option("--instructions-file", type=click.Path(exists=True), default=None)
def project_edit(project_id: int, name: str | None, instructions: str | None, instructions_file: str | None) -> None:
    """Edit a project's name or instructions."""
    proj = database.get_project(project_id)
    if proj is None:
        error(f"Project {project_id} not found.")
        _show_project_list()
        raise click.Abort()

    if instructions_file:
        instructions = Path(instructions_file).read_text()

    if instructions is None and name is None:
        # Interactive: open current instructions in $EDITOR
        instructions = click.edit(proj.instructions) or proj.instructions

    updated = database.update_project(project_id, name=name, instructions=instructions)
    if updated:
        success(f"Project '{updated.name}' updated.")
    else:
        error("Update failed.")


# ── add-instructions ─────────────────────────────────────────────────────────


@project_group.command("add-instructions")
@click.argument("project_id", type=int)
@click.argument("file_path", type=click.Path(exists=True), required=False, default=None)
@click.option("--append", "-a", is_flag=True,
              help="Append to existing instructions instead of replacing them.")
def project_add_instructions(project_id: int, file_path: str | None, append: bool) -> None:
    """Set the system instructions for PROJECT_ID from a .txt file.

    If FILE_PATH is omitted, opens $EDITOR so you can write instructions
    interactively.  The instructions are prepended to every chat system prompt
    for this project.

    Use --append to add to the existing instructions rather than replacing them.
    """
    proj = database.get_project(project_id)
    if proj is None:
        error(f"Project {project_id} not found.")
        _show_project_list()
        raise click.Abort()

    if file_path:
        new_text = Path(file_path).read_text(errors="replace").strip()
        if not new_text:
            warn(f"'{file_path}' is empty — nothing changed.")
            return
        source_label = f"'{Path(file_path).name}'"
    else:
        # Open editor pre-populated with existing instructions when appending
        initial = (proj.instructions + "\n") if append and proj.instructions else ""
        edited = click.edit(initial)
        if edited is None:
            warn("Editor closed without saving — nothing changed.")
            return
        new_text = edited.strip()
        if not new_text:
            warn("No instructions entered — nothing changed.")
            return
        source_label = "editor"

    if append and proj.instructions:
        combined = proj.instructions.rstrip() + "\n\n" + new_text
        action = "appended to"
    else:
        combined = new_text
        action = "set for"

    database.update_project(project_id, instructions=combined)
    success(f"Instructions {action} project '{proj.name}' ({len(combined):,} chars, from {source_label}).")
    preview = combined[:300] + ("…" if len(combined) > 300 else "")
    console.print(Panel(preview, title="Instructions preview", border_style="dim"))


# ── add-file ──────────────────────────────────────────────────────────────────


@project_group.command("add-file")
@click.argument("project_id", type=int)
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--name", default=None, help="Override the stored filename.")
def project_add_file(project_id: int, file_path: str, name: str | None) -> None:
    """Attach a file to a project (included in every chat system prompt)."""
    proj = database.get_project(project_id)
    if proj is None:
        error(f"Project {project_id} not found.")
        _show_project_list()
        raise click.Abort()

    path = Path(file_path)
    filename = name or path.name
    content = path.read_text(errors="replace")

    pf = database.add_project_file(project_id, filename, content)
    success(f"File '{filename}' ({len(content):,} chars) attached to project '{proj.name}'.")


# ── remove-file ───────────────────────────────────────────────────────────────


@project_group.command("remove-file")
@click.argument("project_id", type=int)
@click.argument("filename")
def project_remove_file(project_id: int, filename: str) -> None:
    """Remove an attached file from a project."""
    removed = database.remove_project_file(project_id, filename)
    if removed:
        success(f"File '{filename}' removed.")
    else:
        error(f"File '{filename}' not found in project {project_id}.")


# ── delete ────────────────────────────────────────────────────────────────────


@project_group.command("delete")
@click.argument("project_id", type=int)
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
def project_delete(project_id: int, yes: bool) -> None:
    """Permanently delete a project (chats are detached, not deleted)."""
    proj = database.get_project(project_id)
    if proj is None:
        error(f"Project {project_id} not found.")
        _show_project_list()
        raise click.Abort()

    if not yes:
        click.confirm(f"Delete project '{proj.name}' (id={proj.id})?", abort=True)

    database.delete_project(project_id)
    success(f"Project '{proj.name}' deleted.")
