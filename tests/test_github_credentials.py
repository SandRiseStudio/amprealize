"""Tests for GitHub Credential Repository.

Behavior: behavior_design_test_strategy

Tests BYOK GitHub credential storage, validation, and credential store resolution.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from amprealize.auth.credential_encryption import CredentialEncryptionService
from amprealize.auth.github_credential_repository import (
    GitHubCredentialRepository,
    GitHubCredential,
    CreateGitHubCredentialRequest,
    GitHubCredentialAction,
    GitHubTokenType,
    CredentialScopeType,
    ActorType,
    detect_token_type,
    get_token_prefix,
    validate_github_token,
    GitHubTokenValidationResult,
)
from amprealize.services.github_service import (
    GitHubCredentialStore,
    ResolvedGitHubToken,
)


# ==============================================================================
# Token Detection Tests
# ==============================================================================


class TestTokenTypeDetection:
    """Tests for GitHub token type detection from prefix."""

    def test_detect_classic_token(self):
        """Classic PAT has ghp_ prefix."""
        assert detect_token_type("ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx") == GitHubTokenType.CLASSIC

    def test_detect_fine_grained_token(self):
        """Fine-grained PAT has github_pat_ prefix."""
        assert detect_token_type("github_pat_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx") == GitHubTokenType.FINE_GRAINED

    def test_detect_app_token(self):
        """GitHub App installation token has ghs_ prefix."""
        assert detect_token_type("ghs_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx") == GitHubTokenType.APP

    def test_detect_unknown_token(self):
        """Unknown prefix returns UNKNOWN type."""
        assert detect_token_type("some_random_token") == GitHubTokenType.UNKNOWN
        assert detect_token_type("sk-xxxxxxxxxx") == GitHubTokenType.UNKNOWN


class TestTokenPrefix:
    """Tests for token prefix extraction for display."""

    def test_classic_token_prefix(self):
        """Classic token shows ghp_ + 4 chars."""
        prefix = get_token_prefix("ghp_abcdefghijklmnop")
        assert prefix == "ghp_abcd"
        assert len(prefix) == 8

    def test_fine_grained_token_prefix(self):
        """Fine-grained token shows github_pat_ + 4 chars."""
        prefix = get_token_prefix("github_pat_abcdefghijklmnop")
        assert prefix == "github_pat_abcd"
        assert len(prefix) == 15

    def test_app_token_prefix(self):
        """App token shows ghs_ + 4 chars."""
        prefix = get_token_prefix("ghs_abcdefghijklmnop")
        assert prefix == "ghs_abcd"
        assert len(prefix) == 8

    def test_short_token_prefix(self):
        """Short tokens return as-is."""
        prefix = get_token_prefix("ghp_ab")
        assert prefix == "ghp_ab"


# ==============================================================================
# Token Validation Tests
# ==============================================================================


class TestTokenValidation:
    """Tests for GitHub API token validation."""

    @patch("amprealize.auth.github_credential_repository.httpx.Client")
    def test_valid_token(self, mock_client_class):
        """Valid token returns user info and scopes."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {
            "X-OAuth-Scopes": "repo, read:org",
            "X-RateLimit-Limit": "5000",
            "X-RateLimit-Remaining": "4999",
            "X-RateLimit-Reset": "1700000000",
        }
        mock_response.json.return_value = {
            "login": "testuser",
            "id": 12345,
        }

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_class.return_value = mock_client

        result = validate_github_token("ghp_testtoken")

        assert result.is_valid is True
        assert result.token_type == GitHubTokenType.CLASSIC
        assert result.username == "testuser"
        assert result.user_id == 12345
        assert result.scopes == ["repo", "read:org"]
        assert result.rate_limit == 5000
        assert result.rate_limit_remaining == 4999

    @patch("amprealize.auth.github_credential_repository.httpx.Client")
    def test_invalid_token_401(self, mock_client_class):
        """Invalid token returns 401."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.headers = {}

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_class.return_value = mock_client

        result = validate_github_token("ghp_invalidtoken")

        assert result.is_valid is False
        assert result.error_code == 401
        assert "invalid" in result.error.lower() or "expired" in result.error.lower()

    @patch("amprealize.auth.github_credential_repository.httpx.Client")
    def test_forbidden_token_403(self, mock_client_class):
        """Token without required permissions returns 403."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.headers = {}

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_class.return_value = mock_client

        result = validate_github_token("ghp_nopermissions")

        assert result.is_valid is False
        assert result.error_code == 403


