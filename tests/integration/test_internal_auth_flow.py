"""
Integration Tests for Internal Authentication

Tests the complete internal authentication flow across API, CLI, and storage:
- User registration via API and CLI
- Username/password login via API and CLI
- Multi-provider token storage
- Error handling (duplicate users, invalid credentials, validation)
- Token persistence and retrieval

Prerequisites:
- API server running (uvicorn amprealize.api:app)
- Clean test database (or use temporary storage)
- No conflicting token files

Usage:
    # Run all internal auth integration tests
    pytest tests/integration/test_internal_auth_flow.py -v -s

    # Run specific test class
    pytest tests/integration/test_internal_auth_flow.py::TestInternalAuthAPI -v

    # Run with coverage
    pytest tests/integration/test_internal_auth_flow.py --cov=amprealize.auth --cov-report=html
"""

import asyncio
import json
import os
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class InternalAuthAPIClient:
    """Client for testing internal authentication API endpoints."""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or os.getenv("AMPREALIZE_GATEWAY_URL", "http://localhost:8080")
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        """Create requests session with retry logic."""
        session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=[500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def health_check(self) -> Dict[str, Any]:
        """Check if API is healthy."""
        try:
            response = self.session.get(f"{self.base_url}/health", timeout=5)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            pytest.skip(f"API server not available: {e}")

    def list_providers(self) -> Dict[str, Any]:
        """GET /api/v1/auth/providers - List available auth providers."""
        response = self.session.get(f"{self.base_url}/api/v1/auth/providers", timeout=5)
        response.raise_for_status()
        return response.json()

    def register(
        self,
        username: str,
        password: str,
        email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """POST /api/v1/auth/internal/register - Register new user."""
        payload = {"username": username, "password": password}
        if email:
            payload["email"] = email

        response = self.session.post(
            f"{self.base_url}/api/v1/auth/internal/register",
            json=payload,
            timeout=10,
        )
        return {
            "status_code": response.status_code,
            "data": response.json() if response.status_code < 500 else {"detail": response.text},
        }

    def login(
        self,
        username: str,
        password: str,
    ) -> Dict[str, Any]:
        """POST /api/v1/auth/internal/login - Authenticate with username/password."""
        response = self.session.post(
            f"{self.base_url}/api/v1/auth/internal/login",
            json={"username": username, "password": password},
            timeout=10,
        )
        return {
            "status_code": response.status_code,
            "data": response.json() if response.status_code < 500 else {"detail": response.text},
        }


@pytest.fixture
def api_client():
    """Fixture providing an API client instance."""
    client = InternalAuthAPIClient()
    # Verify API is running
    client.health_check()
    return client


@pytest.fixture
def temp_config_dir():
    """Fixture providing a temporary config directory for isolated tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        prev_plaintext = os.environ.get("AMPREALIZE_ALLOW_PLAINTEXT_TOKENS")
        os.environ["AMPREALIZE_ALLOW_PLAINTEXT_TOKENS"] = "1"
        try:
            yield Path(tmpdir)
        finally:
            if prev_plaintext is None:
                os.environ.pop("AMPREALIZE_ALLOW_PLAINTEXT_TOKENS", None)
            else:
                os.environ["AMPREALIZE_ALLOW_PLAINTEXT_TOKENS"] = prev_plaintext


@pytest.fixture
def unique_username():
    """Generate a unique username for test isolation."""
    import uuid
    return f"testuser_{uuid.uuid4().hex[:8]}"


class TestInternalAuthAPI:
    """Test internal authentication API endpoints."""

    def test_list_providers(self, api_client):
        """Test GET /api/v1/auth/providers returns both GitHub and internal providers."""
        result = api_client.list_providers()

        assert "providers" in result
        providers = result["providers"]
        assert len(providers) == 2

        # Check GitHub provider
        github = next((p for p in providers if p["name"] == "github"), None)
        assert github is not None
        assert github["type"] == "oauth"
        assert github["device_flow"] is True
        assert github["enabled"] is True

        # Check internal provider
        internal = next((p for p in providers if p["name"] == "internal"), None)
        assert internal is not None
        assert internal["type"] == "password"
        assert internal["device_flow"] is False
        assert internal["enabled"] is True

    def test_register_success(self, api_client, unique_username):
        """Test successful user registration returns tokens."""
        result = api_client.register(
            username=unique_username,
            password="TestPassword123!",
            email=f"{unique_username}@example.com",
        )

        assert result["status_code"] == 201
        data = result["data"]

        # Validate response structure
        assert data["status"] == "registered"
        assert data["username"] == unique_username
        assert data["provider"] == "internal"
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "Bearer"
        assert "expires_in" in data
        assert "expires_at" in data
        assert "refresh_expires_in" in data
        assert "refresh_expires_at" in data

        # Validate tokens (JWT format starts with 'eyJ')
        assert data["access_token"].startswith("eyJ")
        assert data["refresh_token"].startswith("eyJ")
        assert data["expires_in"] > 0
        assert data["refresh_expires_in"] > 0

    def test_register_duplicate_user(self, api_client, unique_username):
        """Test registering duplicate username returns 409 Conflict."""
        # First registration
        result1 = api_client.register(
            username=unique_username,
            password="TestPassword123!",
        )
        assert result1["status_code"] == 201

        # Duplicate registration
        result2 = api_client.register(
            username=unique_username,
            password="DifferentPassword456!",
        )
        assert result2["status_code"] == 409
        assert "already exists" in result2["data"]["detail"].lower()

    def test_register_validation_short_username(self, api_client):
        """Test registration with short username returns 400."""
        result = api_client.register(
            username="ab",  # Too short
            password="TestPassword123!",
        )
        assert result["status_code"] == 400
        assert "at least 3 characters" in result["data"]["detail"]

    def test_register_validation_short_password(self, api_client, unique_username):
        """Test registration with short password returns 400."""
        result = api_client.register(
            username=unique_username,
            password="short",  # Too short
        )
        assert result["status_code"] == 400
        assert "at least 8 characters" in result["data"]["detail"]

    def test_login_success(self, api_client, unique_username):
        """Test successful login returns tokens."""
        password = "TestPassword123!"

        # Register user first
        reg_result = api_client.register(username=unique_username, password=password)
        assert reg_result["status_code"] == 201

        # Login with same credentials
        login_result = api_client.login(username=unique_username, password=password)

        assert login_result["status_code"] == 200
        data = login_result["data"]

        # Validate response structure
        assert data["status"] == "authenticated"
        assert data["username"] == unique_username
        assert data["provider"] == "internal"
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "Bearer"
        assert data["expires_in"] > 0

        # Tokens should be different from registration tokens
        assert data["access_token"] != reg_result["data"]["access_token"]

    def test_login_invalid_credentials(self, api_client, unique_username):
        """Test login with invalid credentials returns 401."""
        password = "TestPassword123!"

        # Register user
        reg_result = api_client.register(username=unique_username, password=password)
        assert reg_result["status_code"] == 201

        # Login with wrong password
        login_result = api_client.login(username=unique_username, password="WrongPassword!")
        assert login_result["status_code"] == 401
        assert "invalid" in login_result["data"]["detail"].lower()

    def test_login_nonexistent_user(self, api_client):
        """Test login with nonexistent user returns 401."""
        result = api_client.login(
            username="nonexistent_user_xyz",
            password="SomePassword123!",
        )
        assert result["status_code"] == 401

    def test_login_missing_fields(self, api_client):
        """Test login with missing username or password returns 400."""
        # Missing password
        result1 = api_client.login(username="testuser", password="")
        assert result1["status_code"] == 400

        # Missing username
        result2 = api_client.login(username="", password="password123")
        assert result2["status_code"] == 400


class TestInternalAuthCLI:
    """Test internal authentication via CLI commands."""

    def test_cli_register_command(self, temp_config_dir, unique_username):
        """Test deprecated auth register command exits with OAuth guidance."""
        password = "TestPassword123!"
        email = f"{unique_username}@example.com"

        # Run register command with input piping
        input_data = f"{unique_username}\n{password}\n{password}\n{email}\n"

        env = os.environ.copy()
        env["AMPREALIZE_CONFIG_DIR"] = str(temp_config_dir)

        result = subprocess.run(
            ["python", "-m", "amprealize.cli", "auth", "register"],
            input=input_data,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

        # Internal username/password auth is deprecated in favor of OAuth.
        assert result.returncode == 1
        assert "deprecated" in result.stderr.lower()
        assert "oauth" in result.stderr.lower()

        # Verify token file was not created
        token_file = temp_config_dir / "auth_tokens_internal.json"
        assert not token_file.exists()

    def test_cli_login_command(self, temp_config_dir, unique_username):
        """Test deprecated internal provider login exits with OAuth guidance."""
        password = "TestPassword123!"
        input_data = f"{unique_username}\n{password}\n"

        env = os.environ.copy()
        env["AMPREALIZE_CONFIG_DIR"] = str(temp_config_dir)

        result = subprocess.run(
            ["python", "-m", "amprealize.cli", "auth", "login", "--provider", "internal"],
            input=input_data,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

        assert result.returncode == 1
        assert "deprecated" in result.stderr.lower()
        assert "oauth" in result.stderr.lower()

        token_file = temp_config_dir / "auth_tokens_internal.json"
        assert not token_file.exists()


class TestMultiProviderTokenStorage:
    """Test multi-provider token storage functionality."""

    def test_provider_specific_files(self, temp_config_dir, unique_username):
        """Test that internal and github tokens are stored in separate files."""
        from amprealize.auth_tokens import AuthTokenBundle, FileTokenStore
        from datetime import datetime, timezone, timedelta

        # Pass a file path, not directory - FileTokenStore uses path.parent for base dir
        store = FileTokenStore(temp_config_dir / "auth_tokens.json")

        # Create internal auth tokens
        now = datetime.now(timezone.utc)
        internal_bundle = AuthTokenBundle(
            access_token="ga_internal_test",
            refresh_token="gr_internal_test",
            token_type="Bearer",
            scopes=[],
            client_id="amprealize-cli",
            issued_at=now,
            expires_at=now + timedelta(hours=24),
            refresh_expires_at=now + timedelta(days=30),
            provider="internal",
        )

        # Create github tokens
        github_bundle = AuthTokenBundle(
            access_token="ga_github_test",
            refresh_token="gr_github_test",
            token_type="Bearer",
            scopes=["read:user"],
            client_id="github-oauth-app",
            issued_at=now,
            expires_at=now + timedelta(hours=24),
            refresh_expires_at=now + timedelta(days=30),
            provider="github",
        )

        # Save both
        store.save(internal_bundle, provider="internal")
        store.save(github_bundle, provider="github")

        # Verify separate files exist
        internal_file = temp_config_dir / "auth_tokens_internal.json"
        github_file = temp_config_dir / "auth_tokens_github.json"

        assert internal_file.exists()
        assert github_file.exists()

        # Verify correct tokens in each file
        loaded_internal = store.load(provider="internal")
        loaded_github = store.load(provider="github")

        assert loaded_internal is not None
        assert loaded_internal.access_token == "ga_internal_test"
        assert loaded_internal.provider == "internal"

        assert loaded_github is not None
        assert loaded_github.access_token == "ga_github_test"
        assert loaded_github.provider == "github"

    def test_list_providers(self, temp_config_dir):
        """Test FileTokenStore.list_providers() returns all stored providers."""
        from amprealize.auth_tokens import AuthTokenBundle, FileTokenStore
        from datetime import datetime, timezone, timedelta

        # Pass a file path, not directory
        store = FileTokenStore(temp_config_dir / "auth_tokens.json")

        # Initially empty
        assert store.list_providers() == []

        # Add internal tokens
        now = datetime.now(timezone.utc)
        internal_bundle = AuthTokenBundle(
            access_token="ga_test",
            refresh_token="gr_test",
            token_type="Bearer",
            scopes=[],
            client_id="amprealize-cli",
            issued_at=now,
            expires_at=now + timedelta(hours=24),
            refresh_expires_at=now + timedelta(days=30),
            provider="internal",
        )
        store.save(internal_bundle, provider="internal")

        providers = store.list_providers()
        assert "internal" in providers
        assert len(providers) == 1

        # Add github tokens
        github_bundle = AuthTokenBundle(
            access_token="ga_test2",
            refresh_token="gr_test2",
            token_type="Bearer",
            scopes=["read:user"],
            client_id="github-oauth-app",
            issued_at=now,
            expires_at=now + timedelta(hours=24),
            refresh_expires_at=now + timedelta(days=30),
            provider="github",
        )
        store.save(github_bundle, provider="github")

        providers = store.list_providers()
        assert "internal" in providers
        assert "github" in providers
        assert len(providers) == 2

    def test_clear_provider_specific(self, temp_config_dir):
        """Test clearing tokens for a specific provider doesn't affect others."""
        from amprealize.auth_tokens import AuthTokenBundle, FileTokenStore
        from datetime import datetime, timezone, timedelta

        # Pass a file path, not directory
        store = FileTokenStore(temp_config_dir / "auth_tokens.json")

        # Save tokens for both providers
        now = datetime.now(timezone.utc)
        for provider in ["internal", "github"]:
            scopes = [] if provider == "internal" else ["read:user"]
            client_id = "amprealize-cli" if provider == "internal" else "github-oauth-app"
            bundle = AuthTokenBundle(
                access_token=f"ga_{provider}",
                refresh_token=f"gr_{provider}",
                token_type="Bearer",
                scopes=scopes,
                client_id=client_id,
                issued_at=now,
                expires_at=now + timedelta(hours=24),
                refresh_expires_at=now + timedelta(days=30),
                provider=provider,
            )
            store.save(bundle, provider=provider)

        # Clear only internal
        store.clear(provider="internal")

        # Internal should be gone
        assert store.load(provider="internal") is None

        # GitHub should still exist
        github_tokens = store.load(provider="github")
        assert github_tokens is not None
        assert github_tokens.access_token == "ga_github"


class TestEndToEndFlow:
    """Test complete end-to-end authentication workflows."""

    def test_register_login_workflow(self, api_client, unique_username):
        """Test complete workflow: register -> login -> verify tokens."""
        password = "CompleteFlow123!"

        # Step 1: Register
        reg_result = api_client.register(
            username=unique_username,
            password=password,
            email=f"{unique_username}@example.com",
        )
        assert reg_result["status_code"] == 201
        reg_data = reg_result["data"]
        reg_access_token = reg_data["access_token"]

        # Step 2: Login (should get new tokens)
        login_result = api_client.login(username=unique_username, password=password)
        assert login_result["status_code"] == 200
        login_data = login_result["data"]
        login_access_token = login_data["access_token"]

        # Verify tokens are different (new session)
        assert login_access_token != reg_access_token

        # Step 3: Verify token structure
        assert login_data["username"] == unique_username
        assert login_data["provider"] == "internal"
        assert login_data["token_type"] == "Bearer"

        # Verify expiry is in the future
        expires_at = datetime.fromisoformat(login_data["expires_at"].replace("Z", "+00:00"))
        assert expires_at > datetime.now(timezone.utc)

    def test_concurrent_registrations(self, api_client):
        """Test that concurrent registrations handle race conditions properly."""
        import concurrent.futures
        import uuid

        username = f"concurrent_{uuid.uuid4().hex[:8]}"
        password = "TestPassword123!"

        def attempt_register():
            return api_client.register(username=username, password=password)

        # Attempt 5 concurrent registrations with same username
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(attempt_register) for _ in range(5)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        # Exactly one should succeed (201), others should fail (409)
        success_count = sum(1 for r in results if r["status_code"] == 201)
        conflict_count = sum(1 for r in results if r["status_code"] == 409)

        assert success_count == 1
        assert conflict_count == 4


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
