"""RBAC Permission System for Multi-Tenant Authorization.

This module provides a comprehensive permission system with:
- Permission matrix for org and project level roles
- PermissionService for checking permissions
- Decorators for FastAPI endpoint authorization

Behavior: behavior_lock_down_security_surface

Usage:
    from amprealize.multi_tenant.permissions import (
        Permission,
        OrgPermission,
        ProjectPermission,
        PermissionService,
        require_org_permission,
        require_project_permission,
    )

    # Check permission
    perm_service = PermissionService(pool=pool)
    if perm_service.has_org_permission(user_id, org_id, OrgPermission.INVITE_MEMBERS):
        # User can invite members
        pass

    # Decorator usage
    @app.post("/orgs/{org_id}/members")
    @require_org_permission(OrgPermission.INVITE_MEMBERS)
    async def invite_member(org_id: str, request: Request):
        pass
"""

from __future__ import annotations

import functools
import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, TypeVar, Union

from amprealize.projects.contracts import MemberRole, ProjectRole

if TYPE_CHECKING:
    from amprealize.storage.postgres_pool import PostgresPool

logger = logging.getLogger(__name__)


# =============================================================================
# Permission Enums
# =============================================================================

class OrgPermission(str, Enum):
    """Organization-level permissions.

    Permissions are hierarchical - higher roles inherit all permissions
    from lower roles.
    """
    # View permissions
    VIEW_ORG = "org:view"
    VIEW_MEMBERS = "org:view_members"
    VIEW_PROJECTS = "org:view_projects"
    VIEW_AGENTS = "org:view_agents"
    VIEW_BILLING = "org:view_billing"
    VIEW_SETTINGS = "org:view_settings"
    VIEW_AUDIT_LOG = "org:view_audit_log"

    # Member management
    INVITE_MEMBERS = "org:invite_members"
    REMOVE_MEMBERS = "org:remove_members"
    UPDATE_MEMBER_ROLES = "org:update_member_roles"

    # Project management
    CREATE_PROJECTS = "org:create_projects"
    DELETE_PROJECTS = "org:delete_projects"
    ARCHIVE_PROJECTS = "org:archive_projects"

    # Agent management
    CREATE_AGENTS = "org:create_agents"
    DELETE_AGENTS = "org:delete_agents"
    CONFIGURE_AGENTS = "org:configure_agents"

    # Settings & billing
    UPDATE_SETTINGS = "org:update_settings"
    UPDATE_BRANDING = "org:update_branding"
    MANAGE_BILLING = "org:manage_billing"
    MANAGE_INTEGRATIONS = "org:manage_integrations"

    # Billing (granular)
    VIEW_INVOICES = "org:view_invoices"
    VIEW_USAGE = "org:view_usage"
    MANAGE_SUBSCRIPTIONS = "org:manage_subscriptions"
    MANAGE_PAYMENT_METHODS = "org:manage_payment_methods"

    # Administrative
    DELETE_ORG = "org:delete"
    TRANSFER_OWNERSHIP = "org:transfer_ownership"


class ProjectPermission(str, Enum):
    """Project-level permissions.

    These permissions apply within a specific project context.
    """
    # View permissions
    VIEW_PROJECT = "project:view"
    VIEW_RUNS = "project:view_runs"
    VIEW_BEHAVIORS = "project:view_behaviors"
    VIEW_COMPLIANCE = "project:view_compliance"
    VIEW_SETTINGS = "project:view_settings"

    # Run management
    CREATE_RUNS = "project:create_runs"
    CANCEL_RUNS = "project:cancel_runs"
    DELETE_RUNS = "project:delete_runs"

    # Behavior management
    CREATE_BEHAVIORS = "project:create_behaviors"
    UPDATE_BEHAVIORS = "project:update_behaviors"
    DELETE_BEHAVIORS = "project:delete_behaviors"

    # Compliance
    CREATE_POLICIES = "project:create_policies"
    UPDATE_POLICIES = "project:update_policies"
    APPROVE_VIOLATIONS = "project:approve_violations"

    # Board management (Agile boards, columns, epics, stories, tasks)
    VIEW_BOARDS = "project:view_boards"
    CREATE_BOARDS = "project:create_boards"
    UPDATE_BOARDS = "project:update_boards"
    DELETE_BOARDS = "project:delete_boards"
    MANAGE_COLUMNS = "project:manage_columns"
    CREATE_WORK_ITEMS = "project:create_work_items"  # Epics, Stories, Tasks
    UPDATE_WORK_ITEMS = "project:update_work_items"
    DELETE_WORK_ITEMS = "project:delete_work_items"
    ASSIGN_WORK_ITEMS = "project:assign_work_items"
    MANAGE_SPRINTS = "project:manage_sprints"

    # Member management (for private projects)
    INVITE_MEMBERS = "project:invite_members"
    REMOVE_MEMBERS = "project:remove_members"
    UPDATE_MEMBER_ROLES = "project:update_member_roles"

    # Settings
    UPDATE_SETTINGS = "project:update_settings"

    # Administrative
    DELETE_PROJECT = "project:delete"
    ARCHIVE_PROJECT = "project:archive"
    TRANSFER_OWNERSHIP = "project:transfer_ownership"


# =============================================================================
# Permission Matrix
# =============================================================================

