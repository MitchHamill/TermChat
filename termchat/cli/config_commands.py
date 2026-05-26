"""termchat setup / config commands."""

from __future__ import annotations

import json

import click
from rich.console import Console

from termchat import config
from termchat.cli.formatting import console, error, success, warn
from termchat.core.providers import list_providers

# ── Group ─────────────────────────────────────────────────────────────────────


@click.group("config")
def config_group() -> None:
    """View and update termchat configuration."""


# ── setup ────────────────────────────────────────────────────────────────────


@click.command("setup")
@click.option("--provider", default="anthropic", show_default=True,
              type=click.Choice(list_providers()), help="Provider to configure.")
@click.option("--key", default=None, help="API key (prompted if omitted).")
@click.option("--model", default=None, help="Default model for this provider.")
@click.option("--validate/--no-validate", default=True, show_default=True,
              help="Validate the key with a test API call.")
def setup_cmd(provider: str, key: str | None, model: str | None, validate: bool) -> None:
    """Interactive setup — configure your API key and default model."""
    console.rule("[bold]termchat setup[/]")

    # ── API key ──────────────────────────────────────────────────────────────
    existing = config.get_api_key(provider)
    if key is None:
        prompt_text = f"{provider} API key"
        if existing:
            masked = existing[:8] + "…" + existing[-4:]
            prompt_text += f" (current: {masked}, press Enter to keep)"
        key = click.prompt(prompt_text, default=existing or "", hide_input=True, show_default=False)

    if not key:
        error("No API key provided.")
        raise click.Abort()

    config.set_api_key(provider, key)
    success(f"API key saved for provider '{provider}'.")

    # ── Model ────────────────────────────────────────────────────────────────
    current_model = config.get_default_model(provider)
    if model is None:
        model = click.prompt(
            f"Default model for {provider}",
            default=current_model,
        )
    config.set_default_model(provider, model)
    success(f"Default model set to '{model}'.")

    # ── Validate ─────────────────────────────────────────────────────────────
    if validate:
        from termchat.core.providers import get_provider
        console.print("Validating API key…", end=" ")
        try:
            prov = get_provider(provider, key, model)
            ok = prov.validate_key()
            if ok:
                console.print("[bold green]OK[/]")
            else:
                console.print("[bold red]FAILED[/]")
                warn("Key saved but validation failed — check that it is correct.")
        except Exception as exc:
            console.print(f"[bold red]ERROR[/] ({exc})")
            warn("Key saved but could not validate.")

    console.print()
    console.print("[dim]Run [bold]termchat chat new[/] to start a conversation.[/]")


# ── show ──────────────────────────────────────────────────────────────────────


@config_group.command("show")
def config_show() -> None:
    """Print current configuration (API keys are redacted)."""
    settings = config.all_settings()
    console.print_json(json.dumps(settings, indent=2))


# ── set-model ─────────────────────────────────────────────────────────────────


@config_group.command("set-model")
@click.argument("model")
@click.option("--provider", default=None, help="Provider (default: current default provider).")
def config_set_model(model: str, provider: str | None) -> None:
    """Set the default model for a provider."""
    if provider is None:
        provider = config.get_default_provider()
    config.set_default_model(provider, model)
    success(f"Default model for '{provider}' set to '{model}'.")
