# Design: Start a chat with an initial message

**Date:** 2026-05-27  
**Status:** Approved

---

## Overview

Allow users to pass an initial message directly on the command line when starting a new chat. The message is sent immediately, the response is displayed, and the session then drops into the normal interactive REPL.

---

## Entry Points

Two equivalent ways to start a seeded chat:

| Command | Description |
|---|---|
| `termchat "my prompt"` | Root-level catch-all — any unrecognised positional token(s) become the initial message |
| `termchat ask "my prompt"` | Explicit named command |
| `tc "my prompt"` / `tc ask "my prompt"` | Same via the `tc` shell alias |

All existing options work alongside the message on both entry points:

```
termchat "explain monads" --model claude-opus-4-7
termchat ask "explain monads" -p haskell-project --title "Monad explainer"
```

Existing subcommands (`termchat chat new`, `termchat project …`, etc.) are unaffected.

---

## Behaviour

When an `initial_message` is provided:

1. The chat header (rule + model name + hint line) is printed as normal.
2. The initial message is rendered in a `Panel` — identical to any in-loop user message.
3. `chat_engine.send_message(...)` is called; the response is streamed and rendered.
4. The session falls through into the normal interactive REPL loop.

The initial message travels the **exact same code path** as any user turn: token tracking, auto-compression, chat-key generation, error handling — all behave identically.

---

## Architecture

### `termchat/cli/main.py`

- Add `context_settings={"allow_extra_args": True}` to `@click.group` on `cli`.
- In the `invoke_without_command` branch, join `ctx.args` into `initial_message` (or `None` if empty) and forward it to `chat_new`.
- Add a new top-level `ask` command with:
  - A required `message` argument (positional)
  - The same `--project / -p`, `--model / -m`, `--provider`, `--title / -t` options as `chat new`
  - Delegates to `chat_new(initial_message=message, …)`

### `termchat/cli/chat_commands.py`

- Add `initial_message: str | None = None` parameter to both `chat_new` and `_run_repl`.
- Extract the AI-turn block inside `_run_repl` into a local helper function `_do_ai_turn(user_input: str) -> bool` (returns `True` to continue, raises/returns on error). This avoids duplicating the render + stream + persist logic.
- At the top of `_run_repl`, before the main loop, call `_do_ai_turn(initial_message)` if `initial_message` is set.

No changes to the storage layer, core layer, providers, context engine, or formatting module.

---

## Error Handling

- If the API call for the initial message fails, the error is printed (same as in-loop errors) and the REPL continues — the user can retry or type something else.
- An empty-string `initial_message` (e.g. `termchat ""`) is treated as `None` — the REPL opens normally with no pre-send.

---

## Out of Scope

- `--no-interactive` / one-shot mode (print response and exit) — not requested.
- Piped stdin as initial message — not requested.
- Multi-message seed (passing multiple prompts) — not requested.
