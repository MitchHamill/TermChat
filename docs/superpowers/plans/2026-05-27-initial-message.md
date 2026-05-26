# Initial Message Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow `termchat "prompt"` and `termchat ask "prompt"` to send an initial message, display the response, then drop into the normal interactive REPL.

**Architecture:** Thread an `initial_message` parameter from two new CLI entry points (`allow_extra_args` root catch-all and a new `ask` command) through `chat_new` → `_run_repl`. Inside `_run_repl`, extract the existing AI-turn block into a closure `_do_ai_turn` and call it once before the loop when an initial message is present.

**Tech Stack:** Python, Click (CLI), prompt_toolkit (REPL), Rich (terminal rendering), Anthropic SDK (via existing `chat_engine.send_message`).

---

> **Note:** This project has no automated test suite. Each task ends with a manual smoke-test using `TERMCHAT_CONFIG_DIR=/tmp/tc` to avoid touching the real database.

---

### Task 1: Extract AI-turn block into a `_do_ai_turn` closure inside `_run_repl`

This is a pure refactor — identical behaviour, just moves the AI-turn block into a reusable helper. No new feature yet.

**Files:**
- Modify: `termchat/cli/chat_commands.py` (lines 296–345)

- [ ] **Step 1: Open `termchat/cli/chat_commands.py` and locate the AI-turn block**

  It begins at the comment `# ── AI turn` inside `_run_repl`, after all the slash-command handlers. The block runs from the `console.print(Panel(...))` call through the chat-key generation at the end of the loop body.

