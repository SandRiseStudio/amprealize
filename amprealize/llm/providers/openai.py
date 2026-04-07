"""OpenAI provider — sync + async + streaming.

Ported from agent_llm_client.py (async, tool calls) and llm_provider.py
(sync, token budget, retry) into a single unified provider.

Also serves as the base for OpenRouter, Together, Groq, Fireworks (all
OpenAI-compatible) via the api_base / extra_headers config fields.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from amprealize.llm.providers.base import Provider
from amprealize.llm.types import (
    LLMConfig,
    LLMError,
    LLMResponse,
    AuthenticationError,
    RateLimitError,
    StreamChunk,
    StreamChunkType,
    TokenBudgetError,
)

logger = logging.getLogger(__name__)


class OpenAIProvider(Provider):
    """OpenAI-compatible provider with sync, async, and streaming support.

    Supports GPT-4o, GPT-5, o1/o3 reasoning models, and any OpenAI-compatible
    API (Together, Groq, Fireworks, etc.) via config.api_base.
    """

    def __init__(self, config: LLMConfig) -> None:
        super().__init__(config)
        self._sync_client: Any = None
        self._async_client: Any = None

    # -- Client init (lazy) --------------------------------------------------

    def _get_sync_client(self) -> Any:
        if self._sync_client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise LLMError(
                    "openai package not installed. Run: pip install openai",
                    provider=self.config.provider,
                ) from exc
            kwargs: Dict[str, Any] = {"timeout": self.config.timeout, "max_retries": 0}
            if self.config.api_key:
                kwargs["api_key"] = self.config.api_key
            if self.config.api_base:
                kwargs["base_url"] = self.config.api_base
            if self.config.extra_headers:
                kwargs["default_headers"] = self.config.extra_headers
            self._sync_client = OpenAI(**kwargs)
        return self._sync_client

    def _get_async_client(self) -> Any:
        if self._async_client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:
                raise LLMError(
                    "openai package not installed. Run: pip install openai",
                    provider=self.config.provider,
                ) from exc
            kwargs: Dict[str, Any] = {"timeout": self.config.timeout, "max_retries": 0}
            if self.config.api_key:
                kwargs["api_key"] = self.config.api_key
            if self.config.api_base:
                kwargs["base_url"] = self.config.api_base
            if self.config.extra_headers:
                kwargs["default_headers"] = self.config.extra_headers
            self._async_client = AsyncOpenAI(**kwargs)
        return self._async_client

    # -- Token budget --------------------------------------------------------

    def _check_token_budget(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: int,
    ) -> None:
        """Raise TokenBudgetError if estimated usage exceeds budget."""
        if not self.config.token_budget_enabled:
            return
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        estimated_input = int(total_chars / 3.5) + len(messages) * 4
        estimated_total = estimated_input + max_tokens
        budget = self.config.token_budget_per_request
        if estimated_total > budget:
            raise TokenBudgetError(
                f"Estimated tokens ({estimated_total:,}) exceeds budget ({budget:,})",
                budget=budget,
                estimated_tokens=estimated_total,
                provider=self.config.provider,
            )

    # -- Build request kwargs ------------------------------------------------

    def _build_kwargs(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> Dict[str, Any]:
        model = self.config.model
        mt = max_tokens or self.config.max_tokens
        is_reasoning = model.startswith(("o1", "o3"))

        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        # o1/o3 use max_completion_tokens, not max_tokens
        if is_reasoning:
            kwargs["max_completion_tokens"] = mt
        else:
            kwargs["max_tokens"] = mt
            kwargs["temperature"] = temperature if temperature is not None else self.config.temperature

        if tools:
            oai_tools = []
            for t in tools:
                oai_tools.append({
                    "type": "function",
                    "function": {
                        "name": t.get("name", ""),
                        "description": t.get("description", ""),
                        "parameters": t.get("input_schema", {"type": "object"}),
                    },
                })
            kwargs["tools"] = oai_tools

        return kwargs

    # -- Response parsing ----------------------------------------------------

    def _parse_response(self, response: Any) -> LLMResponse:
        from amprealize.work_item_execution_contracts import ToolCall

        choice = response.choices[0]
        message = choice.message
        content = message.content or ""
        tool_calls: list = []

        if message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append(
                    ToolCall(
                        call_id=tc.id,
                        tool_name=tc.function.name,
                        tool_args=json.loads(tc.function.arguments) if tc.function.arguments else {},
                    )
                )

        input_tokens = response.usage.prompt_tokens if response.usage else 0
        output_tokens = response.usage.completion_tokens if response.usage else 0

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            model=response.model,
            provider=self.config.provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            finish_reason=choice.finish_reason,
        )

    # -- Error mapping -------------------------------------------------------

    @staticmethod
    def _map_error(exc: Exception) -> LLMError:
        msg = str(exc).lower()
        if "rate_limit" in msg or "429" in msg:
            return RateLimitError(str(exc), provider=None)
        if "authentication" in msg or "401" in msg or "invalid_api_key" in msg:
            return AuthenticationError(str(exc), provider=None)
        return LLMError(str(exc), provider=None)

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
        self._check_token_budget(messages, max_tokens or self.config.max_tokens)
        client = self._get_sync_client()
        api_kwargs = self._build_kwargs(messages, tools, temperature, max_tokens)
        try:
            response = client.chat.completions.create(**api_kwargs)
            return self._parse_response(response)
        except (TokenBudgetError, RateLimitError, AuthenticationError):
            raise
        except Exception as exc:
            raise self._map_error(exc) from exc

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
        self._check_token_budget(messages, max_tokens or self.config.max_tokens)
        client = self._get_sync_client()
        api_kwargs = self._build_kwargs(messages, tools, temperature, max_tokens)
        api_kwargs["stream"] = True
        api_kwargs["stream_options"] = {"include_usage": True}

        try:
            content_parts: List[str] = []
            input_tokens = 0
            output_tokens = 0
            finish_reason: Optional[str] = None
            model_used = self.config.model

            stream = client.chat.completions.create(**api_kwargs)
            for chunk in stream:
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        content_parts.append(delta.content)
                        if callback:
                            callback(delta.content)
                    if chunk.choices[0].finish_reason:
                        finish_reason = chunk.choices[0].finish_reason
                if chunk.model:
                    model_used = chunk.model
                if chunk.usage:
                    input_tokens = chunk.usage.prompt_tokens or 0
                    output_tokens = chunk.usage.completion_tokens or 0

            return LLMResponse(
                content="".join(content_parts),
                model=model_used,
                provider=self.config.provider,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason=finish_reason,
            )
        except (TokenBudgetError, RateLimitError, AuthenticationError):
            raise
        except Exception as exc:
            raise self._map_error(exc) from exc

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
        self._check_token_budget(messages, max_tokens or self.config.max_tokens)
        client = self._get_async_client()
        api_kwargs = self._build_kwargs(messages, tools, temperature, max_tokens)
        try:
            response = await client.chat.completions.create(**api_kwargs)
            return self._parse_response(response)
        except (TokenBudgetError, RateLimitError, AuthenticationError):
            raise
        except Exception as exc:
            raise self._map_error(exc) from exc

    async def astream(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Stream OpenAI response as StreamChunks."""
        from amprealize.work_item_execution_contracts import ToolCall

        self._check_token_budget(messages, max_tokens or self.config.max_tokens)
        client = self._get_async_client()
        api_kwargs = self._build_kwargs(messages, tools, temperature, max_tokens)
        api_kwargs["stream"] = True
        api_kwargs["stream_options"] = {"include_usage": True}

        try:
            content_parts: List[str] = []
            # Track in-progress tool calls by index
            tool_builders: Dict[int, Dict[str, Any]] = {}
            tool_calls: list = []
            input_tokens = 0
            output_tokens = 0
            finish_reason: Optional[str] = None
            model_used = self.config.model

            stream = await client.chat.completions.create(**api_kwargs)
            async for chunk in stream:
                if chunk.model:
                    model_used = chunk.model

                if chunk.choices:
                    choice = chunk.choices[0]
                    delta = choice.delta

                    # Text content
                    if delta and delta.content:
                        content_parts.append(delta.content)
                        yield StreamChunk(
                            type=StreamChunkType.TEXT_DELTA,
                            text=delta.content,
                        )

                    # Tool calls (streamed incrementally)
                    if delta and delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index
                            if idx not in tool_builders:
                                tool_builders[idx] = {
                                    "id": tc_delta.id or "",
                                    "name": "",
                                    "args": "",
                                }
                            builder = tool_builders[idx]
                            if tc_delta.id:
                                builder["id"] = tc_delta.id
                            if tc_delta.function:
                                if tc_delta.function.name:
                                    builder["name"] = tc_delta.function.name
                                    yield StreamChunk(
                                        type=StreamChunkType.TOOL_USE_START,
                                        tool_name=builder["name"],
                                        tool_call_id=builder["id"],
                                    )
                                if tc_delta.function.arguments:
                                    builder["args"] += tc_delta.function.arguments
                                    yield StreamChunk(
                                        type=StreamChunkType.TOOL_USE_DELTA,
                                        tool_args_delta=tc_delta.function.arguments,
                                        tool_name=builder["name"],
                                        tool_call_id=builder["id"],
                                    )

                    if choice.finish_reason:
                        finish_reason = choice.finish_reason

                if chunk.usage:
                    input_tokens = chunk.usage.prompt_tokens or 0
                    output_tokens = chunk.usage.completion_tokens or 0

            # Finalize tool calls
            for builder in tool_builders.values():
                try:
                    args = json.loads(builder["args"]) if builder["args"] else {}
                except json.JSONDecodeError:
                    args = {}
                tc = ToolCall(
                    call_id=builder["id"],
                    tool_name=builder["name"],
                    tool_args=args,
                )
                tool_calls.append(tc)
                yield StreamChunk(
                    type=StreamChunkType.TOOL_USE_END,
                    tool_call=tc,
                    tool_name=builder["name"],
                    tool_call_id=builder["id"],
                )

            response = LLMResponse(
                content="".join(content_parts),
                tool_calls=tool_calls,
                model=model_used,
                provider=self.config.provider,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason=finish_reason,
            )
            yield StreamChunk(
                type=StreamChunkType.MESSAGE_COMPLETE,
                response=response,
            )
        except (TokenBudgetError, RateLimitError, AuthenticationError):
            raise
        except Exception as exc:
            yield StreamChunk(
                type=StreamChunkType.ERROR,
                error=str(exc),
            )

    def is_available(self) -> bool:
        return bool(self.config.api_key or os.environ.get("OPENAI_API_KEY"))
