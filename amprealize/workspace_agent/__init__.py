"""Amprealize thin wrapper for workspace management via BreakerAmp.

This module provides a wrapper around the AmpOrchestrator that integrates
with Amprealize's ActionService and logging. It replaces the deprecated
workspace-agent gRPC service with direct Podman container management.

Note: The old gRPC-based interface is deprecated. New code should use
AmpOrchestrator directly from breakeramp package.
"""

from __future__ import annotations

import logging
import os
from enum import Enum
from typing import TYPE_CHECKING, List, Optional, Tuple, Any, Union

logger = logging.getLogger(__name__)

# Import types for runtime use
WORKSPACE_AGENT_AVAILABLE = False
AmpOrchestrator: Any = None
WorkspaceConfig: Any = None
WorkspaceInfo: Any = None
get_orchestrator: Any = None
OrchestratorError: Any = Exception
WorkspaceNotFoundError: Any = Exception
QuotaExceededError: Any = Exception
ProvisionError: Any = Exception

try:
    from breakeramp import (
        AmpOrchestrator,
        WorkspaceConfig,
        WorkspaceInfo,
        get_orchestrator,
        OrchestratorError,
        WorkspaceNotFoundError,
        QuotaExceededError,
        ProvisionError,
    )
    WORKSPACE_AGENT_AVAILABLE = True
except ImportError:
    logger.warning("breakeramp package not installed. Install with: pip install -e ./packages/breakeramp")


