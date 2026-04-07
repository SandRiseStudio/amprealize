"""Core types for the unified LLM package.

Consolidates ProviderType, LLMConfig, LLMResponse, StreamChunk, ModelDefinition,
MODEL_CATALOG, and error hierarchy from the former agent_llm_client.py and
llm_provider.py into one canonical module.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# =============================================================================
# Provider enum
# =============================================================================

class ProviderType(str, Enum):
    """Unified LLM provider enum."""
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    OPENROUTER = "openrouter"
    OLLAMA = "ollama"
    TOGETHER = "together"
    GROQ = "groq"
    FIREWORKS = "fireworks"
    TEST = "test"


# =============================================================================
# Model catalog
# =============================================================================

@dataclass(frozen=True)
class ModelDefinition:
    """Definition of a model in the catalog with pricing and limits."""
    model_id: str
    api_name: str
    provider: ProviderType
    display_name: str
    context_limit: int
    max_output_tokens: int
    input_price_per_m: float   # USD per 1M input tokens
    output_price_per_m: float  # USD per 1M output tokens


MODEL_CATALOG: Dict[str, ModelDefinition] = {
    "claude-opus-4-6": ModelDefinition(
        model_id="claude-opus-4-6",
        api_name="claude-opus-4-20250918",
        provider=ProviderType.ANTHROPIC,
        display_name="Claude Opus 4.6",
        context_limit=200_000,
        max_output_tokens=32_000,
        input_price_per_m=15.0,
        output_price_per_m=75.0,
    ),
    "claude-opus-4-5": ModelDefinition(
        model_id="claude-opus-4-5",
        api_name="claude-opus-4-20250514",
        provider=ProviderType.ANTHROPIC,
        display_name="Claude Opus 4.5",
        context_limit=200_000,
        max_output_tokens=32_000,
        input_price_per_m=15.0,
        output_price_per_m=75.0,
    ),
    "claude-sonnet-4-5": ModelDefinition(
        model_id="claude-sonnet-4-5",
        api_name="claude-sonnet-4-20250514",
        provider=ProviderType.ANTHROPIC,
        display_name="Claude Sonnet 4.5",
        context_limit=200_000,
        max_output_tokens=16_000,
        input_price_per_m=3.0,
        output_price_per_m=15.0,
    ),
    "gpt-5-2": ModelDefinition(
        model_id="gpt-5-2",
        api_name="gpt-5-0802",
        provider=ProviderType.OPENAI,
        display_name="GPT-5.2",
        context_limit=200_000,
        max_output_tokens=32_000,
        input_price_per_m=10.0,
        output_price_per_m=30.0,
    ),
    "gpt-4o": ModelDefinition(
        model_id="gpt-4o",
        api_name="gpt-4o",
        provider=ProviderType.OPENAI,
        display_name="GPT-4o",
        context_limit=128_000,
        max_output_tokens=16_384,
        input_price_per_m=2.5,
        output_price_per_m=10.0,
    ),
    "claude-3-5-sonnet": ModelDefinition(
        model_id="claude-3-5-sonnet",
        api_name="claude-3-5-sonnet-20241022",
        provider=ProviderType.ANTHROPIC,
        display_name="Claude 3.5 Sonnet",
        context_limit=200_000,
        max_output_tokens=8_192,
        input_price_per_m=3.0,
        output_price_per_m=15.0,
    ),
}


def get_model(model_id: str) -> Optional[ModelDefinition]:
    """Look up a model by ID from the catalog."""
    return MODEL_CATALOG.get(model_id)


def list_models() -> List[ModelDefinition]:
    """List all models in the catalog."""
    return list(MODEL_CATALOG.values())


# =============================================================================
# Configuration
# =============================================================================

# Default models per provider
_DEFAULT_MODELS: Dict[ProviderType, str] = {
    ProviderType.OPENAI: "gpt-4o",
    ProviderType.ANTHROPIC: "claude-3-5-sonnet-20241022",
    ProviderType.OPENROUTER: "anthropic/claude-3.5-sonnet",
    ProviderType.OLLAMA: "llama3.2",
    ProviderType.TOGETHER: "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    ProviderType.GROQ: "llama-3.3-70b-versatile",
    ProviderType.FIREWORKS: "accounts/fireworks/models/llama-v3p3-70b-instruct",
    ProviderType.TEST: "test-model",
}

# Provider-specific env var names for API keys
_KEY_ENV_MAP: Dict[ProviderType, str] = {
    ProviderType.OPENAI: "OPENAI_API_KEY",
    ProviderType.ANTHROPIC: "ANTHROPIC_API_KEY",
    ProviderType.OPENROUTER: "OPENROUTER_API_KEY",
    ProviderType.TOGETHER: "TOGETHER_API_KEY",
    ProviderType.GROQ: "GROQ_API_KEY",
    ProviderType.FIREWORKS: "FIREWORKS_API_KEY",
}

# Provider-specific base URLs
_BASE_URL_MAP: Dict[ProviderType, str] = {
    ProviderType.OPENROUTER: "https://openrouter.ai/api/v1",
    ProviderType.TOGETHER: "https://api.together.xyz/v1",
    ProviderType.GROQ: "https://api.groq.com/openai/v1",
    ProviderType.FIREWORKS: "https://api.fireworks.ai/inference/v1",
}


@dataclass
class LLMConfig:
    """Configuration for an LLM provider.

    All credentials are resolved from environment variables. Never hardcode secrets.
    """
    provider: ProviderType = ProviderType.OPENAI
    model: str = "gpt-4o"
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout: float = 120.0
    max_retries: int = 3
    retry_delay: float = 1.0
    extra_headers: Dict[str, str] = field(default_factory=dict)
    # Token budget enforcement
    token_budget_enabled: bool = False
    token_budget_per_request: int = 50_000

    @classmethod
    def from_env(cls, provider: Optional[ProviderType] = None) -> "LLMConfig":
        """Load config from environment variables.

        Env vars (all optional, sensible defaults):
            AMPREALIZE_LLM_PROVIDER, AMPREALIZE_LLM_MODEL, AMPREALIZE_LLM_API_KEY,
            AMPREALIZE_LLM_API_BASE, AMPREALIZE_LLM_MAX_TOKENS, AMPREALIZE_LLM_TEMPERATURE,
            AMPREALIZE_LLM_TIMEOUT, AMPREALIZE_LLM_MAX_RETRIES, AMPREALIZE_LLM_RETRY_DELAY,
            AMPREALIZE_LLM_TOKEN_BUDGET_ENABLED, AMPREALIZE_LLM_TOKEN_BUDGET

        Provider-specific keys:
            OPENAI_API_KEY, ANTHROPIC_API_KEY, OPENROUTER_API_KEY,
            TOGETHER_API_KEY, GROQ_API_KEY, FIREWORKS_API_KEY, OLLAMA_HOST
        """
        provider_str = os.environ.get("AMPREALIZE_LLM_PROVIDER", "openai").lower()
        resolved_provider = provider or ProviderType(provider_str)

        # API key: generic override → provider-specific env var
        api_key = os.environ.get("AMPREALIZE_LLM_API_KEY")
        if not api_key:
            env_name = _KEY_ENV_MAP.get(resolved_provider, "")
            if env_name:
                api_key = os.environ.get(env_name)

        # Base URL: generic override → provider-specific default
        api_base = os.environ.get("AMPREALIZE_LLM_API_BASE")
        if not api_base:
            if resolved_provider == ProviderType.OLLAMA:
                api_base = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
            else:
                api_base = _BASE_URL_MAP.get(resolved_provider)

        return cls(
            provider=resolved_provider,
            model=os.environ.get(
                "AMPREALIZE_LLM_MODEL",
                _DEFAULT_MODELS.get(resolved_provider, "gpt-4o"),
            ),
            api_key=api_key,
            api_base=api_base,
            max_tokens=int(os.environ.get("AMPREALIZE_LLM_MAX_TOKENS", "4096")),
            temperature=float(os.environ.get("AMPREALIZE_LLM_TEMPERATURE", "0.7")),
            timeout=float(os.environ.get("AMPREALIZE_LLM_TIMEOUT", "120")),
            max_retries=int(os.environ.get("AMPREALIZE_LLM_MAX_RETRIES", "3")),
            retry_delay=float(os.environ.get("AMPREALIZE_LLM_RETRY_DELAY", "1.0")),
            token_budget_enabled=os.environ.get("AMPREALIZE_LLM_TOKEN_BUDGET_ENABLED", "false").lower() == "true",
            token_budget_per_request=int(os.environ.get("AMPREALIZE_LLM_TOKEN_BUDGET", "50000")),
        )


# =============================================================================
# Response types
# =============================================================================

@dataclass
class LLMResponse:
    """Unified response from any LLM provider.

    Includes content, tool calls, token usage, cost, and latency metrics.
    """
    content: str
    tool_calls: List[Any] = field(default_factory=list)  # List[ToolCall] — avoid circular import
    model: str = ""
    provider: ProviderType = ProviderType.OPENAI
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    finish_reason: Optional[str] = None


class StreamChunkType(str, Enum):
    """Types of streaming chunks."""
    TEXT_DELTA = "text_delta"
    TOOL_USE_START = "tool_use_start"
    TOOL_USE_DELTA = "tool_use_delta"
    TOOL_USE_END = "tool_use_end"
    MESSAGE_COMPLETE = "message_complete"
    ERROR = "error"


@dataclass
class StreamChunk:
    """A single chunk from a streaming LLM response."""
    type: StreamChunkType
    text: Optional[str] = None
    tool_name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_args_delta: Optional[str] = None
    tool_call: Optional[Any] = None  # Completed ToolCall
    response: Optional[LLMResponse] = None  # Final accumulated response
    error: Optional[str] = None


@dataclass
class LLMCallMetrics:
    """Metrics for a single LLM call."""
    model_id: str
    provider: ProviderType
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    cached_tokens: int = 0


# =============================================================================
# Errors
# =============================================================================

class LLMError(Exception):
    """Base error for LLM operations."""
    def __init__(
        self,
        message: str,
        provider: Optional[ProviderType] = None,
        status_code: Optional[int] = None,
    ):
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


class RateLimitError(LLMError):
    """Raised when rate-limited by a provider (HTTP 429)."""
    pass


class AuthenticationError(LLMError):
    """Raised when authentication fails (HTTP 401/403)."""
    pass


class TokenBudgetError(LLMError):
    """Raised when a request would exceed the configured token budget."""
    def __init__(
        self,
        message: str,
        budget: int,
        estimated_tokens: int,
        provider: Optional[ProviderType] = None,
    ):
        super().__init__(message, provider=provider)
        self.budget = budget
        self.estimated_tokens = estimated_tokens
