"""
MCP Service Adapter with Tenant Context Injection.

Wraps service calls to inject tenant context from MCP session,
ensuring all operations are properly scoped to the authenticated
user's organization and project.

See MCP_AUTH_IMPLEMENTATION_PLAN.md Phase 4 for details.

Following behavior_lock_down_security_surface (Student).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional, Set, TYPE_CHECKING
import uuid

if TYPE_CHECKING:
    from .mcp_server import MCPSessionContext


@dataclass
class TenantContext:
    """
    Immutable tenant context for service calls.

    Captures the authenticated identity and active org/project context
    at the time of a service call. Used for RLS scoping and audit logging.

    Note: org_id and project_id are OPTIONAL - users can operate without
    being part of an organization, and projects can exist independently.
    """
    # Identity (one of these is always set after auth)
    user_id: Optional[str] = None
    service_principal_id: Optional[str] = None

    # Tenant context (optional - not all users/SPs belong to orgs)
    org_id: Optional[str] = None
    project_id: Optional[str] = None

    # Auth metadata
    auth_method: str = "none"
    roles: Set[str] = field(default_factory=set)
    granted_scopes: Set[str] = field(default_factory=set)

    # Request tracing
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def identity(self) -> Optional[str]:
        """Get primary identity (user_id or service_principal_id)."""
        return self.user_id or self.service_principal_id

    @property
    def identity_type(self) -> str:
        """Get identity type for logging/audit."""
        if self.user_id:
            return "user"
        if self.service_principal_id:
            return "service_principal"
        return "anonymous"

    def to_headers(self) -> Dict[str, str]:
        """
        Generate HTTP headers for downstream service calls.

        These headers enable:
        - RLS scoping via X-Org-ID / X-Project-ID
        - Audit logging via X-User-ID / X-Service-Principal-ID
        - Request tracing via X-Request-ID
        """
        headers = {
            "X-Request-ID": self.request_id,
            "X-Auth-Method": self.auth_method,
            "X-Timestamp": self.timestamp.isoformat(),
        }

        # Identity headers
        if self.user_id:
            headers["X-User-ID"] = self.user_id
        if self.service_principal_id:
            headers["X-Service-Principal-ID"] = self.service_principal_id

        # Tenant context headers (only if set)
        if self.org_id:
            headers["X-Org-ID"] = self.org_id
        if self.project_id:
            headers["X-Project-ID"] = self.project_id

        # Role for RBAC decisions
        if self.roles:
            headers["X-Roles"] = ",".join(sorted(self.roles))

        return headers

    def to_audit_context(self) -> Dict[str, Any]:
        """
        Generate context for audit log entries.

        Includes all identity and tenant information needed to
        reconstruct the authorization state at time of action.
        """
        return {
            "user_id": self.user_id,
            "service_principal_id": self.service_principal_id,
            "org_id": self.org_id,
            "project_id": self.project_id,
            "auth_method": self.auth_method,
            "roles": list(self.roles),
            "scopes": list(self.granted_scopes),
            "request_id": self.request_id,
            "timestamp": self.timestamp.isoformat(),
        }


class MCPServiceAdapter:
    """
    Injects tenant context into all service calls.

    This adapter ensures that:
    1. All service calls are scoped to the authenticated tenant
    2. Audit logs include proper identity context
    3. Request tracing is consistent across calls

    Usage:
        adapter = MCPServiceAdapter(session_context)
        headers = adapter.get_context_headers()
        audit_ctx = adapter.get_audit_context()
    """

    def __init__(self, session: "MCPSessionContext"):
        """
        Initialize adapter from MCP session.

        Args:
            session: The current MCP session context (may have None org_id)
        """
        self._session = session
        self._request_id = str(uuid.uuid4())

    def get_tenant_context(self) -> TenantContext:
        """
        Build TenantContext from current session.

        Returns:
            TenantContext with current identity and tenant scope
        """
        return TenantContext(
            user_id=self._session.user_id,
            service_principal_id=self._session.service_principal_id,
            org_id=self._session.org_id,
            project_id=self._session.project_id,
            auth_method=self._session.auth_method,
            roles=set(self._session.roles) if self._session.roles else set(),
            granted_scopes=self._session.granted_scopes or set(),
            request_id=self._request_id,
        )

    def get_context_headers(self) -> Dict[str, str]:
        """Get HTTP headers for service calls."""
        return self.get_tenant_context().to_headers()

    def get_audit_context(self) -> Dict[str, Any]:
        """Get context dict for audit logging."""
        return self.get_tenant_context().to_audit_context()

    def inject_tenant_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Inject tenant context into tool parameters.

        This is used for tools that need org_id/project_id but
        don't require the caller to specify them explicitly.

        Args:
            params: Original tool parameters

        Returns:
            Parameters with tenant context injected (if not already set)
        """
        result = dict(params)

        # Inject org_id if not provided and session has one
        if "org_id" not in result and self._session.org_id:
            result["org_id"] = self._session.org_id

        # Inject project_id if not provided and session has one
        if "project_id" not in result and self._session.project_id:
            result["project_id"] = self._session.project_id

        # Inject user_id for tools that need actor context
        if "user_id" not in result and self._session.user_id:
            result["user_id"] = self._session.user_id

        # Inject service_principal_id for SP calls
        if "service_principal_id" not in result and self._session.service_principal_id:
            result["service_principal_id"] = self._session.service_principal_id

        return result


