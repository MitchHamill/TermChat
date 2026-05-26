"""Context window management.

Responsibilities:
  - Convert stored Message objects into the list-of-dicts format providers expect
  - Build the system prompt (optional project instructions + attached files)
  - Decide when to auto-compress and perform the compression via the provider
"""

from __future__ import annotations

import re

from termchat import config
from termchat.core.providers.base import BaseProvider, CompletionResult
from termchat.storage import database
from termchat.storage.models import Message, Project

# ── Prompt builders ───────────────────────────────────────────────────────────

_SUMMARY_SYSTEM = """\
You are a conversation summarizer.
Given a list of chat messages, write a concise but complete summary that captures:
- All factual information, decisions, and conclusions reached
- Any code, file contents, or technical details that may be needed later
- The overall thread of the conversation

Write the summary in third person past tense as a continuous block of text.
Do NOT include greetings or meta-commentary about summarising.
"""

_SUMMARY_REQUEST_TEMPLATE = """\
Summarize the following conversation messages:

{messages}

Write a concise summary that preserves all important context."""


def build_system_prompt(project: Project | None = None, extra: str = "") -> str:
    """Assemble a system prompt from project instructions and attached files."""
    parts: list[str] = []

    if project:
        if project.instructions:
            parts.append(project.instructions.strip())
        for f in project.files:
            parts.append(
                f"<file name=\"{f.filename}\">\n{f.content}\n</file>"
            )

    if extra:
        parts.append(extra.strip())

    return "\n\n".join(parts)


def messages_to_api_format(messages: list[Message]) -> list[dict]:
    """Convert stored messages to the [{role, content}] format providers accept.

    Summary messages are presented as assistant messages so they slot naturally
    into the conversation flow.  Summaries are always moved to the front of the
    list: they represent *compressed older context* and must precede the recent
    messages regardless of their database insert order.
    """
    summaries = [m for m in messages if m.role == "summary"]
    recents = [m for m in messages if m.role != "summary"]

    result: list[dict] = []
    for msg in summaries:
        result.append({"role": "assistant", "content": msg.content})
    for msg in recents:
        role = "assistant" if msg.role == "summary" else msg.role
        result.append({"role": role, "content": msg.content})
    return result


# ── Character counting ────────────────────────────────────────────────────────

def total_chars(messages: list[Message]) -> int:
    return sum(m.char_count for m in messages)


def needs_compression(messages: list[Message]) -> bool:
    return total_chars(messages) > config.CONTEXT_CHAR_LIMIT


# ── Auto-compress ─────────────────────────────────────────────────────────────

def _format_messages_for_summary(messages: list[Message]) -> str:
    lines: list[str] = []
    for m in messages:
        role_label = m.role.upper()
        lines.append(f"[{role_label}]\n{m.content}")
    return "\n\n---\n\n".join(lines)


def compress_chat(
    chat_id: int,
    provider: BaseProvider,
    *,
    keep_recent: int | None = None,
    force: bool = False,
) -> tuple[bool, int]:
    """Summarize old messages to reduce context size.

    Returns (did_compress, messages_removed).

    The *keep_recent* most recent messages are always preserved verbatim.
    Set *force=True* to compress even if the limit hasn't been reached.
    """
    if keep_recent is None:
        keep_recent = config.CONTEXT_KEEP_RECENT

    messages = database.get_messages(chat_id)

    if len(messages) <= keep_recent + 1:
        return False, 0  # nothing to compress

    if not force and not needs_compression(messages):
        return False, 0

    # Split: old messages to summarise vs. recent messages to keep
    to_summarise = messages[:-keep_recent]
    # Keep at least one full exchange if only summaries were old
    if not to_summarise:
        return False, 0

    formatted = _format_messages_for_summary(to_summarise)
    summary_request = _SUMMARY_REQUEST_TEMPLATE.format(messages=formatted)

    result: CompletionResult = provider.complete(
        messages=[{"role": "user", "content": summary_request}],
        system=_SUMMARY_SYSTEM,
        max_tokens=2048,
    )

    summary_text = (
        f"[Conversation summary — {len(to_summarise)} earlier messages compressed]\n\n"
        + result.content
    )

    last_old_id = to_summarise[-1].id
    database.replace_messages_with_summary(chat_id, last_old_id, summary_text)

    return True, len(to_summarise)


def maybe_auto_compress(
    chat_id: int,
    provider: BaseProvider,
    messages: list[Message],
) -> tuple[bool, int]:
    """Compress if over the limit; called after each assistant reply."""
    if not needs_compression(messages):
        return False, 0
    return compress_chat(chat_id, provider)


# ── Chat key generation ───────────────────────────────────────────────────────

_KEY_SYSTEM = """\
You generate ultra-short chat identifiers.
Given the opening message of a conversation, output a 2-3 word lowercase hyphenated slug.

Rules (strict):
- Lowercase letters and hyphens only — no other characters
- 10 characters maximum total (including hyphens)
- 2-3 words; capture the specific topic
- Avoid generic filler words like "help", "question", "chat", "talk"
- Reply with ONLY the slug — no explanation, no punctuation, no quotes
"""


def _sanitize_key(raw: str) -> str:
    """Normalize AI output to a clean lowercase-hyphenated slug, max 10 chars."""
    lines = raw.strip().lower().splitlines()
    key = lines[0] if lines else ""
    key = re.sub(r"[\s_]+", "-", key)            # spaces/underscores → hyphens
    key = re.sub(r"[^a-z0-9-]", "", key)         # strip everything else
    key = re.sub(r"-{2,}", "-", key)              # collapse consecutive hyphens
    key = key.strip("-")[:10].rstrip("-")         # truncate then trim trailing hyphen
    return key


def generate_chat_key(first_message: str, provider: BaseProvider) -> str:
    """Ask the provider to produce a short slug for a chat's first message.

    Falls back to a slug derived from the raw text if the call fails or returns
    an unusable result.
    """
    try:
        result = provider.complete(
            messages=[{"role": "user", "content": f"Opening message: {first_message[:300]}"}],
            system=_KEY_SYSTEM,
            max_tokens=20,
        )
        key = _sanitize_key(result.content)
        if key:
            return key
    except Exception:
        pass
    # Fallback: derive a slug from the raw message text
    words = re.sub(r"[^a-z0-9\s]", "", first_message.lower()).split()
    return ("-".join(words[:2]))[:10] or "chat"
