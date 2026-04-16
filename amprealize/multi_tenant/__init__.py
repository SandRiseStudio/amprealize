"""Backward-compatibility shim for amprealize.multi_tenant.

Core OSS functionality has been relocated to:
- amprealize.boards   — Board and WorkItem contracts
- amprealize.tenant   — TenantContext, permissions, RBAC
- amprealize.projects  — Project/Agent contracts, OSSProjectService, ExecutionMode

Enterprise-only modules (OrganizationService, InvitationService,
SettingsService, settings_api, api) remain here as upgrade hooks.

Prefer importing from the new packages directly.
"""

# Re-export from new canonical locations (OSS)
from amprealize.tenant.context import TenantContext, TenantMiddleware, get_current_org_id, require_org_context
from amprealize.tenant.permissions import (
    PermissionService,
    OrgPermission,
    ProjectPermission,
    PermissionDenied,
    NotAMember,
    require_org_permission_decorator,
    require_project_permission_decorator,
)

# Enterprise upgrade hooks — stubs that return None/False in OSS
from .organization_service import OrganizationService
from .invitation_service import InvitationService
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
from .api import create_org_routes, ORG_ROUTES_AVAILABLE
from .settings_api import create_settings_routes, SETTINGS_ROUTES_AVAILABLE

__all__ = [
    # Re-exported from amprealize.tenant (OSS)
    "TenantContext",
    "TenantMiddleware",
    "get_current_org_id",
    "require_org_context",
    "PermissionService",
    "OrgPermission",
    "ProjectPermission",
    "PermissionDenied",
    "NotAMember",
    "require_org_permission_decorator",
    "require_project_permission_decorator",
    # Enterprise upgrade hooks
    "OrganizationService",
    "InvitationService",
    "SettingsService",
    "OrgSettings",
    "ProjectSettings",
    "BrandingSettings",
    "NotificationSettings",
    "SecuritySettings",
    "IntegrationSettings",
    "WorkflowSettings",
    "AgentSettings",
    "ORG_ROUTES_AVAILABLE",
    "SETTINGS_ROUTES_AVAILABLE",
    "create_org_routes",
    "create_settings_routes",
]
