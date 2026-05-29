"""Tests for core/context.py — system prompt building, message formatting, compression."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from termchat.core import context
from termchat.core.providers.base import CompletionResult
from termchat.storage import database
from termchat.storage.models import Message, MessageAttachment, Project, ProjectFile

from tests.conftest import MockProvider


NOW = datetime(2024, 1, 1)


def _msg(content: str, role: str = "user", id: int = 1) -> Message:
    return Message(id=id, chat_id=1, role=role, content=content,
                   input_tokens=None, output_tokens=None, created_at=NOW)


def _project(instructions: str = "", files: list[ProjectFile] | None = None) -> Project:
    return Project(id=1, name="TestProject", instructions=instructions,
                   created_at=NOW, updated_at=NOW, files=files or [])


def _file(filename: str, content: str) -> ProjectFile:
    return ProjectFile(id=1, project_id=1, filename=filename, content=content, created_at=NOW)


# ── build_system_prompt ───────────────────────────────────────────────────────

class TestBuildSystemPrompt:
    def test_no_project_no_extra(self):
        assert context.build_system_prompt() == ""

    def test_extra_only(self):
        result = context.build_system_prompt(extra="Be concise.")
        assert result == "Be concise."

    def test_project_instructions_only(self):
        proj = _project(instructions="You are a helpful bot.")
        result = context.build_system_prompt(proj)
        assert result == "You are a helpful bot."

    def test_project_with_file(self):
        proj = _project(
            instructions="Use this file:",
            files=[_file("main.py", "print('hello')")],
        )
        result = context.build_system_prompt(proj)
        assert 'name="main.py"' in result
        assert "print('hello')" in result
        assert "Use this file:" in result

    def test_multiple_files_all_included(self):
        proj = _project(files=[
            _file("a.py", "aaa"),
            _file("b.py", "bbb"),
        ])
        result = context.build_system_prompt(proj)
        assert "aaa" in result
        assert "bbb" in result

    def test_project_with_extra(self):
        proj = _project(instructions="Do A.")
        result = context.build_system_prompt(proj, extra="Also do B.")
        assert "Do A." in result
        assert "Also do B." in result

    def test_empty_project_instructions_omitted(self):
        proj = _project(instructions="")
        result = context.build_system_prompt(proj)
        assert result == ""

    def test_instructions_stripped(self):
        proj = _project(instructions="  trimmed  ")
        result = context.build_system_prompt(proj)
        assert result == "trimmed"


# ── messages_to_api_format ────────────────────────────────────────────────────

class TestMessagesToApiFormat:
    def test_empty_list(self):
        assert context.messages_to_api_format([]) == []

    def test_user_message(self):
        msgs = [_msg("hello", "user")]
        result = context.messages_to_api_format(msgs)
        assert result == [{"role": "user", "content": "hello"}]

    def test_assistant_message(self):
        msgs = [_msg("hi back", "assistant")]
        result = context.messages_to_api_format(msgs)
        assert result == [{"role": "assistant", "content": "hi back"}]

    def test_summary_becomes_assistant(self):
        msgs = [_msg("old context", "summary")]
        result = context.messages_to_api_format(msgs)
        assert result[0]["role"] == "assistant"
        assert result[0]["content"] == "old context"

    def test_summaries_sorted_to_front(self):
        msgs = [
            _msg("recent user msg", "user", id=3),
            _msg("summary of old", "summary", id=1),
        ]
        result = context.messages_to_api_format(msgs)
        assert result[0]["content"] == "summary of old"
        assert result[1]["content"] == "recent user msg"

    def test_multiple_summaries_all_at_front(self):
        msgs = [
            _msg("user question", "user", id=5),
            _msg("summary 2", "summary", id=3),
            _msg("summary 1", "summary", id=1),
        ]
        result = context.messages_to_api_format(msgs)
        roles = [r["role"] for r in result]
        # Both summaries come before the user message
        assert roles.count("assistant") == 2
        assert roles[-1] == "user"

    def test_conversation_order_preserved_for_recents(self):
        msgs = [
            _msg("q1", "user", id=1),
            _msg("a1", "assistant", id=2),
            _msg("q2", "user", id=3),
        ]
        result = context.messages_to_api_format(msgs)
        assert [r["content"] for r in result] == ["q1", "a1", "q2"]

    def test_image_attachment_becomes_multimodal_blocks(self):
        import base64
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
        m = _msg("what's this?", "user")
        m.attachments = [MessageAttachment(
            id=1, message_id=m.id, kind="image",
            media_type="image/png", filename="moon.png", data=png,
        )]
        result = context.messages_to_api_format([m])
        assert len(result) == 1
        content = result[0]["content"]
        assert isinstance(content, list)
        assert content[0]["type"] == "image"
        assert content[0]["source"]["media_type"] == "image/png"
        assert content[0]["source"]["data"] == base64.b64encode(png).decode("ascii")
        assert content[1] == {"type": "text", "text": "what's this?"}

    def test_image_only_message_omits_text_block(self):
        png = b"\x89PNG\r\n\x1a\n"
        m = _msg("", "user")
        m.attachments = [MessageAttachment(
            id=1, message_id=m.id, kind="image",
            media_type="image/png", filename="x.png", data=png,
        )]
        result = context.messages_to_api_format([m])
        content = result[0]["content"]
        assert len(content) == 1
        assert content[0]["type"] == "image"

    def test_text_only_message_keeps_string_content(self):
        m = _msg("hello", "user")
        result = context.messages_to_api_format([m])
        assert result[0]["content"] == "hello"


# ── total_chars / needs_compression ──────────────────────────────────────────

class TestCharCounting:
    def test_total_chars_empty(self):
        assert context.total_chars([]) == 0

    def test_total_chars_sums_content(self):
        msgs = [_msg("hello"), _msg("world")]
        assert context.total_chars(msgs) == 10

    def test_needs_compression_below_limit(self):
        msgs = [_msg("short")]
        assert context.needs_compression(msgs) is False

    def test_needs_compression_above_limit(self):
        long_content = "x" * 60_000
        msgs = [_msg(long_content)]
        assert context.needs_compression(msgs) is True

    def test_needs_compression_at_exact_limit(self):
        content = "x" * 50_000
        msgs = [_msg(content)]
        assert context.needs_compression(msgs) is False

    def test_needs_compression_one_over_limit(self):
        content = "x" * 50_001
        msgs = [_msg(content)]
        assert context.needs_compression(msgs) is True


# ── compress_chat ─────────────────────────────────────────────────────────────

class TestCompressChat:
    def test_no_compression_when_too_few_messages(self, db):
        c = database.create_chat("model")
        database.add_message(c.id, "user", "hi")
        provider = MockProvider()
        did, removed = context.compress_chat(c.id, provider, keep_recent=6, force=True)
        assert did is False
        assert removed == 0

    def test_no_compression_when_not_needed(self, db):
        c = database.create_chat("model")
        for i in range(10):
            database.add_message(c.id, "user", f"msg {i}")
        provider = MockProvider()
        did, removed = context.compress_chat(c.id, provider, keep_recent=6)
        assert did is False

    def test_compression_reduces_messages(self, db):
        c = database.create_chat("model")
        for i in range(10):
            database.add_message(c.id, "user", f"msg {i}")
        provider = MockProvider(response="Summary of old messages.")
        did, removed = context.compress_chat(c.id, provider, keep_recent=6, force=True)
        assert did is True
        assert removed == 4  # 10 messages - keep_recent 6
        remaining = database.get_messages(c.id)
        assert len(remaining) == 7  # 1 summary + 6 kept

    def test_compressed_message_has_summary_role(self, db):
        c = database.create_chat("model")
        for i in range(10):
            database.add_message(c.id, "user", f"msg {i}")
        provider = MockProvider(response="Concise summary.")
        context.compress_chat(c.id, provider, keep_recent=6, force=True)
        msgs = database.get_messages(c.id)
        assert msgs[0].role == "summary"

    def test_compression_calls_provider_complete(self, db):
        c = database.create_chat("model")
        for i in range(10):
            database.add_message(c.id, "user", f"msg {i}")
        provider = MockProvider()
        context.compress_chat(c.id, provider, keep_recent=6, force=True)
        assert len(provider.complete_calls) == 1


# ── generate_chat_title ───────────────────────────────────────────────────────

class TestGenerateChatTitle:
    def test_returns_provider_title(self):
        provider = MockProvider(response="Sorting Algorithms Explained")
        title = context.generate_chat_title("Explain quicksort to me.", provider)
        assert title == "Sorting Algorithms Explained"

    def test_strips_quotes(self):
        provider = MockProvider(response='"My Title"')
        title = context.generate_chat_title("hi", provider)
        assert title == "My Title"

    def test_fallback_on_empty_response(self):
        provider = MockProvider(response="")
        title = context.generate_chat_title("hello world this is a message", provider)
        assert "hello" in title.lower() or title == "New Chat"

    def test_fallback_on_provider_exception(self):
        class BrokenProvider(MockProvider):
            def complete(self, *args, **kwargs):
                raise RuntimeError("API down")

        provider = BrokenProvider()
        title = context.generate_chat_title("explain rust lifetimes please", provider)
        assert title  # any non-empty string is fine

    def test_includes_project_context_in_call(self):
        provider = MockProvider(response="Project Title")
        proj = _project(instructions="Python assistant")
        context.generate_chat_title("help me", provider, project=proj)
        assert len(provider.complete_calls) == 1
        # project context should appear in the user message content
        msg_content = provider.complete_calls[0][0][0]["content"]
        assert "TestProject" in msg_content

    def test_first_message_truncated_to_400_chars(self):
        provider = MockProvider(response="Title")
        long_msg = "x" * 1000
        context.generate_chat_title(long_msg, provider)
        msg_content = provider.complete_calls[0][0][0]["content"]
        # The content passed to provider should not contain 1000 x's
        assert "x" * 401 not in msg_content


# ── generate_title_from_messages ──────────────────────────────────────────────

class TestGenerateTitleFromMessages:
    def test_returns_provider_title(self):
        msgs = [_msg("Explain quicksort to me.", "user", id=1),
                _msg("Quicksort works by...", "assistant", id=2)]
        provider = MockProvider(response="Sorting Algorithms Explained")
        title = context.generate_title_from_messages(msgs, provider)
        assert title == "Sorting Algorithms Explained"

    def test_strips_quotes(self):
        msgs = [_msg("hi", "user", id=1)]
        provider = MockProvider(response='"My Title"')
        title = context.generate_title_from_messages(msgs, provider)
        assert title == "My Title"

    def test_fallback_on_empty_response(self):
        msgs = [_msg("hello world this is a message", "user", id=1)]
        provider = MockProvider(response="")
        title = context.generate_title_from_messages(msgs, provider)
        assert title  # any non-empty string

    def test_fallback_on_provider_exception(self):
        class BrokenProvider(MockProvider):
            def complete(self, *args, **kwargs):
                raise RuntimeError("API down")

        msgs = [_msg("explain rust lifetimes please", "user", id=1)]
        title = context.generate_title_from_messages(msgs, BrokenProvider())
        assert title  # any non-empty string

    def test_empty_messages_returns_new_chat(self):
        provider = MockProvider(response="")
        title = context.generate_title_from_messages([], provider)
        assert title == "New Chat"

    def test_conversation_formatted_for_provider(self):
        msgs = [_msg("hello", "user", id=1),
                _msg("hi there", "assistant", id=2)]
        provider = MockProvider(response="Title")
        context.generate_title_from_messages(msgs, provider)
        assert len(provider.complete_calls) == 1
        content = provider.complete_calls[0][0][0]["content"]
        assert "user: hello" in content
        assert "assistant: hi there" in content

    def test_truncates_long_conversation_from_start(self):
        long_content = "x" * 5000
        msgs = [_msg(long_content, "user", id=1),
                _msg(long_content, "assistant", id=2)]
        provider = MockProvider(response="Title")
        context.generate_title_from_messages(msgs, provider)
        content = provider.complete_calls[0][0][0]["content"]
        # Total would be 10000+ chars; result must be under 8100 chars
        assert len(content) < 8100
