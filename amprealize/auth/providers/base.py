"""
Base classes and exceptions for OAuth provider implementations.

This module defines the abstract OAuthProvider interface that all authentication
providers must implement, along with data classes for responses and custom exceptions.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


# Custom exceptions
class OAuthError(Exception):
    """Base exception for OAuth errors"""
    pass


class AuthorizationPendingError(OAuthError):
    """User hasn't authorized yet (continue polling)"""
    pass


class SlowDownError(OAuthError):
    """Polling too fast, client should increase interval"""
    def __init__(self, retry_after: int = 5):
        self.retry_after = retry_after
        super().__init__(f"Polling too fast. Retry after {retry_after} seconds")


class ExpiredTokenError(OAuthError):
    """Device code or token has expired"""
    pass


class AccessDeniedError(OAuthError):
    """User denied authorization"""
    pass


class InvalidTokenError(OAuthError):
    """Token is invalid or has been revoked"""
    pass


class InvalidCredentialsError(OAuthError):
    """Invalid username/password (for internal auth)"""
    pass


# Data classes
@dataclass
class DeviceCodeResponse:
    """OAuth device code flow initial response"""
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int  # seconds between polling attempts

    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "device_code": self.device_code,
            "user_code": self.user_code,
            "verification_uri": self.verification_uri,
            "expires_in": self.expires_in,
            "interval": self.interval
        }


@dataclass
class TokenResponse:
    """OAuth token response"""
    access_token: str
    token_type: str
    expires_in: int
    refresh_token: Optional[str] = None
    scope: Optional[str] = None

    def to_dict(self):
        """Convert to dictionary for API responses"""
        result = {
            "access_token": self.access_token,
            "token_type": self.token_type,
            "expires_in": self.expires_in
        }
        if self.refresh_token:
            result["refresh_token"] = self.refresh_token
        if self.scope:
            result["scope"] = self.scope
        return result


@dataclass
class UserInfo:
    """Normalized user information across providers"""
    provider: str
    user_id: str  # provider-specific ID
    username: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None

    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "provider": self.provider,
            "user_id": self.user_id,
            "username": self.username,
            "email": self.email,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url
        }


# Abstract base class
class OAuthProvider(ABC):
    """
    Base class for OAuth providers.

    All authentication providers (GitHub, GitLab, Bitbucket, Google, Internal)
    must implement this interface to ensure consistent behavior across platforms.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Provider name (github, gitlab, bitbucket, google, internal).

        Returns:
            str: Lowercase provider identifier
        """
        pass

    @abstractmethod
    async def start_device_flow(self, scopes: list[str]) -> DeviceCodeResponse:
        """
        Initiate OAuth device flow.

        Args:
            scopes: List of OAuth scopes to request

        Returns:
            DeviceCodeResponse: Device code and user verification URI

        Raises:
            OAuthError: If device flow initiation fails
        """
        pass

    @abstractmethod
    async def poll_token(self, device_code: str) -> TokenResponse:
        """
        Poll for access token after user authorization.

        Args:
            device_code: Device code from start_device_flow()

        Returns:
            TokenResponse: Access token and metadata

        Raises:
            AuthorizationPendingError: User hasn't authorized yet (continue polling)
            SlowDownError: Polling too fast, increase interval
            ExpiredTokenError: Device code expired
            AccessDeniedError: User denied authorization
            OAuthError: Other errors
        """
        pass

    @abstractmethod
    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        """
        Refresh an expired access token.

        Args:
            refresh_token: Refresh token from previous TokenResponse

        Returns:
            TokenResponse: New access token

        Raises:
            InvalidTokenError: Refresh token is invalid/expired
            OAuthError: Other errors
        """
        pass

    @abstractmethod
    async def validate_token(self, access_token: str) -> UserInfo:
        """
        Validate token and return user information.

        Args:
            access_token: Access token to validate

        Returns:
            UserInfo: User information from the provider

        Raises:
            InvalidTokenError: Token is invalid/expired
            OAuthError: Other errors
        """
        pass

    @abstractmethod
    async def revoke_token(self, token: str) -> None:
        """
        Revoke a token (logout).

        Args:
            token: Access token or refresh token to revoke

        Raises:
            OAuthError: If revocation fails
        """
        pass
