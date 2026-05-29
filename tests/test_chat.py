"""Tests for core/chat.py — the chat engine."""

from __future__ import annotations

from termchat.core import chat as chat_engine
from termchat.storage import database
from termchat.storage.models import Message

from tests.conftest import MockProvider


class TestSendMessage:
    def test_returns_three_tuple(self, db, mock_provider):
        c = database.create_chat("model")
        result = chat_engine.send_message(c, "Hello", mock_provider)
        assert len(result) == 3

    def test_persists_user_message(self, db, mock_provider):
        c = database.create_chat("model")
        user_msg, _, _ = chat_engine.send_message(c, "What is 2+2?", mock_provider)
        assert isinstance(user_msg, Message)
        assert user_msg.role == "user"
        assert user_msg.content == "What is 2+2?"

    def test_persists_assistant_message(self, db, mock_provider):
        c = database.create_chat("model")
        _, asst_msg, _ = chat_engine.send_message(c, "Hello", mock_provider)
        assert isinstance(asst_msg, Message)
        assert asst_msg.role == "assistant"
        assert asst_msg.content == mock_provider.response.rstrip()  # stream joins chunks

    def test_assistant_message_in_db(self, db, mock_provider):
        c = database.create_chat("model")
        chat_engine.send_message(c, "Hi", mock_provider)
        msgs = database.get_messages(c.id)
        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert msgs[1].role == "assistant"

    def test_token_counts_stored(self, db):
        provider = MockProvider(response="answer", input_tokens=42, output_tokens=17)
        c = database.create_chat("model")
        _, asst_msg, _ = chat_engine.send_message(c, "q", provider)
        assert asst_msg.input_tokens == 42
        assert asst_msg.output_tokens == 17

    def test_on_chunk_callback_called(self, db, mock_provider):
        c = database.create_chat("model")
        received: list[str] = []
        chat_engine.send_message(c, "Hello", mock_provider, on_chunk=received.append)
        assert len(received) > 0
        assert "".join(received).strip() == mock_provider.response.strip()

    def test_auto_sets_title_from_first_message(self, db, mock_provider):
        c = database.create_chat("model")
        assert c.title is None
        chat_engine.send_message(c, "Tell me about Python", mock_provider)
        refreshed = database.get_chat(c.id)
        assert refreshed.title is not None
        assert "Tell me about Python" in refreshed.title

    def test_title_not_overwritten_on_second_message(self, db, mock_provider):
        c = database.create_chat("model", title="Existing Title")
        chat_engine.send_message(c, "new message", mock_provider)
        refreshed = database.get_chat(c.id)
        assert refreshed.title == "Existing Title"

    def test_compressed_flag_false_when_small(self, db, mock_provider):
        c = database.create_chat("model")
        _, _, compressed = chat_engine.send_message(c, "short msg", mock_provider)
        assert compressed is False

    def test_compressed_flag_true_when_large(self, db):
        huge_content = "x" * 60_000
        provider = MockProvider(response=huge_content)
        c = database.create_chat("model")
        # Seed the chat with enough messages to trigger compression
        for _ in range(8):
            database.add_message(c.id, "user", huge_content)
            database.add_message(c.id, "assistant", huge_content)
        compress_provider = MockProvider(response="Summary.")
        _, _, compressed = chat_engine.send_message(c, "one more", compress_provider)
        assert compressed is True

    def test_auto_compress_false_skips_compression(self, db, mock_provider):
        c = database.create_chat("model")
        _, _, compressed = chat_engine.send_message(
            c, "msg", mock_provider, auto_compress=False
        )
        assert compressed is False
        assert len(mock_provider.complete_calls) == 0  # no compress call

    def test_provider_stream_called_once(self, db, mock_provider):
        c = database.create_chat("model")
        chat_engine.send_message(c, "q", mock_provider)
        assert len(mock_provider.stream_calls) == 1

    def test_messages_passed_to_provider_include_history(self, db, mock_provider):
        c = database.create_chat("model")
        database.add_message(c.id, "user", "prior question")
        database.add_message(c.id, "assistant", "prior answer")
        chat_engine.send_message(c, "follow up", mock_provider)
        api_messages = mock_provider.stream_calls[0][0]
        contents = [m["content"] for m in api_messages]
        assert "prior question" in contents
        assert "prior answer" in contents
        assert "follow up" in contents

    def test_image_attachment_forwarded_as_multimodal(self, db, mock_provider):
        png = b"\x89PNG\r\n\x1a\n" + b"\x01\x02\x03"
        c = database.create_chat("model")
        chat_engine.send_message(
            c,
            "what is this?",
            mock_provider,
            attachments=[{
                "kind": "image",
                "filename": "moon.png",
                "media_type": "image/png",
                "data": png,
            }],
        )
        # User message persisted with the binary attachment
        msgs = database.get_messages(c.id)
        assert len(msgs[0].attachments) == 1
        assert msgs[0].attachments[0].data == png
        # Provider received a multimodal content list for the user turn
        api_messages = mock_provider.stream_calls[0][0]
        user_block = api_messages[0]
        assert user_block["role"] == "user"
        assert isinstance(user_block["content"], list)
        assert user_block["content"][0]["type"] == "image"
        assert user_block["content"][0]["source"]["media_type"] == "image/png"


class TestGetChatWithMessages:
    def test_returns_none_for_missing_chat(self, db):
        chat, msgs = chat_engine.get_chat_with_messages(9999)
        assert chat is None
        assert msgs == []

    def test_returns_chat_and_messages(self, db, mock_provider):
        c = database.create_chat("model")
        database.add_message(c.id, "user", "hello")
        database.add_message(c.id, "assistant", "world")
        fetched_chat, msgs = chat_engine.get_chat_with_messages(c.id)
        assert fetched_chat is not None
        assert fetched_chat.id == c.id
        assert len(msgs) == 2

    def test_empty_messages_for_new_chat(self, db):
        c = database.create_chat("model")
        _, msgs = chat_engine.get_chat_with_messages(c.id)
        assert msgs == []
