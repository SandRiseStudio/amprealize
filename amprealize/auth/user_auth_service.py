"""User authentication service for auth.users table.

This service provides user CRUD operations for the canonical auth.users table,
replacing the deprecated PostgresUserService which used internal_users.

Auth Architecture (post-consolidation):
- auth.users: Canonical user table for human users (OAuth and internal)
- execution.agents: AI agent definitions (with owner_id FK to auth.users)
- auth.service_principals: API credentials for agents/services

This service does NOT use the deprecated internal_users table.
"""
from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import bcrypt
import psycopg2
import psycopg2.extras
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


@dataclass
class User:
    """User model for auth.users table."""

    id: str
    email: Optional[str]
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    is_active: bool = True
    email_verified: bool = False
    password_hash: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class UserAuthService:
    """Service for user authentication operations using auth.users table.

    This replaces PostgresUserService which used the deprecated internal_users table.
    """

    def __init__(self, dsn: Optional[str] = None):
        """Initialize the service.

        Args:
            dsn: PostgreSQL connection string. If None, uses DATABASE_URL env var.
        """
        self._dsn = dsn or os.environ.get("DATABASE_URL")
        if not self._dsn:
            raise ValueError("DATABASE_URL or dsn parameter required")

    def _get_connection(self):
        """Get a database connection."""
        return psycopg2.connect(self._dsn)

    def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Get a user by ID.

        Args:
            user_id: User ID

        Returns:
            User object or None if not found
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT id, email, display_name, avatar_url, is_active,
                               email_verified, password_hash, created_at, updated_at, metadata
                        FROM auth.users
                        WHERE id = %s
                        """,
                        (user_id,)
                    )
                    row = cur.fetchone()
                    if row:
                        return User(
                            id=row["id"],
                            email=row["email"],
                            display_name=row["display_name"],
                            avatar_url=row["avatar_url"],
                            is_active=row["is_active"],
                            email_verified=row["email_verified"] or False,
                            password_hash=row.get("password_hash"),
                            created_at=row["created_at"],
                            updated_at=row["updated_at"],
                            metadata=row.get("metadata") or {},
                        )
        except Exception as e:
            logger.error(f"Failed to get user by ID {user_id}: {e}")
        return None

    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get a user by email.

        Args:
            email: User email

        Returns:
            User object or None if not found
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT id, email, display_name, avatar_url, is_active,
                               email_verified, password_hash, created_at, updated_at, metadata
                        FROM auth.users
                        WHERE LOWER(email) = LOWER(%s)
                        """,
                        (email,)
                    )
                    row = cur.fetchone()
                    if row:
                        return User(
                            id=row["id"],
                            email=row["email"],
                            display_name=row["display_name"],
                            avatar_url=row["avatar_url"],
                            is_active=row["is_active"],
                            email_verified=row["email_verified"] or False,
                            password_hash=row.get("password_hash"),
                            created_at=row["created_at"],
                            updated_at=row["updated_at"],
                            metadata=row.get("metadata") or {},
                        )
        except Exception as e:
            logger.error(f"Failed to get user by email {email}: {e}")
        return None

    def create_user(
        self,
        email: str,
        display_name: Optional[str] = None,
        password: Optional[str] = None,
        user_id: Optional[str] = None,
        email_verified: bool = False,
        avatar_url: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[User]:
        """Create a new user.

        Args:
            email: User email (required)
            display_name: Display name
            password: Plain text password (will be hashed)
            user_id: Optional user ID (generated if not provided)
            email_verified: Whether email is verified
            avatar_url: Avatar URL
            metadata: Additional metadata

        Returns:
            Created User object or None on error
        """
        if not email:
            raise ValueError("Email is required")

        user_id = user_id or str(uuid.uuid4())
        password_hash = None
        if password:
            password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

        try:
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        """
                        INSERT INTO auth.users
                        (id, email, display_name, avatar_url, is_active, email_verified, password_hash, metadata)
                        VALUES (%s, %s, %s, %s, true, %s, %s, %s)
                        RETURNING id, email, display_name, avatar_url, is_active,
                                  email_verified, password_hash, created_at, updated_at, metadata
                        """,
                        (user_id, email, display_name, avatar_url, email_verified, password_hash,
                         psycopg2.extras.Json(metadata or {}))
                    )
                    row = cur.fetchone()
                    conn.commit()

                    if row:
                        logger.info(f"Created user {user_id} with email {email}")
                        return User(
                            id=row["id"],
                            email=row["email"],
                            display_name=row["display_name"],
                            avatar_url=row["avatar_url"],
                            is_active=row["is_active"],
                            email_verified=row["email_verified"] or False,
                            password_hash=row.get("password_hash"),
                            created_at=row["created_at"],
                            updated_at=row["updated_at"],
                            metadata=row.get("metadata") or {},
                        )
        except psycopg2.errors.UniqueViolation:
            logger.warning(f"User with email {email} already exists")
            return self.get_user_by_email(email)
        except Exception as e:
            logger.error(f"Failed to create user: {e}")
        return None

    def verify_password(self, user_id: str, password: str) -> bool:
        """Verify a user's password.

        Args:
            user_id: User ID
            password: Plain text password to verify

        Returns:
            True if password matches, False otherwise
        """
        user = self.get_user_by_id(user_id)
        if not user or not user.password_hash:
            return False

        try:
            return bcrypt.checkpw(password.encode(), user.password_hash.encode())
        except Exception as e:
            logger.error(f"Password verification failed: {e}")
            return False

    def set_email_verified(self, user_id: str, verified: bool = True) -> bool:
        """Set email verification status.

        Args:
            user_id: User ID
            verified: Whether email is verified

        Returns:
            True if updated successfully
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE auth.users SET email_verified = %s, updated_at = NOW() WHERE id = %s",
                        (verified, user_id)
                    )
                    conn.commit()
                    return cur.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to update email verification for {user_id}: {e}")
        return False

    def update_user(
        self,
        user_id: str,
        display_name: Optional[str] = None,
        avatar_url: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[User]:
        """Update user fields.

        Args:
            user_id: User ID
            display_name: New display name (None = no change)
            avatar_url: New avatar URL (None = no change)
            metadata: New metadata (None = no change)

        Returns:
            Updated User object or None on error
        """
        updates = []
        values = []

        if display_name is not None:
            updates.append("display_name = %s")
            values.append(display_name)

        if avatar_url is not None:
            updates.append("avatar_url = %s")
            values.append(avatar_url)

        if metadata is not None:
            updates.append("metadata = %s")
            values.append(psycopg2.extras.Json(metadata))

        if not updates:
            return self.get_user_by_id(user_id)

        updates.append("updated_at = NOW()")
        values.append(user_id)

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE auth.users SET {', '.join(updates)} WHERE id = %s",
                        values
                    )
                    conn.commit()
                    return self.get_user_by_id(user_id)
        except Exception as e:
            logger.error(f"Failed to update user {user_id}: {e}")
        return None

    def deactivate_user(self, user_id: str) -> bool:
        """Deactivate a user.

        Args:
            user_id: User ID

        Returns:
            True if deactivated successfully
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE auth.users SET is_active = false, updated_at = NOW() WHERE id = %s",
                        (user_id,)
                    )
                    conn.commit()
                    return cur.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to deactivate user {user_id}: {e}")
        return False

    def create_email_verification_token(self, user_id: str, email: str) -> str:
        """Create an email verification token.

        This creates a secure token stored in auth.email_verification_tokens table.

        Args:
            user_id: User ID
            email: Email to verify

        Returns:
            Verification token string
        """
        import secrets
        token = secrets.token_urlsafe(32)

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    # Create table if not exists
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS auth.email_verification_tokens (
                            id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
                            user_id VARCHAR(36) NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
                            email VARCHAR(255) NOT NULL,
                            token VARCHAR(255) NOT NULL UNIQUE,
                            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
                            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                        )
                    """)

                    # Delete expired tokens for this user
                    cur.execute(
                        "DELETE FROM auth.email_verification_tokens WHERE user_id = %s OR expires_at < NOW()",
                        (user_id,)
                    )

                    # Insert new token (expires in 24 hours)
                    cur.execute(
                        """
                        INSERT INTO auth.email_verification_tokens (user_id, email, token, expires_at)
                        VALUES (%s, %s, %s, NOW() + INTERVAL '24 hours')
                        """,
                        (user_id, email, token)
                    )
                    conn.commit()
                    return token
        except Exception as e:
            logger.error(f"Failed to create verification token: {e}")
            raise

    def verify_email_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify an email verification token.

        Args:
            token: Verification token

        Returns:
            Dict with user_id and email if valid, None otherwise
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT user_id, email FROM auth.email_verification_tokens
                        WHERE token = %s AND expires_at > NOW()
                        """,
                        (token,)
                    )
                    row = cur.fetchone()

                    if row:
                        # Mark email as verified
                        cur.execute(
                            "UPDATE auth.users SET email_verified = true, updated_at = NOW() WHERE id = %s",
                            (row["user_id"],)
                        )

                        # Delete the used token
                        cur.execute(
                            "DELETE FROM auth.email_verification_tokens WHERE token = %s",
                            (token,)
                        )
                        conn.commit()

                        return {"user_id": row["user_id"], "email": row["email"]}
        except Exception as e:
            logger.error(f"Failed to verify email token: {e}")
        return None

    def create_mfa_device(
        self,
        user_id: str,
        secret_encrypted: str,
        device_type: str = "totp",
        device_name: str = "Authenticator App",
    ) -> str:
        """Create an MFA device for a user.

        Args:
            user_id: User ID
            secret_encrypted: Encrypted TOTP secret
            device_type: Type of MFA device (totp)
            device_name: Human-readable device name

        Returns:
            Device ID
        """
        device_id = str(uuid.uuid4())

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    # Create table if not exists
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS auth.mfa_devices (
                            id VARCHAR(36) PRIMARY KEY,
                            user_id VARCHAR(36) NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
                            device_type VARCHAR(20) NOT NULL DEFAULT 'totp',
                            device_name VARCHAR(255),
                            secret_encrypted TEXT NOT NULL,
                            is_verified BOOLEAN NOT NULL DEFAULT FALSE,
                            last_used_at TIMESTAMP WITH TIME ZONE,
                            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                        )
                    """)

                    cur.execute(
                        """
                        INSERT INTO auth.mfa_devices (id, user_id, device_type, device_name, secret_encrypted)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (device_id, user_id, device_type, device_name, secret_encrypted)
                    )
                    conn.commit()
                    return device_id
        except Exception as e:
            logger.error(f"Failed to create MFA device: {e}")
            raise