- [ ] **Step 2: Replace the AI-turn block with a closure + call**

  Replace everything from `# ── AI turn` to the end of the loop body (just before `return None`) with:

  ```python
      # ── AI turn helper (closure over chat, provider, project) ─────────────
      def _do_ai_turn(user_input: str) -> bool:
          """Render user message, call AI, render response.

          Returns True on success, False on API error (caller should continue).
          """
          console.print(Panel(
              user_input,
              title="[bold blue]You[/]",
              border_style="blue",
              title_align="left",
              padding=(0, 1),
          ))

          streamed: list[str] = []
          result_holder: list = [None]  # noqa: F841 (kept for future streaming)

          def on_chunk(chunk: str) -> None:
              streamed.append(chunk)

          with console.status("[green]Thinking…[/]", spinner="dots"):
              try:
                  user_msg, asst_msg, compressed = chat_engine.send_message(
                      chat,
                      user_input,
                      provider,
                      project=project,
                      on_chunk=on_chunk,
                      auto_compress=True,
                  )
              except Exception as exc:
                  error(f"API error: {exc}")
                  return False

          render_message(asst_msg)

          if compressed:
              console.print(
                  "[yellow dim]⚡ Context auto-compressed (50 k char limit reached).[/]"
              )

          if chat.key is None:
              with console.status("[dim]Naming chat…[/]"):
                  raw = ctx.generate_chat_key(user_input, provider)
                  chat.key = database.update_chat_key(
                      chat.id, database.unique_chat_key(raw)
                  )
              console.print(Rule(f"[bold]{chat.key}[/]  [dim]{chat.model}[/]"))

          return True

      # ── Main loop ─────────────────────────────────────────────────────────────
      while True:
          # ── Prompt ────────────────────────────────────────────────────────────
          try:
              user_input = session.prompt(_PROMPT).strip()
          except (KeyboardInterrupt, EOFError):
              console.print("\n[dim]Goodbye.[/]")
              break

          if not user_input:
              continue

          # ── REPL commands ──────────────────────────────────────────────────────
          cmd, _, rest = user_input.partition(" ")
          cmd = cmd.lower()

          if cmd in ("/quit", "/exit"):
              console.print("[dim]Goodbye.[/]")
              break

          if cmd == "/help":
              console.print(_REPL_HELP)
              continue

          if cmd == "/clear":
              import os
              os.system("clear" if sys.platform != "win32" else "cls")
              continue

          if cmd == "/history":
              messages = database.get_messages(chat.id)
              if not messages:
                  console.print("[dim](no messages yet)[/]")
              else:
                  with console.pager(styles=True):
                      for msg in messages:
                          render_message(msg)
              continue

          if cmd == "/tokens":
              totals = database.chat_token_totals(chat.id)
              render_token_summary(totals)
              continue

          if cmd == "/compress":
              with console.status("Compressing context…"):
                  did, n = ctx.compress_chat(chat.id, provider, force=True)
              if did:
                  success(f"Compressed {n} messages into a summary.")
              else:
                  warn("Nothing to compress (too few messages).")
              continue

          if cmd == "/title":
              title = rest.strip()
              if title:
                  database.update_chat_title(chat.id, title)
                  chat.title = title
                  success(f"Title set to '{title}'.")
              else:
                  warn("Usage: /title <new title>")
              continue

          if cmd == "/chats":
              chats = database.list_chats(limit=15)
              projects_map: dict[int, str] = {p.id: p.name for p in database.list_projects()}
              render_chat_list(chats, projects_map, current_id=chat.id)
              if len(chats) == 15:
                  console.print("[dim]Showing 15 most recent. Use [bold]termchat chat list[/] to see all.[/]")
              continue

          if cmd == "/switch":
              arg = rest.strip()
              if not arg:
                  warn("Usage: /switch <key or id>")
                  continue
              target = _resolve_chat_ref(arg)
              if target is None:
                  error(f"Chat '{arg}' not found.")
                  _show_chat_list(current_id=chat.id)
                  continue
              if target.id == chat.id:
                  warn("Already in this chat.")
                  continue
              label = target.key or f"#{target.id}"
              console.print(f"[dim]Switching to {label}…[/]")
              return target.id

          if cmd == "/rename":
              parts = rest.strip().split(None, 1)
              if not parts:
                  warn("Usage: /rename [<key or id>] <new title>")
                  continue
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
              label = target_chat.key or f"#{target_chat.id}"
              success(f"'{label}' renamed to '{new_title}'.")
              continue

          if cmd == "/delete":
              arg = rest.strip()
              if arg:
                  target_chat = _resolve_chat_ref(arg)
                  if target_chat is None:
                      error(f"Chat '{arg}' not found.")
                      continue
              else:
                  target_chat = chat
              label = target_chat.key or f"#{target_chat.id}"
              try:
                  confirmed = click.confirm(f"  Delete '{label}'?", default=False)
              except click.Abort:
                  console.print()
                  continue
              if not confirmed:
                  continue
              database.delete_chat(target_chat.id)
              success(f"'{label}' deleted.")
              if target_chat.id == chat.id:
                  console.print("[dim]Current chat deleted. Goodbye.[/]")
                  return None
              continue

          # ── Unknown slash-command guard ────────────────────────────────────────
          if user_input.startswith("/") and cmd not in _REPL_COMMANDS:
              try:
                  confirmed = click.confirm(
                      f"  '{cmd}' isn't a command — send to AI?", default=False
                  )
              except click.Abort:
                  console.print()
                  continue
              if not confirmed:
                  continue

          if not _do_ai_turn(user_input):
              continue

      return None
  ```

- [ ] **Step 3: Verify the refactor didn't break the normal REPL**

  ```bash
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat chat new
  ```

  Expected: chat opens normally, you can type a message and get a response, `/quit` exits. The REPL should be identical to before.

- [ ] **Step 4: Commit**

  ```bash
  git add termchat/cli/chat_commands.py
  git commit -m "refactor: extract AI-turn block into _do_ai_turn closure in _run_repl"
  ```

---

### Task 2: Add `initial_message` parameter to `_run_repl` and `chat_new`

**Files:**
- Modify: `termchat/cli/chat_commands.py`

