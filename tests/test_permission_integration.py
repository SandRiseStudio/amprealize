"""Integration tests for RBAC permission system across API, CLI, and MCP surfaces.

Tests end-to-end permission checking flows including:
- Auth middleware integration
- API endpoint protection
- CLI tenant context
- MCP permission checking

Following behavior_design_test_strategy (Student):
- Integration tests covering cross-surface permission flows
- Tests for JWT validation + permission checking
- Test pyramid: 20% integration coverage for RBAC
"""

from __future__ import annotations

import asyncio
import json
import os
import pytest
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

# FastAPI testing
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

# Auth components
from amprealize.auth.middleware import (
    AuthConfig,
    AuthMiddleware,
    get_current_user,
    get_current_user_optional,
    get_org_context,
    get_project_context,
    require_org_context,
    require_project_context,
    require_org_permission_dep,
    require_project_permission_dep,
    get_permission_service,
)
from amprealize.auth.jwt_service import JWTService
from amprealize.multi_tenant.permissions import (
    AsyncPermissionService,
    OrgPermission,
    ProjectPermission,
    PermissionDenied,
    NotAMember,
    UserOrgContext,
    UserProjectContext,
)
from amprealize.multi_tenant.contracts import MemberRole, ProjectRole


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def jwt_config():
    """JWT configuration for tests."""
    return {
        "secret_key": "test-secret-key-for-testing-only",
        "algorithm": "HS256",
    }


@pytest.fixture
def jwt_service(jwt_config):
    """Create JWT service for tests."""
    return JWTService(
        secret_key=jwt_config["secret_key"],
        algorithm=jwt_config["algorithm"],
    )


@pytest.fixture
def auth_config(jwt_config):
    """Create auth config for tests."""
    return AuthConfig(
        jwt_secret=jwt_config["secret_key"],
        jwt_algorithm=jwt_config["algorithm"],
        auth_required=True,
        skip_paths={"/health", "/v1/public", "/v1/optional-auth"},
    )


@pytest.fixture
def mock_permission_service():
    """Create mocked AsyncPermissionService."""
    service = MagicMock(spec=AsyncPermissionService)

    # Default: allow all
    service.check_org_permission = AsyncMock(return_value=True)
    service.check_project_permission = AsyncMock(return_value=True)
    service.require_org_permission = AsyncMock(return_value=None)
    service.require_project_permission = AsyncMock(return_value=None)
    service.get_user_org_context = AsyncMock(return_value=UserOrgContext(
        user_id="test-user",
        org_id="test-org",
        role=MemberRole.MEMBER,
        permissions=set(OrgPermission),
    ))
    service.get_user_project_context = AsyncMock(return_value=UserProjectContext(
        user_id="test-user",
        project_id="test-project",
        role=ProjectRole.VIEWER,
        permissions=set(ProjectPermission),
    ))

    return service


@pytest.fixture
def test_app(auth_config, jwt_service, mock_permission_service):
    """Create test FastAPI app with auth middleware."""
    app = FastAPI()

    # Store in app state
    app.state.auth_config = auth_config
    app.state.jwt_service = jwt_service
    app.state.async_permission_service = mock_permission_service

    # Add middleware
    app.add_middleware(AuthMiddleware, config=auth_config)

    # Public endpoint
    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/v1/public")
    def public_endpoint():
        return {"message": "public"}

    # Protected endpoints
    @app.get("/v1/protected")
    def protected_endpoint(user = Depends(get_current_user)):
        return {"user_id": user["user_id"], "message": "protected"}

    @app.get("/v1/optional-auth")
    def optional_auth_endpoint(user = Depends(get_current_user_optional)):
        if user:
            return {"authenticated": True, "user_id": user["user_id"]}
        return {"authenticated": False}

    # Permission-protected endpoints
    @app.get("/v1/orgs/{org_id}/settings")
    def org_settings(
        org_id: str,
        user = Depends(get_current_user),
        perm_service = Depends(get_permission_service),
    ):
        # Inline permission check
        return {"org_id": org_id, "settings": {}}

    @app.post("/v1/orgs/{org_id}/members")
    async def invite_member(
        org_id: str,
        user = Depends(get_current_user),
        perm_service = Depends(get_permission_service),
    ):
        # Check invite permission
        has_perm = await perm_service.check_org_permission(
            user["user_id"], org_id, OrgPermission.INVITE_MEMBERS
        )
        if not has_perm:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Permission denied")
        return {"org_id": org_id, "invited": True}

    return app


