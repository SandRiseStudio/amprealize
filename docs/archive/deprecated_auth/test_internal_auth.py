"""
Tests for internal authentication provider.

Tests registration, login, password management, and JWT token handling.
Uses PostgreSQL for UserService (not SQLite).
"""

import pytest
import os
from datetime import datetime, timedelta

from amprealize.auth.providers.internal import InternalAuthProvider
from amprealize.auth.user_service import UserService
from amprealize.auth.jwt_service import JWTService
from amprealize.auth.providers.base import (
    InvalidCredentialsError,
    ExpiredTokenError,
    OAuthError,
)


def get_auth_postgres_dsn() -> str | None:
    """Build PostgreSQL DSN for auth service from environment variables."""
    # Check for full DSN first
    if dsn := os.environ.get("AMPREALIZE_AUTH_PG_DSN"):
        return dsn

    # Build from components
    host = os.environ.get("AMPREALIZE_PG_HOST_AUTH")
    port = os.environ.get("AMPREALIZE_PG_PORT_AUTH")
    user = os.environ.get("AMPREALIZE_PG_USER_AUTH")
    password = os.environ.get("AMPREALIZE_PG_PASS_AUTH")
    dbname = os.environ.get("AMPREALIZE_PG_DB_AUTH", "amprealize_auth")

    if not all([host, port, user, password]):
        return None

    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


@pytest.fixture(autouse=True)
def clean_auth_db():
    """Clean auth tables before each test."""
    dsn = get_auth_postgres_dsn()
    if not dsn:
        pytest.skip("Auth PostgreSQL not configured (set AMPREALIZE_PG_*_AUTH env vars)")

    import psycopg2

    try:
        conn = psycopg2.connect(dsn)
        with conn.cursor() as cur:
            # Clean in order respecting foreign keys
            cur.execute("TRUNCATE TABLE internal_sessions CASCADE")
            cur.execute("TRUNCATE TABLE password_reset_tokens CASCADE")
            cur.execute("TRUNCATE TABLE internal_users CASCADE")
        conn.commit()
        conn.close()
    except psycopg2.OperationalError as e:
        pytest.skip(f"Auth PostgreSQL not available: {e}")

    yield

    # Cleanup after test
    try:
        conn = psycopg2.connect(dsn)
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE internal_sessions CASCADE")
            cur.execute("TRUNCATE TABLE password_reset_tokens CASCADE")
            cur.execute("TRUNCATE TABLE internal_users CASCADE")
        conn.commit()
        conn.close()
    except Exception:
        pass


@pytest.fixture
def user_service():
    """Create a UserService with PostgreSQL database."""
    dsn = get_auth_postgres_dsn()
    if not dsn:
        pytest.skip("Auth PostgreSQL not configured")
    service = UserService(dsn=dsn)
    yield service
    # Close connection to release locks before cleanup
    service.close()


@pytest.fixture
def jwt_service():
    """Create a JWTService with test configuration."""
    return JWTService(
        secret_key="test_secret_key_for_unit_tests",
        access_token_expiry_hours=1,
        refresh_token_expiry_days=7,
    )


@pytest.fixture
def provider(user_service, jwt_service):
    """Create an InternalAuthProvider for testing."""
    return InternalAuthProvider(
        user_service=user_service,
        jwt_service=jwt_service,
    )


