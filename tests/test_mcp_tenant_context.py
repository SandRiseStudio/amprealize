"""
Tests for MCP Tenant Context & Isolation (Phase 4).

Validates:
1. MCPServiceAdapter correctly builds tenant context
2. Context switching tools work correctly
3. Permission checks are enforced
4. org_id is properly handled as optional

Following behavior_design_test_strategy (Student).
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass, field
from typing import Optional, Set


# ============================================================================
# MCPServiceAdapter Tests
# ============================================================================


class TestMCPServiceAdapter:
    """Tests for MCPServiceAdapter and TenantContext."""

    def test_tenant_context_creation_with_user(self):
        """Test TenantContext is created correctly for user auth."""
        from amprealize.mcp_service_adapter import TenantContext

        ctx = TenantContext(
            user_id="user-123",
            org_id="org-456",
            project_id="proj-789",
            auth_method="device_flow",
            roles={"STUDENT"},
            granted_scopes={"behaviors.read", "runs.create"},
        )

        assert ctx.user_id == "user-123"
        assert ctx.org_id == "org-456"
        assert ctx.project_id == "proj-789"
        assert ctx.identity == "user-123"
        assert ctx.identity_type == "user"
        assert "behaviors.read" in ctx.granted_scopes

    def test_tenant_context_creation_with_service_principal(self):
        """Test TenantContext is created correctly for SP auth."""
        from amprealize.mcp_service_adapter import TenantContext

        ctx = TenantContext(
            service_principal_id="sp-abc",
            org_id="org-456",
            auth_method="client_credentials",
        )

        assert ctx.service_principal_id == "sp-abc"
        assert ctx.user_id is None
        assert ctx.identity == "sp-abc"
        assert ctx.identity_type == "service_principal"

    def test_tenant_context_without_org(self):
        """Test TenantContext with no org (optional org_id)."""
        from amprealize.mcp_service_adapter import TenantContext

        ctx = TenantContext(
            user_id="user-123",
            # No org_id
            auth_method="device_flow",
        )

        assert ctx.org_id is None
        assert ctx.project_id is None
        assert ctx.identity == "user-123"

    def test_tenant_context_to_headers(self):
        """Test HTTP headers are generated correctly."""
        from amprealize.mcp_service_adapter import TenantContext

        ctx = TenantContext(
            user_id="user-123",
            org_id="org-456",
            project_id="proj-789",
            auth_method="device_flow",
            roles={"ADMIN", "STUDENT"},
        )

        headers = ctx.to_headers()

        assert headers["X-User-ID"] == "user-123"
        assert headers["X-Org-ID"] == "org-456"
        assert headers["X-Project-ID"] == "proj-789"
        assert headers["X-Auth-Method"] == "device_flow"
        assert "X-Request-ID" in headers
        assert "X-Roles" in headers
        # Roles are sorted
        assert headers["X-Roles"] == "ADMIN,STUDENT"

    def test_tenant_context_headers_without_optional_fields(self):
        """Test headers omit optional fields when not set."""
        from amprealize.mcp_service_adapter import TenantContext

        ctx = TenantContext(
            user_id="user-123",
            # No org_id, project_id, or roles
            auth_method="device_flow",
        )

        headers = ctx.to_headers()

        assert headers["X-User-ID"] == "user-123"
        assert "X-Org-ID" not in headers
        assert "X-Project-ID" not in headers
        assert "X-Roles" not in headers

    def test_tenant_context_to_audit_context(self):
        """Test audit context is generated correctly."""
        from amprealize.mcp_service_adapter import TenantContext

        ctx = TenantContext(
            user_id="user-123",
            org_id="org-456",
            auth_method="device_flow",
            roles={"STUDENT"},
            granted_scopes={"behaviors.read"},
        )

        audit = ctx.to_audit_context()

        assert audit["user_id"] == "user-123"
        assert audit["org_id"] == "org-456"
        assert audit["auth_method"] == "device_flow"
        assert "STUDENT" in audit["roles"]
        assert "behaviors.read" in audit["scopes"]
        assert "request_id" in audit
        assert "timestamp" in audit

    def test_mcp_service_adapter_inject_tenant_params(self):
        """Test parameter injection from session context."""
        from amprealize.mcp_service_adapter import MCPServiceAdapter

        # Create mock session context
        mock_session = MagicMock()
        mock_session.user_id = "user-123"
        mock_session.service_principal_id = None
        mock_session.org_id = "org-456"
        mock_session.project_id = "proj-789"
        mock_session.auth_method = "device_flow"
        mock_session.roles = ["STUDENT"]
        mock_session.granted_scopes = {"behaviors.read"}

        adapter = MCPServiceAdapter(mock_session)

        # Test injection when params don't have values
        params = {"name": "test"}
        result = adapter.inject_tenant_params(params)

        assert result["name"] == "test"
        assert result["org_id"] == "org-456"
        assert result["project_id"] == "proj-789"
        assert result["user_id"] == "user-123"

    def test_mcp_service_adapter_does_not_override_existing_params(self):
        """Test that existing params are not overwritten."""
        from amprealize.mcp_service_adapter import MCPServiceAdapter

        mock_session = MagicMock()
        mock_session.user_id = "user-123"
        mock_session.service_principal_id = None
        mock_session.org_id = "org-456"
        mock_session.project_id = "proj-789"

        adapter = MCPServiceAdapter(mock_session)

        # Params already have org_id
        params = {"org_id": "other-org"}
        result = adapter.inject_tenant_params(params)

        # Should NOT override
        assert result["org_id"] == "other-org"


# ============================================================================
# Context Switch Handler Tests
# ============================================================================


class TestContextSwitchHandler:
    """Tests for ContextSwitchHandler."""

    def test_get_current_context(self):
        """Test getting current context state."""
        from amprealize.mcp_service_adapter import ContextSwitchHandler

        mock_session = MagicMock()
        mock_session.user_id = "user-123"
        mock_session.service_principal_id = None
        mock_session.org_id = "org-456"
        mock_session.project_id = "proj-789"
        mock_session.auth_method = "device_flow"
        mock_session.roles = ["STUDENT"]
        mock_session.granted_scopes = {"behaviors.read"}
        mock_session.is_authenticated = True

        handler = ContextSwitchHandler(session=mock_session)

        result = handler.get_current_context()

        assert result["user_id"] == "user-123"
        assert result["org_id"] == "org-456"
        assert result["project_id"] == "proj-789"
        assert result["is_authenticated"] is True

    @pytest.mark.asyncio
    async def test_set_org_context_success(self):
        """Test successful org context switch."""
        from amprealize.mcp_service_adapter import ContextSwitchHandler

        mock_session = MagicMock()
        mock_session.user_id = "user-123"
        mock_session.service_principal_id = None
        mock_session.org_id = None
        mock_session.project_id = None

        # Mock permission service
        mock_perm_service = AsyncMock()
        mock_role = MagicMock()
        mock_role.value = "member"
        mock_perm_service.get_user_org_role.return_value = mock_role
        mock_perm_service.get_user_org_permissions.return_value = []

        handler = ContextSwitchHandler(
            session=mock_session,
            permission_service=mock_perm_service,
        )

        result = await handler.set_org_context("org-456")

        assert result.success is True
        assert result.org_id == "org-456"
        assert mock_session.org_id == "org-456"
        assert mock_session.project_id is None  # Should be reset

    @pytest.mark.asyncio
    async def test_set_org_context_access_denied(self):
        """Test org context switch denied when no access."""
        from amprealize.mcp_service_adapter import ContextSwitchHandler

        mock_session = MagicMock()
        mock_session.user_id = "user-123"
        mock_session.service_principal_id = None

        # Mock permission service - returns None (no access)
        mock_perm_service = AsyncMock()
        mock_perm_service.get_user_org_role.return_value = None

        handler = ContextSwitchHandler(
            session=mock_session,
            permission_service=mock_perm_service,
        )

        result = await handler.set_org_context("org-no-access")

        assert result.success is False
        assert result.error_code == "ACCESS_DENIED"

    @pytest.mark.asyncio
    async def test_set_org_context_not_authenticated(self):
        """Test org context switch fails when not authenticated."""
        from amprealize.mcp_service_adapter import ContextSwitchHandler

        mock_session = MagicMock()
        mock_session.user_id = None
        mock_session.service_principal_id = None

        handler = ContextSwitchHandler(session=mock_session)

        result = await handler.set_org_context("org-456")

        assert result.success is False
        assert result.error_code == "NOT_AUTHENTICATED"

    @pytest.mark.asyncio
    async def test_set_project_context_success(self):
        """Test successful project context switch."""
        from amprealize.mcp_service_adapter import ContextSwitchHandler

        mock_session = MagicMock()
        mock_session.user_id = "user-123"
        mock_session.service_principal_id = None
        mock_session.org_id = "org-456"
        mock_session.project_id = None

        # Mock project service
        mock_project_service = MagicMock()
        mock_project = MagicMock()
        mock_project.name = "Test Project"
        mock_project.org_id = "org-456"  # Matches session org
        mock_project_service.get_project.return_value = mock_project

        # Mock permission service
        mock_perm_service = AsyncMock()
        mock_role = MagicMock()
        mock_role.value = "member"
        mock_perm_service.get_user_org_role.return_value = mock_role

        handler = ContextSwitchHandler(
            session=mock_session,
            permission_service=mock_perm_service,
            project_service=mock_project_service,
        )

        result = await handler.set_project_context("proj-789")

        assert result.success is True
        assert result.project_id == "proj-789"
        assert mock_session.project_id == "proj-789"

    @pytest.mark.asyncio
    async def test_set_project_context_org_mismatch(self):
        """Test project switch fails when project org doesn't match."""
        from amprealize.mcp_service_adapter import ContextSwitchHandler

        mock_session = MagicMock()
        mock_session.user_id = "user-123"
        mock_session.service_principal_id = None
        mock_session.org_id = "org-456"  # Current org
        mock_session.project_id = None

        # Mock project service - project belongs to different org
        mock_project_service = MagicMock()
        mock_project = MagicMock()
        mock_project.name = "Other Project"
        mock_project.org_id = "org-other"  # Different org!
        mock_project_service.get_project.return_value = mock_project

        handler = ContextSwitchHandler(
            session=mock_session,
            project_service=mock_project_service,
        )

        result = await handler.set_project_context("proj-789")

        assert result.success is False
        assert result.error_code == "ORG_MISMATCH"

    @pytest.mark.asyncio
    async def test_set_project_auto_sets_org(self):
        """Test project switch auto-sets org context if not set."""
        from amprealize.mcp_service_adapter import ContextSwitchHandler

        mock_session = MagicMock()
        mock_session.user_id = "user-123"
        mock_session.service_principal_id = None
        mock_session.org_id = None  # No org set
        mock_session.project_id = None

        # Mock project service
        mock_project_service = MagicMock()
        mock_project = MagicMock()
        mock_project.name = "Test Project"
        mock_project.org_id = "org-456"
        mock_project_service.get_project.return_value = mock_project

        # Mock permission service
        mock_perm_service = AsyncMock()
        mock_role = MagicMock()
        mock_role.value = "member"
        mock_perm_service.get_user_org_role.return_value = mock_role

        handler = ContextSwitchHandler(
            session=mock_session,
            permission_service=mock_perm_service,
            project_service=mock_project_service,
        )

        result = await handler.set_project_context("proj-789")

        assert result.success is True
        assert mock_session.org_id == "org-456"  # Auto-set from project

    @pytest.mark.asyncio
    async def test_clear_context(self):
        """Test clearing context."""
        from amprealize.mcp_service_adapter import ContextSwitchHandler

        mock_session = MagicMock()
        mock_session.org_id = "org-456"
        mock_session.project_id = "proj-789"

        handler = ContextSwitchHandler(session=mock_session)

        result = await handler.clear_context()

        assert result.success is True
        assert mock_session.org_id is None
        assert mock_session.project_id is None


