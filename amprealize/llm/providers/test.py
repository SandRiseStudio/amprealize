"""Test provider — synthetic responses for dev/CI without real API keys."""

from __future__ import annotations

import time
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from amprealize.llm.providers.base import Provider
from amprealize.llm.types import (
    LLMConfig,
    LLMResponse,
    StreamChunk,
    StreamChunkType,
)


class TestProvider(Provider):
    """Returns synthetic responses — always available, no API key needed."""

    def call(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        return self._synthetic(messages)

    async def acall(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        return self._synthetic(messages)

    def stream_sync(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        callback: Optional[Callable[[str], None]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        resp = self._synthetic(messages)
        if callback:
            callback(resp.content)
        return resp

    async def astream(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        resp = self._synthetic(messages)
        # Simulate streaming by yielding word-by-word
        words = resp.content.split(" ")
        for word in words:
            yield StreamChunk(type=StreamChunkType.TEXT_DELTA, text=word + " ")
        yield StreamChunk(type=StreamChunkType.MESSAGE_COMPLETE, response=resp)

    def is_available(self) -> bool:
        return True

    def _synthetic(self, messages: List[Dict[str, Any]]) -> LLMResponse:
        user_msgs = [m.get("content", "") for m in messages if m.get("role") == "user"]
        user_query = user_msgs[-1] if user_msgs else "test query"

        content = (
            f"[TEST MODE] Query: {user_query}\n"
            f"This is a synthetic response from TestProvider. "
            f"{len(messages)} message(s) processed."
        )

        # Approximate token counts
        input_tokens = sum(len(str(m.get("content", "")).split()) for m in messages)
        output_tokens = len(content.split())

        return LLMResponse(
            content=content,
            model=self.config.model,
            provider=self.config.provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            finish_reason="stop",
        )
