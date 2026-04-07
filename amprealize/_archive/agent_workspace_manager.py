"""Agent Workspace Manager - DEPRECATED

.. deprecated:: 2026-01-16
   This module is deprecated. Use :mod:`amprealize.workspace_agent` instead.

   The workspace management functionality has been extracted to a standalone
   gRPC microservice at ``packages/workspace-agent/``. The new architecture:

   - **workspace-agent service**: Dedicated gRPC service (port 50051) that
     exclusively owns the podman socket and manages container lifecycles
   - **AmprealizeWorkspaceClient**: Thin wrapper in ``amprealize/workspace_agent/``
     that connects to the gRPC service

   Migration::

       # Old (deprecated)
       from amprealize.agent_workspace_manager import (
           AgentWorkspaceManager, get_workspace_manager
       )
       manager = get_workspace_manager()

       # New
       from amprealize.workspace_agent import (
           AmprealizeWorkspaceClient, get_workspace_client
       )
       client = get_workspace_client()

This service handles:
- Provisioning isolated podman containers for agent code execution
- Filesystem sandboxing for agent tools
- Cleanup based on execution outcome (immediate on success, TTL on failure)

Architecture:
- API container communicates with HOST's podman daemon via socket mount
- Each agent workspace is a SEPARATE container, isolated from API server
- Provides per-project/per-user isolation with resource limits

Security Model:
- Agent containers cannot access API server code, secrets, or database
- Resource limits prevent runaway agents from affecting platform
- Ephemeral containers are destroyed after execution

Socket Path: /run/podman/podman.sock (mounted from host)
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Podman socket path - auto-discovered based on platform
def _discover_podman_socket() -> str:
    """Discover the podman socket path based on platform.

    Returns:
        Socket URI (unix:// path)
    """
    import subprocess

    # Environment override takes priority
    env_socket = os.environ.get("PODMAN_SOCKET_PATH")
    if env_socket:
        return env_socket

    # Try to get socket path from podman machine (macOS/Windows)
    # First, find the default/running machine name
    try:
        # Get machine info to find the current machine name
        result = subprocess.run(
            ["podman", "machine", "info", "--format", "{{.Host.CurrentMachine}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            machine_name = result.stdout.strip()

            # Get socket path from this machine
            result = subprocess.run(
                ["podman", "machine", "inspect", machine_name,
                 "--format", "{{.ConnectionInfo.PodmanSocket.Path}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                socket_path = result.stdout.strip()
                if os.path.exists(socket_path):
                    return f"unix://{socket_path}"
    except Exception:
        pass

    # Linux/container: Try standard socket paths
    standard_paths = [
        "/run/podman/podman.sock",  # Root
        f"/run/user/{os.getuid()}/podman/podman.sock",  # User
    ]

    for path in standard_paths:
        if os.path.exists(path):
            return f"unix://{path}"

    # Default fallback
    return "unix:///run/podman/podman.sock"


PODMAN_SOCKET_PATH = _discover_podman_socket()


class PodmanSocketClient:
    """Client for communicating with host's podman via socket.

    This allows the API container to create/manage sibling containers
    for agent workspaces without needing podman CLI installed.
    """

    def __init__(self, socket_uri: str = PODMAN_SOCKET_PATH) -> None:
        """Initialize podman socket client.

        Args:
            socket_uri: Podman socket URI (e.g., unix:///run/podman/podman.sock)
        """
        self._socket_uri = socket_uri
        self._client = None

    def _get_client(self):
        """Get or create podman client."""
        if self._client is None:
            try:
                from podman import PodmanClient
                self._client = PodmanClient(base_url=self._socket_uri)
            except ImportError:
                logger.warning("podman package not installed, socket communication unavailable")
                raise RuntimeError("podman package required for container management")
        return self._client

    def is_available(self) -> bool:
        """Check if podman socket is available."""
        try:
            client = self._get_client()
            client.version()
            return True
        except Exception as e:
            logger.debug(f"Podman socket not available: {e}")
            return False

    def create_container(
        self,
        name: str,
        image: str = "docker.io/library/python:3.11-slim",
        command: Optional[List[str]] = None,
        environment: Optional[Dict[str, str]] = None,
        labels: Optional[Dict[str, str]] = None,
        memory_limit: str = "2g",
        cpu_limit: float = 2.0,
    ) -> str:
        """Create a new container.

        Args:
            name: Container name
            image: Container image
            command: Command to run (default: sleep infinity)
            environment: Environment variables
            labels: Container labels
            memory_limit: Memory limit (e.g., "2g")
            cpu_limit: CPU limit (e.g., 2.0)

        Returns:
            Container ID
        """
        client = self._get_client()

        # Pull image if not present
        try:
            client.images.get(image)
        except Exception:
            logger.info(f"Pulling image: {image}")
            client.images.pull(image)

        # Convert memory limit to bytes
        mem_bytes = None
        if memory_limit:
            if memory_limit.endswith("g"):
                mem_bytes = int(float(memory_limit[:-1]) * 1024 * 1024 * 1024)
            elif memory_limit.endswith("m"):
                mem_bytes = int(float(memory_limit[:-1]) * 1024 * 1024)

        container = client.containers.create(
            name=name,
            image=image,
            command=command or ["sleep", "infinity"],
            environment=environment or {},
            labels=labels or {},
            mem_limit=mem_bytes,
            nano_cpus=int(cpu_limit * 1e9) if cpu_limit else None,
            detach=True,
        )

        container.start()
        container_id = container.id or container.name or name
        return container_id[:12] if container_id else name[:12]

    def exec_run(
        self,
        container_name: str,
        command: str,
        workdir: Optional[str] = None,
        timeout: int = 60,
    ) -> Tuple[str, int]:
        """Execute command in container.

        Args:
            container_name: Container name or ID
            command: Command to execute (shell command string)
            workdir: Working directory inside container
            timeout: Timeout in seconds

        Returns:
            Tuple of (output, exit_code)
        """
        client = self._get_client()
        container = client.containers.get(container_name)

        # Build exec command with shell
        exec_cmd = ["sh", "-c", command]

        try:
            # exec_run returns (exit_code, output_bytes) tuple
            result = container.exec_run(
                cmd=exec_cmd,
                workdir=workdir or "/",
            )

            # Handle tuple result: (exit_code, output_bytes)
            if isinstance(result, tuple) and len(result) >= 2:
                exit_code = result[0] or 0
                output_bytes = result[1]
            else:
                exit_code = 0
                output_bytes = result

            # Output may have multiplexed stream headers - decode and clean
            if output_bytes:
                # Try to decode, stripping any binary headers
                try:
                    if isinstance(output_bytes, bytes):
                        output = output_bytes.decode("utf-8", errors="replace")
                    else:
                        output = str(output_bytes)
                    # Strip multiplexed stream headers (8-byte prefix per chunk)
                    # The format is: 1 byte stream type, 3 bytes padding, 4 bytes size
                    cleaned_lines = []
                    for line in output.split('\n'):
                        # Skip lines that start with control characters
                        if line and ord(line[0]) <= 2:
                            # Strip first 8 bytes (header)
                            line = line[8:] if len(line) > 8 else ""
                        cleaned_lines.append(line)
                    output = '\n'.join(cleaned_lines)
                except Exception:
                    output = str(output_bytes)
            else:
                output = ""

            return output.strip(), int(exit_code)

        except Exception as e:
            logger.error(f"Exec failed in {container_name}: {e}")
            return str(e), 1

    def remove_container(self, container_name: str, force: bool = True) -> bool:
        """Remove a container.

        Args:
            container_name: Container name or ID
            force: Force removal (kill if running)

        Returns:
            True if removed
        """
        try:
            client = self._get_client()
            container = client.containers.get(container_name)
            container.remove(force=force)
            return True
        except Exception as e:
            logger.warning(f"Failed to remove container {container_name}: {e}")
            return False

    def list_containers(self, labels: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        """List containers with optional label filter.

        Args:
            labels: Labels to filter by

        Returns:
            List of container info dicts
        """
        client = self._get_client()

        filters = {}
        if labels:
            filters["label"] = [f"{k}={v}" for k, v in labels.items()]

        containers = client.containers.list(all=True, filters=filters)
        result = []
        for c in containers:
            container_id = c.id or c.name or "unknown"
            result.append({
                "id": container_id[:12] if container_id else "unknown",
                "name": c.name or "unknown",
                "status": getattr(c, 'status', 'unknown'),
                "labels": c.labels or {},
            })
        return result


# Global singleton instance
_global_workspace_manager: Optional["AgentWorkspaceManager"] = None


def get_workspace_manager() -> "AgentWorkspaceManager":
    """Get the global workspace manager instance.

    Creates a new instance if one doesn't exist.
    """
    global _global_workspace_manager
    if _global_workspace_manager is None:
        _global_workspace_manager = AgentWorkspaceManager()
    return _global_workspace_manager


def set_workspace_manager(manager: "AgentWorkspaceManager") -> None:
    """Set the global workspace manager instance.

    Useful for testing or custom configurations.
    """
    global _global_workspace_manager
    _global_workspace_manager = manager


class WorkspaceStatus(str, Enum):
    """Status of an agent workspace."""
    PENDING = "pending"          # Requested, not yet provisioned
    PROVISIONING = "provisioning"  # BreakerAmp container starting
    CLONING = "cloning"          # Git clone in progress
    READY = "ready"              # Workspace ready for agent use
    EXECUTING = "executing"      # Agent actively using workspace
    CLEANUP_PENDING = "cleanup_pending"  # Marked for cleanup
    DESTROYED = "destroyed"      # Cleaned up


class CleanupPolicy(str, Enum):
    """When to clean up workspace."""
    IMMEDIATE = "immediate"      # Delete right away
    TTL = "ttl"                  # Keep for TTL hours
    RETAIN = "retain"           # Don't auto-cleanup


@dataclass
class WorkspaceConfig:
    """Configuration for an agent workspace."""
    run_id: str
    project_id: str
    github_repo: str              # owner/repo format
    github_token: str             # Token for repo access
    github_branch: Optional[str] = None  # Branch to clone (default: default branch)
    workspace_path: str = "/workspace/repo"
    ttl_hours: int = 24           # Hours to keep on failure
    memory_limit: str = "2g"
    cpu_limit: str = "2.0"


@dataclass
class WorkspaceInfo:
    """Information about a provisioned workspace."""
    run_id: str
    container_id: Optional[str] = None
    container_name: Optional[str] = None  # Unique container name for podman exec
    breakeramp_run_id: Optional[str] = None
    status: WorkspaceStatus = WorkspaceStatus.PENDING
    workspace_path: str = "/workspace/repo"
    host_workspace_path: Optional[str] = None  # Path on host (for volume access)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    ready_at: Optional[str] = None
    error: Optional[str] = None
    cleanup_policy: CleanupPolicy = CleanupPolicy.IMMEDIATE
    cleanup_at: Optional[str] = None  # When TTL cleanup should occur
    use_container_exec: bool = False  # If True, commands should use podman exec


class AgentWorkspaceManager:
    """Manages isolated workspaces for agent code execution.

    Each workspace is an BreakerAmp container with a cloned GitHub repo,
    providing filesystem isolation for agent tools.

    Usage:
        manager = AgentWorkspaceManager(breakeramp_service=svc)

        # Provision workspace before agent execution
        info = await manager.provision(WorkspaceConfig(
            run_id="run-123",
            project_id="proj-abc",
            github_repo="owner/repo",
            github_token="ghp_xxx",
        ))

        # Execute agent with workspace
        # ...

        # Cleanup after execution
        await manager.cleanup(run_id="run-123", success=True)
    """

    def __init__(
        self,
        breakeramp_service: Optional[Any] = None,
        github_service: Optional[Any] = None,
    ) -> None:
        """Initialize workspace manager.

        Args:
            breakeramp_service: AmprealizeBreakerAmpService for container orchestration
            github_service: GitHubService for token resolution and API fallback
        """
        self._breakeramp = breakeramp_service
        self._github = github_service
        self._workspaces: Dict[str, WorkspaceInfo] = {}

    async def provision(self, config: WorkspaceConfig) -> WorkspaceInfo:
        """Provision an isolated workspace with cloned repo.

        Steps:
        1. Create BreakerAmp container from agent-workspace blueprint
        2. Clone GitHub repo into container
        3. Return workspace info with paths

        Args:
            config: Workspace configuration

        Returns:
            WorkspaceInfo with container and path details
        """
        run_id = config.run_id

        # Create workspace info
        info = WorkspaceInfo(
            run_id=run_id,
            workspace_path=config.workspace_path,
            status=WorkspaceStatus.PROVISIONING,
        )
        self._workspaces[run_id] = info

        logger.info(f"Provisioning workspace for run {run_id}, repo: {config.github_repo}")

        try:
            if self._breakeramp:
                # Use BreakerAmp for full container isolation
                info = await self._provision_with_breakeramp(config, info)
            else:
                # Fallback: Use local directory (less isolation, for dev/testing)
                info = await self._provision_local(config, info)

            info.status = WorkspaceStatus.READY
            info.ready_at = datetime.now(timezone.utc).isoformat()
            self._workspaces[run_id] = info

            logger.info(f"Workspace ready for run {run_id}: {info.workspace_path}")
            return info

        except Exception as e:
            logger.error(f"Failed to provision workspace for run {run_id}: {e}")
            info.status = WorkspaceStatus.DESTROYED
            info.error = str(e)
            self._workspaces[run_id] = info
            raise WorkspaceProvisionError(run_id, str(e)) from e

    async def _provision_with_breakeramp(
        self,
        config: WorkspaceConfig,
        info: WorkspaceInfo,
    ) -> WorkspaceInfo:
        """Provision workspace using BreakerAmp container."""
        from breakeramp.models import PlanRequest, ApplyRequest

        # Plan the workspace deployment
        # Note: PlanRequest requires environment, optional blueprint_id, variables, etc.
        plan_request = PlanRequest(
            blueprint_id="agent-workspace",
            environment="agent-workspaces",  # Use dedicated environment for agent workspaces
            variables={
                "github_repo": config.github_repo,
                "github_token": config.github_token,
                "run_id": config.run_id,
                "workspace_path": config.workspace_path,
                "ttl_hours": str(config.ttl_hours),
            },
            # Leave defaults for active_modules and machine_disk_size_gb
        )

        plan_response = self._breakeramp.plan(plan_request)

        if not plan_response.success:
            raise WorkspaceProvisionError(
                config.run_id,
                f"BreakerAmp plan failed: {plan_response.error}",
            )

        # Apply the plan
        apply_request = ApplyRequest(plan_id=plan_response.plan_id)
        apply_response = self._breakeramp.apply(apply_request)

        if not apply_response.success:
            raise WorkspaceProvisionError(
                config.run_id,
                f"BreakerAmp apply failed: {apply_response.error}",
            )

        # Update info with container details
        info.breakeramp_run_id = apply_response.run_id
        info.container_id = apply_response.resources.get("workspace", {}).get("container_id")
        info.status = WorkspaceStatus.CLONING

        # Wait for clone to complete (init script runs the clone)
        await self._wait_for_workspace_ready(config.run_id, timeout_seconds=300)

        return info

    async def _provision_local(
        self,
        config: WorkspaceConfig,
        info: WorkspaceInfo,
    ) -> WorkspaceInfo:
        """Provision workspace using podman socket or local directory fallback.

        Priority:
        1. Podman socket API (preferred - container isolation via host's podman)
        2. Local directory (fallback - for environments without podman)

        The socket approach allows the API container to create sibling containers
        on the host for agent workspaces, ensuring complete isolation.
        """
        # Try podman socket first (preferred for isolation)
        socket_client = PodmanSocketClient()

        if socket_client.is_available():
            return await self._provision_with_podman_socket(config, info, socket_client)
        else:
            logger.warning("Podman socket not available - using local directory fallback (less isolation)")
            return await self._provision_local_directory(config, info)

    async def _provision_with_podman_socket(
        self,
        config: WorkspaceConfig,
        info: WorkspaceInfo,
        socket_client: PodmanSocketClient,
    ) -> WorkspaceInfo:
        """Provision an isolated workspace container using podman socket API.

        This creates a sibling container on the host, completely isolated from
        the API server container.
        """
        # Generate unique container name
        short_run_id = config.run_id[:12] if len(config.run_id) > 12 else config.run_id
        container_name = f"amprealize-workspace-{short_run_id}"

        info.container_name = container_name
        info.use_container_exec = True
        info.workspace_path = "/workspace/repo"
        info.status = WorkspaceStatus.PROVISIONING

        logger.info(f"Provisioning container workspace via socket: {container_name}")

        try:
            # Create container via socket API
            container_id = socket_client.create_container(
                name=container_name,
                image="docker.io/library/python:3.11-slim",
                command=["sleep", "infinity"],
                environment={
                    "GITHUB_TOKEN": config.github_token,
                    "GITHUB_REPO": config.github_repo,
                    "RUN_ID": config.run_id,
                },
                labels={
                    "amprealize.run_id": config.run_id,
                    "amprealize.project_id": config.project_id,
                    "amprealize.type": "agent-workspace",
                },
                memory_limit=config.memory_limit,
                cpu_limit=float(config.cpu_limit),
            )

            info.container_id = container_id
            logger.info(f"Container created via socket: {container_id}")

            # Install git and other tools
            info.status = WorkspaceStatus.CLONING
            output, exit_code = socket_client.exec_run(
                container_name,
                "apt-get update && apt-get install -y git curl jq && mkdir -p /workspace",
                timeout=120,
            )

            if exit_code != 0:
                logger.warning(f"Failed to install tools (continuing anyway): {output}")

            # Clone the repository
            clone_url = f"https://x-access-token:{config.github_token}@github.com/{config.github_repo}.git"
            clone_cmd = f"git clone '{clone_url}' /workspace/repo"
            if config.github_branch:
                clone_cmd = f"git clone --branch '{config.github_branch}' '{clone_url}' /workspace/repo"

            output, exit_code = socket_client.exec_run(
                container_name,
                clone_cmd,
                timeout=300,
            )

            if exit_code != 0:
                # Cleanup on failure
                socket_client.remove_container(container_name)
                raise WorkspaceProvisionError(
                    config.run_id,
                    f"Git clone failed: {output}",
                )

            logger.info(f"Successfully cloned {config.github_repo} into container")

            # Create ready marker
            socket_client.exec_run(container_name, "touch /workspace/.ready")

            # Store socket client for later exec calls
            info._socket_client = socket_client  # type: ignore

            self._workspaces[config.run_id] = info
            return info

        except WorkspaceProvisionError:
            raise
        except Exception as e:
            # Cleanup on failure
            socket_client.remove_container(container_name)
            raise WorkspaceProvisionError(config.run_id, str(e)) from e

    async def _provision_with_podman(
        self,
        config: WorkspaceConfig,
        info: WorkspaceInfo,
    ) -> WorkspaceInfo:
        """Provision an isolated workspace container using podman."""
        import subprocess

        # Generate unique container name
        short_run_id = config.run_id[:12] if len(config.run_id) > 12 else config.run_id
        container_name = f"amprealize-workspace-{short_run_id}"

        info.container_name = container_name
        info.use_container_exec = True
        info.workspace_path = "/workspace/repo"
        info.status = WorkspaceStatus.PROVISIONING

        logger.info(f"Provisioning container workspace: {container_name}")

        try:
            # Create and start the container with git and tools
            # Use python:3.11-slim as base (has python, can install git)
            create_cmd = [
                "podman", "run", "-d",
                "--name", container_name,
                "--memory", config.memory_limit,
                "--cpus", config.cpu_limit,
                "-e", f"GITHUB_TOKEN={config.github_token}",
                "-e", f"GITHUB_REPO={config.github_repo}",
                "-e", f"RUN_ID={config.run_id}",
                "--label", f"amprealize.run_id={config.run_id}",
                "--label", "amprealize.type=agent-workspace",
                "docker.io/library/python:3.11-slim",
                "sleep", "infinity"
            ]

            result = subprocess.run(
                create_cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                raise WorkspaceProvisionError(
                    config.run_id,
                    f"Failed to create container: {result.stderr}",
                )

            info.container_id = result.stdout.strip()[:12]
            logger.info(f"Container created: {info.container_id}")

            # Install git and other tools
            info.status = WorkspaceStatus.CLONING
            install_cmd = [
                "podman", "exec", container_name,
                "sh", "-c",
                "apt-get update && apt-get install -y git curl jq && mkdir -p /workspace"
            ]

            result = subprocess.run(
                install_cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode != 0:
                logger.warning(f"Failed to install tools: {result.stderr}")
                # Continue anyway, git might already be there

            # Clone the repository
            clone_url = f"https://x-access-token:{config.github_token}@github.com/{config.github_repo}.git"
            clone_cmd_str = f"git clone '{clone_url}' /workspace/repo"
            if config.github_branch:
                clone_cmd_str = f"git clone --branch '{config.github_branch}' '{clone_url}' /workspace/repo"

            clone_cmd = [
                "podman", "exec", container_name,
                "sh", "-c", clone_cmd_str
            ]

            result = subprocess.run(
                clone_cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )

            if result.returncode != 0:
                raise WorkspaceProvisionError(
                    config.run_id,
                    f"Git clone failed: {result.stderr}",
                )

            logger.info(f"Successfully cloned {config.github_repo} into container")

            # Create ready marker
            subprocess.run(
                ["podman", "exec", container_name, "touch", "/workspace/.ready"],
                capture_output=True,
                timeout=10,
            )

            self._workspaces[config.run_id] = info
            return info

        except subprocess.TimeoutExpired as e:
            # Cleanup on failure
            subprocess.run(["podman", "rm", "-f", container_name], capture_output=True)
            raise WorkspaceProvisionError(config.run_id, f"Timeout: {e}")
        except Exception as e:
            # Cleanup on failure
            subprocess.run(["podman", "rm", "-f", container_name], capture_output=True)
            raise

    async def _provision_local_directory(
        self,
        config: WorkspaceConfig,
        info: WorkspaceInfo,
    ) -> WorkspaceInfo:
        """Provision workspace using local directory (fallback when podman unavailable)."""
        import subprocess
        import tempfile

        # Create temporary workspace directory
        workspace_dir = Path(tempfile.mkdtemp(prefix=f"amprealize-workspace-{config.run_id}-"))
        info.host_workspace_path = str(workspace_dir)
        info.workspace_path = str(workspace_dir)
        info.use_container_exec = False
        info.status = WorkspaceStatus.CLONING

        logger.info(f"Cloning {config.github_repo} to {workspace_dir} (local fallback)")

        # Clone the repository
        clone_url = f"https://x-access-token:{config.github_token}@github.com/{config.github_repo}.git"

        try:
            cmd = ["git", "clone"]
            if config.github_branch:
                cmd.extend(["--branch", config.github_branch])
            cmd.extend([clone_url, str(workspace_dir)])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            if result.returncode != 0:
                raise WorkspaceProvisionError(
                    config.run_id,
                    f"Git clone failed: {result.stderr}",
                )

            logger.info(f"Successfully cloned {config.github_repo}")

        except subprocess.TimeoutExpired:
            raise WorkspaceProvisionError(
                config.run_id,
                "Git clone timed out after 5 minutes",
            )

        return info

    async def _wait_for_workspace_ready(
        self,
        run_id: str,
        timeout_seconds: int = 300,
    ) -> None:
        """Wait for workspace to be ready (clone complete)."""
        import time
        start_time = time.time()

        while time.time() - start_time < timeout_seconds:
            # Check if .ready marker file exists in container
            info = self._workspaces.get(run_id)
            if not info or not info.container_id:
                await asyncio.sleep(2)
                continue

            # Check for ready marker (set by init script)
            # In a real implementation, this would exec into the container
            # For now, we assume the init script completes
            if info.status == WorkspaceStatus.CLONING:
                # Give init script time to complete
                await asyncio.sleep(5)
                return

            await asyncio.sleep(2)

        raise WorkspaceProvisionError(
            run_id,
            f"Workspace not ready after {timeout_seconds} seconds",
        )

    async def get_workspace(self, run_id: str) -> Optional[WorkspaceInfo]:
        """Get workspace info for a run."""
        return self._workspaces.get(run_id)

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
            command: Command to execute
            cwd: Working directory inside container (default: workspace path)
            timeout: Command timeout in seconds

        Returns:
            Tuple of (output, exit_code)

        Raises:
            WorkspaceNotFoundError: If workspace doesn't exist
            WorkspaceProvisionError: If command execution fails
        """
        import subprocess

        info = self._workspaces.get(run_id)
        if not info:
            raise WorkspaceNotFoundError(run_id)

        if info.status != WorkspaceStatus.READY and info.status != WorkspaceStatus.EXECUTING:
            raise WorkspaceProvisionError(run_id, f"Workspace not ready, status: {info.status}")

        # Mark as executing
        info.status = WorkspaceStatus.EXECUTING
        self._workspaces[run_id] = info

        work_dir = cwd or info.workspace_path

        if info.use_container_exec and info.container_name:
            # Check if we have a socket client stored (preferred)
            socket_client = getattr(info, '_socket_client', None)

            if socket_client:
                # Use socket API for exec
                try:
                    return socket_client.exec_run(
                        info.container_name,
                        command,
                        workdir=work_dir,
                        timeout=timeout,
                    )
                except Exception as e:
                    return f"Socket exec error: {e}", 1
            else:
                # Fallback to CLI (for backwards compatibility)
                exec_cmd = [
                    "podman", "exec",
                    "-w", work_dir,
                    info.container_name,
                    "sh", "-c", command
                ]

                try:
                    result = subprocess.run(
                        exec_cmd,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                    )
                    output = result.stdout
                    if result.stderr:
                        output += f"\n{result.stderr}"
                    return output.strip(), result.returncode

                except subprocess.TimeoutExpired:
                    return f"Command timed out after {timeout}s", 124
                except Exception as e:
                    return f"Execution error: {e}", 1
        else:
            # Local execution (fallback mode)
            try:
                result = subprocess.run(
                    command,
                    shell=True,
                    cwd=work_dir,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                output = result.stdout
                if result.stderr:
                    output += f"\n{result.stderr}"
                return output.strip(), result.returncode

            except subprocess.TimeoutExpired:
                return f"Command timed out after {timeout}s", 124
            except Exception as e:
                return f"Execution error: {e}", 1

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
        info = self._workspaces.get(run_id)
        if not info:
            raise WorkspaceNotFoundError(run_id)

        # Build the path relative to workspace
        if not file_path.startswith("/"):
            full_path = f"{info.workspace_path}/{file_path}"
        else:
            full_path = file_path

        if start_line and end_line:
            cmd = f"sed -n '{start_line},{end_line}p' '{full_path}'"
        else:
            cmd = f"cat '{full_path}'"

        output, exit_code = await self.exec_in_workspace(run_id, cmd)
        if exit_code != 0:
            raise WorkspaceProvisionError(run_id, f"Failed to read file {file_path}: {output}")
        return output

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
        import base64

        info = self._workspaces.get(run_id)
        if not info:
            raise WorkspaceNotFoundError(run_id)

        # Build the path relative to workspace
        if not file_path.startswith("/"):
            full_path = f"{info.workspace_path}/{file_path}"
        else:
            full_path = file_path

        # Ensure parent directory exists
        parent_dir = "/".join(full_path.rsplit("/", 1)[:-1]) if "/" in full_path else "."
        await self.exec_in_workspace(run_id, f"mkdir -p '{parent_dir}'")

        # Use base64 encoding to safely transfer content
        encoded = base64.b64encode(content.encode()).decode()
        cmd = f"echo '{encoded}' | base64 -d > '{full_path}'"

        output, exit_code = await self.exec_in_workspace(run_id, cmd)
        if exit_code != 0:
            raise WorkspaceProvisionError(run_id, f"Failed to write file {file_path}: {output}")

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
        info = self._workspaces.get(run_id)
        if not info:
            raise WorkspaceNotFoundError(run_id)

        # Build the path relative to workspace
        if not dir_path.startswith("/"):
            full_path = f"{info.workspace_path}/{dir_path}"
        else:
            full_path = dir_path

        # Use ls with special handling for directories (append /)
        cmd = f"ls -1 '{full_path}' 2>/dev/null | while read f; do if [ -d \"{full_path}/$f\" ]; then echo \"$f/\"; else echo \"$f\"; fi; done"

        output, exit_code = await self.exec_in_workspace(run_id, cmd)
        if exit_code != 0:
            raise WorkspaceProvisionError(run_id, f"Failed to list directory {dir_path}: {output}")

        return [f for f in output.split("\n") if f]

    async def cleanup(
        self,
        run_id: str,
        success: bool = True,
    ) -> None:
        """Cleanup workspace after execution.

        Args:
            run_id: Run ID of the workspace
            success: True if execution succeeded (immediate cleanup),
                    False if failed (retain for TTL debugging)
        """
        info = self._workspaces.get(run_id)
        if not info:
            logger.warning(f"No workspace found for run {run_id}")
            return

        if success:
            # Immediate cleanup on success
            logger.info(f"Cleaning up workspace for run {run_id} (success)")
            info.cleanup_policy = CleanupPolicy.IMMEDIATE
            await self._destroy_workspace(info)
        else:
            # Keep for TTL on failure
            logger.info(f"Retaining workspace for run {run_id} for debugging (failure)")
            info.cleanup_policy = CleanupPolicy.TTL
            info.status = WorkspaceStatus.CLEANUP_PENDING
            # Schedule cleanup after TTL (in production, this would be a background job)
            self._workspaces[run_id] = info

    async def _destroy_workspace(self, info: WorkspaceInfo) -> None:
        """Destroy a workspace container and volumes."""
        import subprocess

        try:
            if info.breakeramp_run_id and self._breakeramp:
                # Destroy via BreakerAmp
                from breakeramp.models import DestroyRequest

                destroy_request = DestroyRequest(
                    amp_run_id=info.breakeramp_run_id,
                    reason="workspace_cleanup",
                    cascade=True,
                )
                self._breakeramp.destroy(destroy_request)

            elif info.use_container_exec and info.container_name:
                # Destroy container - prefer socket API if available
                logger.info(f"Destroying container: {info.container_name}")

                socket_client = getattr(info, '_socket_client', None)
                if socket_client:
                    socket_client.remove_container(info.container_name)
                else:
                    # Fallback to CLI
                    subprocess.run(
                        ["podman", "rm", "-f", info.container_name],
                        capture_output=True,
                        timeout=30,
                    )

            elif info.host_workspace_path:
                # Local cleanup
                import shutil
                workspace_path = Path(info.host_workspace_path)
                if workspace_path.exists():
                    shutil.rmtree(workspace_path)

            info.status = WorkspaceStatus.DESTROYED
            self._workspaces[info.run_id] = info
            logger.info(f"Destroyed workspace for run {info.run_id}")

        except Exception as e:
            logger.error(f"Failed to destroy workspace for run {info.run_id}: {e}")

    async def cleanup_expired(self) -> int:
        """Cleanup all workspaces past their TTL.

        Returns:
            Number of workspaces cleaned up
        """
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        cleaned = 0

        for run_id, info in list(self._workspaces.items()):
            if info.status != WorkspaceStatus.CLEANUP_PENDING:
                continue

            if info.cleanup_policy != CleanupPolicy.TTL:
                continue

            # Check if past TTL
            created = datetime.fromisoformat(info.created_at)
            # Default 24h TTL
            if now - created > timedelta(hours=24):
                logger.info(f"Cleaning up expired workspace for run {run_id}")
                await self._destroy_workspace(info)
                cleaned += 1

        return cleaned

    async def list_workspaces(self) -> List[Dict[str, Any]]:
        """List all tracked workspaces with their status.

        Returns:
            List of workspace info dictionaries
        """
        return [
            {
                "run_id": info.run_id,
                "status": info.status.value,
                "workspace_path": info.workspace_path,
                "created_at": info.created_at,
                "ready_at": info.ready_at,
                "cleanup_policy": info.cleanup_policy.value,
                "error": info.error,
            }
            for info in self._workspaces.values()
        ]

    async def get_stats(self) -> Dict[str, Any]:
        """Get workspace statistics.

        Returns:
            Statistics dictionary with counts by status
        """
        stats = {
            "total": len(self._workspaces),
            "by_status": {},
        }

        for info in self._workspaces.values():
            status = info.status.value
            stats["by_status"][status] = stats["by_status"].get(status, 0) + 1

        return stats


class WorkspaceProvisionError(Exception):
    """Raised when workspace provisioning fails."""

    def __init__(self, run_id: str, message: str) -> None:
        self.run_id = run_id
        self.message = message
        super().__init__(f"Workspace provision failed for run {run_id}: {message}")


class WorkspaceNotFoundError(Exception):
    """Raised when workspace is not found."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        super().__init__(f"No workspace found for run {run_id}")
