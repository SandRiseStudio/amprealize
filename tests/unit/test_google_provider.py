"""
Unit tests for GoogleOAuthProvider.

These tests cover the Google OAuth device flow implementation including
device code request, token polling, token refresh, validation, and revocation.

To run with real Google credentials:
    GOOGLE_CLIENT_ID=xxx GOOGLE_CLIENT_SECRET=yyy pytest tests/unit/test_google_provider.py -v
"""

import pytest
import os
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from amprealize.auth.providers.google import GoogleOAuthProvider
from amprealize.auth.providers.base import (
    DeviceCodeResponse,
    TokenResponse,
    UserInfo,
    AuthorizationPendingError,
    SlowDownError,
    ExpiredTokenError,
    AccessDeniedError,
    InvalidTokenError,
    OAuthError,
)


@pytest.fixture
def google_provider():
    """Create a GoogleOAuthProvider instance for testing."""
    return GoogleOAuthProvider(
        client_id="test-client-id.apps.googleusercontent.com",
        client_secret="test-client-secret"
    )


class TestGoogleOAuthProviderProperties:
    """Test basic provider properties."""

    def test_name_property(self, google_provider):
        """Test that name property returns 'google'."""
        assert google_provider.name == "google"

    def test_endpoints_defined(self, google_provider):
        """Test that all OAuth endpoints are defined."""
        assert google_provider.DEVICE_CODE_URL == "https://oauth2.googleapis.com/device/code"
        assert google_provider.TOKEN_URL == "https://oauth2.googleapis.com/token"
        assert google_provider.USER_INFO_URL == "https://www.googleapis.com/oauth2/v1/userinfo"
        assert google_provider.REVOKE_URL == "https://oauth2.googleapis.com/revoke"


class TestStartDeviceFlow:
    """Test device flow initiation."""

    @pytest.mark.asyncio
    async def test_start_device_flow_success(self, google_provider):
        """Test successful device flow start."""
        mock_response = {
            "device_code": "test-device-code",
            "user_code": "ABCD-1234",
            "verification_url": "https://www.google.com/device",
            "expires_in": 1800,
            "interval": 5
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = MagicMock(
                status_code=200,
                json=lambda: mock_response,
                raise_for_status=lambda: None
            )

            result = await google_provider.start_device_flow()

            assert isinstance(result, DeviceCodeResponse)
            assert result.device_code == "test-device-code"
            assert result.user_code == "ABCD-1234"
            assert result.verification_uri == "https://www.google.com/device"
            assert result.expires_in == 1800
            assert result.interval == 5

    @pytest.mark.asyncio
    async def test_start_device_flow_with_custom_scopes(self, google_provider):
        """Test device flow with custom scopes."""
        mock_response = {
            "device_code": "test-device-code",
            "user_code": "WXYZ-5678",
            "verification_url": "https://www.google.com/device",
            "expires_in": 1800,
            "interval": 5
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = MagicMock(
                status_code=200,
                json=lambda: mock_response,
                raise_for_status=lambda: None
            )

            await google_provider.start_device_flow(scopes=["email", "openid"])

            # Verify the call was made with correct scope parameter
            call_kwargs = mock_instance.post.call_args
            assert "email openid" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_start_device_flow_handles_verification_uri_key(self, google_provider):
        """Test that both verification_url and verification_uri keys are handled."""
        # Test with verification_uri (alternative key)
        mock_response = {
            "device_code": "test-device-code",
            "user_code": "TEST-CODE",
            "verification_uri": "https://www.google.com/device",
            "expires_in": 1800,
            "interval": 5
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = MagicMock(
                status_code=200,
                json=lambda: mock_response,
                raise_for_status=lambda: None
            )

            result = await google_provider.start_device_flow()
            assert result.verification_uri == "https://www.google.com/device"

    @pytest.mark.asyncio
    async def test_start_device_flow_http_error(self, google_provider):
        """Test device flow with HTTP error."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance

            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.text = "Bad Request"
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Bad Request", request=MagicMock(), response=mock_response
            )
            mock_instance.post.return_value = mock_response

            with pytest.raises(OAuthError) as exc_info:
                await google_provider.start_device_flow()

            assert "400" in str(exc_info.value)


class TestPollToken:
    """Test token polling."""

    @pytest.mark.asyncio
    async def test_poll_token_success(self, google_provider):
        """Test successful token poll."""
        mock_response = {
            "access_token": "test-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "test-refresh-token",
            "scope": "email profile openid"
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = MagicMock(
                status_code=200,
                json=lambda: mock_response,
                raise_for_status=lambda: None
            )

            result = await google_provider.poll_token("test-device-code")

            assert isinstance(result, TokenResponse)
            assert result.access_token == "test-access-token"
            assert result.token_type == "Bearer"
            assert result.expires_in == 3600
            assert result.refresh_token == "test-refresh-token"

    @pytest.mark.asyncio
    async def test_poll_token_authorization_pending_428(self, google_provider):
        """Test authorization pending via HTTP 428 status."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = MagicMock(
                status_code=428,
                json=lambda: {"error": "authorization_pending"}
            )

            with pytest.raises(AuthorizationPendingError):
                await google_provider.poll_token("test-device-code")

    @pytest.mark.asyncio
    async def test_poll_token_slow_down_403(self, google_provider):
        """Test slow down via HTTP 403 with slow_down error."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = MagicMock(
                status_code=403,
                json=lambda: {"error": "slow_down"}
            )

            with pytest.raises(SlowDownError) as exc_info:
                await google_provider.poll_token("test-device-code")

            assert exc_info.value.retry_after == 10

    @pytest.mark.asyncio
    async def test_poll_token_access_denied_403(self, google_provider):
        """Test access denied via HTTP 403."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = MagicMock(
                status_code=403,
                json=lambda: {"error": "access_denied"}
            )

            with pytest.raises(AccessDeniedError):
                await google_provider.poll_token("test-device-code")

    @pytest.mark.asyncio
    async def test_poll_token_expired_400(self, google_provider):
        """Test expired token via HTTP 400."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = MagicMock(
                status_code=400,
                json=lambda: {"error": "expired_token"}
            )

            with pytest.raises(ExpiredTokenError):
                await google_provider.poll_token("test-device-code")

    @pytest.mark.asyncio
    async def test_poll_token_invalid_grant_400(self, google_provider):
        """Test invalid grant via HTTP 400."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = MagicMock(
                status_code=400,
                json=lambda: {"error": "invalid_grant"}
            )

            with pytest.raises(ExpiredTokenError):
                await google_provider.poll_token("test-device-code")


