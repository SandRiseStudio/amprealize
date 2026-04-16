"""Unit tests for OrganizationService CRUD operations.

Tests Project CRUD (get, update, delete, restore), Project Membership
management, User-Owned Projects, and Collaborator operations.

Following behavior_design_test_strategy (Student):
- Unit tests with mocks for database layer
- Tests for happy path and error cases
- 70% unit coverage target
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError
from unittest.mock import MagicMock, patch, call
from typing import List, Dict, Any, Optional

from amprealize.multi_tenant.organization_service import OrganizationService

# Mark all tests as unit; skip if enterprise not installed
pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(OrganizationService is None, reason="OrganizationService requires amprealize-enterprise"),
]

# Import contracts for type checking
from amprealize.projects.contracts import (
    Project,
    ProjectMembership,
    ProjectRole,
    ProjectVisibility,
    MemberRole,
    UpdateProjectRequest,
    CreateProjectMembershipRequest,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_pool():
    """Create mock PostgreSQL connection pool with proper context manager."""
    pool = MagicMock()
    connection = MagicMock()
    cursor = MagicMock()

    # Setup cursor() to return the mock cursor
    connection.cursor.return_value = cursor

    # Setup pool.connection() context manager
    connection_ctx = MagicMock()
    connection_ctx.__enter__ = MagicMock(return_value=connection)
    connection_ctx.__exit__ = MagicMock(return_value=False)
    pool.connection.return_value = connection_ctx

    return pool, connection, cursor


@pytest.fixture
def org_service(mock_pool):
    """Create OrganizationService with mocked pool."""
    pool, connection, cursor = mock_pool

    from amprealize.multi_tenant.organization_service import OrganizationService

    # Create service with mock pool directly (bypass dsn path)
    service = OrganizationService(pool=pool)

    return service, cursor


@pytest.fixture
def sample_project() -> tuple:
    """Sample project data as returned by database (tuple format).

    Column order matches: project_id, org_id, owner_id, name, slug, description,
    visibility, settings, archived_at, created_at, updated_at
    """
    return (
        "proj-abc123",                                           # project_id
        "org-xyz789",                                            # org_id
        "user-owner456",                                         # owner_id
        "Test Project",                                          # name
        "test-project",                                          # slug
        "A test project",                                        # description
        "private",                                               # visibility
        {},                                                      # settings
        None,                                                    # archived_at
        datetime(2024, 1, 1, tzinfo=timezone.utc),              # created_at
        datetime(2024, 1, 1, tzinfo=timezone.utc),              # updated_at
    )

@pytest.fixture
def sample_project_membership() -> tuple:
    """Sample project membership data (tuple format).

    Column order matches: membership_id, project_id, user_id, role,
    created_at, updated_at
    """
    return (
        "pmem-abc123",                                           # membership_id
        "proj-abc123",                                           # project_id
        "user-123",                                              # user_id
        "owner",                                                 # role
        datetime(2024, 1, 1, tzinfo=timezone.utc),              # created_at
        datetime(2024, 1, 1, tzinfo=timezone.utc),              # updated_at
    )


# Shared marker for unimplemented methods
_xfail_unimplemented = pytest.mark.xfail(
    reason="Not yet implemented in amprealize-enterprise OrganizationService",
    strict=True,
)


# =============================================================================
# Project CRUD Tests
# =============================================================================

@_xfail_unimplemented
@pytest.mark.unit
class TestGetProject:
    """Tests for get_project method."""

    def test_get_project_by_id(self, org_service, sample_project):
        """Successfully retrieve project by ID."""
        service, cursor = org_service
        cursor.fetchone.return_value = sample_project

        result = service.get_project("proj-abc123")

        assert result is not None
        assert result.id == "proj-abc123"
        assert result.name == "Test Project"
        assert result.slug == "test-project"
        cursor.execute.assert_called_once()

    def test_get_project_with_org_filter(self, org_service, sample_project):
        """Retrieve project with org_id validation."""
        service, cursor = org_service
        cursor.fetchone.return_value = sample_project

        result = service.get_project("proj-abc123", org_id="org-xyz789")

        assert result is not None
        assert result.org_id == "org-xyz789"
        # Verify org_id was included in query
        call_args = cursor.execute.call_args[0]
        assert "org-xyz789" in str(call_args)

    def test_get_project_not_found(self, org_service):
        """Return None when project doesn't exist."""
        service, cursor = org_service
        cursor.fetchone.return_value = None

        result = service.get_project("nonexistent-id")

        assert result is None

    def test_get_project_archived_excluded(self, org_service, sample_project):
        """Archived projects are not returned by default."""
        service, cursor = org_service
        # Return None to simulate archived project being filtered
        cursor.fetchone.return_value = None

        result = service.get_project("proj-archived")

        assert result is None
        # Verify archived_at IS NULL in query
        call_args = cursor.execute.call_args[0][0]
        assert "archived_at IS NULL" in call_args


