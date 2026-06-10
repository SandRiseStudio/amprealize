"""Tests for execution_workspace_kind parsing and validation."""

import pytest

from amprealize.execution_workspace_contracts import (
    ExecutionWorkspaceKind,
    InvalidExecutionWorkspaceKindError,
    parse_execution_workspace_kind,
)

pytestmark = pytest.mark.unit


def test_parse_defaults_to_cloud_git():
    assert parse_execution_workspace_kind(None) == ExecutionWorkspaceKind.CLOUD_GIT
    assert parse_execution_workspace_kind("") == ExecutionWorkspaceKind.CLOUD_GIT


def test_parse_accepts_enums_case_insensitive():
    assert parse_execution_workspace_kind("CLOUD_GIT") == ExecutionWorkspaceKind.CLOUD_GIT
    assert parse_execution_workspace_kind("Local_Connector") == ExecutionWorkspaceKind.LOCAL_CONNECTOR


def test_parse_rejects_unknown():
    with pytest.raises(InvalidExecutionWorkspaceKindError):
        parse_execution_workspace_kind("on_prem_git")
