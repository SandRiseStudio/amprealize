"""MCP tool handlers for OrganizationService.

Provides handlers for organization, project, and membership management.
Following `behavior_prefer_mcp_tools` - MCP provides consistent schemas and automatic telemetry.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
# NOTE: Organization, OrgMembership, Invitation are Pydantic models - use .model_dump() not asdict()

from ...multi_tenant.organization_service import OrganizationService
from ...multi_tenant.contracts import (
    Organization,
    OrgMembership,
    OrgPlan,
    OrgStatus,
    MemberRole,
    Invitation,
    InvitationStatus,
    CreateOrgRequest,
    UpdateOrgRequest,
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


def _org_to_dict(org: Organization) -> Dict[str, Any]:
    """Convert Organization Pydantic model to dict with serialized timestamps."""
    result = org.model_dump()
    return {k: _serialize_value(v) for k, v in result.items()}


def _membership_to_dict(membership: OrgMembership) -> Dict[str, Any]:
    """Convert OrgMembership Pydantic model to dict with serialized timestamps."""
    result = membership.model_dump()
    return {k: _serialize_value(v) for k, v in result.items()}


def _invitation_to_dict(invitation: Invitation) -> Dict[str, Any]:
    """Convert Invitation Pydantic model to dict with serialized timestamps."""
    result = invitation.model_dump()
    return {k: _serialize_value(v) for k, v in result.items()}


# ==============================================================================
# Handler Functions - Organization CRUD
# ==============================================================================


async def handle_create_org(
    service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Create a new organization.

    MCP Tool: orgs.create
    """
    user_id = arguments["user_id"]
    name = arguments["name"]
    # Slug is required - auto-generate from name if not provided
    slug = arguments.get("slug") or name.lower().replace(" ", "-").replace("_", "-")
    # Ensure slug is URL-safe (only lowercase alphanumeric and hyphens)
    import re
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    display_name = arguments.get("display_name")
    plan = arguments.get("plan", "free")
    settings = arguments.get("settings", {})
    metadata = arguments.get("metadata", {})

    # Parse plan enum
    try:
        plan_enum = OrgPlan(plan)
    except ValueError:
        plan_enum = OrgPlan.FREE

    # Create request object
    request = CreateOrgRequest(
        name=name,
        slug=slug,
        display_name=display_name,
        plan=plan_enum,
        settings=settings,
        metadata=metadata,
    )

    org = await service.create_organization(
        request=request,
        owner_id=user_id,
    )

    return {
        "success": True,
        "organization": _org_to_dict(org),
        "message": f"Organization '{name}' created successfully",
    }


