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
    NVIDIA = "nvidia"
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
    supports_tool_calls: bool = True
    supports_structured_output: bool = False
    supports_reasoning_delta: bool = False
    supports_streaming: bool = True
    is_open_model: bool = False
    is_default: bool = False
    free_endpoint: bool = False
    provider_base_url: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


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
        supports_structured_output=True,
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
        supports_structured_output=True,
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
        supports_structured_output=True,
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
        supports_structured_output=True,
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
        supports_structured_output=True,
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
        supports_structured_output=True,
    ),
    "nvidia-deepseek-v4-flash": ModelDefinition(
        model_id="nvidia-deepseek-v4-flash",
        api_name="deepseek-ai/deepseek-v4-flash",
        provider=ProviderType.NVIDIA,
        display_name="DeepSeek V4 Flash (NVIDIA NIM)",
        context_limit=1_000_000,
        max_output_tokens=16_384,
        input_price_per_m=0.0,
        output_price_per_m=0.0,
        supports_structured_output=True,
        supports_reasoning_delta=True,
        is_open_model=True,
        is_default=True,
        free_endpoint=True,
        provider_base_url="https://integrate.api.nvidia.com/v1",
        metadata={
            "publisher": "DeepSeek AI",
            "source": "https://build.nvidia.com/deepseek-ai/deepseek-v4-flash",
            "use_cases": ["coding", "agents", "reasoning"],
            "credit_note": "NVIDIA NIM free endpoint; production limits and credits are controlled by NVIDIA.",
        },
    ),
    "nvidia-deepseek-v4-pro": ModelDefinition(
        model_id="nvidia-deepseek-v4-pro",
        api_name="deepseek-ai/deepseek-v4-pro",
        provider=ProviderType.NVIDIA,
        display_name="DeepSeek V4 Pro (NVIDIA NIM)",
        context_limit=1_000_000,
        max_output_tokens=16_384,
        input_price_per_m=0.0,
        output_price_per_m=0.0,
        supports_tool_calls=True,
        supports_structured_output=True,
        supports_reasoning_delta=True,
        is_open_model=True,
        is_default=True,
        free_endpoint=True,
        provider_base_url="https://integrate.api.nvidia.com/v1",
        metadata={
            "publisher": "DeepSeek AI",
            "source": "https://build.nvidia.com/deepseek-ai/deepseek-v4-pro",
            "use_cases": ["coding", "agents", "reasoning"],
            "credit_note": "NVIDIA NIM free endpoint; production limits and credits are controlled by NVIDIA.",
        },
    ),
    "nvidia-minimax-m2-7": ModelDefinition(
        model_id="nvidia-minimax-m2-7",
        api_name="minimaxai/minimax-m2.7",
        provider=ProviderType.NVIDIA,
        display_name="MiniMax M2.7 (NVIDIA NIM)",
        context_limit=200_000,
        max_output_tokens=16_384,
        input_price_per_m=0.0,
        output_price_per_m=0.0,
        supports_structured_output=True,
        supports_reasoning_delta=True,
        is_open_model=True,
        is_default=True,
        free_endpoint=True,
        provider_base_url="https://integrate.api.nvidia.com/v1",
        metadata={
            "publisher": "MiniMaxAI",
            "source": "https://build.nvidia.com/minimaxai/minimax-m2.7",
            "use_cases": ["coding", "reasoning", "office"],
            "credit_note": "NVIDIA NIM free endpoint; production limits and credits are controlled by NVIDIA.",
        },
    ),
    "nvidia-kimi-k2-thinking": ModelDefinition(
        model_id="nvidia-kimi-k2-thinking",
        api_name="moonshotai/kimi-k2.6",
        provider=ProviderType.NVIDIA,
        display_name="Kimi K2.6 (NVIDIA NIM)",
        context_limit=256_000,
        max_output_tokens=16_384,
        input_price_per_m=0.0,
        output_price_per_m=0.0,
        supports_tool_calls=True,
        supports_structured_output=True,
        supports_reasoning_delta=True,
        is_open_model=True,
        is_default=True,
        free_endpoint=True,
        provider_base_url="https://integrate.api.nvidia.com/v1",
        metadata={
            "publisher": "Moonshot AI",
            "source": "https://build.nvidia.com/moonshotai/kimi-k2.6",
            "use_cases": ["agentic-ai", "reasoning", "tool-calling"],
            "credit_note": "NVIDIA NIM free endpoint; production limits and credits are controlled by NVIDIA.",
        },
    ),
    "nvidia-qwen3-coder-480b-a35b-instruct": ModelDefinition(
        model_id="nvidia-qwen3-coder-480b-a35b-instruct",
        api_name="qwen/qwen3-coder-480b-a35b-instruct",
        provider=ProviderType.NVIDIA,
        display_name="Qwen3 Coder 480B A35B Instruct (NVIDIA NIM)",
        context_limit=262_144,
        max_output_tokens=16_384,
        input_price_per_m=0.0,
        output_price_per_m=0.0,
        supports_tool_calls=True,
        supports_structured_output=True,
        is_open_model=True,
        is_default=True,
        free_endpoint=True,
        provider_base_url="https://integrate.api.nvidia.com/v1",
        metadata={
            "publisher": "Qwen",
            "source": "https://build.nvidia.com/qwen/qwen3-coder-480b-a35b-instruct",
            "use_cases": ["coding", "agentic-ai", "tool-calling"],
            "credit_note": "NVIDIA NIM free endpoint; production limits and credits are controlled by NVIDIA.",
        },
    ),
    "nvidia-gpt-oss-120b": ModelDefinition(
        model_id="nvidia-gpt-oss-120b",
        api_name="openai/gpt-oss-120b",
        provider=ProviderType.NVIDIA,
        display_name="GPT-OSS 120B (NVIDIA NIM)",
        context_limit=131_072,
        max_output_tokens=4_096,
        input_price_per_m=0.0,
        output_price_per_m=0.0,
        supports_tool_calls=True,
        supports_structured_output=True,
        supports_reasoning_delta=True,
        is_open_model=True,
        is_default=True,
        free_endpoint=True,
        provider_base_url="https://integrate.api.nvidia.com/v1",
        metadata={
            "publisher": "OpenAI",
            "source": "https://build.nvidia.com/openai/gpt-oss-120b",
            "use_cases": ["reasoning", "structured-output", "tool-calling"],
            "credit_note": "NVIDIA NIM free endpoint; production limits and credits are controlled by NVIDIA.",
        },
    ),
    "nvidia-mistral-large-3-675b-instruct-2512": ModelDefinition(
        model_id="nvidia-mistral-large-3-675b-instruct-2512",
        api_name="mistralai/mistral-large-3-675b-instruct-2512",
        provider=ProviderType.NVIDIA,
        display_name="Mistral Large 3 675B Instruct (NVIDIA NIM)",
        context_limit=256_000,
        max_output_tokens=16_384,
        input_price_per_m=0.0,
        output_price_per_m=0.0,
        supports_tool_calls=True,
        supports_structured_output=True,
        is_open_model=True,
        is_default=True,
        free_endpoint=True,
        provider_base_url="https://integrate.api.nvidia.com/v1",
        metadata={
            "publisher": "Mistral AI",
            "source": "https://build.nvidia.com/mistralai/mistral-large-3-675b-instruct-2512",
            "use_cases": ["chat", "agents", "instruction-following"],
            "credit_note": "NVIDIA NIM free endpoint; production limits and credits are controlled by NVIDIA.",
        },
    ),
    "nvidia-glm-5-1": ModelDefinition(
        model_id="nvidia-glm-5-1",
        api_name="z-ai/glm-5.1",
        provider=ProviderType.NVIDIA,
        display_name="GLM 5.1 (NVIDIA NIM)",
        context_limit=200_000,
        max_output_tokens=16_384,
        input_price_per_m=0.0,
        output_price_per_m=0.0,
        supports_tool_calls=True,
        supports_structured_output=True,
        supports_reasoning_delta=True,
        is_open_model=True,
        is_default=True,
        free_endpoint=True,
        provider_base_url="https://integrate.api.nvidia.com/v1",
        metadata={
            "publisher": "Z.ai",
            "source": "https://build.nvidia.com/z-ai/glm-5.1",
            "use_cases": ["tool-calling", "coding", "agentic-ai"],
            "credit_note": "NVIDIA NIM free endpoint; production limits and credits are controlled by NVIDIA.",
        },
    ),
    "nvidia-llama-3-1-nemotron-ultra-253b-v1": ModelDefinition(
        model_id="nvidia-llama-3-1-nemotron-ultra-253b-v1",
        api_name="nvidia/llama-3.1-nemotron-ultra-253b-v1",
        provider=ProviderType.NVIDIA,
        display_name="Llama 3.1 Nemotron Ultra 253B (NVIDIA NIM)",
        context_limit=128_000,
        max_output_tokens=16_384,
        input_price_per_m=0.0,
        output_price_per_m=0.0,
        supports_tool_calls=True,
        supports_structured_output=True,
        supports_reasoning_delta=True,
        is_open_model=True,
        is_default=True,
        free_endpoint=True,
        provider_base_url="https://integrate.api.nvidia.com/v1",
        metadata={
            "publisher": "NVIDIA",
            "source": "https://build.nvidia.com/nvidia/llama-3.1-nemotron-ultra-253b-v1",
            "use_cases": ["reasoning", "rag", "tool-calling"],
            "credit_note": "NVIDIA NIM free endpoint; production limits and credits are controlled by NVIDIA.",
        },
    ),
    "nvidia-llama-3-3-70b-instruct": ModelDefinition(
        model_id="nvidia-llama-3-3-70b-instruct",
        api_name="meta/llama-3.3-70b-instruct",
        provider=ProviderType.NVIDIA,
        display_name="Llama 3.3 70B Instruct (NVIDIA NIM)",
        context_limit=128_000,
        max_output_tokens=16_384,
        input_price_per_m=0.0,
        output_price_per_m=0.0,
        supports_tool_calls=True,
        supports_structured_output=True,
        is_open_model=True,
        is_default=True,
        free_endpoint=True,
        provider_base_url="https://integrate.api.nvidia.com/v1",
        metadata={
            "publisher": "Meta",
            "source": "https://build.nvidia.com/meta/llama-3_3-70b-instruct",
            "use_cases": ["chat", "multilingual", "instruction-following"],
            "credit_note": "NVIDIA NIM free endpoint; production limits and credits are controlled by NVIDIA.",
        },
    ),
    "nvidia-nemotron-3-content-safety": ModelDefinition(
        model_id="nvidia-nemotron-3-content-safety",
        api_name="nvidia/nemotron-3-content-safety",
        provider=ProviderType.NVIDIA,
        display_name="Nemotron 3 Content Safety (NVIDIA NIM)",
        context_limit=128_000,
        max_output_tokens=8_192,
        input_price_per_m=0.0,
        output_price_per_m=0.0,
        supports_tool_calls=False,
        supports_structured_output=True,
        is_open_model=True,
        free_endpoint=True,
        provider_base_url="https://integrate.api.nvidia.com/v1",
        metadata={
            "publisher": "NVIDIA",
            "source": "https://build.nvidia.com/nvidia/nemotron-3-content-safety",
            "chat_model": False,
            "use_cases": ["safety", "moderation"],
            "credit_note": "NVIDIA NIM free endpoint; production limits and credits are controlled by NVIDIA.",
        },
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
    ProviderType.NVIDIA: "deepseek-ai/deepseek-v4-flash",
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
    ProviderType.NVIDIA: "NVIDIA_API_KEY",
    ProviderType.TOGETHER: "TOGETHER_API_KEY",
    ProviderType.GROQ: "GROQ_API_KEY",
    ProviderType.FIREWORKS: "FIREWORKS_API_KEY",
}

