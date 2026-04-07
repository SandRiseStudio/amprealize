"""
GitHub OAuth provider implementation using device flow.

This provider integrates with GitHub's OAuth 2.0 device authorization flow,
allowing users to authenticate via https://github.com/login/device.

Configuration (environment variables or .env.github-oauth):
    OAUTH_GITHUB_CLIENT_ID: OAuth app client ID (from .env.github-oauth)
    OAUTH_GITHUB_CLIENT_SECRET: OAuth app client secret
    OAUTH_GITHUB_ENABLED: Set to 'true' to enable this provider (default: false)

GitHub OAuth App Requirements:
    - Device flow must be enabled (checkbox during app creation)
    - Scopes typically requested: read:user, user:email
"""

import httpx
import logging
from typing import Optional

from .base import (
    OAuthProvider,
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

logger = logging.getLogger(__name__)


class GitHubOAuthProvider(OAuthProvider):
    """GitHub OAuth device flow implementation"""

    # GitHub OAuth endpoints
    DEVICE_CODE_URL = "https://github.com/login/device/code"
    TOKEN_URL = "https://github.com/login/oauth/access_token"
    USER_INFO_URL = "https://api.github.com/user"
    REVOKE_URL = "https://github.com/settings/connections/applications"

    def __init__(self, client_id: str, client_secret: str):
        """
        Initialize GitHub OAuth provider.

        Args:
            client_id: OAuth app client ID
            client_secret: OAuth app client secret
        """
        self._client_id = client_id
        self._client_secret = client_secret
        logger.info("Initialized GitHub OAuth provider")

    @property
    def name(self) -> str:
        return "github"

    async def start_device_flow(self, scopes: Optional[list[str]] = None) -> DeviceCodeResponse:
        """
        Start GitHub OAuth device flow.

        Args:
            scopes: List of scopes to request (default: ["read:user", "user:email"])

        Returns:
            DeviceCodeResponse with GitHub's verification URI
        """
        if scopes is None:
            scopes = ["read:user", "user:email"]

        logger.info(f"Starting GitHub device flow with scopes: {scopes}")

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.DEVICE_CODE_URL,
                    headers={"Accept": "application/json"},
                    data={
                        "client_id": self._client_id,
                        "scope": " ".join(scopes)
                    },
                    timeout=10.0
                )
                response.raise_for_status()
                data = response.json()

                logger.info(f"GitHub device flow started: user_code={data['user_code']}")

                return DeviceCodeResponse(
                    device_code=data["device_code"],
                    user_code=data["user_code"],
                    verification_uri=data["verification_uri"],
                    expires_in=data["expires_in"],
                    interval=data["interval"]
                )
            except httpx.HTTPStatusError as e:
                logger.error(f"GitHub device flow failed: {e.response.status_code} {e.response.text}")
                raise OAuthError(f"GitHub device flow failed: {e.response.status_code}")
            except Exception as e:
                logger.error(f"GitHub device flow error: {e}")
                raise OAuthError(f"GitHub device flow error: {e}")

    async def poll_token(self, device_code: str) -> TokenResponse:
        """
        Poll GitHub for access token.

        Args:
            device_code: Device code from start_device_flow()

        Returns:
            TokenResponse with access token

        Raises:
            AuthorizationPendingError: User hasn't authorized yet
            SlowDownError: Polling too fast
            ExpiredTokenError: Device code expired
            AccessDeniedError: User denied authorization
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.TOKEN_URL,
                    headers={"Accept": "application/json"},
                    data={
                        "client_id": self._client_id,
                        "device_code": device_code,
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
                    },
                    timeout=10.0
                )

                data = response.json()

                # Handle GitHub-specific error responses
                if "error" in data:
                    error_code = data["error"]
                    error_desc = data.get("error_description", "")

                    if error_code == "authorization_pending":
                        raise AuthorizationPendingError("User hasn't authorized yet")
                    elif error_code == "slow_down":
                        interval = data.get("interval", 5)
                        raise SlowDownError(retry_after=interval)
                    elif error_code == "expired_token":
                        raise ExpiredTokenError("Device code has expired")
                    elif error_code == "access_denied":
                        raise AccessDeniedError("User denied authorization")
                    else:
                        logger.error(f"GitHub OAuth error: {error_code} - {error_desc}")
                        raise OAuthError(f"GitHub OAuth error: {error_code}")

                logger.info("GitHub access token received successfully")

                return TokenResponse(
                    access_token=data["access_token"],
                    token_type=data["token_type"],
                    expires_in=data.get("expires_in", 28800),  # GitHub default: 8 hours
                    refresh_token=data.get("refresh_token"),
                    scope=data.get("scope")
                )
            except (AuthorizationPendingError, SlowDownError, ExpiredTokenError, AccessDeniedError):
                # Re-raise expected errors
                raise
            except httpx.HTTPStatusError as e:
                logger.error(f"GitHub token poll failed: {e.response.status_code} {e.response.text}")
                raise OAuthError(f"GitHub token poll failed: {e.response.status_code}")
            except Exception as e:
                logger.error(f"GitHub token poll error: {e}")
                raise OAuthError(f"GitHub token poll error: {e}")

    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        """
        Refresh GitHub access token.

        Note: GitHub OAuth apps may not support refresh tokens by default.
        Check your OAuth app settings.

        Args:
            refresh_token: Refresh token from previous TokenResponse

        Returns:
            TokenResponse with new access token
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.TOKEN_URL,
                    headers={"Accept": "application/json"},
                    data={
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token"
                    },
                    timeout=10.0
                )
                response.raise_for_status()
                data = response.json()

                logger.info("GitHub token refreshed successfully")

                return TokenResponse(
                    access_token=data["access_token"],
                    token_type=data["token_type"],
                    expires_in=data.get("expires_in", 28800),
                    refresh_token=data.get("refresh_token"),
                    scope=data.get("scope")
                )
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    raise InvalidTokenError("Refresh token is invalid or expired")
                logger.error(f"GitHub token refresh failed: {e.response.status_code} {e.response.text}")
                raise OAuthError(f"GitHub token refresh failed: {e.response.status_code}")
            except Exception as e:
                logger.error(f"GitHub token refresh error: {e}")
                raise OAuthError(f"GitHub token refresh error: {e}")

    async def validate_token(self, access_token: str) -> UserInfo:
        """
        Validate GitHub access token and get user info.

        Args:
            access_token: GitHub access token

        Returns:
            UserInfo with GitHub user details
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    self.USER_INFO_URL,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/json"
                    },
                    timeout=10.0
                )

                if response.status_code == 401:
                    raise InvalidTokenError("Access token is invalid or expired")

                response.raise_for_status()
                data = response.json()

                logger.info(f"GitHub token validated for user: {data['login']}")

                return UserInfo(
                    provider="github",
                    user_id=str(data["id"]),
                    username=data["login"],
                    email=data.get("email"),
                    display_name=data.get("name"),
                    avatar_url=data.get("avatar_url")
                )
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    raise InvalidTokenError("Access token is invalid or expired")
                logger.error(f"GitHub token validation failed: {e.response.status_code} {e.response.text}")
                raise OAuthError(f"GitHub token validation failed: {e.response.status_code}")
            except InvalidTokenError:
                raise
            except Exception as e:
                logger.error(f"GitHub token validation error: {e}")
                raise OAuthError(f"GitHub token validation error: {e}")

    async def revoke_token(self, token: str) -> None:
        """
        Revoke GitHub access token.

        Note: GitHub OAuth apps require the client_secret for revocation.
        Users can also manually revoke at: https://github.com/settings/connections/applications

        Args:
            token: Access token to revoke
        """
        async with httpx.AsyncClient() as client:
            try:
                # GitHub requires DELETE method with basic auth (client_id:client_secret)
                response = await client.delete(
                    f"https://api.github.com/applications/{self._client_id}/token",
                    auth=(self._client_id, self._client_secret),
                    json={"access_token": token},
                    timeout=10.0
                )

                if response.status_code == 204:
                    logger.info("GitHub token revoked successfully")
                elif response.status_code == 404:
                    logger.warning("GitHub token not found (may already be revoked)")
                else:
                    response.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.error(f"GitHub token revocation failed: {e.response.status_code} {e.response.text}")
                # Don't raise exception - token revocation is best-effort
            except Exception as e:
                logger.error(f"GitHub token revocation error: {e}")
                # Don't raise exception - token revocation is best-effort
