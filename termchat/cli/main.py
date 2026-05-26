"""termchat — main CLI entry point."""

from __future__ import annotations

import click

from termchat import config as cfg
from termchat.storage import database


def _init_db() -> None:
    cfg.ensure_config_dir()
    database.init(cfg.DB_FILE)


# ── Root group ────────────────────────────────────────────────────────────────


@click.group()
@click.version_option(package_name="termchat")
def cli() -> None:
    """termchat — manage AI chat conversations from your terminal.

    \b
    Quick start:
      termchat setup              Configure your API key
      termchat chat new           Start a new conversation
      termchat chat list          List previous chats
      termchat project new NAME   Create a project with custom instructions
    """
    _init_db()


# ── Sub-groups / commands ──────────────────────────────────────────────────────

from termchat.cli.chat_commands import chat_group          # noqa: E402
from termchat.cli.project_commands import project_group    # noqa: E402
from termchat.cli.config_commands import config_group, setup_cmd  # noqa: E402

cli.add_command(chat_group)
cli.add_command(project_group)
cli.add_command(config_group)
cli.add_command(setup_cmd)  # also available as top-level `termchat setup`


# ── Convenience aliases ───────────────────────────────────────────────────────

@cli.command("new")
@click.option("--project", "-p", "project_name", default=None,
              help="Associate with a project.")
@click.option("--model", "-m", default=None)
@click.option("--provider", default=None)
@click.pass_context
def new_alias(ctx: click.Context, project_name: str | None, model: str | None, provider: str | None) -> None:
    """Alias for [bold]termchat chat new[/]."""
    from termchat.cli.chat_commands import chat_new
    ctx.invoke(chat_new, project_name=project_name, model=model, provider=provider)


if __name__ == "__main__":
    cli()