# Organization role -> permissions mapping
ORG_ROLE_PERMISSIONS: Dict[MemberRole, Set[OrgPermission]] = {
    MemberRole.VIEWER: {
        OrgPermission.VIEW_ORG,
        OrgPermission.VIEW_MEMBERS,
        OrgPermission.VIEW_PROJECTS,
        OrgPermission.VIEW_AGENTS,
    },
    MemberRole.MEMBER: {
        # Inherits viewer permissions +
        OrgPermission.VIEW_ORG,
        OrgPermission.VIEW_MEMBERS,
        OrgPermission.VIEW_PROJECTS,
        OrgPermission.VIEW_AGENTS,
        OrgPermission.VIEW_SETTINGS,
        OrgPermission.CREATE_PROJECTS,
    },
    MemberRole.ADMIN: {
        # Inherits member permissions +
        OrgPermission.VIEW_ORG,
        OrgPermission.VIEW_MEMBERS,
        OrgPermission.VIEW_PROJECTS,
        OrgPermission.VIEW_AGENTS,
        OrgPermission.VIEW_BILLING,
        OrgPermission.VIEW_SETTINGS,
        OrgPermission.VIEW_AUDIT_LOG,
        OrgPermission.INVITE_MEMBERS,
        OrgPermission.REMOVE_MEMBERS,
        OrgPermission.UPDATE_MEMBER_ROLES,
        OrgPermission.CREATE_PROJECTS,
        OrgPermission.DELETE_PROJECTS,
        OrgPermission.ARCHIVE_PROJECTS,
        OrgPermission.CREATE_AGENTS,
        OrgPermission.DELETE_AGENTS,
        OrgPermission.CONFIGURE_AGENTS,
        OrgPermission.UPDATE_SETTINGS,
        OrgPermission.UPDATE_BRANDING,
        OrgPermission.MANAGE_INTEGRATIONS,
        OrgPermission.VIEW_INVOICES,
        OrgPermission.VIEW_USAGE,
    },
    MemberRole.OWNER: {
        # All permissions
        OrgPermission.VIEW_ORG,
        OrgPermission.VIEW_MEMBERS,
        OrgPermission.VIEW_PROJECTS,
        OrgPermission.VIEW_AGENTS,
        OrgPermission.VIEW_BILLING,
        OrgPermission.VIEW_SETTINGS,
        OrgPermission.VIEW_AUDIT_LOG,
        OrgPermission.INVITE_MEMBERS,
        OrgPermission.REMOVE_MEMBERS,
        OrgPermission.UPDATE_MEMBER_ROLES,
        OrgPermission.CREATE_PROJECTS,
        OrgPermission.DELETE_PROJECTS,
        OrgPermission.ARCHIVE_PROJECTS,
        OrgPermission.CREATE_AGENTS,
        OrgPermission.DELETE_AGENTS,
        OrgPermission.CONFIGURE_AGENTS,
        OrgPermission.UPDATE_SETTINGS,
        OrgPermission.UPDATE_BRANDING,
        OrgPermission.MANAGE_BILLING,
        OrgPermission.MANAGE_INTEGRATIONS,
        OrgPermission.VIEW_INVOICES,
        OrgPermission.VIEW_USAGE,
        OrgPermission.MANAGE_SUBSCRIPTIONS,
        OrgPermission.MANAGE_PAYMENT_METHODS,
        OrgPermission.DELETE_ORG,
        OrgPermission.TRANSFER_OWNERSHIP,
    },
}

# Project role -> permissions mapping
PROJECT_ROLE_PERMISSIONS: Dict[ProjectRole, Set[ProjectPermission]] = {
    ProjectRole.VIEWER: {
        ProjectPermission.VIEW_PROJECT,
        ProjectPermission.VIEW_RUNS,
        ProjectPermission.VIEW_BEHAVIORS,
        ProjectPermission.VIEW_COMPLIANCE,
        ProjectPermission.VIEW_BOARDS,
    },
    ProjectRole.CONTRIBUTOR: {
        # Inherits viewer permissions +
        ProjectPermission.VIEW_PROJECT,
        ProjectPermission.VIEW_RUNS,
        ProjectPermission.VIEW_BEHAVIORS,
        ProjectPermission.VIEW_COMPLIANCE,
        ProjectPermission.VIEW_SETTINGS,
        ProjectPermission.CREATE_RUNS,
        ProjectPermission.CREATE_BEHAVIORS,
        # Board permissions
        ProjectPermission.VIEW_BOARDS,
        ProjectPermission.CREATE_WORK_ITEMS,
        ProjectPermission.UPDATE_WORK_ITEMS,
        ProjectPermission.ASSIGN_WORK_ITEMS,
    },
    ProjectRole.MAINTAINER: {
        # Inherits contributor permissions +
        ProjectPermission.VIEW_PROJECT,
        ProjectPermission.VIEW_RUNS,
        ProjectPermission.VIEW_BEHAVIORS,
        ProjectPermission.VIEW_COMPLIANCE,
        ProjectPermission.VIEW_SETTINGS,
        ProjectPermission.CREATE_RUNS,
        ProjectPermission.CANCEL_RUNS,
        ProjectPermission.DELETE_RUNS,
        ProjectPermission.CREATE_BEHAVIORS,
        ProjectPermission.UPDATE_BEHAVIORS,
        ProjectPermission.DELETE_BEHAVIORS,
        ProjectPermission.CREATE_POLICIES,
        ProjectPermission.UPDATE_POLICIES,
        ProjectPermission.APPROVE_VIOLATIONS,
        ProjectPermission.INVITE_MEMBERS,
        ProjectPermission.REMOVE_MEMBERS,
        ProjectPermission.UPDATE_SETTINGS,
        # Board permissions
        ProjectPermission.VIEW_BOARDS,
        ProjectPermission.CREATE_BOARDS,
        ProjectPermission.UPDATE_BOARDS,
        ProjectPermission.MANAGE_COLUMNS,
        ProjectPermission.CREATE_WORK_ITEMS,
        ProjectPermission.UPDATE_WORK_ITEMS,
        ProjectPermission.DELETE_WORK_ITEMS,
        ProjectPermission.ASSIGN_WORK_ITEMS,
        ProjectPermission.MANAGE_SPRINTS,
    },
    ProjectRole.OWNER: {
        # All permissions
        ProjectPermission.VIEW_PROJECT,
        ProjectPermission.VIEW_RUNS,
        ProjectPermission.VIEW_BEHAVIORS,
        ProjectPermission.VIEW_COMPLIANCE,
        ProjectPermission.VIEW_SETTINGS,
        ProjectPermission.CREATE_RUNS,
        ProjectPermission.CANCEL_RUNS,
        ProjectPermission.DELETE_RUNS,
        ProjectPermission.CREATE_BEHAVIORS,
        ProjectPermission.UPDATE_BEHAVIORS,
        ProjectPermission.DELETE_BEHAVIORS,
        ProjectPermission.CREATE_POLICIES,
        ProjectPermission.UPDATE_POLICIES,
        ProjectPermission.APPROVE_VIOLATIONS,
        ProjectPermission.INVITE_MEMBERS,
        ProjectPermission.REMOVE_MEMBERS,
        ProjectPermission.UPDATE_MEMBER_ROLES,
        ProjectPermission.UPDATE_SETTINGS,
        ProjectPermission.DELETE_PROJECT,
        ProjectPermission.ARCHIVE_PROJECT,
        ProjectPermission.TRANSFER_OWNERSHIP,
        # Board permissions (all)
        ProjectPermission.VIEW_BOARDS,
        ProjectPermission.CREATE_BOARDS,
        ProjectPermission.UPDATE_BOARDS,
        ProjectPermission.DELETE_BOARDS,
        ProjectPermission.MANAGE_COLUMNS,
        ProjectPermission.CREATE_WORK_ITEMS,
        ProjectPermission.UPDATE_WORK_ITEMS,
        ProjectPermission.DELETE_WORK_ITEMS,
        ProjectPermission.ASSIGN_WORK_ITEMS,
        ProjectPermission.MANAGE_SPRINTS,
    },
}


