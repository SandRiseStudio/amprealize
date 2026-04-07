"""Retry middleware — wraps any Provider with exponential backoff.

Retries on transient errors (429, 500, 502, 503, timeouts).
Does NOT retry on authentication errors or token budget errors.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from amprealize.llm.providers.base import Provider
from amprealize.llm.types import (
    AuthenticationError,
    LLMConfig,
    LLMError,
    LLMResponse,
    RateLimitError,
    StreamChunk,
    TokenBudgetError,
)

logger = logging.getLogger(__name__)

# Errors that should NOT be retried
_NO_RETRY_TYPES = (AuthenticationError, TokenBudgetError)


class RetryMiddleware(Provider):
    """Wraps a Provider with retry logic and exponential backoff.

    Usage:
        provider = get_provider(config)
        provider_with_retry = RetryMiddleware(config, inner=provider)
    """

    def __init__(
        self,
        config: LLMConfig,
        *,
        inner: Provider,
        max_retries: Optional[int] = None,
        base_delay: Optional[float] = None,
        max_delay: float = 60.0,
    ) -> None:
        super().__init__(config)
        self._inner = inner
        self._max_retries = max_retries if max_retries is not None else config.max_retries
        self._base_delay = base_delay if base_delay is not None else config.retry_delay
        self._max_delay = max_delay

    def _delay(self, attempt: int) -> float:
        """Exponential backoff with jitter."""
        delay = self._base_delay * (2 ** attempt) + random.uniform(0, 0.5)
        return min(delay, self._max_delay)

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        if isinstance(exc, _NO_RETRY_TYPES):
            return False
        if isinstance(exc, RateLimitError):
            return True
        msg = str(exc).lower()
        return any(kw in msg for kw in ("429", "500", "502", "503", "timeout", "connection"))

    # -- Sync ----------------------------------------------------------------

    def call(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        last_exc: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            try:
                return self._inner.call(
                    messages, tools=tools, temperature=temperature,
                    max_tokens=max_tokens, **kwargs,
                )
            except Exception as exc:
                last_exc = exc
                if not self._is_retryable(exc) or attempt == self._max_retries:
                    raise
                delay = self._delay(attempt)
                logger.warning(
                    "LLM call failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, self._max_retries + 1, delay, exc,
                )
                time.sleep(delay)
        raise last_exc  # type: ignore[misc]

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
        last_exc: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            try:
                return self._inner.stream_sync(
                    messages, tools=tools, callback=callback,
                    temperature=temperature, max_tokens=max_tokens, **kwargs,
                )
            except Exception as exc:
                last_exc = exc
                if not self._is_retryable(exc) or attempt == self._max_retries:
                    raise
                delay = self._delay(attempt)
                logger.warning(
                    "LLM stream failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, self._max_retries + 1, delay, exc,
                )
                time.sleep(delay)
        raise last_exc  # type: ignore[misc]

    # -- Async ---------------------------------------------------------------

    async def acall(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        last_exc: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            try:
                return await self._inner.acall(
                    messages, tools=tools, temperature=temperature,
                    max_tokens=max_tokens, **kwargs,
                )
            except Exception as exc:
                last_exc = exc
                if not self._is_retryable(exc) or attempt == self._max_retries:
                    raise
                delay = self._delay(attempt)
                logger.warning(
                    "LLM async call failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, self._max_retries + 1, delay, exc,
                )
                await asyncio.sleep(delay)
        raise last_exc  # type: ignore[misc]

    async def astream(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Retry the entire stream from the beginning on transient errors."""
        last_exc: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            try:
                async for chunk in self._inner.astream(
                    messages, tools=tools, temperature=temperature,
                    max_tokens=max_tokens, **kwargs,
                ):
                    yield chunk
                return  # stream completed successfully
            except Exception as exc:
                last_exc = exc
                if not self._is_retryable(exc) or attempt == self._max_retries:
                    raise
                delay = self._delay(attempt)
                logger.warning(
                    "LLM async stream failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, self._max_retries + 1, delay, exc,
                )
                await asyncio.sleep(delay)
        raise last_exc  # type: ignore[misc]

    def is_available(self) -> bool:
        return self._inner.is_available()
