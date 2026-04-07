"""Unified LLM client with sync + async + streaming + metrics.

Provides a single entry point for all LLM calls across the platform.
Handles credential resolution, provider instantiation, cost tracking,
and token accounting.
"""

from __future__ import annotations

import logging
import math
import os
import time
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from amprealize.llm.types import (
    LLMCallMetrics,
    LLMConfig,
    LLMResponse,
    ModelDefinition,
    MODEL_CATALOG,
    ProviderType,
    StreamChunk,
    get_model,
)
from amprealize.llm.providers import get_provider
from amprealize.llm.providers.base import Provider

logger = logging.getLogger(__name__)


class LLMClient:
    """Unified LLM client for all provider interactions.

    Supports sync (call, stream_sync) and async (acall, astream) modes.
    Tracks cost, tokens, and call history across all calls in a session.
    """

    def __init__(
        self,
        config: Optional[LLMConfig] = None,
        *,
        credential_resolver: Optional[Callable[..., Optional[str]]] = None,
        tool_registry: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Args:
            config: Default LLMConfig. If None, resolved from env at first call.
            credential_resolver: Optional function(provider_name, project_id?, org_id?) -> api_key.
                Falls back to env vars if not provided.
            tool_registry: Dict mapping tool names to their JSON schemas.
        """
        self._default_config = config
        self._credential_resolver = credential_resolver or self._default_credential_resolver
        self._tool_registry = tool_registry or {}
        # Cache of provider instances keyed by (provider_type, api_base)
        self._providers: Dict[str, Provider] = {}
        self._call_history: List[LLMCallMetrics] = []

    # -- Public: sync --------------------------------------------------------

    def call(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[str]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        config: Optional[LLMConfig] = None,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> LLMResponse:
        """Synchronous LLM call."""
        cfg = self._resolve_config(config, model, project_id, org_id)
        provider = self._get_provider(cfg)
        tool_schemas = self._build_tool_schemas(tools) if tools else None

        start = time.perf_counter()
        response = provider.call(
            messages,
            tools=tool_schemas,
            temperature=temperature if temperature is not None else cfg.temperature,
            max_tokens=max_tokens or cfg.max_tokens,
        )
        latency_ms = (time.perf_counter() - start) * 1000

        self._finalize_response(response, cfg, latency_ms)
        return response

    def stream_sync(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[str]] = None,
        model: Optional[str] = None,
        callback: Optional[Callable[[str], None]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        config: Optional[LLMConfig] = None,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> LLMResponse:
        """Synchronous streaming call with optional text callback."""
        cfg = self._resolve_config(config, model, project_id, org_id)
        provider = self._get_provider(cfg)
        tool_schemas = self._build_tool_schemas(tools) if tools else None

        start = time.perf_counter()
        response = provider.stream_sync(
            messages,
            tools=tool_schemas,
            callback=callback,
            temperature=temperature if temperature is not None else cfg.temperature,
            max_tokens=max_tokens or cfg.max_tokens,
        )
        latency_ms = (time.perf_counter() - start) * 1000

        self._finalize_response(response, cfg, latency_ms)
        return response

    # -- Public: async -------------------------------------------------------

    async def acall(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[str]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        config: Optional[LLMConfig] = None,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> LLMResponse:
        """Asynchronous LLM call."""
        cfg = self._resolve_config(config, model, project_id, org_id)
        provider = self._get_provider(cfg)
        tool_schemas = self._build_tool_schemas(tools) if tools else None

        start = time.perf_counter()
        response = await provider.acall(
            messages,
            tools=tool_schemas,
            temperature=temperature if temperature is not None else cfg.temperature,
            max_tokens=max_tokens or cfg.max_tokens,
        )
        latency_ms = (time.perf_counter() - start) * 1000

        self._finalize_response(response, cfg, latency_ms)
        return response

    async def astream(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[str]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        config: Optional[LLMConfig] = None,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> AsyncIterator[StreamChunk]:
        """Asynchronous streaming call yielding StreamChunks."""
        cfg = self._resolve_config(config, model, project_id, org_id)
        provider = self._get_provider(cfg)
        tool_schemas = self._build_tool_schemas(tools) if tools else None

        start = time.perf_counter()
        async for chunk in provider.astream(
            messages,
            tools=tool_schemas,
            temperature=temperature if temperature is not None else cfg.temperature,
            max_tokens=max_tokens or cfg.max_tokens,
        ):
            # Track the final response if present
            if chunk.response is not None:
                latency_ms = (time.perf_counter() - start) * 1000
                self._finalize_response(chunk.response, cfg, latency_ms)
            yield chunk

    # -- Metrics -------------------------------------------------------------

    def get_total_cost(self) -> float:
        """Total cost (USD) of all calls in this session."""
        return sum(m.cost_usd for m in self._call_history)

    def get_total_tokens(self) -> Dict[str, int]:
        """Total tokens used in this session."""
        return {
            "input": sum(m.input_tokens for m in self._call_history),
            "output": sum(m.output_tokens for m in self._call_history),
            "total": sum(m.input_tokens + m.output_tokens for m in self._call_history),
        }

    def get_call_history(self) -> List[LLMCallMetrics]:
        """Return a copy of the call history."""
        return list(self._call_history)

    # -- Tool registry -------------------------------------------------------

    def register_tool(self, name: str, schema: Dict[str, Any]) -> None:
        self._tool_registry[name] = schema

    def register_tools(self, tools: Dict[str, Any]) -> None:
        self._tool_registry.update(tools)

    # -- Internal ------------------------------------------------------------

    def _resolve_config(
        self,
        override: Optional[LLMConfig],
        model: Optional[str],
        project_id: Optional[str],
        org_id: Optional[str],
    ) -> LLMConfig:
        """Merge override config, model, and credentials into a final config."""
        cfg = override or self._default_config or LLMConfig.from_env()

        # If a model was specified, look it up in the catalog to set provider
        if model:
            model_def = get_model(model)
            if model_def:
                cfg = LLMConfig(
                    provider=model_def.provider,
                    model=model_def.api_name,
                    api_key=cfg.api_key,
                    api_base=cfg.api_base,
                    max_tokens=cfg.max_tokens,
                    temperature=cfg.temperature,
                    timeout=cfg.timeout,
                    max_retries=cfg.max_retries,
                    retry_delay=cfg.retry_delay,
                    extra_headers=cfg.extra_headers,
                    token_budget_enabled=cfg.token_budget_enabled,
                    token_budget_per_request=cfg.token_budget_per_request,
                )

        # Resolve credential if not already set
        if not cfg.api_key and cfg.provider != ProviderType.TEST:
            key = self._resolve_credential(cfg.provider.value, project_id, org_id)
            if key:
                cfg = LLMConfig(
                    provider=cfg.provider,
                    model=cfg.model,
                    api_key=key,
                    api_base=cfg.api_base,
                    max_tokens=cfg.max_tokens,
                    temperature=cfg.temperature,
                    timeout=cfg.timeout,
                    max_retries=cfg.max_retries,
                    retry_delay=cfg.retry_delay,
                    extra_headers=cfg.extra_headers,
                    token_budget_enabled=cfg.token_budget_enabled,
                    token_budget_per_request=cfg.token_budget_per_request,
                )

        return cfg

    def _resolve_credential(
        self,
        provider_name: str,
        project_id: Optional[str],
        org_id: Optional[str],
    ) -> Optional[str]:
        """Try the credential resolver, adapting to its arity."""
        try:
            import inspect
            sig = inspect.signature(self._credential_resolver)
            param_count = len(sig.parameters)
            if param_count >= 3:
                return self._credential_resolver(provider_name, project_id, org_id)
            else:
                return self._credential_resolver(provider_name)
        except Exception:
            return self._credential_resolver(provider_name)

    @staticmethod
    def _default_credential_resolver(provider: str) -> Optional[str]:
        env_vars = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "together": "TOGETHER_API_KEY",
            "groq": "GROQ_API_KEY",
            "fireworks": "FIREWORKS_API_KEY",
        }
        env_var = env_vars.get(provider)
        return os.getenv(env_var) if env_var else None

    def _get_provider(self, cfg: LLMConfig) -> Provider:
        """Get or create a cached provider for the given config."""
        cache_key = f"{cfg.provider.value}:{cfg.api_base or ''}:{cfg.api_key or ''}"
        if cache_key not in self._providers:
            self._providers[cache_key] = get_provider(cfg)
        return self._providers[cache_key]

    def _build_tool_schemas(self, tool_names: List[str]) -> List[Dict[str, Any]]:
        """Resolve tool names to their JSON Schema definitions from the registry."""
        schemas = []
        for name in tool_names:
            if name in self._tool_registry:
                schemas.append(self._tool_registry[name])
            else:
                # Minimal fallback schema
                schemas.append({
                    "name": name,
                    "description": f"Execute {name} tool",
                    "input_schema": {"type": "object", "properties": {}},
                })
        return schemas

    def _finalize_response(
        self,
        response: LLMResponse,
        cfg: LLMConfig,
        latency_ms: float,
    ) -> None:
        """Fill in latency, cost, and record metrics."""
        if response.latency_ms == 0:
            response.latency_ms = latency_ms

        # Back-fill cost from model catalog if provider didn't set it
        if response.cost_usd == 0 and (response.input_tokens or response.output_tokens):
            model_def = self._find_model_def(cfg.model)
            if model_def:
                response.cost_usd = (
                    (response.input_tokens / 1_000_000) * model_def.input_price_per_m
                    + (response.output_tokens / 1_000_000) * model_def.output_price_per_m
                )

        if not response.model:
            response.model = cfg.model
        if response.provider == ProviderType.OPENAI and cfg.provider != ProviderType.OPENAI:
            response.provider = cfg.provider

        # Estimate tokens if provider returned 0
        if response.input_tokens == 0 and response.output_tokens == 0:
            response.input_tokens = self._estimate_tokens_from_messages(messages=[])
            response.output_tokens = max(1, math.ceil(len(response.content) / 4))

        self._call_history.append(
            LLMCallMetrics(
                model_id=response.model,
                provider=cfg.provider,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                latency_ms=response.latency_ms,
                cost_usd=response.cost_usd,
            )
        )

    @staticmethod
    def _find_model_def(api_name: str) -> Optional[ModelDefinition]:
        """Find a ModelDefinition by api_name or model_id."""
        # Direct lookup by model_id
        if api_name in MODEL_CATALOG:
            return MODEL_CATALOG[api_name]
        # Search by api_name field
        for m in MODEL_CATALOG.values():
            if m.api_name == api_name:
                return m
        return None

    @staticmethod
    def _estimate_tokens_from_messages(messages: List[Dict[str, Any]]) -> int:
        if not messages:
            return 0
        total_chars = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and "text" in block:
                        total_chars += len(block["text"])
        return max(1, math.ceil(total_chars / 4))