# =============================================================================
# Permission Contracts
# =============================================================================

@dataclass
class PermissionCheckResult:
    """Result of a permission check."""
    allowed: bool
    role: Optional[Union[MemberRole, ProjectRole]] = None
    reason: Optional[str] = None
    checked_permission: Optional[str] = None


@dataclass
class UserOrgContext:
    """User's context within an organization."""
    user_id: str
    org_id: str
    role: MemberRole
    permissions: Set[OrgPermission] = field(default_factory=set)

    def __post_init__(self):
        """Initialize permissions based on role."""
        if not self.permissions:
            self.permissions = ORG_ROLE_PERMISSIONS.get(self.role, set())


@dataclass
class UserProjectContext:
    """User's context within a project."""
    user_id: str
    project_id: str
    role: ProjectRole
    permissions: Set[ProjectPermission] = field(default_factory=set)

    def __post_init__(self):
        """Initialize permissions based on role."""
        if not self.permissions:
            self.permissions = PROJECT_ROLE_PERMISSIONS.get(self.role, set())


# =============================================================================
# Permission Exceptions
# =============================================================================

class PermissionDenied(Exception):
    """Raised when a user lacks required permissions."""

    def __init__(
        self,
        permission: Union[OrgPermission, ProjectPermission],
        user_id: str,
        resource_id: str,
        message: Optional[str] = None,
    ):
        self.permission = permission
        self.user_id = user_id
        self.resource_id = resource_id
        self.message = message or f"User {user_id} lacks permission {permission.value} on {resource_id}"
        super().__init__(self.message)


class NotAMember(Exception):
    """Raised when user is not a member of the resource."""

    def __init__(self, user_id: str, resource_id: str, resource_type: str = "organization"):
        self.user_id = user_id
        self.resource_id = resource_id
        self.resource_type = resource_type
        super().__init__(f"User {user_id} is not a member of {resource_type} {resource_id}")


# =============================================================================
# Permission Service
# =============================================================================