@_xfail_unimplemented
@pytest.mark.unit
class TestGetProjectBySlug:
    """Tests for get_project_by_slug method."""

    def test_get_project_by_slug_success(self, org_service, sample_project):
        """Successfully retrieve project by org_id and slug."""
        service, cursor = org_service
        cursor.fetchone.return_value = sample_project

        result = service.get_project_by_slug("org-xyz789", "test-project")

        assert result is not None
        assert result.slug == "test-project"
        assert result.org_id == "org-xyz789"

    def test_get_project_by_slug_not_found(self, org_service):
        """Return None when slug doesn't exist in org."""
        service, cursor = org_service
        cursor.fetchone.return_value = None

        result = service.get_project_by_slug("org-xyz789", "nonexistent-slug")

        assert result is None


@_xfail_unimplemented
@pytest.mark.unit
class TestUpdateProject:
    """Tests for update_project method."""

    def test_update_project_name(self, org_service, sample_project):
        """Successfully update project name."""
        service, cursor = org_service

        # First call gets project for returning, then update returns affected row
        cursor.fetchone.return_value = sample_project
        cursor.rowcount = 1

        request = UpdateProjectRequest(name="Updated Name")
        result = service.update_project("proj-abc123", request)

        assert result is not None
        # Verify UPDATE was called
        call_args_str = " ".join(str(c) for c in cursor.execute.call_args_list)
        assert "UPDATE" in call_args_str

    def test_update_project_visibility(self, org_service, sample_project):
        """Update project visibility setting."""
        service, cursor = org_service
        cursor.fetchone.return_value = sample_project
        cursor.rowcount = 1

        request = UpdateProjectRequest(visibility=ProjectVisibility.INTERNAL)
        result = service.update_project("proj-abc123", request)

        assert result is not None

    def test_update_project_not_found(self, org_service):
        """Return None when project doesn't exist."""
        service, cursor = org_service
        cursor.fetchone.return_value = None
        cursor.rowcount = 0

        request = UpdateProjectRequest(name="New Name")
        result = service.update_project("nonexistent", request)

        assert result is None

    def test_update_project_no_changes(self, org_service, sample_project):
        """Handle update request with no fields set."""
        service, cursor = org_service
        cursor.fetchone.return_value = sample_project

        request = UpdateProjectRequest()  # No fields set
        result = service.update_project("proj-abc123", request)

        # Should return existing project without UPDATE
        assert result is not None


@_xfail_unimplemented
@pytest.mark.unit
class TestDeleteProject:
    """Tests for delete_project (soft delete) method."""

    def test_delete_project_success(self, org_service, sample_project):
        """Successfully soft-delete a project."""
        service, cursor = org_service
        cursor.rowcount = 1

        result = service.delete_project("proj-abc123")

        assert result is True
        # Verify soft delete (SET archived_at) was used
        call_args_str = " ".join(str(c) for c in cursor.execute.call_args_list)
        assert "UPDATE" in call_args_str and "archived_at" in call_args_str

    def test_delete_project_unassigns_agents(self, org_service, sample_project):
        """Deleting project sets agents' project_id to NULL."""
        service, cursor = org_service
        cursor.rowcount = 1

        result = service.delete_project("proj-abc123")

        assert result is True
        # Verify agents were unassigned
        call_args_str = " ".join(str(c) for c in cursor.execute.call_args_list)
        assert "agents" in call_args_str.lower() or "project_id" in call_args_str

    def test_delete_project_not_found(self, org_service):
        """Return False when project doesn't exist."""
        service, cursor = org_service
        cursor.rowcount = 0

        result = service.delete_project("nonexistent")

        assert result is False

    def test_delete_project_already_deleted(self, org_service, sample_project):
        """Handle already-deleted (archived) project."""
        service, cursor = org_service
        cursor.rowcount = 0  # No rows updated

        result = service.delete_project("proj-abc123")

        assert result is False