async def handle_get_org(
    service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Get organization details by ID.

    MCP Tool: orgs.get
    """
    org_id = arguments["org_id"]
    user_id = arguments["user_id"]

    # Check user has access to this org
    membership = await service.get_membership(org_id=org_id, user_id=user_id)
    if not membership:
        return {
            "success": False,
            "error": "Access denied or organization not found",
        }

    org = await service.get_organization(org_id)
    if not org:
        return {
            "success": False,
            "error": f"Organization {org_id} not found",
        }

    return {
        "success": True,
        "organization": _org_to_dict(org),
    }


async def handle_list_orgs(
    service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    List organizations the user belongs to.

    MCP Tool: orgs.list

    The user_id is automatically injected from the authenticated session context.
    If not authenticated, an error is returned.
    """
    user_id = arguments.get("user_id")
    if not user_id:
        return {
            "success": False,
            "error": "Authentication required. Call auth.deviceLogin first to authenticate.",
            "hint": "Use the auth.deviceLogin tool to authenticate before accessing organizations.",
        }

    role = arguments.get("role")
    limit = arguments.get("limit", 50)
    offset = arguments.get("offset", 0)

    # Parse role filter if provided
    role_filter = None
    if role:
        try:
            role_filter = MemberRole(role)
        except ValueError:
            pass

    orgs = await service.list_user_organizations(user_id=user_id)

    # Apply role filter if specified
    if role_filter:
        # Filter orgs where user has the specified role
        filtered_orgs = []
        for org in orgs:
            membership = await service.get_membership(org_id=org.id, user_id=user_id)
            if membership and membership.role == role_filter:
                filtered_orgs.append(org)
        orgs = filtered_orgs

    # Apply pagination
    orgs = orgs[offset:offset + limit]

    return {
        "success": True,
        "organizations": [_org_to_dict(org) for org in orgs],
        "total": len(orgs),
        "limit": limit,
        "offset": offset,
    }


async def handle_update_org(
    service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Update organization settings.

    MCP Tool: orgs.update
    """
    user_id = arguments["user_id"]
    org_id = arguments["org_id"]

    # Check user has admin access
    membership = await service.get_membership(org_id=org_id, user_id=user_id)
    if not membership or membership.role not in [MemberRole.OWNER, MemberRole.ADMIN]:
        return {
            "success": False,
            "error": "Access denied. Requires admin or owner role.",
        }

    # Build update request
    update_request = UpdateOrgRequest(
        name=arguments.get("name"),
        display_name=arguments.get("display_name"),
        settings=arguments.get("settings"),
        metadata=arguments.get("metadata"),
    )

    org = await service.update_organization(org_id, update_request)
    if not org:
        return {
            "success": False,
            "error": f"Failed to update organization {org_id}",
        }

    return {
        "success": True,
        "organization": _org_to_dict(org),
        "message": "Organization updated successfully",
    }


async def handle_delete_org(
    service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Soft-delete an organization.

    MCP Tool: orgs.delete
    """
    user_id = arguments["user_id"]
    org_id = arguments["org_id"]

    # Check user is owner
    membership = await service.get_membership(org_id=org_id, user_id=user_id)
    if not membership or membership.role != MemberRole.OWNER:
        return {
            "success": False,
            "error": "Access denied. Only the owner can delete an organization.",
        }

    success = await service.delete_organization(org_id)
    if not success:
        return {
            "success": False,
            "error": f"Failed to delete organization {org_id}",
        }

    return {
        "success": True,
        "org_id": org_id,
        "message": "Organization deleted successfully",
    }


async def handle_switch_org(
    service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Switch user's current organization context.

    MCP Tool: orgs.switch
    """
    user_id = arguments["user_id"]
    org_id = arguments["org_id"]

    # Verify user has access to this org
    membership = await service.get_membership(org_id=org_id, user_id=user_id)
    if not membership:
        return {
            "success": False,
            "error": "Access denied or organization not found",
        }

    org = await service.get_organization(org_id)
    if not org:
        return {
            "success": False,
            "error": f"Organization {org_id} not found",
        }

    # Set as current org in user preferences (if method exists)
    if hasattr(service, 'set_user_current_org'):
        await service.set_user_current_org(user_id=user_id, org_id=org_id)

    return {
        "success": True,
        "current_org": {
            "id": org.id,
            "name": org.name,
            "slug": org.slug,
            "role": membership.role.value if hasattr(membership.role, 'value') else membership.role,
        },
        "message": f"Switched to organization '{org.name}'",
    }


async def handle_get_context(
    service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Get user's context within an organization.

    MCP Tool: orgs.getContext
    """
    user_id = arguments["user_id"]
    org_id = arguments["org_id"]

    membership = await service.get_membership(org_id=org_id, user_id=user_id)
    if not membership:
        return {
            "success": False,
            "error": "User is not a member of this organization",
        }

    org = await service.get_organization(org_id)
    if not org:
        return {
            "success": False,
            "error": f"Organization {org_id} not found",
        }

    return {
        "success": True,
        "context": {
            "org_id": org_id,
            "user_id": user_id,
            "role": membership.role.value if hasattr(membership.role, 'value') else membership.role,
            "plan": org.plan.value if hasattr(org.plan, 'value') else org.plan,
            "settings": org.settings or {},
        },
    }


# ==============================================================================
# Handler Functions - Membership Management
# ==============================================================================


async def handle_list_members(
    service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    List organization members.

    MCP Tool: orgs.members
    """
    user_id = arguments["user_id"]
    org_id = arguments["org_id"]
    role = arguments.get("role")
    limit = arguments.get("limit", 50)
    offset = arguments.get("offset", 0)

    # Check user has access to this org
    membership = await service.get_membership(org_id=org_id, user_id=user_id)
    if not membership:
        return {
            "success": False,
            "error": "Access denied or organization not found",
        }

    # Parse role filter if provided
    role_filter = None
    if role:
        try:
            role_filter = MemberRole(role)
        except ValueError:
            pass

    members = await service.list_memberships(org_id=org_id)

    # Apply role filter if specified
    if role_filter:
        members = [m for m in members if m.role == role_filter]

    # Apply pagination
    total = len(members)
    members = members[offset:offset + limit]

    return {
        "success": True,
        "members": [_membership_to_dict(m) for m in members],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


async def handle_add_member(
    service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Add a member to an organization.

    MCP Tool: orgs.addMember
    """
    user_id = arguments["user_id"]
    org_id = arguments["org_id"]
    target_user_id = arguments["target_user_id"]
    role = arguments.get("role", "member")

    # Check user has admin access
    membership = await service.get_membership(org_id=org_id, user_id=user_id)
    if not membership or membership.role not in [MemberRole.OWNER, MemberRole.ADMIN]:
        return {
            "success": False,
            "error": "Access denied. Requires admin or owner role.",
        }

    # Parse role
    try:
        role_enum = MemberRole(role)
    except ValueError:
        role_enum = MemberRole.MEMBER

    new_membership = await service.add_member(
        org_id=org_id,
        user_id=target_user_id,
        role=role_enum,
    )

    if not new_membership:
        return {
            "success": False,
            "error": "Failed to add member. User may already be a member.",
        }

    return {
        "success": True,
        "membership": _membership_to_dict(new_membership),
        "message": f"Member added successfully with role '{role}'",
    }


async def handle_remove_member(
    service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Remove a member from an organization.

    MCP Tool: orgs.removeMember
    """
    user_id = arguments["user_id"]
    org_id = arguments["org_id"]
    target_user_id = arguments["target_user_id"]

    # Check user has admin access
    membership = await service.get_membership(org_id=org_id, user_id=user_id)
    if not membership or membership.role not in [MemberRole.OWNER, MemberRole.ADMIN]:
        return {
            "success": False,
            "error": "Access denied. Requires admin or owner role.",
        }

    # Cannot remove owner
    target_membership = await service.get_membership(org_id=org_id, user_id=target_user_id)
    if target_membership and target_membership.role == MemberRole.OWNER:
        return {
            "success": False,
            "error": "Cannot remove the organization owner.",
        }

    success = await service.remove_member(org_id=org_id, user_id=target_user_id)
    if not success:
        return {
            "success": False,
            "error": "Failed to remove member.",
        }

    return {
        "success": True,
        "removed_user_id": target_user_id,
        "message": "Member removed successfully",
    }


async def handle_update_member_role(
    service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Update a member's role.

    MCP Tool: orgs.updateMemberRole
    """
    user_id = arguments["user_id"]
    org_id = arguments["org_id"]
    target_user_id = arguments["target_user_id"]
    role = arguments["role"]

    # Check user has admin access
    membership = await service.get_membership(org_id=org_id, user_id=user_id)
    if not membership or membership.role not in [MemberRole.OWNER, MemberRole.ADMIN]:
        return {
            "success": False,
            "error": "Access denied. Requires admin or owner role.",
        }

    # Parse role
    try:
        role_enum = MemberRole(role)
    except ValueError:
        return {
            "success": False,
            "error": f"Invalid role: {role}",
        }

    # Only owner can transfer ownership
    if role_enum == MemberRole.OWNER and membership.role != MemberRole.OWNER:
        return {
            "success": False,
            "error": "Only the current owner can transfer ownership.",
        }

    updated = await service.update_member_role(
        org_id=org_id,
        user_id=target_user_id,
        role=role_enum,
    )

    if not updated:
        return {
            "success": False,
            "error": "Failed to update member role.",
        }

    return {
        "success": True,
        "membership": _membership_to_dict(updated),
        "message": f"Member role updated to '{role}'",
    }


# ==============================================================================
# Handler Functions - Invitations
# ==============================================================================


async def handle_invite_member(
    service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Send an invitation to join an organization.

    MCP Tool: orgs.invite
    """
    user_id = arguments["user_id"]
    org_id = arguments["org_id"]
    email = arguments["email"]
    role = arguments.get("role", "member")

    # Check user has admin access
    membership = await service.get_membership(org_id=org_id, user_id=user_id)
    if not membership or membership.role not in [MemberRole.OWNER, MemberRole.ADMIN]:
        return {
            "success": False,
            "error": "Access denied. Requires admin or owner role.",
        }

    # Parse role
    try:
        role_enum = MemberRole(role)
    except ValueError:
        role_enum = MemberRole.MEMBER

    invitation = await service.create_invitation(
        org_id=org_id,
        email=email,
        role=role_enum,
        invited_by=user_id,
    )

    if not invitation:
        return {
            "success": False,
            "error": "Failed to create invitation. Email may already be invited.",
        }

    return {
        "success": True,
        "invitation": _invitation_to_dict(invitation),
        "message": f"Invitation sent to {email}",
    }


async def handle_accept_invitation(
    service: OrganizationService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Accept an organization invitation.

    MCP Tool: orgs.acceptInvitation
    """
    user_id = arguments["user_id"]
    token = arguments["token"]

    result = await service.accept_invitation(
        token=token,
        user_id=user_id,
    )

    if not result:
        return {
            "success": False,
            "error": "Invalid or expired invitation token.",
        }

    membership, org = result

    return {
        "success": True,
        "membership": _membership_to_dict(membership),
        "organization": {
            "id": org.id,
            "name": org.name,
            "slug": org.slug,
        },
        "message": f"Welcome to {org.name}!",
    }


# ==============================================================================
# Handler Registry
# ==============================================================================


ORG_HANDLERS = {
    "orgs.create": handle_create_org,
    "orgs.get": handle_get_org,
    "orgs.list": handle_list_orgs,
    "orgs.update": handle_update_org,
    "orgs.delete": handle_delete_org,
    "orgs.switch": handle_switch_org,
    "orgs.getContext": handle_get_context,
    "orgs.members": handle_list_members,
    "orgs.addMember": handle_add_member,
    "orgs.removeMember": handle_remove_member,
    "orgs.updateMemberRole": handle_update_member_role,
    "orgs.invite": handle_invite_member,
    "orgs.acceptInvitation": handle_accept_invitation,
}
