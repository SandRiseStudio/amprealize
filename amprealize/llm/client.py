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
from typing import Any, AsyncIterator, Callable, Dict, List, Mapping, Optional

from amprealize.execution_observability import sanitize_observability_payload
from amprealize.llm.types import (
    LLMCallMetrics,
    LLMConfig,
    LLMResponse,
    ModelDefinition,
    MODEL_CATALOG,
    ProviderType,
    StreamChunk,
    get_model,
    get_provider_base_url,
    get_provider_key_env,
)
from amprealize.llm.providers import get_provider
from amprealize.llm.providers.base import Provider
from amprealize.telemetry import TelemetryClient

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
        telemetry: Optional[TelemetryClient] = None,
    ) -> None:
        """
        Args:
            config: Default LLMConfig. If None, resolved from env at first call.
            credential_resolver: Optional function(provider_name, project_id?, org_id?) -> api_key.
                Falls back to env vars if not provided.
            tool_registry: Dict mapping tool names to their JSON schemas.
            telemetry: Optional telemetry client for LLM generation observability.
        """
        self._default_config = config
        self._credential_resolver = credential_resolver or self._default_credential_resolver
        self._tool_registry = tool_registry or {}
        self._telemetry = telemetry or TelemetryClient.noop()
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
        user_id: Optional[str] = None,
        prefer_user_credential: bool = False,
        execution_observability: Optional[Mapping[str, Any]] = None,
        actor: Optional[Dict[str, str]] = None,
    ) -> LLMResponse:
        """Synchronous LLM call."""
        cfg = self._resolve_config(
            config,
            model,
            project_id,
            org_id,
            user_id,
            prefer_user_credential,
        )
        provider = self._get_provider(cfg)
        tool_schemas = self._build_tool_schemas(tools) if tools else None
        credential_scope = self._credential_scope(project_id, org_id, user_id, prefer_user_credential)

        start = time.perf_counter()
        try:
            response = provider.call(
                messages,
                tools=tool_schemas,
                temperature=temperature if temperature is not None else cfg.temperature,
                max_tokens=max_tokens or cfg.max_tokens,
            )
            latency_ms = (time.perf_counter() - start) * 1000

            self._finalize_response(response, cfg, latency_ms)
            self._emit_generation_completed(
                response=response,
                cfg=cfg,
                operation="call",
                is_streaming=False,
                first_token_latency_ms=None,
                tool_schema_count=len(tool_schemas or []),
                credential_scope=credential_scope,
                execution_observability=execution_observability,
                actor=actor,
            )
            return response
        except Exception as exc:
            self._emit_generation_failed(
                error=exc,
                cfg=cfg,
                operation="call",
                is_streaming=False,
                latency_ms=(time.perf_counter() - start) * 1000,
                first_token_latency_ms=None,
                tool_schema_count=len(tool_schemas or []),
                credential_scope=credential_scope,
                execution_observability=execution_observability,
                actor=actor,
            )
            raise

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
        user_id: Optional[str] = None,
        prefer_user_credential: bool = False,
        execution_observability: Optional[Mapping[str, Any]] = None,
        actor: Optional[Dict[str, str]] = None,
    ) -> LLMResponse:
        """Synchronous streaming call with optional text callback."""
        cfg = self._resolve_config(
            config,
            model,
            project_id,
            org_id,
            user_id,
            prefer_user_credential,
        )
        provider = self._get_provider(cfg)
        tool_schemas = self._build_tool_schemas(tools) if tools else None
        credential_scope = self._credential_scope(project_id, org_id, user_id, prefer_user_credential)

        start = time.perf_counter()
        first_token_latency_ms: Optional[float] = None

        def observed_callback(text: str) -> None:
            nonlocal first_token_latency_ms
            if first_token_latency_ms is None and text:
                first_token_latency_ms = (time.perf_counter() - start) * 1000
            if callback:
                callback(text)

        try:
            response = provider.stream_sync(
                messages,
                tools=tool_schemas,
                callback=observed_callback,
                temperature=temperature if temperature is not None else cfg.temperature,
                max_tokens=max_tokens or cfg.max_tokens,
            )
            latency_ms = (time.perf_counter() - start) * 1000

            self._finalize_response(response, cfg, latency_ms)
            self._emit_generation_completed(
                response=response,
                cfg=cfg,
                operation="stream_sync",
                is_streaming=True,
                first_token_latency_ms=first_token_latency_ms,
                tool_schema_count=len(tool_schemas or []),
                credential_scope=credential_scope,
                execution_observability=execution_observability,
                actor=actor,
            )
            return response
        except Exception as exc:
            self._emit_generation_failed(
                error=exc,
                cfg=cfg,
                operation="stream_sync",
                is_streaming=True,
                latency_ms=(time.perf_counter() - start) * 1000,
                first_token_latency_ms=first_token_latency_ms,
                tool_schema_count=len(tool_schemas or []),
                credential_scope=credential_scope,
                execution_observability=execution_observability,
                actor=actor,
            )
            raise

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
        user_id: Optional[str] = None,
        prefer_user_credential: bool = False,
        execution_observability: Optional[Mapping[str, Any]] = None,
        actor: Optional[Dict[str, str]] = None,
    ) -> LLMResponse:
        """Asynchronous LLM call."""
        cfg = self._resolve_config(
            config,
            model,
            project_id,
            org_id,
            user_id,
            prefer_user_credential,
        )
        provider = self._get_provider(cfg)
        tool_schemas = self._build_tool_schemas(tools) if tools else None
        credential_scope = self._credential_scope(project_id, org_id, user_id, prefer_user_credential)

        start = time.perf_counter()
        try:
            response = await provider.acall(
                messages,
                tools=tool_schemas,
                temperature=temperature if temperature is not None else cfg.temperature,
                max_tokens=max_tokens or cfg.max_tokens,
            )
            latency_ms = (time.perf_counter() - start) * 1000

            self._finalize_response(response, cfg, latency_ms)
            self._emit_generation_completed(
                response=response,
                cfg=cfg,
                operation="acall",
                is_streaming=False,
                first_token_latency_ms=None,
                tool_schema_count=len(tool_schemas or []),
                credential_scope=credential_scope,
                execution_observability=execution_observability,
                actor=actor,
            )
            return response
        except Exception as exc:
            self._emit_generation_failed(
                error=exc,
                cfg=cfg,
                operation="acall",
                is_streaming=False,
                latency_ms=(time.perf_counter() - start) * 1000,
                first_token_latency_ms=None,
                tool_schema_count=len(tool_schemas or []),
                credential_scope=credential_scope,
                execution_observability=execution_observability,
                actor=actor,
            )
            raise

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
        user_id: Optional[str] = None,
        prefer_user_credential: bool = False,
        execution_observability: Optional[Mapping[str, Any]] = None,
        actor: Optional[Dict[str, str]] = None,
    ) -> AsyncIterator[StreamChunk]:
        """Asynchronous streaming call yielding StreamChunks."""
        cfg = self._resolve_config(
            config,
            model,
            project_id,
            org_id,
            user_id,
            prefer_user_credential,
        )
        provider = self._get_provider(cfg)
        tool_schemas = self._build_tool_schemas(tools) if tools else None
        credential_scope = self._credential_scope(project_id, org_id, user_id, prefer_user_credential)

        start = time.perf_counter()
        first_token_latency_ms: Optional[float] = None
        try:
            async for chunk in provider.astream(
                messages,
                tools=tool_schemas,
                temperature=temperature if temperature is not None else cfg.temperature,
                max_tokens=max_tokens or cfg.max_tokens,
            ):
                if first_token_latency_ms is None and (
                    chunk.text or chunk.reasoning or chunk.tool_args_delta
                ):
                    first_token_latency_ms = (time.perf_counter() - start) * 1000
                # Track the final response if present
                if chunk.response is not None:
                    latency_ms = (time.perf_counter() - start) * 1000
                    self._finalize_response(chunk.response, cfg, latency_ms)
                    self._emit_generation_completed(
                        response=chunk.response,
                        cfg=cfg,
                        operation="astream",
                        is_streaming=True,
                        first_token_latency_ms=first_token_latency_ms,
                        tool_schema_count=len(tool_schemas or []),
                        credential_scope=credential_scope,
                        execution_observability=execution_observability,
                        actor=actor,
                    )
                yield chunk
        except Exception as exc:
            self._emit_generation_failed(
                error=exc,
                cfg=cfg,
                operation="astream",
                is_streaming=True,
                latency_ms=(time.perf_counter() - start) * 1000,
                first_token_latency_ms=first_token_latency_ms,
                tool_schema_count=len(tool_schemas or []),
                credential_scope=credential_scope,
                execution_observability=execution_observability,
                actor=actor,
            )
            raise

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
        user_id: Optional[str],
        prefer_user_credential: bool,
    ) -> LLMConfig:
        """Merge override config, model, and credentials into a final config."""
        cfg = override or self._default_config or LLMConfig.from_env()

        # If a model was specified, look it up in the catalog to set provider
        if model:
            model_def = get_model(model)
            if model_def:
                provider_changed = model_def.provider != cfg.provider
                cfg = LLMConfig(
                    provider=model_def.provider,
                    model=model_def.api_name,
                    api_key=None if provider_changed else cfg.api_key,
                    api_base=model_def.provider_base_url or get_provider_base_url(model_def.provider),
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
            key = self._resolve_credential(
                cfg.provider.value,
                project_id,
                org_id,
                user_id,
                prefer_user_credential,
            )
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
        user_id: Optional[str],
        prefer_user_credential: bool,
    ) -> Optional[str]:
        """Try the credential resolver, adapting to its arity."""
        try:
            import inspect
            sig = inspect.signature(self._credential_resolver)
            param_count = len(sig.parameters)
            if param_count >= 5:
                return self._credential_resolver(
                    provider_name,
                    project_id,
                    org_id,
                    user_id,
                    prefer_user_credential,
                )
            if param_count == 4:
                return self._credential_resolver(provider_name, project_id, org_id, user_id)
            if param_count >= 3:
                return self._credential_resolver(provider_name, project_id, org_id)
            return self._credential_resolver(provider_name)
        except Exception:
            return self._credential_resolver(provider_name)

    @staticmethod
    def _default_credential_resolver(provider: str) -> Optional[str]:
        env_vars = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "nvidia": "NVIDIA_API_KEY",
            "together": "TOGETHER_API_KEY",
            "groq": "GROQ_API_KEY",
            "fireworks": "FIREWORKS_API_KEY",
        }
        env_var = env_vars.get(provider)
        if not env_var and provider in ProviderType._value2member_map_:
            env_var = get_provider_key_env(ProviderType(provider))
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

    def _emit_generation_completed(
        self,
        *,
        response: LLMResponse,
        cfg: LLMConfig,
        operation: str,
        is_streaming: bool,
        first_token_latency_ms: Optional[float],
        tool_schema_count: int,
        credential_scope: str,
        execution_observability: Optional[Mapping[str, Any]],
        actor: Optional[Dict[str, str]],
    ) -> None:
        payload: Dict[str, Any] = {
            "operation": operation,
            "status": "completed",
            "provider": cfg.provider.value,
            "model_id": response.model or cfg.model,
            "latency_ms": response.latency_ms,
            "first_token_latency_ms": first_token_latency_ms,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "total_tokens": response.input_tokens + response.output_tokens,
            "cost_usd": response.cost_usd,
            "finish_reason": response.finish_reason,
            "is_streaming": is_streaming,
            "tool_schema_count": tool_schema_count,
            "credential_scope": credential_scope,
            "max_retries": cfg.max_retries,
            "output_preview": response.content[:512],
        }
        if execution_observability:
            payload["execution_observability"] = dict(execution_observability)

        self._telemetry.emit_event(
            event_type="llm.generation.completed",
            payload=sanitize_observability_payload(payload),
            actor=actor,
            run_id=_context_value(execution_observability, "run_id"),
            session_id=_context_value(execution_observability, "conversation_id"),
        )

    def _emit_generation_failed(
        self,
        *,
        error: Exception,
        cfg: LLMConfig,
        operation: str,
        is_streaming: bool,
        latency_ms: float,
        first_token_latency_ms: Optional[float],
        tool_schema_count: int,
        credential_scope: str,
        execution_observability: Optional[Mapping[str, Any]],
        actor: Optional[Dict[str, str]],
    ) -> None:
        payload: Dict[str, Any] = {
            "operation": operation,
            "status": "failed",
            "provider": cfg.provider.value,
            "model_id": cfg.model,
            "latency_ms": latency_ms,
            "first_token_latency_ms": first_token_latency_ms,
            "is_streaming": is_streaming,
            "tool_schema_count": tool_schema_count,
            "credential_scope": credential_scope,
            "max_retries": cfg.max_retries,
            "error": str(error),
            "error_class": error.__class__.__name__,
            "provider_status_code": getattr(error, "status_code", None),
        }
        if execution_observability:
            payload["execution_observability"] = dict(execution_observability)

        self._telemetry.emit_event(
            event_type="llm.generation.failed",
            payload=sanitize_observability_payload(payload),
            actor=actor,
            run_id=_context_value(execution_observability, "run_id"),
            session_id=_context_value(execution_observability, "conversation_id"),
        )

    @staticmethod
    def _credential_scope(
        project_id: Optional[str],
        org_id: Optional[str],
        user_id: Optional[str],
        prefer_user_credential: bool,
    ) -> str:
        if prefer_user_credential and user_id:
            return "user"
        if project_id:
            return "project"
        if org_id:
            return "org"
        return "environment"

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


def _context_value(
    execution_observability: Optional[Mapping[str, Any]],
    key: str,
) -> Optional[str]:
    if not execution_observability:
        return None
    value = execution_observability.get(key)
    return str(value) if value is not None else None