@_xfail_unimplemented
@pytest.mark.unit
class TestRestoreProject:
    """Tests for restore_project method."""

    def test_restore_project_success(self, org_service, sample_project):
        """Successfully restore an archived project."""
        service, cursor = org_service
        cursor.fetchone.return_value = sample_project
        cursor.rowcount = 1

        result = service.restore_project("proj-abc123")

        assert result is not None
        # Verify archived_at was cleared
        call_args_str = " ".join(str(c) for c in cursor.execute.call_args_list)
        assert "archived_at" in call_args_str

    def test_restore_project_not_archived(self, org_service, sample_project):
        """Handle restore of non-archived project."""
        service, cursor = org_service
        cursor.fetchone.return_value = sample_project  # Not archived
        cursor.rowcount = 1

        result = service.restore_project("proj-abc123")

        # Should still succeed or return existing project
        assert result is not None

    def test_restore_project_not_found(self, org_service):
        """Return None when project doesn't exist."""
        service, cursor = org_service
        cursor.fetchone.return_value = None
        cursor.rowcount = 0

        result = service.restore_project("nonexistent")

        assert result is None


# =============================================================================
# Project Membership Tests
# =============================================================================

@_xfail_unimplemented
@pytest.mark.unit
class TestAddProjectMember:
    """Tests for add_project_member method."""

    def test_add_member_success(self, org_service, sample_project_membership):
        """Successfully add a member to a project."""
        service, cursor = org_service
        # No existing membership
        cursor.fetchone.return_value = None

        result = service.add_project_member(
            project_id="proj-abc123",
            user_id="user-456",
            role=ProjectRole.CONTRIBUTOR,
        )

        assert result is not None
        # Verify INSERT was called
        call_args_str = " ".join(str(c) for c in cursor.execute.call_args_list)
        assert "INSERT" in call_args_str and "project_memberships" in call_args_str

    def test_add_member_duplicate(self, org_service, sample_project_membership):
        """Handle adding duplicate member."""
        service, cursor = org_service
        cursor.fetchone.return_value = sample_project_membership  # Already exists

        with pytest.raises(ValueError):
            service.add_project_member(
                project_id="proj-abc123",
                user_id="user-123",
                role=ProjectRole.VIEWER,
            )

    def test_add_member_project_not_found(self, org_service):
        """Adding member to nonexistent project still creates membership."""
        service, cursor = org_service
        cursor.fetchone.return_value = None  # No existing membership

        # The service doesn't validate project existence before adding membership
        # (that's handled by FK constraints in the database)
        result = service.add_project_member(
            project_id="nonexistent",
            user_id="user-456",
            role=ProjectRole.VIEWER,
        )

        assert result is not None


@_xfail_unimplemented
@pytest.mark.unit
class TestRemoveProjectMember:
    """Tests for remove_project_member method."""

    def test_remove_member_success(self, org_service):
        """Successfully remove a member from a project."""
        service, cursor = org_service
        # First fetchone: owner count = 2, second fetchone: is_owner = False
        cursor.fetchone.side_effect = [
            (2,),  # owner count
            (False,),  # is_owner check
        ]
        cursor.rowcount = 1  # DELETE succeeded

        result = service.remove_project_member("proj-abc123", "user-456")

        assert result is True

    def test_remove_last_owner_blocked(self, org_service):
        """Prevent removing the last owner from a project."""
        service, cursor = org_service
        cursor.fetchone.side_effect = [
            (1,),  # Only one owner
            (True,),  # This user is the owner
        ]

        with pytest.raises(ValueError, match="Cannot remove the last owner"):
            service.remove_project_member("proj-abc123", "user-123")

    def test_remove_member_not_found(self, org_service):
        """Return False when membership doesn't exist."""
        service, cursor = org_service
        cursor.fetchone.side_effect = [
            (0,),  # No owners (this user isn't even in the project)
            None,  # User not found
        ]
        cursor.rowcount = 0  # DELETE affected 0 rows

        result = service.remove_project_member("proj-abc123", "nonexistent-user")

        assert result is False