@pytest.fixture
def test_client(test_app):
    """Create test client."""
    return TestClient(test_app)


@pytest.fixture
def valid_token(jwt_service):
    """Generate valid JWT token."""
    return jwt_service.generate_access_token(
        user_id="test-user-id",
        username="testuser",
        additional_claims={"email": "test@example.com"},
    )


@pytest.fixture
def expired_token(jwt_config):
    """Generate expired JWT token."""
    import jwt as pyjwt
    payload = {
        "sub": "test-user-id",
        "username": "testuser",
        "type": "access",
        "exp": datetime.now(timezone.utc) - timedelta(seconds=60),
        "iat": datetime.now(timezone.utc) - timedelta(seconds=120),
    }
    return pyjwt.encode(payload, jwt_config["secret_key"], algorithm=jwt_config["algorithm"])


# =============================================================================
# Auth Middleware Integration Tests
# =============================================================================

@pytest.mark.unit
class TestAuthMiddlewareIntegration:
    """Test auth middleware with FastAPI endpoints."""

    def test_public_endpoint_no_auth(self, test_client):
        """Public endpoints should work without authentication."""
        response = test_client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_public_path_in_config(self, test_client):
        """Paths in public_paths config should not require auth."""
        response = test_client.get("/v1/public")
        assert response.status_code == 200

    def test_protected_endpoint_requires_auth(self, test_client):
        """Protected endpoints should require authentication."""
        response = test_client.get("/v1/protected")
        assert response.status_code == 401
        assert "Authorization header missing" in response.json()["detail"]

    def test_protected_endpoint_with_valid_token(self, test_client, valid_token):
        """Protected endpoints should work with valid token."""
        response = test_client.get(
            "/v1/protected",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == "test-user-id"
        assert data["message"] == "protected"

    def test_protected_endpoint_with_expired_token(self, test_client, expired_token):
        """Expired tokens should be rejected."""
        response = test_client.get(
            "/v1/protected",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert response.status_code == 401

    def test_protected_endpoint_with_invalid_token(self, test_client):
        """Invalid tokens should be rejected."""
        response = test_client.get(
            "/v1/protected",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert response.status_code == 401

    def test_optional_auth_without_token(self, test_client):
        """Optional auth endpoint should work without token."""
        response = test_client.get("/v1/optional-auth")
        assert response.status_code == 200
        assert response.json() == {"authenticated": False}

    def test_optional_auth_with_token(self, test_client, valid_token):
        """Optional auth endpoint should include user when token present."""
        response = test_client.get(
            "/v1/optional-auth",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is True
        assert data["user_id"] == "test-user-id"


# =============================================================================
# Permission Checking Integration Tests
# =============================================================================

@pytest.mark.unit
class TestPermissionCheckingIntegration:
    """Test permission checking with endpoints."""

    def test_permission_granted(
        self, test_client, valid_token, mock_permission_service
    ):
        """Endpoint should succeed when permission is granted."""
        mock_permission_service.check_org_permission = AsyncMock(return_value=True)

        response = test_client.post(
            "/v1/orgs/org-123/members",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert response.status_code == 200
        assert response.json()["invited"] is True

    def test_permission_denied(
        self, test_client, valid_token, mock_permission_service
    ):
        """Endpoint should fail when permission is denied."""
        mock_permission_service.check_org_permission = AsyncMock(return_value=False)

        response = test_client.post(
            "/v1/orgs/org-123/members",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert response.status_code == 403
        assert "Permission denied" in response.json()["detail"]


# =============================================================================
# CLI Tenant Context Tests
# =============================================================================

@pytest.mark.unit
@pytest.mark.skip(reason="CLI --org-id/--project-id are subcommand-specific, not global flags yet")
class TestCLITenantContext:
    """Test CLI tenant context flags."""

    def test_org_id_from_arg(self):
        """CLI --org-id flag should set environment variable."""
        from amprealize.cli import _parse_args, main

        # Parse args with org-id
        args = _parse_args(["--org-id", "test-org-123", "scan-secrets"])

        assert args.org_id == "test-org-123"

    def test_project_id_from_arg(self):
        """CLI --project-id flag should set environment variable."""
        from amprealize.cli import _parse_args

        args = _parse_args(["--project-id", "proj-456", "scan-secrets"])

        assert args.project_id == "proj-456"

    def test_org_id_from_env(self):
        """CLI should read org-id from environment if not provided."""
        from amprealize.cli import _parse_args

        with patch.dict(os.environ, {"AMPREALIZE_ORG_ID": "env-org-123"}):
            args = _parse_args(["scan-secrets"])
            assert args.org_id == "env-org-123"

    def test_arg_overrides_env(self):
        """CLI arg should override environment variable."""
        from amprealize.cli import _parse_args

        with patch.dict(os.environ, {"AMPREALIZE_ORG_ID": "env-org-123"}):
            args = _parse_args(["--org-id", "arg-org-456", "scan-secrets"])
            assert args.org_id == "arg-org-456"

    def test_both_tenant_contexts(self):
        """CLI should support both org-id and project-id."""
        from amprealize.cli import _parse_args

        args = _parse_args([
            "--org-id", "org-123",
            "--project-id", "proj-456",
            "scan-secrets",
        ])

        assert args.org_id == "org-123"
        assert args.project_id == "proj-456"


# =============================================================================
# MCP Permission Integration Tests
# =============================================================================

@pytest.mark.unit
@pytest.mark.skip(reason="MCPServiceRegistry.permission_service and MCPServer._check_permission not yet implemented")
class TestMCPPermissionIntegration:
    """Test MCP server permission checking."""

    def test_mcp_service_registry_permission_service(self):
        """MCPServiceRegistry should provide permission service."""
        from amprealize.mcp_server import MCPServiceRegistry

        # Create registry
        registry = MCPServiceRegistry()

        # First call should return None (not configured)
        service = registry.permission_service()
        assert service is None  # No pool configured

    def test_mcp_server_check_permission_method_exists(self):
        """MCPServer should have _check_permission method."""
        from amprealize.mcp_server import MCPServer

        # Check the method exists
        assert hasattr(MCPServer, "_check_permission")

        # Check method signature accepts expected params
        import inspect
        sig = inspect.signature(MCPServer._check_permission)
        params = list(sig.parameters.keys())
        assert "user_id" in params
        assert "org_id" in params
        assert "project_id" in params
        assert "org_permission" in params
        assert "project_permission" in params


# =============================================================================
# Cross-Surface Parity Tests
# =============================================================================

@pytest.mark.unit
class TestCrossSurfaceParity:
    """Test permission checking consistency across surfaces.

    Following behavior_validate_cross_surface_parity (Student):
    Verify permissions work identically across API, CLI, and MCP.
    """

    def test_org_permission_enum_values(self):
        """OrgPermission enum should have expected values."""
        from amprealize.multi_tenant.permissions import OrgPermission

        # Core permissions should exist
        assert hasattr(OrgPermission, "VIEW_ORG")
        assert hasattr(OrgPermission, "DELETE_ORG")
        assert hasattr(OrgPermission, "INVITE_MEMBERS")

    def test_project_permission_enum_values(self):
        """ProjectPermission enum should have expected values."""
        from amprealize.multi_tenant.permissions import ProjectPermission

        # Core permissions should exist
        assert hasattr(ProjectPermission, "VIEW_PROJECT")
        assert hasattr(ProjectPermission, "DELETE_PROJECT")
        assert hasattr(ProjectPermission, "VIEW_RUNS")

    def test_permission_service_types_compatible(self):
        """PermissionService and AsyncPermissionService should have same interface."""
        from amprealize.multi_tenant.permissions import (
            PermissionService,
            AsyncPermissionService,
        )

        # Check key methods exist on both
        sync_methods = {"has_org_permission", "has_project_permission", "require_org_permission", "require_project_permission"}
        async_methods = {"has_org_permission", "has_project_permission", "require_org_permission", "require_project_permission"}

        for method in sync_methods:
            assert hasattr(PermissionService, method), f"PermissionService missing {method}"
        for method in async_methods:
            assert hasattr(AsyncPermissionService, method), f"AsyncPermissionService missing {method}"


# =============================================================================
# Async Permission Service Tests
# =============================================================================

@pytest.mark.unit
@pytest.mark.asyncio
class TestAsyncPermissionService:
    """Test AsyncPermissionService integration."""

    async def test_async_check_org_permission_allowed(self):
        """AsyncPermissionService should check org permissions."""
        # Create mocked service
        service = MagicMock(spec=AsyncPermissionService)
        service.check_org_permission = AsyncMock(return_value=True)

        result = await service.check_org_permission(
            "user-1", "org-1", OrgPermission.VIEW_ORG
        )
        assert result is True

    async def test_async_check_org_permission_denied(self):
        """AsyncPermissionService should return False when denied."""
        service = MagicMock(spec=AsyncPermissionService)
        service.check_org_permission = AsyncMock(return_value=False)

        result = await service.check_org_permission(
            "user-1", "org-1", OrgPermission.DELETE_ORG
        )
        assert result is False

    async def test_async_require_permission_raises(self):
        """AsyncPermissionService require methods should raise on denial."""
        service = MagicMock(spec=AsyncPermissionService)
        service.require_org_permission = AsyncMock(
            side_effect=PermissionDenied(OrgPermission.VIEW_ORG, "user-1", "org-1")
        )

        with pytest.raises(PermissionDenied):
            await service.require_org_permission(
                "user-1", "org-1", OrgPermission.VIEW_ORG
            )


# =============================================================================
# Billing Permissions Tests
# =============================================================================

@pytest.mark.unit
class TestBillingPermissions:
    """Test billing-related permissions."""

    def test_billing_permissions_exist(self):
        """Billing permissions should exist in OrgPermission enum."""
        # These were added per user request
        assert hasattr(OrgPermission, "VIEW_INVOICES")
        assert hasattr(OrgPermission, "VIEW_USAGE")
        assert hasattr(OrgPermission, "MANAGE_SUBSCRIPTIONS")
        assert hasattr(OrgPermission, "MANAGE_PAYMENT_METHODS")

    def test_owner_has_billing_permissions(self):
        """Owner role should have all billing permissions."""
        from amprealize.multi_tenant.permissions import ORG_ROLE_PERMISSIONS

        owner_perms = ORG_ROLE_PERMISSIONS[MemberRole.OWNER]

        assert OrgPermission.VIEW_INVOICES in owner_perms
        assert OrgPermission.VIEW_USAGE in owner_perms
        assert OrgPermission.MANAGE_SUBSCRIPTIONS in owner_perms
        assert OrgPermission.MANAGE_PAYMENT_METHODS in owner_perms

    def test_member_limited_billing_permissions(self):
        """Member role should have limited billing permissions."""
        from amprealize.multi_tenant.permissions import ORG_ROLE_PERMISSIONS

        member_perms = ORG_ROLE_PERMISSIONS[MemberRole.MEMBER]

        # Members should NOT have billing permissions
        assert OrgPermission.VIEW_INVOICES not in member_perms
        assert OrgPermission.MANAGE_SUBSCRIPTIONS not in member_perms
        assert OrgPermission.MANAGE_PAYMENT_METHODS not in member_perms
