"""Mode Executor implementations for the Execution Gateway.

Three execution modes, each with a distinct isolation model:

- ContainerIsolatedExecutor: Full Podman sandbox; clone source into container.
- ContainerConnectedExecutor: Podman sandbox with user's project mounted.
- LocalDirectExecutor: No container; direct host filesystem access.

Part of E3 — Agent Execution Loop Rearchitecture (AMPREALIZE-277 / Phases 1+2).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .execution_gateway_contracts import (
    NewExecutionMode,
    ResolvedExecution,
    SourceType,
)
from .work_item_execution_contracts import AgentExecutionMode
from .source_providers import (
    CloneStrategy,
    SourceProvider,
    execute_clone,
    resolve_source_provider,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Container Isolated Executor
# ---------------------------------------------------------------------------


class ContainerIsolatedExecutor:
    """Full sandbox — source cloned into container, no host access.

    This is the default for Web/API/MCP surfaces. The agent runs inside
    a Podman container with the project repository cloned into it.
    Output is delivered via PR, patch file, or archive — never by writing
    to the host filesystem.
    """

    def __init__(
        self,
        orchestrator: Any,
        github_service: Any = None,
        source_providers: Optional[Dict[SourceType, SourceProvider]] = None,
    ) -> None:
        """
        Args:
            orchestrator: AmpOrchestrator (or AmprealizeWorkspaceClient) for
                container lifecycle management.
            github_service: GitHubService for token resolution during clone.
                Deprecated — prefer source_providers.
            source_providers: Registry mapping SourceType -> SourceProvider.
                When provided, used for multi-provider clone instead of
                the legacy GitHub-only path.
        """
        self._orchestrator = orchestrator
        self._github_service = github_service
        self._source_providers = source_providers or {}

    @property
    def mode(self) -> NewExecutionMode:
        return NewExecutionMode.CONTAINER_ISOLATED

    async def provision_workspace(
        self,
        resolved: ResolvedExecution,
    ) -> ResolvedExecution:
        """Provision a Podman container and clone the source into it.

        Uses SourceProvider when available for multi-provider support.
        Falls back to legacy AmpOrchestrator GitHub-only clone if no
        SourceProvider is registered for the source type.
        """
        provider = resolve_source_provider(
            resolved.source_type,
            provider_registry=self._source_providers,
        )

        if provider is not None:
            return await self._provision_with_provider(resolved, provider)

        # Legacy path: GitHub-only via AmpOrchestrator._clone_repo()
        return await self._provision_legacy(resolved)

    async def _provision_with_provider(
        self,
        resolved: ResolvedExecution,
        provider: SourceProvider,
    ) -> ResolvedExecution:
        """Provision container + clone via SourceProvider."""
        from breakeramp import WorkspaceConfig

        scope = self._build_scope(resolved)

        # Provision a bare container (no github_repo — we clone ourselves)
        config = WorkspaceConfig(
            run_id=resolved.run_id,
            scope=scope,
            project_id=resolved.request.project_id,
            agent_id=resolved.agent_id,
            user_id=resolved.request.user_id,
            labels={
                "amprealize.mode": self.mode.value,
                "amprealize.cycle_id": resolved.cycle_id,
                "amprealize.source_type": resolved.source_type.value,
            },
        )

        info = await self._orchestrator.provision_workspace(config)

        resolved.workspace_id = info.run_id
        resolved.workspace_path = info.workspace_path
        resolved.container_id = info.container_id

        # Build clone spec and execute
        clone_spec = provider.build_clone_spec(
            resolved,
            target_dir=f"{info.workspace_path}/repo",
        )

        container_name = f"workspace-{resolved.run_id}"

        async def _exec_in_container(cmd: str):
            return await self._orchestrator.exec_in_workspace(
                resolved.run_id, cmd,
            )

        clone_result = await execute_clone(clone_spec, exec_fn=_exec_in_container)
        if not clone_result.success:
            logger.warning(
                f"Source clone failed for run {resolved.run_id}: "
                f"{clone_result.error}"
            )
            # Don't fail provisioning — source may not be needed for all phases

        return resolved

    async def _provision_legacy(
        self,
        resolved: ResolvedExecution,
    ) -> ResolvedExecution:
        """Legacy GitHub-only provisioning via AmpOrchestrator._clone_repo()."""
        from breakeramp import WorkspaceConfig

        scope = self._build_scope(resolved)
        github_token = self._resolve_github_token(resolved)

        config = WorkspaceConfig(
            run_id=resolved.run_id,
            scope=scope,
            project_id=resolved.request.project_id,
            agent_id=resolved.agent_id,
            user_id=resolved.request.user_id,
            github_repo=resolved.source_url if resolved.source_type == SourceType.GITHUB else None,
            github_token=github_token,
            github_branch=resolved.source_ref,
            labels={
                "amprealize.mode": self.mode.value,
                "amprealize.cycle_id": resolved.cycle_id,
            },
        )

        info = await self._orchestrator.provision_workspace(config)

        resolved.workspace_id = info.run_id
        resolved.workspace_path = info.workspace_path
        resolved.container_id = info.container_id

        return resolved

    async def execute(
        self,
        resolved: ResolvedExecution,
        execution_loop: Any,
        *,
        work_item: Any,
        agent: Any,
        agent_version: Any,
        exec_policy: Any,
    ) -> Dict[str, Any]:
        """Run the agent execution loop inside the container."""
        return await _drive_loop(
            resolved, execution_loop,
            work_item=work_item,
            agent=agent,
            agent_version=agent_version,
            exec_policy=exec_policy,
        )

    async def cleanup(self, resolved: ResolvedExecution) -> None:
        """Remove the container."""
        if resolved.workspace_id:
            try:
                await self._orchestrator.cleanup_workspace(
                    resolved.workspace_id,
                    retain_on_failure=True,
                )
            except Exception as e:
                logger.warning(
                    f"Cleanup failed for container-isolated workspace "
                    f"{resolved.workspace_id}: {e}"
                )

    # -- helpers --

    def _build_scope(self, resolved: ResolvedExecution) -> str:
        if resolved.request.org_id:
            return f"org:{resolved.request.org_id}"
        return f"user:{resolved.request.user_id}"

    def _resolve_github_token(self, resolved: ResolvedExecution) -> Optional[str]:
        """Resolve a GitHub token for cloning the source repository."""
        if resolved.source_type != SourceType.GITHUB or not self._github_service:
            return None
        try:
            token_info = self._github_service.get_resolved_token(
                project_id=resolved.request.project_id,
                org_id=resolved.request.org_id,
                user_id=resolved.request.user_id,
            )
            return token_info.token if token_info else None
        except Exception as e:
            logger.warning(f"GitHub token resolution failed: {e}")
            return None


# ---------------------------------------------------------------------------
# Container Connected Executor
# ---------------------------------------------------------------------------


class ContainerConnectedExecutor:
    """Podman sandbox with the user's local directory mounted.

    Ideal for IDE and CLI usage — the agent runs inside a container but
    can read/write the project directory through a bind mount.  Changes
    appear directly in the user's workspace after execution.
    """

    def __init__(
        self,
        orchestrator: Any,
        github_service: Any = None,
        source_providers: Optional[Dict[SourceType, SourceProvider]] = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._github_service = github_service
        self._source_providers = source_providers or {}

    @property
    def mode(self) -> NewExecutionMode:
        return NewExecutionMode.CONTAINER_CONNECTED

    async def provision_workspace(
        self,
        resolved: ResolvedExecution,
    ) -> ResolvedExecution:
        """Provision a Podman container with the local directory mounted."""
        local_path = resolved.request.workspace_path
        if not local_path or not Path(local_path).is_dir():
            raise ValueError(
                f"CONTAINER_CONNECTED mode requires a valid workspace_path. "
                f"Got: {local_path!r}"
            )

        from breakeramp import WorkspaceConfig
        from breakeramp.runtime.podman import PodmanClient

        scope = self._build_scope(resolved)
        container_workdir = "/workspace"

        # The orchestrator's provision_workspace does not yet support
        # arbitrary volume mounts, so we provision at the Podman level
        # directly, then register the state with the orchestrator for
        # cleanup tracking.
        podman: PodmanClient = await self._orchestrator._get_podman()

        container_name = f"workspace-{resolved.run_id}"
        env = {
            "AMPREALIZE_RUN_ID": resolved.run_id,
            "AMPREALIZE_SCOPE": scope,
            "WORKSPACE_PATH": container_workdir,
        }
        labels = {
            "amprealize.run_id": resolved.run_id,
            "amprealize.scope": scope,
            "amprealize.mode": self.mode.value,
            "amprealize.type": "agent-workspace",
        }

        container_id = await podman.create_container(
            name=container_name,
            environment=env,
            labels=labels,
            volumes={local_path: container_workdir},
        )

        resolved.workspace_id = resolved.run_id
        resolved.workspace_path = container_workdir
        resolved.container_id = container_id

        logger.info(
            f"Connected workspace provisioned: {container_name} "
            f"(mount {local_path} → {container_workdir})"
        )
        return resolved

    async def execute(
        self,
        resolved: ResolvedExecution,
        execution_loop: Any,
        *,
        work_item: Any,
        agent: Any,
        agent_version: Any,
        exec_policy: Any,
    ) -> Dict[str, Any]:
        return await _drive_loop(
            resolved, execution_loop,
            work_item=work_item,
            agent=agent,
            agent_version=agent_version,
            exec_policy=exec_policy,
        )

    async def cleanup(self, resolved: ResolvedExecution) -> None:
        """Remove the container — local directory persists."""
        if not resolved.container_id:
            return
        try:
            from breakeramp.runtime.podman import PodmanClient
            podman: PodmanClient = await self._orchestrator._get_podman()
            container_name = f"workspace-{resolved.run_id}"
            await podman.remove_container(container_name, force=True)
        except Exception as e:
            logger.warning(
                f"Cleanup failed for connected workspace "
                f"{resolved.run_id}: {e}"
            )

    def _build_scope(self, resolved: ResolvedExecution) -> str:
        if resolved.request.org_id:
            return f"org:{resolved.request.org_id}"
        return f"user:{resolved.request.user_id}"


# ---------------------------------------------------------------------------
# Local Direct Executor
# ---------------------------------------------------------------------------


class LocalDirectExecutor:
    """No container — agent operates directly on the host filesystem.

    Only appropriate for trusted local scenarios where the user explicitly
    opts in (CLI ``--local`` flag, IDE setting). The agent runs with the
    same filesystem permissions as the invoking process.
    """

    @property
    def mode(self) -> NewExecutionMode:
        return NewExecutionMode.LOCAL_DIRECT

    async def provision_workspace(
        self,
        resolved: ResolvedExecution,
    ) -> ResolvedExecution:
        """Validate the local path exists. No container to provision."""
        local_path = resolved.request.workspace_path
        if not local_path:
            raise ValueError(
                "LOCAL_DIRECT mode requires a workspace_path in the request."
            )

        real_path = Path(local_path).resolve()
        if not real_path.is_dir():
            raise ValueError(
                f"LOCAL_DIRECT workspace path does not exist: {real_path}"
            )

        resolved.workspace_id = None
        resolved.workspace_path = str(real_path)
        resolved.container_id = None

        logger.info(f"Local workspace validated: {real_path}")
        return resolved

    async def execute(
        self,
        resolved: ResolvedExecution,
        execution_loop: Any,
        *,
        work_item: Any,
        agent: Any,
        agent_version: Any,
        exec_policy: Any,
    ) -> Dict[str, Any]:
        return await _drive_loop(
            resolved, execution_loop,
            work_item=work_item,
            agent=agent,
            agent_version=agent_version,
            exec_policy=exec_policy,
        )

    async def cleanup(self, resolved: ResolvedExecution) -> None:
        """No-op — local filesystem is the user's responsibility."""
        pass