# Backward compatibility aliases
class WorkspaceStatus(str, Enum):
    """Status of a workspace (backward compat alias)."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CleanupPolicy(str, Enum):
    """Cleanup policy for workspaces (backward compat alias)."""
    IMMEDIATE = "immediate"
    ON_SUCCESS = "on_success"
    PRESERVE_ON_FAILURE = "preserve_on_failure"


# Backward compat exception aliases (inherit from OrchestratorError when available)
class WorkspaceError(Exception):
    """Base workspace error (backward compat alias)."""
    pass


class WorkspaceProvisionError(WorkspaceError):
    """Provisioning failed (backward compat alias)."""
    pass


class WorkspaceExecError(WorkspaceError):
    """Execution failed (backward compat alias)."""
    pass


class AmprealizeWorkspaceClient:
    """Wrapper around AmpOrchestrator with Amprealize integration.

    This wrapper:
    - Uses AmpOrchestrator for container operations (replaces gRPC)
    - Logs operations via ActionService (optional)
    - Provides the same interface as the old AgentWorkspaceManager

    Example:
        client = AmprealizeWorkspaceClient()

        info = await client.provision(WorkspaceConfig(
            run_id="run-123",
            scope="org:tenant-abc",
            github_repo="owner/repo",
            github_token="ghp_xxx",
        ))

        output, exit_code = await client.exec_in_workspace("run-123", "ls -la")
        await client.cleanup("run-123", success=True)

    Note: New code should use AmpOrchestrator directly from breakeramp package.
    This wrapper is maintained for backward compatibility.
    """

    def __init__(
        self,
        orchestrator: Optional[AmpOrchestrator] = None,
        action_service: Any = None,
        # Deprecated parameters (ignored, kept for backward compat)
        host: Optional[str] = None,
        token: Optional[str] = None,
    ) -> None:
        """Initialize the client.

        Args:
            orchestrator: AmpOrchestrator instance (default: global singleton)
            action_service: Optional ActionService for logging operations
            host: Deprecated, ignored
            token: Deprecated, ignored
        """
        if not WORKSPACE_AGENT_AVAILABLE:
            raise RuntimeError(
                "breakeramp package not installed. "
                "Install with: pip install -e ./packages/breakeramp"
            )

        if host or token:
            logger.warning(
                "host and token parameters are deprecated. "
                "AmprealizeWorkspaceClient now uses AmpOrchestrator directly."
            )

        self._orchestrator = orchestrator or get_orchestrator()
        self._action_service = action_service

    async def close(self) -> None:
        """Close the client connection."""
        await self._orchestrator.close()

    async def provision(self, config: WorkspaceConfig) -> WorkspaceInfo:
        """Provision an isolated workspace with cloned repo.

        Args:
            config: Workspace configuration

        Returns:
            WorkspaceInfo with container and path details
        """
        logger.info(f"Provisioning workspace: run_id={config.run_id}")

        try:
            info = await self._orchestrator.provision_workspace(config)

            # Log to ActionService if available
            if self._action_service:
                await self._log_action(
                    run_id=config.run_id,
                    action_type="workspace.provision",
                    details={
                        "github_repo": config.github_repo,
                        "container_name": info.container_name,
                        "status": info.status,
                    },
                    success=True,
                )

            return info

        except Exception as e:
            if self._action_service:
                await self._log_action(
                    run_id=config.run_id,
                    action_type="workspace.provision",
                    details={"error": str(e)},
                    success=False,
                )
            raise

    async def get_workspace(self, run_id: str) -> Optional[WorkspaceInfo]:
        """Get workspace info for a run.

        Args:
            run_id: Run ID

        Returns:
            WorkspaceInfo or None if not found
        """
        try:
            return await self._orchestrator.get_workspace_info(run_id)
        except WorkspaceNotFoundError:
            return None

    async def exec_in_workspace(
        self,
        run_id: str,
        command: str,
        cwd: Optional[str] = None,
        timeout: int = 60,
    ) -> Tuple[str, int]:
        """Execute a command inside the workspace container.

        Args:
            run_id: Run ID of the workspace
            command: Command to execute (shell command string)
            cwd: Working directory inside container
            timeout: Command timeout in seconds

        Returns:
            Tuple of (output, exit_code)
        """
        output, exit_code = await self._orchestrator.exec_in_workspace(
            run_id=run_id,
            command=command,
            timeout=timeout,
            workdir=cwd,
        )
        return output, exit_code

    async def read_file_in_workspace(
        self,
        run_id: str,
        file_path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
    ) -> str:
        """Read a file from inside the workspace.

        Args:
            run_id: Run ID of the workspace
            file_path: Path to file inside workspace
            start_line: Optional start line (1-indexed)
            end_line: Optional end line (1-indexed)

        Returns:
            File contents
        """
        content = await self._orchestrator.read_file(run_id, file_path)

        # Apply line filtering if requested
        if start_line or end_line:
            lines = content.split('\n')
            start_idx = (start_line - 1) if start_line else 0
            end_idx = end_line if end_line else len(lines)
            content = '\n'.join(lines[start_idx:end_idx])

        return content

    async def write_file_in_workspace(
        self,
        run_id: str,
        file_path: str,
        content: str,
    ) -> None:
        """Write a file inside the workspace.

        Args:
            run_id: Run ID of the workspace
            file_path: Path to file inside workspace
            content: Content to write
        """
        await self._orchestrator.write_file(
            run_id=run_id,
            path=file_path,
            content=content,
        )

    async def list_dir_in_workspace(
        self,
        run_id: str,
        dir_path: str,
    ) -> List[str]:
        """List directory contents in workspace.

        Args:
            run_id: Run ID of the workspace
            dir_path: Path to directory inside workspace

        Returns:
            List of file/directory names
        """
        # Use exec to list directory
        output, exit_code = await self._orchestrator.exec_in_workspace(
            run_id=run_id,
            command=f"ls -1 {dir_path}",
        )
        if exit_code != 0:
            return []
        return [f for f in output.strip().split('\n') if f]

    async def cleanup(
        self,
        run_id: str,
        success: bool = True,
    ) -> None:
        """Cleanup workspace after execution.

        Args:
            run_id: Run ID of the workspace
            success: True if execution succeeded (immediate cleanup)
        """
        logger.info(f"Cleaning up workspace: run_id={run_id}, success={success}")

        try:
            await self._orchestrator.cleanup_workspace(run_id)

            if self._action_service:
                await self._log_action(
                    run_id=run_id,
                    action_type="workspace.cleanup",
                    details={"success": success},
                    success=True,
                )
        except Exception as e:
            if self._action_service:
                await self._log_action(
                    run_id=run_id,
                    action_type="workspace.cleanup",
                    details={"error": str(e)},
                    success=False,
                )
            raise

    async def cleanup_expired(self) -> int:
        """Cleanup all expired/zombie workspaces.

        Returns:
            Number of workspaces cleaned up
        """
        cleaned = await self._orchestrator.cleanup_zombies()
        return len(cleaned)

    async def list_workspaces(self) -> List[dict]:
        """List all workspaces.

        Returns:
            List of workspace info dicts
        """
        # Get all workspaces from state store
        workspaces = []
        state_store = await self._orchestrator._get_state()

        # This is a simplified implementation - list by common scopes
        # In production, would need a more efficient listing mechanism
        return workspaces

    async def get_stats(self) -> dict:
        """Get service statistics.

        Returns:
            Stats dict
        """
        # Simplified stats - orchestrator doesn't track detailed stats
        return {
            "total_workspaces": 0,  # Would need to query state store
            "active_workspaces": 0,
        }

    async def health(self) -> dict:
        """Check service health.

        Returns:
            Health status dict
        """
        # Check Podman connectivity
        try:
            podman = await self._orchestrator._get_podman()
            available = await podman.is_available()
            return {
                "status": "healthy" if available else "unhealthy",
                "podman": available,
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
            }

    async def _log_action(
        self,
        run_id: str,
        action_type: str,
        details: dict,
        success: bool,
    ) -> None:
        """Log an action to ActionService."""
        if not self._action_service:
            return

        try:
            await self._action_service.record_action(
                run_id=run_id,
                action_type=action_type,
                details=details,
                success=success,
            )
        except Exception as e:
            logger.warning(f"Failed to log action: {e}")


# Global client instance (lazy initialization)
_global_client: Optional[AmprealizeWorkspaceClient] = None


def get_workspace_client(
    orchestrator: Optional[AmpOrchestrator] = None,
    action_service: Any = None,
    # Deprecated parameters (ignored, kept for backward compat)
    host: Optional[str] = None,
    token: Optional[str] = None,
) -> AmprealizeWorkspaceClient:
    """Get or create the global workspace client.

    Args:
        orchestrator: AmpOrchestrator instance (default: global singleton)
        action_service: Optional ActionService
        host: Deprecated, ignored
        token: Deprecated, ignored

    Returns:
        AmprealizeWorkspaceClient instance
    """
    global _global_client

    if _global_client is None:
        _global_client = AmprealizeWorkspaceClient(
            orchestrator=orchestrator,
            action_service=action_service,
        )

    return _global_client


def reset_workspace_client() -> None:
    """Reset the global workspace client (for testing)."""
    global _global_client
    _global_client = None


# Re-export for convenience
__all__ = [
    # Client
    "AmprealizeWorkspaceClient",
    "get_workspace_client",
    "reset_workspace_client",
    # Models (re-exported from breakeramp)
    "WorkspaceConfig",
    "WorkspaceInfo",
    # Backward compat aliases
    "WorkspaceStatus",
    "CleanupPolicy",
    "WorkspaceError",
    "WorkspaceNotFoundError",
    "WorkspaceProvisionError",
    "WorkspaceExecError",
    "OrchestratorError",
    "QuotaExceededError",
    "ProvisionError",
    # BreakerAmp re-exports for direct access
    "AmpOrchestrator",
    "get_orchestrator",
    # Constants
    "WORKSPACE_AGENT_AVAILABLE",
]