class TestUserService:
    """Test user management functionality."""

    def test_create_user(self, user_service):
        """Test creating a new user."""
        user = user_service.create_user(
            username="testuser",
            password="test_password_123",
            email="test@example.com",
        )

        assert user.username == "testuser"
        assert user.email == "test@example.com"
        assert user.is_active is True
        assert user.is_admin is False
        assert user.hashed_password != "test_password_123"  # Should be hashed

    def test_create_user_duplicate_username(self, user_service):
        """Test that duplicate usernames are rejected."""
        user_service.create_user("testuser", "password123")

        with pytest.raises(ValueError, match="already exists"):
            user_service.create_user("testuser", "password456")

    def test_create_user_short_username(self, user_service):
        """Test that short usernames are rejected."""
        with pytest.raises(ValueError, match="at least 3 characters"):
            user_service.create_user("ab", "password123")

    def test_create_user_short_password(self, user_service):
        """Test that short passwords are rejected."""
        with pytest.raises(ValueError, match="at least 8 characters"):
            user_service.create_user("testuser", "pass")

    def test_authenticate_success(self, user_service):
        """Test successful authentication."""
        user_service.create_user("testuser", "password123")

        user = user_service.authenticate("testuser", "password123")
        assert user is not None
        assert user.username == "testuser"

    def test_authenticate_wrong_password(self, user_service):
        """Test authentication with wrong password."""
        user_service.create_user("testuser", "password123")

        user = user_service.authenticate("testuser", "wrong_password")
        assert user is None

    def test_authenticate_nonexistent_user(self, user_service):
        """Test authentication with nonexistent user."""
        user = user_service.authenticate("nonexistent", "password123")
        assert user is None

    def test_update_password(self, user_service):
        """Test password update."""
        user = user_service.create_user("testuser", "old_password_123")

        # Update password
        success = user_service.update_password(user.id, "new_password_123")
        assert success is True

        # Old password should not work
        assert user_service.authenticate("testuser", "old_password_123") is None

        # New password should work
        assert user_service.authenticate("testuser", "new_password_123") is not None

    def test_delete_user(self, user_service):
        """Test user deletion (soft delete)."""
        user = user_service.create_user("testuser", "password123")

        # Delete user
        success = user_service.delete_user(user.id)
        assert success is True

        # User should not be able to authenticate
        assert user_service.authenticate("testuser", "password123") is None

    def test_list_users(self, user_service):
        """Test listing users."""
        user_service.create_user("user1", "password123")
        user_service.create_user("user2", "password123")
        user3 = user_service.create_user("user3", "password123")

        # Delete one user
        user_service.delete_user(user3.id)

        # List active users
        active_users = user_service.list_users(active_only=True)
        assert len(active_users) == 2
        assert all(u.is_active for u in active_users)

        # List all users
        all_users = user_service.list_users(active_only=False)
        assert len(all_users) == 3


class TestPasswordReset:
    """Test password reset functionality."""

    def test_create_reset_token(self, user_service):
        """Test creating a password reset token."""
        user = user_service.create_user("testuser", "password123")

        reset_token = user_service.create_reset_token(user.id, expiry_hours=24)

        assert reset_token.user_id == user.id
        assert reset_token.token is not None
        assert reset_token.is_valid is True

    def test_validate_reset_token(self, user_service):
        """Test validating a reset token."""
        user = user_service.create_user("testuser", "password123")
        reset_token = user_service.create_reset_token(user.id)

        # Validate token
        validated = user_service.validate_reset_token(reset_token.token)
        assert validated is not None
        assert validated.user_id == user.id

    def test_use_reset_token(self, user_service):
        """Test using a reset token to change password."""
        user = user_service.create_user("testuser", "old_password_123")
        reset_token = user_service.create_reset_token(user.id)

        # Use token to reset password
        success = user_service.use_reset_token(reset_token.token, "new_password_123")
        assert success is True

        # Old password should not work
        assert user_service.authenticate("testuser", "old_password_123") is None

        # New password should work
        assert user_service.authenticate("testuser", "new_password_123") is not None

        # Token should be marked as used
        assert user_service.validate_reset_token(reset_token.token) is None

    def test_reset_token_expires(self, user_service):
        """Test that expired reset tokens are invalid."""
        user = user_service.create_user("testuser", "password123")

        # Create token with very short expiry
        reset_token = user_service.create_reset_token(user.id, expiry_hours=0)

        # Token should be invalid
        assert user_service.validate_reset_token(reset_token.token) is None