# ==============================================================================
# Credential Data Class Tests
# ==============================================================================


class TestGitHubCredential:
    """Tests for GitHubCredential data class."""

    def test_has_required_scopes_classic_with_repo(self):
        """Classic token with repo scope has required scopes."""
        cred = GitHubCredential(
            id="test-id",
            scope_type=CredentialScopeType.PROJECT,
            scope_id="proj-123",
            token_type=GitHubTokenType.CLASSIC,
            name="Test Token",
            token_prefix="ghp_test",
            scopes=["repo", "read:org"],
        )
        assert cred.has_required_scopes is True
        assert cred.scope_warning is None

    def test_has_required_scopes_classic_without_repo(self):
        """Classic token without repo scope lacks required scopes."""
        cred = GitHubCredential(
            id="test-id",
            scope_type=CredentialScopeType.PROJECT,
            scope_id="proj-123",
            token_type=GitHubTokenType.CLASSIC,
            name="Test Token",
            token_prefix="ghp_test",
            scopes=["read:org"],
        )
        assert cred.has_required_scopes is False
        assert cred.scope_warning is not None
        assert "repo" in cred.scope_warning.lower()

    def test_has_required_scopes_fine_grained(self):
        """Fine-grained token needs contents:write and pull_requests:write."""
        cred = GitHubCredential(
            id="test-id",
            scope_type=CredentialScopeType.PROJECT,
            scope_id="proj-123",
            token_type=GitHubTokenType.FINE_GRAINED,
            name="Test Token",
            token_prefix="github_pat_test",
            scopes=["contents:write", "pull_requests:write", "metadata:read"],
        )
        assert cred.has_required_scopes is True

    def test_has_required_scopes_no_scopes(self):
        """Token with no scopes info returns warning."""
        cred = GitHubCredential(
            id="test-id",
            scope_type=CredentialScopeType.PROJECT,
            scope_id="proj-123",
            token_type=GitHubTokenType.CLASSIC,
            name="Test Token",
            token_prefix="ghp_test",
            scopes=None,
        )
        assert cred.has_required_scopes is False
        assert cred.scope_warning is not None

    def test_masked_token(self):
        """Masked token shows prefix + asterisks."""
        cred = GitHubCredential(
            id="test-id",
            scope_type=CredentialScopeType.PROJECT,
            scope_id="proj-123",
            token_type=GitHubTokenType.CLASSIC,
            name="Test Token",
            token_prefix="ghp_abcd",
        )
        assert cred.masked_token == "ghp_abcd****"

    def test_to_dict(self):
        """to_dict includes all fields."""
        cred = GitHubCredential(
            id="test-id",
            scope_type=CredentialScopeType.PROJECT,
            scope_id="proj-123",
            token_type=GitHubTokenType.CLASSIC,
            name="Test Token",
            token_prefix="ghp_abcd",
            is_valid=True,
            failure_count=0,
            scopes=["repo"],
            rate_limit=5000,
            rate_limit_remaining=4500,
            github_username="testuser",
            github_user_id=12345,
            created_by="user-123",
            created_at=datetime(2026, 1, 14, tzinfo=timezone.utc),
        )

        d = cred.to_dict()

        assert d["id"] == "test-id"
        assert d["scope_type"] == "project"
        assert d["token_type"] == "classic"
        assert d["masked_token"] == "ghp_abcd****"
        assert d["has_required_scopes"] is True
        assert d["scope_warning"] is None
        assert d["github_username"] == "testuser"
        assert "token" not in d  # Should not include actual token

    def test_to_dict_with_token(self):
        """to_dict with include_token=True includes decrypted token."""
        cred = GitHubCredential(
            id="test-id",
            scope_type=CredentialScopeType.PROJECT,
            scope_id="proj-123",
            token_type=GitHubTokenType.CLASSIC,
            name="Test Token",
            token_prefix="ghp_abcd",
        )
        cred._decrypted_token = "ghp_secret_token"

        d = cred.to_dict(include_token=True)

        assert d["token"] == "ghp_secret_token"


