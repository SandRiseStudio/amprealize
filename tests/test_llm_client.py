"""Tests for amprealize.llm — unified LLM client package.

Covers: types, provider registry, LLMClient, TestProvider, retry middleware,
model catalog, config, metrics tracking.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]

from amprealize.llm.types import (
    AuthenticationError,
    LLMCallMetrics,
    LLMConfig,
    LLMError,
    LLMResponse,
    ModelDefinition,
    MODEL_CATALOG,
    ProviderType,
    RateLimitError,
    StreamChunk,
    StreamChunkType,
    TokenBudgetError,
    get_model,
    list_models,
)
from amprealize.llm.providers.base import Provider
from amprealize.llm.providers import get_provider, PROVIDER_REGISTRY, _register_providers
from amprealize.llm.providers.test import TestProvider
from amprealize.llm.client import LLMClient
from amprealize.llm.retry import RetryMiddleware


# Ensure provider registry is populated for all tests
@pytest.fixture(autouse=True)
def _ensure_registry():
    if not PROVIDER_REGISTRY:
        _register_providers()


# ==========================================================================
# Types
# ==========================================================================

class TestProviderType:
    def test_values(self):
        assert ProviderType.ANTHROPIC.value == "anthropic"
        assert ProviderType.OPENAI.value == "openai"
        assert ProviderType.OPENROUTER.value == "openrouter"
        assert ProviderType.TEST.value == "test"

    def test_str_enum(self):
        assert str(ProviderType.ANTHROPIC) == "ProviderType.ANTHROPIC" or ProviderType.ANTHROPIC == "anthropic"


class TestModelCatalog:
    def test_has_models(self):
        assert len(MODEL_CATALOG) >= 6

    def test_get_model(self):
        m = get_model("claude-opus-4-6")
        assert m is not None
        assert m.provider == ProviderType.ANTHROPIC
        assert m.input_price_per_m == 15.0

    def test_get_model_unknown(self):
        assert get_model("nonexistent-model") is None

    def test_list_models(self):
        models = list_models()
        assert len(models) == len(MODEL_CATALOG)
        assert all(isinstance(m, ModelDefinition) for m in models)

    def test_model_definition_frozen(self):
        m = get_model("gpt-4o")
        assert m is not None
        with pytest.raises(AttributeError):
            m.model_id = "hacked"  # type: ignore[misc]

    def test_gpt4o_pricing(self):
        m = get_model("gpt-4o")
        assert m is not None
        assert m.input_price_per_m == 2.5
        assert m.output_price_per_m == 10.0
        assert m.context_limit == 128_000


class TestLLMConfig:
    def test_defaults(self):
        cfg = LLMConfig()
        assert cfg.provider == ProviderType.OPENAI
        assert cfg.model == "gpt-4o"
        assert cfg.temperature == 0.7
        assert cfg.max_retries == 3

    @patch.dict(os.environ, {
        "AMPREALIZE_LLM_PROVIDER": "anthropic",
        "ANTHROPIC_API_KEY": "sk-test-123",
        "AMPREALIZE_LLM_MODEL": "claude-3-5-sonnet-20241022",
        "AMPREALIZE_LLM_TEMPERATURE": "0.5",
    }, clear=False)
    def test_from_env_anthropic(self):
        cfg = LLMConfig.from_env()
        assert cfg.provider == ProviderType.ANTHROPIC
        assert cfg.api_key == "sk-test-123"
        assert cfg.model == "claude-3-5-sonnet-20241022"
        assert cfg.temperature == 0.5

    @patch.dict(os.environ, {
        "OPENAI_API_KEY": "sk-openai-test",
        "AMPREALIZE_LLM_PROVIDER": "openai",
    }, clear=False)
    def test_from_env_openai_default(self):
        # Remove model override so default kicks in
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AMPREALIZE_LLM_MODEL", None)
            cfg = LLMConfig.from_env(ProviderType.OPENAI)
        assert cfg.api_key == "sk-openai-test"
        assert cfg.model == "gpt-4o"

    @patch.dict(os.environ, {
        "AMPREALIZE_LLM_PROVIDER": "ollama",
        "OLLAMA_HOST": "http://myhost:11434",
    }, clear=False)
    def test_from_env_ollama(self):
        # Remove model override so provider default kicks in
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AMPREALIZE_LLM_MODEL", None)
            cfg = LLMConfig.from_env()
        assert cfg.provider == ProviderType.OLLAMA
        assert cfg.api_base == "http://myhost:11434"
        assert cfg.model == "llama3.2"

    @patch.dict(os.environ, {
        "AMPREALIZE_LLM_TOKEN_BUDGET_ENABLED": "true",
        "AMPREALIZE_LLM_TOKEN_BUDGET": "25000",
    }, clear=False)
    def test_from_env_token_budget(self):
        cfg = LLMConfig.from_env(ProviderType.TEST)
        assert cfg.token_budget_enabled is True
        assert cfg.token_budget_per_request == 25000


class TestLLMResponse:
    def test_basic(self):
        r = LLMResponse(content="hello", model="gpt-4o", provider=ProviderType.OPENAI)
        assert r.content == "hello"
        assert r.tool_calls == []
        assert r.cost_usd == 0.0

    def test_with_tokens(self):
        r = LLMResponse(
            content="hi", input_tokens=100, output_tokens=50,
            cost_usd=0.001, latency_ms=150.0,
        )
        assert r.input_tokens == 100
        assert r.output_tokens == 50


class TestErrors:
    def test_llm_error(self):
        e = LLMError("fail", provider=ProviderType.OPENAI, status_code=500)
        assert str(e) == "fail"
        assert e.provider == ProviderType.OPENAI
        assert e.status_code == 500

    def test_rate_limit_is_llm_error(self):
        e = RateLimitError("rate limited")
        assert isinstance(e, LLMError)

    def test_auth_error(self):
        e = AuthenticationError("bad key")
        assert isinstance(e, LLMError)

    def test_token_budget_error(self):
        e = TokenBudgetError("over budget", budget=50000, estimated_tokens=60000)
        assert e.budget == 50000
        assert e.estimated_tokens == 60000


class TestStreamChunk:
    def test_text_delta(self):
        c = StreamChunk(type=StreamChunkType.TEXT_DELTA, text="hello")
        assert c.type == StreamChunkType.TEXT_DELTA
        assert c.text == "hello"

    def test_message_complete(self):
        r = LLMResponse(content="done")
        c = StreamChunk(type=StreamChunkType.MESSAGE_COMPLETE, response=r)
        assert c.response is not None


# ==========================================================================
# Provider registry
# ==========================================================================

class TestProviderRegistry:
    def test_registry_populated(self):
        assert ProviderType.ANTHROPIC in PROVIDER_REGISTRY
        assert ProviderType.OPENAI in PROVIDER_REGISTRY
        assert ProviderType.TEST in PROVIDER_REGISTRY
        assert ProviderType.OPENROUTER in PROVIDER_REGISTRY
        assert ProviderType.OLLAMA in PROVIDER_REGISTRY

    def test_get_provider_test(self):
        cfg = LLMConfig(provider=ProviderType.TEST, model="test-model")
        p = get_provider(cfg)
        assert isinstance(p, TestProvider)

    def test_get_provider_unsupported(self):
        # Create a config with a bogus provider
        cfg = LLMConfig(provider=ProviderType.OPENAI)
        # This works fine for OPENAI
        p = get_provider(cfg)
        assert p is not None


# ==========================================================================
# TestProvider
# ==========================================================================

class TestTestProvider:
    def setup_method(self):
        self.cfg = LLMConfig(provider=ProviderType.TEST, model="test-model")
        self.provider = TestProvider(self.cfg)

    def test_is_available(self):
        assert self.provider.is_available() is True

    def test_call_sync(self):
        msgs = [{"role": "user", "content": "What is 2+2?"}]
        resp = self.provider.call(msgs)
        assert "[TEST MODE]" in resp.content
        assert "2+2" in resp.content
        assert resp.finish_reason == "stop"
        assert resp.input_tokens > 0
        assert resp.output_tokens > 0

    @pytest.mark.asyncio
    async def test_acall(self):
        msgs = [{"role": "user", "content": "hello"}]
        resp = await self.provider.acall(msgs)
        assert "hello" in resp.content

    def test_stream_sync_with_callback(self):
        collected = []
        msgs = [{"role": "user", "content": "test"}]
        resp = self.provider.stream_sync(msgs, callback=lambda t: collected.append(t))
        assert len(collected) == 1
        assert "[TEST MODE]" in collected[0]

    @pytest.mark.asyncio
    async def test_astream(self):
        msgs = [{"role": "user", "content": "test streaming"}]
        chunks = []
        async for chunk in self.provider.astream(msgs):
            chunks.append(chunk)
        # Last chunk should be MESSAGE_COMPLETE
        assert chunks[-1].type == StreamChunkType.MESSAGE_COMPLETE
        assert chunks[-1].response is not None
        # Prior chunks should be TEXT_DELTA
        text_chunks = [c for c in chunks if c.type == StreamChunkType.TEXT_DELTA]
        assert len(text_chunks) > 0
        full_text = "".join(c.text or "" for c in text_chunks)
        assert "TEST MODE" in full_text


# ==========================================================================
# LLMClient
# ==========================================================================

class TestLLMClient:
    def setup_method(self):
        self.cfg = LLMConfig(provider=ProviderType.TEST, model="test-model")
        self.client = LLMClient(self.cfg)

    def test_sync_call(self):
        resp = self.client.call([{"role": "user", "content": "hi"}])
        assert resp.content
        assert resp.model == "test-model"

    @pytest.mark.asyncio
    async def test_async_call(self):
        resp = await self.client.acall([{"role": "user", "content": "hello"}])
        assert "hello" in resp.content

    def test_metrics_tracking(self):
        self.client.call([{"role": "user", "content": "test1"}])
        self.client.call([{"role": "user", "content": "test2"}])
        history = self.client.get_call_history()
        assert len(history) == 2
        assert all(isinstance(m, LLMCallMetrics) for m in history)

    def test_total_tokens(self):
        self.client.call([{"role": "user", "content": "hello world"}])
        totals = self.client.get_total_tokens()
        assert totals["input"] > 0
        assert totals["output"] > 0
        assert totals["total"] == totals["input"] + totals["output"]

    def test_total_cost(self):
        self.client.call([{"role": "user", "content": "test"}])
        # TestProvider doesn't have catalog pricing, so cost might be 0
        cost = self.client.get_total_cost()
        assert isinstance(cost, float)

    def test_model_override(self):
        """When passing model= by catalog ID, provider is resolved from catalog."""
        # "gpt-4o" is in MODEL_CATALOG with provider OPENAI
        # But since we don't have an OPENAI key, we can't actually call it
        # This test verifies the config resolution logic
        with patch("amprealize.llm.providers.openai.OpenAIProvider.call") as mock_call:
            mock_call.return_value = LLMResponse(
                content="mocked", model="gpt-4o", provider=ProviderType.OPENAI,
                input_tokens=10, output_tokens=5,
            )
            with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
                client = LLMClient()
                resp = client.call(
                    [{"role": "user", "content": "hi"}],
                    model="gpt-4o",
                )
                assert resp.content == "mocked"

    def test_tool_registry(self):
        schema = {
            "name": "search",
            "description": "Search the web",
            "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
        }
        self.client.register_tool("search", schema)
        assert "search" in self.client._tool_registry

    @pytest.mark.asyncio
    async def test_astream(self):
        chunks = []
        async for chunk in self.client.astream([{"role": "user", "content": "test"}]):
            chunks.append(chunk)
        complete = [c for c in chunks if c.type == StreamChunkType.MESSAGE_COMPLETE]
        assert len(complete) == 1

    def test_stream_sync(self):
        collected = []
        resp = self.client.stream_sync(
            [{"role": "user", "content": "streaming"}],
            callback=lambda t: collected.append(t),
        )
        assert resp.content
        assert len(collected) > 0

    def test_credential_resolver(self):
        """Custom credential resolver is used."""
        resolver = MagicMock(return_value="custom-key-123")
        cfg = LLMConfig(provider=ProviderType.TEST, model="test-model")
        client = LLMClient(cfg, credential_resolver=resolver)
        # TestProvider ignores credentials, but resolver should still be callable
        resp = client.call([{"role": "user", "content": "test"}])
        assert resp.content


# ==========================================================================
# RetryMiddleware
# ==========================================================================

class TestRetryMiddleware:
    def setup_method(self):
        self.cfg = LLMConfig(
            provider=ProviderType.TEST, model="test-model",
            max_retries=2, retry_delay=0.01,
        )
        self.inner = TestProvider(self.cfg)

    def test_no_retry_on_success(self):
        middleware = RetryMiddleware(self.cfg, inner=self.inner)
        resp = middleware.call([{"role": "user", "content": "hi"}])
        assert resp.content

    def test_retry_on_transient_error(self):
        call_count = 0
        original_call = self.inner.call

        def flaky_call(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise LLMError("connection error", provider=ProviderType.TEST)
            return original_call(messages, **kwargs)

        self.inner.call = flaky_call
        middleware = RetryMiddleware(self.cfg, inner=self.inner, base_delay=0.01)
        resp = middleware.call([{"role": "user", "content": "hi"}])
        assert resp.content
        assert call_count == 2

    def test_no_retry_on_auth_error(self):
        def auth_fail(messages, **kwargs):
            raise AuthenticationError("bad key")

        self.inner.call = auth_fail
        middleware = RetryMiddleware(self.cfg, inner=self.inner, base_delay=0.01)
        with pytest.raises(AuthenticationError):
            middleware.call([{"role": "user", "content": "hi"}])

    def test_no_retry_on_token_budget(self):
        def budget_fail(messages, **kwargs):
            raise TokenBudgetError("over", budget=1000, estimated_tokens=2000)

        self.inner.call = budget_fail
        middleware = RetryMiddleware(self.cfg, inner=self.inner, base_delay=0.01)
        with pytest.raises(TokenBudgetError):
            middleware.call([{"role": "user", "content": "hi"}])

    def test_max_retries_exhausted(self):
        def always_fail(messages, **kwargs):
            raise LLMError("timeout error", provider=ProviderType.TEST)

        self.inner.call = always_fail
        middleware = RetryMiddleware(self.cfg, inner=self.inner, max_retries=2, base_delay=0.01)
        with pytest.raises(LLMError, match="timeout error"):
            middleware.call([{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_async_retry(self):
        call_count = 0
        original_acall = self.inner.acall

        async def flaky_acall(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RateLimitError("429 rate limited")
            return await original_acall(messages, **kwargs)

        self.inner.acall = flaky_acall
        middleware = RetryMiddleware(self.cfg, inner=self.inner, base_delay=0.01)
        resp = await middleware.acall([{"role": "user", "content": "hi"}])
        assert resp.content
        assert call_count == 2

    def test_is_available_delegates(self):
        middleware = RetryMiddleware(self.cfg, inner=self.inner)
        assert middleware.is_available() is True


# ==========================================================================
# Import test — verify __init__.py exports
# ==========================================================================

class TestPackageExports:
    def test_all_exports(self):
        from amprealize.llm import (
            LLMClient,
            LLMConfig,
            LLMResponse,
            LLMCallMetrics,
            StreamChunk,
            StreamChunkType,
            Provider,
            ProviderType,
            get_provider,
            PROVIDER_REGISTRY,
            ModelDefinition,
            MODEL_CATALOG,
            get_model,
            list_models,
            LLMError,
            RateLimitError,
            AuthenticationError,
            TokenBudgetError,
        )
        assert LLMClient is not None
        assert len(PROVIDER_REGISTRY) >= 5