class TestRefreshToken:
    """Test token refresh."""

    @pytest.mark.asyncio
    async def test_refresh_token_success(self, google_provider):
        """Test successful token refresh."""
        mock_response = {
            "access_token": "new-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "email profile openid"
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = MagicMock(
                status_code=200,
                json=lambda: mock_response,
                raise_for_status=lambda: None
            )

            result = await google_provider.refresh_token("test-refresh-token")

            assert isinstance(result, TokenResponse)
            assert result.access_token == "new-access-token"
            # Should preserve original refresh token if not returned
            assert result.refresh_token == "test-refresh-token"

    @pytest.mark.asyncio
    async def test_refresh_token_invalid_grant(self, google_provider):
        """Test refresh with invalid grant error."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance

            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.json.return_value = {"error": "invalid_grant"}
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Bad Request", request=MagicMock(), response=mock_response
            )
            mock_instance.post.return_value = mock_response

            with pytest.raises(InvalidTokenError):
                await google_provider.refresh_token("expired-refresh-token")


class TestValidateToken:
    """Test token validation."""

    @pytest.mark.asyncio
    async def test_validate_token_success(self, google_provider):
        """Test successful token validation."""
        mock_response = {
            "id": "123456789",
            "email": "user@example.com",
            "name": "Test User",
            "picture": "https://example.com/avatar.jpg"
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = MagicMock(
                status_code=200,
                json=lambda: mock_response,
                raise_for_status=lambda: None
            )

            result = await google_provider.validate_token("test-access-token")

            assert isinstance(result, UserInfo)
            assert result.provider == "google"
            assert result.user_id == "123456789"
            assert result.email == "user@example.com"
            assert result.display_name == "Test User"
            assert result.avatar_url == "https://example.com/avatar.jpg"
            # Username should be email prefix
            assert result.username == "user"

    @pytest.mark.asyncio
    async def test_validate_token_unauthorized(self, google_provider):
        """Test validation with invalid token."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = MagicMock(
                status_code=401
            )

            with pytest.raises(InvalidTokenError):
                await google_provider.validate_token("invalid-token")


class TestRevokeToken:
    """Test token revocation."""

    @pytest.mark.asyncio
    async def test_revoke_token_success(self, google_provider):
        """Test successful token revocation."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = MagicMock(
                status_code=200
            )

            # Should not raise
            await google_provider.revoke_token("test-token")

    @pytest.mark.asyncio
    async def test_revoke_token_already_revoked(self, google_provider):
        """Test revocation of already revoked token (400 response)."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = MagicMock(
                status_code=400
            )

            # Should not raise - revocation is best-effort
            await google_provider.revoke_token("already-revoked-token")


class TestProviderRegistration:
    """Test provider is properly registered."""

    def test_google_provider_registered(self):
        """Test that GoogleOAuthProvider is registered in the registry."""
        from amprealize.auth.providers import ProviderRegistry, GoogleOAuthProvider

        providers = ProviderRegistry.list_providers()
        assert "google" in providers

        provider_class = ProviderRegistry.get("google")
        assert provider_class is GoogleOAuthProvider

    def test_create_provider_from_registry(self):
        """Test creating Google provider via registry."""
        from amprealize.auth.providers import ProviderRegistry

        # Set env vars for test
        with patch.dict(os.environ, {
            "GOOGLE_CLIENT_ID": "test-id.apps.googleusercontent.com",
            "GOOGLE_CLIENT_SECRET": "test-secret"
        }):
            provider = ProviderRegistry.create_provider("google")
            assert provider.name == "google"


# Integration test marker - requires real credentials
@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("GOOGLE_CLIENT_ID"),
    reason="GOOGLE_CLIENT_ID not set"
)
class TestGoogleProviderIntegration:
    """Integration tests requiring real Google OAuth credentials."""

    @pytest.fixture
    def real_provider(self):
        """Create provider with real credentials from environment."""
        return GoogleOAuthProvider(
            client_id=os.environ["GOOGLE_CLIENT_ID"],
            client_secret=os.environ["GOOGLE_CLIENT_SECRET"]
        )

    @pytest.mark.asyncio
    async def test_real_device_flow_start(self, real_provider):
        """Test starting real device flow (requires manual authorization)."""
        try:
            result = await real_provider.start_device_flow()
        except OAuthError as exc:
            message = str(exc)
            if "invalid_client" in message and "Limited Input" in message:
                pytest.skip(
                    "Configured Google OAuth client is not a TVs/Limited Input device client"
                )
            raise

        assert result.device_code
        assert result.user_code
        assert "google.com" in result.verification_uri
        assert result.expires_in > 0

        print(f"\n\nTo complete authorization:")
        print(f"1. Go to: {result.verification_uri}")
        print(f"2. Enter code: {result.user_code}")
        print(f"Device code expires in {result.expires_in} seconds\n")
