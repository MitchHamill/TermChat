"""Chat engine — orchestrates provider calls, storage, and context management."""

from __future__ import annotations

from typing import Callable, Generator

from termchat.core import context as ctx
from termchat.core.providers.base import BaseProvider, CompletionResult
from termchat.storage import database
from termchat.storage.models import Chat, Message, Project


def send_message(
    chat: Chat,
    user_text: str,
    provider: BaseProvider,
    *,
    project: Project | None = None,
    on_chunk: Callable[[str], None] | None = None,
    auto_compress: bool = True,
    attachments: list[dict] | None = None,
) -> tuple[Message, Message, bool]:
    """Send *user_text*, stream the response, persist both messages.

    Returns (user_message, assistant_message, was_compressed).

    *on_chunk* is called with each streamed text chunk so the UI can render
    progressively.

    *attachments* is a list of binary attachment dicts
    ({"kind","filename","media_type","data"}) — typically images — that get
    persisted on the user message and forwarded to the provider as multimodal
    content blocks.
    """
    # 1. Persist the user turn
    user_msg = database.add_message(
        chat.id, "user", user_text, attachments=attachments
    )
    database.touch_chat(chat.id)

    # 2. Build context for the API call
    all_msgs = database.get_messages(chat.id)
    system_prompt = ctx.build_system_prompt(project)
    api_messages = ctx.messages_to_api_format(all_msgs)

    # 3. Stream the assistant response
    gen = provider.stream(api_messages, system=system_prompt)
    chunks: list[str] = []
    result: CompletionResult | None = None

    try:
        while True:
            chunk = next(gen)
            chunks.append(chunk)
            if on_chunk:
                on_chunk(chunk)
    except StopIteration as e:
        result = e.value

    content = "".join(chunks)

    # 4. Persist the assistant turn with token counts
    asst_msg = database.add_message(
        chat.id,
        "assistant",
        content,
        input_tokens=result.input_tokens if result else None,
        output_tokens=result.output_tokens if result else None,
    )

    # 5. Auto-set title from first user message if not set
    if chat.title is None:
        title = user_text[:60].replace("\n", " ").strip()
        database.update_chat_title(chat.id, title)
        chat.title = title

    # 6. Optionally auto-compress if context is too large
    compressed = False
    if auto_compress:
        updated_msgs = database.get_messages(chat.id)
        compressed, _ = ctx.maybe_auto_compress(chat.id, provider, updated_msgs)

    return user_msg, asst_msg, compressed


def get_chat_with_messages(chat_id: int) -> tuple[Chat | None, list[Message]]:
    chat = database.get_chat(chat_id)
    if chat is None:
        return None, []
    return chat, database.get_messages(chat_id)
