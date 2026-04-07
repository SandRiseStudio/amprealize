"""Abstract base class for LLM providers.

Each provider implements sync (call, stream_sync) and async (acall, astream)
interfaces. Both Anthropic and OpenAI SDKs ship native sync + async clients,
so providers use them directly — no event loop hacks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, Dict, List, Optional

if TYPE_CHECKING:
    from amprealize.llm.types import LLMConfig, LLMResponse, StreamChunk


class Provider(ABC):
    """Abstract base for LLM providers."""

    def __init__(self, config: "LLMConfig") -> None:
        self.config = config

    # -- Sync ----------------------------------------------------------------

    @abstractmethod
    def call(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> "LLMResponse":
        """Synchronous single-shot call."""
        ...

    def stream_sync(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        callback: Optional[Callable[[str], None]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> "LLMResponse":
        """Synchronous streaming with optional text callback.

        Default implementation falls back to non-streaming call.
        """
        return self.call(
            messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

    # -- Async ---------------------------------------------------------------

    @abstractmethod
    async def acall(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> "LLMResponse":
        """Asynchronous single-shot call."""
        ...

    async def astream(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> AsyncIterator["StreamChunk"]:
        """Asynchronous streaming returning StreamChunk iterator.

        Default implementation falls back to acall and yields a single complete chunk.
        """
        from amprealize.llm.types import StreamChunk, StreamChunkType

        response = await self.acall(
            messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        yield StreamChunk(
            type=StreamChunkType.TEXT_DELTA,
            text=response.content,
        )
        yield StreamChunk(
            type=StreamChunkType.MESSAGE_COMPLETE,
            response=response,
        )

    # -- Utility -------------------------------------------------------------

    def is_available(self) -> bool:
        """Check if the provider is configured and reachable."""
        return bool(self.config.api_key)