class TestJWTService:
    """Test JWT token generation and validation."""

    def test_generate_access_token(self, jwt_service):
        """Test generating an access token."""
        token = jwt_service.generate_access_token(
            user_id="user123",
            username="testuser",
        )

        assert token is not None
        assert isinstance(token, str)

    def test_validate_access_token(self, jwt_service):
        """Test validating an access token."""
        token = jwt_service.generate_access_token(
            user_id="user123",
            username="testuser",
        )

        payload = jwt_service.validate_token(token, expected_type="access")
        assert payload["sub"] == "user123"
        assert payload["username"] == "testuser"
        assert payload["type"] == "access"

    def test_generate_refresh_token(self, jwt_service):
        """Test generating a refresh token."""
        token = jwt_service.generate_refresh_token(
            user_id="user123",
            username="testuser",
        )

        assert token is not None
        assert isinstance(token, str)

    def test_validate_refresh_token(self, jwt_service):
        """Test validating a refresh token."""
        token = jwt_service.generate_refresh_token(
            user_id="user123",
            username="testuser",
        )

        payload = jwt_service.validate_token(token, expected_type="refresh")
        assert payload["sub"] == "user123"
        assert payload["username"] == "testuser"
        assert payload["type"] == "refresh"

    def test_refresh_access_token(self, jwt_service):
        """Test refreshing an access token."""
        refresh_token = jwt_service.generate_refresh_token(
            user_id="user123",
            username="testuser",
        )

        new_access_token = jwt_service.refresh_access_token(refresh_token)
        assert new_access_token is not None

        payload = jwt_service.validate_token(new_access_token, expected_type="access")
        assert payload["sub"] == "user123"

    def test_token_type_mismatch(self, jwt_service):
        """Test that token type is validated."""
        access_token = jwt_service.generate_access_token("user123", "testuser")

        with pytest.raises(ValueError, match="Invalid token type"):
            jwt_service.validate_token(access_token, expected_type="refresh")


@pytest.mark.asyncio
class TestInternalAuthProvider:
    """Test internal authentication provider."""

    async def test_register(self, provider):
        """Test user registration."""
        token_response = await provider.register(
            username="newuser",
            password="password123",
            email="new@example.com",
        )

        assert token_response.access_token is not None
        assert token_response.refresh_token is not None
        assert token_response.token_type == "Bearer"
        assert token_response.expires_in > 0

    async def test_register_duplicate(self, provider):
        """Test that duplicate registration is rejected."""
        await provider.register("testuser", "password123")

        with pytest.raises(OAuthError, match="Registration failed"):
            await provider.register("testuser", "password456")

    async def test_login_success(self, provider):
        """Test successful login."""
        # Register user first
        await provider.register("testuser", "password123")

        # Login
        token_response = await provider.login("testuser", "password123")

        assert token_response.access_token is not None
        assert token_response.refresh_token is not None

    async def test_login_wrong_password(self, provider):
        """Test login with wrong password."""
        await provider.register("testuser", "password123")

        with pytest.raises(InvalidCredentialsError, match="Invalid username or password"):
            await provider.login("testuser", "wrong_password")

    async def test_validate_token(self, provider):
        """Test token validation."""
        # Register and get tokens
        token_response = await provider.register("testuser", "password123", "test@example.com")

        # Validate access token
        user_info = await provider.validate_token(token_response.access_token)

        assert user_info.provider == "internal"
        assert user_info.username == "testuser"
        assert user_info.email == "test@example.com"

    async def test_refresh_token(self, provider):
        """Test refreshing tokens."""
        # Register and get tokens
        token_response = await provider.register("testuser", "password123")
        old_access_token = token_response.access_token

        # Refresh token
        new_token_response = await provider.refresh_token(token_response.refresh_token)

        assert new_token_response.access_token is not None
        assert new_token_response.access_token != old_access_token
        assert new_token_response.refresh_token is not None

    async def test_start_device_flow(self, provider):
        """Test device flow start (returns session for internal auth)."""
        response = await provider.start_device_flow(scopes=["user"])

        assert response.verification_uri == "internal://login"
        assert response.user_code is not None
        assert response.device_code == response.user_code  # Same for internal

    async def test_poll_token_raises(self, provider):
        """Test that poll_token raises error (not supported)."""
        with pytest.raises(OAuthError, match="not supported"):
            await provider.poll_token("session123")