class PermissionService:
    """Service for checking and enforcing permissions.

    This service provides methods to check user permissions at both
    organization and project levels, with caching support.

    Attributes:
        pool: PostgresPool instance for database operations.
        cache_ttl: TTL for permission cache in seconds.
    """

    def __init__(
        self,
        pool: Optional["PostgresPool"] = None,
        dsn: Optional[str] = None,
        cache_ttl: int = 300,
    ):
        """Initialize the permission service.

        Args:
            pool: PostgresPool instance for database operations.
            dsn: PostgreSQL connection string (creates pool automatically).
            cache_ttl: Time-to-live for permission cache in seconds.

        Raises:
            ValueError: If neither pool nor dsn is provided.
        """
        if pool is not None:
            self.pool = pool
        elif dsn is not None:
            from amprealize.storage.postgres_pool import PostgresPool
            self.pool = PostgresPool(dsn=dsn)
        else:
            raise ValueError("Either pool or dsn must be provided")

        self.cache_ttl = cache_ttl
        self._cache: Dict[str, tuple] = {}  # (result, timestamp)

    # =========================================================================
    # Organization Permissions
    # =========================================================================

    def get_user_org_role(self, user_id: str, org_id: str) -> Optional[MemberRole]:
        """Get user's role in an organization.

        Args:
            user_id: User ID to check.
            org_id: Organization ID.

        Returns:
            MemberRole if user is a member, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT role FROM org_memberships
                WHERE user_id = %s AND org_id = %s AND is_active = TRUE
                """,
                (user_id, org_id)
            )
            row = cursor.fetchone()
            if row:
                return MemberRole(row[0])
            return None

    def get_user_org_context(self, user_id: str, org_id: str) -> Optional[UserOrgContext]:
        """Get user's full context within an organization.

        Args:
            user_id: User ID to check.
            org_id: Organization ID.

        Returns:
            UserOrgContext if user is a member, None otherwise.
        """
        role = self.get_user_org_role(user_id, org_id)
        if role is None:
            return None
        return UserOrgContext(user_id=user_id, org_id=org_id, role=role)

    def has_org_permission(
        self,
        user_id: str,
        org_id: str,
        permission: OrgPermission,
    ) -> PermissionCheckResult:
        """Check if user has a specific organization permission.

        Args:
            user_id: User ID to check.
            org_id: Organization ID.
            permission: Permission to check.

        Returns:
            PermissionCheckResult indicating whether permission is granted.
        """
        role = self.get_user_org_role(user_id, org_id)

        if role is None:
            return PermissionCheckResult(
                allowed=False,
                reason=f"User is not a member of organization {org_id}",
                checked_permission=permission.value,
            )

        role_permissions = ORG_ROLE_PERMISSIONS.get(role, set())
        allowed = permission in role_permissions

        return PermissionCheckResult(
            allowed=allowed,
            role=role,
            reason=None if allowed else f"Role {role.value} lacks permission {permission.value}",
            checked_permission=permission.value,
        )

    def require_org_permission(
        self,
        user_id: str,
        org_id: str,
        permission: OrgPermission,
    ) -> UserOrgContext:
        """Require a specific organization permission, raising if not granted.

        Args:
            user_id: User ID to check.
            org_id: Organization ID.
            permission: Required permission.

        Returns:
            UserOrgContext for the user.

        Raises:
            NotAMember: If user is not a member of the organization.
            PermissionDenied: If user lacks the required permission.
        """
        context = self.get_user_org_context(user_id, org_id)

        if context is None:
            raise NotAMember(user_id, org_id, "organization")

        if permission not in context.permissions:
            raise PermissionDenied(permission, user_id, org_id)

        return context

    def get_user_org_permissions(
        self,
        user_id: str,
        org_id: str,
    ) -> Set[OrgPermission]:
        """Get all permissions a user has in an organization.

        Args:
            user_id: User ID to check.
            org_id: Organization ID.

        Returns:
            Set of OrgPermissions the user has.
        """
        role = self.get_user_org_role(user_id, org_id)
        if role is None:
            return set()
        return ORG_ROLE_PERMISSIONS.get(role, set())

    # =========================================================================
    # Project Permissions
    # =========================================================================

    def get_user_project_role(
        self,
        user_id: str,
        project_id: str,
    ) -> Optional[ProjectRole]:
        """Get user's role in a project.

        For org-owned projects, this checks project_memberships first,
        then falls back to org membership with appropriate role mapping.

        For user-owned projects, checks if user is owner or collaborator.

        Args:
            user_id: User ID to check.
            project_id: Project ID.

        Returns:
            ProjectRole if user has access, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()

            # First check if user is the project owner (user-owned project)
            cursor.execute(
                """
                SELECT owner_id FROM projects WHERE project_id = %s
                """,
                (project_id,)
            )
            row = cursor.fetchone()
            if row and row[0] == user_id:
                return ProjectRole.OWNER

            # Check project membership
            cursor.execute(
                """
                SELECT role FROM project_memberships
                WHERE project_id = %s AND user_id = %s
                """,
                (project_id, user_id)
            )
            row = cursor.fetchone()
            if row:
                return ProjectRole(row[0])

            # Check collaborators (for user-owned projects)
            cursor.execute(
                """
                SELECT role FROM project_collaborators
                WHERE project_id = %s AND user_id = %s
                """,
                (project_id, user_id)
            )
            row = cursor.fetchone()
            if row:
                return ProjectRole(row[0])

            # For org-owned projects, check org membership
            cursor.execute(
                """
                SELECT m.role
                FROM org_memberships m
                JOIN projects p ON p.org_id = m.org_id
                WHERE p.project_id = %s AND m.user_id = %s AND m.is_active = TRUE
                """,
                (project_id, user_id)
            )
            row = cursor.fetchone()
            if row:
                # Map org role to project role
                org_role = MemberRole(row[0])
                return self._map_org_role_to_project_role(org_role)

            return None

    def _map_org_role_to_project_role(self, org_role: MemberRole) -> ProjectRole:
        """Map organization role to default project role.

        Args:
            org_role: Organization role.

        Returns:
            Corresponding project role.
        """
        mapping = {
            MemberRole.OWNER: ProjectRole.OWNER,
            MemberRole.ADMIN: ProjectRole.MAINTAINER,
            MemberRole.MEMBER: ProjectRole.CONTRIBUTOR,
            MemberRole.VIEWER: ProjectRole.VIEWER,
        }
        return mapping.get(org_role, ProjectRole.VIEWER)

    def get_user_project_context(
        self,
        user_id: str,
        project_id: str,
    ) -> Optional[UserProjectContext]:
        """Get user's full context within a project.

        Args:
            user_id: User ID to check.
            project_id: Project ID.

        Returns:
            UserProjectContext if user has access, None otherwise.
        """
        role = self.get_user_project_role(user_id, project_id)
        if role is None:
            return None
        return UserProjectContext(user_id=user_id, project_id=project_id, role=role)

    def has_project_permission(
        self,
        user_id: str,
        project_id: str,
        permission: ProjectPermission,
    ) -> PermissionCheckResult:
        """Check if user has a specific project permission.

        Args:
            user_id: User ID to check.
            project_id: Project ID.
            permission: Permission to check.

        Returns:
            PermissionCheckResult indicating whether permission is granted.
        """
        role = self.get_user_project_role(user_id, project_id)

        if role is None:
            return PermissionCheckResult(
                allowed=False,
                reason=f"User has no access to project {project_id}",
                checked_permission=permission.value,
            )

        role_permissions = PROJECT_ROLE_PERMISSIONS.get(role, set())
        allowed = permission in role_permissions

        return PermissionCheckResult(
            allowed=allowed,
            role=role,
            reason=None if allowed else f"Role {role.value} lacks permission {permission.value}",
            checked_permission=permission.value,
        )

    def require_project_permission(
        self,
        user_id: str,
        project_id: str,
        permission: ProjectPermission,
    ) -> UserProjectContext:
        """Require a specific project permission, raising if not granted.

        Args:
            user_id: User ID to check.
            project_id: Project ID.
            permission: Required permission.

        Returns:
            UserProjectContext for the user.

        Raises:
            NotAMember: If user has no access to the project.
            PermissionDenied: If user lacks the required permission.
        """
        context = self.get_user_project_context(user_id, project_id)

        if context is None:
            raise NotAMember(user_id, project_id, "project")

        if permission not in context.permissions:
            raise PermissionDenied(permission, user_id, project_id)

        return context

    def get_user_project_permissions(
        self,
        user_id: str,
        project_id: str,
    ) -> Set[ProjectPermission]:
        """Get all permissions a user has in a project.

        Args:
            user_id: User ID to check.
            project_id: Project ID.

        Returns:
            Set of ProjectPermissions the user has.
        """
        role = self.get_user_project_role(user_id, project_id)
        if role is None:
            return set()
        return PROJECT_ROLE_PERMISSIONS.get(role, set())

    # =========================================================================
    # Bulk Permission Checks
    # =========================================================================

    def filter_accessible_projects(
        self,
        user_id: str,
        project_ids: List[str],
        required_permission: Optional[ProjectPermission] = None,
    ) -> List[str]:
        """Filter a list of projects to those the user can access.

        Args:
            user_id: User ID to check.
            project_ids: List of project IDs to filter.
            required_permission: Optional permission to require.

        Returns:
            List of project IDs the user can access.
        """
        if not project_ids:
            return []

        accessible = []
        for project_id in project_ids:
            if required_permission:
                result = self.has_project_permission(user_id, project_id, required_permission)
                if result.allowed:
                    accessible.append(project_id)
            else:
                role = self.get_user_project_role(user_id, project_id)
                if role is not None:
                    accessible.append(project_id)

        return accessible

    def filter_accessible_orgs(
        self,
        user_id: str,
        org_ids: List[str],
        required_permission: Optional[OrgPermission] = None,
    ) -> List[str]:
        """Filter a list of organizations to those the user can access.

        Args:
            user_id: User ID to check.
            org_ids: List of organization IDs to filter.
            required_permission: Optional permission to require.

        Returns:
            List of organization IDs the user can access.
        """
        if not org_ids:
            return []

        accessible = []
        for org_id in org_ids:
            if required_permission:
                result = self.has_org_permission(user_id, org_id, required_permission)
                if result.allowed:
                    accessible.append(org_id)
            else:
                role = self.get_user_org_role(user_id, org_id)
                if role is not None:
                    accessible.append(org_id)

        return accessible


# =============================================================================
# FastAPI Decorators
# =============================================================================

F = TypeVar('F', bound=Callable[..., Any])


def require_org_permission_decorator(permission: OrgPermission) -> Callable[[F], F]:
    """Decorator factory for requiring organization permission on FastAPI endpoints.

    The decorated endpoint must have:
    - `org_id` path parameter
    - `request` parameter with `state.user_id` set by auth middleware
    - `permission_service` in `request.state` or app state

    Example:
        @app.post("/orgs/{org_id}/members")
        @require_org_permission_decorator(OrgPermission.INVITE_MEMBERS)
        async def invite_member(org_id: str, request: Request, body: InviteRequest):
            # User is authorized, proceed with invite
            pass

    Args:
        permission: Required OrgPermission.

    Returns:
        Decorator function.
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Extract request and org_id from kwargs
            request = kwargs.get('request')
            org_id = kwargs.get('org_id')

            if request is None or org_id is None:
                raise ValueError(
                    "Endpoint must have 'request' and 'org_id' parameters "
                    "for @require_org_permission decorator"
                )

            # Get user_id from request state (set by auth middleware)
            user_id = getattr(request.state, 'user_id', None)
            if user_id is None:
                from fastapi import HTTPException
                raise HTTPException(status_code=401, detail="Authentication required")

            # Get permission service
            perm_service = getattr(request.state, 'permission_service', None)
            if perm_service is None:
                perm_service = getattr(request.app.state, 'permission_service', None)

            if perm_service is None:
                raise ValueError("PermissionService not found in request or app state")

            # Check permission
            try:
                perm_service.require_org_permission(user_id, org_id, permission)
            except NotAMember:
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail="Organization not found")
            except PermissionDenied as e:
                from fastapi import HTTPException
                raise HTTPException(status_code=403, detail=str(e))

            return await func(*args, **kwargs)

        return wrapper  # type: ignore
    return decorator