@_xfail_unimplemented
@pytest.mark.unit
class TestListProjectMembers:
    """Tests for list_project_members method."""

    def test_list_members_success(self, org_service, sample_project_membership):
        """Successfully list all project members."""
        service, cursor = org_service
        # Create a second membership tuple
        second_membership = (
            "pmem-def456",  # membership_id
            "proj-abc123",  # project_id
            "user-456",  # user_id
            "viewer",  # role
            datetime.now(timezone.utc),  # created_at
            datetime.now(timezone.utc),  # updated_at
        )
        cursor.fetchall.return_value = [sample_project_membership, second_membership]

        result = service.list_project_members("proj-abc123")

        assert isinstance(result, list)
        assert len(result) == 2

    def test_list_members_empty(self, org_service):
        """Return empty list when no members."""
        service, cursor = org_service
        cursor.fetchall.return_value = []

        result = service.list_project_members("proj-abc123")

        assert result == []


@_xfail_unimplemented
@pytest.mark.unit
class TestUpdateProjectMemberRole:
    """Tests for update_project_member_role method."""

    def test_update_role_success(self, org_service, sample_project_membership):
        """Successfully update a member's role."""
        service, cursor = org_service
        # For non-owner role update: check owner count, check is_owner, update, then select
        cursor.fetchone.side_effect = [
            (2,),  # owner count (more than 1 owner)
            (False,),  # is_owner check (current user is not owner)
            sample_project_membership,  # Return updated membership
        ]
        cursor.rowcount = 1  # UPDATE succeeded

        result = service.update_project_member_role(
            "proj-abc123",
            "user-123",
            ProjectRole.MAINTAINER,
        )

        assert result is not None

    def test_demote_last_owner_blocked(self, org_service):
        """Prevent demoting the last owner."""
        service, cursor = org_service
        cursor.fetchone.side_effect = [
            (1,),  # Only one owner
            (True,),  # This user is the owner
        ]

        with pytest.raises(ValueError, match="Cannot demote the last owner"):
            service.update_project_member_role(
                "proj-abc123",
                "user-123",
                ProjectRole.VIEWER,
            )

    def test_update_role_member_not_found(self, org_service):
        """Return None when membership doesn't exist."""
        service, cursor = org_service
        # For non-owner role: owner count, is_owner check
        cursor.fetchone.side_effect = [
            (0,),  # No owners (project has no members)
            None,  # User not found
            None,  # Final SELECT returns nothing
        ]
        cursor.rowcount = 0  # UPDATE affected 0 rows

        result = service.update_project_member_role(
            "proj-abc123",
            "nonexistent",
            ProjectRole.MAINTAINER,
        )

        assert result is None

# =============================================================================
# Optional Organization Tests (Projects/Agents)
# =============================================================================

@pytest.fixture
def sample_project_no_org() -> tuple:
    """Sample project data (user-owned, no org).

    Column order: project_id, org_id, owner_id, name, slug, description,
    visibility, settings, created_at, updated_at
    """
    return (
        "proj-personal123",                                      # project_id
        None,                                                    # org_id (no org)
        "user-owner456",                                         # owner_id
        "My Project",                                   # name
        "my-personal-project",                                   # slug
        "A project without org",                        # description
        "private",                                               # visibility
        {},                                                      # settings
        datetime(2024, 1, 1, tzinfo=timezone.utc),              # created_at
        datetime(2024, 1, 1, tzinfo=timezone.utc),              # updated_at
    )


@pytest.fixture
def sample_collaborator() -> tuple:
    """Sample project collaborator data.

    Column order: collaborator_id, project_id, user_id, role, invited_by,
    invited_at, accepted_at, created_at, updated_at
    """
    return (
        "collab-abc123",                                         # collaborator_id
        "proj-personal123",                                      # project_id
        "user-collab789",                                        # user_id (collaborator)
        "contributor",                                           # role
        "user-owner456",                                         # invited_by
        datetime(2024, 1, 1, tzinfo=timezone.utc),              # invited_at
        datetime(2024, 1, 2, tzinfo=timezone.utc),              # accepted_at
        datetime(2024, 1, 1, tzinfo=timezone.utc),              # created_at
        datetime(2024, 1, 2, tzinfo=timezone.utc),              # updated_at
    )