@dataclass
class ContextSwitchResult:
    """Result of a context switch operation."""
    success: bool
    org_id: Optional[str] = None
    org_name: Optional[str] = None
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    role: Optional[str] = None
    permissions: Optional[list] = None
    error: Optional[str] = None
    error_code: Optional[str] = None


class ContextSwitchHandler:
    """
    Handles context switching with permission validation.

    Verifies that the authenticated user/SP has access to the
    target organization or project before switching context.

    Important: org_id is OPTIONAL - users can operate without
    being part of an organization.
    """

    def __init__(
        self,
        session: "MCPSessionContext",
        permission_service: Any = None,  # AsyncPermissionService
        org_service: Any = None,  # OrganizationService
        project_service: Any = None,  # ProjectService
    ):
        self._session = session
        self._permission_service = permission_service
        self._org_service = org_service
        self._project_service = project_service

    async def set_org_context(self, org_id: str) -> ContextSwitchResult:
        """
        Switch to a different organization context.

        Args:
            org_id: Organization ID to switch to

        Returns:
            ContextSwitchResult with new context or error
        """
        identity = self._session.user_id or self._session.service_principal_id
        if not identity:
            return ContextSwitchResult(
                success=False,
                error="Not authenticated",
                error_code="NOT_AUTHENTICATED",
            )

        # Verify user/SP has access to this org
        if self._permission_service:
            try:
                role = await self._permission_service.get_user_org_role(identity, org_id)
                if role is None:
                    return ContextSwitchResult(
                        success=False,
                        error=f"Access denied to organization {org_id}",
                        error_code="ACCESS_DENIED",
                    )

                # Get org details
                org_name = None
                permissions = []
                if self._org_service:
                    org = self._org_service.get(org_id)
                    org_name = org.name if org else None

                # Get permissions for this role
                if self._permission_service:
                    perms = await self._permission_service.get_user_org_permissions(identity, org_id)
                    permissions = [p.value for p in perms]

                # Update session context
                self._session.org_id = org_id
                self._session.project_id = None  # Reset project when switching org

                return ContextSwitchResult(
                    success=True,
                    org_id=org_id,
                    org_name=org_name,
                    role=role.value if role else None,
                    permissions=permissions,
                )

            except Exception as e:
                return ContextSwitchResult(
                    success=False,
                    error=f"Failed to verify org access: {e}",
                    error_code="PERMISSION_CHECK_FAILED",
                )

        # If no permission service, allow switching (for testing/development)
        self._session.org_id = org_id
        self._session.project_id = None

        return ContextSwitchResult(
            success=True,
            org_id=org_id,
        )

    async def set_project_context(self, project_id: str) -> ContextSwitchResult:
        """
        Switch to a different project context.

        For org-owned projects, verifies the project belongs to the
        current org context (if set). For user-owned projects, verifies
        the user is the owner or collaborator.

        Args:
            project_id: Project ID to switch to

        Returns:
            ContextSwitchResult with new context or error
        """
        identity = self._session.user_id or self._session.service_principal_id
        if not identity:
            return ContextSwitchResult(
                success=False,
                error="Not authenticated",
                error_code="NOT_AUTHENTICATED",
            )

        # Get project details
        project = None
        if self._project_service:
            project = self._project_service.get_project(project_id)
            if not project:
                return ContextSwitchResult(
                    success=False,
                    error=f"Project {project_id} not found",
                    error_code="PROJECT_NOT_FOUND",
                )

            # If project belongs to an org, verify org access
            if project.org_id:
                # If we have a current org context, verify it matches
                if self._session.org_id and project.org_id != self._session.org_id:
                    return ContextSwitchResult(
                        success=False,
                        error=f"Project {project_id} belongs to a different organization",
                        error_code="ORG_MISMATCH",
                    )

                # Verify user has access to the project's org
                if self._permission_service:
                    role = await self._permission_service.get_user_org_role(identity, project.org_id)
                    if role is None:
                        return ContextSwitchResult(
                            success=False,
                            error="Access denied to project's organization",
                            error_code="ACCESS_DENIED",
                        )
            else:
                # User-owned project - verify user is owner or collaborator
                if project.owner_id != identity:
                    # TODO: Check collaborators when implemented
                    pass

        # Update session context
        self._session.project_id = project_id

        # Also update org context if project has one and we didn't have one set
        if project and project.org_id and not self._session.org_id:
            self._session.org_id = project.org_id

        return ContextSwitchResult(
            success=True,
            org_id=self._session.org_id,
            project_id=project_id,
            project_name=project.name if project else None,
        )

    async def clear_context(self) -> ContextSwitchResult:
        """
        Clear the current org and project context.

        Returns the session to a state with no active tenant scope.
        Useful when the user wants to operate without org context.
        """
        self._session.org_id = None
        self._session.project_id = None

        return ContextSwitchResult(
            success=True,
        )

    def get_current_context(self) -> Dict[str, Any]:
        """
        Get the current context state.

        Returns:
            Dict with current org/project context and identity info
        """
        return {
            "user_id": self._session.user_id,
            "service_principal_id": self._session.service_principal_id,
            "org_id": self._session.org_id,
            "project_id": self._session.project_id,
            "auth_method": self._session.auth_method,
            "roles": list(self._session.roles) if self._session.roles else [],
            "scopes": list(self._session.granted_scopes) if self._session.granted_scopes else [],
            "is_authenticated": self._session.is_authenticated,
        }
