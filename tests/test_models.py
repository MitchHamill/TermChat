"""Tests for storage/models.py dataclass properties."""

from __future__ import annotations

from datetime import datetime

import pytest

from termchat.storage.models import Chat, Message, Project, ProjectFile


NOW = datetime(2024, 1, 1, 12, 0, 0)


def _msg(content: str, role: str = "user", input_tokens=None, output_tokens=None) -> Message:
    return Message(
        id=1, chat_id=1, role=role, content=content,
        input_tokens=input_tokens, output_tokens=output_tokens, created_at=NOW,
    )


class TestMessageProperties:
    def test_char_count_matches_content_length(self):
        msg = _msg("hello world")
        assert msg.char_count == 11

    def test_char_count_empty_content(self):
        assert _msg("").char_count == 0

    def test_char_count_unicode(self):
        content = "héllo wörld"
        assert _msg(content).char_count == len(content)

    def test_total_tokens_both_present(self):
        msg = _msg("x", input_tokens=100, output_tokens=50)
        assert msg.total_tokens == 150

    def test_total_tokens_none_input(self):
        msg = _msg("x", input_tokens=None, output_tokens=20)
        assert msg.total_tokens == 20

    def test_total_tokens_none_output(self):
        msg = _msg("x", input_tokens=30, output_tokens=None)
        assert msg.total_tokens == 30

    def test_total_tokens_both_none(self):
        msg = _msg("x", input_tokens=None, output_tokens=None)
        assert msg.total_tokens == 0

    def test_total_tokens_zeros(self):
        msg = _msg("x", input_tokens=0, output_tokens=0)
        assert msg.total_tokens == 0


class TestProjectDefaults:
    def test_files_default_empty_list(self):
        proj = Project(id=1, name="p", instructions="", created_at=NOW, updated_at=NOW)
        assert proj.files == []

    def test_files_not_shared_between_instances(self):
        p1 = Project(id=1, name="p1", instructions="", created_at=NOW, updated_at=NOW)
        p2 = Project(id=2, name="p2", instructions="", created_at=NOW, updated_at=NOW)
        p1.files.append(
            ProjectFile(id=1, project_id=1, filename="f", content="c", created_at=NOW)
        )
        assert p2.files == []
