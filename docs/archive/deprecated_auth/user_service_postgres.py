"""
PostgreSQL user service for internal authentication.
.. deprecated:: 2026-01-07
    This module is deprecated and will be removed in a future release.
    The internal_users table and PostgresUserService were designed for a
    separate internal auth database that was never deployed.

    Use auth.users table via MultiTenantAuthService instead:
    - amprealize/multi_tenant/auth_service.py for user management
    - amprealize/multi_tenant/organization_service.py for org/project management

    See AGENTS.md for the canonical auth architecture.
Handles user CRUD operations, password management, and authentication
using PostgreSQL as the backing store.
"""

from __future__ import annotations

import uuid
import secrets
import bcrypt
import warnings
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

from amprealize.auth.models import User, PasswordResetToken, InternalSession
from amprealize.storage.postgres_pool import PostgresPool


def _utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class PostgresUserService:
    """PostgreSQL-backed service for managing internal users and authentication.

    .. deprecated:: 2026-01-07
        Use MultiTenantAuthService with auth.users table instead.

    Parity implementation with SQLite UserService, using PostgresPool for
    connection management.

    Args:
        dsn: PostgreSQL connection string (postgresql://user:pass@host:port/dbname)
    """

    def __init__(self, dsn: str):
        """
        Initialize PostgreSQL user service.

        Args:
            dsn: PostgreSQL connection string
        """
        warnings.warn(
            "PostgresUserService is deprecated. Use MultiTenantAuthService "
            "with auth.users table instead. See amprealize/multi_tenant/auth_service.py",
            DeprecationWarning,
            stacklevel=2,
        )
        self._pool = PostgresPool(dsn=dsn, service_name="auth")
        self._init_db()

    @contextmanager
    def _connection(self, *, autocommit: bool = True):
        """Get a connection from the pool."""
        with self._pool.connection(autocommit=autocommit) as conn:
            yield conn

    def _init_db(self):
        """Initialize database tables."""
        with self._connection() as conn:
            with conn.cursor() as cur:
                # Users table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS internal_users (
                        id VARCHAR(36) PRIMARY KEY,
                        username VARCHAR(255) UNIQUE NOT NULL,
                        email VARCHAR(255),
                        hashed_password TEXT,
                        display_name VARCHAR(255),
                        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
                        is_active BOOLEAN DEFAULT TRUE,
                        is_admin BOOLEAN DEFAULT FALSE
                    )
                """)

                # Password reset tokens table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS password_reset_tokens (
                        id VARCHAR(36) PRIMARY KEY,
                        user_id VARCHAR(36) REFERENCES internal_users(id) ON DELETE CASCADE,
                        token VARCHAR(255) UNIQUE NOT NULL,
                        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                        expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
                        used_at TIMESTAMP WITH TIME ZONE
                    )
                """)

                # Sessions table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS internal_sessions (
                        session_id VARCHAR(36) PRIMARY KEY,
                        user_id VARCHAR(36) REFERENCES internal_users(id) ON DELETE CASCADE,
                        username VARCHAR(255) NOT NULL,
                        access_token TEXT NOT NULL,
                        refresh_token TEXT NOT NULL,
                        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                        expires_at TIMESTAMP WITH TIME ZONE NOT NULL
                    )
                """)

                # Indexes
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_internal_users_username
                    ON internal_users(username)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user_id
                    ON password_reset_tokens(user_id)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_internal_sessions_user_id
                    ON internal_sessions(user_id)
                """)

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
        now = _utc_now()

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
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO internal_users
                    (id, username, email, hashed_password, display_name, created_at, updated_at, is_active, is_admin)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user.id,
                        user.username,
                        user.email,
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
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM internal_users WHERE id = %s",
                    (user_id,),
                )
                row = cur.fetchone()

                if not row:
                    return None

                return self._row_to_user(row, cur.description)

    def get_user_by_username(self, username: str) -> Optional[User]:
        """
        Get user by username.

        Args:
            username: Username

        Returns:
            User object or None
        """
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM internal_users WHERE username = %s",
                    (username,),
                )
                row = cur.fetchone()

                if not row:
                    return None

                return self._row_to_user(row, cur.description)

    def _row_to_user(self, row: tuple, description) -> User:
        """Convert a database row to a User object."""
        columns = [col[0] for col in description]
        row_dict = dict(zip(columns, row))

        return User(
            id=row_dict["id"],
            username=row_dict["username"],
            email=row_dict["email"] or "",
            hashed_password=row_dict.get("hashed_password"),  # Can be None for OAuth users
            created_at=row_dict["created_at"],
            updated_at=row_dict["updated_at"],
            is_active=bool(row_dict["is_active"]),
            is_admin=bool(row_dict["is_admin"]),
            display_name=row_dict.get("display_name"),
        )

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
        now = _utc_now()

        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE internal_users
                    SET hashed_password = %s, updated_at = %s
                    WHERE id = %s
                    """,
                    (hashed_password, now, user_id),
                )
                return cur.rowcount > 0

    def delete_user(self, user_id: str) -> bool:
        """
        Delete a user (soft delete by setting is_active=False).

        Args:
            user_id: User ID

        Returns:
            True if user was deleted
        """
        now = _utc_now()

        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE internal_users
                    SET is_active = %s, updated_at = %s
                    WHERE id = %s
                    """,
                    (False, now, user_id),
                )
                return cur.rowcount > 0

    def list_users(self, active_only: bool = True) -> List[User]:
        """
        List all users.

        Args:
            active_only: If True, only return active users

        Returns:
            List of User objects
        """
        with self._connection() as conn:
            with conn.cursor() as cur:
                if active_only:
                    cur.execute(
                        "SELECT * FROM internal_users WHERE is_active = TRUE ORDER BY username"
                    )
                else:
                    cur.execute("SELECT * FROM internal_users ORDER BY username")

                rows = cur.fetchall()
                return [self._row_to_user(row, cur.description) for row in rows]

    # Password Reset Methods

    def create_password_reset_token(
        self,
        user_id: str,
        expires_hours: int = 24,
    ) -> PasswordResetToken:
        """
        Create a password reset token for a user.

        Args:
            user_id: User ID
            expires_hours: Token validity in hours (default 24)

        Returns:
            PasswordResetToken object
        """
        token_id = str(uuid.uuid4())
        token = secrets.token_urlsafe(32)
        now = _utc_now()
        expires_at = now + timedelta(hours=expires_hours)

        reset_token = PasswordResetToken(
            id=token_id,
            user_id=user_id,
            token=token,
            created_at=now,
            expires_at=expires_at,
            used_at=None,
        )

        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO password_reset_tokens
                    (id, user_id, token, created_at, expires_at, used_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        reset_token.id,
                        reset_token.user_id,
                        reset_token.token,
                        reset_token.created_at,
                        reset_token.expires_at,
                        reset_token.used_at,
                    ),
                )

        return reset_token

    def validate_reset_token(self, token: str) -> Optional[PasswordResetToken]:
        """
        Validate a password reset token.

        Args:
            token: Token string

        Returns:
            PasswordResetToken if valid, None otherwise
        """
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM password_reset_tokens
                    WHERE token = %s AND used_at IS NULL AND expires_at > NOW()
                    """,
                    (token,),
                )
                row = cur.fetchone()

                if not row:
                    return None

                columns = [col[0] for col in cur.description]
                row_dict = dict(zip(columns, row))

                return PasswordResetToken(
                    id=row_dict["id"],
                    user_id=row_dict["user_id"],
                    token=row_dict["token"],
                    created_at=row_dict["created_at"],
                    expires_at=row_dict["expires_at"],
                    used_at=row_dict["used_at"],
                )

    def use_reset_token(self, token: str, new_password: str) -> bool:
        """
        Use a password reset token to change password.

        Args:
            token: Token string
            new_password: New password

        Returns:
            True if password was reset successfully
        """
        reset_token = self.validate_reset_token(token)
        if not reset_token:
            return False

        # Update password
        if not self.update_password(reset_token.user_id, new_password):
            return False

        # Mark token as used
        now = _utc_now()
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE password_reset_tokens SET used_at = %s WHERE token = %s",
                    (now, token),
                )

        return True

    # Session Methods

    def create_session(
        self,
        user_id: str,
        username: str,
        access_token: str,
        refresh_token: str,
        expires_hours: int = 24,
    ) -> InternalSession:
        """
        Create a new session.

        Args:
            user_id: User ID
            username: Username
            access_token: JWT access token
            refresh_token: JWT refresh token
            expires_hours: Session validity in hours

        Returns:
            InternalSession object
        """
        session_id = str(uuid.uuid4())
        now = _utc_now()
        expires_at = now + timedelta(hours=expires_hours)

        session = InternalSession(
            session_id=session_id,
            user_id=user_id,
            username=username,
            access_token=access_token,
            refresh_token=refresh_token,
            created_at=now,
            expires_at=expires_at,
        )

        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO internal_sessions
                    (session_id, user_id, username, access_token, refresh_token, created_at, expires_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        session.session_id,
                        session.user_id,
                        session.username,
                        session.access_token,
                        session.refresh_token,
                        session.created_at,
                        session.expires_at,
                    ),
                )

        return session

    def get_session(self, session_id: str) -> Optional[InternalSession]:
        """
        Get a session by ID.

        Args:
            session_id: Session ID

        Returns:
            InternalSession if found and valid, None otherwise
        """
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM internal_sessions
                    WHERE session_id = %s AND expires_at > NOW()
                    """,
                    (session_id,),
                )
                row = cur.fetchone()

                if not row:
                    return None

                columns = [col[0] for col in cur.description]
                row_dict = dict(zip(columns, row))

                return InternalSession(
                    session_id=row_dict["session_id"],
                    user_id=row_dict["user_id"],
                    username=row_dict["username"],
                    access_token=row_dict["access_token"],
                    refresh_token=row_dict["refresh_token"],
                    created_at=row_dict["created_at"],
                    expires_at=row_dict["expires_at"],
                )

    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session.

        Args:
            session_id: Session ID

        Returns:
            True if session was deleted
        """
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM internal_sessions WHERE session_id = %s",
                    (session_id,),
                )
                return cur.rowcount > 0

    def delete_user_sessions(self, user_id: str) -> int:
        """
        Delete all sessions for a user.

        Args:
            user_id: User ID

        Returns:
            Number of sessions deleted
        """
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM internal_sessions WHERE user_id = %s",
                    (user_id,),
                )
                return cur.rowcount

    def cleanup_expired_sessions(self) -> int:
        """
        Clean up expired sessions.

        Returns:
            Number of sessions cleaned up
        """
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM internal_sessions WHERE expires_at < NOW()"
                )
                return cur.rowcount

    def cleanup_expired_tokens(self) -> int:
        """
        Clean up expired password reset tokens.

        Returns:
            Number of tokens cleaned up
        """
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM password_reset_tokens WHERE expires_at < NOW()"
                )
                return cur.rowcount

    # -------------------------------------------------------------------------
    # Federated Identity Methods (Stub implementations)
    # -------------------------------------------------------------------------
    # These methods are required by IdentityLinkingService but were never
    # implemented in this deprecated service. They return empty/stub values
    # to allow the profile page to load.
    # TODO: Migrate to MultiTenantAuthService which has full implementation.
    # -------------------------------------------------------------------------

    def get_federated_identity_by_provider(
        self,
        provider: str,
        provider_user_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Get federated identity by provider and provider user ID.

        Stub implementation - returns None as internal_users doesn't have
        federated identity support.

        Args:
            provider: OAuth provider name (e.g., 'google', 'github')
            provider_user_id: User ID from the OAuth provider

        Returns:
            None (stub implementation)
        """
        return None

    def get_user_federated_identities(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Get all federated identities for a user.

        Stub implementation - returns empty list as internal_users doesn't
        have federated identity support.

        Args:
            user_id: Internal user ID

        Returns:
            Empty list (stub implementation)
        """
        return []

    def create_federated_identity(
        self,
        user_id: str,
        provider: str,
        provider_user_id: str,
        provider_email: Optional[str] = None,
        provider_username: Optional[str] = None,
        provider_display_name: Optional[str] = None,
        provider_avatar_url: Optional[str] = None,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        token_expires_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Create a federated identity link.

        Stub implementation - raises NotImplementedError.

        Args:
            user_id: Internal user ID
            provider: OAuth provider name
            provider_user_id: User ID from the OAuth provider
            provider_email: Email from OAuth provider
            provider_username: Username from OAuth provider
            provider_display_name: Display name from OAuth provider
            provider_avatar_url: Avatar URL from OAuth provider
            access_token: Encrypted OAuth access token
            refresh_token: Encrypted OAuth refresh token
            token_expires_at: Token expiration time

        Raises:
            NotImplementedError: This is a stub implementation
        """
        raise NotImplementedError(
            "Federated identity not supported in PostgresUserService. "
            "Use MultiTenantAuthService instead."
        )

    def update_federated_identity_tokens(
        self,
        identity_id: str,
        access_token: str,
        refresh_token: Optional[str] = None,
    ) -> bool:
        """
        Update OAuth tokens for a federated identity.

        Stub implementation - returns False.

        Args:
            identity_id: Federated identity ID
            access_token: New encrypted access token
            refresh_token: New encrypted refresh token

        Returns:
            False (stub implementation)
        """
        return False

    # -------------------------------------------------------------------------
    # MFA Methods (Stub implementations)
    # -------------------------------------------------------------------------
    # These methods are required by the API endpoints but were never
    # implemented in this deprecated service.
    # -------------------------------------------------------------------------

    def get_user_mfa_devices(
        self,
        user_id: str,
        verified_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Get MFA devices for a user.

        Stub implementation - returns empty list as internal_users doesn't
        have MFA support.

        Args:
            user_id: User ID
            verified_only: Whether to only return verified devices

        Returns:
            Empty list (stub implementation)
        """
        return []

    def user_has_verified_mfa(self, user_id: str) -> bool:
        """
        Check if user has verified MFA.

        Stub implementation - returns False as internal_users doesn't
        have MFA support.

        Args:
            user_id: User ID

        Returns:
            False (stub implementation)
        """
        return False

    def get_user_by_email(self, email: str) -> Optional[User]:
        """
        Get user by email address.

        Args:
            email: Email address

        Returns:
            User object or None
        """
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM internal_users WHERE email = %s",
                    (email,),
                )
                row = cur.fetchone()

                if not row:
                    return None

                return self._row_to_user(row, cur.description)
