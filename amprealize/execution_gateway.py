"""Execution Gateway — Unified entry point for agent execution.

The ExecutionGateway replaces the tangled routing logic previously spread across
WorkItemExecutionService.execute() and _run_execution_loop(). It provides a
single entry point that:

1. Validates the request and permissions
2. Resolves execution mode from surface + project settings + overrides
3. Resolves model and credentials (including BYOK)
4. Creates Run + TaskCycle records
5. Delegates workspace provisioning and execution to the appropriate ModeExecutor

All surfaces (API, MCP, CLI, VS Code, Web) call the gateway with an
ExecutionRequest. The gateway is surface-agnostic.

Part of E3 — Agent Execution Loop Rearchitecture (AMPREALIZE-277 / Phase 1).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .action_contracts import Actor
from .execution_gateway_contracts import (
    ExecutionGatewayResult,
    ExecutionRequest,
    ModeExecutor,
    NewExecutionMode,
    OutputTarget,
    ResolvedExecution,
    SourceType,
    resolve_execution_mode,
    resolve_output_target,
)
from .boards.contracts import AssigneeType, WorkItem
from .output_handlers import (
    OutputContext,
    OutputResult,
    OutputStatus,
    get_handler_class,
)
from .run_contracts import RunCreateRequest, RunProgressUpdate
from .task_cycle_contracts import CyclePhase, CreateCycleRequest
from .work_item_execution_contracts import (
    AgentExecutionMode,
    ExecutionPolicy,
    ExecutionState,
)

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class ExecutionGateway:
    """Unified entry point for agent execution across all surfaces.

    The gateway orchestrates:
    - Request validation and permission checks
    - Execution mode resolution
    - Model + credential resolution (BYOK-aware)
    - Run + TaskCycle record creation
    - Delegating to the correct ModeExecutor

    Each ModeExecutor handles its own workspace provisioning, execution,
    and cleanup according to its isolation model.
    """

    def __init__(
        self,
        *,
        board_service: Any,
        run_service: Any,
        task_cycle_service: Any,
        agent_registry: Any,
        credential_store: Any,
        telemetry: Any = None,
        execution_loop_factory: Any = None,
        executors: Optional[Dict[NewExecutionMode, ModeExecutor]] = None,
        settings_service: Any = None,
        github_service: Any = None,
    ) -> None:
        """
        Args:
            board_service: BoardService for work item lookup.
            run_service: RunService for run tracking.
            task_cycle_service: TaskCycleService for GEP phase management.
            agent_registry: AgentRegistryService for agent lookup.
            credential_store: CredentialStore for model/key resolution.
            telemetry: Optional TelemetryClient.
            execution_loop_factory: Callable that builds an AgentExecutionLoop.
            executors: Map of mode -> ModeExecutor. Missing modes will raise
                       at execute time.
            settings_service: SettingsService for project-level settings.
            github_service: GitHubService for PR creation in output handlers.
        """
        self._board = board_service
        self._runs = run_service
        self._cycles = task_cycle_service
        self._agents = agent_registry
        self._creds = credential_store
        self._telemetry = telemetry
        self._loop_factory = execution_loop_factory
        self._executors: Dict[NewExecutionMode, ModeExecutor] = executors or {}
        self._settings = settings_service
        self._github_service = github_service

    # ------------------------------------------------------------------
    # Executor registration
    # ------------------------------------------------------------------

    def register_executor(self, executor: ModeExecutor) -> None:
        """Register a ModeExecutor for its declared mode."""
        self._executors[executor.mode] = executor
        logger.info(f"Registered executor for {executor.mode.value}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(self, request: ExecutionRequest) -> ExecutionGatewayResult:
        """Execute a work item through the full pipeline.

        This is the single entry point that all surfaces call.

        Args:
            request: The execution request with work item ID, surface, overrides.

        Returns:
            ExecutionGatewayResult with run_id, mode, and status.
        """
        try:
            # --- Phase A: Validate ---
            work_item = self._load_work_item(request)
            agent, agent_version = self._load_agent(work_item, request)
            exec_policy = self._resolve_policy(agent_version, request)
            self._check_idempotency(work_item, request)

            # --- Phase B: Resolve execution configuration ---
            mode = self._resolve_mode(request)
            source_type, source_url, source_ref = self._resolve_source(request)
            output_target = resolve_output_target(mode, request.output_target_override, source_type)
            model_id, api_key, cred_source, is_byok = self._resolve_model(
                request, exec_policy,
            )

            # --- Phase C: Create tracking records ---
            run_id, cycle_id = self._create_records(
                request, work_item, agent, agent_version,
                exec_policy, model_id, mode.value,
            )

            # --- Phase D: Build resolved execution ---
            resolved = ResolvedExecution(
                run_id=run_id,
                cycle_id=cycle_id,
                request=request,
                mode=mode,
                output_target=output_target,
                source_type=source_type,
                source_url=source_url,
                source_ref=source_ref or "main",
                model_id=model_id,
                api_key=api_key,
                credential_source=cred_source,
                is_byok=is_byok,
                agent_id=agent.agent_id,
                agent_version_id=agent_version.version_id if agent_version else None,
                playbook=self._extract_playbook(agent_version),
            )

            # --- Phase E: Dispatch to executor ---
            executor = self._executors.get(mode)
            if executor is None:
                raise ValueError(
                    f"No executor registered for mode {mode.value}. "
                    f"Available: {list(self._executors.keys())}"
                )

            # Resolve agent execution mode (GEP vs SESSION)
            agent_exec_mode = request.agent_execution_mode or AgentExecutionMode.GEP

            # Wrap in SessionModeExecutor when session mode requested
            if agent_exec_mode == AgentExecutionMode.SESSION:
                from .mode_executors import SessionModeExecutor
                executor = SessionModeExecutor(inner_executor=executor)
                logger.info(
                    f"Session Mode requested for run {run_id} — "
                    f"wrapping {mode.value} executor in SessionModeExecutor"
                )

            # Link run to work item
            self._link_run_to_work_item(request.work_item_id, run_id, request.org_id)

            # Emit start telemetry
            self._emit_start(resolved, work_item)

            # Launch execution in background
            asyncio.create_task(
                self._run_with_executor(executor, resolved, work_item, agent, agent_version, exec_policy)
            )

            return ExecutionGatewayResult(
                success=True,
                run_id=run_id,
                cycle_id=cycle_id,
                mode=mode,
                output_target=output_target,
                message="Execution started",
            )

        except Exception as e:
            logger.exception(f"Gateway execution failed: {e}")
            return ExecutionGatewayResult(
                success=False,
                error=str(e),
                message=f"Execution failed: {e}",
            )

    # ------------------------------------------------------------------
    # Background execution
    # ------------------------------------------------------------------

    async def _run_with_executor(
        self,
        executor: ModeExecutor,
        resolved: ResolvedExecution,
        work_item: WorkItem,
        agent: Any,
        agent_version: Any,
        exec_policy: ExecutionPolicy,
    ) -> None:
        """Run the full provision → execute → deliver → cleanup lifecycle."""
        try:
            # 1. Provision workspace (SessionModeExecutor uses setup/cleanup)
            if hasattr(executor, "provision_workspace"):
                resolved = await executor.provision_workspace(resolved)
            elif hasattr(executor, "setup"):
                await executor.setup(resolved)
            logger.info(
                f"Workspace provisioned for run {resolved.run_id}: "
                f"mode={resolved.mode.value}, path={resolved.workspace_path}"
            )

            # 2. Initialize output context on the resolved execution
            resolved.output_context = self._init_output_context(resolved, work_item)

            # 3. Build execution loop
            execution_loop = self._build_execution_loop(resolved)

            # 4. Execute
            await executor.execute(
                resolved,
                execution_loop,
                work_item=work_item,
                agent=agent,
                agent_version=agent_version,
                exec_policy=exec_policy,
            )

            # 5. Deliver output via handler (if we have accumulated changes)
            output_result = await self._deliver_output(resolved, work_item)

            # 6. Post-execution success handling
            await self._on_success(resolved, work_item, output_result=output_result)

        except Exception as e:
            logger.exception(f"Execution failed for run {resolved.run_id}: {e}")
            await self._on_failure(resolved, work_item, str(e))

        finally:
            # 7. Cleanup workspace
            try:
                await executor.cleanup(resolved)
            except Exception as cleanup_err:
                logger.warning(
                    f"Cleanup failed for run {resolved.run_id}: {cleanup_err}"
                )

    # ------------------------------------------------------------------
    # Output handling
    # ------------------------------------------------------------------

    def _init_output_context(
        self,
        resolved: ResolvedExecution,
        work_item: WorkItem,
    ) -> OutputContext:
        """Create an OutputContext for accumulating changes during execution."""
        return OutputContext(
            run_id=resolved.run_id,
            work_item_id=resolved.request.work_item_id,
            work_item_title=work_item.title,
            repo=resolved.source_url or "",
            base_branch=resolved.source_ref or "main",
            branch_name=f"amprealize/{resolved.run_id}",
            project_id=resolved.request.project_id,
            org_id=resolved.request.org_id or "",
            workspace_path=resolved.workspace_path,
        )

    def _build_output_handler(self, resolved: ResolvedExecution):
        """Instantiate the appropriate OutputHandler for the output target."""
        from .output_handlers import (
            GitHubPRHandler,
            LocalSyncHandler,
            PatchFileHandler,
        )

        target = resolved.output_target

        if target == OutputTarget.PULL_REQUEST:
            if not self._github_service:
                logger.warning(
                    f"No github_service for PR output (run {resolved.run_id})"
                )
                return None
            return GitHubPRHandler(github_service=self._github_service)

        if target == OutputTarget.PATCH_FILE:
            return PatchFileHandler()

        if target == OutputTarget.LOCAL_SYNC:
            return LocalSyncHandler()

        logger.warning(f"No handler for output target {target.value}")
        return None

    async def _deliver_output(
        self,
        resolved: ResolvedExecution,
        work_item: WorkItem,
    ) -> Optional[OutputResult]:
        """Deliver accumulated output via the appropriate handler.

        Returns the OutputResult or None if no handler / no changes.
        """
        output_ctx = resolved.output_context
        if not output_ctx or not output_ctx.has_changes():
            logger.debug(f"No output changes for run {resolved.run_id}")
            return None

        handler = self._build_output_handler(resolved)
        if handler is None:
            return None

        try:
            result = await handler.deliver(output_ctx)
            logger.info(
                f"Output delivered for run {resolved.run_id}: "
                f"handler={handler.handler_type}, status={result.status.value}, "
                f"files={result.files_changed}"
            )
            return result
        except Exception as e:
            logger.exception(
                f"Output delivery failed for run {resolved.run_id}: {e}"
            )
            return OutputResult(
                status=OutputStatus.FAILED,
                handler_type=handler.handler_type,
                error=str(e),
            )

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _load_work_item(self, request: ExecutionRequest) -> WorkItem:
        """Load and validate the work item."""
        work_item = self._board.get_work_item(
            request.work_item_id,
            org_id=request.org_id,
        )
        if not work_item:
            raise ValueError(f"Work item {request.work_item_id} not found")
        return work_item

    def _load_agent(self, work_item: WorkItem, request: ExecutionRequest):
        """Load the agent assigned to the work item."""
        agent_id = request.agent_id_override or work_item.assignee_id
        if not agent_id:
            raise ValueError(f"Work item {work_item.item_id} has no agent assigned")

        # Validate it's an agent assignment (not a human)
        if not request.agent_id_override and work_item.assignee_type != AssigneeType.AGENT:
            raise ValueError(
                f"Work item {work_item.item_id} is assigned to a "
                f"{work_item.assignee_type}, not an agent"
            )

        agent = self._agents.get_agent(agent_id, org_id=request.org_id)
        if not agent:
            raise ValueError(f"Agent {agent_id} not found")

        # Get latest version
        agent_version = self._agents.get_latest_version(agent_id, org_id=request.org_id)
        return agent, agent_version

    def _resolve_policy(self, agent_version: Any, request: ExecutionRequest) -> ExecutionPolicy:
        """Resolve the execution policy from agent version or defaults."""
        if agent_version and hasattr(agent_version, "execution_policy") and agent_version.execution_policy:
            return agent_version.execution_policy
        return ExecutionPolicy()

    def _check_idempotency(self, work_item: WorkItem, request: ExecutionRequest) -> None:
        """Check if there's already an active execution for this work item."""
        if work_item.run_id:
            try:
                run = self._runs.get_run(work_item.run_id)
                if run and run.status in ("pending", "running", "paused"):
                    raise ValueError(
                        f"Work item {work_item.item_id} already has an active "
                        f"execution: run_id={work_item.run_id}"
                    )
            except Exception:
                pass  # Run not found — safe to proceed

    # ------------------------------------------------------------------
    # Resolution helpers
    # ------------------------------------------------------------------

    def _resolve_mode(self, request: ExecutionRequest) -> NewExecutionMode:
        """Resolve execution mode from request, project settings, and surface."""
        project_mode = None
        if request.project_id and self._settings:
            try:
                settings = self._settings.get_project_settings(request.project_id)
                if hasattr(settings, "execution_mode_v2"):
                    project_mode = settings.execution_mode_v2
            except Exception:
                pass

        return resolve_execution_mode(
            surface=request.surface,
            mode_override=request.mode_override,
            project_mode=project_mode,
        )

    def _resolve_source(self, request: ExecutionRequest):
        """Resolve source type, URL, and ref for workspace provisioning."""
        if request.source_type:
            return request.source_type, request.source_url, request.source_ref

        # Auto-detect from project settings
        if request.project_id and self._settings:
            try:
                settings = self._settings.get_project_settings(request.project_id)
                if hasattr(settings, "github_repo") and settings.github_repo:
                    return SourceType.GITHUB, settings.github_repo, request.source_ref
                if hasattr(settings, "gitlab_repo") and settings.gitlab_repo:
                    return SourceType.GITLAB, settings.gitlab_repo, request.source_ref
            except Exception:
                pass

        # For local workspace path
        if request.workspace_path:
            return SourceType.LOCAL_DIR, request.workspace_path, None

        # Fallback — no source
        return SourceType.LOCAL_DIR, None, None

    def _resolve_model(self, request: ExecutionRequest, policy: ExecutionPolicy):
        """Resolve model ID and credentials.

        Returns:
            (model_id, api_key, credential_source, is_byok)
        """
        # Determine preferred model
        model_id = request.model_override or policy.model_policy.preferred_model_id

        result = self._creds.get_credential_for_model(
            model_id,
            project_id=request.project_id,
            org_id=request.org_id,
        )
        if result:
            api_key, source, is_byok = result
            return model_id, api_key, source, is_byok

        # Try fallbacks
        for fallback in policy.model_policy.fallback_model_ids:
            result = self._creds.get_credential_for_model(
                fallback,
                project_id=request.project_id,
                org_id=request.org_id,
            )
            if result:
                api_key, source, is_byok = result
                return fallback, api_key, source, is_byok

        raise ValueError(
            f"No available model for project {request.project_id}. "
            f"Tried: {model_id}, fallbacks: {policy.model_policy.fallback_model_ids}"
        )

    # ------------------------------------------------------------------
    # Record creation
    # ------------------------------------------------------------------

    def _create_records(
        self,
        request: ExecutionRequest,
        work_item: WorkItem,
        agent: Any,
        agent_version: Any,
        policy: ExecutionPolicy,
        model_id: str,
        mode: str,
    ) -> tuple[str, str]:
        """Create Run and TaskCycle records. Returns (run_id, cycle_id)."""
        actor = Actor(id=request.user_id, role="user", surface=request.surface)

        run = self._runs.create_run(RunCreateRequest(
            actor=actor,
            workflow_name="work_item_execution",
            triggering_user_id=request.user_id,
            metadata={
                "work_item_id": request.work_item_id,
                "agent_id": agent.agent_id,
                "model_id": model_id,
                "project_id": request.project_id,
                "org_id": request.org_id,
                "execution_mode": mode,
                "execution_policy": policy.to_dict() if hasattr(policy, "to_dict") else {},
                "agent_playbook_version": agent_version.version if agent_version else None,
            },
            initial_message=f"Executing work item: {work_item.title}",
        ))

        cycle_resp = self._cycles.create_cycle(CreateCycleRequest(
            task_id=request.work_item_id,
            assigned_agent_id=agent.agent_id,
            requester_entity_id=request.user_id,
            requester_entity_type="user",
            metadata={
                "work_item_id": request.work_item_id,
                "run_id": run.run_id,
                "agent_id": agent.agent_id,
                "model_id": model_id,
            },
        ))

        if not cycle_resp.cycle:
            raise ValueError(
                f"Failed to create TaskCycle for work item {request.work_item_id}"
            )

        cycle_id = cycle_resp.cycle.cycle_id

        # Persist cycle link on the run
        self._runs.update_run(
            run.run_id,
            RunProgressUpdate(metadata={
                "cycle_id": cycle_id,
                "phase": CyclePhase.PLANNING.value,
            }),
        )

        return run.run_id, cycle_id

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_playbook(self, agent_version: Any) -> Dict[str, Any]:
        if agent_version and hasattr(agent_version, "playbook"):
            return agent_version.playbook or {}
        return {}

    def _link_run_to_work_item(
        self,
        work_item_id: str,
        run_id: str,
        org_id: Optional[str],
    ) -> None:
        try:
            self._board.update_work_item(
                work_item_id,
                updates={"run_id": run_id},
                org_id=org_id,
            )
        except Exception as e:
            logger.warning(f"Failed to link run {run_id} to work item {work_item_id}: {e}")

    def _build_execution_loop(self, resolved: ResolvedExecution) -> Any:
        """Build an AgentExecutionLoop for this execution."""
        if self._loop_factory:
            return self._loop_factory(resolved)

        # Fallback: import and build directly
        from .agent_execution_loop import AgentExecutionLoop
        from .llm import LLMClient

        llm_client = LLMClient(
            credential_resolver=lambda provider, **kw: resolved.api_key
            if provider == self._provider_for_model(resolved.model_id) else None,
        )

        loop = AgentExecutionLoop(
            run_service=self._runs,
            task_cycle_service=self._cycles,
            llm_client=llm_client,
            telemetry=self._telemetry,
        )
        return loop

    @staticmethod
    def _provider_for_model(model_id: str) -> Optional[str]:
        from .work_item_execution_contracts import get_model
        m = get_model(model_id)
        return m.provider.value if m else None

    def _emit_start(self, resolved: ResolvedExecution, work_item: WorkItem) -> None:
        if self._telemetry:
            self._telemetry.emit_event(
                event_type="execution.gateway.started",
                payload={
                    "run_id": resolved.run_id,
                    "cycle_id": resolved.cycle_id,
                    "work_item_id": resolved.request.work_item_id,
                    "agent_id": resolved.agent_id,
                    "model_id": resolved.model_id,
                    "mode": resolved.mode.value,
                    "output_target": resolved.output_target.value,
                    "source_type": resolved.source_type.value,
                    "is_byok": resolved.is_byok,
                    "surface": resolved.request.surface,
                },
                run_id=resolved.run_id,
            )

    async def _on_success(
        self,
        resolved: ResolvedExecution,
        work_item: WorkItem,
        output_result: Optional[OutputResult] = None,
    ) -> None:
        """Post-execution success handling."""
        try:
            from .run_contracts import RunProgressUpdate, RunStatus

            metadata: Dict[str, Any] = {}
            if output_result:
                metadata["output"] = output_result.to_dict()

            self._runs.update_run(
                resolved.run_id,
                RunProgressUpdate(
                    status=RunStatus.COMPLETED,
                    metadata=metadata if metadata else None,
                ),
            )
        except Exception as e:
            logger.warning(f"Failed to mark run {resolved.run_id} as completed: {e}")

        if self._telemetry:
            telemetry_payload: Dict[str, Any] = {
                "run_id": resolved.run_id,
                "mode": resolved.mode.value,
            }
            if output_result:
                telemetry_payload["output_handler"] = output_result.handler_type
                telemetry_payload["output_status"] = output_result.status.value
                telemetry_payload["files_changed"] = output_result.files_changed
                if output_result.pr_url:
                    telemetry_payload["pr_url"] = output_result.pr_url

            self._telemetry.emit_event(
                event_type="execution.gateway.completed",
                payload=telemetry_payload,
                run_id=resolved.run_id,
            )

    async def _on_failure(
        self,
        resolved: ResolvedExecution,
        work_item: WorkItem,
        error: str,
    ) -> None:
        """Post-execution failure handling."""
        try:
            from .run_contracts import RunProgressUpdate, RunStatus
            self._runs.update_run(
                resolved.run_id,
                RunProgressUpdate(
                    status=RunStatus.FAILED,
                    metadata={"error": error[:500]},
                ),
            )
        except Exception as e:
            logger.warning(f"Failed to mark run {resolved.run_id} as failed: {e}")

        if self._telemetry:
            self._telemetry.emit_event(
                event_type="execution.gateway.failed",
                payload={
                    "run_id": resolved.run_id,
                    "mode": resolved.mode.value,
                    "error": error[:200],
                },
                run_id=resolved.run_id,
            )
