"""
JWT token service for internal authentication.

Generates and validates JWT tokens for access and refresh tokens.
"""

import os
import jwt
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
import secrets


class JWTService:
    """Service for generating and validating JWT tokens."""

    def __init__(
        self,
        secret_key: Optional[str] = None,
        access_token_expiry_hours: int = 24,
        refresh_token_expiry_days: int = 30,
        algorithm: str = "HS256",
    ):
        """
        Initialize JWT service.

        Args:
            secret_key: Secret key for signing tokens (from env if not provided)
            access_token_expiry_hours: Hours until access token expires
            refresh_token_expiry_days: Days until refresh token expires
            algorithm: JWT algorithm to use
        """
        self.secret_key = secret_key or os.environ.get(
            "AMPREALIZE_JWT_SECRET",
            secrets.token_urlsafe(32)  # Generate if not provided
        )
        self.access_token_expiry = timedelta(hours=access_token_expiry_hours)
        self.refresh_token_expiry = timedelta(days=refresh_token_expiry_days)
        self.algorithm = algorithm

    def generate_access_token(
        self,
        user_id: str,
        username: str,
        additional_claims: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Generate an access token.

        Args:
            user_id: User's unique ID
            username: User's username
            additional_claims: Optional additional JWT claims

        Returns:
            JWT access token string
        """
        now = datetime.utcnow()
        expires_at = now + self.access_token_expiry

        payload = {
            "sub": user_id,  # Subject (user ID)
            "username": username,
            "type": "access",
            "iat": now,  # Issued at
            "exp": expires_at,  # Expiration
            "jti": secrets.token_urlsafe(16),  # Unique ID to avoid token reuse collisions
        }

        if additional_claims:
            payload.update(additional_claims)

        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def generate_refresh_token(
        self,
        user_id: str,
        username: str,
    ) -> str:
        """
        Generate a refresh token.

        Args:
            user_id: User's unique ID
            username: User's username

        Returns:
            JWT refresh token string
        """
        now = datetime.utcnow()
        expires_at = now + self.refresh_token_expiry

        payload = {
            "sub": user_id,
            "username": username,
            "type": "refresh",
            "iat": now,
            "exp": expires_at,
            "jti": secrets.token_urlsafe(16),  # JWT ID for uniqueness
        }

        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def validate_token(self, token: str, expected_type: str = "access") -> Dict[str, Any]:
        """
        Validate and decode a JWT token.

        Args:
            token: JWT token string
            expected_type: Expected token type ("access" or "refresh")

        Returns:
            Decoded token payload

        Raises:
            jwt.ExpiredSignatureError: Token has expired
            jwt.InvalidTokenError: Token is invalid
            ValueError: Token type mismatch
        """
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
            )

            # Verify token type
            token_type = payload.get("type")
            if token_type != expected_type:
                raise ValueError(
                    f"Invalid token type: expected '{expected_type}', got '{token_type}'"
                )

            return payload

        except jwt.ExpiredSignatureError:
            raise
        except jwt.InvalidTokenError:
            raise

    def refresh_access_token(self, refresh_token: str) -> str:
        """
        Generate a new access token from a valid refresh token.

        Args:
            refresh_token: Valid refresh token

        Returns:
            New access token

        Raises:
            jwt.ExpiredSignatureError: Refresh token has expired
            jwt.InvalidTokenError: Refresh token is invalid
        """
        payload = self.validate_token(refresh_token, expected_type="refresh")
        user_id = payload["sub"]
        username = payload["username"]

        return self.generate_access_token(user_id, username)

    def decode_token_without_validation(self, token: str) -> Dict[str, Any]:
        """
        Decode token without validating signature or expiry (for debugging).

        Args:
            token: JWT token string

        Returns:
            Decoded payload
        """
        return jwt.decode(
            token,
            options={"verify_signature": False, "verify_exp": False},
        )

    def get_token_expiry(self, token: str) -> datetime:
        """
        Get expiration datetime from a token.

        Args:
            token: JWT token string

        Returns:
            Expiration datetime
        """
        payload = self.decode_token_without_validation(token)
        exp_timestamp = payload.get("exp")
        if exp_timestamp:
            return datetime.fromtimestamp(exp_timestamp, tz=timezone.utc)
        raise ValueError("Token has no expiration claim")