- [ ] **Step 1: Update `_run_repl` signature and add pre-loop send**

  Change the signature from:
  ```python
  def _run_repl(chat: Chat, provider, project=None) -> int | None:
  ```
  to:
  ```python
  def _run_repl(chat: Chat, provider, project=None, initial_message: str | None = None) -> int | None:
  ```

  Then, after the banner block (the `console.print(...)` lines that show the chat header and hint line), and **before** the `_do_ai_turn` closure definition, add:

  ```python
      # Pre-seed: send the initial message before entering the loop
      _initial_message = (initial_message or "").strip() or None
  ```

  Then, after the `_do_ai_turn` closure definition and **before** `while True:`, add:

  ```python
      if _initial_message:
          _do_ai_turn(_initial_message)

  ```

  The structure of `_run_repl` should now be:
  ```
  def _run_repl(..., initial_message=None):
      session = PromptSession(...)
      # print header/banner
      _initial_message = (initial_message or "").strip() or None

      def _do_ai_turn(user_input):
          ...

      if _initial_message:
          _do_ai_turn(_initial_message)

      while True:
          ...
          if not _do_ai_turn(user_input):
              continue
      return None
  ```

- [ ] **Step 2: Add `initial_message` as a hidden option on `chat_new`**

  Add one option to the `chat_new` Click command (after the existing `--title` option) and update its signature:

  ```python
  @chat_group.command("new")
  @click.option("--project", "-p", "project_name", default=None,
                help="Associate with a project by name or id.")
  @click.option("--model", "-m", default=None, help="Model override.")
  @click.option("--provider", default=None, type=str, help="Provider override.")
  @click.option("--title", "-t", default=None, help="Set a title immediately.")
  @click.option("--initial-message", "initial_message", default=None, hidden=True,
                help="Pre-seed the chat with this message (used programmatically).")
  def chat_new(project_name: str | None, model: str | None, provider: str | None,
               title: str | None, initial_message: str | None = None) -> None:
  ```

  And thread it through to `_run_repl` at the bottom of `chat_new`:
  ```python
      chat = database.create_chat(mname, pname, project_id, title)
      _handle_switch(_run_repl(chat, prov, project=project, initial_message=initial_message))
  ```

- [ ] **Step 3: Verify `chat new` still works normally (no initial message)**

  ```bash
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat chat new
  ```
  Expected: opens empty REPL as before.

- [ ] **Step 4: Verify initial message works via the hidden option**

  ```bash
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat chat new --initial-message "What is 2+2?"
  ```
  Expected: chat opens, your message is displayed in a blue Panel, AI responds, then you're in the REPL to continue.

- [ ] **Step 5: Commit**

  ```bash
  git add termchat/cli/chat_commands.py
  git commit -m "feat: add initial_message support to _run_repl and chat_new"
  ```

---

### Task 3: Wire root-level catch-all in `main.py`

**Files:**
- Modify: `termchat/cli/main.py`

- [ ] **Step 1: Add `allow_extra_args` to the root group**

  Change:
  ```python
  @click.group(invoke_without_command=True)
  ```
  to:
  ```python
  @click.group(invoke_without_command=True, context_settings={"allow_extra_args": True})
  ```

- [ ] **Step 2: Pass `initial_message` in the `invoke_without_command` branch**

  Change the bottom of `cli`:
  ```python
      _init_db()
      if ctx.invoked_subcommand is None:
          from termchat.cli.chat_commands import chat_new
          ctx.invoke(chat_new, project_name=project_name, model=model, provider=provider)
  ```
  to:
  ```python
      _init_db()
      if ctx.invoked_subcommand is None:
          from termchat.cli.chat_commands import chat_new
          initial_message = " ".join(ctx.args).strip() or None
          ctx.invoke(chat_new, project_name=project_name, model=model,
                     provider=provider, initial_message=initial_message)
  ```

- [ ] **Step 3: Verify `termchat "prompt"` works**

  ```bash
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat "What is the capital of France?"
  ```
  Expected: message is rendered in a Panel, AI responds, REPL opens.

- [ ] **Step 4: Verify existing subcommands still route correctly**

  ```bash
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat chat new
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat chat list
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat new
  ```
  Expected: all three work as before — no routing regressions.

