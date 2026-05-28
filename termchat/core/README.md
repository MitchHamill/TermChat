# termchat/core — AI orchestration layer

This package contains everything that talks to an AI provider or manages conversation context. It knows nothing about the terminal UI and nothing about how to render output — that is all in `cli/`.

```
core/
├── chat.py           ← single orchestration entry point (send_message)
├── context.py        ← system prompt builder, message formatter, compression
└── providers/
    ├── README.md     ← full provider contract and how to add a new one
    ├── base.py       ← BaseProvider ABC + CompletionResult dataclass
    ├── anthropic_provider.py
    └── __init__.py   ← registry (_REGISTRY) + get_provider() factory
```

---

## `chat.py` — orchestration

### `send_message(chat, user_text, provider, *, project, on_chunk, auto_compress)`

The single function the CLI calls to perform one AI turn. Steps in order:

1. **Persist the user turn** — `database.add_message(chat.id, "user", user_text)`
2. **Touch the chat** — updates `updated_at` so the chat floats to the top of `chat list`
3. **Build context** — `context.build_system_prompt(project)` + `context.messages_to_api_format(all_messages)`
4. **Stream the response** — calls `provider.stream()`, drives the generator manually, calls `on_chunk` with each text chunk so the UI can render progressively
5. **Persist the assistant turn** — stores content + token counts from the `CompletionResult`
6. **Auto-title** — if the chat has no title yet, uses the first 60 chars of the user message
7. **Auto-compress** — calls `context.maybe_auto_compress()` if `auto_compress=True`

**Returns:** `(user_message, assistant_message, was_compressed)`

### `get_chat_with_messages(chat_id)`

Convenience wrapper: returns `(Chat | None, list[Message])`.

---

## `context.py` — context management

### System prompt

`build_system_prompt(project, extra="")` assembles the system prompt sent to the provider:

```
<project instructions>

<file name="foo.py">
...file content...
</file>

<extra>
```

If `project` is `None`, the system prompt is empty (or just `extra` if supplied).

### Message format conversion

`messages_to_api_format(messages)` converts stored `Message` dataclasses to the `[{role, content}]` list providers expect.

**Key rule for summaries:** summary messages are always placed at the **front** of the list, regardless of their database insertion order. This ensures the model always sees compressed older context before recent messages.

```python
# Summary messages become role="assistant" in the API payload:
{"role": "assistant", "content": "[Conversation summary — 14 earlier messages compressed]\n\n..."}
```

### Compression

#### `compress_chat(chat_id, provider, *, keep_recent, force)`

| Step | Detail |
|------|--------|
| Fetch all messages | via `database.get_messages` |
| Split | `to_summarise = messages[:-keep_recent]` |
| Request summary | `provider.complete(...)` with a focused system prompt |
| Atomic replace | `database.replace_messages_with_summary(...)` deletes old rows and inserts one summary row in a single transaction |

Returns `(did_compress: bool, messages_removed: int)`.

Set `force=True` to compress even if the character limit hasn't been reached (used by `/compress` and `termchat chat compress`).

#### `maybe_auto_compress(chat_id, provider, messages)`

Called after every assistant reply. Checks `total_chars(messages) > CONTEXT_CHAR_LIMIT` and delegates to `compress_chat` if true.

#### `needs_compression(messages)` / `total_chars(messages)`

Utility predicates — exposed so the CLI can check without calling the full compress path.

### Chat title generation

`generate_chat_title(first_message, provider, *, project)` asks the AI to produce a concise 4–8 word title in Title Case for a new chat. When a project is supplied, the project name and instructions are passed as supplemental context so the title reflects the project's domain.

Falls back to the first six words of the raw message if the API call fails.

---

## `providers/`

See [`providers/README.md`](providers/README.md) for the full contract and a step-by-step guide to adding a new provider.

### Quick summary

```python
# Get a provider instance
from termchat.core.providers import get_provider
prov = get_provider("anthropic", api_key="sk-ant-…", model="claude-sonnet-4-6")

# Non-streaming
result = prov.complete(messages, system="…")
result.content        # str
result.input_tokens   # int
result.output_tokens  # int

# Streaming
gen = prov.stream(messages, system="…")
try:
    while True:
        chunk = next(gen)   # str — each text chunk
except StopIteration as e:
    result = e.value        # CompletionResult
```
