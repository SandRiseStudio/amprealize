"""Tenant isolation and RBAC for Amprealize.

Provides:
- TenantContext: Request-scoped tenant isolation via PostgreSQL RLS
- TenantMiddleware: FastAPI middleware for automatic tenant context
- PermissionService: RBAC permission checking and enforcement
- Permission enums for org-level and project-level access control
"""

from .context import TenantContext, TenantMiddleware, get_current_org_id, require_org_context
from .permissions import (
    AsyncPermissionService,
    NotAMember,
    OrgPermission,
    PermissionDenied,
    PermissionService,
    ProjectPermission,
    require_org_permission_decorator,
    require_project_permission_decorator,
)

__all__ = [
    "AsyncPermissionService",
    "TenantContext",
    "TenantMiddleware",
    "NotAMember",
    "OrgPermission",
    "PermissionDenied",
    "PermissionService",
    "ProjectPermission",
    "get_current_org_id",
    "require_org_context",
    "require_org_permission_decorator",
    "require_project_permission_decorator",
]
