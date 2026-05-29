"""Shared fixtures and helpers for the termchat test suite."""

from __future__ import annotations

from typing import Generator

import pytest

from termchat.core.providers.base import BaseProvider, CompletionResult
from termchat.storage import database


# ── Mock provider ─────────────────────────────────────────────────────────────

class MockProvider(BaseProvider):
    """Deterministic provider for tests — no network calls."""

    def __init__(self, response: str = "Mock response.", input_tokens: int = 10, output_tokens: int = 5):
        super().__init__(api_key="test-key", model="test-model")
        self.response = response
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self.complete_calls: list[tuple] = []
        self.stream_calls: list[tuple] = []

    def complete(self, messages, *, system="", max_tokens=8096) -> CompletionResult:
        self.complete_calls.append((messages, system))
        return CompletionResult(
            content=self.response,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            model=self.model,
        )

    def stream(self, messages, *, system="", max_tokens=8096) -> Generator[str, None, CompletionResult]:
        self.stream_calls.append((messages, system))
        for word in self.response.split():
            yield word + " "
        return CompletionResult(
            content=self.response,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            model=self.model,
        )


# ── Database fixture ──────────────────────────────────────────────────────────

@pytest.fixture()
def db(tmp_path):
    """Initialise a fresh in-memory-like SQLite DB for each test."""
    db_file = tmp_path / "test.db"
    database.init(db_file)
    yield db_file
    database._db_path = None


@pytest.fixture()
def mock_provider() -> MockProvider:
    return MockProvider()
