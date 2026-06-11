"""MCP tool handlers for ProjectService.

Provides handlers for project management within organizations.
Following `behavior_prefer_mcp_tools` - MCP provides consistent schemas and automatic telemetry.
"""

from __future__ import annotations

from datetime import datetime
import inspect
import re
from typing import Any, Dict, Optional

from ...multi_tenant.organization_service import OrganizationService
from ...multi_tenant.contracts import (
    Project,
    ProjectMembership,
    ProjectRole,
    ProjectVisibility,
    MemberRole,
    UpdateProjectRequest,
)


# ==============================================================================
# Serialization Helpers
# ==============================================================================


def _serialize_value(value: Any) -> Any:
    """Recursively serialize values for JSON output."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, 'value'):  # Enum
        return value.value
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_value(v) for v in value]
    return str(value)


def _project_to_dict(project: Project) -> Dict[str, Any]:
    """Convert Project Pydantic model to dict with serialized timestamps."""
    result = project.model_dump()
    return {k: _serialize_value(v) for k, v in result.items()}


def _membership_to_dict(membership: ProjectMembership) -> Dict[str, Any]:
    """Convert ProjectMembership Pydantic model to dict with serialized timestamps."""
    result = membership.model_dump()
    return {k: _serialize_value(v) for k, v in result.items()}


async def _call(method: Any, *args: Any, **kwargs: Any) -> Any:
    """Call sync or async service methods through one awaitable path."""
    result = method(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


# ==============================================================================
# Authorization Helpers
# ==============================================================================


def _is_admin_from_session(arguments: Dict[str, Any]) -> bool:
    """Check if the session indicates admin status."""
    session = arguments.get("_session", {})
    return session.get("is_admin", False)


def _resolve_user_id(arguments: Dict[str, Any]) -> Optional[str]:
    """Resolve the acting user from explicit arguments or injected session."""
    session = arguments.get("_session", {})
    return arguments.get("user_id") or session.get("user_id")


def _auth_required_response() -> Dict[str, Any]:
    return {
        "success": False,
        "error": "Authentication required. Call auth.deviceLogin first to authenticate.",
        "hint": "Use the auth.deviceLogin tool to authenticate before accessing projects.",
    }


def _parse_project_role(role: str) -> ProjectRole:
    """Parse MCP-friendly project role names into the canonical enum."""
    role_aliases = {
        "admin": ProjectRole.MAINTAINER,
        "developer": ProjectRole.CONTRIBUTOR,
        "member": ProjectRole.CONTRIBUTOR,
    }
    normalized_role = role_aliases.get(role, role)
    return ProjectRole(normalized_role)


def _slugify_project_name(name: str) -> str:
    slug = name.strip().lower().replace(" ", "-").replace("_", "-")
    return re.sub(r"[^a-z0-9-]", "", slug) or "project"


async def _check_org_access(
    org_service: OrganizationService,
    org_id: str,
    user_id: str,
    require_admin: bool = False,
    arguments: Optional[Dict[str, Any]] = None,
) -> tuple[bool, Optional[str], Optional[MemberRole]]:
    """
    Check if user has access to the organization.

    Admin users (from session) bypass all access checks.

    Returns: (has_access, error_message, role)
    """
    # Admin users have full access
    if arguments and _is_admin_from_session(arguments):
        return True, None, MemberRole.OWNER

    membership = await _call(org_service.get_membership, org_id=org_id, user_id=user_id)
    if not membership:
        return False, "Access denied or organization not found", None

    if require_admin and membership.role not in [MemberRole.OWNER, MemberRole.ADMIN]:
        return False, "Access denied. Requires admin or owner role.", membership.role

    return True, None, membership.role


async def _check_project_access(
    project_service: OrganizationService,
    org_service: OrganizationService,
    project_id: str,
    user_id: str,
    require_write: bool = False,
    arguments: Optional[Dict[str, Any]] = None,
) -> tuple[bool, Optional[str], Optional[Project]]:
    """
    Check if user has access to the project.

    Admin users (from session) bypass all access checks.
    User-owned projects (no org_id) are accessible if owned by user.

    Returns: (has_access, error_message, project)
    """
    # Admin users have full access
    if arguments and _is_admin_from_session(arguments):
        project = await _call(project_service.get_project, project_id)
        if not project:
            return False, f"Project {project_id} not found", None
        return True, None, project

    project = await _call(project_service.get_project, project_id)
    if not project:
        return False, f"Project {project_id} not found", None

    # User-owned project - check ownership
    if project.org_id is None:
        owner_id = getattr(project, 'owner_id', None) or getattr(project, 'created_by', None)
        if owner_id == user_id:
            return True, None, project
        return False, "Access denied. You are not the owner of this project.", None

    # Org project - check org membership
    has_access, error, role = await _check_org_access(
        org_service,
        project.org_id,
        user_id,
        require_admin=require_write,
        arguments=arguments,
    )

    if not has_access:
        return False, error, None

    return True, None, project


# ==============================================================================
# Handler Functions - Project CRUD
# ==============================================================================


async def handle_create_project(
    project_service: OrganizationService,
    org_service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Create a new project. If org_id is provided, creates an organization project.
    If org_id is omitted, creates a user-owned project.

    MCP Tool: projects.create
    """
    user_id = _resolve_user_id(arguments)
    if not user_id:
        return _auth_required_response()

    org_id = arguments.get("org_id")  # Optional - None for user-owned projects
    name = arguments["name"]
    description = arguments.get("description")
    visibility = arguments.get("visibility", "private")
    settings = arguments.get("settings", {})
    metadata = arguments.get("metadata", {})
    slug = arguments.get("slug") or _slugify_project_name(name)

    # Parse visibility
    try:
        visibility_enum = ProjectVisibility(visibility)
    except ValueError:
        visibility_enum = ProjectVisibility.PRIVATE

    if org_id:
        # Org project: check user has admin access to org
        has_access, error, _ = await _check_org_access(
            org_service, org_id, user_id, require_admin=True, arguments=arguments
        )
        if not has_access:
            return {"success": False, "error": error}

    project = await _call(
        project_service.create_project,
        name=name,
        owner_id=user_id,
        slug=slug,
        org_id=org_id,
        description=description,
        visibility=visibility_enum,
        settings=settings,
    )

    return {
        "success": True,
        "project": _project_to_dict(project),
        "message": f"Project '{name}' created successfully",
    }


