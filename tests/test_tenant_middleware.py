"""Unit tests for TenantMiddleware tenant resolution and skip-path logic.

Tests:
- Auth-derived tenant takes priority over headers
- Skip paths bypass tenant resolution
- Header-based resolution when auth context absent
- dict-based scope["state"] access works correctly
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from amprealize.auth.middleware import AuthConfig, AuthMiddleware
from amprealize.auth.jwt_service import JWTService
from amprealize.multi_tenant.context import TenantMiddleware, TenantContext


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def jwt_service():
    return JWTService(secret_key="test-secret-key-for-unit-tests")  # pragma: allowlist secret


@pytest.fixture
def valid_token(jwt_service):
    return jwt_service.generate_access_token(
        user_id="user-123",
        username="testuser",
        additional_claims={"org_id": "org-456"},
    )


@pytest.fixture
def mock_pool():
    """Mock PostgresPool that tracks execute calls."""
    pool = AsyncMock()
    pool.execute = AsyncMock()
    pool.fetch_one = AsyncMock(return_value=None)
    return pool


def _build_app(
    mock_pool,
    jwt_service,
    *,
    auth_required: bool = True,
    enable_header: bool = False,
    enable_auth_context: bool = True,
    skip_paths=None,
):
    """Build a FastAPI app with AuthMiddleware + TenantMiddleware stacked correctly."""
    app = FastAPI()

    @app.get("/api/v1/projects")
    async def list_projects():
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    auth_config = AuthConfig(
        jwt_secret=jwt_service.secret_key,
        skip_paths=skip_paths or {"/health", "/health/"},
        auth_required=auth_required,
    )

    # Middleware ordering: TenantMiddleware added first (inner),
    # AuthMiddleware second (outer). Request flow: Auth → Tenant → app.
    app.add_middleware(
        TenantMiddleware,
        pool=mock_pool,
        enable_header=enable_header,
        enable_subdomain=False,
        enable_path=False,
        enable_auth_context=enable_auth_context,
        skip_paths=auth_config.skip_paths,
        apply_limits=True,
    )
    app.add_middleware(
        AuthMiddleware,
        config=auth_config,
    )

    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTenantMiddlewareResolution:
    """Test that auth-derived tenant takes priority."""

    def test_auth_context_sets_tenant(self, mock_pool, jwt_service, valid_token):
        """Auth-derived org_id from JWT should set tenant context."""
        app = _build_app(mock_pool, jwt_service)
        client = TestClient(app)

        resp = client.get(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert resp.status_code == 200

        # TenantContext.activate() should have been called with org_id from JWT
        calls = mock_pool.execute.call_args_list
        # Should call set_tenant_context with org_id="org-456", user_id="user-123"
        assert any(
            "set_tenant_context" in str(c) and "org-456" in str(c)
            for c in calls
        ), f"Expected set_tenant_context with org-456, got: {calls}"

    def test_auth_overrides_header(self, mock_pool, jwt_service, valid_token):
        """Auth-derived org_id should take priority over X-Tenant-ID header."""
        app = _build_app(mock_pool, jwt_service, enable_header=True)
        client = TestClient(app)

        resp = client.get(
            "/api/v1/projects",
            headers={
                "Authorization": f"Bearer {valid_token}",
                "X-Tenant-ID": "spoofed-org-999",
            },
        )
        assert resp.status_code == 200

        # Should use auth-derived org-456, NOT spoofed header
        calls = mock_pool.execute.call_args_list
        assert any(
            "set_tenant_context" in str(c) and "org-456" in str(c)
            for c in calls
        ), f"Expected org-456 from auth, not spoofed-org-999: {calls}"
        assert not any(
            "spoofed-org-999" in str(c) for c in calls
        ), f"Spoofed header should not be used: {calls}"

    def test_header_fallback_when_no_auth(self, mock_pool, jwt_service):
        """When no auth context, headers should be used as fallback."""
        app = _build_app(
            mock_pool, jwt_service,
            auth_required=False,
            enable_header=True,
        )
        client = TestClient(app)

        resp = client.get(
            "/api/v1/projects",
            headers={"X-Tenant-ID": "header-org-789"},
        )
        assert resp.status_code == 200

        calls = mock_pool.execute.call_args_list
        assert any(
            "set_tenant_context" in str(c) and "header-org-789" in str(c)
            for c in calls
        ), f"Expected header-org-789 as fallback: {calls}"

    def test_user_id_used_when_no_org_id(self, mock_pool, jwt_service):
        """In OSS mode, user_id should be used when org_id is absent."""
        # Generate token without org_id claim
        token = jwt_service.generate_access_token(
            user_id="user-oss-001",
            username="ossuser",
        )
        app = _build_app(mock_pool, jwt_service)
        client = TestClient(app)

        resp = client.get(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

        # TenantContext should still activate (user_id triggers auth context)
        calls = mock_pool.execute.call_args_list
        # Without org_id, activate() calls clear_current_org()
        assert any(
            "clear_current_org" in str(c) for c in calls
        ), f"Expected clear_current_org for no-org auth: {calls}"


@pytest.mark.unit
class TestTenantMiddlewareSkipPaths:
    """Test that skip paths bypass tenant resolution."""

    def test_skip_path_no_tenant_resolution(self, mock_pool, jwt_service):
        """Health endpoint should bypass TenantMiddleware entirely."""
        app = _build_app(mock_pool, jwt_service, auth_required=False)
        client = TestClient(app)

        resp = client.get("/health")
        assert resp.status_code == 200

        # No pool.execute calls — tenant resolution was skipped
        mock_pool.execute.assert_not_called()

    def test_non_skip_path_activates_tenant(self, mock_pool, jwt_service, valid_token):
        """Non-skip paths should activate tenant context."""
        app = _build_app(mock_pool, jwt_service)
        client = TestClient(app)

        resp = client.get(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert resp.status_code == 200
        # Pool should have been called for tenant activation
        assert mock_pool.execute.call_count >= 1

    def test_unauthenticated_non_skip_returns_401(self, mock_pool, jwt_service):
        """Non-skip path without auth should return 401 when auth_required."""
        app = _build_app(mock_pool, jwt_service, auth_required=True)
        client = TestClient(app)

        resp = client.get("/api/v1/projects")
        assert resp.status_code == 401


@pytest.mark.unit
class TestTenantMiddlewareStateAccess:
    """Test that dict-based scope['state'] works correctly."""

    def test_dict_state_access(self, mock_pool, jwt_service, valid_token):
        """Verify TenantMiddleware reads from dict-style state (not getattr)."""
        app = _build_app(mock_pool, jwt_service)
        client = TestClient(app)

        resp = client.get(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert resp.status_code == 200

        # If getattr were still used on a dict, org_id would be None
        # and set_tenant_context wouldn't be called with org-456.
        calls = mock_pool.execute.call_args_list
        set_calls = [c for c in calls if "set_tenant_context" in str(c)]
        assert len(set_calls) > 0, "set_tenant_context should be called (dict state access works)"


@pytest.mark.unit
class TestTenantContextActivation:
    """Test TenantContext activate/deactivate lifecycle."""

    @pytest.mark.asyncio
    async def test_activate_with_org_id(self, mock_pool):
        ctx = TenantContext(
            pool=mock_pool,
            org_id="org-test",
            user_id="user-test",
            apply_limits=True,
        )
        await ctx.activate()
        mock_pool.execute.assert_any_call(
            "SELECT set_tenant_context($1, $2)", "org-test", "user-test"
        )

    @pytest.mark.asyncio
    async def test_activate_without_org_clears(self, mock_pool):
        ctx = TenantContext(
            pool=mock_pool,
            org_id=None,
            apply_limits=True,
        )
        await ctx.activate()
        mock_pool.execute.assert_any_call("SELECT clear_current_org()")

    @pytest.mark.asyncio
    async def test_deactivate_clears_context(self, mock_pool):
        ctx = TenantContext(
            pool=mock_pool,
            org_id="org-test",
            user_id="user-test",
        )
        await ctx.activate()
        mock_pool.execute.reset_mock()
        await ctx.deactivate()
        mock_pool.execute.assert_any_call("SELECT clear_current_org()")
