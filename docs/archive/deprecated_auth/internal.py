"""
Internal authentication provider for username/password authentication.
.. deprecated:: 2026-01-07
    This module is deprecated and will be removed in a future release.
    The InternalAuthProvider was designed for a separate internal auth
    database (port 5440) that was never deployed.

    Use Google OAuth via MultiTenantAuthService instead:
    - amprealize/multi_tenant/auth_service.py for authentication
    - amprealize/auth/providers/google.py for OAuth flow

    The auth.users table in the main database is the canonical user store.
This provider supports local/air-gapped environments where OAuth is unavailable.
"""

import uuid
from datetime import datetime, timedelta
from typing import List, Optional
import httpx

import os

from amprealize.auth.providers.base import (
    OAuthProvider,
    DeviceCodeResponse,
    TokenResponse,
    UserInfo,
    OAuthError,
    InvalidCredentialsError,
    InvalidTokenError,
    ExpiredTokenError,
)
from amprealize.auth.user_service_postgres import PostgresUserService
from amprealize.auth.jwt_service import JWTService
from amprealize.auth.models import InternalSession
from amprealize.utils.dsn import resolve_postgres_dsn
import warnings

_AUTH_PG_DSN_ENV = "AMPREALIZE_AUTH_PG_DSN"
_DEFAULT_AUTH_PG_DSN = "postgresql://amprealize_auth:dev_auth_pass@localhost:5440/amprealize_auth"


