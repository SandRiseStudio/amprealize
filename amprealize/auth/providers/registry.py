"""Provider registry for managing OAuth providers.

This module provides a centralized registry for OAuth provider implementations,
enabling pluggable authentication across different platforms (GitHub, Google).

Note: InternalAuthProvider was deprecated on 2026-01-09.
User authentication is now handled via auth.users table and UserAuthService.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Type

from .base import OAuthProvider
from .github import GitHubOAuthProvider
from .google import GoogleOAuthProvider


class ProviderRegistry:
    """Registry for OAuth provider implementations."""

    _providers: Dict[str, Type[OAuthProvider]] = {}
    _default_provider: Optional[str] = None

    @classmethod
    def register(cls, name: str, provider_class: Type[OAuthProvider], *, default: bool = False) -> None:
        """Register an OAuth provider implementation.

        Args:
            name: Provider identifier (e.g., "github", "gitlab")
            provider_class: Provider class implementing OAuthProvider
            default: Whether this should be the default provider
        """
        if not name:
            raise ValueError("Provider name cannot be empty")
        if not issubclass(provider_class, OAuthProvider):
            raise TypeError(f"{provider_class} must implement OAuthProvider")

        cls._providers[name] = provider_class

        if default or cls._default_provider is None:
            cls._default_provider = name

    @classmethod
    def get(cls, name: Optional[str] = None) -> Type[OAuthProvider]:
        """Get a registered OAuth provider by name.

        Args:
            name: Provider identifier (e.g., "github"). If None, returns default.

        Returns:
            Provider class implementing OAuthProvider

        Raises:
            ValueError: If provider name is unknown
        """
        provider_name = name or cls._default_provider

        if not provider_name:
            raise ValueError("No provider specified and no default provider set")

        if provider_name not in cls._providers:
            available = ", ".join(cls.list_providers())
            raise ValueError(
                f"Unknown provider: {provider_name}. "
                f"Available providers: {available}"
            )

        return cls._providers[provider_name]

    @classmethod
    def list_providers(cls) -> List[str]:
        """List all registered provider names.

        Returns:
            List of provider identifiers
        """
        return sorted(cls._providers.keys())

    @classmethod
    def get_default(cls) -> Optional[str]:
        """Get the default provider name.

        Returns:
            Default provider identifier or None
        """
        return cls._default_provider

    @classmethod
    def set_default(cls, name: str) -> None:
        """Set the default provider.

        Args:
            name: Provider identifier

        Raises:
            ValueError: If provider name is unknown
        """
        if name not in cls._providers:
            raise ValueError(f"Unknown provider: {name}")
        cls._default_provider = name

    @classmethod
    def create_provider(
        cls,
        name: Optional[str] = None,
        *,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        **kwargs,
    ) -> OAuthProvider:
        """Create an OAuth provider instance.

        Args:
            name: Provider identifier (e.g., "github", "internal"). If None, uses default.
            client_id: OAuth client ID (defaults to env var, not needed for internal)
            client_secret: OAuth client secret (defaults to env var, not needed for internal)
            **kwargs: Additional provider-specific arguments

        Returns:
            Instantiated OAuth provider

        Raises:
            ValueError: If provider not found or credentials missing
        """
        provider_class = cls.get(name)
        provider_name = name or cls._default_provider or "oauth"

        # Auto-detect credentials from environment if not provided
        if client_id is None:
            client_id = os.getenv(f"{provider_name.upper()}_CLIENT_ID") or os.getenv("OAUTH_CLIENT_ID")

        if client_secret is None:
            client_secret = os.getenv(f"{provider_name.upper()}_CLIENT_SECRET") or os.getenv("OAUTH_CLIENT_SECRET")

        if not client_id or not client_secret:
            raise ValueError(
                f"OAuth credentials not found. Set {provider_name.upper()}_CLIENT_ID "
                f"and {provider_name.upper()}_CLIENT_SECRET environment variables."
            )

        return provider_class(client_id=client_id, client_secret=client_secret, **kwargs)  # type: ignore[call-arg]


# Register built-in providers
ProviderRegistry.register("github", GitHubOAuthProvider, default=True)
ProviderRegistry.register("google", GoogleOAuthProvider)

# Note: InternalAuthProvider was deprecated on 2026-01-09.
# User authentication is now handled via auth.users table and UserAuthService.
# Future OAuth providers will be registered here:
# ProviderRegistry.register("gitlab", GitLabOAuthProvider)
# ProviderRegistry.register("bitbucket", BitbucketOAuthProvider)