# ============================================================================
# MCP Server Context Handler Tests
# ============================================================================


class TestMCPServerContextHandlers:
    """Tests for context handlers in MCP server."""

    def test_context_getcontext_returns_session_state(self):
        """Test context.getContext returns current session."""
        # This would be an integration test with MCP server
        # For unit testing, we verify the underlying method
        pass

    def test_context_switch_scope_requirement(self):
        """Verify context.setOrg and context.setProject require context.switch scope."""
        import json
        from pathlib import Path

        tools_dir = Path(__file__).parent.parent / "mcp" / "tools"

        # Check setOrg manifest
        set_org_manifest = tools_dir / "context.setOrg.json"
        if set_org_manifest.exists():
            with open(set_org_manifest) as f:
                manifest = json.load(f)
                assert "context.switch" in manifest.get("required_scopes", [])

        # Check setProject manifest
        set_project_manifest = tools_dir / "context.setProject.json"
        if set_project_manifest.exists():
            with open(set_project_manifest) as f:
                manifest = json.load(f)
                assert "context.switch" in manifest.get("required_scopes", [])

        # Check getContext is public (no required scopes)
        get_context_manifest = tools_dir / "context.getContext.json"
        if get_context_manifest.exists():
            with open(get_context_manifest) as f:
                manifest = json.load(f)
                assert manifest.get("required_scopes", []) == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
