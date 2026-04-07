"""workspace-agent: Standalone workspace management for isolated agent execution.

This package provides:
- PodmanSocketClient: Low-level podman socket communication
- WorkspaceService: Core workspace management logic
- StateStore: Pluggable state backends (in-memory, Redis)

Note: gRPC server removed in favor of AmpOrchestrator (2026-01-16).
For production use, see breakeramp.orchestrator.AmpOrchestrator.

Example:
    from workspace_agent import WorkspaceService, WorkspaceConfig

    service = WorkspaceService()
    info = await service.provision(WorkspaceConfig(
        run_id="run-123",
        project_id="proj-abc",
        github_repo="owner/repo",
        github_token="ghp_xxx",
    ))

    output, exit_code = await service.exec("run-123", "ls -la")
    await service.cleanup("run-123", success=True)
"""

from workspace_agent.models import (
    CleanupPolicy,
    WorkspaceConfig,
    WorkspaceInfo,
    WorkspaceStatus,
)
from workspace_agent.podman_client import PodmanSocketClient, discover_podman_socket
from workspace_agent.service import WorkspaceService

__version__ = "0.1.0"

__all__ = [
    # Models
    "CleanupPolicy",
    "WorkspaceConfig",
    "WorkspaceInfo",
    "WorkspaceStatus",
    # Podman
    "PodmanSocketClient",
    "discover_podman_socket",
    # Service
    "WorkspaceService",
]
