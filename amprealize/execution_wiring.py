"""Execution Wiring - Connects AgentExecutionLoop with WorkItemExecutionService.

This module provides factory functions to create and wire together the execution
components needed for agent work item execution:

- WorkItemExecutionService: Orchestrates work item execution
- AgentExecutionLoop: Drives phase-by-phase GEP execution
- AgentLLMClient: Handles LLM calls for agent reasoning
- ToolExecutor: Executes tool calls with permission enforcement

Usage during API/MCP initialization:

    from amprealize.execution_wiring import wire_execution_service

    service = wire_execution_service(
        dsn=execution_dsn,
        board_service=board_service,
        run_service=run_service,
        telemetry=telemetry,
    )

See WORK_ITEM_EXECUTION_PLAN.md for full specification.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from .run_service import RunService
from .services.board_service import BoardService
from .task_cycle_service import TaskCycleService
from .telemetry import TelemetryClient
from .work_item_execution_contracts import ExecutionPolicy

logger = logging.getLogger(__name__)


def _create_credential_resolver_from_store(
    credential_store: Any,
) -> Callable[[str, Optional[str], Optional[str]], Optional[str]]:
    """Create a credential resolver function that uses the CredentialStore.

    This returns a function that can resolve API keys for providers using
    the CredentialStore's credential resolution logic (project -> org -> platform).

    Args:
        credential_store: CredentialStore instance from WorkItemExecutionService

    Returns:
        Credential resolver function (provider, project_id, org_id) -> api_key
    """
    def resolver(
        provider: str,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> Optional[str]:
        """Resolve API key for a provider using CredentialStore."""
        # Map provider name to a model_id from that provider to use resolution
        provider_to_model = {
            "anthropic": "claude-sonnet-4-5",
            "openai": "gpt-4o",
            "openrouter": "claude-sonnet-4-5",  # Use any model for OpenRouter
        }

        model_id = provider_to_model.get(provider)
        if not model_id:
            return None

        result = credential_store.get_credential_for_model(model_id, project_id, org_id)
        if result:
            api_key, source, is_byok = result
            logger.debug(f"Resolved credential for {provider}: source={source}, byok={is_byok}")
            return api_key
        return None

    return resolver


# Type alias for credential resolvers - supports both simple (provider) and
# context-aware (provider, project_id, org_id) signatures
CredentialResolver = Callable[..., Optional[str]]


def wire_execution_service(
    *,
    dsn: Optional[str] = None,
    board_service: Optional[BoardService] = None,
    run_service: Optional[RunService] = None,
    task_cycle_service: Optional[TaskCycleService] = None,
    telemetry: Optional[TelemetryClient] = None,
    credential_resolver: Optional[CredentialResolver] = None,
    tool_registry: Optional[Dict[str, Any]] = None,
    bci_service: Optional[Any] = None,  # BCIService for EKA
    enable_early_retrieval: Optional[bool] = None,  # Override EKA config
    gate_notifier: Optional[Any] = None,  # GateNotifier for gate event notifications
) -> Any:
    """Create and wire a fully-configured WorkItemExecutionService.

    This function creates all the execution components and wires them together:

    1. Creates WorkItemExecutionService
    2. Creates AgentExecutionLoop
    3. Creates LLMClient
    4. Wires: WorkItemExecutionService.set_execution_loop(loop)
    5. Wires: AgentExecutionLoop.set_llm_client(client)

    Note: ToolExecutor is created per-execution with the specific ExecutionPolicy,
    so it's not pre-wired here but set during each execution run.

    Args:
        dsn: PostgreSQL connection string for execution state
        board_service: Service for board/work item operations (shared instance)
        run_service: Service for run tracking (shared instance)
        task_cycle_service: Service for GEP phase management
        telemetry: Telemetry client for event emission
        credential_resolver: Function to resolve LLM API keys
        tool_registry: Registry of tool schemas for LLM calls

    Returns:
        Fully wired WorkItemExecutionService instance
    """
    from .agent_execution_loop import AgentExecutionLoop
    from .llm import LLMClient
    from .work_item_execution_service import WorkItemExecutionService

    logger.info("Wiring execution service components...")

    # Create the task cycle service if not provided
    if task_cycle_service is None:
        from .storage.postgres_pool import PostgresPool
        pool = PostgresPool(dsn) if dsn else None
        task_cycle_service = TaskCycleService(pool=pool)

    # Create the run service if not provided - prefer PostgreSQL when DSN is available
    if run_service is None:
        if dsn:
            from .run_service_postgres import PostgresRunService
            run_service = PostgresRunService(dsn=dsn, telemetry=telemetry)
            logger.info("Created PostgresRunService with PostgreSQL backend")
        else:
            run_service = RunService()
            logger.warning("No DSN provided - using SQLite RunService (not recommended for production)")

    # Create the main service
    service = WorkItemExecutionService(
        dsn=dsn,
        board_service=board_service,
        run_service=run_service,
        task_cycle_service=task_cycle_service,
        telemetry=telemetry,
    )
    logger.info("Created WorkItemExecutionService")

    # Create credential resolver from service's credential store if not provided
    if credential_resolver is None and service._credential_store is not None:
        credential_resolver = _create_credential_resolver_from_store(service._credential_store)
        logger.info("Created credential resolver from WorkItemExecutionService's CredentialStore")

    # Create the LLM client
    llm_client = LLMClient(
        credential_resolver=credential_resolver,
        tool_registry=tool_registry,
    )
    logger.info("Created LLMClient")

    # Create BCIService for Early Knowledge Alignment if not provided
    if bci_service is None:
        try:
            from .bci_service import BCIService
            from .behavior_service import BehaviorService
            behavior_service = BehaviorService()
            bci_service = BCIService(
                behavior_service=behavior_service,
                telemetry=telemetry,
            )
            logger.info("Created BCIService for EKA")
        except Exception as e:
            logger.warning(f"Could not create BCIService for EKA: {e}")
            bci_service = None

    # Create the execution loop with EKA support
    execution_loop = AgentExecutionLoop(
        run_service=run_service,
        task_cycle_service=task_cycle_service,
        llm_client=llm_client,
        telemetry=telemetry,
        bci_service=bci_service,
        enable_early_retrieval=enable_early_retrieval,
        gate_notifier=gate_notifier,
    )
    logger.info(f"Created AgentExecutionLoop (EKA enabled: {execution_loop._enable_early_retrieval})")

    # Wire them together
    service.set_execution_loop(execution_loop)
    logger.info("Wired AgentExecutionLoop into WorkItemExecutionService")

    logger.info("Execution service wiring complete")
    return service


def wire_execution_loop(
    *,
    dsn: Optional[str] = None,
    run_service: Optional[RunService] = None,
    task_cycle_service: Optional[TaskCycleService] = None,
    telemetry: Optional[TelemetryClient] = None,
    credential_resolver: Optional[CredentialResolver] = None,
    tool_registry: Optional[Dict[str, Any]] = None,
    bci_service: Optional[Any] = None,  # BCIService for EKA
    enable_early_retrieval: Optional[bool] = None,  # Override EKA config
) -> Any:
    """Create and wire a standalone AgentExecutionLoop with LLM client.

    Use this when you need just the execution loop without the full service,
    for example when the WorkItemExecutionService is already created.

    Args:
        dsn: PostgreSQL connection string for PostgresRunService
        run_service: Service for run tracking
        task_cycle_service: Service for GEP phase management
        telemetry: Telemetry client
        credential_resolver: Function to resolve LLM API keys
        tool_registry: Registry of tool schemas
        bci_service: BCIService for Early Knowledge Alignment (EKA)
        enable_early_retrieval: Override AMPREALIZE_ENABLE_EARLY_RETRIEVAL env var

    Returns:
        AgentExecutionLoop with LLM client and EKA wired
    """
    from .agent_execution_loop import AgentExecutionLoop
    from .llm import LLMClient

    # Create LLM client
    llm_client = LLMClient(
        credential_resolver=credential_resolver,
        tool_registry=tool_registry,
    )

    # Create run service if not provided - prefer PostgreSQL when DSN is available
    if run_service is None:
        if dsn:
            from .run_service_postgres import PostgresRunService
            run_service = PostgresRunService(dsn=dsn, telemetry=telemetry)
            logger.info("Created PostgresRunService for wire_execution_loop")
        else:
            run_service = RunService()
            logger.warning("No DSN provided - using SQLite RunService")

    # Create BCIService for EKA if not provided
    if bci_service is None:
        try:
            from .bci_service import BCIService
            from .behavior_service import BehaviorService
            behavior_service = BehaviorService()
            bci_service = BCIService(
                behavior_service=behavior_service,
                telemetry=telemetry,
            )
            logger.info("Created BCIService for EKA in wire_execution_loop")
        except Exception as e:
            logger.warning(f"Could not create BCIService for EKA: {e}")
            bci_service = None

    # Create execution loop with LLM client and EKA support
    execution_loop = AgentExecutionLoop(
        run_service=run_service,
        task_cycle_service=task_cycle_service or TaskCycleService(),
        llm_client=llm_client,
        telemetry=telemetry,
        bci_service=bci_service,
        enable_early_retrieval=enable_early_retrieval,
    )

    return execution_loop


def create_tool_executor_for_run(
    policy: ExecutionPolicy,
    *,
    mcp_client: Optional[Any] = None,
    project_root: Optional[str] = None,
    telemetry: Optional[TelemetryClient] = None,
    pr_context: Optional[Any] = None,
    github_service: Optional[Any] = None,
    github_context: Optional[Dict[str, Any]] = None,
    workspace_info: Optional[Any] = None,
    workspace_manager: Optional[Any] = None,
) -> Any:
    """Create a ToolExecutor for a specific execution run.

    ToolExecutor is created per-run because it needs the ExecutionPolicy
    which varies by work item, agent, and project settings.

    This factory is the shared entrypoint for both direct mode
    (WorkItemExecutionService) and queue mode (ExecutionWorker),
    ensuring cross-surface parity per COLLAB_SAAS_REQUIREMENTS.md.

    Args:
        policy: Execution policy for this run (permissions, write scope, etc.)
        mcp_client: MCP client for remote tool execution
        project_root: Project root directory for path resolution
        telemetry: Telemetry client
        pr_context: PRExecutionContext for file change accumulation
        github_service: GitHubService for GitHub API fallback tools
        github_context: Context for GitHub API (repo, project_id, org_id, user_id)
        workspace_info: WorkspaceInfo for container-based execution
        workspace_manager: AmprealizeWorkspaceClient for workspace operations

    Returns:
        ToolExecutor configured for the run
    """
    from .tool_executor import ToolExecutor

    return ToolExecutor(
        policy=policy,
        mcp_client=mcp_client,
        project_root=project_root,
        telemetry=telemetry,
        pr_context=pr_context,
        github_service=github_service,
        github_context=github_context,
        workspace_info=workspace_info,
        workspace_manager=workspace_manager,
    )


def wire_execution_gateway(
    *,
    dsn: Optional[str] = None,
    board_service: Optional[BoardService] = None,
    run_service: Optional[RunService] = None,
    task_cycle_service: Optional[TaskCycleService] = None,
    telemetry: Optional[TelemetryClient] = None,
    credential_resolver: Optional[CredentialResolver] = None,
    bci_service: Optional[Any] = None,
    enable_early_retrieval: Optional[bool] = None,
    gate_notifier: Optional[Any] = None,
    agent_registry: Optional[Any] = None,
    settings_service: Optional[Any] = None,
    orchestrator: Optional[Any] = None,
    github_service: Optional[Any] = None,
    github_credential_store: Optional[Any] = None,
    gitlab_credential_store: Optional[Any] = None,
    gitlab_host: str = "gitlab.com",
) -> Any:
    """Create a fully-wired ExecutionGateway with registered mode executors.

    This is the new entry point (Phase 1+2 of E3 rearchitecture) that
    builds an ExecutionGateway alongside the legacy WorkItemExecutionService
    returned by ``wire_execution_service``.

    Args:
        dsn: PostgreSQL connection string.
        board_service: BoardService for work item lookup.
        run_service: RunService for run tracking.
        task_cycle_service: TaskCycleService for GEP phases.
        telemetry: TelemetryClient for event emission.
        credential_resolver: LLM API key resolver.
        bci_service: BCIService for EKA.
        enable_early_retrieval: Override env var for EKA.
        gate_notifier: GateNotifier for gate events.
        agent_registry: AgentRegistryService for agent lookup.
        settings_service: SettingsService for project-level config.
        orchestrator: AmpOrchestrator (or AmprealizeWorkspaceClient).
        github_service: GitHubService for token/PR resolution (legacy).
        github_credential_store: GitHubCredentialStore for SourceProvider.
        gitlab_credential_store: Credential store with get_gitlab_token().
        gitlab_host: Default GitLab host for SourceProvider.

    Returns:
        Fully wired ExecutionGateway instance.
    """
    from .execution_gateway import ExecutionGateway
    from .mode_executors import (
        ContainerConnectedExecutor,
        ContainerIsolatedExecutor,
        LocalDirectExecutor,
    )
    from .source_providers import build_source_provider_registry

    logger.info("Wiring ExecutionGateway components...")

    # --- Ensure core services exist ---
    if task_cycle_service is None:
        from .storage.postgres_pool import PostgresPool
        pool = PostgresPool(dsn) if dsn else None
        task_cycle_service = TaskCycleService(pool=pool)

    if run_service is None:
        if dsn:
            from .run_service_postgres import PostgresRunService
            run_service = PostgresRunService(dsn=dsn, telemetry=telemetry)
        else:
            run_service = RunService()

    # --- Credential store ---
    # If no credential_resolver was passed we still need a CredentialStore
    # instance for the gateway's _resolve_model().  Build one from the
    # WorkItemExecutionService module.
    credential_store = None
    if agent_registry is None or credential_resolver is None:
        try:
            from .work_item_execution_service import CredentialStore
            credential_store = CredentialStore(dsn=dsn)
        except Exception as e:
            logger.warning(f"Could not create CredentialStore: {e}")

    if agent_registry is None:
        try:
            from .agent_registry_service import AgentRegistryService
            agent_registry = AgentRegistryService(dsn=dsn, telemetry=telemetry)
        except Exception as e:
            logger.warning(f"Could not create AgentRegistryService: {e}")

    # --- Build execution loop factory ---
    def _loop_factory(resolved: Any) -> Any:
        return wire_execution_loop(
            dsn=dsn,
            run_service=run_service,
            task_cycle_service=task_cycle_service,
            telemetry=telemetry,
            credential_resolver=credential_resolver,
            bci_service=bci_service,
            enable_early_retrieval=enable_early_retrieval,
        )

    # --- Build gateway ---
    gateway = ExecutionGateway(
        board_service=board_service,
        run_service=run_service,
        task_cycle_service=task_cycle_service,
        agent_registry=agent_registry,
        credential_store=credential_store,
        telemetry=telemetry,
        execution_loop_factory=_loop_factory,
        settings_service=settings_service,
    )

    # --- Build source provider registry (Phase 2) ---
    source_providers = build_source_provider_registry(
        github_credential_store=github_credential_store,
        gitlab_credential_store=gitlab_credential_store,
        gitlab_host=gitlab_host,
    )
    logger.info(
        f"Built source provider registry: "
        f"{[st.value for st in source_providers.keys()]}"
    )

    # --- Register mode executors ---
    if orchestrator is not None:
        gateway.register_executor(
            ContainerIsolatedExecutor(
                orchestrator, github_service,
                source_providers=source_providers,
            )
        )
        gateway.register_executor(
            ContainerConnectedExecutor(
                orchestrator, github_service,
                source_providers=source_providers,
            )
        )
        logger.info("Registered CONTAINER_ISOLATED and CONTAINER_CONNECTED executors")
    else:
        logger.warning(
            "No orchestrator provided — container-based execution modes "
            "will not be available."
        )

    gateway.register_executor(LocalDirectExecutor())
    logger.info("Registered LOCAL_DIRECT executor")

    logger.info("ExecutionGateway wiring complete")
    return gateway
