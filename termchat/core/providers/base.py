"""Abstract base class for AI providers.

Adding a new provider:
  1. Subclass BaseProvider
  2. Implement complete() and stream()
  3. Register in providers/__init__.py under a short name
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generator


@dataclass
class CompletionResult:
    content: str
    input_tokens: int
    output_tokens: int
    model: str


class BaseProvider(ABC):
    """Minimal interface every provider must implement."""

    def __init__(self, *, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    # ------------------------------------------------------------------
    # Required
    # ------------------------------------------------------------------

    @abstractmethod
    def complete(
        self,
        messages: list[dict],
        *,
        system: str = "",
        max_tokens: int = 8096,
    ) -> CompletionResult:
        """Return a full completion (non-streaming)."""

    @abstractmethod
    def stream(
        self,
        messages: list[dict],
        *,
        system: str = "",
        max_tokens: int = 8096,
    ) -> Generator[str, None, CompletionResult]:
        """Yield text chunks; the generator *return value* is a CompletionResult.

        Usage:
            gen = provider.stream(messages)
            try:
                while True:
                    chunk = next(gen)
                    print(chunk, end="", flush=True)
            except StopIteration as e:
                result: CompletionResult = e.value
        """

    # ------------------------------------------------------------------
    # Optional helpers (override if the provider supports them)
    # ------------------------------------------------------------------

    def validate_key(self) -> bool:
        """Return True if the API key appears valid (may make a cheap API call)."""
        return True

    @property
    def provider_name(self) -> str:
        return type(self).__name__.lower().replace("provider", "")
