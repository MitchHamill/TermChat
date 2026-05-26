"""Anthropic (Claude) provider."""

from __future__ import annotations

from typing import Generator

import anthropic

from termchat.core.providers.base import BaseProvider, CompletionResult


class AnthropicProvider(BaseProvider):
    """Wraps the official Anthropic Python SDK."""

    def __init__(self, *, api_key: str, model: str) -> None:
        super().__init__(api_key=api_key, model=model)
        self._client = anthropic.Anthropic(api_key=api_key)

    # ------------------------------------------------------------------
    # Non-streaming
    # ------------------------------------------------------------------

    def complete(
        self,
        messages: list[dict],
        *,
        system: str = "",
        max_tokens: int = 8096,
    ) -> CompletionResult:
        kwargs: dict = dict(
            model=self.model,
            max_tokens=max_tokens,
            messages=messages,
        )
        if system:
            kwargs["system"] = system

        response = self._client.messages.create(**kwargs)

        content = "".join(
            block.text for block in response.content if block.type == "text"
        )
        return CompletionResult(
            content=content,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
        )

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def stream(
        self,
        messages: list[dict],
        *,
        system: str = "",
        max_tokens: int = 8096,
    ) -> Generator[str, None, CompletionResult]:
        kwargs: dict = dict(
            model=self.model,
            max_tokens=max_tokens,
            messages=messages,
        )
        if system:
            kwargs["system"] = system

        collected: list[str] = []
        input_tokens = 0
        output_tokens = 0
        final_model = self.model

        with self._client.messages.stream(**kwargs) as stream_mgr:
            for chunk in stream_mgr.text_stream:
                collected.append(chunk)
                yield chunk

            # Final message has accurate usage counts
            final_msg = stream_mgr.get_final_message()
            input_tokens = final_msg.usage.input_tokens
            output_tokens = final_msg.usage.output_tokens
            final_model = final_msg.model

        return CompletionResult(
            content="".join(collected),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=final_model,
        )

    # ------------------------------------------------------------------
    # Key validation
    # ------------------------------------------------------------------

    def validate_key(self) -> bool:
        try:
            # Cheapest possible call
            self._client.messages.create(
                model=self.model,
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
            return True
        except anthropic.AuthenticationError:
            return False
        except Exception:
            # Network errors etc. — assume key is OK
            return True
