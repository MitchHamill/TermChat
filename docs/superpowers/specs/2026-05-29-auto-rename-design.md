# Auto-Rename Chat from Full Conversation

**Date:** 2026-05-29  
**Status:** Approved

## Summary

Update the `/rename` REPL command to work without an argument. When called with no text, it calls the Anthropic API with the full conversation context and applies the generated title automatically.

## Changes

### `termchat/core/context.py` — new function

Add `generate_title_from_messages(messages, provider, *, project=None) -> str`.

- Formats `list[Message]` as `role: content` lines joined by newlines
- Truncates from the **start** of the conversation (keeping the most recent context) if the total exceeds 8,000 chars
- Uses a new `_FULL_TITLE_SYSTEM` prompt: same rules as `_TITLE_SYSTEM` (title case, 4–8 words, no trailing punctuation, reply with only the title) but instructs the model to consider the whole conversation
- Wraps the `provider.complete()` call in a broad `except Exception` and falls back to the first few words of the first non-summary message, same pattern as `generate_chat_title()`
- Returns a `str`

### `termchat/cli/chat_commands.py` — `/rename` handler

When `rest.strip()` is empty (no args provided):

1. Call `database.get_messages(chat.id)` to get the full message list
2. Call `ctx.generate_title_from_messages(messages, provider, project=project)` inside a `console.status("[dim]Generating title…[/]")` spinner
3. Apply the title via `database.update_chat_title` and update `chat.title`
4. Print a success message in the same style as the manual rename path

The existing behavior (rename with an explicit title, or rename another chat by ID) is unchanged.

### `termchat/cli/chat_commands.py` — help text

Update `_REPL_HELP`:

```
/rename [ID] [TEXT]   — rename this chat (or another by ID); omit TEXT to generate from conversation
```

## Out of Scope

- No changes to `generate_chat_title()` or its callers in `chat.py`
- No new tests required beyond the existing suite (the new function follows the same testable shape as `generate_chat_title`; manual verification via the REPL is sufficient)
