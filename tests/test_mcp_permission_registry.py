"""Unit tests for ``mcp_permission_registry`` (guideai-1183)."""

import pytest

pytestmark = pytest.mark.unit

from amprealize.mcp_permission_registry import (
    MCP_TOOL_RBAC_REGISTRY,
    mcp_tool_rbac_requirement,
)
from amprealize.tenant.permissions import OrgPermission, ProjectPermission


def test_mcp_tool_rbac_requirement_known_mutations():
    assert mcp_tool_rbac_requirement("workItems.create") is not None
    req = mcp_tool_rbac_requirement("workItems.create")
    assert req is not None
    assert req.project_permission == ProjectPermission.CREATE_WORK_ITEMS
    assert req.org_permission is None


def test_mcp_tool_rbac_requirement_org_scoped():
    req = mcp_tool_rbac_requirement("projects.create")
    assert req is not None
    assert req.org_permission == OrgPermission.CREATE_PROJECTS


def test_mcp_tool_rbac_requirement_unknown_tool():
    assert mcp_tool_rbac_requirement("nonexistent.tool") is None


def test_registry_non_empty():
    assert len(MCP_TOOL_RBAC_REGISTRY) >= 10
