"""Data models for workspace-agent.

These are standalone Pydantic models with no amprealize dependencies.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class WorkspaceStatus(str, Enum):
    """Status of an agent workspace."""
    PENDING = "pending"              # Requested, not yet provisioned
    PROVISIONING = "provisioning"    # Container starting
    CLONING = "cloning"              # Git clone in progress
    READY = "ready"                  # Workspace ready for agent use
    EXECUTING = "executing"          # Agent actively using workspace
    CLEANUP_PENDING = "cleanup_pending"  # Marked for cleanup
    DESTROYED = "destroyed"          # Cleaned up


class CleanupPolicy(str, Enum):
    """When to clean up workspace."""
    IMMEDIATE = "immediate"          # Delete right away
    TTL = "ttl"                      # Keep for TTL hours
    RETAIN = "retain"                # Don't auto-cleanup


class WorkspaceConfig(BaseModel):
    """Configuration for provisioning an agent workspace."""

    run_id: str = Field(..., description="Unique identifier for this run")
    project_id: str = Field(..., description="Project this workspace belongs to")
    github_repo: str = Field(..., description="GitHub repo in owner/repo format")
    github_token: str = Field(..., description="Token for repo access")
    github_branch: Optional[str] = Field(None, description="Branch to clone (default: default branch)")
    workspace_path: str = Field("/workspace/repo", description="Path inside container for repo")
    ttl_hours: int = Field(24, description="Hours to keep on failure")
    memory_limit: str = Field("2g", description="Container memory limit")
    cpu_limit: str = Field("2.0", description="Container CPU limit")
    image: str = Field(
        "docker.io/library/python:3.11-slim",
        description="Container image to use",
    )
    labels: Dict[str, str] = Field(default_factory=dict, description="Additional container labels")

    class Config:
        extra = "forbid"


class WorkspaceInfo(BaseModel):
    """Information about a provisioned workspace."""

    run_id: str = Field(..., description="Run ID this workspace belongs to")
    container_id: Optional[str] = Field(None, description="Container ID (short)")
    container_name: Optional[str] = Field(None, description="Container name for exec")
    status: WorkspaceStatus = Field(WorkspaceStatus.PENDING, description="Current status")
    workspace_path: str = Field("/workspace/repo", description="Path to repo inside container")
    host_workspace_path: Optional[str] = Field(None, description="Path on host (for volume access)")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO8601 creation timestamp",
    )
    ready_at: Optional[str] = Field(None, description="ISO8601 timestamp when ready")
    error: Optional[str] = Field(None, description="Error message if failed")
    cleanup_policy: CleanupPolicy = Field(CleanupPolicy.IMMEDIATE, description="Cleanup policy")
    cleanup_at: Optional[str] = Field(None, description="When TTL cleanup should occur")
    project_id: Optional[str] = Field(None, description="Project ID")

    class Config:
        extra = "allow"  # Allow internal fields like _socket_client

    def to_redis_dict(self) -> Dict[str, Any]:
        """Convert to dict for Redis storage."""
        return {
            "run_id": self.run_id,
            "container_id": self.container_id,
            "container_name": self.container_name,
            "status": self.status.value,
            "workspace_path": self.workspace_path,
            "host_workspace_path": self.host_workspace_path,
            "created_at": self.created_at,
            "ready_at": self.ready_at,
            "error": self.error,
            "cleanup_policy": self.cleanup_policy.value,
            "cleanup_at": self.cleanup_at,
            "project_id": self.project_id,
        }

    @classmethod
    def from_redis_dict(cls, data: Dict[str, Any]) -> "WorkspaceInfo":
        """Create from Redis dict."""
        return cls(
            run_id=data["run_id"],
            container_id=data.get("container_id"),
            container_name=data.get("container_name"),
            status=WorkspaceStatus(data.get("status", "pending")),
            workspace_path=data.get("workspace_path", "/workspace/repo"),
            host_workspace_path=data.get("host_workspace_path"),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            ready_at=data.get("ready_at"),
            error=data.get("error"),
            cleanup_policy=CleanupPolicy(data.get("cleanup_policy", "immediate")),
            cleanup_at=data.get("cleanup_at"),
            project_id=data.get("project_id"),
        )


class ExecResult(BaseModel):
    """Result of executing a command in a workspace."""

    output: str = Field(..., description="Command output (stdout + stderr)")
    exit_code: int = Field(..., description="Command exit code")
    timed_out: bool = Field(False, description="Whether command timed out")


class WorkspaceStats(BaseModel):
    """Statistics about workspace service."""

    total_workspaces: int = Field(0, description="Total workspaces in state")
    active_workspaces: int = Field(0, description="Workspaces in READY/EXECUTING status")
    pending_cleanup: int = Field(0, description="Workspaces pending cleanup")
    containers_running: int = Field(0, description="Actual running containers")
    podman_available: bool = Field(False, description="Whether podman socket is available")


class HealthStatus(BaseModel):
    """Health check response."""

    healthy: bool = Field(..., description="Whether service is healthy")
    podman_connected: bool = Field(False, description="Podman socket connection status")
    redis_connected: bool = Field(False, description="Redis connection status")
    uptime_seconds: float = Field(0, description="Service uptime in seconds")
    version: str = Field("0.1.0", description="Service version")


# Error classes

class WorkspaceError(Exception):
    """Base class for workspace errors."""

    def __init__(self, run_id: str, message: str) -> None:
        self.run_id = run_id
        self.message = message
        super().__init__(f"[{run_id}] {message}")


class WorkspaceNotFoundError(WorkspaceError):
    """Raised when workspace doesn't exist."""

    def __init__(self, run_id: str) -> None:
        super().__init__(run_id, "Workspace not found")


class WorkspaceProvisionError(WorkspaceError):
    """Raised when workspace provisioning fails."""
    pass


class WorkspaceExecError(WorkspaceError):
    """Raised when command execution fails."""
    pass
