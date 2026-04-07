"""
Google OAuth provider implementation using device flow.

This provider integrates with Google's OAuth 2.0 device authorization flow,
allowing users to authenticate via https://www.google.com/device.

Configuration (environment variables):
    GOOGLE_CLIENT_ID: OAuth client ID (*.apps.googleusercontent.com)
    GOOGLE_CLIENT_SECRET: OAuth client secret
    OAUTH_GOOGLE_ENABLED: Set to 'true' to enable this provider (default: false)

Google Cloud Console Setup:
    1. Create OAuth 2.0 Client ID with application type: "Desktop app"
    2. Enable Google+ API (for user profile info) in APIs & Services
    3. Device flow works with limited scopes: email, profile, openid
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


class GoogleOAuthProvider(OAuthProvider):
    """Google OAuth provider supporting both device flow and authorization code flow"""

    # Google OAuth endpoints
    AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    USER_INFO_URL = "https://www.googleapis.com/oauth2/v1/userinfo"
    REVOKE_URL = "https://oauth2.googleapis.com/revoke"

    def __init__(self, client_id: str, client_secret: str):
        """
        Initialize Google OAuth provider.

        Args:
            client_id: OAuth client ID (*.apps.googleusercontent.com)
            client_secret: OAuth client secret
        """
        self._client_id = client_id
        self._client_secret = client_secret
        logger.info("Initialized Google OAuth provider")

    @property
    def name(self) -> str:
        return "google"

    # -------------------------------------------------------------------------
    # Authorization Code Flow (for web)
    # -------------------------------------------------------------------------

    def get_authorization_url(self, redirect_uri: str, state: Optional[str] = None, scopes: Optional[list[str]] = None) -> str:
        """
        Generate Google OAuth authorization URL.

        Args:
            redirect_uri: Callback URL after authorization
            state: CSRF state parameter (recommended)
            scopes: List of OAuth scopes to request (default: ["email", "profile", "openid"])

        Returns:
            str: URL to redirect user to for authorization
        """
        if scopes is None:
            scopes = ["email", "profile", "openid"]

        import urllib.parse

        params = {
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "response_type": "code",
            "access_type": "offline",  # Get refresh token
            "prompt": "consent",  # Force consent to ensure refresh token
        }
        if state:
            params["state"] = state

        return f"{self.AUTHORIZATION_URL}?{urllib.parse.urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> "TokenResponse":
        """
        Exchange authorization code for access token.

        Args:
            code: Authorization code from callback
            redirect_uri: Same redirect_uri used in authorization request

        Returns:
            TokenResponse: Access token and metadata
        """
        from .base import TokenResponse

        logger.info("Exchanging Google authorization code for token (redirect_uri=%s)", redirect_uri)

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.TOKEN_URL,
                    data={
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "code": code,
                        "redirect_uri": redirect_uri,
                        "grant_type": "authorization_code",
                    },
                    timeout=10.0
                )

                # Parse response body first to get error details
                data = response.json()

                # Check for error in response (Google returns 400 with error details)
                if "error" in data:
                    error = data.get("error", "unknown_error")
                    error_description = data.get("error_description", "Unknown error")
                    logger.error(
                        "Google code exchange error: %s - %s (status=%d, redirect_uri=%s)",
                        error, error_description, response.status_code, redirect_uri
                    )
                    raise OAuthError(f"Google OAuth error: {error} - {error_description}")

                # Now raise for other HTTP errors
                response.raise_for_status()

                logger.info("Google code exchange successful")
                return TokenResponse(
                    access_token=data["access_token"],
                    token_type=data.get("token_type", "Bearer"),
                    expires_in=data.get("expires_in", 3600),
                    refresh_token=data.get("refresh_token"),
                    scope=data.get("scope")
                )

            except httpx.HTTPStatusError as e:
                # Try to get error body for more context
                try:
                    error_body = e.response.json()
                    error_detail = error_body.get("error_description", error_body.get("error", str(e)))
                except Exception:
                    error_detail = str(e)
                logger.error("Google code exchange HTTP error: %s (body: %s)", e, error_detail)
                raise OAuthError(f"Google code exchange failed: {error_detail}")
            except httpx.RequestError as e:
                logger.error("Google code exchange request error: %s", e)
                raise OAuthError(f"Google code exchange request failed: {e}")

    async def start_device_flow(self, scopes: Optional[list[str]] = None) -> DeviceCodeResponse:
        """
        Start Google OAuth device flow.

        Args:
            scopes: List of scopes to request (default: ["email", "profile", "openid"])

        Returns:
            DeviceCodeResponse with Google's verification URI

        Note:
            Google device flow only supports limited scopes:
            - OpenID Connect: email, profile, openid
            - Drive: drive.appdata, drive.file
            - YouTube: youtube, youtube.readonly
        """
        if scopes is None:
            scopes = ["email", "profile", "openid"]

        logger.info(f"Starting Google device flow with scopes: {scopes}")

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.DEVICE_CODE_URL,
                    data={
                        "client_id": self._client_id,
                        "scope": " ".join(scopes)
                    },
                    timeout=10.0
                )
                response.raise_for_status()
                data = response.json()

                # Google uses 'verification_url' instead of 'verification_uri'
                verification_uri = data.get("verification_url") or data.get("verification_uri")

                logger.info(f"Google device flow started: user_code={data['user_code']}")

                return DeviceCodeResponse(
                    device_code=data["device_code"],
                    user_code=data["user_code"],
                    verification_uri=verification_uri,
                    expires_in=data["expires_in"],
                    interval=data.get("interval", 5)
                )
            except httpx.HTTPStatusError as e:
                logger.error(f"Google device flow failed: {e.response.status_code} {e.response.text}")
                raise OAuthError(f"Google device flow failed: {e.response.status_code}")
            except Exception as e:
                logger.error(f"Google device flow error: {e}")
                raise OAuthError(f"Google device flow error: {e}")

    async def poll_token(self, device_code: str) -> TokenResponse:
        """
        Poll Google for access token.

        Args:
            device_code: Device code from start_device_flow()

        Returns:
            TokenResponse with access token

        Raises:
            AuthorizationPendingError: User hasn't authorized yet
            SlowDownError: Polling too fast
            ExpiredTokenError: Device code expired
            AccessDeniedError: User denied authorization

        Note:
            Google uses HTTP status codes for errors:
            - 428 Precondition Required: authorization_pending
            - 403 Forbidden: access_denied or slow_down
            - 400 Bad Request: expired_token or invalid_grant
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.TOKEN_URL,
                    data={
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "device_code": device_code,
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
                    },
                    timeout=10.0
                )

                # Google uses HTTP status codes for device flow errors
                if response.status_code == 428:
                    # Authorization pending
                    raise AuthorizationPendingError("User hasn't authorized yet")

                if response.status_code == 403:
                    data = response.json()
                    error = data.get("error", "")
                    if error == "slow_down":
                        raise SlowDownError(retry_after=10)
                    else:
                        raise AccessDeniedError("User denied authorization or access forbidden")

                if response.status_code == 400:
                    data = response.json()
                    error = data.get("error", "")
                    if error in ("expired_token", "invalid_grant"):
                        raise ExpiredTokenError("Device code has expired")
                    else:
                        raise OAuthError(f"Google OAuth error: {error}")

                response.raise_for_status()
                data = response.json()

                # Check for error in response body (fallback)
                if "error" in data:
                    error_code = data["error"]
                    error_desc = data.get("error_description", "")

                    if error_code == "authorization_pending":
                        raise AuthorizationPendingError("User hasn't authorized yet")
                    elif error_code == "slow_down":
                        raise SlowDownError(retry_after=10)
                    elif error_code in ("expired_token", "invalid_grant"):
                        raise ExpiredTokenError("Device code has expired")
                    elif error_code == "access_denied":
                        raise AccessDeniedError("User denied authorization")
                    else:
                        logger.error(f"Google OAuth error: {error_code} - {error_desc}")
                        raise OAuthError(f"Google OAuth error: {error_code}")

                logger.info("Google access token received successfully")

                return TokenResponse(
                    access_token=data["access_token"],
                    token_type=data.get("token_type", "Bearer"),
                    expires_in=data.get("expires_in", 3600),
                    refresh_token=data.get("refresh_token"),
                    scope=data.get("scope")
                )
            except (AuthorizationPendingError, SlowDownError, ExpiredTokenError, AccessDeniedError):
                # Re-raise expected errors
                raise
            except httpx.HTTPStatusError as e:
                logger.error(f"Google token poll failed: {e.response.status_code} {e.response.text}")
                raise OAuthError(f"Google token poll failed: {e.response.status_code}")
            except Exception as e:
                if isinstance(e, OAuthError):
                    raise
                logger.error(f"Google token poll error: {e}")
                raise OAuthError(f"Google token poll error: {e}")

    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        """
        Refresh Google access token.

        Args:
            refresh_token: Refresh token from previous TokenResponse

        Returns:
            TokenResponse with new access token
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.TOKEN_URL,
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

                logger.info("Google token refreshed successfully")

                return TokenResponse(
                    access_token=data["access_token"],
                    token_type=data.get("token_type", "Bearer"),
                    expires_in=data.get("expires_in", 3600),
                    refresh_token=data.get("refresh_token", refresh_token),  # Google may not return new refresh token
                    scope=data.get("scope")
                )
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    raise InvalidTokenError("Refresh token is invalid or expired")
                if e.response.status_code == 400:
                    data = e.response.json()
                    if data.get("error") == "invalid_grant":
                        raise InvalidTokenError("Refresh token has been revoked or expired")
                logger.error(f"Google token refresh failed: {e.response.status_code} {e.response.text}")
                raise OAuthError(f"Google token refresh failed: {e.response.status_code}")
            except Exception as e:
                logger.error(f"Google token refresh error: {e}")
                raise OAuthError(f"Google token refresh error: {e}")

    async def validate_token(self, access_token: str) -> UserInfo:
        """
        Validate Google access token and get user info.

        Args:
            access_token: Google access token

        Returns:
            UserInfo with Google user details
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    self.USER_INFO_URL,
                    headers={
                        "Authorization": f"Bearer {access_token}"
                    },
                    timeout=10.0
                )

                if response.status_code == 401:
                    raise InvalidTokenError("Access token is invalid or expired")

                response.raise_for_status()
                data = response.json()

                logger.info(f"Google token validated for user: {data.get('email', data.get('id'))}")

                return UserInfo(
                    provider="google",
                    user_id=str(data["id"]),
                    username=data.get("email", "").split("@")[0] or str(data["id"]),
                    email=data.get("email"),
                    display_name=data.get("name"),
                    avatar_url=data.get("picture")
                )
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    raise InvalidTokenError("Access token is invalid or expired")
                logger.error(f"Google token validation failed: {e.response.status_code} {e.response.text}")
                raise OAuthError(f"Google token validation failed: {e.response.status_code}")
            except InvalidTokenError:
                raise
            except Exception as e:
                logger.error(f"Google token validation error: {e}")
                raise OAuthError(f"Google token validation error: {e}")

    async def revoke_token(self, token: str) -> None:
        """
        Revoke Google access or refresh token.

        Args:
            token: Access token or refresh token to revoke
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.REVOKE_URL,
                    data={"token": token},
                    timeout=10.0
                )

                if response.status_code == 200:
                    logger.info("Google token revoked successfully")
                elif response.status_code == 400:
                    logger.warning("Google token may already be revoked or invalid")
                else:
                    response.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.error(f"Google token revocation failed: {e.response.status_code} {e.response.text}")
                # Don't raise exception - token revocation is best-effort
            except Exception as e:
                logger.error(f"Google token revocation error: {e}")
