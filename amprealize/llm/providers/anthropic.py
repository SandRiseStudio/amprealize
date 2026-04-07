"""Anthropic (Claude) provider — sync + async + streaming.

Ported from agent_llm_client.py (async, tool calls) and llm_provider.py
(sync, generate_stream) into a single unified provider.
"""

from __future__ import annotations

import json
import logging
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
    get_model,
)

logger = logging.getLogger(__name__)


class AnthropicProvider(Provider):
    """Anthropic Claude provider with sync, async, and streaming support."""

    def __init__(self, config: LLMConfig) -> None:
        super().__init__(config)
        self._sync_client: Any = None
        self._async_client: Any = None

    # -- Client initialisation (lazy) ----------------------------------------

    def _get_sync_client(self) -> Any:
        if self._sync_client is None:
            try:
                from anthropic import Anthropic
            except ImportError as exc:
                raise LLMError(
                    "anthropic package not installed. Run: pip install anthropic",
                    provider=self.config.provider,
                ) from exc
            kwargs: Dict[str, Any] = {"timeout": self.config.timeout}
            if self.config.api_key:
                kwargs["api_key"] = self.config.api_key
            if self.config.api_base:
                kwargs["base_url"] = self.config.api_base
            self._sync_client = Anthropic(**kwargs)
        return self._sync_client

    def _get_async_client(self) -> Any:
        if self._async_client is None:
            try:
                from anthropic import AsyncAnthropic
            except ImportError as exc:
                raise LLMError(
                    "anthropic package not installed. Run: pip install anthropic",
                    provider=self.config.provider,
                ) from exc
            kwargs: Dict[str, Any] = {"timeout": self.config.timeout}
            if self.config.api_key:
                kwargs["api_key"] = self.config.api_key
            if self.config.api_base:
                kwargs["base_url"] = self.config.api_base
            self._async_client = AsyncAnthropic(**kwargs)
        return self._async_client

    # -- Message conversion --------------------------------------------------

    @staticmethod
    def _split_system(
        messages: List[Dict[str, Any]],
    ) -> tuple[str, List[Dict[str, Any]]]:
        """Extract system content and return (system, non-system messages).

        Anthropic requires system content as a separate parameter, not in the
        messages list.
        """
        system_parts: List[str] = []
        filtered: List[Dict[str, Any]] = []
        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")
                if isinstance(content, str):
                    system_parts.append(content)
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and "text" in block:
                            system_parts.append(block["text"])
            else:
                filtered.append(msg)
        return "\n\n".join(system_parts), filtered

    @staticmethod
    def _convert_tools(tools: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
        """Convert tool schemas to Anthropic format.

        Anthropic expects: {name, description, input_schema}
        """
        if not tools:
            return None
        converted = []
        for t in tools:
            converted.append({
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "input_schema": t.get("input_schema", {"type": "object", "properties": {}}),
            })
        return converted

    # -- Build request kwargs ------------------------------------------------

    def _build_kwargs(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> Dict[str, Any]:
        system_content, api_messages = self._split_system(messages)
        kwargs: Dict[str, Any] = {
            "model": self.config.model,
            "messages": api_messages,
            "max_tokens": max_tokens or self.config.max_tokens,
        }
        if system_content:
            kwargs["system"] = system_content
        if temperature is not None:
            kwargs["temperature"] = temperature
        converted = self._convert_tools(tools)
        if converted:
            kwargs["tools"] = converted
        return kwargs

    # -- Response parsing ----------------------------------------------------

    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse an Anthropic Messages response into LLMResponse."""
        from amprealize.work_item_execution_contracts import ToolCall

        content_parts: List[str] = []
        tool_calls: list = []

        for block in response.content:
            if block.type == "text":
                content_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        call_id=block.id,
                        tool_name=block.name,
                        tool_args=block.input if isinstance(block.input, dict) else {},
                    )
                )

        input_tokens = response.usage.input_tokens if response.usage else 0
        output_tokens = response.usage.output_tokens if response.usage else 0

        return LLMResponse(
            content="".join(content_parts),
            tool_calls=tool_calls,
            model=response.model,
            provider=self.config.provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            finish_reason=response.stop_reason,
        )

    # -- Error mapping -------------------------------------------------------

    @staticmethod
    def _map_error(exc: Exception) -> LLMError:
        msg = str(exc).lower()
        if "rate_limit" in msg or "429" in msg:
            return RateLimitError(str(exc), provider=None)
        if "authentication" in msg or "401" in msg:
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
        client = self._get_sync_client()
        api_kwargs = self._build_kwargs(messages, tools, temperature, max_tokens)
        try:
            response = client.messages.create(**api_kwargs)
            return self._parse_response(response)
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
        client = self._get_sync_client()
        api_kwargs = self._build_kwargs(messages, tools, temperature, max_tokens)
        try:
            content_parts: List[str] = []
            input_tokens = 0
            output_tokens = 0
            finish_reason: Optional[str] = None
            model_used = self.config.model

            with client.messages.stream(**api_kwargs) as stream:
                for text in stream.text_stream:
                    content_parts.append(text)
                    if callback:
                        callback(text)
                final = stream.get_final_message()
                input_tokens = final.usage.input_tokens
                output_tokens = final.usage.output_tokens
                finish_reason = final.stop_reason
                model_used = final.model

            return LLMResponse(
                content="".join(content_parts),
                model=model_used,
                provider=self.config.provider,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason=finish_reason,
            )
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
        client = self._get_async_client()
        api_kwargs = self._build_kwargs(messages, tools, temperature, max_tokens)
        try:
            response = await client.messages.create(**api_kwargs)
            return self._parse_response(response)
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
        """Stream Anthropic response as StreamChunks.

        Yields TEXT_DELTA for text, TOOL_USE_START/DELTA/END for tool calls,
        and a final MESSAGE_COMPLETE with the accumulated LLMResponse.
        """
        from amprealize.work_item_execution_contracts import ToolCall

        client = self._get_async_client()
        api_kwargs = self._build_kwargs(messages, tools, temperature, max_tokens)

        try:
            content_parts: List[str] = []
            tool_calls: list = []
            current_tool_name: Optional[str] = None
            current_tool_id: Optional[str] = None
            current_tool_args = ""
            input_tokens = 0
            output_tokens = 0

            async with client.messages.stream(**api_kwargs) as stream:
                async for event in stream:
                    if event.type == "content_block_start":
                        block = event.content_block
                        if block.type == "tool_use":
                            current_tool_name = block.name
                            current_tool_id = block.id
                            current_tool_args = ""
                            yield StreamChunk(
                                type=StreamChunkType.TOOL_USE_START,
                                tool_name=block.name,
                                tool_call_id=block.id,
                            )
                    elif event.type == "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
                            content_parts.append(delta.text)
                            yield StreamChunk(
                                type=StreamChunkType.TEXT_DELTA,
                                text=delta.text,
                            )
                        elif delta.type == "input_json_delta":
                            current_tool_args += delta.partial_json
                            yield StreamChunk(
                                type=StreamChunkType.TOOL_USE_DELTA,
                                tool_args_delta=delta.partial_json,
                                tool_name=current_tool_name,
                                tool_call_id=current_tool_id,
                            )
                    elif event.type == "content_block_stop":
                        if current_tool_name:
                            try:
                                args = json.loads(current_tool_args) if current_tool_args else {}
                            except json.JSONDecodeError:
                                args = {}
                            tc = ToolCall(
                                call_id=current_tool_id or "",
                                tool_name=current_tool_name,
                                tool_args=args,
                            )
                            tool_calls.append(tc)
                            yield StreamChunk(
                                type=StreamChunkType.TOOL_USE_END,
                                tool_call=tc,
                                tool_name=current_tool_name,
                                tool_call_id=current_tool_id,
                            )
                            current_tool_name = None
                            current_tool_id = None
                            current_tool_args = ""
                    elif event.type == "message_delta":
                        if hasattr(event, "usage") and event.usage:
                            output_tokens = getattr(event.usage, "output_tokens", 0)
                    elif event.type == "message_start":
                        if hasattr(event, "message") and hasattr(event.message, "usage"):
                            input_tokens = getattr(event.message.usage, "input_tokens", 0)

                # Get final message for accurate counts
                final = stream.get_final_message()
                input_tokens = final.usage.input_tokens
                output_tokens = final.usage.output_tokens

            response = LLMResponse(
                content="".join(content_parts),
                tool_calls=tool_calls,
                model=final.model,
                provider=self.config.provider,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason=final.stop_reason,
            )
            yield StreamChunk(
                type=StreamChunkType.MESSAGE_COMPLETE,
                response=response,
            )
        except Exception as exc:
            yield StreamChunk(
                type=StreamChunkType.ERROR,
                error=str(exc),
            )

    def is_available(self) -> bool:
        import os
        return bool(self.config.api_key or os.environ.get("ANTHROPIC_API_KEY"))
