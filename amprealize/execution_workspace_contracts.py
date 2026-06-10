"""Execution workspace kind — where agent work runs (cloud vs local connector).

Canonical values are carried on ``ExecutionRequest.metadata["execution_workspace_kind"]``
and persisted on run metadata. The ExecutionGateway uses one state machine with
separate *drivers*: cloud paths delegate to mode executors; ``local_connector`` stages
a run lease for an outbound WebSocket client (daemon) scoped to the pairing user.

Pairing is user-scoped first; org-wide fleet devices are out of scope for this slice.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional


class ExecutionWorkspaceKind(str, Enum):
    """Backend workspace for a work-item execution."""

    CLOUD_GIT = "cloud_git"
    LOCAL_CONNECTOR = "local_connector"


class InvalidExecutionWorkspaceKindError(ValueError):
    """Raised when ``execution_workspace_kind`` is not a known enum value."""


def parse_execution_workspace_kind(raw: Optional[Any]) -> ExecutionWorkspaceKind:
    """Parse and validate ``execution_workspace_kind`` (default: cloud_git)."""
    if raw is None or raw == "":
        return ExecutionWorkspaceKind.CLOUD_GIT
    s = str(raw).strip().lower()
    if s == ExecutionWorkspaceKind.CLOUD_GIT.value:
        return ExecutionWorkspaceKind.CLOUD_GIT
    if s == ExecutionWorkspaceKind.LOCAL_CONNECTOR.value:
        return ExecutionWorkspaceKind.LOCAL_CONNECTOR
    raise InvalidExecutionWorkspaceKindError(
        f"Invalid execution_workspace_kind {raw!r}; "
        f"expected {ExecutionWorkspaceKind.CLOUD_GIT.value!r} or "
        f"{ExecutionWorkspaceKind.LOCAL_CONNECTOR.value!r}"
    )


def execution_workspace_kind_label(kind: ExecutionWorkspaceKind) -> str:
    return kind.value