# Provider-specific base URLs
_BASE_URL_MAP: Dict[ProviderType, str] = {
    ProviderType.OPENROUTER: "https://openrouter.ai/api/v1",
    ProviderType.NVIDIA: "https://integrate.api.nvidia.com/v1",
    ProviderType.TOGETHER: "https://api.together.xyz/v1",
    ProviderType.GROQ: "https://api.groq.com/openai/v1",
    ProviderType.FIREWORKS: "https://api.fireworks.ai/inference/v1",
}


def get_provider_default_model(provider: ProviderType) -> str:
    """Return the default API model name for a provider."""
    return _DEFAULT_MODELS.get(provider, "gpt-4o")


def get_provider_key_env(provider: ProviderType) -> str:
    """Return the provider-specific API key environment variable name."""
    return _KEY_ENV_MAP.get(provider, "")


def get_provider_base_url(provider: ProviderType) -> Optional[str]:
    """Return the default OpenAI-compatible base URL for a provider."""
    return _BASE_URL_MAP.get(provider)


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

        Chat-only override (read in ``ConversationReplyService`` for streaming, not here):
            AMPREALIZE_CHAT_LLM_TEMPERATURE — when set, overrides effective temperature for
            chat reply ``astream``/``call`` only; otherwise ``AMPREALIZE_LLM_TEMPERATURE`` applies.

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
    reasoning_content: Optional[str] = None


class StreamChunkType(str, Enum):
    """Types of streaming chunks."""
    TEXT_DELTA = "text_delta"
    REASONING_DELTA = "reasoning_delta"
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
    reasoning: Optional[str] = None
    tool_name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_args_delta: Optional[str] = None
    tool_call: Optional[Any] = None  # Completed ToolCall
    response: Optional[LLMResponse] = None  # Final accumulated response
    error: Optional[str] = None
    # Set on ERROR chunks: original provider/SDK exception name (e.g. APITimeoutError)
    error_class: Optional[str] = None


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
