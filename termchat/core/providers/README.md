# termchat/core/providers — provider interface

This package defines the abstract provider interface and contains all concrete implementations. Adding support for a new AI backend is a matter of subclassing `BaseProvider`, implementing two methods, and registering a short name.

```
providers/
├── base.py                  ← BaseProvider ABC + CompletionResult
├── anthropic_provider.py    ← Anthropic (Claude) implementation
└── __init__.py              ← registry + get_provider() factory
```

---

## The `BaseProvider` contract

```python
from termchat.core.providers.base import BaseProvider, CompletionResult
```

### `CompletionResult`

A plain dataclass returned by both `complete()` and `stream()`:

```python
@dataclass
class CompletionResult:
    content: str        # full response text
    input_tokens: int   # tokens consumed from the context window
    output_tokens: int  # tokens generated
    model: str          # model ID actually used (may differ from requested)
```

### `BaseProvider.__init__(*, api_key, model)`

Every provider is constructed with exactly these two keyword arguments. Store them as `self.api_key` and `self.model`.

### `complete(messages, *, system="", max_tokens=8096) -> CompletionResult`

Non-streaming, synchronous completion. Used for:
- Context summarisation
- Chat key generation
- Key validation

`messages` is a list of `{"role": "user"|"assistant", "content": str}` dicts.

### `stream(messages, *, system="", max_tokens=8096) -> Generator[str, None, CompletionResult]`

A Python **generator** that:
- **Yields** `str` — each text chunk as it arrives
- **Returns** (via `StopIteration.value`) a `CompletionResult` with accurate final token counts

The caller drives the generator manually:

```python
gen = provider.stream(messages, system=system_prompt)
try:
    while True:
        chunk = next(gen)
        on_chunk(chunk)
except StopIteration as e:
    result: CompletionResult = e.value
```

### `validate_key() -> bool`

Optional override. The default always returns `True`. Implementations should make the cheapest possible API call (e.g. `max_tokens=1`) and return `False` only on an authentication error, `True` on any other exception (network errors, rate limits, etc.).

### `provider_name -> str`

Read-only property — defaults to the class name with `"provider"` stripped and lowercased. Override if the default is wrong.

---

## The registry

`providers/__init__.py` maintains a dict mapping short provider names to classes:

```python
_REGISTRY: dict[str, type[BaseProvider]] = {
    "anthropic": AnthropicProvider,
}
```

`get_provider(name, api_key, model)` looks up the class and calls its constructor:

```python
from termchat.core.providers import get_provider
prov = get_provider("anthropic", "sk-ant-…", "claude-sonnet-4-6")
```

`list_providers()` returns the registered names — used to populate `--provider` option choices.

---

## Adding a new provider

### Step 1 — Create the implementation file

`termchat/core/providers/openai_provider.py`:

```python
"""OpenAI provider for termchat."""

from __future__ import annotations

from typing import Generator

import openai

from termchat.core.providers.base import BaseProvider, CompletionResult


class OpenAIProvider(BaseProvider):

    def __init__(self, *, api_key: str, model: str) -> None:
        super().__init__(api_key=api_key, model=model)
        self._client = openai.OpenAI(api_key=api_key)

    # ── Non-streaming ─────────────────────────────────────────────────────────

    def complete(
        self,
        messages: list[dict],
        *,
        system: str = "",
        max_tokens: int = 8096,
    ) -> CompletionResult:
        if system:
            messages = [{"role": "system", "content": system}] + messages
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
        )
        choice = response.choices[0]
        return CompletionResult(
            content=choice.message.content or "",
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            model=response.model,
        )

    # ── Streaming ─────────────────────────────────────────────────────────────

    def stream(
        self,
        messages: list[dict],
        *,
        system: str = "",
        max_tokens: int = 8096,
    ) -> Generator[str, None, CompletionResult]:
        if system:
            messages = [{"role": "system", "content": system}] + messages

        collected: list[str] = []
        with self._client.chat.completions.stream(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
        ) as stream:
            for chunk in stream:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    collected.append(delta)
                    yield delta
            final = stream.get_final_completion()

        return CompletionResult(
            content="".join(collected),
            input_tokens=final.usage.prompt_tokens,
            output_tokens=final.usage.completion_tokens,
            model=final.model,
        )

    # ── Key validation ────────────────────────────────────────────────────────

    def validate_key(self) -> bool:
        try:
            self._client.chat.completions.create(
                model=self.model,
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
            return True
        except openai.AuthenticationError:
            return False
        except Exception:
            return True
```

### Step 2 — Register the provider

`termchat/core/providers/__init__.py`:

```python
from termchat.core.providers.openai_provider import OpenAIProvider

_REGISTRY: dict[str, type[BaseProvider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,          # ← add this line
}
```

### Step 3 — Add a default model (optional)

`termchat/config.py`:

```python
PROVIDER_DEFAULTS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o",               # ← add this line
}
```

### Step 4 — Configure the API key

```bash
termchat setup --provider openai
# or
export OPENAI_API_KEY="sk-…"
```

### Step 5 — Use it

```bash
termchat chat new --provider openai --model gpt-4o
```

---

## Current providers

| Name         | Class                | File                       | Models                        |
|--------------|----------------------|----------------------------|-------------------------------|
| `anthropic`  | `AnthropicProvider`  | `anthropic_provider.py`    | `claude-*` family             |

---

## Notes

- The `system` parameter maps differently per provider. Anthropic uses a top-level `system` field; OpenAI uses a `{"role": "system", ...}` message prepended to the list. Handle this translation inside your provider — the rest of the codebase always passes `system` as a keyword argument and does not know about the difference.
- Token counts must be accurate — they are stored per-message in the database and shown to the user. If your SDK does not provide streaming token counts in the final message, fall back to counting chunks or making a follow-up count call.
- `validate_key()` should never raise — catch all exceptions and return `True` if you cannot determine the key is invalid.
