"""Multi-tenant support for Amprealize.

This package provides:
- TenantContext: Request-scoped tenant isolation via PostgreSQL RLS
- OrganizationService: PostgreSQL-backed org CRUD and membership management
- InvitationService: Invitation management with notification support
- PermissionService: RBAC permission checking and enforcement
- SettingsService: Organization and project settings management
- Pydantic contracts for Organizations, Projects, Members, Agents, and Invitations

Usage:
    from amprealize.multi_tenant import TenantContext, OrganizationService, InvitationService
    from amprealize.multi_tenant.contracts import (
        Organization, CreateOrgRequest,
        Invitation, CreateInvitationRequest,
    )

    # Set tenant context at request start
    async with TenantContext(pool, org_id="org-123"):
        orgs = await org_service.list_organizations(user_id="user-456")

    # Invite a user
    invitation = invite_service.create_invitation(
        org_id="org-123",
        request=CreateInvitationRequest(email="user@example.com"),
        invited_by="user-456",
    )

    # Check permissions
    from amprealize.multi_tenant.permissions import PermissionService, OrgPermission
    if await perm_service.has_org_permission(user_id, org_id, OrgPermission.INVITE_MEMBERS):
        # User can invite members
        pass

    # Manage settings
    from amprealize.multi_tenant.settings import SettingsService
    org_settings = await settings_service.get_org_settings(org_id)
"""

from .context import TenantContext, TenantMiddleware, get_current_org_id, require_org_context
from .organization_service import OrganizationService
from .invitation_service import InvitationService
from .permissions import (
    PermissionService,
    OrgPermission,
    ProjectPermission,
    PermissionDenied,
    NotAMember,
    require_org_permission_decorator,
    require_project_permission_decorator,
)
from .settings import (
    SettingsService,
    OrgSettings,
    ProjectSettings,
    BrandingSettings,
    NotificationSettings,
    SecuritySettings,
    IntegrationSettings,
    WorkflowSettings,
    AgentSettings,
)
from .api import create_org_routes
from .settings_api import create_settings_routes

__all__ = [
    # Context management
    "TenantContext",
    "TenantMiddleware",
    "get_current_org_id",
    "require_org_context",
    # Services
    "OrganizationService",
    "InvitationService",
    "PermissionService",
    "SettingsService",
    # Permissions
    "OrgPermission",
    "ProjectPermission",
    "PermissionDenied",
    "NotAMember",
    "require_org_permission_decorator",
    "require_project_permission_decorator",
    # Settings
    "OrgSettings",
    "ProjectSettings",
    "BrandingSettings",
    "NotificationSettings",
    "SecuritySettings",
    "IntegrationSettings",
    "WorkflowSettings",
    "AgentSettings",
    # API
    "create_org_routes",
    "create_settings_routes",
]
