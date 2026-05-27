"""termchat — main CLI entry point."""

from __future__ import annotations

import typing as t

import click

from termchat import config as cfg
from termchat.storage import database


def _init_db() -> None:
    cfg.ensure_config_dir()
    database.init(cfg.DB_FILE)


# ── Root group ────────────────────────────────────────────────────────────────


class _CatchAllGroup(click.Group):
    """click.Group that treats an unrecognised first positional arg as free-form
    extra args rather than raising 'No such command'."""

    def invoke(self, ctx: click.Context) -> t.Any:
        # Click 8.4+ made ctx.protected_args a read-only property; use the
        # private backing attribute (_protected_args) for both read and write.
        combined = ctx._protected_args + ctx.args
        if combined and self.get_command(ctx, combined[0]) is None:
            # Not a known subcommand — stash in meta, clear so no dispatch error
            ctx.meta["termchat.initial_args"] = combined
            ctx._protected_args = []
            ctx.args = []
        return super().invoke(ctx)


@click.group(cls=_CatchAllGroup, invoke_without_command=True)
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
        extra = ctx.meta.get("termchat.initial_args", [])
        initial_message = " ".join(extra).strip() or None
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


@cli.command("ask")
@click.argument("message")
@click.option("--project", "-p", "project_name", default=None,
              help="Associate with a project by name or id.")
@click.option("--model", "-m", default=None, help="Model override.")
@click.option("--provider", default=None, help="Provider override.")
@click.option("--title", "-t", default=None, help="Set a title immediately.")
@click.pass_context
def ask_cmd(ctx: click.Context, message: str, project_name: str | None,
            model: str | None, provider: str | None, title: str | None) -> None:
    """Start a new chat with MESSAGE as the opening prompt."""
    from termchat.cli.chat_commands import chat_new
    ctx.invoke(chat_new, project_name=project_name, model=model,
               provider=provider, title=title, initial_message=message)


if __name__ == "__main__":
    cli()