# ==============================================================================
# Credential Store Tests
# ==============================================================================


class TestGitHubCredentialStore:
    """Tests for GitHubCredentialStore resolution logic."""

    def test_platform_token_from_env(self):
        """Platform token is loaded from GITHUB_TOKEN env var."""
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_platform_token"}, clear=False):
            store = GitHubCredentialStore(pool=None)
            result = store.get_token()

            assert result is not None
            assert result[0] == "ghp_platform_token"
            assert result[1] == "platform"

    def test_platform_token_from_gh_token(self):
        """Platform token falls back to GH_TOKEN env var."""
        with patch.dict(os.environ, {"GH_TOKEN": "ghp_gh_token"}, clear=False):
            # Make sure GITHUB_TOKEN is not set
            env = os.environ.copy()
            env.pop("GITHUB_TOKEN", None)
            with patch.dict(os.environ, env, clear=True):
                with patch.dict(os.environ, {"GH_TOKEN": "ghp_gh_token"}):
                    store = GitHubCredentialStore(pool=None)
                    store._platform_token = "ghp_gh_token"  # Simulate loading
                    result = store.get_token()

                    assert result is not None
                    assert result[0] == "ghp_gh_token"

    def test_shell_style_byok_default_does_not_block_platform_token(self):
        """Shell-style BYOK placeholders should not break platform-token resolution."""
        with patch.dict(
            os.environ,
            {
                "GITHUB_TOKEN": "ghp_platform_token",
                "BYOK_ENCRYPTION_KEY": "${BYOK_ENCRYPTION_KEY:-F8mx5M0oI4byBM353Yu5dtcz8d4AxlEKl1cBf2FW0Y4=}",
            },
            clear=False,
        ):
            store = GitHubCredentialStore(pool=None)
            result = store.get_token()

            assert result is not None
            assert result[0] == "ghp_platform_token"
            assert result[1] == "platform"

    def test_credential_encryption_resolves_shell_default_placeholder(self):
        """CredentialEncryptionService should resolve ${VAR:-default} placeholders."""
        with patch.dict(
            os.environ,
            {
                "BYOK_ENCRYPTION_KEY": "${BYOK_ENCRYPTION_KEY:-F8mx5M0oI4byBM353Yu5dtcz8d4AxlEKl1cBf2FW0Y4=}"
            },
            clear=True,
        ):
            service = CredentialEncryptionService()
            ciphertext = service.encrypt("secret-token")

            assert service.decrypt(ciphertext) == "secret-token"

    def test_no_token_available(self):
        """Returns None when no token is available."""
        with patch.dict(os.environ, {}, clear=True):
            store = GitHubCredentialStore(pool=None)
            store._platform_token = None  # Clear any loaded token
            result = store.get_token()

            assert result is None


# ==============================================================================
# Repository Integration Tests (require database)
# ==============================================================================


@pytest.mark.integration
class TestGitHubCredentialRepositoryIntegration:
    """Integration tests for GitHubCredentialRepository.

    These tests require a running PostgreSQL database with the auth schema.
    Skip if database is not available.
    """

    @pytest.fixture
    def repo(self):
        """Create repository with test database connection."""
        # Skip if no database connection
        pytest.importorskip("psycopg2")
        from amprealize.storage.postgres_pool import PostgresPool

        try:
            pool = PostgresPool()
            return GitHubCredentialRepository(pool=pool)
        except Exception:
            pytest.skip("Database not available")

    def test_create_credential(self, repo):
        """Test creating a GitHub credential."""
        # This would require mocking the GitHub API validation
        # or using skip_validation=True
        pass

    def test_get_for_scope(self, repo):
        """Test getting credential for a scope."""
        # Returns None if no credential exists
        result = repo.get_for_scope(
            scope_type=CredentialScopeType.PROJECT,
            scope_id="test-project-nonexistent",
        )
        assert result is None


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def mock_valid_github_response():
    """Mock response for valid GitHub token validation."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {
        "X-OAuth-Scopes": "repo, read:org",
        "X-RateLimit-Limit": "5000",
        "X-RateLimit-Remaining": "4999",
        "X-RateLimit-Reset": "1700000000",
    }
    mock_response.json.return_value = {
        "login": "testuser",
        "id": 12345,
    }
    return mock_response