class InternalAuthProvider(OAuthProvider):
    """
    Internal authentication provider using username/password.

    .. deprecated:: 2026-01-07
        Use Google OAuth via MultiTenantAuthService instead.

    This provider implements the OAuthProvider interface but uses
    JWT tokens instead of OAuth. It's designed for:
    - Local development without internet
    - Air-gapped environments
    - Self-hosted Git servers
    - Projects without OAuth provider access
    """

    @property
    def name(self) -> str:
        """Provider name identifier."""
        return "internal"

    def __init__(
        self,
        dsn: Optional[str] = None,
        user_service: Optional[PostgresUserService] = None,
        jwt_service: Optional[JWTService] = None,
    ):
        """
        Initialize internal auth provider.

        Args:
            dsn: PostgreSQL DSN for auth database. If not provided, resolved from
                 environment variables following standard AMPREALIZE_AUTH_PG_DSN pattern.
            user_service: PostgresUserService instance (creates default if not provided)
            jwt_service: JWTService instance (creates default if not provided)
        """
        warnings.warn(
            "InternalAuthProvider is deprecated. Use Google OAuth via "
            "MultiTenantAuthService instead. See amprealize/auth/providers/google.py",
            DeprecationWarning,
            stacklevel=2,
        )
        if user_service is None:
            resolved_dsn = resolve_postgres_dsn(
                service="AUTH",
                explicit_dsn=dsn,
                env_var=_AUTH_PG_DSN_ENV,
                default_dsn=_DEFAULT_AUTH_PG_DSN,
            )
            self.user_service = PostgresUserService(dsn=resolved_dsn)
        else:
            self.user_service = user_service
        self.jwt_service = jwt_service or JWTService()
        self.provider_name = "internal"
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client (unused but required for interface)."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client

    async def start_device_flow(self, scopes: List[str]) -> DeviceCodeResponse:
        """
        Start device flow (adapted for username/password).

        For internal auth, this doesn't make sense in the traditional OAuth way.
        Instead, we return a session ID that can be used with login credentials.

        Args:
            scopes: Requested scopes (unused for internal auth)

        Returns:
            DeviceCodeResponse with session information
        """
        # Generate a session ID that will be used for login
        session_id = str(uuid.uuid4())

        # For internal auth, there's no external verification URI
        # The "user code" is the session ID
        return DeviceCodeResponse(
            verification_uri="internal://login",
            user_code=session_id,
            device_code=session_id,
            expires_in=3600,  # 1 hour to complete login
            interval=5,
        )

    async def login(self, username: str, password: str) -> TokenResponse:
        """
        Login with username and password.

        This is the main authentication method for internal auth.

        Args:
            username: Username
            password: Password

        Returns:
            TokenResponse with access and refresh tokens

        Raises:
            InvalidCredentialsError: If credentials are invalid
        """
        user = self.user_service.authenticate(username, password)
        if not user:
            raise InvalidCredentialsError("Invalid username or password")

        # Generate JWT tokens
        access_token = self.jwt_service.generate_access_token(
            user_id=user.id,
            username=user.username,
            additional_claims={"provider": "internal"},
        )
        refresh_token = self.jwt_service.generate_refresh_token(
            user_id=user.id,
            username=user.username,
        )

        # Get token expiry
        expires_in = int(self.jwt_service.access_token_expiry.total_seconds())

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            token_type="Bearer",
            scope="user",
        )

    async def register(
        self,
        username: str,
        password: str,
        email: str = "",
    ) -> TokenResponse:
        """
        Register a new user and return tokens.

        Args:
            username: Username
            password: Password
            email: Email (optional)

        Returns:
            TokenResponse with access and refresh tokens

        Raises:
            OAuthError: If registration fails
        """
        try:
            user = self.user_service.create_user(
                username=username,
                password=password,
                email=email,
            )
        except ValueError as e:
            raise OAuthError(f"Registration failed: {e}")

        # Generate tokens for newly registered user
        access_token = self.jwt_service.generate_access_token(
            user_id=user.id,
            username=user.username,
            additional_claims={"provider": "internal"},
        )
        refresh_token = self.jwt_service.generate_refresh_token(
            user_id=user.id,
            username=user.username,
        )

        expires_in = int(self.jwt_service.access_token_expiry.total_seconds())

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            token_type="Bearer",
            scope="user",
        )

    async def poll_token(self, device_code: str) -> TokenResponse:
        """
        Poll for token (not applicable for internal auth).

        For internal auth, use login() directly instead.
        This method is kept for OAuthProvider interface compatibility.

        Args:
            device_code: Session ID from start_device_flow

        Returns:
            TokenResponse if session has completed login

        Raises:
            OAuthError: This method should not be used for internal auth
        """
        raise OAuthError(
            "poll_token not supported for internal auth. Use login() instead."
        )

    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        """
        Refresh an access token.

        Args:
            refresh_token: Valid refresh token

        Returns:
            TokenResponse with new access token

        Raises:
            ExpiredTokenError: If refresh token is expired
            InvalidCredentialsError: If refresh token is invalid
        """
        try:
            new_access_token = self.jwt_service.refresh_access_token(refresh_token)
        except Exception as e:
            if "expired" in str(e).lower():
                raise ExpiredTokenError("Refresh token has expired")
            raise InvalidCredentialsError("Invalid refresh token")

        # Decode refresh token to get user info
        try:
            payload = self.jwt_service.validate_token(refresh_token, expected_type="refresh")
            user_id = payload["sub"]

            # Get fresh user data
            user = self.user_service.get_user_by_id(user_id)
            if not user or not user.is_active:
                raise InvalidCredentialsError("User is inactive or not found")

            # Generate new refresh token as well
            new_refresh_token = self.jwt_service.generate_refresh_token(
                user_id=user.id,
                username=user.username,
            )

        except Exception as e:
            raise InvalidCredentialsError(f"Failed to refresh token: {e}")

        expires_in = int(self.jwt_service.access_token_expiry.total_seconds())

        return TokenResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            expires_in=expires_in,
            token_type="Bearer",
            scope="user",
        )

    async def validate_token(self, access_token: str) -> UserInfo:
        """
        Validate an access token and return user info.

        Args:
            access_token: JWT access token

        Returns:
            UserInfo with user details

        Raises:
            ExpiredTokenError: If token is expired
            InvalidCredentialsError: If token is invalid
        """
        try:
            payload = self.jwt_service.validate_token(access_token, expected_type="access")
            user_id = payload["sub"]
            username = payload["username"]

            # Get user details
            user = self.user_service.get_user_by_id(user_id)
            if not user or not user.is_active:
                raise InvalidCredentialsError("User is inactive or not found")

            return UserInfo(
                provider="internal",
                user_id=user.id,
                username=user.username,
                email=user.email,
                display_name=user.username,
                avatar_url=None,
            )

        except Exception as e:
            if "expired" in str(e).lower():
                raise ExpiredTokenError("Access token has expired")
            raise InvalidCredentialsError(f"Invalid access token: {e}")

    async def revoke_token(self, token: str) -> None:
        """
        Revoke a token.

        For JWT tokens, we can't truly revoke them (they're stateless).
        In a production system, you'd maintain a revocation list or use short expiry times.

        Args:
            token: Token to revoke
        """
        # For now, just validate the token exists
        try:
            self.jwt_service.decode_token_without_validation(token)
        except Exception:
            raise InvalidCredentialsError("Invalid token")

        # In a real implementation, you might:
        # 1. Add token to a revocation list (Redis/database)
        # 2. Emit an event for distributed systems
        # 3. Delete associated sessions
        pass

    async def close(self):
        """Close HTTP client if created."""
        if self._http_client:
            await self._http_client.aclose()