def require_project_permission_decorator(permission: ProjectPermission) -> Callable[[F], F]:
    """Decorator factory for requiring project permission on FastAPI endpoints.

    Similar to require_org_permission_decorator but for projects.

    Args:
        permission: Required ProjectPermission.

    Returns:
        Decorator function.
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Extract request and project_id from kwargs
            request = kwargs.get('request')
            project_id = kwargs.get('project_id')

            if request is None or project_id is None:
                raise ValueError(
                    "Endpoint must have 'request' and 'project_id' parameters "
                    "for @require_project_permission decorator"
                )

            # Get user_id from request state
            user_id = getattr(request.state, 'user_id', None)
            if user_id is None:
                from fastapi import HTTPException
                raise HTTPException(status_code=401, detail="Authentication required")

            # Get permission service
            perm_service = getattr(request.state, 'permission_service', None)
            if perm_service is None:
                perm_service = getattr(request.app.state, 'permission_service', None)

            if perm_service is None:
                raise ValueError("PermissionService not found in request or app state")

            # Check permission
            try:
                perm_service.require_project_permission(user_id, project_id, permission)
            except NotAMember:
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail="Project not found")
            except PermissionDenied as e:
                from fastapi import HTTPException
                raise HTTPException(status_code=403, detail=str(e))

            return await func(*args, **kwargs)

        return wrapper  # type: ignore
    return decorator


# Convenience aliases
require_org_permission = require_org_permission_decorator
require_project_permission = require_project_permission_decorator


# =============================================================================
# Helper Functions
# =============================================================================

def get_role_permissions(role: Union[MemberRole, ProjectRole]) -> Set[Union[OrgPermission, ProjectPermission]]:
    """Get all permissions for a given role.

    Args:
        role: MemberRole or ProjectRole.

    Returns:
        Set of permissions for the role.
    """
    if isinstance(role, MemberRole):
        return ORG_ROLE_PERMISSIONS.get(role, set())  # type: ignore
    elif isinstance(role, ProjectRole):
        return PROJECT_ROLE_PERMISSIONS.get(role, set())  # type: ignore
    return set()


def permission_requires_role(
    permission: Union[OrgPermission, ProjectPermission],
) -> Optional[Union[MemberRole, ProjectRole]]:
    """Get the minimum role required for a permission.

    Args:
        permission: Permission to check.

    Returns:
        Minimum role that has the permission, or None if not found.
    """
    if isinstance(permission, OrgPermission):
        # Check roles from lowest to highest
        for role in [MemberRole.VIEWER, MemberRole.MEMBER, MemberRole.ADMIN, MemberRole.OWNER]:
            if permission in ORG_ROLE_PERMISSIONS.get(role, set()):
                return role
    elif isinstance(permission, ProjectPermission):
        for role in [ProjectRole.VIEWER, ProjectRole.CONTRIBUTOR, ProjectRole.MAINTAINER, ProjectRole.OWNER]:
            if permission in PROJECT_ROLE_PERMISSIONS.get(role, set()):
                return role
    return None


# =============================================================================
# Async Permission Service
# =============================================================================

class AsyncPermissionService:
    """Async version of PermissionService for use with FastAPI.

    This service provides async methods to check user permissions at both
    organization and project levels, using asyncpg for database operations.

    Behavior: behavior_lock_down_security_surface

    Attributes:
        dsn: PostgreSQL connection string.
        cache_ttl: TTL for permission cache in seconds.
    """

    def __init__(
        self,
        dsn: Optional[str] = None,
        cache_ttl: int = 300,
    ):
        """Initialize the async permission service.

        Args:
            dsn: PostgreSQL connection string. If None, uses AMPREALIZE_AUTH_PG_DSN env var.
            cache_ttl: Time-to-live for permission cache in seconds.
        """
        import os
        self.dsn = dsn or os.getenv("AMPREALIZE_AUTH_PG_DSN")
        if not self.dsn:
            raise ValueError("DSN required - provide dsn or set AMPREALIZE_AUTH_PG_DSN")

        self.cache_ttl = cache_ttl
        self._pool = None
        self._cache: Dict[str, tuple] = {}  # (result, timestamp)

    async def _get_pool(self):
        """Get or create asyncpg connection pool."""
        if self._pool is None:
            try:
                import asyncpg
                self._pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=10)
            except ImportError:
                raise ImportError("asyncpg required for AsyncPermissionService. Install with: pip install asyncpg")
        return self._pool

    async def close(self):
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    # =========================================================================
    # Organization Permissions (Async)
    # =========================================================================

    async def get_user_org_role(self, user_id: str, org_id: str) -> Optional[MemberRole]:
        """Get user's role in an organization.

        Args:
            user_id: User ID to check.
            org_id: Organization ID.

        Returns:
            MemberRole if user is a member, None otherwise.
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT role FROM org_memberships
                WHERE user_id = $1 AND org_id = $2 AND is_active = TRUE
                """,
                user_id, org_id
            )
            if row:
                return MemberRole(row["role"])
            return None

    async def get_user_org_context(self, user_id: str, org_id: str) -> Optional[UserOrgContext]:
        """Get user's full context within an organization.

        Args:
            user_id: User ID to check.
            org_id: Organization ID.

        Returns:
            UserOrgContext if user is a member, None otherwise.
        """
        role = await self.get_user_org_role(user_id, org_id)
        if role is None:
            return None
        return UserOrgContext(user_id=user_id, org_id=org_id, role=role)

    async def has_org_permission(
        self,
        user_id: str,
        org_id: str,
        permission: OrgPermission,
    ) -> PermissionCheckResult:
        """Check if user has a specific organization permission.

        Args:
            user_id: User ID to check.
            org_id: Organization ID.
            permission: Permission to check.

        Returns:
            PermissionCheckResult indicating whether permission is granted.
        """
        role = await self.get_user_org_role(user_id, org_id)

        if role is None:
            return PermissionCheckResult(
                allowed=False,
                reason=f"User is not a member of organization {org_id}",
                checked_permission=permission.value,
            )

        role_permissions = ORG_ROLE_PERMISSIONS.get(role, set())
        allowed = permission in role_permissions

        return PermissionCheckResult(
            allowed=allowed,
            role=role,
            reason=None if allowed else f"Role {role.value} lacks permission {permission.value}",
            checked_permission=permission.value,
        )

    async def require_org_permission(
        self,
        user_id: str,
        org_id: str,
        permission: OrgPermission,
    ) -> UserOrgContext:
        """Require a specific organization permission, raising if not granted.

        Args:
            user_id: User ID to check.
            org_id: Organization ID.
            permission: Required permission.

        Returns:
            UserOrgContext for the user.

        Raises:
            NotAMember: If user is not a member of the organization.
            PermissionDenied: If user lacks the required permission.
        """
        context = await self.get_user_org_context(user_id, org_id)

        if context is None:
            raise NotAMember(user_id, org_id, "organization")

        if permission not in context.permissions:
            raise PermissionDenied(permission, user_id, org_id)

        return context

    async def get_user_org_permissions(
        self,
        user_id: str,
        org_id: str,
    ) -> Set[OrgPermission]:
        """Get all permissions a user has in an organization.

        Args:
            user_id: User ID to check.
            org_id: Organization ID.

        Returns:
            Set of OrgPermissions the user has.
        """
        role = await self.get_user_org_role(user_id, org_id)
        if role is None:
            return set()
        return ORG_ROLE_PERMISSIONS.get(role, set())

    # =========================================================================
    # Project Permissions (Async)
    # =========================================================================

    async def get_user_project_role(
        self,
        user_id: str,
        project_id: str,
    ) -> Optional[ProjectRole]:
        """Get user's role in a project.

        For org-owned projects, this checks project_memberships first,
        then falls back to org membership with appropriate role mapping.

        For user-owned projects, checks if user is owner or collaborator.

        Args:
            user_id: User ID to check.
            project_id: Project ID.

        Returns:
            ProjectRole if user has access, None otherwise.
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # First check if user is the project owner (user-owned project)
            row = await conn.fetchrow(
                "SELECT owner_id FROM projects WHERE project_id = $1",
                project_id
            )
            if row and row["owner_id"] == user_id:
                return ProjectRole.OWNER

            # Check project membership
            row = await conn.fetchrow(
                """
                SELECT role FROM project_memberships
                WHERE project_id = $1 AND user_id = $2
                """,
                project_id, user_id
            )
            if row:
                return ProjectRole(row["role"])

            # Check collaborators (for user-owned projects)
            row = await conn.fetchrow(
                """
                SELECT role FROM project_collaborators
                WHERE project_id = $1 AND user_id = $2
                """,
                project_id, user_id
            )
            if row:
                return ProjectRole(row["role"])

            # For org-owned projects, check org membership
            row = await conn.fetchrow(
                """
                SELECT m.role
                FROM org_memberships m
                JOIN projects p ON p.org_id = m.org_id
                WHERE p.project_id = $1 AND m.user_id = $2 AND m.is_active = TRUE
                """,
                project_id, user_id
            )
            if row:
                # Map org role to project role
                org_role = MemberRole(row["role"])
                return self._map_org_role_to_project_role(org_role)

            return None

    def _map_org_role_to_project_role(self, org_role: MemberRole) -> ProjectRole:
        """Map organization role to default project role.

        Args:
            org_role: Organization role.

        Returns:
            Corresponding project role.
        """
        mapping = {
            MemberRole.OWNER: ProjectRole.OWNER,
            MemberRole.ADMIN: ProjectRole.MAINTAINER,
            MemberRole.MEMBER: ProjectRole.CONTRIBUTOR,
            MemberRole.VIEWER: ProjectRole.VIEWER,
        }
        return mapping.get(org_role, ProjectRole.VIEWER)

    async def get_user_project_context(
        self,
        user_id: str,
        project_id: str,
    ) -> Optional[UserProjectContext]:
        """Get user's full context within a project.

        Args:
            user_id: User ID to check.
            project_id: Project ID.

        Returns:
            UserProjectContext if user has access, None otherwise.
        """
        role = await self.get_user_project_role(user_id, project_id)
        if role is None:
            return None
        return UserProjectContext(user_id=user_id, project_id=project_id, role=role)

    async def has_project_permission(
        self,
        user_id: str,
        project_id: str,
        permission: ProjectPermission,
    ) -> PermissionCheckResult:
        """Check if user has a specific project permission.

        Args:
            user_id: User ID to check.
            project_id: Project ID.
            permission: Permission to check.

        Returns:
            PermissionCheckResult indicating whether permission is granted.
        """
        role = await self.get_user_project_role(user_id, project_id)

        if role is None:
            return PermissionCheckResult(
                allowed=False,
                reason=f"User has no access to project {project_id}",
                checked_permission=permission.value,
            )

        role_permissions = PROJECT_ROLE_PERMISSIONS.get(role, set())
        allowed = permission in role_permissions

        return PermissionCheckResult(
            allowed=allowed,
            role=role,
            reason=None if allowed else f"Role {role.value} lacks permission {permission.value}",
            checked_permission=permission.value,
        )

    async def require_project_permission(
        self,
        user_id: str,
        project_id: str,
        permission: ProjectPermission,
    ) -> UserProjectContext:
        """Require a specific project permission, raising if not granted.

        Args:
            user_id: User ID to check.
            project_id: Project ID.
            permission: Required permission.

        Returns:
            UserProjectContext for the user.

        Raises:
            NotAMember: If user has no access to the project.
            PermissionDenied: If user lacks the required permission.
        """
        context = await self.get_user_project_context(user_id, project_id)

        if context is None:
            raise NotAMember(user_id, project_id, "project")

        if permission not in context.permissions:
            raise PermissionDenied(permission, user_id, project_id)

        return context

    async def get_user_project_permissions(
        self,
        user_id: str,
        project_id: str,
    ) -> Set[ProjectPermission]:
        """Get all permissions a user has in a project.

        Args:
            user_id: User ID to check.
            project_id: Project ID.

        Returns:
            Set of ProjectPermissions the user has.
        """
        role = await self.get_user_project_role(user_id, project_id)
        if role is None:
            return set()
        return PROJECT_ROLE_PERMISSIONS.get(role, set())

    # =========================================================================
    # Bulk Permission Checks (Async)
    # =========================================================================

    async def filter_accessible_projects(
        self,
        user_id: str,
        project_ids: List[str],
        required_permission: Optional[ProjectPermission] = None,
    ) -> List[str]:
        """Filter a list of projects to those the user can access.

        Args:
            user_id: User ID to check.
            project_ids: List of project IDs to filter.
            required_permission: Optional permission to require.

        Returns:
            List of project IDs the user can access.
        """
        if not project_ids:
            return []

        accessible = []
        for project_id in project_ids:
            if required_permission:
                result = await self.has_project_permission(user_id, project_id, required_permission)
                if result.allowed:
                    accessible.append(project_id)
            else:
                role = await self.get_user_project_role(user_id, project_id)
                if role is not None:
                    accessible.append(project_id)

        return accessible

    async def filter_accessible_orgs(
        self,
        user_id: str,
        org_ids: List[str],
        required_permission: Optional[OrgPermission] = None,
    ) -> List[str]:
        """Filter a list of organizations to those the user can access.

        Args:
            user_id: User ID to check.
            org_ids: List of organization IDs to filter.
            required_permission: Optional permission to require.

        Returns:
            List of organization IDs the user can access.
        """
        if not org_ids:
            return []

        accessible = []
        for org_id in org_ids:
            if required_permission:
                result = await self.has_org_permission(user_id, org_id, required_permission)
                if result.allowed:
                    accessible.append(org_id)
            else:
                role = await self.get_user_org_role(user_id, org_id)
                if role is not None:
                    accessible.append(org_id)

        return accessible


