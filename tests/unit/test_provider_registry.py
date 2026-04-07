"""Test provider registry."""

import os
import pytest

from amprealize.auth.providers import ProviderRegistry, GitHubOAuthProvider, OAuthProvider


def test_register_provider():
    """Test registering a provider."""
    # GitHub should already be registered as default
    assert "github" in ProviderRegistry.list_providers()
    assert ProviderRegistry.get_default() == "github"


def test_get_provider():
    """Test getting a registered provider."""
    provider_class = ProviderRegistry.get("github")
    assert provider_class == GitHubOAuthProvider
    assert issubclass(provider_class, OAuthProvider)


def test_get_default_provider():
    """Test getting the default provider."""
    provider_class = ProviderRegistry.get()  # No name = default
    assert provider_class == GitHubOAuthProvider


def test_get_unknown_provider():
    """Test getting an unknown provider raises ValueError."""
    with pytest.raises(ValueError, match="Unknown provider: unknown"):
        ProviderRegistry.get("unknown")


def test_list_providers():
    """Test listing all registered providers."""
    providers = ProviderRegistry.list_providers()
    assert isinstance(providers, list)
    assert "github" in providers
    assert providers == sorted(providers)  # Should be sorted


def test_create_provider_with_credentials():
    """Test creating a provider instance with explicit credentials."""
    client_id = "test_client_id"
    client_secret = "test_client_secret"

    provider = ProviderRegistry.create_provider(
        "github",
        client_id=client_id,
        client_secret=client_secret
    )

    assert isinstance(provider, GitHubOAuthProvider)
    assert provider._client_id == client_id
    assert provider._client_secret == client_secret


def test_create_provider_from_env():
    """Test creating a provider instance from environment variables."""
    # Set environment variables
    os.environ["OAUTH_CLIENT_ID"] = "env_client_id"
    os.environ["OAUTH_CLIENT_SECRET"] = "env_client_secret"

    try:
        provider = ProviderRegistry.create_provider("github")
        assert isinstance(provider, GitHubOAuthProvider)
        assert provider._client_id == "env_client_id"
        assert provider._client_secret == "env_client_secret"
    finally:
        # Clean up
        os.environ.pop("OAUTH_CLIENT_ID", None)
        os.environ.pop("OAUTH_CLIENT_SECRET", None)


def test_create_provider_no_credentials():
    """Test creating a provider without credentials raises ValueError."""
    # Ensure no credentials in environment
    os.environ.pop("OAUTH_CLIENT_ID", None)
    os.environ.pop("OAUTH_CLIENT_SECRET", None)
    os.environ.pop("GITHUB_CLIENT_ID", None)
    os.environ.pop("GITHUB_CLIENT_SECRET", None)

    with pytest.raises(ValueError, match="OAuth credentials not found"):
        ProviderRegistry.create_provider("github")


def test_set_default_provider():
    """Test setting the default provider."""
    original_default = ProviderRegistry.get_default()

    try:
        # Set to GitHub (already registered)
        ProviderRegistry.set_default("github")
        assert ProviderRegistry.get_default() == "github"
    finally:
        # Restore original default
        if original_default:
            ProviderRegistry.set_default(original_default)


def test_set_default_unknown_provider():
    """Test setting default to unknown provider raises ValueError."""
    with pytest.raises(ValueError, match="Unknown provider: unknown"):
        ProviderRegistry.set_default("unknown")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
