"""Ollama provider — extends OpenAI using Ollama's OpenAI-compatible endpoint.

Ollama exposes /v1/chat/completions which is fully OpenAI-compatible,
so we simply set the base URL and disable API key requirement.
"""

from __future__ import annotations

import os

from amprealize.llm.providers.openai import OpenAIProvider
from amprealize.llm.types import LLMConfig


class OllamaProvider(OpenAIProvider):
    """Ollama local inference via OpenAI-compatible /v1/ endpoint."""

    def __init__(self, config: LLMConfig) -> None:
        ollama_host = config.api_base or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        # Ensure we target the OpenAI-compat endpoint
        api_base = f"{ollama_host.rstrip('/')}/v1"

        config = LLMConfig(
            provider=config.provider,
            model=config.model,
            api_key=config.api_key or "ollama",  # Ollama expects a dummy key for OpenAI compat
            api_base=api_base,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
            timeout=config.timeout,
            max_retries=config.max_retries,
            retry_delay=config.retry_delay,
            extra_headers=config.extra_headers,
            token_budget_enabled=config.token_budget_enabled,
            token_budget_per_request=config.token_budget_per_request,
        )
        super().__init__(config)

    def is_available(self) -> bool:
        """Check if Ollama is running."""
        import urllib.request
        import urllib.error

        # Strip /v1 to get back to base Ollama URL
        base = self.config.api_base or "http://localhost:11434/v1"
        ollama_base = base.rsplit("/v1", 1)[0]
        try:
            req = urllib.request.Request(f"{ollama_base}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False
