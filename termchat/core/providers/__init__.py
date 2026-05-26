"""Provider implementations and registry."""

from __future__ import annotations

from termchat.core.providers.base import BaseProvider, CompletionResult
from termchat.core.providers.anthropic_provider import AnthropicProvider

_REGISTRY: dict[str, type[BaseProvider]] = {
    "anthropic": AnthropicProvider,
}


def get_provider(name: str, api_key: str, model: str) -> BaseProvider:
    """Return an initialised provider instance by name."""
    cls = _REGISTRY.get(name)
    if cls is None:
        supported = ", ".join(_REGISTRY)
        raise ValueError(f"Unknown provider '{name}'. Supported: {supported}")
    return cls(api_key=api_key, model=model)


def list_providers() -> list[str]:
    return list(_REGISTRY)


__all__ = ["BaseProvider", "CompletionResult", "AnthropicProvider", "get_provider", "list_providers"]