@_xfail_unimplemented
@pytest.mark.unit
class TestProjects:
    """Tests for user-owned projects (no org required)."""

    def test_create_project(self, org_service):
        """Create a project without organization."""
        service, cursor = org_service
        cursor.fetchone.return_value = None  # No slug conflict

        result = service.create_project(
            owner_id="user-123",
            name="My Project",
            slug="my-project",
            description="User-owned project",
        )

        assert result is not None
        assert result.owner_id == "user-123"
        assert result.org_id is None  # No org association
        assert result.name == "My Project"
        cursor.execute.assert_called()  # Should insert

    def test_create_project_slug_conflict(self, org_service):
        """Reject project with duplicate slug for same user."""
        service, cursor = org_service
        cursor.fetchone.return_value = ("proj-existing",)  # Slug exists

        with pytest.raises(ValueError, match="already taken"):
            service.create_project(
                owner_id="user-123",
                name="My Project",
                slug="existing-slug",
            )

    def test_list_projects(self, org_service, sample_project_no_org):
        """List all projects for a user."""
        service, cursor = org_service
        cursor.fetchall.return_value = [sample_project_no_org]

        result = service.list_projects(owner_id="user-owner456")

        assert len(result) == 1
        assert result[0].owner_id == "user-owner456"
        assert result[0].name == "My Project"



@_xfail_unimplemented
@pytest.mark.unit
class TestProjectCollaborators:
    """Tests for project collaborator management."""

    def test_add_collaborator_success(self, org_service):
        """Add a collaborator to a user-owned project."""
        service, cursor = org_service
        # First query: verify project is user-owned and owner
        cursor.fetchone.side_effect = [
            ("user-owner456",),  # owner_id from project
            None,  # No existing collaboration
        ]

        result = service.add_collaborator(
            project_id="proj-personal123",
            user_id="user-collab789",
            invited_by="user-owner456",
            role=ProjectRole.CONTRIBUTOR,
        )

        assert result is not None
        assert result.project_id == "proj-personal123"
        assert result.user_id == "user-collab789"
        assert result.invited_by == "user-owner456"

    def test_add_collaborator_not_owner(self, org_service):
        """Reject collaborator addition by non-owner."""
        service, cursor = org_service
        cursor.fetchone.return_value = ("user-other",)  # Different owner

        with pytest.raises(ValueError, match="Only the project owner"):
            service.add_collaborator(
                project_id="proj-personal123",
                user_id="user-collab789",
                invited_by="user-not-owner",
            )

    def test_add_collaborator_not_user_owned_project(self, org_service):
        """Reject collaborator addition to org-owned project."""
        service, cursor = org_service
        cursor.fetchone.return_value = None  # No user-owned project found

        with pytest.raises(ValueError, match="not a user-owned project"):
            service.add_collaborator(
                project_id="proj-org-owned",
                user_id="user-collab789",
                invited_by="user-123",
            )

    def test_add_collaborator_already_exists(self, org_service):
        """Reject duplicate collaborator."""
        service, cursor = org_service
        cursor.fetchone.side_effect = [
            ("user-owner456",),  # owner_id from project
            ("collab-existing",),  # Existing collaboration
        ]

        with pytest.raises(ValueError, match="already a collaborator"):
            service.add_collaborator(
                project_id="proj-personal123",
                user_id="user-collab789",
                invited_by="user-owner456",
            )

    def test_accept_collaboration(self, org_service):
        """Accept a collaboration invitation."""
        service, cursor = org_service
        cursor.rowcount = 1  # One row updated

        result = service.accept_collaboration(
            collaborator_id="collab-abc123",
            user_id="user-collab789",
        )

        assert result is True

    def test_accept_collaboration_wrong_user(self, org_service):
        """Cannot accept collaboration for another user."""
        service, cursor = org_service
        cursor.rowcount = 0  # No rows updated (wrong user)

        result = service.accept_collaboration(
            collaborator_id="collab-abc123",
            user_id="user-wrong",
        )

        assert result is False

    def test_list_project_collaborators(self, org_service, sample_collaborator):
        """List all collaborators on a project."""
        service, cursor = org_service
        cursor.fetchall.return_value = [sample_collaborator]

        result = service.list_project_collaborators(project_id="proj-personal123")

        assert len(result) == 1
        assert result[0].user_id == "user-collab789"
        assert result[0].role == ProjectRole.CONTRIBUTOR

    def test_list_user_collaborations(self, org_service, sample_project_no_org):
        """List projects where user is a collaborator."""
        service, cursor = org_service
        cursor.fetchall.return_value = [sample_project_no_org]

        result = service.list_user_collaborations(user_id="user-collab789")

        assert len(result) == 1
        assert result[0].name == "My Project"

    def test_remove_collaborator_by_owner(self, org_service):
        """Owner can remove collaborator."""
        service, cursor = org_service
        cursor.fetchone.return_value = ("user-owner456",)  # project owner
        cursor.rowcount = 1

        result = service.remove_collaborator(
            project_id="proj-personal123",
            user_id="user-collab789",
            removed_by="user-owner456",
        )

        assert result is True

    def test_remove_collaborator_self_remove(self, org_service):
        """Collaborator can remove themselves."""
        service, cursor = org_service
        cursor.fetchone.return_value = ("user-owner456",)  # different owner
        cursor.rowcount = 1

        result = service.remove_collaborator(
            project_id="proj-personal123",
            user_id="user-collab789",
            removed_by="user-collab789",  # self-removal
        )

        assert result is True

    def test_update_collaborator_role(self, org_service):
        """Update collaborator role."""
        service, cursor = org_service
        cursor.fetchone.return_value = ("user-owner456",)  # project owner
        cursor.rowcount = 1

        result = service.update_collaborator_role(
            project_id="proj-personal123",
            user_id="user-collab789",
            new_role=ProjectRole.MAINTAINER,
            updated_by="user-owner456",
        )

        assert result is True


