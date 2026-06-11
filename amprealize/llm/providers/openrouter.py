"""OpenRouter provider — extends OpenAI with OpenRouter-specific config.

OpenRouter is fully OpenAI-compatible; we just override the base URL and
add the required HTTP-Referer and X-Title headers.
"""

from __future__ import annotations

import os

from amprealize.llm.providers.openai import OpenAIProvider
from amprealize.llm.types import LLMConfig


class OpenRouterProvider(OpenAIProvider):
    """OpenRouter API — unified gateway to many models."""

    def __init__(self, config: LLMConfig) -> None:
        if not config.api_base:
            config = LLMConfig(
                provider=config.provider,
                model=config.model,
                api_key=config.api_key,
                api_base="https://openrouter.ai/api/v1",
                max_tokens=config.max_tokens,
                temperature=config.temperature,
                timeout=config.timeout,
                max_retries=config.max_retries,
                retry_delay=config.retry_delay,
                extra_headers={
                    "HTTP-Referer": "https://github.com/SandRiseStudio/amprealize",
                    "X-Title": "Amprealize",
                    **config.extra_headers,
                },
                token_budget_enabled=config.token_budget_enabled,
                token_budget_per_request=config.token_budget_per_request,
            )
        super().__init__(config)

    def is_available(self) -> bool:
        return bool(self.config.api_key or os.environ.get("OPENROUTER_API_KEY"))