# ---------------------------------------------------------------------------
# Session Mode Executor
# ---------------------------------------------------------------------------


class SessionModeExecutor:
    """Lightweight executor for conversational agent sessions.

    Wraps the standard AgentExecutionLoop but always runs in SESSION mode,
    producing a 3-phase flow: PLANNING → EXECUTING → COMPLETING.

    This executor is surface-agnostic — it can wrap any isolation executor
    (ContainerIsolated, ContainerConnected, LocalDirect) or run standalone
    when no container orchestration is needed.
    """

    def __init__(
        self,
        inner_executor: Any = None,
    ) -> None:
        """
        Args:
            inner_executor: Optional inner executor (ContainerIsolated, etc.)
                for workspace provisioning. When None, assumes workspace is
                already available (e.g., local CLI/IDE).
        """
        self._inner = inner_executor

    async def setup(self, resolved: ResolvedExecution) -> None:
        """Delegate workspace setup to inner executor if present."""
        if self._inner and hasattr(self._inner, "setup"):
            await self._inner.setup(resolved)

    async def execute(
        self,
        resolved: ResolvedExecution,
        execution_loop: Any,
        *,
        work_item: Any,
        agent: Any,
        agent_version: Any,
        exec_policy: Any,
    ) -> Dict[str, Any]:
        return await _drive_loop(
            resolved, execution_loop,
            work_item=work_item,
            agent=agent,
            agent_version=agent_version,
            exec_policy=exec_policy,
            execution_mode=AgentExecutionMode.SESSION,
        )

    async def cleanup(self, resolved: ResolvedExecution) -> None:
        """Delegate cleanup to inner executor if present."""
        if self._inner and hasattr(self._inner, "cleanup"):
            await self._inner.cleanup(resolved)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _drive_loop(
    resolved: ResolvedExecution,
    loop: Any,
    *,
    work_item: Any,
    agent: Any,
    agent_version: Any,
    exec_policy: Any,
    execution_mode: AgentExecutionMode = AgentExecutionMode.GEP,
) -> Dict[str, Any]:
    """Drive the AgentExecutionLoop with the resolved context."""
    return await loop.run(
        run_id=resolved.run_id,
        cycle_id=resolved.cycle_id,
        work_item=work_item,
        agent=agent,
        agent_version=agent_version,
        exec_policy=exec_policy,
        model_id=resolved.model_id,
        user_id=resolved.request.user_id,
        org_id=resolved.request.org_id,
        project_id=resolved.request.project_id,
        execution_mode=execution_mode,
    )