# =============================================================================
# Async FastAPI Decorators
# =============================================================================

def require_org_permission_async(permission: OrgPermission) -> Callable[[F], F]:
    """Async decorator factory for requiring organization permission on FastAPI endpoints.

    The decorated endpoint must have:
    - `org_id` path parameter
    - `request` parameter with `state.user_id` set by auth middleware
    - `async_permission_service` in `request.app.state`

    Example:
        @app.post("/orgs/{org_id}/members")
        @require_org_permission_async(OrgPermission.INVITE_MEMBERS)
        async def invite_member(org_id: str, request: Request, body: InviteRequest):
            # User is authorized, proceed with invite
            pass

    Args:
        permission: Required OrgPermission.

    Returns:
        Decorator function.
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Extract request and org_id from kwargs
            request = kwargs.get('request')
            org_id = kwargs.get('org_id')

            if request is None or org_id is None:
                raise ValueError(
                    "Endpoint must have 'request' and 'org_id' parameters "
                    "for @require_org_permission_async decorator"
                )

            # Get user_id from request state (set by auth middleware)
            user_id = getattr(request.state, 'user_id', None)
            if user_id is None:
                from fastapi import HTTPException
                raise HTTPException(status_code=401, detail="Authentication required")

            # Get async permission service
            perm_service = getattr(request.app.state, 'async_permission_service', None)

            if perm_service is None:
                raise ValueError("AsyncPermissionService not found in app state")

            # Check permission
            try:
                await perm_service.require_org_permission(user_id, org_id, permission)
            except NotAMember:
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail="Organization not found")
            except PermissionDenied as e:
                from fastapi import HTTPException
                raise HTTPException(status_code=403, detail=str(e))

            return await func(*args, **kwargs)

        return wrapper  # type: ignore
    return decorator


def require_project_permission_async(permission: ProjectPermission) -> Callable[[F], F]:
    """Async decorator factory for requiring project permission on FastAPI endpoints.

    Similar to require_org_permission_async but for projects.

    Args:
        permission: Required ProjectPermission.

    Returns:
        Decorator function.
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Extract request and project_id from kwargs
            request = kwargs.get('request')
            project_id = kwargs.get('project_id')

            if request is None or project_id is None:
                raise ValueError(
                    "Endpoint must have 'request' and 'project_id' parameters "
                    "for @require_project_permission_async decorator"
                )

            # Get user_id from request state
            user_id = getattr(request.state, 'user_id', None)
            if user_id is None:
                from fastapi import HTTPException
                raise HTTPException(status_code=401, detail="Authentication required")

            # Get async permission service
            perm_service = getattr(request.app.state, 'async_permission_service', None)

            if perm_service is None:
                raise ValueError("AsyncPermissionService not found in app state")

            # Check permission
            try:
                await perm_service.require_project_permission(user_id, project_id, permission)
            except NotAMember:
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail="Project not found")
            except PermissionDenied as e:
                from fastapi import HTTPException
                raise HTTPException(status_code=403, detail=str(e))

            return await func(*args, **kwargs)

        return wrapper  # type: ignore
    return decorator
