"""Execution worker process for processing agent execution jobs.

This module provides the ExecutionWorker class that:
1. Consumes jobs from the execution queue (Redis Streams)
2. Provisions isolated workspaces via BreakerAmp
3. Runs the AgentExecutionLoop
4. Cleans up workspaces after execution
5. Reports results and handles failures

Run as a standalone process:
    python -m amprealize.execution_worker
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional
from uuid import uuid4

if TYPE_CHECKING:
    from amprealize.agent_registry_contracts import Agent, AgentVersion
    from amprealize.work_item_execution_contracts import ExecutionPolicy

# Execution queue imports
from execution_queue import (
    ExecutionJob,
    ExecutionQueueConsumer,
    ExecutionResult,
    ExecutionStatus,
    Priority,
)

# BreakerAmp orchestrator imports
from breakeramp import (
    AmpOrchestrator,
    WorkspaceConfig,
    WorkspaceInfo,
    get_orchestrator,
    OrchestratorError,
    QuotaExceededError,
)

# Prometheus metrics
from amprealize.execution_metrics import (
    record_job_processed,
    record_job_duration,
    set_jobs_in_progress,
    record_workspace_provisioned,
    record_workspace_cleaned,
    set_worker_info,
)

logger = logging.getLogger(__name__)


@dataclass
class WorkerConfig:
    """Configuration for the execution worker."""

    # Redis connection
    redis_url: str = field(
        default_factory=lambda: os.environ.get("REDIS_URL", "redis://localhost:6379")
    )

    # Consumer group settings
    consumer_group: str = "execution-workers"
    consumer_name: Optional[str] = None  # Auto-generated if None

    # Queue settings
    stream_prefix: str = "amprealize:executions"
    block_ms: int = 5000
    batch_size: int = 1
    max_retries: int = 3

    # Heartbeat settings
    heartbeat_interval_seconds: int = 30

    # Feature flags
    provision_workspace: bool = True  # Set False to run without BreakerAmp

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        """Create config from environment variables."""
        return cls(
            redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379"),
            consumer_group=os.environ.get("EXECUTION_CONSUMER_GROUP", "execution-workers"),
            consumer_name=os.environ.get("EXECUTION_CONSUMER_NAME"),
            stream_prefix=os.environ.get("EXECUTION_QUEUE_PREFIX", "amprealize:executions"),
            block_ms=int(os.environ.get("EXECUTION_BLOCK_MS", "5000")),
            max_retries=int(os.environ.get("EXECUTION_MAX_RETRIES", "3")),
            heartbeat_interval_seconds=int(os.environ.get("HEARTBEAT_INTERVAL", "30")),
            provision_workspace=os.environ.get("PROVISION_WORKSPACE", "true").lower() == "true",
        )


class ExecutionWorker:
    """Worker that consumes and executes agent jobs from the queue.

    Lifecycle:
    1. Start → connects to Redis, ensures consumer groups exist
    2. Consume loop → claims jobs, processes them, acks/nacks
    3. For each job:
       a. Provision workspace (BreakerAmp container)
       b. Load agent, work item, execution policy
       c. Run AgentExecutionLoop
       d. Cleanup workspace
       e. Report result
    4. Stop → graceful shutdown, finishes current job

    Example:
        worker = ExecutionWorker(config)
        await worker.start()  # Blocks until stopped
    """

    def __init__(
        self,
        config: Optional[WorkerConfig] = None,
        # Inject dependencies for testing
        run_service: Optional[Any] = None,
        task_cycle_service: Optional[Any] = None,
        work_item_service: Optional[Any] = None,
        agent_service: Optional[Any] = None,
        orchestrator: Optional[Any] = None,
    ):
        """Initialize the worker.

        Args:
            config: Worker configuration
            run_service: RunService for run tracking
            task_cycle_service: TaskCycleService for phase management
            work_item_service: Service for loading work items
            agent_service: Service for loading agents
            orchestrator: AmpOrchestrator for workspace management
        """
        self.config = config or WorkerConfig.from_env()

        # Consumer
        self._consumer: Optional[ExecutionQueueConsumer] = None

        # Injected services (lazy-loaded if not provided)
        self._run_service = run_service
        self._task_cycle_service = task_cycle_service
        self._work_item_service = work_item_service
        self._agent_service = agent_service
        self._orchestrator = orchestrator

        # State
        self._running = False
        self._current_job: Optional[ExecutionJob] = None
        self._heartbeat_task: Optional[asyncio.Task] = None

        # Metrics (optional prometheus)
        self._jobs_processed = 0
        self._jobs_succeeded = 0
        self._jobs_failed = 0

    async def start(self) -> None:
        """Start the worker and begin consuming jobs.

        This is a blocking call that runs until stop() is called.
        Starts:
        - Consumer loop (job processing)
        - ZombieReaper background task (stale workspace cleanup)
        """
        logger.info(
            "Starting ExecutionWorker",
            extra={
                "consumer_group": self.config.consumer_group,
                "consumer_name": self.config.consumer_name,
                "redis_url": self.config.redis_url,
            },
        )

        self._running = True

        # Initialize consumer
        self._consumer = ExecutionQueueConsumer(
            redis_url=self.config.redis_url,
            consumer_group=self.config.consumer_group,
            consumer_name=self.config.consumer_name,
            stream_prefix=self.config.stream_prefix,
            block_ms=self.config.block_ms,
            batch_size=self.config.batch_size,
            max_retries=self.config.max_retries,
        )

        # Load services if not injected
        await self._ensure_services()

        # Set worker info metric
        worker_id = self.config.consumer_name or f"worker-{os.getpid()}"
        set_worker_info(
            worker_id=worker_id,
            consumer_group=self.config.consumer_group,
        )

        # Start ZombieReaper as background task if workspace provisioning enabled
        reaper_task = None
        if self.config.provision_workspace and self._orchestrator:
            try:
                from amprealize.zombie_reaper import ZombieReaper, ZombieReaperConfig
                reaper_config = ZombieReaperConfig(
                    check_interval_seconds=60,
                    max_idle_seconds=self.config.heartbeat_interval_seconds * 4,
                )
                self._zombie_reaper = ZombieReaper(self._orchestrator, reaper_config)
                reaper_task = asyncio.create_task(self._zombie_reaper.run())
                logger.info("Started ZombieReaper background task")
            except Exception as e:
                logger.warning(f"Could not start ZombieReaper: {e}")

        # Start consuming
        try:
            await self._consumer.consume(self._handle_job)
        finally:
            # Stop zombie reaper
            if reaper_task and hasattr(self, '_zombie_reaper'):
                self._zombie_reaper.stop()
                try:
                    await reaper_task
                except (asyncio.CancelledError, Exception):
                    pass
            await self._cleanup()

    async def stop(self) -> None:
        """Signal the worker to stop after current job."""
        logger.info("Stopping ExecutionWorker...")
        self._running = False
        if self._consumer:
            self._consumer.stop()
        if self._heartbeat_task:
            self._heartbeat_task.cancel()

    async def _cleanup(self) -> None:
        """Cleanup resources on shutdown."""
        if self._consumer:
            await self._consumer.close()

    async def _ensure_services(self) -> None:
        """Lazy-load services if not injected.

        Initializes all services the worker needs for full-parity execution:
        - PostgreSQL pool for database access
        - RunService for run tracking
        - TaskCycleService for GEP phase management
        - BoardService for work item operations + completion handlers
        - AgentRegistryService for loading agents
        - AmpOrchestrator for workspace management
        - TelemetryClient for structured event emission
        - BCIService for Early Knowledge Alignment (behavior retrieval)
        """
        # Initialize PostgreSQL pool for database access
        if not hasattr(self, '_pool') or self._pool is None:
            from amprealize.storage.postgres_pool import PostgresPool
            from amprealize.utils.dsn import apply_host_overrides

            dsn = apply_host_overrides(
                os.environ.get("DATABASE_URL"),
                "WORKER"
            )
            if dsn:
                self._pool = PostgresPool(dsn)
            else:
                self._pool = None

        if self._run_service is None:
            from amprealize.run_service import RunService
            from amprealize.run_service_postgres import PostgresRunService
            from amprealize.utils.dsn import apply_host_overrides

            # Try service-specific DSN first, then DATABASE_URL fallback
            dsn = apply_host_overrides(
                os.environ.get("AMPREALIZE_RUN_PG_DSN") or os.environ.get("DATABASE_URL"),
                "RUN"
            )
            if dsn:
                self._run_service = PostgresRunService(dsn=dsn)
            else:
                self._run_service = RunService()

        if self._task_cycle_service is None:
            from amprealize.task_cycle_service import TaskCycleService
            self._task_cycle_service = TaskCycleService()

        # Initialize board service for loading work items + completion handlers
        if self._work_item_service is None:
            from amprealize.services.board_service import BoardService
            self._work_item_service = BoardService(pool=self._pool)

        # Initialize agent registry for loading agents
        if self._agent_service is None:
            from amprealize.agent_registry_service import AgentRegistryService
            self._agent_service = AgentRegistryService(pool=self._pool)

        if self._orchestrator is None and self.config.provision_workspace:
            # Initialize orchestrator (uses REDIS_URL env var internally)
            self._orchestrator = get_orchestrator()

        # Initialize TelemetryClient for structured event emission
        if not hasattr(self, '_telemetry') or self._telemetry is None:
            try:
                from amprealize.telemetry import TelemetryClient
                self._telemetry = TelemetryClient()
                logger.info("Initialized TelemetryClient for worker")
            except Exception as e:
                logger.warning(f"Could not create TelemetryClient: {e}")
                from amprealize.telemetry import TelemetryClient
                self._telemetry = TelemetryClient.noop()

        # Initialize BCIService for Early Knowledge Alignment
        if not hasattr(self, '_bci_service') or self._bci_service is None:
            try:
                from amprealize.bci_service import BCIService
                from amprealize.behavior_service import BehaviorService
                behavior_service = BehaviorService()
                self._bci_service = BCIService(
                    behavior_service=behavior_service,
                    telemetry=self._telemetry,
                )
                logger.info("Initialized BCIService for EKA in worker")
            except Exception as e:
                logger.warning(f"Could not create BCIService for EKA: {e}")
                self._bci_service = None

    async def _handle_job(self, job: ExecutionJob) -> ExecutionResult:
        """Handle a single execution job.

        This is the main job processing logic:
        1. Start heartbeat
        2. Provision workspace
        3. Load context (agent, work item, etc.)
        4. Run execution loop
        5. Cleanup workspace
        6. Return result
        """
        self._current_job = job
        self._jobs_processed += 1
        started_at = datetime.now(timezone.utc)

        workspace_info = None
        error_message = None
        status = ExecutionStatus.SUCCESS

        logger.info(
            f"Processing job {job.job_id}",
            extra={
                "job_id": job.job_id,
                "run_id": job.run_id,
                "work_item_id": job.work_item_id,
                "agent_id": job.agent_id,
                "scope": job.get_isolation_scope(),
                "timeout_seconds": job.timeout_seconds,
            },
        )

        # Start heartbeat
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(job.run_id)
        )

        # Track in-progress metric
        set_jobs_in_progress(self.config.consumer_name or f"worker-{os.getpid()}", 1)

        try:
            # Step 1: Provision workspace (if enabled globally AND required by policy)
            # Research agents set require_workspace=False to use local project directory
            context = await self._load_execution_context(job)
            logger.info(f"Context loaded for job {job.job_id}, keys={list(context.keys())}")
            exec_policy = context["exec_policy"]
            logger.info(f"exec_policy type={type(exec_policy).__name__}, require_workspace={exec_policy.require_workspace}")

            if self.config.provision_workspace and exec_policy.require_workspace and self._orchestrator:
                try:
                    workspace_info = await self._provision_workspace(job)
                except Exception as prov_err:
                    # Graceful degradation: if workspace provisioning fails
                    # (e.g., image pull issues in dev), continue without a workspace.
                    # The agent will use the mounted project directory instead.
                    logger.warning(
                        f"Workspace provisioning failed for job {job.job_id}, "
                        f"continuing without isolated workspace: {prov_err}"
                    )
                    workspace_info = None

            logger.info(f"About to enter _run_execution_loop for job {job.job_id}")
            # Step 2: Run execution loop with timeout
            try:
                result = await asyncio.wait_for(
                    self._run_execution_loop(job, context, workspace_info),
                    timeout=job.timeout_seconds,
                )

                if result.get("error"):
                    status = ExecutionStatus.FAILURE
                    error_message = result.get("error")
                else:
                    self._jobs_succeeded += 1

            except asyncio.TimeoutError:
                status = ExecutionStatus.TIMEOUT
                error_message = f"Execution timed out after {job.timeout_seconds} seconds"
                logger.warning(f"Job {job.job_id} timed out")
                self._jobs_failed += 1

        except asyncio.CancelledError:
            status = ExecutionStatus.CANCELLED
            error_message = "Execution cancelled"
            logger.info(f"Job {job.job_id} cancelled")
            raise  # Re-raise to let consumer handle

        except Exception as e:
            status = ExecutionStatus.FAILURE
            error_message = str(e)
            logger.exception(f"Job {job.job_id} failed: {e}")
            self._jobs_failed += 1

        finally:
            # Cancel heartbeat
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
                try:
                    await self._heartbeat_task
                except asyncio.CancelledError:
                    pass

            # Clear in-progress metric
            set_jobs_in_progress(self.config.consumer_name or f"worker-{os.getpid()}", 0)

            # Step 4: Cleanup workspace
            if workspace_info and self._orchestrator:
                await self._cleanup_workspace(
                    job,
                    workspace_info,
                    preserve_on_failure=(status != ExecutionStatus.SUCCESS),
                )

            self._current_job = None

        completed_at = datetime.now(timezone.utc)

        # Record metrics
        scope = job.get_isolation_scope()
        duration = (completed_at - started_at).total_seconds()
        record_job_processed(status=status.value, scope=scope)
        record_job_duration(scope=scope, duration_seconds=duration)

        return ExecutionResult(
            job_id=job.job_id,
            run_id=job.run_id,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            error_message=error_message,
        )

    async def _heartbeat_loop(self, run_id: str) -> None:
        """Send periodic heartbeats while processing a job.

        Heartbeats update the run's last_heartbeat timestamp so the
        zombie reaper knows this job is still active. Also updates
        the orchestrator state for workspace zombie detection.
        """
        while True:
            try:
                await asyncio.sleep(self.config.heartbeat_interval_seconds)

                # Update orchestrator workspace heartbeat
                if self._orchestrator:
                    try:
                        await self._orchestrator.send_heartbeat(run_id)
                    except Exception as e:
                        logger.warning(f"Orchestrator heartbeat failed for {run_id}: {e}")

                # Update run service heartbeat
                if self._run_service:
                    # Update run metadata with heartbeat
                    from amprealize.run_contracts import RunProgressUpdate
                    self._run_service.update_run(
                        run_id,
                        RunProgressUpdate(
                            metadata={"last_heartbeat": datetime.now(timezone.utc).isoformat()},
                        ),
                    )

                logger.debug(f"Heartbeat sent for run {run_id}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Heartbeat failed for run {run_id}: {e}")

    async def _provision_workspace(self, job: ExecutionJob) -> Optional[WorkspaceInfo]:
        """Provision an isolated workspace for the job.

        Uses BreakerAmp orchestrator to create a container with:
        - Resource limits based on tenant plan
        - Mounted volumes for workspace files
        - Network isolation

        Returns:
            WorkspaceInfo if successful, None if workspace not needed

        Raises:
            QuotaExceededError: If tenant has too many concurrent workspaces
            OrchestratorError: If provisioning fails
        """
        if not self._orchestrator:
            return None

        logger.info(f"Provisioning workspace for job {job.job_id}")

        # Get resource limits based on tenant plan
        # TODO: Load from QuotaService based on org/user plan
        memory_limit = "2g"
        cpu_limit = 2.0

        # Get repo URL if work item has one
        github_repo = job.payload.get("repo_url") or job.payload.get("github_repo")
        github_branch = job.payload.get("repo_branch") or job.payload.get("github_branch", "main")
        github_token = job.payload.get("github_token")

        logger.info(f"Workspace provisioning - github_repo={github_repo}, branch={github_branch}")

        # Resolve GitHub token if repo specified but token not provided
        if github_repo and not github_token:
            try:
                from amprealize.services.github_service import GitHubCredentialStore
                credential_store = GitHubCredentialStore(pool=self._pool)
                resolved_token = credential_store.get_resolved_token(
                    project_id=job.project_id,
                    org_id=job.org_id,
                    user_id=job.user_id,
                )
                if resolved_token:
                    github_token = resolved_token.token
                    logger.info(f"Resolved GitHub token from '{resolved_token.source}' for workspace clone")
                else:
                    logger.warning(f"No GitHub token available for project {job.project_id}, repo clone may fail")
            except Exception as e:
                logger.warning(f"Failed to resolve GitHub token: {e}")

        # Create workspace config
        config = WorkspaceConfig(
            run_id=job.run_id,
            scope=job.get_isolation_scope(),
            memory_limit=memory_limit,
            cpu_limit=cpu_limit,
            timeout_seconds=job.timeout_seconds,
            github_repo=github_repo,
            github_branch=github_branch,
            github_token=github_token,
            project_id=job.project_id,
            agent_id=job.agent_id,
            user_id=job.user_id,
            environment={
                "AMPREALIZE_RUN_ID": job.run_id,
                "AMPREALIZE_WORK_ITEM_ID": job.work_item_id,
                "AMPREALIZE_AGENT_ID": job.agent_id,
                "AMPREALIZE_PROJECT_ID": job.project_id or "",
            },
        )

        try:
            workspace_info = await self._orchestrator.provision_workspace(config)

            # Record provisioning metric
            record_workspace_provisioned(scope=job.get_isolation_scope())

            logger.info(
                f"Workspace provisioned for job {job.job_id}",
                extra={
                    "container_id": workspace_info.container_id,
                    "workspace_path": workspace_info.workspace_path,
                },
            )

            return workspace_info

        except QuotaExceededError as e:
            logger.warning(
                f"Quota exceeded for job {job.job_id}: {e}",
                extra={"scope": job.get_isolation_scope()},
            )
            raise
        except OrchestratorError as e:
            logger.error(f"Failed to provision workspace for job {job.job_id}: {e}")
            raise

    async def _load_execution_context(self, job: ExecutionJob) -> Dict[str, Any]:
        """Load all context needed for execution.

        Loads from database services:
        - work_item: The WorkItem being executed
        - agent: The Agent to run
        - agent_version: Active agent version with playbook
        - exec_policy: Execution policy based on agent type
        - cycle_id: TaskCycle ID (created if not exists)
        - model_id: Selected model (from override or agent default)

        Returns:
            Dict with all execution context

        Raises:
            ValueError: If work item or agent cannot be loaded
        """
        from amprealize.agent_registry_contracts import Agent, AgentVersion
        from amprealize.work_item_execution_contracts import ExecutionPolicy
        from amprealize.task_cycle_contracts import CreateCycleRequest

        # Load work item
        work_item = None
        if self._work_item_service and job.work_item_id:
            try:
                work_item = self._work_item_service.get_work_item(
                    item_id=job.work_item_id,
                )
            except Exception as e:
                logger.error(f"Failed to load work item {job.work_item_id}: {e}")

        if not work_item:
            raise ValueError(f"Work item {job.work_item_id} not found")

        # Load agent and active version
        agent = None
        agent_version = None
        if self._agent_service and job.agent_id:
            try:
                result = self._agent_service.get_agent(job.agent_id)
                if result:
                    agent_dict = result.get("agent")
                    versions = result.get("versions", [])
                    if agent_dict:
                        agent = Agent(**agent_dict) if isinstance(agent_dict, dict) else agent_dict
                        # Find active version
                        for v in versions:
                            if isinstance(v, dict):
                                v_clean = {k: val for k, val in v.items() if k != "version_id"}
                                v_obj = AgentVersion(**v_clean)
                            else:
                                v_obj = v
                            if getattr(v_obj, "is_active", False) or v_obj.status == "ACTIVE":
                                agent_version = v_obj
                                break
            except Exception as e:
                logger.error(f"Failed to load agent {job.agent_id}: {e}")

        if not agent:
            raise ValueError(f"Agent {job.agent_id} not found")

        # Get execution policy based on agent type
        exec_policy = self._get_agent_execution_policy(agent, agent_version)

        # Get or create task cycle
        # Use top-level cycle_id first, then fall back to payload for backwards compat
        cycle_id = job.cycle_id or job.payload.get("cycle_id")
        if not cycle_id:
            try:
                cycle_response = self._task_cycle_service.create_cycle(
                    CreateCycleRequest(
                        task_id=job.work_item_id,  # Work item ID serves as task ID
                        assigned_agent_id=job.agent_id,
                        requester_entity_id=job.user_id,
                        requester_entity_type="user",
                    )
                )
                if cycle_response.cycle:
                    cycle_id = cycle_response.cycle.cycle_id
                    logger.info(f"Created task cycle {cycle_id} for job {job.job_id}")
                else:
                    raise ValueError(f"Failed to create task cycle: {cycle_response.error}")
            except Exception as e:
                logger.error(f"Failed to create task cycle: {e}")
                raise

        # Determine model ID
        model_id = job.model_override
        if not model_id and agent_version:
            model_id = agent_version.metadata.get("model_id")
        if not model_id:
            model_id = os.environ.get("AMPREALIZE_DEFAULT_MODEL", "claude-sonnet-4-20250514")

        # Resolve agent execution mode from job payload
        agent_execution_mode = None
        exec_mode_str = job.payload.get("agent_execution_mode")
        if exec_mode_str:
            from amprealize.work_item_execution_contracts import AgentExecutionMode
            try:
                agent_execution_mode = AgentExecutionMode(exec_mode_str)
            except ValueError:
                logger.warning(f"Invalid agent_execution_mode in job payload: {exec_mode_str}")

        return {
            "run_id": job.run_id,
            "cycle_id": cycle_id,
            "work_item": work_item,
            "agent": agent,
            "agent_version": agent_version,
            "exec_policy": exec_policy,
            "model_id": model_id,
            "user_id": job.user_id,
            "org_id": job.org_id,
            "project_id": job.project_id,
            "agent_execution_mode": agent_execution_mode,
        }

    def _get_agent_execution_policy(
        self,
        agent: "Agent",
        agent_version: "AgentVersion | None",
    ) -> "ExecutionPolicy":
        """Get execution policy based on agent type.

        Uses agent-specific presets:
        - Research agents: skip TESTING/FIXING/VERIFYING phases
        - Architect agents: skip TESTING/FIXING phases
        - Engineering agents: run all phases with strict verification
        """
        from amprealize.work_item_execution_contracts import ExecutionPolicy

        if not agent_version:
            return ExecutionPolicy()

        # Check for explicit policy in metadata
        policy_data = agent_version.metadata.get("execution_policy", {})
        if policy_data:
            return ExecutionPolicy.from_dict(policy_data)

        # Use presets based on agent name/slug
        agent_id_lower = (agent.agent_id or "").lower()
        agent_slug = agent_version.metadata.get("slug", "").lower()
        agent_name_lower = (agent.name or "").lower()

        # Research agents
        if any(x in y for x in ["research", "ai_research"] for y in [agent_id_lower, agent_slug, agent_name_lower]):
            logger.info(f"Using research agent preset for {agent.agent_id}")
            return ExecutionPolicy.for_research_agent()

        # Architect agents
        if any(x in y for x in ["architect", "architecture"] for y in [agent_id_lower, agent_slug, agent_name_lower]):
            logger.info(f"Using architect agent preset for {agent.agent_id}")
            return ExecutionPolicy.for_architect_agent()

        # Engineering agents
        if any(x in y for x in ["engineer", "developer", "coding"] for y in [agent_id_lower, agent_slug, agent_name_lower]):
            logger.info(f"Using engineering agent preset for {agent.agent_id}")
            return ExecutionPolicy.for_engineering_agent()

        # Default: fully autonomous
        return ExecutionPolicy.fully_autonomous()

    async def _run_execution_loop(
        self,
        job: ExecutionJob,
        context: Dict[str, Any],
        workspace_info: Optional[WorkspaceInfo],
    ) -> Dict[str, Any]:
        """Run the AgentExecutionLoop with full tool execution support.

        This achieves full parity with direct mode (WorkItemExecutionService._run_execution_loop):
        - LLM calls via AgentLLMClient with credential resolution
        - ToolExecutor with workspace context and permission enforcement
        - PR mode with GitHub service for write_scope == PR_ONLY / LOCAL_AND_PR
        - BCIService for Early Knowledge Alignment (behavior retrieval)
        - Phase transitions (PLANNING → EXECUTING → COMPLETING)

        Design principles (per COLLAB_SAAS_REQUIREMENTS.md):
        - Cross-surface parity: queue mode produces identical results to direct mode
        - Audit trail: every agent action is traceable via telemetry and run service
        - Programmatic access: identical API/MCP semantics regardless of execution mode

        Args:
            job: The execution job
            context: Execution context with work_item, agent, exec_policy, etc.
            workspace_info: Workspace container info (optional, for sandboxed execution)

        Returns:
            Dict with execution result (status, outputs, error)
        """
        from amprealize.agent_execution_loop import AgentExecutionLoop
        from amprealize.work_item_execution_service import CredentialStore
        from amprealize.work_item_execution_contracts import WriteScope

        run_id = context["run_id"]
        cycle_id = context["cycle_id"]
        work_item = context["work_item"]
        agent = context["agent"]
        agent_version = context.get("agent_version")
        exec_policy = context["exec_policy"]
        model_id = context["model_id"]
        user_id = context["user_id"]
        org_id = context.get("org_id")
        project_id = context.get("project_id")

        logger.info(
            f"_run_execution_loop: extracted all context for job {job.job_id}, "
            f"exec_policy type={type(exec_policy).__name__}, "
            f"work_item type={type(work_item).__name__}, "
            f"agent type={type(agent).__name__}"
        )

        logger.info(
            f"Starting AgentExecutionLoop for job {job.job_id}",
            extra={
                "run_id": run_id,
                "agent_id": agent.agent_id,
                "model_id": model_id,
                "skip_phases": list(exec_policy.skip_phases) if exec_policy.skip_phases else [],
                "has_workspace": workspace_info is not None,
                "write_scope": exec_policy.write_scope.value if hasattr(exec_policy.write_scope, 'value') else str(exec_policy.write_scope),
            },
        )

        # =====================================================================
        # 1. Resolve LLM credentials
        # Priority: BYOK (project → org) → platform env vars
        # =====================================================================
        api_key = None
        credential_source = "unknown"
        credential_store = CredentialStore(pool=self._pool)

        try:
            resolved = credential_store.get_credential_for_model(
                model_id=model_id,
                project_id=project_id,
                org_id=org_id,
            )
            if resolved:
                api_key, credential_source, _is_byok = resolved
                logger.info(f"Resolved API key from {credential_source} for model {model_id}")
        except Exception as e:
            logger.warning(f"Failed to resolve credential from store: {e}")

        # Fallback to environment variables
        if not api_key:
            if "claude" in model_id.lower() or "anthropic" in model_id.lower():
                api_key = os.environ.get("ANTHROPIC_API_KEY")
                credential_source = "env:ANTHROPIC_API_KEY"
            elif "gpt" in model_id.lower() or "openai" in model_id.lower():
                api_key = os.environ.get("OPENAI_API_KEY")
                credential_source = "env:OPENAI_API_KEY"
            else:
                api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")
                credential_source = "env:fallback"

        if not api_key:
            error_msg = f"No API key available for model {model_id}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}

        logger.info(f"Using API key from {credential_source} for model {model_id}")

        # =====================================================================
        # 2. Create credential resolver for LLM client
        # =====================================================================
        def credential_resolver(provider: str) -> Optional[str]:
            """Resolve API key for the matching provider."""
            if provider == "anthropic" and "claude" in model_id.lower():
                return api_key
            elif provider == "openai" and "gpt" in model_id.lower():
                return api_key
            env_vars = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
            env_var = env_vars.get(provider)
            return os.environ.get(env_var) if env_var else None

        try:
            from amprealize.llm import LLMClient
            llm_client = LLMClient(
                credential_resolver=credential_resolver,
            )
        except Exception as e:
            error_msg = f"Failed to create LLM client: {e}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}

        # =====================================================================
        # 3. Set up PR context if write scope requires PR creation
        # (Parity with WorkItemExecutionService._setup_pr_context)
        # =====================================================================
        pr_context = None
        github_service = None

        if exec_policy.write_scope in (WriteScope.PR_ONLY, WriteScope.LOCAL_AND_PR):
            try:
                pr_context = await self._setup_pr_context(
                    work_item=work_item,
                    run_id=run_id,
                    project_id=project_id,
                    org_id=org_id,
                )
                if pr_context:
                    from amprealize.services.github_service import GitHubService
                    github_service = GitHubService(pool=self._pool)
                    logger.info(
                        f"PR mode enabled for run {run_id}: "
                        f"branch={pr_context.branch_name}, repo={pr_context.repo}"
                    )
            except Exception as e:
                logger.warning(f"Failed to set up PR context for run {run_id}: {e}")

        # =====================================================================
        # 4. Resolve GitHub repo for API fallback tools
        # =====================================================================
        github_repo = job.payload.get("github_repo")
        if not github_repo and project_id:
            try:
                github_repo = await self._resolve_project_repo(project_id)
            except Exception as e:
                logger.warning(f"Could not resolve GitHub repo for project {project_id}: {e}")

        # =====================================================================
        # 5. Create ToolExecutor with full context
        # (Parity with WorkItemExecutionService._run_execution_loop)
        # Per COLLAB_SAAS_REQUIREMENTS.md: cross-surface parity - queue mode
        # must produce identical tool execution behavior as direct mode
        # =====================================================================
        workspace_path = workspace_info.workspace_path if workspace_info else None

        from amprealize.tool_executor import ToolExecutor
        tool_executor = ToolExecutor(
            policy=exec_policy,
            telemetry=self._telemetry,
            project_root=workspace_path or (work_item.project_id if hasattr(work_item, 'project_id') else None),
            pr_context=pr_context,
            github_service=github_service,
            github_context={
                "repo": github_repo,
                "project_id": project_id,
                "org_id": org_id,
                "user_id": user_id,
            } if github_repo else None,
            workspace_info=workspace_info,
        )

        # =====================================================================
        # 6. Create execution loop with EKA (BCIService) support
        # =====================================================================
        execution_loop = AgentExecutionLoop(
            run_service=self._run_service,
            task_cycle_service=self._task_cycle_service,
            llm_client=llm_client,
            tool_executor=tool_executor,
            telemetry=self._telemetry,
            bci_service=getattr(self, '_bci_service', None),
        )

        # Wire PR context and GitHub service on the loop
        if pr_context and github_service:
            execution_loop.set_github_service(github_service)
            execution_loop.set_pr_context(pr_context)

        logger.info(
            f"Created full execution pipeline for run {run_id}: "
            f"tool_executor=✓, pr_context={'✓' if pr_context else '✗'}, "
            f"workspace={'✓' if workspace_info else '✗'}, "
            f"bci={'✓' if getattr(self, '_bci_service', None) else '✗'}"
        )

        # =====================================================================
        # 7. Run the execution loop
        # =====================================================================
        try:
            result = await execution_loop.run(
                run_id=run_id,
                cycle_id=cycle_id,
                work_item=work_item,
                agent=agent,
                agent_version=agent_version,
                exec_policy=exec_policy,
                model_id=model_id,
                user_id=user_id,
                org_id=org_id,
                project_id=project_id,
                execution_mode=context.get("agent_execution_mode"),
            )

            status = result.get("status", "unknown")
            if status == "completed":
                logger.info(f"Execution loop completed successfully for job {job.job_id}")

                # === Completion handler (parity with direct mode) ===
                pr_url = pr_context.pr_url if pr_context else None
                await self._on_execution_complete(
                    run_id=run_id,
                    work_item_id=work_item.item_id,
                    agent_id=agent.agent_id,
                    org_id=org_id,
                    pr_url=pr_url,
                )

                return {"success": True, "result": result}
            elif status == "paused":
                logger.info(f"Execution loop paused (waiting for approval) for job {job.job_id}")
                return {"success": True, "status": "paused", "result": result}
            else:
                error = result.get("error", "Unknown error")
                logger.error(f"Execution loop failed for job {job.job_id}: {error}")

                # === Failure handler (parity with direct mode) ===
                await self._on_execution_failed(
                    run_id=run_id,
                    work_item_id=work_item.item_id,
                    agent_id=agent.agent_id,
                    error=error,
                    org_id=org_id,
                )

                return {"success": False, "error": error, "result": result}

        except Exception as e:
            logger.exception(f"Execution loop error for job {job.job_id}: {e}")

            # === Failure handler on exception ===
            await self._on_execution_failed(
                run_id=run_id,
                work_item_id=work_item.item_id if hasattr(work_item, 'item_id') else job.work_item_id,
                agent_id=agent.agent_id if hasattr(agent, 'agent_id') else job.agent_id,
                error=str(e),
                org_id=org_id,
            )

            return {"success": False, "error": str(e)}

    # =========================================================================
    # PR Context Setup (parity with WorkItemExecutionService._setup_pr_context)
    # =========================================================================

    async def _setup_pr_context(
        self,
        work_item: Any,
        run_id: str,
        project_id: Optional[str],
        org_id: Optional[str],
    ) -> Optional[Any]:
        """Set up PR context for PR-mode execution.

        Resolves the project's GitHub repository and creates a PRExecutionContext
        with a unique branch name for this execution.
        """
        try:
            from amprealize.work_item_execution_contracts import PRExecutionContext
            from amprealize.work_item_execution_service import generate_pr_branch_name

            if not project_id:
                return None

            repo = await self._resolve_project_repo(project_id)
            if not repo:
                return None

            # Detect default branch from GitHub API
            from amprealize.services.github_service import GitHubService
            github_service = GitHubService(pool=self._pool)
            base_branch = github_service.get_default_branch(
                repo=repo,
                project_id=project_id,
                org_id=org_id,
            )

            branch_name = generate_pr_branch_name(work_item.item_id)

            return PRExecutionContext(
                work_item_id=work_item.item_id,
                run_id=run_id,
                branch_name=branch_name,
                repo=repo,
                base_branch=base_branch,
            )
        except Exception as e:
            logger.warning(f"Failed to setup PR context for run {run_id}: {e}")
            return None

    async def _resolve_project_repo(self, project_id: str) -> Optional[str]:
        """Resolve the GitHub repo (owner/repo) for a project."""
        try:
            query = """
                SELECT
                    settings->>'repository_url' as repo_url,
                    settings->>'github_repo' as github_repo
                FROM auth.projects
                WHERE project_id = %s
            """
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (project_id,))
                    row = cur.fetchone()
                    if row:
                        repo_url = row[0] or row[1]
                        if repo_url:
                            if repo_url.startswith("https://github.com/"):
                                return repo_url.replace("https://github.com/", "").rstrip("/")
                            elif repo_url.startswith("git@github.com:"):
                                return repo_url.replace("git@github.com:", "").replace(".git", "").rstrip("/")
                            return repo_url
        except Exception as e:
            logger.warning(f"Error resolving project repo for {project_id}: {e}")
        return None

    # =========================================================================
    # Completion & Failure Handlers
    # (Parity with WorkItemExecutionService._on_execution_complete/failed)
    # Per COLLAB_SAAS_REQUIREMENTS.md: audit trail for every agent action
    # =========================================================================

    async def _on_execution_complete(
        self,
        run_id: str,
        work_item_id: str,
        agent_id: str,
        org_id: Optional[str],
        pr_url: Optional[str] = None,
    ) -> None:
        """Handle successful execution completion.

        - Post concise summary comment (with PR link if applicable)
        - Move work item to completed column
        - Emit telemetry event
        """
        try:
            run = self._run_service.get_run(run_id)
            summary = self._generate_summary(run)

            if pr_url:
                summary += f"\n\n---\n\n**Pull Request:** [{pr_url}]({pr_url})"

            self._post_work_item_comment(
                work_item_id=work_item_id,
                author_id=agent_id,
                author_type="agent",
                content=summary,
                run_id=run_id,
                org_id=org_id,
            )

            self._move_to_completed(work_item_id, org_id)

            if hasattr(self, '_telemetry') and self._telemetry:
                self._telemetry.emit_event(
                    event_type="work_item.execution.completed",
                    payload={
                        "run_id": run_id,
                        "work_item_id": work_item_id,
                        "agent_id": agent_id,
                        "pr_url": pr_url,
                        "source": "queue_worker",
                    },
                    run_id=run_id,
                )

        except Exception as e:
            logger.exception(f"Error in completion handler for run {run_id}: {e}")

    async def _on_execution_failed(
        self,
        run_id: str,
        work_item_id: str,
        agent_id: str,
        error: str,
        org_id: Optional[str],
    ) -> None:
        """Handle execution failure.

        - Post error summary as comment
        - Update run status to FAILED
        - Emit telemetry event
        """
        try:
            self._post_work_item_comment(
                work_item_id=work_item_id,
                author_id=agent_id,
                author_type="agent",
                content=f"## Execution Failed\n\n**Error:** {error}\n\n**Run ID:** {run_id}",
                run_id=run_id,
                org_id=org_id,
            )

            from amprealize.run_contracts import RunProgressUpdate, RunStatus
            self._run_service.update_run(
                run_id,
                RunProgressUpdate(status=RunStatus.FAILED, message=error),
            )

            if hasattr(self, '_telemetry') and self._telemetry:
                self._telemetry.emit_event(
                    event_type="work_item.execution.failed",
                    payload={
                        "run_id": run_id,
                        "work_item_id": work_item_id,
                        "error": error,
                        "source": "queue_worker",
                    },
                    run_id=run_id,
                )

        except Exception as e:
            logger.exception(f"Error in failure handler for run {run_id}: {e}")

    def _post_work_item_comment(
        self,
        work_item_id: str,
        author_id: str,
        author_type: str,
        content: str,
        run_id: Optional[str],
        org_id: Optional[str],
    ) -> None:
        """Post a comment to a work item."""
        try:
            from amprealize.services.board_service import Actor as BoardActor
            actor = BoardActor(id="system", role="system", surface="queue_worker")

            self._work_item_service.add_comment(
                work_item_id=work_item_id,
                author_id=author_id,
                author_type=author_type,
                content=content,
                actor=actor,
                run_id=run_id,
                org_id=org_id,
            )
            logger.info(
                f"Posted comment to work item {work_item_id}: "
                f"{content[:100]}... (author: {author_id})"
            )
        except Exception as e:
            logger.exception(f"Error posting comment to work item {work_item_id}: {e}")

    def _move_to_completed(self, work_item_id: str, org_id: Optional[str]) -> None:
        """Move work item to completed column."""
        try:
            from amprealize.boards.contracts import (
                UpdateWorkItemRequest, WorkItemStatus, MoveWorkItemRequest,
            )
            from amprealize.services.board_service import Actor as BoardActor
            actor = BoardActor(id="system", role="system", surface="queue_worker")

            request = UpdateWorkItemRequest(status=WorkItemStatus.DONE)
            self._work_item_service.update_work_item(
                item_id=work_item_id,
                request=request,
                actor=actor,
                org_id=org_id,
            )

            item = self._work_item_service.get_work_item(work_item_id, org_id=org_id)
            if item.board_id:
                done_column = self._work_item_service.get_column_by_status_mapping(
                    board_id=item.board_id,
                    status_mapping=WorkItemStatus.DONE,
                    org_id=org_id,
                )
                if done_column:
                    move_request = MoveWorkItemRequest(
                        column_id=done_column.column_id,
                        position=0,
                    )
                    self._work_item_service.move_work_item(
                        item_id=work_item_id,
                        request=move_request,
                        actor=actor,
                        org_id=org_id,
                    )
                    logger.info(f"Moved work item {work_item_id} to done column")
        except Exception as e:
            logger.exception(f"Error moving work item {work_item_id} to completed: {e}")

    def _generate_summary(self, run: Any) -> str:
        """Generate a concise execution summary for posting as a comment."""
        lines = ["## Execution Summary\n"]
        lines.append(f"**Status:** {run.status}")

        if hasattr(run, 'duration_ms') and run.duration_ms:
            duration_s = run.duration_ms / 1000
            if duration_s > 60:
                lines.append(f"**Duration:** {duration_s / 60:.1f} minutes")
            else:
                lines.append(f"**Duration:** {duration_s:.1f} seconds")

        if hasattr(run, 'steps') and run.steps:
            lines.append(f"**Steps Completed:** {len(run.steps)}")

        if hasattr(run, 'outputs') and run.outputs:
            lines.append("\n### Outputs")
            if "files_changed" in run.outputs:
                lines.append(f"- Files changed: {run.outputs['files_changed']}")
            if "pr_url" in run.outputs:
                lines.append(f"- PR: {run.outputs['pr_url']}")
            if "summary" in run.outputs:
                lines.append(f"\n{run.outputs['summary']}")

        if hasattr(run, 'error') and run.error:
            lines.append(f"\n### Error\n```\n{run.error}\n```")

        return "\n".join(lines)

    async def _cleanup_workspace(
        self,
        job: ExecutionJob,
        workspace_info: WorkspaceInfo,
        preserve_on_failure: bool = False,
    ) -> None:
        """Cleanup the workspace after execution.

        Args:
            job: The execution job
            workspace_info: Workspace info from provisioning
            preserve_on_failure: Keep workspace for debugging if True
        """
        if not self._orchestrator:
            return

        if preserve_on_failure:
            logger.info(
                f"Preserving workspace for failed job {job.job_id} (will auto-cleanup after timeout)",
                extra={
                    "run_id": job.run_id,
                    "container_id": workspace_info.container_id,
                },
            )
            # Workspace will be cleaned up by zombie reaper after heartbeat timeout
            # We don't remove it immediately to allow debugging
            return

        try:
            logger.info(f"Cleaning up workspace for job {job.job_id}")
            await self._orchestrator.cleanup_workspace(job.run_id)

            # Record cleanup metric
            record_workspace_cleaned(scope=job.get_isolation_scope(), reason="success")

            logger.debug(f"Workspace cleaned up for job {job.job_id}")
        except Exception as e:
            logger.warning(
                f"Failed to cleanup workspace for job {job.job_id}: {e}",
                extra={"run_id": job.run_id},
            )
            # Don't re-raise - cleanup failures shouldn't fail the job


async def main() -> None:
    """Main entry point for running the worker."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    config = WorkerConfig.from_env()
    worker = ExecutionWorker(config)

    # Setup signal handlers
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda s=sig: asyncio.create_task(worker.stop()),
        )

    logger.info("ExecutionWorker starting...")
    await worker.start()
    logger.info("ExecutionWorker stopped")


if __name__ == "__main__":
    asyncio.run(main())
