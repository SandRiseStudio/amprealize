"""
User service for internal authentication.

.. deprecated:: 2026-01-08
    This module is deprecated and will be removed in a future release.
    The internal_users table and UserService were designed for a
    separate internal auth database that was never deployed.

    Use auth.users table via MultiTenantAuthService instead:
    - amprealize/multi_tenant/auth_service.py for user management
    - amprealize/multi_tenant/organization_service.py for org/project management

    See AGENTS.md for the canonical auth architecture.

Handles user CRUD operations, password management, and authentication.
Migrated from SQLite to PostgreSQL for consistency with other services.
"""

import uuid
import secrets
import bcrypt
import os
import warnings
from datetime import datetime, timedelta
from typing import Optional, List

import psycopg2
import psycopg2.extras

from amprealize.auth.models import User, PasswordResetToken
from amprealize.utils.dsn import resolve_postgres_dsn

_AUTH_PG_DSN_ENV = "AMPREALIZE_AUTH_PG_DSN"
_DEFAULT_PG_DSN = "postgresql://amprealize_auth:dev_auth_pass@localhost:5440/amprealize_auth"


class UserService:
    """Service for managing internal users and authentication.

    .. deprecated:: 2026-01-08
        Use MultiTenantAuthService with auth.users table instead.

    Uses PostgreSQL for persistence, consistent with other Amprealize services.
    DSN resolution follows the standard pattern via resolve_postgres_dsn().
    """

    def __init__(self, dsn: Optional[str] = None):
        """
        Initialize user service.

        Args:
            dsn: PostgreSQL DSN. If not provided, resolved from environment
                 variables following the standard AMPREALIZE_PG_* pattern.
        """
        warnings.warn(
            "UserService is deprecated. Use MultiTenantAuthService "
            "with auth.users table instead. See amprealize/multi_tenant/auth_service.py",
            DeprecationWarning,
            stacklevel=2,
        )
        self._dsn = resolve_postgres_dsn(
            service="AUTH",
            explicit_dsn=dsn,
            env_var=_AUTH_PG_DSN_ENV,
            default_dsn=_DEFAULT_PG_DSN,
        )
        self._conn: Optional[psycopg2.extensions.connection] = None

    def _get_connection(self) -> psycopg2.extensions.connection:
        """Get or create database connection."""
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self._dsn)
            self._conn.autocommit = False
        return self._conn

    def _execute(self, query: str, params: tuple = (), fetch: bool = False):
        """Execute a query with proper connection handling."""
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, params)
                if fetch:
                    return cur.fetchall()
                conn.commit()
                return cur.rowcount
        except Exception:
            conn.rollback()
            raise

    def _execute_one(self, query: str, params: tuple = ()):
        """Execute a query and return single row."""
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, params)
                return cur.fetchone()
        except Exception:
            conn.rollback()
            raise

    def close(self):
        """Close database connection."""
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None

    def _row_to_user(self, row: dict) -> User:
        """Convert database row to User object."""
        return User(
            id=row["id"],
            username=row["username"],
            email=row["email"] or "",
            hashed_password=row.get("hashed_password"),  # Can be None for OAuth users
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            is_active=row["is_active"],
            is_admin=row["is_admin"],
            display_name=row.get("display_name"),
        )

    def _hash_password(self, password: str) -> str:
        """
        Hash a password using bcrypt.

        Args:
            password: Plain text password

        Returns:
            Bcrypt hashed password
        """
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
        return hashed.decode("utf-8")

    def _verify_password(self, password: str, hashed_password: str) -> bool:
        """
        Verify a password against its hash.

        Args:
            password: Plain text password
            hashed_password: Bcrypt hashed password

        Returns:
            True if password matches
        """
        return bcrypt.checkpw(
            password.encode("utf-8"),
            hashed_password.encode("utf-8")
        )

    def create_user(
        self,
        username: str,
        password: Optional[str] = None,
        email: str = "",
        is_admin: bool = False,
        display_name: Optional[str] = None,
    ) -> User:
        """
        Create a new user.

        Args:
            username: Unique username
            password: Plain text password (will be hashed). None for OAuth-only users.
            email: Email address (optional)
            is_admin: Whether user has admin privileges
            display_name: User's display name (optional, typically from OAuth)

        Returns:
            Created User object

        Raises:
            ValueError: If username already exists or validation fails
        """
        # Validate username
        if not username or len(username) < 3:
            raise ValueError("Username must be at least 3 characters")

        # Only validate password if provided (OAuth users don't have passwords)
        if password is not None and len(password) < 8:
            raise ValueError("Password must be at least 8 characters")

        # Check if username exists
        if self.get_user_by_username(username):
            raise ValueError(f"Username '{username}' already exists")

        # Create user
        user_id = str(uuid.uuid4())
        hashed_password = self._hash_password(password) if password else None
        now = datetime.utcnow()

        user = User(
            id=user_id,
            username=username,
            email=email,
            hashed_password=hashed_password,
            created_at=now,
            updated_at=now,
            is_active=True,
            is_admin=is_admin,
            display_name=display_name,
        )

        # Insert into database
        self._execute(
            """
            INSERT INTO internal_users
            (id, username, email, hashed_password, display_name, created_at, updated_at, is_active, is_admin)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user.id,
                user.username,
                user.email or None,
                user.hashed_password,
                user.display_name,
                user.created_at,
                user.updated_at,
                user.is_active,
                user.is_admin,
            ),
        )

        return user

    def authenticate(self, username: str, password: str) -> Optional[User]:
        """
        Authenticate a user with username/password.

        Args:
            username: Username
            password: Plain text password

        Returns:
            User object if authentication succeeds, None otherwise
        """
        user = self.get_user_by_username(username)
        if not user:
            return None

        if not user.is_active:
            return None

        # OAuth-only users can't authenticate with password
        if not user.hashed_password:
            return None

        if not self._verify_password(password, user.hashed_password):
            return None

        return user

    def get_user_by_id(self, user_id: str) -> Optional[User]:
        """
        Get user by ID.

        Args:
            user_id: User ID

        Returns:
            User object or None
        """
        row = self._execute_one(
            "SELECT * FROM internal_users WHERE id = %s",
            (user_id,),
        )

        if not row:
            return None

        return self._row_to_user(row)

    def get_user_by_username(self, username: str) -> Optional[User]:
        """
        Get user by username.

        Args:
            username: Username

        Returns:
            User object or None
        """
        row = self._execute_one(
            "SELECT * FROM internal_users WHERE username = %s",
            (username,),
        )

        if not row:
            return None

        return self._row_to_user(row)

    def update_password(self, user_id: str, new_password: str) -> bool:
        """
        Update user password.

        Args:
            user_id: User ID
            new_password: New plain text password

        Returns:
            True if update succeeded

        Raises:
            ValueError: If validation fails
        """
        if not new_password or len(new_password) < 8:
            raise ValueError("Password must be at least 8 characters")

        hashed_password = self._hash_password(new_password)

        # Note: updated_at is auto-updated by trigger in PostgreSQL
        rowcount = self._execute(
            """
            UPDATE internal_users
            SET hashed_password = %s
            WHERE id = %s
            """,
            (hashed_password, user_id),
        )
        return rowcount > 0

    def delete_user(self, user_id: str) -> bool:
        """
        Delete a user (soft delete by setting is_active=False).

        Args:
            user_id: User ID

        Returns:
            True if user was deleted
        """
        rowcount = self._execute(
            """
            UPDATE internal_users
            SET is_active = FALSE
            WHERE id = %s
            """,
            (user_id,),
        )
        return rowcount > 0

    def list_users(self, active_only: bool = True) -> List[User]:
        """
        List all users.

        Args:
            active_only: Only return active users

        Returns:
            List of User objects
        """
        if active_only:
            query = "SELECT * FROM internal_users WHERE is_active = TRUE ORDER BY created_at DESC"
        else:
            query = "SELECT * FROM internal_users ORDER BY created_at DESC"

        rows = self._execute(query, fetch=True)
        return [self._row_to_user(row) for row in (rows or [])]

    def create_reset_token(self, user_id: str, expiry_hours: int = 24) -> PasswordResetToken:
        """
        Create a password reset token.

        Args:
            user_id: User ID
            expiry_hours: Hours until token expires

        Returns:
            PasswordResetToken object

        Raises:
            ValueError: If user not found
        """
        user = self.get_user_by_id(user_id)
        if not user:
            raise ValueError("User not found")

        token_id = str(uuid.uuid4())
        token = secrets.token_urlsafe(32)
        now = datetime.utcnow()
        expires_at = now + timedelta(hours=expiry_hours)

        reset_token = PasswordResetToken(
            id=token_id,
            user_id=user_id,
            token=token,
            created_at=now,
            expires_at=expires_at,
        )

        self._execute(
            """
            INSERT INTO password_reset_tokens
            (id, user_id, token, created_at, expires_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                reset_token.id,
                reset_token.user_id,
                reset_token.token,
                reset_token.created_at,
                reset_token.expires_at,
            ),
        )

        return reset_token

    def validate_reset_token(self, token: str) -> Optional[PasswordResetToken]:
        """
        Validate a reset token.

        Args:
            token: Reset token string

        Returns:
            PasswordResetToken if valid, None otherwise
        """
        row = self._execute_one(
            "SELECT * FROM password_reset_tokens WHERE token = %s",
            (token,),
        )

        if not row:
            return None

        reset_token = PasswordResetToken(
            id=row["id"],
            user_id=row["user_id"],
            token=row["token"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            used_at=row["used_at"],
        )

        if not reset_token.is_valid:
            return None

        return reset_token

    def use_reset_token(self, token: str, new_password: str) -> bool:
        """
        Use a reset token to change password.

        Args:
            token: Reset token string
            new_password: New password

        Returns:
            True if password was reset

        Raises:
            ValueError: If token invalid or password validation fails
        """
        reset_token = self.validate_reset_token(token)
        if not reset_token:
            raise ValueError("Invalid or expired reset token")

        # Update password
        self.update_password(reset_token.user_id, new_password)

        # Mark token as used
        now = datetime.utcnow()
        self._execute(
            "UPDATE password_reset_tokens SET used_at = %s WHERE id = %s",
            (now, reset_token.id),
        )

        return True
