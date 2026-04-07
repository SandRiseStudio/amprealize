"""Unit tests for MCP multi-tenant handlers.

Tests the handler functions for orgs.*, projects.*, orgAgents.*, and billing.* namespaces.
Each handler is tested in isolation with mocked services.

Following behavior_design_test_strategy (Student):
- Unit tests using mocks for service layer
- Tests for happy path, error handling, and edge cases
- 70% coverage target per handler module
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Optional

# Mark entire module as unit tests (no infrastructure required)
pytestmark = pytest.mark.unit

# Import contracts for test data
from amprealize.multi_tenant.contracts import (
    Organization,
    OrgMembership,
    OrgPlan,
    OrgStatus,
    MemberRole,
    Project,
    ProjectVisibility,
    ProjectRole,
    Agent,
    AgentType,
    AgentStatus,
    Invitation,
    InvitationStatus,
)

# Import handlers
from amprealize.mcp.handlers.org_handlers import (
    ORG_HANDLERS,
    handle_create_org,
    handle_get_org,
    handle_list_orgs,
    handle_update_org,
    handle_delete_org,
    handle_add_member,
    handle_remove_member,
    handle_update_member_role,
    handle_get_context,
    handle_list_members,
    handle_invite_member,
    handle_accept_invitation,
    handle_switch_org,
)

from amprealize.mcp.handlers.project_handlers import (
    PROJECT_HANDLERS,
    handle_create_project,
    handle_get_project,
    handle_list_projects,
    handle_update_project,
    handle_delete_project,
    handle_archive_project,
    handle_restore_project,
    handle_get_settings,
    handle_update_settings,
    handle_get_stats,
    handle_get_usage,
)

from amprealize.mcp.handlers.org_agent_handlers import (
    ORG_AGENT_HANDLERS,
    handle_create_agent,
    handle_get_agent,
    handle_list_agents,
    handle_update_agent,
    handle_delete_agent,
    handle_pause_agent,
    handle_resume_agent,
    handle_stop_agent,
    handle_get_status,
    handle_assign_to_project,
    handle_remove_from_project,
)

from amprealize.mcp.handlers.billing_handlers import (
    BILLING_HANDLERS,
    handle_get_subscription,
    handle_get_usage,
    handle_get_limits,
    handle_check_limit,
    handle_get_invoices,
    handle_create_checkout_session,
    handle_create_portal_session,
    handle_cancel_subscription,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_org() -> Organization:
    """Sample organization fixture."""
    return Organization(
        id="org-abc123",
        name="Test Organization",
        slug="test-org",
        plan=OrgPlan.FREE,
        status=OrgStatus.ACTIVE,
        settings={},
        owner_id="user-owner",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_membership() -> OrgMembership:
    """Sample org membership fixture."""
    return OrgMembership(
        id="membership-123",
        org_id="org-abc123",
        user_id="user-123",
        role=MemberRole.MEMBER,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_project() -> Project:
    """Sample project fixture."""
    return Project(
        id="proj-abc123",
        owner_id="user-test123",
        org_id="org-xyz789",
        name="Test Project",
        slug="test-project",
        description="A test project",
        visibility=ProjectVisibility.PRIVATE,
        settings={},
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_agent() -> Agent:
    """Sample agent fixture."""
    return Agent(
        id="agent-abc123",
        owner_id="user-test123",
        org_id="org-xyz789",
        name="Test Agent",
        agent_type=AgentType.SPECIALIST,  # Use agent_type, not type
        status=AgentStatus.ACTIVE,
        config={},
        capabilities=[],
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def mock_org_service():
    """Create mock OrganizationService with correct method names."""
    service = MagicMock()
    # Configure async methods - matching actual OrganizationService API
    service.create_organization = AsyncMock()
    service.get_organization = AsyncMock()
    service.list_user_organizations = AsyncMock()
    service.update_organization = AsyncMock()
    service.delete_organization = AsyncMock()
    service.add_member = AsyncMock()
    service.remove_member = AsyncMock()
    service.update_member_role = AsyncMock()
    service.list_members = AsyncMock()
    service.create_invitation = AsyncMock()
    service.accept_invitation = AsyncMock()
    service.get_membership = AsyncMock()
    service.set_user_current_org = AsyncMock()
    service.get_user_current_org = AsyncMock()
    return service


@pytest.fixture
def mock_project_service():
    """Create mock ProjectService (via OrganizationService)."""
    service = MagicMock()
    service.create_project = AsyncMock()
    service.get_project = AsyncMock()
    service.list_projects = AsyncMock()
    service.update_project = AsyncMock()
    service.delete_project = AsyncMock()
    service.archive_project = AsyncMock()
    service.restore_project = AsyncMock()
    service.get_project_settings = AsyncMock()
    service.update_project_settings = AsyncMock()
    service.get_project_stats = AsyncMock()
    service.get_project_usage = AsyncMock()
    return service


@pytest.fixture
def mock_agent_service():
    """Create mock AgentService."""
    service = MagicMock()
    service.create_agent = AsyncMock()
    service.get_agent = AsyncMock()
    service.list_agents = AsyncMock()
    service.update_agent = AsyncMock()
    service.delete_agent = AsyncMock()
    service.update_agent_status = AsyncMock()
    service.get_agent_status = AsyncMock()
    service.assign_agent_to_project = AsyncMock()
    service.remove_agent_from_project = AsyncMock()
    return service


@pytest.fixture
def mock_billing_service():
    """Create mock BillingService."""
    service = MagicMock()
    service.get_subscription = AsyncMock()
    service.get_usage = AsyncMock()
    service.get_limits = AsyncMock()
    service.check_limit = AsyncMock()
    service.get_invoices = AsyncMock()
    service.create_checkout_session = AsyncMock()
    service.create_portal_session = AsyncMock()
    service.cancel_subscription = AsyncMock()
    return service


# =============================================================================
# Test: Handler Registry Completeness
# =============================================================================


class TestHandlerRegistries:
    """Verify all handler registries are complete."""

    def test_org_handlers_registry(self):
        """Test ORG_HANDLERS contains expected tools."""
        expected_tools = [
            "orgs.create",
            "orgs.get",
            "orgs.list",
            "orgs.update",
            "orgs.delete",
            "orgs.addMember",
            "orgs.removeMember",
            "orgs.updateMemberRole",
            "orgs.getContext",
            "orgs.members",
            "orgs.invite",
            "orgs.acceptInvitation",
            "orgs.switch",
        ]
        for tool in expected_tools:
            assert tool in ORG_HANDLERS, f"Missing handler for {tool}"
        assert len(ORG_HANDLERS) == 13

    def test_project_handlers_registry(self):
        """Test PROJECT_HANDLERS contains expected tools."""
        expected_tools = [
            "projects.create",
            "projects.get",
            "projects.list",
            "projects.update",
            "projects.delete",
            "projects.archive",
            "projects.restore",
            "projects.getSettings",
            "projects.updateSettings",
            "projects.getStats",
            "projects.getUsage",
        ]
        for tool in expected_tools:
            assert tool in PROJECT_HANDLERS, f"Missing handler for {tool}"
        assert len(PROJECT_HANDLERS) == 11

    def test_org_agent_handlers_registry(self):
        """Test ORG_AGENT_HANDLERS contains expected tools."""
        expected_tools = [
            "orgAgents.create",
            "orgAgents.get",
            "orgAgents.list",
            "orgAgents.update",
            "orgAgents.delete",
            "orgAgents.pause",
            "orgAgents.resume",
            "orgAgents.stop",
            "orgAgents.getStatus",
            "orgAgents.assignToProject",
            "orgAgents.removeFromProject",
        ]
        for tool in expected_tools:
            assert tool in ORG_AGENT_HANDLERS, f"Missing handler for {tool}"
        assert len(ORG_AGENT_HANDLERS) == 11

    def test_billing_handlers_registry(self):
        """Test BILLING_HANDLERS contains expected tools."""
        expected_tools = [
            "billing.getSubscription",
            "billing.getUsage",
            "billing.getLimits",
            "billing.checkLimit",
            "billing.getInvoices",
            "billing.createCheckoutSession",
            "billing.createPortalSession",
            "billing.cancelSubscription",
        ]
        for tool in expected_tools:
            assert tool in BILLING_HANDLERS, f"Missing handler for {tool}"
        assert len(BILLING_HANDLERS) == 8


# =============================================================================
# Test: Organization Handlers
# =============================================================================


class TestOrgHandlers:
    """Tests for orgs.* namespace handlers."""

    @pytest.mark.asyncio
    async def test_create_org_success(self, mock_org_service, sample_org):
        """Test successful organization creation."""
        mock_org_service.create_organization.return_value = sample_org

        result = await handle_create_org(
            mock_org_service,
            {
                "user_id": "user-123",
                "name": "Test Organization",
            }
        )

        assert result["success"] is True
        assert result["organization"]["id"] == "org-abc123"
        assert result["organization"]["name"] == "Test Organization"
        mock_org_service.create_organization.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_org_success(self, mock_org_service, sample_org, sample_membership):
        """Test successful organization retrieval."""
        mock_org_service.get_membership.return_value = sample_membership
        mock_org_service.get_organization.return_value = sample_org

        result = await handle_get_org(
            mock_org_service,
            {
                "user_id": "user-123",
                "org_id": "org-abc123",
            }
        )

        assert result["success"] is True
        assert result["organization"]["id"] == "org-abc123"

    @pytest.mark.asyncio
    async def test_get_org_not_found(self, mock_org_service):
        """Test organization not found (no membership)."""
        mock_org_service.get_membership.return_value = None

        result = await handle_get_org(
            mock_org_service,
            {
                "user_id": "user-123",
                "org_id": "org-nonexistent",
            }
        )

        assert result["success"] is False
        assert "access denied" in result["error"].lower() or "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_list_orgs_success(self, mock_org_service, sample_org):
        """Test listing user organizations."""
        mock_org_service.list_user_organizations.return_value = [sample_org]

        result = await handle_list_orgs(
            mock_org_service,
            {
                "user_id": "user-123",
            }
        )

        assert result["success"] is True
        assert len(result["organizations"]) == 1
        assert result["organizations"][0]["id"] == "org-abc123"

    @pytest.mark.asyncio
    async def test_update_org_success(self, mock_org_service, sample_org, sample_membership):
        """Test successful organization update."""
        admin_membership = OrgMembership(
            id=sample_membership.id,
            org_id=sample_membership.org_id,
            user_id=sample_membership.user_id,
            role=MemberRole.ADMIN,
            created_at=sample_membership.created_at,
            updated_at=sample_membership.updated_at,
        )
        mock_org_service.get_membership.return_value = admin_membership

        updated_org = Organization(
            id=sample_org.id,
            name="Updated Organization",
            slug=sample_org.slug,
            plan=sample_org.plan,
            status=sample_org.status,
            settings=sample_org.settings,
            created_at=sample_org.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        mock_org_service.update_organization.return_value = updated_org

        result = await handle_update_org(
            mock_org_service,
            {
                "user_id": "user-123",
                "org_id": "org-abc123",
                "name": "Updated Organization",
            }
        )

        assert result["success"] is True
        assert result["organization"]["name"] == "Updated Organization"

    @pytest.mark.asyncio
    async def test_delete_org_success(self, mock_org_service, sample_membership):
        """Test successful organization deletion."""
        owner_membership = OrgMembership(
            id=sample_membership.id,
            org_id=sample_membership.org_id,
            user_id=sample_membership.user_id,
            role=MemberRole.OWNER,
            created_at=sample_membership.created_at,
            updated_at=sample_membership.updated_at,
        )
        mock_org_service.get_membership.return_value = owner_membership
        mock_org_service.delete_organization.return_value = True

        result = await handle_delete_org(
            mock_org_service,
            {
                "user_id": "user-123",
                "org_id": "org-abc123",
            }
        )

        assert result["success"] is True
        assert "deleted" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_add_member_success(self, mock_org_service, sample_membership):
        """Test adding member to organization."""
        admin_membership = OrgMembership(
            id="admin-membership-123",
            org_id=sample_membership.org_id,
            user_id="user-admin",
            role=MemberRole.ADMIN,
            created_at=sample_membership.created_at,
            updated_at=sample_membership.updated_at,
        )
        mock_org_service.get_membership.return_value = admin_membership
        mock_org_service.add_member.return_value = sample_membership

        result = await handle_add_member(
            mock_org_service,
            {
                "user_id": "user-admin",
                "org_id": "org-abc123",
                "target_user_id": "user-123",
                "role": "member",
            }
        )

        assert result["success"] is True
        assert result["membership"]["user_id"] == "user-123"

    @pytest.mark.asyncio
    async def test_remove_member_success(self, mock_org_service, sample_membership):
        """Test removing member from organization."""
        admin_membership = OrgMembership(
            id="admin-membership-123",
            org_id=sample_membership.org_id,
            user_id="user-admin",
            role=MemberRole.ADMIN,
            created_at=sample_membership.created_at,
            updated_at=sample_membership.updated_at,
        )
        target_membership = OrgMembership(
            id="target-membership-123",
            org_id=sample_membership.org_id,
            user_id="user-123",
            role=MemberRole.MEMBER,
            created_at=sample_membership.created_at,
            updated_at=sample_membership.updated_at,
        )
        # First call returns admin membership, second call returns target membership
        mock_org_service.get_membership.side_effect = [admin_membership, target_membership]
        mock_org_service.remove_member.return_value = True

        result = await handle_remove_member(
            mock_org_service,
            {
                "user_id": "user-admin",
                "org_id": "org-abc123",
                "target_user_id": "user-123",
            }
        )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_update_member_role_success(self, mock_org_service, sample_membership):
        """Test updating member role."""
        owner_membership = OrgMembership(
            id="owner-membership-123",
            org_id=sample_membership.org_id,
            user_id="user-owner",
            role=MemberRole.OWNER,
            created_at=sample_membership.created_at,
            updated_at=sample_membership.updated_at,
        )
        mock_org_service.get_membership.return_value = owner_membership

        updated_membership = OrgMembership(
            id=sample_membership.id,
            org_id=sample_membership.org_id,
            user_id=sample_membership.user_id,
            role=MemberRole.ADMIN,
            created_at=sample_membership.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        mock_org_service.update_member_role.return_value = updated_membership

        result = await handle_update_member_role(
            mock_org_service,
            {
                "user_id": "user-owner",
                "org_id": "org-abc123",
                "target_user_id": "user-123",
                "role": "admin",
            }
        )

        assert result["success"] is True
        assert result["membership"]["role"] == "admin"

    @pytest.mark.asyncio
    async def test_get_context_success(self, mock_org_service, sample_org, sample_membership):
        """Test getting current org/project context."""
        mock_org_service.get_membership.return_value = sample_membership
        mock_org_service.get_organization.return_value = sample_org

        result = await handle_get_context(
            mock_org_service,
            {
                "user_id": "user-123",
                "org_id": "org-abc123",
            }
        )

        assert result["success"] is True
        assert result["context"]["org_id"] == "org-abc123"


# =============================================================================
# Test: Project Handlers
# =============================================================================


class TestProjectHandlers:
    """Tests for projects.* namespace handlers."""

    @pytest.mark.asyncio
    async def test_create_project_success(self, mock_project_service, mock_org_service, sample_project, sample_membership):
        """Test successful project creation."""
        # User must be admin to create project
        admin_membership = OrgMembership(
            id=sample_membership.id,
            org_id=sample_membership.org_id,
            user_id=sample_membership.user_id,
            role=MemberRole.ADMIN,
            created_at=sample_membership.created_at,
            updated_at=sample_membership.updated_at,
        )
        mock_org_service.get_membership.return_value = admin_membership
        mock_project_service.create_project.return_value = sample_project

        result = await handle_create_project(
            mock_project_service,
            mock_org_service,
            {
                "user_id": "user-123",
                "org_id": "org-xyz789",
                "name": "Test Project",
                "description": "A test project",
            }
        )

        assert result["success"] is True
        assert result["project"]["id"] == "proj-abc123"
        assert result["project"]["name"] == "Test Project"

    @pytest.mark.asyncio
    async def test_get_project_success(self, mock_project_service, mock_org_service, sample_project, sample_membership):
        """Test successful project retrieval."""
        mock_project_service.get_project.return_value = sample_project
        mock_org_service.get_membership.return_value = sample_membership

        result = await handle_get_project(
            mock_project_service,
            mock_org_service,
            {
                "user_id": "user-123",
                "project_id": "proj-abc123",
            }
        )

        assert result["success"] is True
        assert result["project"]["id"] == "proj-abc123"

    @pytest.mark.asyncio
    async def test_get_project_not_found(self, mock_project_service, mock_org_service):
        """Test project not found."""
        mock_project_service.get_project.return_value = None

        result = await handle_get_project(
            mock_project_service,
            mock_org_service,
            {
                "user_id": "user-123",
                "project_id": "proj-nonexistent",
            }
        )

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_list_projects_success(self, mock_project_service, mock_org_service, sample_project, sample_membership):
        """Test listing projects."""
        mock_org_service.get_membership.return_value = sample_membership
        mock_project_service.list_projects.return_value = [sample_project]

        result = await handle_list_projects(
            mock_project_service,
            mock_org_service,
            {
                "user_id": "user-123",
                "org_id": "org-xyz789",
            }
        )

        assert result["success"] is True
        assert len(result["projects"]) == 1

    @pytest.mark.asyncio
    async def test_update_project_success(self, mock_project_service, mock_org_service, sample_project, sample_membership):
        """Test successful project update."""
        admin_membership = OrgMembership(
            id=sample_membership.id,
            org_id=sample_membership.org_id,
            user_id=sample_membership.user_id,
            role=MemberRole.ADMIN,
            created_at=sample_membership.created_at,
            updated_at=sample_membership.updated_at,
        )
        mock_project_service.get_project.return_value = sample_project
        mock_org_service.get_membership.return_value = admin_membership

        updated_project = Project(
            id=sample_project.id,
            owner_id=sample_project.owner_id,
            org_id=sample_project.org_id,
            name="Updated Project",
            slug=sample_project.slug,
            description=sample_project.description,
            visibility=sample_project.visibility,
            settings=sample_project.settings,
            created_at=sample_project.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        mock_project_service.update_project.return_value = updated_project

        result = await handle_update_project(
            mock_project_service,
            mock_org_service,
            {
                "user_id": "user-123",
                "project_id": "proj-abc123",
                "name": "Updated Project",
            }
        )

        assert result["success"] is True
        assert result["project"]["name"] == "Updated Project"

    @pytest.mark.asyncio
    async def test_delete_project_success(self, mock_project_service, mock_org_service, sample_project, sample_membership):
        """Test successful project deletion."""
        admin_membership = OrgMembership(
            id=sample_membership.id,
            org_id=sample_membership.org_id,
            user_id=sample_membership.user_id,
            role=MemberRole.ADMIN,
            created_at=sample_membership.created_at,
            updated_at=sample_membership.updated_at,
        )
        mock_project_service.get_project.return_value = sample_project
        mock_org_service.get_membership.return_value = admin_membership
        mock_project_service.delete_project.return_value = True

        result = await handle_delete_project(
            mock_project_service,
            mock_org_service,
            {
                "user_id": "user-123",
                "project_id": "proj-abc123",
            }
        )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_archive_project_success(self, mock_project_service, mock_org_service, sample_project, sample_membership):
        """Test archiving a project."""
        admin_membership = OrgMembership(
            id=sample_membership.id,
            org_id=sample_membership.org_id,
            user_id=sample_membership.user_id,
            role=MemberRole.ADMIN,
            created_at=sample_membership.created_at,
            updated_at=sample_membership.updated_at,
        )
        mock_project_service.get_project.return_value = sample_project
        mock_org_service.get_membership.return_value = admin_membership
        # Handler calls update_project with settings={"archived": True, ...}
        mock_project_service.update_project.return_value = sample_project

        result = await handle_archive_project(
            mock_project_service,
            mock_org_service,
            {
                "user_id": "user-123",
                "project_id": "proj-abc123",
            }
        )

        assert result["success"] is True


# =============================================================================
# Test: Organization Agent Handlers
# =============================================================================


class TestOrgAgentHandlers:
    """Tests for orgAgents.* namespace handlers."""

    @pytest.mark.asyncio
    async def test_create_agent_success(self, mock_agent_service, sample_agent):
        """Test successful agent creation."""
        mock_agent_service.create_agent.return_value = sample_agent

        result = await handle_create_agent(
            mock_agent_service,
            {
                "user_id": "user-123",
                "org_id": "org-xyz789",
                "name": "Test Agent",
                "type": "orchestrator",
            }
        )

        assert result["success"] is True
        assert result["agent"]["id"] == "agent-abc123"
        assert result["agent"]["name"] == "Test Agent"

    @pytest.mark.asyncio
    async def test_get_agent_success(self, mock_agent_service, sample_agent):
        """Test successful agent retrieval."""
        mock_agent_service.get_agent.return_value = sample_agent

        result = await handle_get_agent(
            mock_agent_service,
            {
                "user_id": "user-123",
                "agent_id": "agent-abc123",
            }
        )

        assert result["success"] is True
        assert result["agent"]["id"] == "agent-abc123"

    @pytest.mark.asyncio
    async def test_get_agent_not_found(self, mock_agent_service):
        """Test agent not found."""
        mock_agent_service.get_agent.return_value = None

        result = await handle_get_agent(
            mock_agent_service,
            {
                "user_id": "user-123",
                "agent_id": "agent-nonexistent",
            }
        )

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_list_agents_success(self, mock_agent_service, sample_agent):
        """Test listing agents."""
        mock_agent_service.list_agents.return_value = [sample_agent]

        result = await handle_list_agents(
            mock_agent_service,
            {
                "user_id": "user-123",
                "org_id": "org-xyz789",
            }
        )

        assert result["success"] is True
        assert len(result["agents"]) == 1

    @pytest.mark.asyncio
    async def test_pause_agent_success(self, mock_agent_service, sample_agent):
        """Test pausing an agent."""
        paused_agent = Agent(
            id=sample_agent.id,
            owner_id=sample_agent.owner_id,
            org_id=sample_agent.org_id,
            name=sample_agent.name,
            agent_type=sample_agent.agent_type,
            status=AgentStatus.PAUSED,
            config=sample_agent.config,
            capabilities=sample_agent.capabilities,
            created_at=sample_agent.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        mock_agent_service.update_agent_status.return_value = paused_agent

        result = await handle_pause_agent(
            mock_agent_service,
            {
                "user_id": "user-123",
                "agent_id": "agent-abc123",
            }
        )

        assert result["success"] is True
        assert result["agent"]["status"] == "paused"

    @pytest.mark.asyncio
    async def test_resume_agent_success(self, mock_agent_service, sample_agent):
        """Test resuming an agent."""
        mock_agent_service.update_agent_status.return_value = sample_agent

        result = await handle_resume_agent(
            mock_agent_service,
            {
                "user_id": "user-123",
                "agent_id": "agent-abc123",
            }
        )

        assert result["success"] is True
        assert result["agent"]["status"] == "active"

    @pytest.mark.asyncio
    async def test_stop_agent_success(self, mock_agent_service, sample_agent):
        """Test stopping an agent."""
        stopped_agent = Agent(
            id=sample_agent.id,
            owner_id=sample_agent.owner_id,
            org_id=sample_agent.org_id,
            name=sample_agent.name,
            agent_type=sample_agent.agent_type,
            status=AgentStatus.DISABLED,
            config=sample_agent.config,
            capabilities=sample_agent.capabilities,
            created_at=sample_agent.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        mock_agent_service.update_agent_status.return_value = stopped_agent

        result = await handle_stop_agent(
            mock_agent_service,
            {
                "user_id": "user-123",
                "agent_id": "agent-abc123",
                "reason": "Test stop",
            }
        )

        assert result["success"] is True
        assert result["agent"]["status"] == "disabled"

    @pytest.mark.asyncio
    async def test_assign_to_project_success(self, mock_agent_service):
        """Test assigning agent to project."""
        mock_agent_service.assign_agent_to_project.return_value = True

        result = await handle_assign_to_project(
            mock_agent_service,
            {
                "user_id": "user-123",
                "agent_id": "agent-abc123",
                "project_id": "proj-xyz789",
            }
        )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_remove_from_project_success(self, mock_agent_service):
        """Test removing agent from project."""
        mock_agent_service.remove_agent_from_project.return_value = True

        result = await handle_remove_from_project(
            mock_agent_service,
            {
                "user_id": "user-123",
                "agent_id": "agent-abc123",
                "project_id": "proj-xyz789",
            }
        )

        assert result["success"] is True


# =============================================================================
# Test: Billing Handlers
# =============================================================================


class TestBillingHandlers:
    """Tests for billing.* namespace handlers."""

    @pytest.mark.asyncio
    async def test_get_subscription_success(self, mock_billing_service):
        """Test getting subscription."""
        mock_billing_service.get_subscription.return_value = {
            "id": "sub-123",
            "plan": "pro",
            "status": "active",
            "current_period_end": "2024-12-31T23:59:59Z",
        }

        result = await handle_get_subscription(
            mock_billing_service,
            {
                "user_id": "user-123",
                "org_id": "org-abc123",
            }
        )

        assert result["success"] is True
        assert result["subscription"]["plan"] == "pro"

    @pytest.mark.asyncio
    async def test_get_subscription_none(self, mock_billing_service):
        """Test getting subscription when none exists."""
        mock_billing_service.get_subscription.return_value = None

        result = await handle_get_subscription(
            mock_billing_service,
            {
                "user_id": "user-123",
                "org_id": "org-abc123",
            }
        )

        assert result["success"] is True
        assert result["subscription"] is None

    @pytest.mark.asyncio
    async def test_get_usage_success(self, mock_billing_service):
        """Test getting usage metrics."""
        mock_billing_service.get_usage.return_value = {
            "api_calls": 1500,
            "storage_mb": 250,
            "agents": 5,
        }

        result = await handle_get_usage(
            mock_billing_service,
            {
                "user_id": "user-123",
                "org_id": "org-abc123",
            }
        )

        assert result["success"] is True
        assert result["usage"]["api_calls"] == 1500

    @pytest.mark.asyncio
    async def test_get_limits_success(self, mock_billing_service):
        """Test getting plan limits."""
        mock_billing_service.get_limits.return_value = {
            "api_calls_limit": 10000,
            "storage_mb_limit": 5000,
            "agents_limit": 20,
        }

        result = await handle_get_limits(
            mock_billing_service,
            {
                "user_id": "user-123",
                "org_id": "org-abc123",
            }
        )

        assert result["success"] is True
        assert result["limits"]["agents_limit"] == 20

    @pytest.mark.asyncio
    async def test_check_limit_allowed(self, mock_billing_service):
        """Test checking limit when allowed."""
        mock_billing_service.check_limit.return_value = {
            "allowed": True,
            "current_usage": 5,
            "limit": 20,
            "remaining": 15,
        }

        result = await handle_check_limit(
            mock_billing_service,
            {
                "user_id": "user-123",
                "org_id": "org-abc123",
                "limit_type": "agents",
                "requested_amount": 1,
            }
        )

        assert result["success"] is True
        assert result["allowed"] is True
        assert result["remaining"] == 15

    @pytest.mark.asyncio
    async def test_check_limit_exceeded(self, mock_billing_service):
        """Test checking limit when exceeded."""
        mock_billing_service.check_limit.return_value = {
            "allowed": False,
            "current_usage": 20,
            "limit": 20,
            "remaining": 0,
            "message": "Agent limit reached",
        }

        result = await handle_check_limit(
            mock_billing_service,
            {
                "user_id": "user-123",
                "org_id": "org-abc123",
                "limit_type": "agents",
                "requested_amount": 1,
            }
        )

        assert result["success"] is True
        assert result["allowed"] is False
        assert result["remaining"] == 0

    @pytest.mark.asyncio
    async def test_get_invoices_success(self, mock_billing_service):
        """Test getting invoices."""
        mock_billing_service.get_invoices.return_value = [
            {"id": "inv-1", "amount": 99, "status": "paid"},
            {"id": "inv-2", "amount": 99, "status": "paid"},
        ]

        result = await handle_get_invoices(
            mock_billing_service,
            {
                "user_id": "user-123",
                "org_id": "org-abc123",
            }
        )

        assert result["success"] is True
        assert len(result["invoices"]) == 2

    @pytest.mark.asyncio
    async def test_create_checkout_session_success(self, mock_billing_service):
        """Test creating checkout session."""
        mock_billing_service.create_checkout_session.return_value = {
            "session_id": "cs_123",
            "url": "https://checkout.stripe.com/...",
        }

        result = await handle_create_checkout_session(
            mock_billing_service,
            {
                "user_id": "user-123",
                "org_id": "org-abc123",
                "plan": "pro",
                "success_url": "https://app.example.com/success",
                "cancel_url": "https://app.example.com/cancel",
            }
        )

        assert result["success"] is True
        assert result["session_id"] == "cs_123"
        assert "url" in result

    @pytest.mark.asyncio
    async def test_create_portal_session_success(self, mock_billing_service):
        """Test creating billing portal session."""
        mock_billing_service.create_portal_session.return_value = {
            "url": "https://billing.stripe.com/...",
        }

        result = await handle_create_portal_session(
            mock_billing_service,
            {
                "user_id": "user-123",
                "org_id": "org-abc123",
                "return_url": "https://app.example.com/settings",
            }
        )

        assert result["success"] is True
        assert "url" in result

    @pytest.mark.asyncio
    async def test_cancel_subscription_success(self, mock_billing_service):
        """Test canceling subscription."""
        mock_billing_service.cancel_subscription.return_value = {
            "cancel_at": "2024-12-31T23:59:59Z",
        }

        result = await handle_cancel_subscription(
            mock_billing_service,
            {
                "user_id": "user-123",
                "org_id": "org-abc123",
                "at_period_end": True,
            }
        )

        assert result["success"] is True
        assert "cancel_at" in result


# =============================================================================
# Test: Error Handling
# =============================================================================


class TestErrorHandling:
    """Test error handling across handlers."""

    @pytest.mark.asyncio
    async def test_org_handler_service_exception(self, mock_org_service):
        """Test org handler handles service exceptions."""
        mock_org_service.create_org.side_effect = Exception("Database error")

        with pytest.raises(Exception):
            await handle_create_org(
                mock_org_service,
                {
                    "user_id": "user-123",
                    "name": "Test Org",
                }
            )

    @pytest.mark.asyncio
    async def test_project_handler_service_exception(self, mock_project_service):
        """Test project handler handles service exceptions."""
        mock_project_service.create_project.side_effect = Exception("Database error")

        with pytest.raises(Exception):
            await handle_create_project(
                mock_project_service,
                {
                    "user_id": "user-123",
                    "org_id": "org-xyz789",
                    "name": "Test Project",
                }
            )

    @pytest.mark.asyncio
    async def test_agent_handler_service_exception(self, mock_agent_service):
        """Test agent handler handles service exceptions."""
        mock_agent_service.create_agent.side_effect = Exception("Database error")

        with pytest.raises(Exception):
            await handle_create_agent(
                mock_agent_service,
                {
                    "user_id": "user-123",
                    "org_id": "org-xyz789",
                    "name": "Test Agent",
                }
            )

    @pytest.mark.asyncio
    async def test_billing_handler_service_exception(self, mock_billing_service):
        """Test billing handler handles service exceptions."""
        mock_billing_service.get_subscription.side_effect = Exception("Stripe error")

        with pytest.raises(Exception):
            await handle_get_subscription(
                mock_billing_service,
                {
                    "user_id": "user-123",
                    "org_id": "org-abc123",
                }
            )
