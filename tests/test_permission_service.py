"""Unit tests for PermissionService RBAC operations.

Tests permission checking, role-based access, and permission enforcement
for organizations and projects.

Following behavior_design_test_strategy (Student):
- Unit tests with mocks for database layer
- Tests for happy path and error cases
- Test pyramid: comprehensive unit coverage for RBAC
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock
from typing import List, Dict, Any, Optional

# Import contracts for type checking
from amprealize.projects.contracts import (
    MemberRole,
    ProjectRole,
)
from amprealize.tenant.permissions import (
    OrgPermission,
    ProjectPermission,
    PermissionService,
    PermissionDenied,
    NotAMember,
    UserOrgContext,
    UserProjectContext,
    ORG_ROLE_PERMISSIONS,
    PROJECT_ROLE_PERMISSIONS,
    require_org_permission_decorator,
    require_project_permission_decorator,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_pool():
    """Create mock PostgreSQL connection pool with context manager."""
    pool = MagicMock()
    connection = MagicMock()
    cursor = MagicMock()

    # The service code calls conn.cursor() directly (not as context manager)
    connection.cursor.return_value = cursor

    # Setup pool.connection() context manager
    connection_ctx = MagicMock()
    connection_ctx.__enter__ = MagicMock(return_value=connection)
    connection_ctx.__exit__ = MagicMock(return_value=False)
    pool.connection.return_value = connection_ctx

    return pool, connection, cursor


@pytest.fixture
def permission_service(mock_pool):
    """Create PermissionService with mocked pool."""
    pool, connection, cursor = mock_pool

    service = PermissionService(pool=pool)

    return service, cursor


# =============================================================================
# Permission Matrix Tests
# =============================================================================

@pytest.mark.unit
class TestPermissionMatrix:
    """Test the permission matrices are correctly configured."""

    def test_owner_has_all_org_permissions(self):
        """Owner role should have all organization permissions."""
        owner_perms = ORG_ROLE_PERMISSIONS[MemberRole.OWNER]
        all_perms = set(OrgPermission)

        # Owner should have every permission
        assert owner_perms == all_perms

    def test_admin_has_most_org_permissions(self):
        """Admin role should have most permissions except destructive ones."""
        admin_perms = ORG_ROLE_PERMISSIONS[MemberRole.ADMIN]

        # Admin should NOT have
        assert OrgPermission.DELETE_ORG not in admin_perms
        assert OrgPermission.TRANSFER_OWNERSHIP not in admin_perms

        # Admin SHOULD have
        assert OrgPermission.VIEW_ORG in admin_perms
        assert OrgPermission.UPDATE_SETTINGS in admin_perms
        assert OrgPermission.INVITE_MEMBERS in admin_perms
        assert OrgPermission.VIEW_BILLING in admin_perms
        assert OrgPermission.VIEW_AUDIT_LOG in admin_perms

    def test_member_has_basic_org_permissions(self):
        """Member role should have basic operational permissions."""
        member_perms = ORG_ROLE_PERMISSIONS[MemberRole.MEMBER]

        # Member should have
        assert OrgPermission.VIEW_ORG in member_perms
        assert OrgPermission.CREATE_PROJECTS in member_perms
        assert OrgPermission.VIEW_SETTINGS in member_perms

        # Member should NOT have
        assert OrgPermission.UPDATE_SETTINGS not in member_perms
        assert OrgPermission.MANAGE_BILLING not in member_perms
        assert OrgPermission.INVITE_MEMBERS not in member_perms
        assert OrgPermission.UPDATE_MEMBER_ROLES not in member_perms

    def test_viewer_has_read_only_org_permissions(self):
        """Viewer role should only have view permissions."""
        viewer_perms = ORG_ROLE_PERMISSIONS[MemberRole.VIEWER]

        # Viewer should only have view/read permissions
        assert OrgPermission.VIEW_ORG in viewer_perms
        assert OrgPermission.VIEW_MEMBERS in viewer_perms
        assert OrgPermission.VIEW_PROJECTS in viewer_perms
        assert OrgPermission.VIEW_AGENTS in viewer_perms

        # Viewer should NOT have any write permissions
        assert OrgPermission.UPDATE_SETTINGS not in viewer_perms
        assert OrgPermission.CREATE_PROJECTS not in viewer_perms
        assert OrgPermission.INVITE_MEMBERS not in viewer_perms
        assert OrgPermission.MANAGE_BILLING not in viewer_perms

    def test_project_owner_has_all_project_permissions(self):
        """Project owner should have all project permissions."""
        owner_perms = PROJECT_ROLE_PERMISSIONS[ProjectRole.OWNER]
        all_perms = set(ProjectPermission)

        assert owner_perms == all_perms

    def test_project_maintainer_permissions(self):
        """Maintainer should have most permissions except destructive ones."""
        maintainer_perms = PROJECT_ROLE_PERMISSIONS[ProjectRole.MAINTAINER]

        # Maintainer should NOT have
        assert ProjectPermission.DELETE_PROJECT not in maintainer_perms
        assert ProjectPermission.TRANSFER_OWNERSHIP not in maintainer_perms
        assert ProjectPermission.ARCHIVE_PROJECT not in maintainer_perms

        # Maintainer SHOULD have
        assert ProjectPermission.VIEW_PROJECT in maintainer_perms
        assert ProjectPermission.UPDATE_SETTINGS in maintainer_perms
        assert ProjectPermission.INVITE_MEMBERS in maintainer_perms
        assert ProjectPermission.CREATE_RUNS in maintainer_perms

    def test_project_contributor_permissions(self):
        """Contributor should have operational permissions."""
        contributor_perms = PROJECT_ROLE_PERMISSIONS[ProjectRole.CONTRIBUTOR]

        # Contributor should have
        assert ProjectPermission.VIEW_PROJECT in contributor_perms
        assert ProjectPermission.CREATE_RUNS in contributor_perms
        assert ProjectPermission.CREATE_BEHAVIORS in contributor_perms

        # Contributor should NOT have
        assert ProjectPermission.UPDATE_SETTINGS not in contributor_perms
        assert ProjectPermission.INVITE_MEMBERS not in contributor_perms
        assert ProjectPermission.DELETE_PROJECT not in contributor_perms

    def test_project_viewer_read_only_permissions(self):
        """Project viewer should only have read permissions."""
        viewer_perms = PROJECT_ROLE_PERMISSIONS[ProjectRole.VIEWER]

        # Viewer should only have view permissions
        assert ProjectPermission.VIEW_PROJECT in viewer_perms
        assert ProjectPermission.VIEW_RUNS in viewer_perms
        assert ProjectPermission.VIEW_BEHAVIORS in viewer_perms

        # Viewer should NOT have any write permissions
        assert ProjectPermission.CREATE_RUNS not in viewer_perms
        assert ProjectPermission.UPDATE_SETTINGS not in viewer_perms
        assert ProjectPermission.CREATE_BEHAVIORS not in viewer_perms


# =============================================================================
# PermissionService - Organization Permission Tests
# =============================================================================

class TestOrgPermissionChecking:
    """Test organization-level permission checking."""

    def test_get_user_org_role_returns_role(self, permission_service):
        """get_user_org_role returns correct role when user is member."""
        service, cursor = permission_service

        # Mock database return - user is ADMIN
        cursor.fetchone.return_value = ("admin",)

        role = service.get_user_org_role("user-123", "org-456")

        assert role == MemberRole.ADMIN
        cursor.execute.assert_called_once()

    def test_get_user_org_role_returns_none_for_non_member(self, permission_service):
        """get_user_org_role returns None when user is not a member."""
        service, cursor = permission_service

        # Mock database return - no membership found
        cursor.fetchone.return_value = None

        role = service.get_user_org_role("user-123", "org-456")

        assert role is None

    def test_has_org_permission_returns_true_for_admin(self, permission_service):
        """has_org_permission returns allowed=True when admin has permission."""
        service, cursor = permission_service

        # User is an admin
        cursor.fetchone.return_value = ("admin",)

        result = service.has_org_permission(
            "user-123",
            "org-456",
            OrgPermission.INVITE_MEMBERS
        )

        assert result.allowed is True

    def test_has_org_permission_returns_false_for_viewer(self, permission_service):
        """has_org_permission returns allowed=False when viewer lacks permission."""
        service, cursor = permission_service

        # User is a viewer
        cursor.fetchone.return_value = ("viewer",)

        result = service.has_org_permission(
            "user-123",
            "org-456",
            OrgPermission.INVITE_MEMBERS
        )

        assert result.allowed is False

    def test_has_org_permission_returns_false_for_non_member(self, permission_service):
        """has_org_permission returns allowed=False when user is not a member."""
        service, cursor = permission_service

        # No membership
        cursor.fetchone.return_value = None

        result = service.has_org_permission(
            "user-123",
            "org-456",
            OrgPermission.VIEW_ORG
        )

        assert result.allowed is False

    def test_require_org_permission_succeeds_for_valid_permission(self, permission_service):
        """require_org_permission does not raise when permission exists."""
        service, cursor = permission_service

        # User is owner
        cursor.fetchone.return_value = ("owner",)

        # Should not raise
        service.require_org_permission(
            "user-123",
            "org-456",
            OrgPermission.DELETE_ORG
        )

    def test_require_org_permission_raises_for_non_member(self, permission_service):
        """require_org_permission raises NotAMember when not a member."""
        service, cursor = permission_service

        # No membership
        cursor.fetchone.return_value = None

        with pytest.raises(NotAMember) as exc_info:
            service.require_org_permission(
                "user-123",
                "org-456",
                OrgPermission.VIEW_ORG
            )

        assert exc_info.value.user_id == "user-123"
        assert exc_info.value.resource_id == "org-456"

    def test_require_org_permission_raises_for_insufficient_permission(self, permission_service):
        """require_org_permission raises PermissionDenied when lacking permission."""
        service, cursor = permission_service

        # User is member (not admin)
        cursor.fetchone.return_value = ("member",)

        with pytest.raises(PermissionDenied) as exc_info:
            service.require_org_permission(
                "user-123",
                "org-456",
                OrgPermission.MANAGE_BILLING
            )

        assert exc_info.value.user_id == "user-123"
        assert exc_info.value.resource_id == "org-456"
        assert exc_info.value.permission == OrgPermission.MANAGE_BILLING

    def test_get_user_org_context_returns_full_context(self, permission_service):
        """get_user_org_context returns complete context with permissions."""
        service, cursor = permission_service

        # User is admin
        cursor.fetchone.return_value = ("admin",)

        context = service.get_user_org_context("user-123", "org-456")

        assert context is not None
        assert context.user_id == "user-123"
        assert context.org_id == "org-456"
        assert context.role == MemberRole.ADMIN
        assert OrgPermission.INVITE_MEMBERS in context.permissions
        assert OrgPermission.DELETE_ORG not in context.permissions

    def test_get_user_org_context_returns_none_for_non_member(self, permission_service):
        """get_user_org_context returns None when not a member."""
        service, cursor = permission_service

        cursor.fetchone.return_value = None

        context = service.get_user_org_context("user-123", "org-456")

        assert context is None


# =============================================================================
# PermissionService - Project Permission Tests
# =============================================================================

class TestProjectPermissionChecking:
    """Test project-level permission checking."""

    def test_get_user_project_role_from_collaborator(self, permission_service):
        """get_user_project_role returns role from project_collaborators."""
        service, cursor = permission_service

        # 4 fetchone calls: owner check -> None, membership -> None, collaborator -> maintainer
        cursor.fetchone.side_effect = [None, None, ("maintainer",)]

        role = service.get_user_project_role("user-123", "proj-789")

        assert role == ProjectRole.MAINTAINER

    def test_get_user_project_role_inherits_from_org_owner(self, permission_service):
        """get_user_project_role inherits from org owner role."""
        service, cursor = permission_service

        # owner check -> None, membership -> None, collaborator -> None, org -> owner
        cursor.fetchone.side_effect = [None, None, None, ("owner",)]

        role = service.get_user_project_role("user-123", "proj-789")

        assert role == ProjectRole.OWNER

    def test_get_user_project_role_inherits_from_org_admin(self, permission_service):
        """get_user_project_role inherits from org admin role."""
        service, cursor = permission_service

        # owner check -> None, membership -> None, collaborator -> None, org -> admin
        cursor.fetchone.side_effect = [None, None, None, ("admin",)]

        role = service.get_user_project_role("user-123", "proj-789")

        assert role == ProjectRole.MAINTAINER

    def test_get_user_project_role_inherits_from_org_member(self, permission_service):
        """get_user_project_role inherits from org member role."""
        service, cursor = permission_service

        # owner check -> None, membership -> None, collaborator -> None, org -> member
        cursor.fetchone.side_effect = [None, None, None, ("member",)]

        role = service.get_user_project_role("user-123", "proj-789")

        assert role == ProjectRole.CONTRIBUTOR

    def test_get_user_project_role_inherits_from_org_viewer(self, permission_service):
        """get_user_project_role inherits from org viewer role."""
        service, cursor = permission_service

        # owner check -> None, membership -> None, collaborator -> None, org -> viewer
        cursor.fetchone.side_effect = [None, None, None, ("viewer",)]

        role = service.get_user_project_role("user-123", "proj-789")

        assert role == ProjectRole.VIEWER

    def test_has_project_permission_returns_true_for_maintainer(self, permission_service):
        """has_project_permission returns allowed=True when maintainer has permission."""
        service, cursor = permission_service

        # Mock get_user_project_role to avoid complex cursor side_effect
        with patch.object(service, 'get_user_project_role', return_value=ProjectRole.MAINTAINER):
            result = service.has_project_permission(
                "user-123",
                "proj-789",
                ProjectPermission.INVITE_MEMBERS
            )

        assert result.allowed

    def test_has_project_permission_returns_false_for_viewer(self, permission_service):
        """has_project_permission returns allowed=False when viewer lacks permission."""
        service, cursor = permission_service

        with patch.object(service, 'get_user_project_role', return_value=ProjectRole.VIEWER):
            result = service.has_project_permission(
                "user-123",
                "proj-789",
                ProjectPermission.CREATE_RUNS
            )

        assert not result.allowed

    def test_require_project_permission_succeeds_for_owner(self, permission_service):
        """require_project_permission does not raise when owner has permission."""
        service, cursor = permission_service

        with patch.object(service, 'get_user_project_role', return_value=ProjectRole.OWNER):
            # Should not raise
            service.require_project_permission(
                "user-123",
                "proj-789",
                ProjectPermission.DELETE_PROJECT
            )

    def test_require_project_permission_raises_for_contributor(self, permission_service):
        """require_project_permission raises PermissionDenied for insufficient role."""
        service, cursor = permission_service

        with patch.object(service, 'get_user_project_role', return_value=ProjectRole.CONTRIBUTOR):
            with pytest.raises(PermissionDenied) as exc_info:
                service.require_project_permission(
                    "user-123",
                    "proj-789",
                    ProjectPermission.DELETE_PROJECT
                )

        assert exc_info.value.permission == ProjectPermission.DELETE_PROJECT

    def test_get_user_project_context_returns_full_context(self, permission_service):
        """get_user_project_context returns context with permissions."""
        service, cursor = permission_service

        with patch.object(service, 'get_user_project_role', return_value=ProjectRole.CONTRIBUTOR):
            context = service.get_user_project_context(
                "user-123",
                "proj-789"
            )

        assert context is not None
        assert context.user_id == "user-123"
        assert context.project_id == "proj-789"
        assert context.role == ProjectRole.CONTRIBUTOR
        assert ProjectPermission.CREATE_RUNS in context.permissions
        assert ProjectPermission.DELETE_PROJECT not in context.permissions


# =============================================================================
# Filter / Bulk Access Tests
# =============================================================================

class TestFilterAccessible:
    """Test bulk access filtering methods."""

    def test_filter_accessible_orgs(self, permission_service):
        """filter_accessible_orgs returns orgs user can access."""
        service, cursor = permission_service

        # Mock get_user_org_role directly (cursor mock doesn't wire correctly)
        with patch.object(service, 'get_user_org_role') as mock_role:
            mock_role.side_effect = [MemberRole.MEMBER, None, MemberRole.MEMBER]

            org_ids = ["org-1", "org-2", "org-3"]
            accessible = service.filter_accessible_orgs("user-123", org_ids)

        assert len(accessible) == 2
        assert "org-1" in accessible
        assert "org-3" in accessible
        assert "org-2" not in accessible

    def test_filter_accessible_projects(self, permission_service):
        """filter_accessible_projects returns projects user can access."""
        service, cursor = permission_service

        # Mock get_user_project_role directly (it makes multiple DB calls per project)
        with patch.object(service, 'get_user_project_role') as mock_role:
            mock_role.side_effect = [ProjectRole.CONTRIBUTOR, None, ProjectRole.VIEWER]

            project_ids = ["proj-a", "proj-b", "proj-c"]
            accessible = service.filter_accessible_projects("user-123", project_ids)

            assert len(accessible) == 2
            assert "proj-a" in accessible
            assert "proj-c" in accessible
            assert "proj-b" not in accessible

    def test_get_user_org_permissions(self, permission_service):
        """get_user_org_permissions returns permission set."""
        service, cursor = permission_service

        with patch.object(service, 'get_user_org_role', return_value=MemberRole.ADMIN):
            permissions = service.get_user_org_permissions("user-123", "org-456")

        assert permissions is not None
        assert OrgPermission.VIEW_ORG in permissions
        assert OrgPermission.INVITE_MEMBERS in permissions
        assert OrgPermission.DELETE_ORG not in permissions  # Admin can't delete

    def test_get_user_project_permissions(self, permission_service):
        """get_user_project_permissions returns permission set."""
        service, cursor = permission_service

        with patch.object(service, 'get_user_project_role', return_value=ProjectRole.CONTRIBUTOR):
            permissions = service.get_user_project_permissions("user-123", "proj-789")

        assert permissions is not None
        assert ProjectPermission.VIEW_PROJECT in permissions
        assert ProjectPermission.CREATE_RUNS in permissions
        assert ProjectPermission.DELETE_PROJECT not in permissions


# =============================================================================
# Exception Tests
# =============================================================================

@pytest.mark.unit
class TestPermissionExceptions:
    """Test permission exception classes."""

    def test_permission_denied_message(self):
        """PermissionDenied has descriptive message."""
        exc = PermissionDenied(
            permission=OrgPermission.DELETE_ORG,
            user_id="user-123",
            resource_id="org-456",
        )

        assert "user-123" in str(exc)
        assert "org-456" in str(exc)
        assert "org:delete" in str(exc)
        assert exc.user_id == "user-123"
        assert exc.resource_id == "org-456"

    def test_not_a_member_message(self):
        """NotAMember has descriptive message."""
        exc = NotAMember(
            user_id="user-123",
            resource_id="org-456",
            resource_type="organization"
        )

        assert "user-123" in str(exc)
        assert "org-456" in str(exc)
        assert "not a member" in str(exc).lower()


# =============================================================================
# Decorator Tests
# =============================================================================

@pytest.mark.unit
class TestPermissionDecorators:
    """Test FastAPI permission decorators."""

    def test_require_org_permission_decorator_passes(self, mock_pool):
        """Decorator allows request when permission exists."""
        import asyncio

        pool, connection, cursor = mock_pool

        @require_org_permission_decorator(OrgPermission.DELETE_ORG)
        async def protected_endpoint(request, org_id):
            return {"status": "ok"}

        # Mock request with MagicMock permission_service (avoids cursor wiring)
        mock_request = MagicMock()
        mock_request.state.user_id = "user-123"
        mock_request.state.permission_service = MagicMock()

        # Should not raise
        result = asyncio.run(
            protected_endpoint(request=mock_request, org_id="org-456")
        )
        assert result["status"] == "ok"

    def test_require_project_permission_decorator_passes(self, mock_pool):
        """Project decorator allows request when permission exists."""
        import asyncio

        pool, connection, cursor = mock_pool

        @require_project_permission_decorator(ProjectPermission.DELETE_PROJECT)
        async def protected_endpoint(request, project_id):
            return {"status": "ok"}

        # Mock request with MagicMock permission_service (avoids cursor wiring)
        mock_request = MagicMock()
        mock_request.state.user_id = "user-123"
        mock_request.state.permission_service = MagicMock()

        # Should not raise
        result = asyncio.run(
            protected_endpoint(request=mock_request, project_id="proj-789")
        )
        assert result["status"] == "ok"


# =============================================================================
# User Context Dataclass Tests
# =============================================================================

@pytest.mark.unit
class TestUserContextDataclasses:
    """Test UserOrgContext and UserProjectContext dataclasses."""

    def test_user_org_context_has_permission(self):
        """UserOrgContext permission check via 'in' operator."""
        context = UserOrgContext(
            user_id="user-123",
            org_id="org-456",
            role=MemberRole.ADMIN,
            permissions=ORG_ROLE_PERMISSIONS[MemberRole.ADMIN]
        )

        assert OrgPermission.INVITE_MEMBERS in context.permissions
        assert OrgPermission.DELETE_ORG not in context.permissions

    def test_user_project_context_has_permission(self):
        """UserProjectContext permission check via 'in' operator."""
        context = UserProjectContext(
            user_id="user-123",
            project_id="proj-789",
            role=ProjectRole.CONTRIBUTOR,
            permissions=PROJECT_ROLE_PERMISSIONS[ProjectRole.CONTRIBUTOR]
        )

        assert ProjectPermission.CREATE_RUNS in context.permissions
        assert ProjectPermission.DELETE_PROJECT not in context.permissions
