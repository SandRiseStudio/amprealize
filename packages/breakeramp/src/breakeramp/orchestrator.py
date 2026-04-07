"""BreakerAmp Workspace Orchestrator - Unified Control Plane.

The AmpOrchestrator consolidates workspace management for agent execution:
- Provisions isolated container workspaces
- Manages workspace lifecycle (create, monitor, destroy)
- Enforces per-tenant quotas and resource limits
- Handles zombie detection and cleanup
- Integrates with compliance/audit hooks

This replaces:
- workspace-agent gRPC service
- legacy workspace client wrapper
- Manual Podman container commands

Architecture:
    ┌─────────────────────────────────────────────────────────────┐
    │                    AmpOrchestrator                          │
    │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
    │  │ PodmanClient│  │  StateStore │  │    QuotaService     │ │
    │  │ (runtime)   │  │ (Redis)     │  │   (limits/plans)    │ │
    │  └─────────────┘  └─────────────┘  └─────────────────────┘ │
    │                                                             │
    │  Methods:                                                   │
    │  - provision_workspace()  - cleanup_workspace()            │
    │  - exec_in_workspace()    - cleanup_zombies()              │
    │  - send_heartbeat()       - get_workspace_info()           │
    └─────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from breakeramp.runtime.podman import PodmanClient, ContainerNotFoundError
from breakeramp.runtime.state import (
    StateStore,
    WorkspaceState,
    WorkspaceStatus,
    InMemoryStateStore,
    RedisStateStore,
)
from breakeramp.quota import (
    QuotaService,
    QuotaLimits,
    PLAN_LIMITS,
    get_isolation_scope,
    parse_scope,
    get_quota_service,
)

logger = logging.getLogger(__name__)


class OrchestratorError(Exception):
    """Base exception for orchestrator operations."""
    pass


class WorkspaceNotFoundError(OrchestratorError):
    """Workspace was not found."""
    def __init__(self, run_id: str):
        self.run_id = run_id
        super().__init__(f"Workspace not found: {run_id}")


class QuotaExceededError(OrchestratorError):
    """Tenant quota exceeded."""
    def __init__(self, scope: str, current: int, limit: int):
        self.scope = scope
        self.current = current
        self.limit = limit
        super().__init__(f"Quota exceeded for {scope}: {current}/{limit}")


class ProvisionError(OrchestratorError):
    """Failed to provision workspace."""
    pass


@dataclass
class WorkspaceConfig:
    """Configuration for provisioning an agent workspace."""
    run_id: str
    scope: str  # "org:{org_id}" or "user:{user_id}"

    # Resource limits
    memory_limit: str = "2g"
    cpu_limit: float = 2.0
    timeout_seconds: int = 3600

    # Container settings
    image: str = "docker.io/library/python:3.11-slim"
    workdir: str = "/workspace"
    environment: Dict[str, str] = field(default_factory=dict)

    # Optional: GitHub repo to clone
    github_repo: Optional[str] = None
    github_token: Optional[str] = None
    github_branch: str = "main"

    # Optional context
    project_id: Optional[str] = None
    agent_id: Optional[str] = None
    user_id: Optional[str] = None

    # Labels for tracking
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class WorkspaceInfo:
    """Runtime info about a provisioned workspace (public API)."""
    run_id: str
    container_id: str
    container_name: str
    status: str
    scope: str
    workspace_path: str
    created_at: str

    @classmethod
    def from_state(cls, state: WorkspaceState) -> "WorkspaceInfo":
        """Create from internal state."""
        return cls(
            run_id=state.run_id,
            container_id=state.container_id,
            container_name=state.container_name,
            status=state.status.value,
            scope=state.scope,
            workspace_path=state.workspace_path,
            created_at=state.created_at,
        )


# NOTE: QuotaLimits and PLAN_LIMITS are imported from breakeramp.quota


@dataclass
class OrchestratorHooks:
    """Hooks for telemetry and compliance integration."""
    on_workspace_provisioned: Optional[Callable[[WorkspaceConfig, WorkspaceInfo], None]] = None
    on_workspace_cleaned: Optional[Callable[[str], None]] = None
    on_quota_exceeded: Optional[Callable[[str, int, int], None]] = None
    on_zombie_detected: Optional[Callable[[str], None]] = None


class AmpOrchestrator:
    """Unified control plane for agent workspace management.

    This orchestrator manages the full lifecycle of agent execution workspaces:
    1. Provisioning: Create isolated containers with resource limits
    2. Execution: Run commands inside workspaces
    3. Monitoring: Track heartbeats, detect zombies
    4. Cleanup: Remove workspaces, preserve failures for debugging

    Example:
        orchestrator = AmpOrchestrator()

        # Provision workspace
        config = WorkspaceConfig(
            run_id="run-123",
            scope="org:tenant-abc",
            github_repo="owner/repo",
        )
        info = await orchestrator.provision_workspace(config)

        # Execute commands
        output, code = await orchestrator.exec_in_workspace("run-123", "python main.py")

        # Send heartbeats during execution
        await orchestrator.send_heartbeat("run-123")

        # Cleanup when done
        await orchestrator.cleanup_workspace("run-123")
    """

    def __init__(
        self,
        podman: Optional[PodmanClient] = None,
        state: Optional[StateStore] = None,
        hooks: Optional[OrchestratorHooks] = None,
        quota_service: Optional[QuotaService] = None,
        quota_resolver: Optional[Callable[[str], QuotaLimits]] = None,
    ):
        """Initialize the orchestrator.

        Args:
            podman: Podman client for container operations
            state: State store for workspace tracking
            hooks: Optional hooks for telemetry/compliance
            quota_service: QuotaService for plan-based limits (preferred)
            quota_resolver: DEPRECATED - use quota_service instead
        """
        self._podman = podman
        self._state = state
        self._hooks = hooks or OrchestratorHooks()
        self._quota_service = quota_service
        # Backward compat: support old quota_resolver
        self._quota_resolver = quota_resolver

    async def _get_quota_service(self) -> QuotaService:
        """Lazy-init QuotaService."""
        if self._quota_service is None:
            self._quota_service = get_quota_service()
        return self._quota_service

    async def _get_podman(self) -> PodmanClient:
        """Lazy-init Podman client."""
        if self._podman is None:
            self._podman = PodmanClient()
        return self._podman

    async def _get_state(self) -> StateStore:
        """Lazy-init state store."""
        if self._state is None:
            redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            try:
                self._state = RedisStateStore(redis_url)
                if await self._state.health_check():
                    logger.info("Using RedisStateStore for workspace state")
                else:
                    raise Exception("Redis not available")
            except Exception:
                logger.warning("Redis not available, using InMemoryStateStore")
                self._state = InMemoryStateStore()
        return self._state

    async def provision_workspace(self, config: WorkspaceConfig) -> WorkspaceInfo:
        """Provision an isolated container workspace for agent execution.

        Args:
            config: Workspace configuration

        Returns:
            WorkspaceInfo with container details

        Raises:
            QuotaExceededError: If tenant quota is exceeded
            ProvisionError: If provisioning fails
        """
        podman = await self._get_podman()
        state_store = await self._get_state()

        # Check quota
        await self._enforce_quota(config.scope)

        # Build container labels
        labels = {
            "amprealize.run_id": config.run_id,
            "amprealize.scope": config.scope,
            "amprealize.type": "agent-workspace",
            **(config.labels or {}),
        }
        if config.project_id:
            labels["amprealize.project_id"] = config.project_id
        if config.agent_id:
            labels["amprealize.agent_id"] = config.agent_id

        # Build environment
        env = {
            "AMPREALIZE_RUN_ID": config.run_id,
            "AMPREALIZE_SCOPE": config.scope,
            "WORKSPACE_PATH": config.workdir,
            **(config.environment or {}),
        }

        container_name = f"workspace-{config.run_id}"

        try:
            # Create initial state record
            workspace_state = WorkspaceState(
                run_id=config.run_id,
                container_id="",  # Will be filled after creation
                container_name=container_name,
                status=WorkspaceStatus.PROVISIONING,
                scope=config.scope,
                created_at=datetime.now(timezone.utc).isoformat(),
                workspace_path=config.workdir,
                memory_limit=config.memory_limit,
                cpu_limit=config.cpu_limit,
                timeout_seconds=config.timeout_seconds,
                project_id=config.project_id,
                agent_id=config.agent_id,
                github_repo=config.github_repo,
                labels=labels,
            )
            await state_store.set(workspace_state)

            # Create container (don't set workdir - it may not exist in base image)
            container_id = await podman.create_container(
                name=container_name,
                image=config.image,
                environment=env,
                labels=labels,
                memory_limit=config.memory_limit,
                cpu_limit=config.cpu_limit,
                # Note: workdir not set here - we create it after container starts
            )

            # Update state with container ID
            workspace_state.container_id = container_id
            workspace_state.status = WorkspaceStatus.READY
            await state_store.set(workspace_state)

            # Create workspace directory (may not exist in base image)
            await podman.exec_run(container_name, f"mkdir -p {config.workdir}")

            # Clone repo if specified
            if config.github_repo:
                await self._clone_repo(
                    container_name=container_name,
                    repo=config.github_repo,
                    token=config.github_token,
                    branch=config.github_branch,
                    workdir=config.workdir,
                )

            # Update status to running
            workspace_state.status = WorkspaceStatus.RUNNING
            workspace_state.last_heartbeat = datetime.now(timezone.utc).isoformat()
            await state_store.set(workspace_state)

            info = WorkspaceInfo.from_state(workspace_state)

            # Hook for telemetry
            if self._hooks.on_workspace_provisioned:
                try:
                    self._hooks.on_workspace_provisioned(config, info)
                except Exception as e:
                    logger.warning(f"Hook on_workspace_provisioned failed: {e}")

            logger.info(f"Provisioned workspace: {config.run_id} (container={container_id})")
            return info

        except Exception as e:
            # Mark as failed
            workspace_state.status = WorkspaceStatus.FAILED
            workspace_state.error_message = str(e)
            await state_store.set(workspace_state)

            # Cleanup partial container
            try:
                await podman.remove_container(container_name, force=True)
            except Exception:
                pass

            raise ProvisionError(f"Failed to provision workspace {config.run_id}: {e}") from e

    async def _clone_repo(
        self,
        container_name: str,
        repo: str,
        token: Optional[str],
        branch: str,
        workdir: str,
    ) -> None:
        """Clone a GitHub repository into the workspace."""
        podman = await self._get_podman()

        # Build clone URL
        if token:
            clone_url = f"https://x-access-token:{token}@github.com/{repo}.git"
        else:
            clone_url = f"https://github.com/{repo}.git"

        # Clone command
        clone_cmd = f"git clone --depth 1 --branch {branch} {clone_url} {workdir}/repo"

        output, exit_code = await podman.exec_run(container_name, clone_cmd)
        if exit_code != 0:
            logger.warning(f"Git clone failed: {output}")
            # Don't fail provisioning, repo might not be needed

    async def exec_in_workspace(
        self,
        run_id: str,
        command: str,
        timeout: Optional[int] = None,
        workdir: Optional[str] = None,
    ) -> Tuple[str, int]:
        """Execute command in workspace container.

        Args:
            run_id: Run ID of the workspace
            command: Shell command to execute
            timeout: Optional timeout in seconds
            workdir: Optional working directory override

        Returns:
            Tuple of (output, exit_code)

        Raises:
            WorkspaceNotFoundError: If workspace doesn't exist
        """
        podman = await self._get_podman()
        state_store = await self._get_state()

        state = await state_store.get(run_id)
        if not state:
            raise WorkspaceNotFoundError(run_id)

        return await podman.exec_run(
            state.container_name,
            command,
            timeout=timeout or state.timeout_seconds,
            workdir=workdir or state.workspace_path,
        )

    async def send_heartbeat(self, run_id: str) -> bool:
        """Update heartbeat timestamp for zombie detection.

        Args:
            run_id: Run ID of the workspace

        Returns:
            True if heartbeat was updated
        """
        state_store = await self._get_state()
        return await state_store.update_heartbeat(run_id, datetime.now(timezone.utc))

    async def get_workspace_info(self, run_id: str) -> Optional[WorkspaceInfo]:
        """Get workspace info by run ID.

        Args:
            run_id: Run ID of the workspace

        Returns:
            WorkspaceInfo or None if not found
        """
        state_store = await self._get_state()
        state = await state_store.get(run_id)
        if state:
            return WorkspaceInfo.from_state(state)
        return None

    async def cleanup_workspace(
        self,
        run_id: str,
        retain_on_failure: bool = True,
        retention_hours: int = 24,
    ) -> bool:
        """Cleanup workspace container.

        Args:
            run_id: Run ID of the workspace
            retain_on_failure: Keep failed workspaces for debugging
            retention_hours: Hours to retain failed workspaces

        Returns:
            True if workspace was cleaned up
        """
        podman = await self._get_podman()
        state_store = await self._get_state()

        state = await state_store.get(run_id)
        if not state:
            return False  # Already cleaned up

        # Mark as cleaning
        state.status = WorkspaceStatus.CLEANING
        await state_store.set(state)

        # Check if we should retain for debugging
        if retain_on_failure and state.status == WorkspaceStatus.FAILED:
            logger.info(f"Retaining failed workspace for debugging: {run_id}")
            # Don't delete container or state, just leave it for inspection
            return False

        # Remove container
        try:
            await podman.remove_container(state.container_name, force=True)
        except Exception as e:
            logger.warning(f"Failed to remove container for {run_id}: {e}")

        # Delete state
        await state_store.delete(run_id)

        # Hook for telemetry
        if self._hooks.on_workspace_cleaned:
            try:
                self._hooks.on_workspace_cleaned(run_id)
            except Exception as e:
                logger.warning(f"Hook on_workspace_cleaned failed: {e}")

        logger.info(f"Cleaned up workspace: {run_id}")
        return True

    async def cleanup_zombies(self, max_idle_seconds: int = 120) -> List[str]:
        """Find and terminate zombie workspaces.

        Zombies are workspaces in RUNNING state that haven't sent a
        heartbeat within max_idle_seconds.

        Args:
            max_idle_seconds: Maximum idle time before considering zombie

        Returns:
            List of cleaned up run IDs
        """
        podman = await self._get_podman()
        state_store = await self._get_state()

        zombies = await state_store.find_stale(max_idle_seconds)
        cleaned = []

        for state in zombies:
            logger.warning(f"Terminating zombie workspace: {state.run_id}")

            # Hook for alerting
            if self._hooks.on_zombie_detected:
                try:
                    self._hooks.on_zombie_detected(state.run_id)
                except Exception as e:
                    logger.warning(f"Hook on_zombie_detected failed: {e}")

            # Force remove container
            try:
                await podman.remove_container(state.container_name, force=True)
            except Exception as e:
                logger.warning(f"Failed to remove zombie container {state.run_id}: {e}")

            # Delete state
            await state_store.delete(state.run_id)
            cleaned.append(state.run_id)

        if cleaned:
            logger.info(f"Cleaned up {len(cleaned)} zombie workspaces")

        return cleaned

    async def _enforce_quota(self, scope: str) -> None:
        """Check tenant quota before provisioning.

        Uses QuotaService to resolve plan-based limits, falling back
        to legacy quota_resolver if provided for backward compatibility.

        Args:
            scope: Tenant scope (org:id or user:id)

        Raises:
            QuotaExceededError: If quota is exceeded
        """
        state_store = await self._get_state()
        current = await state_store.count_by_scope(scope)

        # Resolve limits using QuotaService or legacy resolver
        if self._quota_resolver:
            # Backward compat: use old resolver
            limits = self._quota_resolver(scope)
        else:
            # Use QuotaService (preferred)
            quota_service = await self._get_quota_service()
            limits = await quota_service.get_limits_for_scope(scope)

        if current >= limits.max_concurrent_workspaces:
            # Hook for alerting
            if self._hooks.on_quota_exceeded:
                try:
                    self._hooks.on_quota_exceeded(scope, current, limits.max_concurrent_workspaces)
                except Exception as e:
                    logger.warning(f"Hook on_quota_exceeded failed: {e}")

            raise QuotaExceededError(scope, current, limits.max_concurrent_workspaces)

    async def get_limits(self, scope: str) -> QuotaLimits:
        """Get quota limits for a scope.

        Args:
            scope: Tenant scope (org:id or user:id)

        Returns:
            QuotaLimits for the scope
        """
        if self._quota_resolver:
            return self._quota_resolver(scope)
        quota_service = await self._get_quota_service()
        return await quota_service.get_limits_for_scope(scope)

    async def list_workspaces(self, scope: Optional[str] = None) -> List[WorkspaceInfo]:
        """List workspaces, optionally filtered by scope.

        Args:
            scope: Optional scope filter

        Returns:
            List of WorkspaceInfo
        """
        state_store = await self._get_state()

        if scope:
            states = await state_store.list_by_scope(scope)
        else:
            states = await state_store.list_all()

        return [WorkspaceInfo.from_state(s) for s in states]

    async def write_file(self, run_id: str, path: str, content: str) -> bool:
        """Write a file to the workspace.

        Args:
            run_id: Run ID of the workspace
            path: File path inside workspace
            content: File content

        Returns:
            True if successful
        """
        podman = await self._get_podman()
        state_store = await self._get_state()

        state = await state_store.get(run_id)
        if not state:
            raise WorkspaceNotFoundError(run_id)

        return await podman.write_file(state.container_name, path, content)

    async def read_file(self, run_id: str, path: str) -> Optional[str]:
        """Read a file from the workspace.

        Args:
            run_id: Run ID of the workspace
            path: File path inside workspace

        Returns:
            File content or None if not found
        """
        podman = await self._get_podman()
        state_store = await self._get_state()

        state = await state_store.get(run_id)
        if not state:
            raise WorkspaceNotFoundError(run_id)

        return await podman.read_file(state.container_name, path)

    async def close(self) -> None:
        """Close connections and cleanup resources."""
        if self._podman:
            await self._podman.close()
        if self._state and hasattr(self._state, 'close'):
            await self._state.close()


# Module-level singleton for convenience
_default_orchestrator: Optional[AmpOrchestrator] = None


def get_orchestrator() -> AmpOrchestrator:
    """Get the default orchestrator instance (singleton).

    Returns:
        AmpOrchestrator instance
    """
    global _default_orchestrator
    if _default_orchestrator is None:
        _default_orchestrator = AmpOrchestrator()
    return _default_orchestrator