- [ ] **Step 5: Verify `termchat` (no args) still opens an empty REPL**

  ```bash
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat
  ```
  Expected: opens normally.

- [ ] **Step 6: Commit**

  ```bash
  git add termchat/cli/main.py
  git commit -m "feat: allow root-level positional message (termchat \"prompt\")"
  ```

---

### Task 4: Add the `ask` command

**Files:**
- Modify: `termchat/cli/main.py`

- [ ] **Step 1: Add the `ask` command after the `new_alias` command**

  Add this block after the `new_alias` command (before `if __name__ == "__main__":`):

  ```python
  @cli.command("ask")
  @click.argument("message")
  @click.option("--project", "-p", "project_name", default=None,
                help="Associate new chat with a project.")
  @click.option("--model", "-m", default=None, help="Model override.")
  @click.option("--provider", default=None, help="Provider override.")
  @click.option("--title", "-t", default=None, help="Set a title immediately.")
  @click.pass_context
  def ask_cmd(ctx: click.Context, message: str, project_name: str | None,
              model: str | None, provider: str | None, title: str | None) -> None:
      """Start a new chat with MESSAGE as the opening prompt."""
      from termchat.cli.chat_commands import chat_new
      ctx.invoke(chat_new, project_name=project_name, model=model,
                 provider=provider, title=title, initial_message=message)
  ```

- [ ] **Step 2: Verify `termchat ask "prompt"` works**

  ```bash
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat ask "Explain list comprehensions in Python"
  ```
  Expected: message Panel, AI response, drops into REPL.

- [ ] **Step 3: Verify options work alongside the message**

  ```bash
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat ask "hello" --model claude-haiku-4-5-20251001
  ```
  Expected: chat opens with haiku model, message sent, REPL continues.

- [ ] **Step 4: Verify `termchat ask --help` is clean**

  ```bash
  termchat ask --help
  ```
  Expected: shows `MESSAGE` argument and the four options (`--project`, `--model`, `--provider`, `--title`). `--initial-message` does NOT appear (it's hidden).

- [ ] **Step 5: Verify `termchat --help` shows `ask` in the commands list**

  ```bash
  termchat --help
  ```
  Expected: `ask` appears as a command alongside `chat`, `project`, `config`, `setup`, `new`.

- [ ] **Step 6: Commit**

  ```bash
  git add termchat/cli/main.py
  git commit -m "feat: add 'termchat ask <message>' command"
  ```

---

### Task 5: Final integration smoke-test

No code changes — verify all scenarios end-to-end.

- [ ] **Scenario 1 — root-level single-word message**

  ```bash
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat "hello"
  ```
  Expected: Panel with "hello", AI response, REPL opens.

- [ ] **Scenario 2 — root-level multi-word message (quoted)**

  ```bash
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat "what time is it in Tokyo right now?"
  ```
  Expected: full sentence sent, response shown, REPL continues.

- [ ] **Scenario 3 — root-level with options**

  ```bash
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat "summarise the Rust ownership model" --model claude-haiku-4-5-20251001
  ```
  Expected: correct model used, message sent, REPL opens.

- [ ] **Scenario 4 — `ask` command**

  ```bash
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat ask "what is a monad?"
  ```
  Expected: message Panel, response, REPL.

- [ ] **Scenario 5 — `ask` with project**

  ```bash
  # First create a test project if none exists
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat project new testproj
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat ask "hello" -p testproj
  ```
  Expected: "Project: testproj" shown under the chat header.

- [ ] **Scenario 6 — no regression: existing subcommands**

  ```bash
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat chat new
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat chat list
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat new
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat
  ```
  Expected: all behave exactly as before.

- [ ] **Scenario 7 — empty string edge case**

  ```bash
  TERMCHAT_CONFIG_DIR=/tmp/tc termchat ""
  ```
  Expected: opens a normal empty REPL (empty string treated as `None`).

- [ ] **Final commit if any loose ends**

  ```bash
  git add -A
  git commit -m "chore: final cleanup for initial-message feature" --allow-empty
  ```
