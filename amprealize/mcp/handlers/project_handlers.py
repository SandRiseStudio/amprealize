"""MCP tool handlers for ProjectService.

Provides handlers for project management within organizations.
Following `behavior_prefer_mcp_tools` - MCP provides consistent schemas and automatic telemetry.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from ...multi_tenant.organization_service import OrganizationService
from ...multi_tenant.contracts import (
    Project,
    ProjectVisibility,
    MemberRole,
    CreateProjectRequest,
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


# ==============================================================================
# Authorization Helpers
# ==============================================================================


def _is_admin_from_session(arguments: Dict[str, Any]) -> bool:
    """Check if the session indicates admin status."""
    session = arguments.get("_session", {})
    return session.get("is_admin", False)


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

    membership = await org_service.get_membership(org_id=org_id, user_id=user_id)
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
        project = await project_service.get_project(project_id)
        if not project:
            return False, f"Project {project_id} not found", None
        return True, None, project

    project = await project_service.get_project(project_id)
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
    user_id = arguments.get("user_id")
    if not user_id:
        return {
            "success": False,
            "error": "Authentication required. Call auth.deviceLogin first to authenticate.",
            "hint": "Use the auth.deviceLogin tool to authenticate before creating projects.",
        }

    org_id = arguments.get("org_id")  # Optional - None for user-owned projects
    name = arguments["name"]
    description = arguments.get("description")
    visibility = arguments.get("visibility", "private")
    settings = arguments.get("settings", {})
    metadata = arguments.get("metadata", {})

    # Parse visibility
    try:
        visibility_enum = ProjectVisibility(visibility)
    except ValueError:
        visibility_enum = ProjectVisibility.PRIVATE

    if org_id:
        # Org project: check user has admin access to org
        has_access, error, _ = await _check_org_access(
            org_service, org_id, user_id, require_admin=True
        )
        if not has_access:
            return {"success": False, "error": error}

    project = await project_service.create_project(
        name=name,
        owner_id=user_id,
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
    user_id = arguments["user_id"]
    project_id = arguments["project_id"]

    has_access, error, project = await _check_project_access(
        project_service, org_service, project_id, user_id
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
    user_id = arguments.get("user_id")
    if not user_id:
        return {
            "success": False,
            "error": "Authentication required. Call auth.deviceLogin first to authenticate.",
            "hint": "Use the auth.deviceLogin tool to authenticate before accessing projects.",
        }

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

        all_projects = await project_service.list_projects(org_id=org_id)
    elif is_admin:
        # Admin: list ALL projects across all orgs and personal
        all_projects = await project_service.list_projects()
    else:
        # List all projects user has access to (personal + org memberships)
        all_projects = await project_service.list_projects(owner_id=user_id)

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
    user_id = arguments["user_id"]
    project_id = arguments["project_id"]

    # Check user has write access
    has_access, error, project = await _check_project_access(
        project_service, org_service, project_id, user_id, require_write=True
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

    updated_project = await project_service.update_project(project_id, update_request)
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
    user_id = arguments["user_id"]
    project_id = arguments["project_id"]

    # Check user has write access
    has_access, error, project = await _check_project_access(
        project_service, org_service, project_id, user_id, require_write=True
    )
    if not has_access:
        return {"success": False, "error": error}

    success = await project_service.delete_project(project_id)
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
    user_id = arguments["user_id"]
    project_id = arguments["project_id"]

    # Check user has write access
    has_access, error, project = await _check_project_access(
        project_service, org_service, project_id, user_id, require_write=True
    )
    if not has_access:
        return {"success": False, "error": error}

    # Archive by updating settings
    current_settings = project.settings or {}
    current_settings["archived"] = True
    current_settings["archived_at"] = datetime.utcnow().isoformat()

    update_request = UpdateProjectRequest(settings=current_settings)
    updated_project = await project_service.update_project(project_id, update_request)

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
    user_id = arguments["user_id"]
    project_id = arguments["project_id"]

    # Check user has write access
    has_access, error, project = await _check_project_access(
        project_service, org_service, project_id, user_id, require_write=True
    )
    if not has_access:
        return {"success": False, "error": error}

    # Restore by removing archive flag from settings
    current_settings = project.settings or {}
    current_settings["archived"] = False
    current_settings["archived_at"] = None

    update_request = UpdateProjectRequest(settings=current_settings)
    updated_project = await project_service.update_project(project_id, update_request)

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
    user_id = arguments["user_id"]
    project_id = arguments["project_id"]

    has_access, error, project = await _check_project_access(
        project_service, org_service, project_id, user_id
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
    user_id = arguments["user_id"]
    project_id = arguments["project_id"]
    settings = arguments["settings"]
    merge = arguments.get("merge", True)

    # Check user has write access
    has_access, error, project = await _check_project_access(
        project_service, org_service, project_id, user_id, require_write=True
    )
    if not has_access:
        return {"success": False, "error": error}

    # Merge or replace settings
    if merge and project.settings:
        new_settings = {**project.settings, **settings}
    else:
        new_settings = settings

    update_request = UpdateProjectRequest(settings=new_settings)
    updated_project = await project_service.update_project(project_id, update_request)

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
    user_id = arguments["user_id"]
    project_id = arguments["project_id"]

    has_access, error, project = await _check_project_access(
        project_service, org_service, project_id, user_id
    )
    if not has_access:
        return {"success": False, "error": error}

    # Get stats if method exists
    stats = {}
    if hasattr(project_service, 'get_project_stats'):
        stats = await project_service.get_project_stats(project_id)

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
    user_id = arguments["user_id"]
    project_id = arguments["project_id"]
    period = arguments.get("period", "30d")

    has_access, error, project = await _check_project_access(
        project_service, org_service, project_id, user_id
    )
    if not has_access:
        return {"success": False, "error": error}

    # Get usage if method exists
    usage = {}
    if hasattr(project_service, 'get_project_usage'):
        usage = await project_service.get_project_usage(project_id, period=period)

    return {
        "success": True,
        "project_id": project_id,
        "period": period,
        "usage": _serialize_value(usage),
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
    "projects.archive": handle_archive_project,
    "projects.restore": handle_restore_project,
    "projects.getSettings": handle_get_settings,
    "projects.updateSettings": handle_update_settings,
    "projects.getStats": handle_get_stats,
    "projects.getUsage": handle_get_usage,
}
