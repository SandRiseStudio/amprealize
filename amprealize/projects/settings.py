"""Execution mode and surface constants for work-item processing.

These are core OSS definitions used by work_item_execution_service
to determine how tasks execute (local vs remote).
"""

from enum import Enum


class ExecutionMode(str, Enum):
    """Execution mode for work item processing."""
    LOCAL = "local"
    GITHUB_PR = "github_pr"
    LOCAL_AND_PR = "local_and_pr"


# Surfaces that support local file operations
LOCAL_CAPABLE_SURFACES = frozenset({"cli", "vscode", "mcp", "codespaces", "gitpod"})

# Surfaces that do NOT support local file operations
REMOTE_ONLY_SURFACES = frozenset({"web", "api"})

__all__ = [
    "ExecutionMode",
    "LOCAL_CAPABLE_SURFACES",
    "REMOTE_ONLY_SURFACES",
]