@_xfail_unimplemented
@pytest.mark.unit
class TestUserSubscriptions:
    """Tests for user-level subscriptions."""

    def test_create_user_subscription(self, org_service):
        """Create a user-level subscription."""
        service, cursor = org_service
        cursor.fetchone.return_value = None  # No existing subscription

        from amprealize.projects.contracts import OrgPlan

        result = service.create_user_subscription(
            user_id="user-123",
            plan=OrgPlan.STARTER,
        )

        assert result is not None
        assert result.user_id == "user-123"
        assert result.org_id is None  # User subscription, not org
        assert result.plan == OrgPlan.STARTER

    def test_create_user_subscription_already_exists(self, org_service):
        """Reject duplicate user subscription."""
        service, cursor = org_service
        cursor.fetchone.return_value = ("sub-existing",)  # Subscription exists

        from amprealize.projects.contracts import OrgPlan

        with pytest.raises(ValueError, match="already has a subscription"):
            service.create_user_subscription(
                user_id="user-123",
                plan=OrgPlan.STARTER,
            )

    def test_get_user_subscription(self, org_service):
        """Get user's personal subscription."""
        service, cursor = org_service
        cursor.fetchone.return_value = (
            "sub-123",           # subscription_id
            "user-123",          # user_id
            None,                # stripe_subscription_id
            None,                # stripe_customer_id
            "starter",           # plan
            "active",            # status
            None,                # current_period_start
            None,                # current_period_end
            None,                # cancel_at
            datetime(2024, 1, 1, tzinfo=timezone.utc),  # created_at
            datetime(2024, 1, 1, tzinfo=timezone.utc),  # updated_at
        )

        result = service.get_user_subscription(user_id="user-123")

        assert result is not None
        assert result.user_id == "user-123"
        assert result.org_id is None


@_xfail_unimplemented
@pytest.mark.unit
class TestBillingContext:
    """Tests for billing context resolution (org vs user subscription)."""

    def test_resolve_billing_org_context(self, org_service):
        """Org subscription takes precedence when user is in org context."""
        service, cursor = org_service
        # First query: check org membership
        cursor.fetchone.side_effect = [
            ("admin",),  # User is org member
            ("sub-org123", "starter", "active", 500000, 10000),  # Org subscription
        ]

        result = service.resolve_billing_context(
            user_id="user-123",
            org_id="org-456",
        )

        assert result is not None
        assert result.subscription_type == "org"
        assert result.org_id == "org-456"

    def test_resolve_billing_project_determines_org(self, org_service):
        """Org-owned project uses org subscription."""
        service, cursor = org_service
        cursor.fetchone.side_effect = [
            ("org-456", None),  # Project is org-owned
            ("sub-org123", "starter", "active", 500000, 10000),  # Org subscription
        ]

        result = service.resolve_billing_context(
            user_id="user-123",
            project_id="proj-456",
        )

        assert result is not None
        assert result.subscription_type == "org"

    def test_resolve_billing_user_subscription(self, org_service):
        """Personal work uses user subscription."""
        service, cursor = org_service
        cursor.fetchone.side_effect = [
            ("sub-user123", "starter", "active"),  # User subscription
            (5000,),  # Tokens used
        ]

        result = service.resolve_billing_context(user_id="user-123")

        assert result is not None
        assert result.subscription_type == "user"
        assert result.org_id is None

    def test_resolve_billing_no_subscription(self, org_service):
        """Return None when no subscription found."""
        service, cursor = org_service
        cursor.fetchone.return_value = None  # No subscription

        result = service.resolve_billing_context(user_id="user-123")

        assert result is None


