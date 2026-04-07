"""OAuth provider implementations for Amprealize multi-provider authentication.

Supports:
- GitHub OAuth (device flow)
- Google OAuth (web flow + device flow)

Note: InternalAuthProvider was deprecated on 2026-01-09.
User authentication is now handled via auth.users table and UserAuthService.
"""

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
    InvalidCredentialsError,
    OAuthError,
)
from .github import GitHubOAuthProvider
from .google import GoogleOAuthProvider
from .registry import ProviderRegistry

__all__ = [
    "OAuthProvider",
    "DeviceCodeResponse",
    "TokenResponse",
    "UserInfo",
    "AuthorizationPendingError",
    "SlowDownError",
    "ExpiredTokenError",
    "AccessDeniedError",
    "InvalidTokenError",
    "InvalidCredentialsError",
    "OAuthError",
    "GitHubOAuthProvider",
    "GoogleOAuthProvider",
    "ProviderRegistry",
]
