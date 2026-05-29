# Auto-Rename Chat from Full Conversation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/rename` with no arguments call the Anthropic API with the full conversation and apply the generated title automatically.

**Architecture:** A new `generate_title_from_messages()` function in `context.py` owns the full-conversation title logic. The `/rename` REPL handler in `chat_commands.py` calls it when no argument is given. The existing `generate_chat_title()` and its callers are untouched.

**Tech Stack:** Python, prompt_toolkit REPL, Anthropic SDK (via existing `BaseProvider` abstraction), Rich console, pytest

---

## File Map

- **Modify:** `termchat/core/context.py` — add `_FULL_TITLE_SYSTEM` constant and `generate_title_from_messages()`
- **Modify:** `termchat/cli/chat_commands.py` — update `/rename` handler and `_REPL_HELP` string
- **Modify:** `tests/test_context.py` — add `TestGenerateTitleFromMessages` test class

---

### Task 1: Write failing tests for `generate_title_from_messages`

**Files:**
- Modify: `tests/test_context.py`

- [ ] **Step 1: Add the test class to `tests/test_context.py`**

Append this class to the end of the file (after `TestGenerateChatTitle`):

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_context.py::TestGenerateTitleFromMessages -v
```

Expected: All tests FAIL with `AttributeError: module 'termchat.core.context' has no attribute 'generate_title_from_messages'`

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_context.py
git commit -m "test: add failing tests for generate_title_from_messages"
```

---

### Task 2: Implement `generate_title_from_messages` in `context.py`

**Files:**
- Modify: `termchat/core/context.py`

- [ ] **Step 1: Add `_FULL_TITLE_SYSTEM` constant and the new function**

In `termchat/core/context.py`, append after the existing `generate_chat_title` function (after line 229):

```python
_FULL_TITLE_SYSTEM = """\
You generate short, descriptive chat titles.
Given a full conversation between a user and an assistant, output a concise title \
(4-8 words) that captures the main topic or outcome.

Rules (strict):
- Title case (capitalize major words)
- No punctuation at the end
- Capture the specific topic or task
- Avoid generic filler like "Help With" or "Question About"
- Reply with ONLY the title — no explanation, no quotes
"""


def generate_title_from_messages(
    messages: list[Message],
    provider: BaseProvider,
    *,
    project: Project | None = None,
) -> str:
    """Ask the provider to produce a title from the full conversation.

    Falls back to a title derived from the first non-summary message if the
    call fails or returns empty.
    """
    if not messages:
        return "New Chat"

    lines = [f"{m.role}: {m.content}" for m in messages]
    text = "\n\n".join(lines)
    if len(text) > 8000:
        text = "…" + text[-7997:]
    content = f"Conversation:\n{text}"

    if project:
        ctx_lines = [f"Project name: {project.name}"]
        if project.instructions:
            ctx_lines.append(f"Project instructions: {project.instructions[:300]}")
        content += "\n\nProject context:\n" + "\n".join(ctx_lines)

    try:
        result = provider.complete(
            messages=[{"role": "user", "content": content}],
            system=_FULL_TITLE_SYSTEM,
            max_tokens=30,
        )
        title = result.content.strip().strip('"').strip("'")
        if title:
            return title
    except Exception:
        pass

    # Fallback: first few words of the first non-summary message
    first = next((m for m in messages if m.role != "summary"), messages[0])
    words = first.content.split()
    return " ".join(words[:6]) or "New Chat"
```

- [ ] **Step 2: Run the tests to verify they pass**

```bash
pytest tests/test_context.py::TestGenerateTitleFromMessages -v
```

Expected: All 7 tests PASS

- [ ] **Step 3: Run the full test suite to check for regressions**

```bash
pytest
```

Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add termchat/core/context.py tests/test_context.py
git commit -m "feat: add generate_title_from_messages for full-conversation title generation"
```

---

### Task 3: Update the `/rename` REPL handler and help text

**Files:**
- Modify: `termchat/cli/chat_commands.py`

- [ ] **Step 1: Replace the `/rename` handler block**

In `termchat/cli/chat_commands.py`, replace lines 490–512:

```python
        if cmd == "/rename":
            parts = rest.strip().split(None, 1)
            if not parts:
                warn("Usage: /rename [<key or id>] <new title>")
                continue
            # If the first token resolves to a chat AND a second token exists,
            # treat it as a chat reference; otherwise rename the current chat.
            referenced = _resolve_chat_ref(parts[0]) if len(parts) > 1 else None
            if referenced is not None:
                target_chat = referenced
                new_title = parts[1].strip()
            else:
                target_chat = chat
                new_title = rest.strip()
            if not new_title:
                warn("Usage: /rename [<key or id>] <new title>")
                continue
            database.update_chat_title(target_chat.id, new_title)
            if target_chat.id == chat.id:
                chat.title = new_title
            label = target_chat.title or f"#{target_chat.id}"
            success(f"'{label}' renamed to '{new_title}'.")
            continue
```

with:

```python
        if cmd == "/rename":
            parts = rest.strip().split(None, 1)
            if not parts:
                # No args — generate title from the full conversation
                msgs = database.get_messages(chat.id)
                with console.status("[dim]Generating title…[/]"):
                    new_title = ctx.generate_title_from_messages(msgs, provider, project=project)
                database.update_chat_title(chat.id, new_title)
                chat.title = new_title
                success(f"Chat renamed to '{new_title}'.")
                continue
            # If the first token resolves to a chat AND a second token exists,
            # treat it as a chat reference; otherwise rename the current chat.
            referenced = _resolve_chat_ref(parts[0]) if len(parts) > 1 else None
            if referenced is not None:
                target_chat = referenced
                new_title = parts[1].strip()
            else:
                target_chat = chat
                new_title = rest.strip()
            if not new_title:
                warn("Usage: /rename [ID] [TEXT]")
                continue
            database.update_chat_title(target_chat.id, new_title)
            if target_chat.id == chat.id:
                chat.title = new_title
            label = target_chat.title or f"#{target_chat.id}"
            success(f"'{label}' renamed to '{new_title}'.")
            continue
```

- [ ] **Step 2: Update the help text in `_REPL_HELP`**

In `termchat/cli/chat_commands.py`, find this line in `_REPL_HELP`:

```python
  [cyan]/rename[/] [ID] TEXT    — rename this chat, or another chat by numeric ID
```

Replace with:

```python
  [cyan]/rename[/] [ID] [TEXT]  — rename this chat (omit TEXT to generate from conversation)
```

- [ ] **Step 3: Run the full test suite**

```bash
pytest
```

Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add termchat/cli/chat_commands.py
git commit -m "feat: auto-rename chat from full conversation when /rename called with no args"
```