@_xfail_unimplemented
@pytest.mark.unit
class TestUserUsageTracking:
    """Tests for user-level usage tracking."""

    def test_record_user_usage_personal(self, org_service):
        """Record usage for personal work (no org)."""
        service, cursor = org_service

        result = service.record_user_usage(
            user_id="user-123",
            metric_name="tokens",
            quantity=1000,
        )

        assert result is not None
        assert result.user_id == "user-123"
        assert result.org_id is None  # Personal usage
        assert result.quantity == 1000

    def test_record_user_usage_in_org(self, org_service):
        """Record usage within org context."""
        service, cursor = org_service

        result = service.record_user_usage(
            user_id="user-123",
            metric_name="tokens",
            quantity=1000,
            org_id="org-456",
        )

        assert result is not None
        assert result.user_id == "user-123"
        assert result.org_id == "org-456"  # Billed to org

    def test_get_user_usage_summary(self, org_service):
        """Get usage summary for user's personal work."""
        service, cursor = org_service
        cursor.fetchone.return_value = (5000,)  # Total usage

        result = service.get_user_usage_summary(
            user_id="user-123",
            metric_name="tokens",
            start_date=datetime(2024, 1, 1),
        )

        assert result == 5000

    def test_get_user_usage_including_org(self, org_service):
        """Get total usage including org context."""
        service, cursor = org_service
        cursor.fetchone.return_value = (15000,)  # Total including org

        result = service.get_user_usage_summary(
            user_id="user-123",
            metric_name="tokens",
            start_date=datetime(2024, 1, 1),
            include_org_usage=True,
        )

        assert result == 15000


# =============================================================================
# Contract Validation Tests (Pydantic model validation)
# =============================================================================

@pytest.mark.unit
class TestContractValidation:
    """Tests for unified project contract validation (owner_id required, org_id optional)."""

    def test_project_requires_owner_id(self):
        """Project must always have owner_id."""
        from amprealize.projects.contracts import Project

        with pytest.raises(ValidationError):
            Project(
                name="Test",
                slug="test",
                # Missing owner_id
            )

    def test_project_allows_both_org_and_owner(self):
        """Project can have both org_id and owner_id (org project with an owner)."""
        from amprealize.projects.contracts import Project

        project = Project(
            name="Test",
            slug="test",
            org_id="org-123",
            owner_id="user-456",
        )

        assert project.org_id == "org-123"
        assert project.owner_id == "user-456"

    def test_project_valid_org_owned(self):
        """Valid org-owned project (still needs owner_id)."""
        from amprealize.projects.contracts import Project

        project = Project(
            name="Test",
            slug="test",
            org_id="org-123",
            owner_id="user-456",
        )

        assert project.org_id == "org-123"
        assert project.owner_id == "user-456"

    def test_project_valid_user_owned(self):
        """Valid user-owned project (no org)."""
        from amprealize.projects.contracts import Project

        project = Project(
            name="Test",
            slug="test",
            owner_id="user-123",
        )

        assert project.org_id is None
        assert project.owner_id == "user-123"

    def test_agent_requires_owner(self):
        """Agent must have owner_id set."""
        from amprealize.projects.contracts import Agent

        with pytest.raises(Exception):
            Agent(name="Test Agent")

    def test_subscription_requires_owner(self):
        """Subscription must have either org_id or user_id."""
        from amprealize.projects.contracts import Subscription

        with pytest.raises(ValueError, match="Must set either org_id or user_id"):
            Subscription()

    def test_usage_record_requires_attribution(self):
        """Usage record must have org_id or user_id."""
        from amprealize.projects.contracts import UsageRecord

        with pytest.raises(ValueError, match="Must set either org_id or user_id"):
            UsageRecord(metric_name="tokens")
