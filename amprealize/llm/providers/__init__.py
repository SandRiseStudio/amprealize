"""Provider registry and factory."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Type

from amprealize.llm.types import LLMConfig, LLMError, ProviderType
from amprealize.llm.providers.base import Provider

if TYPE_CHECKING:
    pass

# Registry populated at import time by each provider module
PROVIDER_REGISTRY: Dict[ProviderType, Type[Provider]] = {}


def _register_providers() -> None:
    """Import provider modules to populate the registry."""
    from amprealize.llm.providers.anthropic import AnthropicProvider
    from amprealize.llm.providers.openai import OpenAIProvider
    from amprealize.llm.providers.openrouter import OpenRouterProvider
    from amprealize.llm.providers.ollama import OllamaProvider
    from amprealize.llm.providers.test import TestProvider

    PROVIDER_REGISTRY.update({
        ProviderType.ANTHROPIC: AnthropicProvider,
        ProviderType.OPENAI: OpenAIProvider,
        ProviderType.OPENROUTER: OpenRouterProvider,
        ProviderType.OLLAMA: OllamaProvider,
        ProviderType.TOGETHER: OpenAIProvider,   # OpenAI-compatible
        ProviderType.GROQ: OpenAIProvider,       # OpenAI-compatible
        ProviderType.FIREWORKS: OpenAIProvider,   # OpenAI-compatible
        ProviderType.TEST: TestProvider,
    })


def get_provider(config: LLMConfig) -> Provider:
    """Instantiate a provider from config.

    Raises:
        LLMError: If the provider type is not supported.
    """
    if not PROVIDER_REGISTRY:
        _register_providers()

    provider_class = PROVIDER_REGISTRY.get(config.provider)
    if provider_class is None:
        raise LLMError(
            f"Unsupported provider: {config.provider}. "
            f"Supported: {', '.join(p.value for p in PROVIDER_REGISTRY)}",
            provider=config.provider,
        )
    return provider_class(config)
