"""MCP tool → RBAC requirement registry for server-side permission checks.

Maps internal MCP tool names (manifest / handler keys, e.g. ``workItems.create``)
to optional organization- and project-level permissions enforced when
``AsyncPermissionService`` is available (see ``MCPServiceRegistry.permission_service``).

Tools omitted from this map rely on OAuth scopes, session context, and handler-level
checks only. Following ``behavior_lock_down_security_surface`` (Student).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Final, Optional

try:
    from .tenant.permissions import OrgPermission, ProjectPermission
except ImportError:  # tenant/ is OSS-only; enterprise uses multi_tenant
    from .multi_tenant.permissions import OrgPermission, ProjectPermission


@dataclass(frozen=True)
class MCPToolRBACRequirement:
    """RBAC requirement for a single MCP tool."""

    org_permission: Optional[OrgPermission] = None
    project_permission: Optional[ProjectPermission] = None


def _req(
    org: Optional[OrgPermission] = None,
    project: Optional[ProjectPermission] = None,
) -> MCPToolRBACRequirement:
    return MCPToolRBACRequirement(org_permission=org, project_permission=project)


# Internal tool names must match handler registries / manifests after denormalization
# (``_denormalize_tool_name``), e.g. ``workItems.create`` not ``workitems_create``.
MCP_TOOL_RBAC_REGISTRY: Final[Dict[str, MCPToolRBACRequirement]] = {
    # Organizations
    "orgs.update": _req(OrgPermission.UPDATE_SETTINGS),
    "orgs.delete": _req(OrgPermission.DELETE_ORG),
    "orgs.addMember": _req(OrgPermission.INVITE_MEMBERS),
    "orgs.removeMember": _req(OrgPermission.REMOVE_MEMBERS),
    "orgs.updateMemberRole": _req(OrgPermission.UPDATE_MEMBER_ROLES),
    "orgs.invite": _req(OrgPermission.INVITE_MEMBERS),
    # Projects (org-scoped create/delete; project-scoped mutations)
    "projects.create": _req(OrgPermission.CREATE_PROJECTS),
    "projects.delete": _req(project=ProjectPermission.DELETE_PROJECT),
    "projects.update": _req(project=ProjectPermission.UPDATE_SETTINGS),
    "projects.archive": _req(project=ProjectPermission.ARCHIVE_PROJECT),
    "projects.restore": _req(project=ProjectPermission.ARCHIVE_PROJECT),
    "projects.updateSettings": _req(project=ProjectPermission.UPDATE_SETTINGS),
    "projects.addMember": _req(project=ProjectPermission.INVITE_MEMBERS),
    "projects.removeMember": _req(project=ProjectPermission.REMOVE_MEMBERS),
    "projects.updateMemberRole": _req(project=ProjectPermission.UPDATE_MEMBER_ROLES),
    # Boards & work items
    "boards.create": _req(project=ProjectPermission.CREATE_BOARDS),
    "boards.update": _req(project=ProjectPermission.UPDATE_BOARDS),
    "boards.delete": _req(project=ProjectPermission.DELETE_BOARDS),
    "board.createLabel": _req(project=ProjectPermission.UPDATE_BOARDS),
    "board.updateLabel": _req(project=ProjectPermission.UPDATE_BOARDS),
    "board.deleteLabel": _req(project=ProjectPermission.UPDATE_BOARDS),
    "workItems.create": _req(project=ProjectPermission.CREATE_WORK_ITEMS),
    "workItems.update": _req(project=ProjectPermission.UPDATE_WORK_ITEMS),
    "workItems.delete": _req(project=ProjectPermission.DELETE_WORK_ITEMS),
    "workItems.move": _req(project=ProjectPermission.UPDATE_WORK_ITEMS),
    "workItems.postComment": _req(project=ProjectPermission.UPDATE_WORK_ITEMS),
    "workItems.moveToColumn": _req(project=ProjectPermission.UPDATE_WORK_ITEMS),
    "workItems.execute": _req(project=ProjectPermission.UPDATE_WORK_ITEMS),
    "workItems.cancelExecution": _req(project=ProjectPermission.CANCEL_RUNS),
    "columns.create": _req(project=ProjectPermission.MANAGE_COLUMNS),
    # Runs
    "runs.create": _req(project=ProjectPermission.CREATE_RUNS),
    "runs.cancel": _req(project=ProjectPermission.CANCEL_RUNS),
    "runs.delete": _req(project=ProjectPermission.DELETE_RUNS),
    # Observability trace warehouse reads (parity with POST /api/v1/observability/traces/*)
    "traces.runs": _req(project=ProjectPermission.VIEW_RUNS),
    "traces.conversations": _req(project=ProjectPermission.VIEW_RUNS),
    "traces.spans": _req(project=ProjectPermission.VIEW_RUNS),
    # Behaviors (project-scoped authoring)
    "behaviors.create": _req(project=ProjectPermission.CREATE_BEHAVIORS),
    "behaviors.update": _req(project=ProjectPermission.UPDATE_BEHAVIORS),
    "behaviors.propose": _req(project=ProjectPermission.UPDATE_BEHAVIORS),
    "behaviors.submit": _req(project=ProjectPermission.UPDATE_BEHAVIORS),
    "behaviors.approve": _req(project=ProjectPermission.UPDATE_BEHAVIORS),
    "behaviors.deprecate": _req(project=ProjectPermission.UPDATE_BEHAVIORS),
    "behaviors.deleteDraft": _req(project=ProjectPermission.DELETE_BEHAVIORS),
}


def mcp_tool_rbac_requirement(tool_name: str) -> Optional[MCPToolRBACRequirement]:
    """Return RBAC requirement for ``tool_name``, or ``None`` if not registered."""
    return MCP_TOOL_RBAC_REGISTRY.get(tool_name)
