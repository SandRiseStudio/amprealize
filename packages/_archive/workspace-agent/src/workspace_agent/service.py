"""Core workspace service implementation.

This module provides the main WorkspaceService class that orchestrates
workspace provisioning, command execution, and cleanup.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from workspace_agent.hooks import WorkspaceHooks
from workspace_agent.models import (
    CleanupPolicy,
    ExecResult,
    HealthStatus,
    WorkspaceConfig,
    WorkspaceError,
    WorkspaceExecError,
    WorkspaceInfo,
    WorkspaceNotFoundError,
    WorkspaceProvisionError,
    WorkspaceStats,
    WorkspaceStatus,
)
from workspace_agent.podman_client import PodmanSocketClient
from workspace_agent.state import InMemoryStateStore, StateStore

logger = logging.getLogger(__name__)


class WorkspaceService:
    """Core workspace management service.

    Manages isolated container workspaces for agent code execution:
    - Provisions containers with cloned GitHub repos
    - Executes commands within containers
    - Handles cleanup based on execution outcome

    Example:
        service = WorkspaceService()

        # Provision workspace
        info = await service.provision(WorkspaceConfig(
            run_id="run-123",
            project_id="proj-abc",
            github_repo="owner/repo",
            github_token="ghp_xxx",
        ))

        # Execute commands
        result = await service.exec("run-123", "ls -la")

        # Cleanup
        await service.cleanup("run-123", success=True)
    """

    def __init__(
        self,
        state_store: Optional[StateStore] = None,
        podman_client: Optional[PodmanSocketClient] = None,
        hooks: Optional[WorkspaceHooks] = None,
    ) -> None:
        """Initialize workspace service.

        Args:
            state_store: State storage backend (default: in-memory)
            podman_client: Podman socket client (default: auto-discover)
            hooks: Callback hooks for lifecycle events
        """
        self._state = state_store or InMemoryStateStore()
        self._podman = podman_client or PodmanSocketClient()
        self._hooks = hooks or WorkspaceHooks()
        self._start_time = time.time()

        # Cache socket clients per container for exec operations
        self._socket_clients: Dict[str, PodmanSocketClient] = {}

    @property
    def state(self) -> StateStore:
        """Get the state store."""
        return self._state

    @property
    def podman(self) -> PodmanSocketClient:
        """Get the podman client."""
        return self._podman

    async def provision(self, config: WorkspaceConfig) -> WorkspaceInfo:
        """Provision an isolated workspace with cloned repo.

        Steps:
        1. Create container from image
        2. Install git and tools
        3. Clone GitHub repo into container
        4. Return workspace info

        Args:
            config: Workspace configuration

        Returns:
            WorkspaceInfo with container and path details

        Raises:
            WorkspaceProvisionError: If provisioning fails
        """
        run_id = config.run_id

        # Create initial workspace info
        info = WorkspaceInfo(
            run_id=run_id,
            workspace_path=config.workspace_path,
            status=WorkspaceStatus.PROVISIONING,
            project_id=config.project_id,
        )
        await self._state.set(info)

        logger.info(f"Provisioning workspace for run {run_id}, repo: {config.github_repo}")

        try:
            # Check if podman is available
            if not self._podman.is_available():
                raise WorkspaceProvisionError(
                    run_id,
                    "Podman socket not available. Ensure podman is running and socket is mounted.",
                )

            # Generate unique container name
            short_run_id = run_id[:12] if len(run_id) > 12 else run_id
            container_name = f"amprealize-workspace-{short_run_id}"

            info.container_name = container_name
            info.workspace_path = "/workspace/repo"
            await self._state.set(info)

            # Create container
            container_id = self._podman.create_container(
                name=container_name,
                image=config.image,
                command=["sleep", "infinity"],
                environment={
                    "GITHUB_TOKEN": config.github_token,
                    "GITHUB_REPO": config.github_repo,
                    "RUN_ID": run_id,
                },
                labels={
                    "amprealize.run_id": run_id,
                    "amprealize.project_id": config.project_id,
                    "amprealize.type": "agent-workspace",
                    **config.labels,
                },
                memory_limit=config.memory_limit,
                cpu_limit=float(config.cpu_limit),
            )

            info.container_id = container_id
            logger.info(f"Container created: {container_id}")

            # Install git and tools
            info.status = WorkspaceStatus.CLONING
            await self._state.set(info)

            output, exit_code = self._podman.exec_run(
                container_name,
                "apt-get update && apt-get install -y git curl jq && mkdir -p /workspace",
                timeout=120,
            )

            if exit_code != 0:
                logger.warning(f"Tool installation returned non-zero (continuing): {output}")

            # Clone the repository
            clone_url = f"https://x-access-token:{config.github_token}@github.com/{config.github_repo}.git"
            clone_cmd = f"git clone '{clone_url}' /workspace/repo"
            if config.github_branch:
                clone_cmd = f"git clone --branch '{config.github_branch}' '{clone_url}' /workspace/repo"

            output, exit_code = self._podman.exec_run(
                container_name,
                clone_cmd,
                timeout=300,
            )

            if exit_code != 0:
                # Cleanup on failure
                self._podman.remove_container(container_name)
                raise WorkspaceProvisionError(run_id, f"Git clone failed: {output}")

            logger.info(f"Successfully cloned {config.github_repo}")

            # Create ready marker
            self._podman.exec_run(container_name, "touch /workspace/.ready")

            # Update final state
            info.status = WorkspaceStatus.READY
            info.ready_at = datetime.now(timezone.utc).isoformat()
            await self._state.set(info)

            # Cache socket client
            self._socket_clients[run_id] = self._podman

            # Trigger hook
            await self._hooks.trigger_provision(config, info)

            logger.info(f"Workspace ready for run {run_id}: {info.workspace_path}")
            return info

        except WorkspaceProvisionError:
            raise
        except Exception as e:
            logger.error(f"Failed to provision workspace for run {run_id}: {e}")
            info.status = WorkspaceStatus.DESTROYED
            info.error = str(e)
            await self._state.set(info)
            await self._hooks.trigger_error(run_id, e)
            raise WorkspaceProvisionError(run_id, str(e)) from e

    async def get_workspace(self, run_id: str) -> Optional[WorkspaceInfo]:
        """Get workspace info for a run.

        Args:
            run_id: Run ID

        Returns:
            WorkspaceInfo or None if not found
        """
        return await self._state.get(run_id)

    async def exec(
        self,
        run_id: str,
        command: str,
        cwd: Optional[str] = None,
        timeout: int = 60,
    ) -> ExecResult:
        """Execute a command inside the workspace container.

        Args:
            run_id: Run ID of the workspace
            command: Shell command to execute
            cwd: Working directory (default: workspace path)
            timeout: Command timeout in seconds

        Returns:
            ExecResult with output and exit code

        Raises:
            WorkspaceNotFoundError: If workspace doesn't exist
            WorkspaceExecError: If execution fails
        """
        info = await self._state.get(run_id)
        if not info:
            raise WorkspaceNotFoundError(run_id)

        if info.status not in (WorkspaceStatus.READY, WorkspaceStatus.EXECUTING):
            raise WorkspaceExecError(run_id, f"Workspace not ready, status: {info.status}")

        if not info.container_name:
            raise WorkspaceExecError(run_id, "No container name")

        # Mark as executing
        info.status = WorkspaceStatus.EXECUTING
        await self._state.set(info)

        work_dir = cwd or info.workspace_path

        try:
            # Get cached socket client or use default
            client = self._socket_clients.get(run_id, self._podman)

            output, exit_code = client.exec_run(
                info.container_name,
                command,
                workdir=work_dir,
                timeout=timeout,
            )

            # Trigger hook
            await self._hooks.trigger_exec(run_id, command, exit_code)

            # Restore ready status
            info.status = WorkspaceStatus.READY
            await self._state.set(info)

            return ExecResult(output=output, exit_code=exit_code)

        except Exception as e:
            info.status = WorkspaceStatus.READY
            await self._state.set(info)
            return ExecResult(output=str(e), exit_code=1)

    async def read_file(
        self,
        run_id: str,
        file_path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
    ) -> str:
        """Read a file from inside the workspace.

        Args:
            run_id: Run ID of the workspace
            file_path: Path to file (relative to workspace or absolute)
            start_line: Optional start line (1-indexed)
            end_line: Optional end line (1-indexed)

        Returns:
            File contents
        """
        info = await self._state.get(run_id)
        if not info:
            raise WorkspaceNotFoundError(run_id)

        # Build path
        if not file_path.startswith("/"):
            full_path = f"{info.workspace_path}/{file_path}"
        else:
            full_path = file_path

        # Build command
        if start_line and end_line:
            cmd = f"sed -n '{start_line},{end_line}p' '{full_path}'"
        else:
            cmd = f"cat '{full_path}'"

        result = await self.exec(run_id, cmd)
        if result.exit_code != 0:
            raise WorkspaceExecError(run_id, f"Failed to read file {file_path}: {result.output}")
        return result.output

    async def write_file(
        self,
        run_id: str,
        file_path: str,
        content: str,
    ) -> None:
        """Write a file inside the workspace.

        Args:
            run_id: Run ID of the workspace
            file_path: Path to file (relative to workspace or absolute)
            content: Content to write
        """
        info = await self._state.get(run_id)
        if not info:
            raise WorkspaceNotFoundError(run_id)

        # Build path
        if not file_path.startswith("/"):
            full_path = f"{info.workspace_path}/{file_path}"
        else:
            full_path = file_path

        # Ensure parent directory exists
        parent_dir = "/".join(full_path.rsplit("/", 1)[:-1]) if "/" in full_path else "."
        await self.exec(run_id, f"mkdir -p '{parent_dir}'")

        # Use base64 encoding to safely transfer content
        encoded = base64.b64encode(content.encode()).decode()
        cmd = f"echo '{encoded}' | base64 -d > '{full_path}'"

        result = await self.exec(run_id, cmd)
        if result.exit_code != 0:
            raise WorkspaceExecError(run_id, f"Failed to write file {file_path}: {result.output}")

    async def list_dir(
        self,
        run_id: str,
        dir_path: str,
    ) -> List[str]:
        """List directory contents in workspace.

        Args:
            run_id: Run ID of the workspace
            dir_path: Path to directory (relative to workspace or absolute)

        Returns:
            List of entries (directories end with /)
        """
        info = await self._state.get(run_id)
        if not info:
            raise WorkspaceNotFoundError(run_id)

        # Build path
        if not dir_path.startswith("/"):
            full_path = f"{info.workspace_path}/{dir_path}"
        else:
            full_path = dir_path

        # List with directory indicator
        cmd = f"ls -1 '{full_path}' 2>/dev/null | while read f; do if [ -d \"{full_path}/$f\" ]; then echo \"$f/\"; else echo \"$f\"; fi; done"

        result = await self.exec(run_id, cmd)
        if result.exit_code != 0:
            raise WorkspaceExecError(run_id, f"Failed to list directory {dir_path}: {result.output}")

        return [f for f in result.output.split("\n") if f]

    async def cleanup(
        self,
        run_id: str,
        success: bool = True,
    ) -> None:
        """Cleanup workspace after execution.

        Args:
            run_id: Run ID of the workspace
            success: True for immediate cleanup, False to retain for TTL
        """
        info = await self._state.get(run_id)
        if not info:
            logger.warning(f"No workspace found for run {run_id}")
            return

        if success:
            # Immediate cleanup
            logger.info(f"Cleaning up workspace for run {run_id} (success)")
            info.cleanup_policy = CleanupPolicy.IMMEDIATE
            await self._destroy_workspace(info)
        else:
            # Retain for TTL
            logger.info(f"Retaining workspace for run {run_id} for debugging")
            info.cleanup_policy = CleanupPolicy.TTL
            info.status = WorkspaceStatus.CLEANUP_PENDING
            info.cleanup_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
            await self._state.set(info)

        # Trigger hook
        await self._hooks.trigger_cleanup(run_id, success)

    async def _destroy_workspace(self, info: WorkspaceInfo) -> None:
        """Destroy a workspace container."""
        try:
            if info.container_name:
                logger.info(f"Destroying container: {info.container_name}")

                client = self._socket_clients.get(info.run_id, self._podman)
                client.remove_container(info.container_name)

                # Clean up cached client
                self._socket_clients.pop(info.run_id, None)

            # Update state
            info.status = WorkspaceStatus.DESTROYED
            await self._state.set(info)

            # Optionally delete from state store
            # await self._state.delete(info.run_id)

        except Exception as e:
            logger.error(f"Failed to destroy workspace {info.run_id}: {e}")
            info.error = str(e)
            await self._state.set(info)

    async def cleanup_expired(self) -> int:
        """Cleanup all expired workspaces.

        Returns:
            Number of workspaces cleaned up
        """
        now = datetime.now(timezone.utc)
        expired = await self._state.list_expired(now)

        count = 0
        for info in expired:
            try:
                await self._destroy_workspace(info)
                count += 1
            except Exception as e:
                logger.error(f"Failed to cleanup expired workspace {info.run_id}: {e}")

        return count

    async def list_workspaces(self) -> List[WorkspaceInfo]:
        """List all workspaces.

        Returns:
            List of workspace info
        """
        return await self._state.list_all()

    async def get_stats(self) -> WorkspaceStats:
        """Get service statistics.

        Returns:
            WorkspaceStats with counts and health info
        """
        all_workspaces = await self._state.list_all()

        active = sum(
            1 for w in all_workspaces
            if w.status in (WorkspaceStatus.READY, WorkspaceStatus.EXECUTING)
        )
        pending_cleanup = sum(
            1 for w in all_workspaces
            if w.status == WorkspaceStatus.CLEANUP_PENDING
        )

        # Count actual containers
        containers_running = 0
        try:
            containers = self._podman.list_containers(
                labels={"amprealize.type": "agent-workspace"}
            )
            containers_running = len([c for c in containers if c.get("status") == "running"])
        except Exception:
            pass

        return WorkspaceStats(
            total_workspaces=len(all_workspaces),
            active_workspaces=active,
            pending_cleanup=pending_cleanup,
            containers_running=containers_running,
            podman_available=self._podman.is_available(),
        )

    async def health(self) -> HealthStatus:
        """Get service health status.

        Returns:
            HealthStatus with component health
        """
        podman_ok = self._podman.is_available()
        redis_ok = await self._state.health_check()

        return HealthStatus(
            healthy=podman_ok and redis_ok,
            podman_connected=podman_ok,
            redis_connected=redis_ok,
            uptime_seconds=time.time() - self._start_time,
            version="0.1.0",
        )