async def handle_get_project(
    project_service: OrganizationService,
    org_service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Get project details by ID.

    MCP Tool: projects.get
    """
    user_id = _resolve_user_id(arguments)
    if not user_id:
        return _auth_required_response()
    project_id = arguments["project_id"]

    has_access, error, project = await _check_project_access(
        project_service, org_service, project_id, user_id, arguments=arguments
    )
    if not has_access:
        return {"success": False, "error": error}

    return {
        "success": True,
        "project": _project_to_dict(project),
    }


async def handle_list_projects(
    project_service: OrganizationService,
    org_service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    List projects. If org_id is provided, lists projects in that org.
    If org_id is not provided, lists all projects the user has access to
    (user-owned projects + projects from orgs they belong to).

    MCP Tool: projects.list

    The user_id is automatically injected from the authenticated session context.
    If not authenticated, an error is returned.
    """
    user_id = _resolve_user_id(arguments)
    if not user_id:
        return _auth_required_response()

    org_id = arguments.get("org_id")  # Optional - if not provided, list all user's projects
    limit = arguments.get("limit", 50)
    offset = arguments.get("offset", 0)
    is_admin = _is_admin_from_session(arguments)

    all_projects = []

    if org_id:
        # List projects in specific org
        has_access, error, _ = await _check_org_access(org_service, org_id, user_id, arguments=arguments)
        if not has_access:
            return {"success": False, "error": error}

        all_projects = await _call(project_service.list_projects, owner_id=user_id, org_id=org_id)
    elif is_admin:
        # Admin: list ALL projects across all orgs and personal
        all_projects = await _call(project_service.list_projects, owner_id=user_id)
    else:
        # List all projects user has access to (personal + org memberships)
        all_projects = await _call(project_service.list_projects, owner_id=user_id)

    # Apply pagination
    total = len(all_projects)
    paginated_projects = all_projects[offset:offset + limit]

    return {
        "success": True,
        "projects": [_project_to_dict(p) for p in paginated_projects],
        "total": total,
        "org_id": org_id,  # None if listing all
        "limit": limit,
        "offset": offset,
    }


async def handle_update_project(
    project_service: OrganizationService,
    org_service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Update project settings.

    MCP Tool: projects.update
    """
    user_id = _resolve_user_id(arguments)
    if not user_id:
        return _auth_required_response()
    project_id = arguments["project_id"]

    # Check user has write access
    has_access, error, project = await _check_project_access(
        project_service, org_service, project_id, user_id, require_write=True, arguments=arguments
    )
    if not has_access:
        return {"success": False, "error": error}

    # Build update request
    update_request = UpdateProjectRequest(
        name=arguments.get("name"),
        description=arguments.get("description"),
        settings=arguments.get("settings"),
        metadata=arguments.get("metadata"),
    )

    updated_project = await _call(project_service.update_project, project_id, update_request)
    if not updated_project:
        return {
            "success": False,
            "error": f"Failed to update project {project_id}",
        }

    return {
        "success": True,
        "project": _project_to_dict(updated_project),
        "message": "Project updated successfully",
    }


async def handle_delete_project(
    project_service: OrganizationService,
    org_service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Delete a project (soft delete).

    MCP Tool: projects.delete
    """
    user_id = _resolve_user_id(arguments)
    if not user_id:
        return _auth_required_response()
    project_id = arguments["project_id"]

    # Check user has write access
    has_access, error, project = await _check_project_access(
        project_service, org_service, project_id, user_id, require_write=True, arguments=arguments
    )
    if not has_access:
        return {"success": False, "error": error}

    success = await _call(project_service.delete_project, project_id)
    if not success:
        return {
            "success": False,
            "error": f"Failed to delete project {project_id}",
        }

    return {
        "success": True,
        "project_id": project_id,
        "message": "Project deleted successfully",
    }


async def handle_archive_project(
    project_service: OrganizationService,
    org_service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Archive a project.

    MCP Tool: projects.archive
    """
    user_id = _resolve_user_id(arguments)
    if not user_id:
        return _auth_required_response()
    project_id = arguments["project_id"]

    # Check user has write access
    has_access, error, project = await _check_project_access(
        project_service, org_service, project_id, user_id, require_write=True, arguments=arguments
    )
    if not has_access:
        return {"success": False, "error": error}

    # Archive by updating settings
    current_settings = project.settings or {}
    current_settings["archived"] = True
    current_settings["archived_at"] = datetime.utcnow().isoformat()

    update_request = UpdateProjectRequest(settings=current_settings)
    updated_project = await _call(project_service.update_project, project_id, update_request)

    if not updated_project:
        return {
            "success": False,
            "error": f"Failed to archive project {project_id}",
        }

    return {
        "success": True,
        "project": _project_to_dict(updated_project),
        "message": "Project archived successfully",
    }


async def handle_restore_project(
    project_service: OrganizationService,
    org_service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Restore an archived project.

    MCP Tool: projects.restore
    """
    user_id = _resolve_user_id(arguments)
    if not user_id:
        return _auth_required_response()
    project_id = arguments["project_id"]

    # Check user has write access
    has_access, error, project = await _check_project_access(
        project_service, org_service, project_id, user_id, require_write=True, arguments=arguments
    )
    if not has_access:
        return {"success": False, "error": error}

    # Restore by removing archive flag from settings
    current_settings = project.settings or {}
    current_settings["archived"] = False
    current_settings["archived_at"] = None

    update_request = UpdateProjectRequest(settings=current_settings)
    updated_project = await _call(project_service.update_project, project_id, update_request)

    if not updated_project:
        return {
            "success": False,
            "error": f"Failed to restore project {project_id}",
        }

    return {
        "success": True,
        "project": _project_to_dict(updated_project),
        "message": "Project restored successfully",
    }


# ==============================================================================
# Handler Functions - Project Settings
# ==============================================================================


async def handle_get_settings(
    project_service: OrganizationService,
    org_service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Get project settings.

    MCP Tool: projects.getSettings
    """
    user_id = _resolve_user_id(arguments)
    if not user_id:
        return _auth_required_response()
    project_id = arguments["project_id"]

    has_access, error, project = await _check_project_access(
        project_service, org_service, project_id, user_id, arguments=arguments
    )
    if not has_access:
        return {"success": False, "error": error}

    return {
        "success": True,
        "project_id": project_id,
        "settings": project.settings or {},
    }


async def handle_update_settings(
    project_service: OrganizationService,
    org_service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Update project settings.

    MCP Tool: projects.updateSettings
    """
    user_id = _resolve_user_id(arguments)
    if not user_id:
        return _auth_required_response()
    project_id = arguments["project_id"]
    settings = arguments["settings"]
    merge = arguments.get("merge", True)

    # Check user has write access
    has_access, error, project = await _check_project_access(
        project_service, org_service, project_id, user_id, require_write=True, arguments=arguments
    )
    if not has_access:
        return {"success": False, "error": error}

    # Merge or replace settings
    if merge and project.settings:
        new_settings = {**project.settings, **settings}
    else:
        new_settings = settings

    update_request = UpdateProjectRequest(settings=new_settings)
    updated_project = await _call(project_service.update_project, project_id, update_request)

    if not updated_project:
        return {
            "success": False,
            "error": "Failed to update project settings",
        }

    return {
        "success": True,
        "project_id": project_id,
        "settings": updated_project.settings or {},
        "message": "Project settings updated successfully",
    }


# ==============================================================================
# Handler Functions - Project Stats
# ==============================================================================


async def handle_get_stats(
    project_service: OrganizationService,
    org_service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Get project statistics and usage.

    MCP Tool: projects.getStats
    """
    user_id = _resolve_user_id(arguments)
    if not user_id:
        return _auth_required_response()
    project_id = arguments["project_id"]

    has_access, error, project = await _check_project_access(
        project_service, org_service, project_id, user_id, arguments=arguments
    )
    if not has_access:
        return {"success": False, "error": error}

    # Get stats if method exists
    stats = {}
    if hasattr(project_service, 'get_project_stats'):
        stats = await _call(project_service.get_project_stats, project_id)

    return {
        "success": True,
        "project_id": project_id,
        "stats": _serialize_value(stats),
    }


async def handle_get_usage(
    project_service: OrganizationService,
    org_service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Get detailed project usage metrics.

    MCP Tool: projects.getUsage
    """
    user_id = _resolve_user_id(arguments)
    if not user_id:
        return _auth_required_response()
    project_id = arguments["project_id"]
    period = arguments.get("period", "30d")

    has_access, error, project = await _check_project_access(
        project_service, org_service, project_id, user_id, arguments=arguments
    )
    if not has_access:
        return {"success": False, "error": error}

    # Get usage if method exists
    usage = {}
    if hasattr(project_service, 'get_project_usage'):
        usage = await _call(project_service.get_project_usage, project_id, period=period)

    return {
        "success": True,
        "project_id": project_id,
        "period": period,
        "usage": _serialize_value(usage),
    }


# ==============================================================================
# Handler Functions - Project Context and Membership
# ==============================================================================


async def handle_switch_project(
    project_service: OrganizationService,
    org_service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """Switch the user's current project context after validating access."""
    user_id = _resolve_user_id(arguments)
    if not user_id:
        return _auth_required_response()
    project_id = arguments["project_id"]

    has_access, error, project = await _check_project_access(
        project_service, org_service, project_id, user_id, arguments=arguments
    )
    if not has_access:
        return {"success": False, "error": error}

    if hasattr(project_service, "set_user_current_project"):
        await _call(project_service.set_user_current_project, user_id=user_id, project_id=project_id)

    return {
        "success": True,
        "current_project": {
            "id": project.id,
            "name": project.name,
            "org_id": project.org_id,
        },
        "message": f"Switched to project '{project.name}'",
    }


async def handle_list_members(
    project_service: OrganizationService,
    org_service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """List project members after validating read access."""
    user_id = _resolve_user_id(arguments)
    if not user_id:
        return _auth_required_response()
    project_id = arguments["project_id"]
    role = arguments.get("role")
    limit = arguments.get("limit", 50)
    offset = arguments.get("offset", 0)

    has_access, error, _ = await _check_project_access(
        project_service, org_service, project_id, user_id, arguments=arguments
    )
    if not has_access:
        return {"success": False, "error": error}

    if hasattr(project_service, "list_project_members"):
        members = await _call(project_service.list_project_members, project_id)
    elif hasattr(project_service, "list_project_participants"):
        members = await _call(project_service.list_project_participants, project_id)
    else:
        return {"success": False, "error": "Project membership listing is not supported by this service."}

    if role:
        try:
            role_filter = _parse_project_role(role)
            members = [m for m in members if getattr(m, "role", None) == role_filter]
        except ValueError:
            members = []

    total = len(members)
    paginated_members = members[offset:offset + limit]
    return {
        "success": True,
        "members": [_serialize_value(m.model_dump() if hasattr(m, "model_dump") else m) for m in paginated_members],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


async def handle_add_member(
    project_service: OrganizationService,
    org_service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """Add a project member after validating write access."""
    user_id = _resolve_user_id(arguments)
    if not user_id:
        return _auth_required_response()
    project_id = arguments["project_id"]
    target_user_id = arguments["target_user_id"]
    role = arguments.get("role", "contributor")

    has_access, error, _ = await _check_project_access(
        project_service, org_service, project_id, user_id, require_write=True, arguments=arguments
    )
    if not has_access:
        return {"success": False, "error": error}

    if not hasattr(project_service, "add_project_member"):
        return {"success": False, "error": "Project member management is not supported by this service."}

    try:
        role_enum = _parse_project_role(role)
    except ValueError:
        return {"success": False, "error": f"Invalid project role: {role}"}

    membership = await _call(
        project_service.add_project_member,
        project_id=project_id,
        user_id=target_user_id,
        role=role_enum,
    )
    return {
        "success": True,
        "membership": _membership_to_dict(membership) if hasattr(membership, "model_dump") else _serialize_value(membership),
        "message": f"Project member added with role '{role_enum.value}'",
    }


async def handle_remove_member(
    project_service: OrganizationService,
    org_service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """Remove a project member after validating write access."""
    user_id = _resolve_user_id(arguments)
    if not user_id:
        return _auth_required_response()
    project_id = arguments["project_id"]
    target_user_id = arguments["target_user_id"]

    has_access, error, _ = await _check_project_access(
        project_service, org_service, project_id, user_id, require_write=True, arguments=arguments
    )
    if not has_access:
        return {"success": False, "error": error}

    if not hasattr(project_service, "remove_project_member"):
        return {"success": False, "error": "Project member management is not supported by this service."}

    success = await _call(project_service.remove_project_member, project_id=project_id, user_id=target_user_id)
    if not success:
        return {"success": False, "error": "Failed to remove project member."}
    return {
        "success": True,
        "removed_user_id": target_user_id,
        "message": "Project member removed successfully",
    }


async def handle_update_member_role(
    project_service: OrganizationService,
    org_service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """Update a project member role after validating write access."""
    user_id = _resolve_user_id(arguments)
    if not user_id:
        return _auth_required_response()
    project_id = arguments["project_id"]
    target_user_id = arguments["target_user_id"]
    role = arguments["role"]

    has_access, error, _ = await _check_project_access(
        project_service, org_service, project_id, user_id, require_write=True, arguments=arguments
    )
    if not has_access:
        return {"success": False, "error": error}

    if not hasattr(project_service, "update_project_member_role"):
        return {"success": False, "error": "Project member management is not supported by this service."}

    try:
        role_enum = _parse_project_role(role)
    except ValueError:
        return {"success": False, "error": f"Invalid project role: {role}"}

    membership = await _call(
        project_service.update_project_member_role,
        project_id=project_id,
        user_id=target_user_id,
        new_role=role_enum,
    )
    if not membership:
        return {"success": False, "error": "Failed to update project member role."}
    return {
        "success": True,
        "membership": _membership_to_dict(membership) if hasattr(membership, "model_dump") else _serialize_value(membership),
        "message": f"Project member role updated to '{role_enum.value}'",
    }


# ==============================================================================
# Handler Registry
# ==============================================================================


PROJECT_HANDLERS = {
    "projects.create": handle_create_project,
    "projects.get": handle_get_project,
    "projects.list": handle_list_projects,
    "projects.update": handle_update_project,
    "projects.delete": handle_delete_project,
    "projects.switch": handle_switch_project,
    "projects.archive": handle_archive_project,
    "projects.restore": handle_restore_project,
    "projects.getSettings": handle_get_settings,
    "projects.updateSettings": handle_update_settings,
    "projects.getStats": handle_get_stats,
    "projects.getUsage": handle_get_usage,
    "projects.listMembers": handle_list_members,
    "projects.addMember": handle_add_member,
    "projects.removeMember": handle_remove_member,
    "projects.updateMemberRole": handle_update_member_role,
}
