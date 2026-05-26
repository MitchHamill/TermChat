"""termchat — main CLI entry point."""

from __future__ import annotations

import click

from termchat import config as cfg
from termchat.storage import database


def _init_db() -> None:
    cfg.ensure_config_dir()
    database.init(cfg.DB_FILE)


# ── Root group ────────────────────────────────────────────────────────────────


@click.group(invoke_without_command=True, context_settings={"allow_extra_args": True})
@click.option("--project", "-p", "project_name", default=None,
              help="Associate new chat with a project.")
@click.option("--model", "-m", default=None, help="Model override.")
@click.option("--provider", default=None, help="Provider override.")
@click.version_option(package_name="termchat")
@click.pass_context
def cli(ctx: click.Context, project_name: str | None, model: str | None, provider: str | None) -> None:
    """termchat — AI chat in your terminal.

    \b
    Starts a new chat by default. Ctrl-D or /quit to exit.
    Run [tc -h] or [termchat -h] to see all commands.

    \b
    Quick start:
      termchat setup              Configure your API key
      termchat chat list          List previous chats
      termchat project new NAME   Create a project with custom instructions
    """
    _init_db()
    if ctx.invoked_subcommand is None:
        from termchat.cli.chat_commands import chat_new
        initial_message = " ".join(ctx.args).strip() or None
        ctx.invoke(chat_new, project_name=project_name, model=model,
                   provider=provider, initial_message=initial_message)


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
