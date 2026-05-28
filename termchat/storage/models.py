"""Dataclass models that mirror the SQLite schema."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Project:
    id: int
    name: str
    instructions: str
    created_at: datetime
    updated_at: datetime
    files: list[ProjectFile] = field(default_factory=list)


@dataclass
class ProjectFile:
    id: int
    project_id: int
    filename: str
    content: str
    created_at: datetime


@dataclass
class Chat:
    id: int
    title: str | None
    provider: str
    model: str
    project_id: int | None
    created_at: datetime
    updated_at: datetime


@dataclass
class Message:
    id: int
    chat_id: int
    role: str          # "user" | "assistant" | "summary"
    content: str
    input_tokens: int | None
    output_tokens: int | None
    created_at: datetime

    @property
    def total_tokens(self) -> int:
        return (self.input_tokens or 0) + (self.output_tokens or 0)

    @property
    def char_count(self) -> int:
        return len(self.content)
