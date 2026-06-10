"""Work Item Execution Service - Orchestrates agent execution of work items.

Bridges Work Items ↔ RunService ↔ TaskCycleService and drives execution per GEP.
See WORK_ITEM_EXECUTION_PLAN.md for full specification.

Features:
- Validate permissions + project/org tool/model gating
- Resolve assigned agent and load playbook snapshot
- Create Run + TaskCycle linked to work item
- Invoke AgentExecutionLoop until terminal (or enqueue for worker execution)
- Persist logs to RunService and update Work Item/Board state
- Post concise summary comment on completion

Execution Modes:
- EXECUTION_MODE=queue: Enqueue for worker processing (default)
- EXECUTION_MODE=direct: Run inline (legacy, for development)
"""

from __future__ import annotations

import json
import logging
import os
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from dotenv import load_dotenv

from .action_contracts import Actor
from .agent_registry_contracts import Agent, AgentVersion
from .agent_registry_service import AgentRegistryService
from .auth.llm_credential_repository import LLMCredentialRepository
from .boards.contracts import WorkItem, WorkItemStatus, AssigneeType, WorkItemType, validate_research_url
from .run_contracts import Run, RunCreateRequest, RunProgressUpdate, RunStatus, RunStep
from .run_service import RunService, RunNotFoundError
from .services.board_service import BoardService, WorkItemNotFoundError
from .storage.postgres_pool import PostgresPool
from .task_cycle_contracts import (
    CyclePhase,
    CycleResponse,
    CreateCycleRequest,
    GateType,
    PHASE_GATES,
    SubmitClarificationRequest,
    TimeoutConfig,
    TransitionPhaseRequest,
    TriggerType,
)
from .task_cycle_service import TaskCycleService
from .telemetry import TelemetryClient
from .utils.dsn import resolve_postgres_dsn
from .work_item_execution_contracts import (
    AgentExecutionMode,
    AvailableModel,
    ExecuteWorkItemRequest,
    ExecuteWorkItemResponse,
    ExecutionPolicy,
    ExecutionState,
    ExecutionStatusResponse,
    GatePolicyType,
    InternetAccessPolicy,
    MODEL_CATALOG,
    ModelCredential,
    ModelDefinition,
    ModelPolicy,
    PendingFileChange,
    PRCommitStrategy,
    PRExecutionContext,
    WorkItemComment,
    WriteScope,
    generate_pr_branch_name,
    get_model,
)
from .projects.settings import (
    ExecutionMode,
    LOCAL_CAPABLE_SURFACES,
    REMOTE_ONLY_SURFACES,
)
from .resource_analysis import ResourceAnalysisService
from .multi_tenant.settings import SettingsService
from .workspace_agent import (
    AmprealizeWorkspaceClient,
    WorkspaceConfig,
    WorkspaceInfo,
    WorkspaceProvisionError,
    get_workspace_client,
)


logger = logging.getLogger(__name__)

_EXECUTION_PG_DSN_ENV = "AMPREALIZE_EXECUTION_PG_DSN"
_DEFAULT_PG_DSN = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize"


class WorkItemExecutionError(Exception):
    """Base error for work item execution."""
    pass


class WorkItemNotAssignedError(WorkItemExecutionError):
    """Raised when work item has no agent assigned."""
    pass


class AgentNotFoundError(WorkItemExecutionError):
    """Raised when assigned agent cannot be found."""
    pass


class ExecutionAlreadyActiveError(WorkItemExecutionError):
    """Raised when work item already has an active execution."""
    pass


class ModelNotAvailableError(WorkItemExecutionError):
    """Raised when requested model is not available."""
    pass


class InternetAccessDeniedError(WorkItemExecutionError):
    """Raised when internet access is required but disabled."""
    pass


class ExecutionSurfaceRestrictedError(WorkItemExecutionError):
    """Raised when execution surface doesn't support the required execution mode.

    For example, attempting to execute with local write mode from the web UI.
    """
    def __init__(self, message: str, guidance: str):
        super().__init__(message)
        self.guidance = guidance


def _now_iso() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def _short_id(prefix: str) -> str:
    """Generate a short prefixed ID."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class CredentialStore:
    """Manages LLM provider credentials at platform/org/project/user scope.

    Resolution order depends on context:
    - Project/agent execution: project -> user -> org -> platform.
    - Personal chat: user -> org -> platform.
    - If ``prefer_user`` is true: user -> project -> org -> platform.
    """

    def __init__(
        self,
        pool: Optional[PostgresPool] = None,
        credential_repository: Optional["LLMCredentialRepository"] = None,
    ) -> None:
        self._pool = pool
        self._credential_repository = credential_repository
        # In-memory fallback for platform credentials from env
        self._platform_credentials: Dict[str, str] = {}
        self._load_platform_credentials()

    def _load_platform_credentials(self) -> None:
        """Load platform credentials from environment variables."""
        explicit_env_file = os.getenv("AMPREALIZE_ENV_FILE")
        env_paths = [
            Path(explicit_env_file).expanduser() if explicit_env_file else None,
            Path.cwd() / ".env",
            Path(__file__).resolve().parents[1] / ".env",
            Path(__file__).resolve().parents[2] / ".env",
        ]
        for env_path in env_paths:
            if env_path and env_path.exists():
                load_dotenv(env_path, override=False)

        # Load provider API keys from environment
        if api_key := os.getenv("ANTHROPIC_API_KEY"):
            self._platform_credentials["anthropic"] = api_key
        if api_key := os.getenv("OPENAI_API_KEY"):
            self._platform_credentials["openai"] = api_key
        if api_key := os.getenv("OPENROUTER_API_KEY"):
            self._platform_credentials["openrouter"] = api_key
        if api_key := os.getenv("NVIDIA_API_KEY"):
            self._platform_credentials["nvidia"] = api_key
        if api_key := os.getenv("TOGETHER_API_KEY"):
            self._platform_credentials["together"] = api_key
        if api_key := os.getenv("GROQ_API_KEY"):
            self._platform_credentials["groq"] = api_key
        if api_key := os.getenv("FIREWORKS_API_KEY"):
            self._platform_credentials["fireworks"] = api_key

    def _credential_scope_pairs(
        self,
        *,
        project_id: Optional[str],
        org_id: Optional[str],
        user_id: Optional[str],
        prefer_user: bool,
    ) -> List[Tuple[Any, str]]:
        """Return (scope_type, scope_id) tuples in BYOK resolution order."""
        from amprealize.auth.llm_credential_repository import CredentialScopeType

        scope_order: List[Tuple[Any, Optional[str]]] = []
        if prefer_user and user_id:
            scope_order.append((CredentialScopeType.USER, user_id))
        if project_id:
            scope_order.append((CredentialScopeType.PROJECT, project_id))
        if user_id and (CredentialScopeType.USER, user_id) not in scope_order:
            scope_order.append((CredentialScopeType.USER, user_id))
        if org_id:
            scope_order.append((CredentialScopeType.ORG, org_id))
        return [(st, sid) for st, sid in scope_order if sid]

    def credential_blocked_by_invalid_scoped_byok(
        self,
        model_id: str,
        *,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
        prefer_user: bool = False,
    ) -> bool:
        """True when scoped BYOK exists but cannot be used and no credential was resolved.

        Used for error messaging when :meth:`get_credential_for_model` returns
        ``None`` (e.g. broken BYOK and no platform key).
        """
        model = get_model(model_id)
        if not model or not self._credential_repository:
            return False
        provider = model.provider.value
        for scope_type, scope_id in self._credential_scope_pairs(
            project_id=project_id,
            org_id=org_id,
            user_id=user_id,
            prefer_user=prefer_user,
        ):
            resolved = self._resolve_scoped_byok(
                scope_type=scope_type,
                scope_id=scope_id,
                provider=provider,
            )
            if resolved:
                api_key, _source, _is_byok, scope_was_configured = resolved
                if scope_was_configured and not api_key:
                    return True
                if api_key:
                    return False
        return False

    def get_active_byok_credential_id(
        self,
        model_id: str,
        *,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
        prefer_user: bool = False,
    ) -> Optional[str]:
        """Database id of the BYOK row supplying credentials, if any."""
        resolved = self.get_credential_for_model(
            model_id,
            project_id=project_id,
            org_id=org_id,
            user_id=user_id,
            prefer_user=prefer_user,
        )
        if not resolved or not self._credential_repository:
            return None
        _key, source, is_byok = resolved
        if not is_byok:
            return None
        model = get_model(model_id)
        if not model:
            return None
        provider = model.provider.value
        from amprealize.auth.llm_credential_repository import CredentialScopeType

        scope_id: Optional[str] = None
        scope_type: Any = None
        if source == "user":
            scope_type, scope_id = CredentialScopeType.USER, user_id
        elif source == "project":
            scope_type, scope_id = CredentialScopeType.PROJECT, project_id
        elif source == "org":
            scope_type, scope_id = CredentialScopeType.ORG, org_id
        if not scope_type or not scope_id:
            return None
        cred = self._credential_repository.get_for_provider(
            scope_type=scope_type,
            scope_id=scope_id,
            provider=provider,
            decrypt=False,
        )
        return cred.id if cred else None

    def _resolve_scoped_byok(
        self,
        *,
        scope_type: Any,
        scope_id: Optional[str],
        provider: str,
    ) -> Optional[Tuple[Optional[str], str, bool, bool]]:
        """Resolve one BYOK scope.

        Returns:
            (api_key, source, is_byok, scope_was_configured) or None when the
            scope is not applicable.
        """
        if not self._credential_repository or not scope_id:
            return None

        cred = self._credential_repository.get_for_provider(
            scope_type=scope_type,
            scope_id=scope_id,
            provider=provider,
            decrypt=True,
            include_invalid=True,
        )
        if not cred:
            return None

        source = scope_type.value
        if cred.is_valid and cred.decrypted_key:
            return (cred.decrypted_key, source, True, True)

        logger.warning(
            "BYOK credential exists for provider %s in %s %s but cannot be used "
            "(is_valid=%s, decrypted=%s)",
            provider,
            source,
            scope_id,
            cred.is_valid,
            cred.decrypted_key is not None,
        )
        return (None, source, True, True)

    def get_credential_for_model(
        self,
        model_id: str,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
        prefer_user: bool = False,
    ) -> Optional[Tuple[str, str, bool]]:
        """Get credential for a model.

        Returns:
            Tuple of (api_key, source, is_byok) or None if not available
            source is one of: "user", "project", "org", "platform"

        BYOK priority:
            The first scope in resolution order that yields a **decrypted,
            valid** BYOK key wins. Rows that exist but cannot be used (invalid,
            decrypt failure) are skipped so platform keys can still apply.
            When a usable BYOK key is found, platform credentials for that
            provider are not used for the same resolution pass.
        """
        model = get_model(model_id)
        if not model:
            return None

        provider = model.provider.value
        byok_configured_for_provider = False

        # Check database for scoped BYOK credentials.
        if self._credential_repository:
            scope_order = self._credential_scope_pairs(
                project_id=project_id,
                org_id=org_id,
                user_id=user_id,
                prefer_user=prefer_user,
            )

            for scope_type, scope_id in scope_order:
                resolved = self._resolve_scoped_byok(
                    scope_type=scope_type,
                    scope_id=scope_id,
                    provider=provider,
                )
                if not resolved:
                    continue
                api_key, source, is_byok, scope_was_configured = resolved
                if api_key:
                    if scope_was_configured:
                        byok_configured_for_provider = True
                    return (api_key, source, is_byok)
                # Row exists at this scope but no usable key (invalid, decrypt failure,
                # auto-disabled). Do not block platform fallback — otherwise model lists
                # and chat stay empty while env keys are configured.
                if scope_was_configured:
                    logger.warning(
                        "Ignoring unusable BYOK for provider %s at scope %s/%s; "
                        "trying remaining scopes or platform credentials",
                        provider,
                        getattr(scope_type, "value", scope_type),
                        scope_id,
                    )
                continue

        # 3. Fall back to platform credentials from environment
        # Only if user has NOT configured BYOK for this provider
        if not byok_configured_for_provider and provider in self._platform_credentials:
            return (self._platform_credentials[provider], "platform", False)

        return None

    def record_credential_success(
        self,
        model_id: str,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        prefer_user: bool = False,
    ) -> None:
        """Record successful use of a BYOK credential.

        Should be called after a successful LLM API call to track usage
        and reset any previous failure counts.
        """
        if not self._credential_repository:
            return

        model = get_model(model_id)
        if not model:
            return

        cred_id = self.get_active_byok_credential_id(
            model_id,
            project_id=project_id,
            org_id=org_id,
            user_id=user_id,
            prefer_user=prefer_user,
        )
        if cred_id:
            self._credential_repository.record_success(cred_id, actor_id)

    def record_credential_failure(
        self,
        model_id: str,
        error_code: Optional[int] = None,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        prefer_user: bool = False,
    ) -> bool:
        """Record auth failure for a BYOK credential.

        Should be called when an LLM API call returns 401/403 to track
        failures and potentially disable the credential after threshold.

        Args:
            model_id: The model that was called
            error_code: HTTP status code (401, 403 triggers failure tracking)
            project_id: Project context
            org_id: Org context
            actor_id: Who triggered the call

        Returns:
            True if the credential was disabled (threshold reached)
        """
        if not self._credential_repository:
            return False

        # Only track 401/403 errors as auth failures
        if error_code not in (401, 403):
            return False

        model = get_model(model_id)
        if not model:
            return False

        cred_id = self.get_active_byok_credential_id(
            model_id,
            project_id=project_id,
            org_id=org_id,
            user_id=user_id,
            prefer_user=prefer_user,
        )
        if cred_id:
            return self._credential_repository.record_failure(
                cred_id,
                error_code=error_code,
                run_id=actor_id,
            )

        return False

    def get_available_models(
        self,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
        prefer_user: bool = False,
        provider_filter: Optional[str] = None,
        free_open_only: bool = False,
    ) -> List[AvailableModel]:
        """Get all models available for a project."""
        available = []
        credential_cache: Dict[str, Optional[Tuple[str, str, bool]]] = {}

        for model_id, model in MODEL_CATALOG.items():
            provider = model.provider.value if hasattr(model.provider, "value") else str(model.provider)
            if provider_filter and provider != provider_filter:
                continue
            if free_open_only and (
                not model.metadata.get("is_open_model", False)
                or not model.metadata.get("free_endpoint", False)
                or not model.metadata.get("chat_model", True)
            ):
                continue

            if provider not in credential_cache:
                credential_cache[provider] = self.get_credential_for_model(
                    model_id,
                    project_id,
                    org_id,
                    user_id=user_id,
                    prefer_user=prefer_user,
                )
            cred = credential_cache[provider]
            if cred:
                api_key, source, is_byok = cred
                available.append(AvailableModel(
                    model=model,
                    credential_source=source,
                    credential_id=f"cred-{model.provider.value}-{source}",
                    is_byok=is_byok,
                ))

        return available

    def is_model_available(
        self,
        model_id: str,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
        prefer_user: bool = False,
    ) -> bool:
        """Check if a model is available for a project."""
        return self.get_credential_for_model(
            model_id,
            project_id,
            org_id,
            user_id=user_id,
            prefer_user=prefer_user,
        ) is not None


class InternetAccessResolver:
    """Resolves internet access permissions based on org/project settings."""

    def __init__(self, pool: Optional[PostgresPool] = None) -> None:
        self._pool = pool

    def is_internet_enabled(
        self,
        policy: InternetAccessPolicy,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> bool:
        """Determine if internet access is enabled.

        Resolution order:
        - If project disables, internet is disabled.
        - Else if org disables, internet is disabled.
        - Else the agent's execution policy decides.
        """
        # TODO: Check project and org settings from database
        # For now, use policy directly
        if policy == InternetAccessPolicy.DISABLED:
            return False
        if policy == InternetAccessPolicy.ENABLED:
            return True
        # INHERIT - default to enabled for now
        return True


class WriteTargetResolver:
    """Resolves write target scope based on project settings and actor surface.

    This resolver determines the effective write scope for an execution by:
    1. Checking the explicit policy (if not INHERIT)
    2. Querying project settings for execution_mode
    3. Validating the actor surface supports the required mode
    """

    def __init__(
        self,
        pool: Optional[PostgresPool] = None,
        settings_service: Optional[SettingsService] = None,
    ) -> None:
        self._pool = pool
        self._settings_service = settings_service
        # Create settings service if pool is provided but service is not
        # SettingsService is None in OSS (enterprise-only), so guard the call
        if self._pool and not self._settings_service and SettingsService is not None:
            self._settings_service = SettingsService(pool=self._pool)

    def get_write_scope(
        self,
        policy: WriteScope,
        project_id: Optional[str] = None,
        actor_surface: Optional[str] = None,
    ) -> WriteScope:
        """Determine effective write scope.

        If policy is INHERIT, falls back to project settings execution_mode.

        Args:
            policy: The write scope policy from execution config
            project_id: Project ID to look up settings
            actor_surface: The surface initiating execution (cli, web, vscode, etc.)

        Returns:
            Resolved WriteScope for the execution
        """
        if policy != WriteScope.INHERIT:
            return policy

        # Try to get execution_mode from project settings
        if project_id and self._settings_service:
            try:
                settings = self._settings_service.get_project_settings(project_id)
                execution_mode = settings.execution_mode

                # Map ExecutionMode to WriteScope
                if execution_mode == ExecutionMode.LOCAL:
                    return WriteScope.LOCAL_ONLY
                elif execution_mode == ExecutionMode.GITHUB_PR:
                    return WriteScope.PR_ONLY
                elif execution_mode == ExecutionMode.LOCAL_AND_PR:
                    return WriteScope.LOCAL_AND_PR
            except Exception as e:
                logger.warning(f"Failed to get project settings for {project_id}: {e}")

        # Default to PR_ONLY for safety (works from any surface)
        return WriteScope.PR_ONLY

    def validate_surface_for_mode(
        self,
        execution_mode: ExecutionMode,
        actor_surface: str,
    ) -> tuple[bool, str]:
        """Validate that the actor surface supports the execution mode.

        Args:
            execution_mode: The execution mode from project settings
            actor_surface: The surface initiating execution

        Returns:
            Tuple of (is_valid, error_message)
        """
        actor_surface_lower = actor_surface.lower()

        # PR-only mode works from any surface
        if execution_mode == ExecutionMode.GITHUB_PR:
            return (True, "")

        # Local modes require a local-capable surface
        if execution_mode in (ExecutionMode.LOCAL, ExecutionMode.LOCAL_AND_PR):
            if actor_surface_lower in REMOTE_ONLY_SURFACES:
                mode_display = "local" if execution_mode == ExecutionMode.LOCAL else "local + PR"
                return (
                    False,
                    f"Execution mode '{mode_display}' requires local filesystem access, "
                    f"which is not available from the {actor_surface} interface."
                )

        return (True, "")


class WorkItemExecutionService:
    """Orchestrates agent execution of work items via GEP.

    This service is the main entry point for executing work items. It:
    1. Validates the work item has an assigned agent
    2. Loads the agent's playbook and execution policy
    3. Creates Run + TaskCycle records
    4. Invokes the AgentExecutionLoop
    5. Posts summary comments and updates board state on completion
    """

    def __init__(
        self,
        *,
        board_service: Optional[BoardService] = None,
        run_service: Optional[RunService] = None,
        task_cycle_service: Optional[TaskCycleService] = None,
        agent_registry_service: Optional[AgentRegistryService] = None,
        credential_store: Optional[CredentialStore] = None,
        internet_resolver: Optional[InternetAccessResolver] = None,
        write_resolver: Optional[WriteTargetResolver] = None,
        telemetry: Optional[TelemetryClient] = None,
        pool: Optional[PostgresPool] = None,
        dsn: Optional[str] = None,
        execution_mode: Optional[str] = None,
        queue_publisher: Optional[Any] = None,
    ) -> None:
        """Initialize WorkItemExecutionService.

        Args:
            board_service: Service for board/work item operations
            run_service: Service for run tracking
            task_cycle_service: Service for GEP phase management
            agent_registry_service: Service for agent lookup
            execution_mode: 'direct' (inline) or 'queue' (worker). Env: EXECUTION_MODE
            queue_publisher: ExecutionQueuePublisher for queue mode
            credential_store: Store for LLM credentials
            internet_resolver: Resolver for internet access permissions
            write_resolver: Resolver for write scope
            telemetry: Telemetry client for event emission
            pool: PostgreSQL connection pool
            dsn: PostgreSQL connection string
        """
        # Initialize pool if needed
        if pool is None and dsn:
            pool = PostgresPool(dsn)
        elif pool is None:
            dsn = resolve_postgres_dsn(
                service="WORK_ITEM_EXECUTION",
                explicit_dsn=None,
                env_var=_EXECUTION_PG_DSN_ENV,
                default_dsn=_DEFAULT_PG_DSN,
            )
            pool = PostgresPool(dsn)

        self._pool = pool
        self._telemetry = telemetry or TelemetryClient.noop()

        # Initialize LLMCredentialRepository for BYOK credential access
        from .auth.llm_credential_repository import LLMCredentialRepository
        credential_repo = LLMCredentialRepository(pool=pool)

        # Initialize sub-services
        self._board_service = board_service or BoardService(pool=pool)

        # Initialize run service - prefer PostgreSQL when DSN is available
        if run_service is not None:
            self._run_service = run_service
        elif dsn:
            from .run_service_postgres import PostgresRunService
            self._run_service = PostgresRunService(dsn=dsn, telemetry=self._telemetry)
            logger.info("Created PostgresRunService for WorkItemExecutionService")
        else:
            logger.warning("No DSN provided - using SQLite RunService (not recommended for production)")
            self._run_service = RunService()

        self._task_cycle_service = task_cycle_service or TaskCycleService(pool=pool)
        self._agent_registry = agent_registry_service or AgentRegistryService(pool=pool)
        self._credential_store = credential_store or CredentialStore(pool=pool, credential_repository=credential_repo)
        self._internet_resolver = internet_resolver or InternetAccessResolver(pool=pool)
        self._write_resolver = write_resolver or WriteTargetResolver(pool=pool)
        self._resource_analysis_service = ResourceAnalysisService()

        # Initialize workspace client for GitHub repo access during execution
        # This connects to the workspace-agent gRPC service
        self._workspace_manager = get_workspace_client()

        # Execution loop will be set via setter or import
        self._execution_loop: Optional[Any] = None

        # Execution mode: 'direct' (inline) or 'queue' (worker processing)
        self._execution_mode = execution_mode or os.environ.get("EXECUTION_MODE", "queue")
        self._queue_publisher = queue_publisher

        # Lazy-init queue publisher if in queue mode
        if self._execution_mode == "queue" and self._queue_publisher is None:
            try:
                from execution_queue import ExecutionQueuePublisher
                self._queue_publisher = ExecutionQueuePublisher()
                logger.info("Initialized ExecutionQueuePublisher for queue mode")
            except ImportError:
                logger.warning("execution-queue package not installed, falling back to direct mode")
                warnings.warn(
                    "EXECUTION_MODE=direct is deprecated and will be removed in a future release. "
                    "Install the execution-queue package for queue-based execution.",
                    DeprecationWarning,
                    stacklevel=2,
                )
                self._execution_mode = "direct"

    def set_execution_loop(self, loop: Any) -> None:
        """Set the execution loop (avoids circular import)."""
        self._execution_loop = loop

    def _resolve_project_default_model_id(self, project_id: Optional[str]) -> Optional[str]:
        """Return the project-level agent model default from project settings."""
        if not project_id:
            return None
        settings_service = getattr(self._write_resolver, "_settings_service", None)
        if not settings_service:
            return None
        try:
            settings = settings_service.get_project_settings(project_id)
        except Exception:
            return None

        prefs: Any = None
        if isinstance(settings, dict):
            prefs = settings.get("agent_model_preferences")
        elif settings is not None:
            prefs = getattr(settings, "agent_model_preferences", None)

        if isinstance(prefs, dict):
            value = prefs.get("default_model_id")
            return value.strip() if isinstance(value, str) and value.strip() else None
        value = getattr(prefs, "default_model_id", None)
        return value.strip() if isinstance(value, str) and value.strip() else None

    async def execute(
        self,
        request: ExecuteWorkItemRequest,
    ) -> ExecuteWorkItemResponse:
        """Execute a work item.

        This is the main entry point for starting execution. It:
        1. Validates the work item and agent
        2. Checks for existing active execution (idempotency)
        3. Creates Run and TaskCycle records
        4. Starts the execution loop asynchronously

        Args:
            request: Execution request with work item ID and options

        Returns:
            Response with run_id, cycle_id, and initial status

        Raises:
            WorkItemNotFoundError: If work item doesn't exist
            WorkItemNotAssignedError: If no agent is assigned
            AgentNotFoundError: If assigned agent doesn't exist
            ExecutionAlreadyActiveError: If execution is already running
            ModelNotAvailableError: If requested model isn't available
        """
        work_item_id = request.work_item_id
        user_id = request.user_id
        org_id = request.org_id
        project_id = request.project_id

        # Step 1: Load and validate work item
        work_item = self._get_work_item(work_item_id, org_id)
        if not work_item:
            raise WorkItemNotFoundError(f"Work item {work_item_id} not found")

        # Use work item's project if not provided
        if not project_id:
            project_id = work_item.project_id

        # Step 2: Resolve the execution agent. Research ownership is assignable
        # to anyone, but execution is restricted to the builtin AI Research agent.
        if work_item.item_type == WorkItemType.RESEARCH:
            validate_research_url(work_item.metadata)
            agent_id = self._resolve_ai_research_agent_id()
        else:
            if not work_item.assignee_id or work_item.assignee_type != AssigneeType.AGENT:
                raise WorkItemNotAssignedError(
                    f"Work item {work_item_id} has no agent assigned"
                )
            agent_id = work_item.assignee_id

        # Step 3: Check for existing active execution (idempotency)
        if work_item.run_id:
            existing_status = self.get_status(work_item_id, org_id)
            if existing_status and existing_status.status in (
                ExecutionState.PENDING,
                ExecutionState.RUNNING,
                ExecutionState.PAUSED,
            ):
                # Return existing run instead of creating new one
                return ExecuteWorkItemResponse(
                    run_id=existing_status.run_id,
                    cycle_id=existing_status.cycle_id,
                    work_item_id=work_item_id,
                    agent_id=agent_id,
                    model_id=existing_status.model_id or "",
                    status=existing_status.status,
                    phase=existing_status.phase,
                    created_at=existing_status.started_at or _now_iso(),
                    message="Existing execution in progress",
                )

        # Step 4: Load agent and playbook
        agent, agent_version = self._load_agent(agent_id, org_id)
        if not agent:
            raise AgentNotFoundError(f"Agent {agent_id} not found")

        # Step 5: Resolve execution policy
        exec_policy = request.execution_policy or self._get_agent_execution_policy(agent_version)

        # Step 5.5: Check execution surface compatibility
        actor_surface = request.actor_surface or "api"
        if project_id and self._write_resolver:
            try:
                # Get project settings to check execution_mode
                if self._write_resolver._settings_service:
                    settings = self._write_resolver._settings_service.get_project_settings(project_id)
                    is_valid, error_msg = self._write_resolver.validate_surface_for_mode(
                        settings.execution_mode,
                        actor_surface,
                    )
                    if not is_valid:
                        raise ExecutionSurfaceRestrictedError(
                            message=error_msg,
                            guidance=(
                                "To execute this work item, you can either:\n"
                                "1. Use the VS Code extension or CLI to run locally\n"
                                "2. Change the project's execution_mode to 'github_pr' in project settings\n\n"
                                "PR mode will create a GitHub branch and pull request with all changes."
                            ),
                        )
            except ExecutionSurfaceRestrictedError:
                raise  # Re-raise our custom error
            except Exception as e:
                # Log but don't block execution if settings lookup fails
                logger.warning(f"Could not validate execution surface for project {project_id}: {e}")

        # Step 6: Resolve model
        model_id = (
            request.model_id
            or self._resolve_project_default_model_id(project_id)
            or exec_policy.model_policy.preferred_model_id
        )
        if not self._credential_store.is_model_available(model_id, project_id, org_id):
            # Try fallbacks
            model_id = None
            for fallback in exec_policy.model_policy.fallback_model_ids:
                if self._credential_store.is_model_available(fallback, project_id, org_id):
                    model_id = fallback
                    break
            if not model_id:
                raise ModelNotAvailableError(
                    f"No available model for agent {agent_id} in project {project_id}"
                )

        # Step 7: Create Run record
        actor = Actor(id=user_id, role="user", surface=actor_surface)
        run = self._run_service.create_run(RunCreateRequest(
            actor=actor,
            workflow_name="work_item_execution",
            triggering_user_id=user_id,  # For GitHub credential resolution
            metadata={
                "work_item_id": work_item_id,
                "agent_id": agent_id,
                "model_id": model_id,
                "project_id": project_id,
                "org_id": org_id,
                "execution_policy": exec_policy.to_dict(),
                "agent_playbook_version": agent_version.version if agent_version else None,
            },
            initial_message=f"Executing work item: {work_item.title}",
        ))

        # Step 8: Create TaskCycle
        cycle_request = CreateCycleRequest(
            task_id=work_item_id,
            assigned_agent_id=agent_id,
            requester_entity_id=user_id,
            requester_entity_type="user",
            metadata={
                "work_item_id": work_item_id,
                "run_id": run.run_id,
                "agent_id": agent_id,
                "model_id": model_id,
            },
        )
        cycle_response = self._task_cycle_service.create_cycle(cycle_request)

        # Extract cycle_id from response - fail if cycle wasn't created
        if not cycle_response.cycle:
            raise WorkItemExecutionError(
                f"Failed to create execution cycle for work item {work_item_id}: "
                f"{cycle_response.message or 'Unknown error'}"
            )
        cycle_id = cycle_response.cycle.cycle_id

        # Persist cycle info on the run for phase tracking.
        self._run_service.update_run(
            run.run_id,
            RunProgressUpdate(
                metadata={
                    "cycle_id": cycle_id,
                    "phase": CyclePhase.PLANNING.value,
                },
            ),
        )

        # Step 9: Link run to work item
        self._update_work_item_run(work_item_id, run.run_id, org_id)

        # Step 10: Emit telemetry
        self._telemetry.emit_event(
            event_type="work_item.execution.started",
            payload={
                "run_id": run.run_id,
                "cycle_id": cycle_id,
                "work_item_id": work_item_id,
                "agent_id": agent_id,
                "model_id": model_id,
                "project_id": project_id,
                "org_id": org_id,
            },
            run_id=run.run_id,
        )

        # Step 11: Start execution loop (async or via queue)
        # The actual execution happens asynchronously
        if self._execution_mode == "queue" and self._queue_publisher:
            # Queue mode: enqueue job for worker processing
            from execution_queue import ExecutionJob, Priority

            # Determine priority based on context
            priority = Priority.NORMAL
            if exec_policy and hasattr(exec_policy, 'priority'):
                priority_str = getattr(exec_policy, 'priority', 'normal').lower()
                priority = Priority.HIGH if priority_str == 'high' else (
                    Priority.LOW if priority_str == 'low' else Priority.NORMAL
                )

            # Resolve GitHub repo for workspace provisioning
            github_repo = await self._resolve_project_repo(project_id) if project_id else None
            logger.info(f"Resolved github_repo for project {project_id}: {github_repo}")

            job = ExecutionJob(
                job_id=run.run_id,  # Use run_id as job_id for correlation
                run_id=run.run_id,
                work_item_id=work_item_id,
                agent_id=agent_id,
                user_id=user_id,
                project_id=project_id,
                priority=priority,
                org_id=org_id,
                model_override=model_id,  # model_override maps to model_id
                cycle_id=cycle_id,  # Top-level field for direct access by worker
                payload={
                    "cycle_id": cycle_id,  # Keep in payload for backwards compat
                    "work_item_title": work_item.title if work_item else None,
                    "agent_version": agent_version.version if agent_version else None,
                    "exec_policy": exec_policy.to_dict() if exec_policy else None,
                    "github_repo": github_repo,  # For workspace provisioning
                    "agent_execution_mode": request.agent_execution_mode.value if request.agent_execution_mode else None,
                },
            )

            await self._queue_publisher.enqueue(job)
            logger.info(f"Enqueued execution job: {run.run_id} (priority={priority.value})")

        elif self._execution_loop and cycle_id:
            # Direct mode: schedule execution in background (DEPRECATED)
            warnings.warn(
                "Direct/inline execution mode is deprecated and will be removed in a future release. "
                "Migrate to queue-based execution (EXECUTION_MODE=queue) with execution-queue package.",
                DeprecationWarning,
                stacklevel=2,
            )
            logger.warning(
                "direct-execution-deprecated",
                extra={
                    "run_id": run.run_id,
                    "execution_mode": self._execution_mode,
                    "msg": "Direct execution is deprecated — migrate to EXECUTION_MODE=queue",
                },
            )
            import asyncio
            asyncio.create_task(self._run_execution_loop(
                run_id=run.run_id,
                cycle_id=cycle_id,
                work_item=work_item,
                agent=agent,
                agent_version=agent_version,
                exec_policy=exec_policy,
                model_id=model_id,
                user_id=user_id,
                org_id=org_id,
                project_id=project_id,
                agent_execution_mode=request.agent_execution_mode,
            ))

        return ExecuteWorkItemResponse(
            run_id=run.run_id,
            cycle_id=cycle_id,
            work_item_id=work_item_id,
            agent_id=agent_id,
            model_id=model_id,
            status=ExecutionState.PENDING,
            phase=CyclePhase.PLANNING.value,
            created_at=run.created_at,
            message="Execution started",
        )

    async def _run_execution_loop(
        self,
        run_id: str,
        cycle_id: str,
        work_item: WorkItem,
        agent: Agent,
        agent_version: Optional[AgentVersion],
        exec_policy: ExecutionPolicy,
        model_id: str,
        user_id: str,
        org_id: Optional[str],
        project_id: Optional[str],
        agent_execution_mode: Optional["AgentExecutionMode"] = None,
    ) -> None:
        """Run the execution loop in the background.

        This method runs the AgentExecutionLoop until completion or failure.
        Creates a ToolExecutor with the specific ExecutionPolicy for this run.
        When write_scope is PR_ONLY or LOCAL_AND_PR, sets up PR context for
        accumulating file changes and creating a pull request.

        Workspace Setup:
        - If project has a GitHub repo configured, clones it into an isolated workspace
        - Uses BreakerAmp for container isolation (or local directory fallback)
        - Workspace path is passed to ToolExecutor for filesystem tools
        - Cleanup: immediate on success, 24h retention on failure for debugging
        """
        pr_context: Optional[PRExecutionContext] = None
        github_service = None
        workspace_info: Optional[WorkspaceInfo] = None
        execution_success = False

        try:
            if not self._execution_loop:
                logger.error(f"No execution loop configured for run {run_id}")
                return

            # Set up PR context if write scope requires PR creation
            if exec_policy.write_scope in (WriteScope.PR_ONLY, WriteScope.LOCAL_AND_PR):
                pr_context = await self._setup_pr_context(
                    work_item=work_item,
                    run_id=run_id,
                    project_id=project_id,
                    org_id=org_id,
                )
                if pr_context:
                    # Import GitHubService lazily to avoid circular imports
                    from .services.github_service import GitHubService
                    github_service = GitHubService(pool=self._pool)
                    logger.info(
                        f"PR mode enabled for run {run_id}: "
                        f"branch={pr_context.branch_name}, repo={pr_context.repo}"
                    )

            # =========================================================================
            # Workspace Setup - Clone GitHub repo for agent filesystem access
            # =========================================================================
            workspace_path = None

            if project_id:
                workspace_info = await self._setup_workspace(
                    run_id=run_id,
                    project_id=project_id,
                    org_id=org_id,
                    user_id=user_id,
                )
                if workspace_info:
                    workspace_path = workspace_info.workspace_path
                    logger.info(
                        f"Workspace provisioned for run {run_id}: {workspace_path}"
                    )
                    if workspace_info.use_container_exec:
                        logger.info(
                            f"Container-based workspace: {workspace_info.container_name}"
                        )

            # Resolve GitHub repo for API fallback tools
            github_repo = await self._resolve_project_repo(project_id) if project_id else None

            # Create ToolExecutor for this run with the specific execution policy
            # This enforces write scope, internet access, and other permissions
            from .tool_executor import ToolExecutor
            tool_executor = ToolExecutor(
                policy=exec_policy,
                telemetry=self._telemetry,
                project_root=workspace_path or work_item.project_id,  # Use workspace path if available
                pr_context=pr_context,
                github_service=github_service,
                github_context={
                    "repo": github_repo,
                    "project_id": project_id,
                    "org_id": org_id,
                    "user_id": user_id,
                },
                resource_analysis_service=self._resource_analysis_service,
                resource_analysis_inventory_provider=self._build_execution_resource_inventory,
                workspace_info=workspace_info,  # Pass workspace info for container exec
                workspace_manager=self._workspace_manager,  # Pass workspace manager for container operations
                run_service=self._run_service,
                run_id=run_id,
            )
            self._execution_loop.set_tool_executor(tool_executor)
            logger.info(f"Created ToolExecutor for run {run_id} with policy: write_scope={exec_policy.write_scope}, internet={exec_policy.internet_access}")

            # Set PR context on execution loop for PR creation
            if pr_context and github_service:
                self._execution_loop.set_github_service(github_service)
                self._execution_loop.set_pr_context(pr_context)

            # Run the loop
            await self._execution_loop.run(
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
                execution_mode=agent_execution_mode,
            )

            # Mark success for cleanup policy
            execution_success = True

            # On success, post summary and move to completed
            # Include PR link if one was created
            pr_url = pr_context.pr_url if pr_context else None
            await self._on_execution_complete(
                run_id=run_id,
                work_item_id=work_item.item_id,
                agent_id=agent.agent_id,
                org_id=org_id,
                pr_url=pr_url,
            )

        except Exception as e:
            logger.exception(f"Execution loop failed for run {run_id}: {e}")
            await self._on_execution_failed(
                run_id=run_id,
                work_item_id=work_item.item_id,
                agent_id=agent.agent_id,
                error=str(e),
                org_id=org_id,
            )

        finally:
            # =========================================================================
            # Workspace Cleanup
            # - Immediate cleanup on success
            # - Retain for 24h on failure for debugging
            # =========================================================================
            if workspace_info:
                try:
                    await self._workspace_manager.cleanup(
                        run_id=run_id,
                        success=execution_success,
                    )
                except Exception as cleanup_error:
                    logger.warning(f"Workspace cleanup failed for run {run_id}: {cleanup_error}")

    async def _setup_workspace(
        self,
        run_id: str,
        project_id: str,
        org_id: Optional[str],
        user_id: str,
    ) -> Optional[WorkspaceInfo]:
        """Provision an isolated workspace with the project's GitHub repo.

        This method:
        1. Resolves the project's GitHub repo
        2. Gets a GitHub token using the credential resolution hierarchy
        3. Provisions a workspace container with the cloned repo

        Args:
            run_id: Run ID for tracking
            project_id: Project to get repo from
            org_id: Organization ID for token resolution
            user_id: User ID (triggering_user_id) for token resolution

        Returns:
            WorkspaceInfo if workspace provisioned, None if no repo configured
        """
        try:
            # Step 1: Get the project's GitHub repo
            repo = await self._resolve_project_repo(project_id)
            if not repo:
                logger.info(
                    f"No GitHub repo configured for project {project_id}, "
                    f"skipping workspace provisioning"
                )
                return None

            # Step 2: Resolve GitHub token using the credential hierarchy
            # User-linked credentials take priority, then project, then org, then platform
            from .services.github_service import GitHubService
            github_service = GitHubService(pool=self._pool)

            resolved_token = github_service.get_resolved_token(
                project_id=project_id,
                org_id=org_id,
                user_id=user_id,  # triggering_user_id for per-user resolution
            )

            if not resolved_token:
                logger.warning(
                    f"No GitHub token available for project {project_id}, "
                    f"cannot clone repo"
                )
                return None

            logger.info(
                f"Using GitHub token from '{resolved_token.source}' for repo clone"
            )

            # Step 3: Provision workspace with cloned repo
            config = WorkspaceConfig(
                run_id=run_id,
                project_id=project_id,
                github_repo=repo,
                github_token=resolved_token.token,
                ttl_hours=24,  # Keep for 24h on failure
            )

            workspace_info = await self._workspace_manager.provision(config)
            return workspace_info

        except WorkspaceProvisionError as e:
            logger.error(f"Failed to provision workspace: {e}")
            # Don't fail execution - agent can still work without local workspace
            # It will fall back to GitHub API for file access
            return None
        except Exception as e:
            logger.warning(f"Error setting up workspace for run {run_id}: {e}")
            return None

    async def _setup_pr_context(
        self,
        work_item: WorkItem,
        run_id: str,
        project_id: Optional[str],
        org_id: Optional[str],
    ) -> Optional[PRExecutionContext]:
        """Set up PR context for PR-mode execution.

        Resolves the project's GitHub repository and creates a PRExecutionContext
        with a unique branch name for this execution.

        Args:
            work_item: The work item being executed
            run_id: The run ID for this execution
            project_id: Project ID for resolving repo
            org_id: Organization ID for credential resolution

        Returns:
            PRExecutionContext if repo is configured, None otherwise
        """
        try:
            # Get project settings to find GitHub repo
            if not project_id:
                logger.warning(f"No project_id for PR context setup (run {run_id})")
                return None

            # Try to get repo from project settings
            repo = await self._resolve_project_repo(project_id)
            if not repo:
                logger.warning(
                    f"No GitHub repo configured for project {project_id}, "
                    f"PR mode will not create commits"
                )
                return None

            # Import GitHubService for default branch resolution
            from .services.github_service import GitHubService
            github_service = GitHubService(pool=self._pool)

            # Detect default branch from GitHub API (synchronous)
            base_branch = github_service.get_default_branch(
                repo=repo,
                project_id=project_id,
                org_id=org_id,
            )

            # Generate unique branch name
            branch_name = generate_pr_branch_name(work_item.item_id)

            return PRExecutionContext(
                work_item_id=work_item.item_id,
                run_id=run_id,
                branch_name=branch_name,
                repo=repo,
                base_branch=base_branch,
            )

        except Exception as e:
            logger.exception(f"Failed to setup PR context for run {run_id}: {e}")
            return None

    async def _resolve_project_repo(self, project_id: str) -> Optional[str]:
        """Resolve the GitHub repo for a project.

        Returns repo in 'owner/repo' format, or None if not configured.
        """
        try:
            # Try to get from project settings service first
            if self._write_resolver and self._write_resolver._settings_service:
                settings = self._write_resolver._settings_service.get_project_settings(project_id)
                # Check repository_url field (primary setting)
                if hasattr(settings, 'repository_url') and settings.repository_url:
                    repo_url = settings.repository_url
                    # Extract owner/repo from URL
                    if repo_url.startswith("https://github.com/"):
                        return repo_url.replace("https://github.com/", "").rstrip("/")
                    elif repo_url.startswith("git@github.com:"):
                        return repo_url.replace("git@github.com:", "").replace(".git", "").rstrip("/")
                    else:
                        return repo_url
                # Fallback to github_repo field
                if hasattr(settings, 'github_repo') and settings.github_repo:
                    return settings.github_repo

            # Fallback: Direct database query to auth.projects settings JSONB
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
                            # Extract owner/repo from URL if needed
                            # e.g., "https://github.com/SandRiseStudio/amprealize" -> "Nas4146/amprealize"
                            if repo_url.startswith("https://github.com/"):
                                return repo_url.replace("https://github.com/", "").rstrip("/")
                            elif repo_url.startswith("git@github.com:"):
                                return repo_url.replace("git@github.com:", "").replace(".git", "").rstrip("/")
                            else:
                                # Assume it's already in owner/repo format
                                return repo_url

            return None

        except Exception as e:
            logger.warning(f"Could not resolve repo for project {project_id}: {e}")
            return None

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
        - Update work item status
        """
        try:
            # Get run for summary generation
            run = self._run_service.get_run(run_id)

            # Generate summary
            summary = self._generate_summary(run)

            # Append PR link if one was created
            if pr_url:
                summary += f"\n\n---\n\n**Pull Request:** [{pr_url}]({pr_url})"

            # Post comment
            self._post_work_item_comment(
                work_item_id=work_item_id,
                author_id=agent_id,
                author_type="agent",
                content=summary,
                run_id=run_id,
                org_id=org_id,
            )

            # Move to completed column
            self._move_to_completed(work_item_id, org_id)

            # Emit telemetry
            self._telemetry.emit_event(
                event_type="work_item.execution.completed",
                payload={
                    "run_id": run_id,
                    "work_item_id": work_item_id,
                    "agent_id": agent_id,
                    "pr_url": pr_url,
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
        - Do NOT move work item to completed
        """
        try:
            # Post error comment
            self._post_work_item_comment(
                work_item_id=work_item_id,
                author_id=agent_id,  # Use actual agent ID for error comments
                author_type="agent",
                content=f"## Execution Failed\n\n**Error:** {error}\n\n**Run ID:** {run_id}",
                run_id=run_id,
                org_id=org_id,
            )

            # Update run status
            from amprealize.run_contracts import RunProgressUpdate
            self._run_service.update_run(run_id, RunProgressUpdate(status=RunStatus.FAILED, message=error))

            # Emit telemetry
            self._telemetry.emit_event(
                event_type="work_item.execution.failed",
                payload={
                    "run_id": run_id,
                    "work_item_id": work_item_id,
                    "error": error,
                },
                run_id=run_id,
            )

        except Exception as e:
            logger.exception(f"Error in failure handler for run {run_id}: {e}")

    def get_status(
        self,
        work_item_id: str,
        org_id: Optional[str] = None,
    ) -> Optional[ExecutionStatusResponse]:
        """Get the execution status for a work item.

        Args:
            work_item_id: Work item ID
            org_id: Organization ID for multi-tenant filtering

        Returns:
            Execution status or None if no execution exists
        """
        # Get work item to find run_id
        work_item = self._get_work_item(work_item_id, org_id)
        if not work_item or not work_item.run_id:
            return None

        # Get run
        try:
            run = self._run_service.get_run(work_item.run_id)
        except RunNotFoundError:
            return None

        # Get cycle for phase info (GEP). Research runs advance phase via run metadata
        # only — the TaskCycle stays at planning because no AgentExecutionLoop runs.
        cycle_id = run.metadata.get("cycle_id")
        run_metadata = run.metadata or {}
        phase = CyclePhase.PLANNING.value
        if cycle_id:
            cycle = self._task_cycle_service.get_cycle(cycle_id)
            if cycle:
                phase = cycle.current_phase.value
        if work_item.item_type == WorkItemType.RESEARCH:
            rp = run_metadata.get("phase")
            if isinstance(rp, str) and rp.strip():
                phase = rp.strip()
        elif run_metadata.get("execution_pipeline") == "research":
            rp = run_metadata.get("phase")
            if isinstance(rp, str) and rp.strip():
                phase = rp.strip()

        # Extract pending clarifications from run metadata
        pending_clarifications = None
        clarification_questions = run_metadata.get("clarification_questions")
        if clarification_questions and isinstance(clarification_questions, list):
            pending_clarifications = clarification_questions

        return self._execution_status_from_run(
            run,
            work_item_id=work_item_id,
            cycle_id=cycle_id or "",
            phase=phase,
            pending_clarifications=pending_clarifications,
        )

    def cancel(
        self,
        work_item_id: str,
        user_id: str,
        org_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> bool:
        """Cancel an active execution.

        Args:
            work_item_id: Work item ID
            user_id: User requesting cancellation
            org_id: Organization ID
            reason: Optional cancellation reason

        Returns:
            True if cancelled, False if no active execution
        """
        status = self.get_status(work_item_id, org_id)
        if not status:
            return False

        if status.status not in (ExecutionState.PENDING, ExecutionState.RUNNING, ExecutionState.PAUSED):
            return False

        # Cancel the run
        self._run_service.cancel_run(status.run_id)

        # Cancel the cycle (note: TaskCycleService.cancel_cycle not yet implemented)
        # TODO: Implement cycle cancellation via phase transition to 'cancelled'
        # if status.cycle_id:
        #     self._task_cycle_service.cancel_cycle(status.cycle_id, reason or "User cancelled")

        # Post cancellation comment
        self._post_work_item_comment(
            work_item_id=work_item_id,
            author_id=user_id,
            author_type="user",
            content=f"## Execution Cancelled\n\n{reason or 'No reason provided'}\n\n**Run ID:** {status.run_id}",
            run_id=status.run_id,
            org_id=org_id,
        )

        # Emit telemetry
        self._telemetry.emit_event(
            event_type="work_item.execution.cancelled",
            payload={
                "run_id": status.run_id,
                "work_item_id": work_item_id,
                "user_id": user_id,
                "reason": reason,
            },
            run_id=status.run_id,
        )

        return True

    def provide_clarification(
        self,
        work_item_id: str,
        clarification_id: str,
        response: str,
        user_id: str,
        org_id: Optional[str] = None,
    ) -> bool:
        """Provide a clarification response for a paused execution.

        When an agent requests clarification during execution (CLARIFYING phase),
        this method delivers the user's response to the waiting execution.

        Args:
            work_item_id: Work item ID
            clarification_id: ID of the clarification question being answered
            response: User's response text
            user_id: User providing the clarification
            org_id: Organization ID

        Returns:
            True if clarification was delivered, False if execution not waiting
        """
        status = self.get_status(work_item_id, org_id)
        if not status:
            return False

        # Only accept clarifications for paused executions
        if status.status != ExecutionState.PAUSED:
            logger.warning(
                f"Cannot provide clarification for work item {work_item_id}: "
                f"execution is {status.status}, not paused"
            )
            return False

        # Store the clarification response
        # The execution loop will pick this up when resuming
        try:
            with self._pool.connection() as conn:
                cur = conn.cursor()
                try:
                    cur.execute(
                        """
                        INSERT INTO execution_clarifications
                        (clarification_id, work_item_id, run_id, response, user_id, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (clarification_id) DO UPDATE
                        SET response = EXCLUDED.response, user_id = EXCLUDED.user_id, created_at = EXCLUDED.created_at
                        """,
                        (clarification_id, work_item_id, status.run_id, response, user_id, _now_iso()),
                    )
                finally:
                    cur.close()
                conn.commit()
        except Exception as e:
            logger.exception(f"Error storing clarification for {work_item_id}: {e}")
            # Fall back to in-memory storage if table doesn't exist yet
            pass

        # Resume the execution by transitioning cycle out of clarifying
        if status.cycle_id:
            try:
                clarification_request = SubmitClarificationRequest(
                    cycle_id=status.cycle_id,
                    sender_id=user_id,
                    sender_type="entity",  # User providing clarification
                    content=response,
                )
                self._task_cycle_service.submit_clarification(clarification_request)
            except Exception as e:
                logger.exception(f"Error submitting clarification to cycle: {e}")

        # Emit telemetry
        self._telemetry.emit_event(
            event_type="work_item.clarification.provided",
            payload={
                "work_item_id": work_item_id,
                "run_id": status.run_id,
                "clarification_id": clarification_id,
                "user_id": user_id,
            },
            run_id=status.run_id,
        )

        return True

    async def approve_gate(
        self,
        work_item_id: str,
        user_id: str,
        org_id: Optional[str] = None,
        project_id: Optional[str] = None,
        phase: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Approve a strict gate on a paused execution and re-enqueue for resumption.

        When an execution is paused at a STRICT gate (ARCHITECTING, VERIFYING,
        COMPLETING), this method approves the gate, transitions the cycle to
        the next phase, and re-enqueues the execution job so the worker resumes.

        Args:
            work_item_id: Work item ID
            user_id: User approving the gate
            org_id: Organization ID
            project_id: Project ID
            phase: Phase to approve (if None, uses current phase)
            notes: Approval notes/feedback

        Returns:
            Dict with success, message, run_id, resumed
        """
        exec_status = self.get_status(work_item_id, org_id)
        if not exec_status:
            return {
                "success": False,
                "message": f"No active execution found for work item {work_item_id}",
            }

        # Must be paused to approve a gate
        if exec_status.status not in (ExecutionState.PAUSED, ExecutionState.PENDING):
            return {
                "success": False,
                "message": (
                    f"Execution is {exec_status.status.value}, not paused at a gate. "
                    f"Only paused executions can have gates approved."
                ),
            }

        if not exec_status.cycle_id:
            return {
                "success": False,
                "message": "No task cycle associated with this execution.",
            }

        # Determine current and next phase
        cycle = self._task_cycle_service.get_cycle(exec_status.cycle_id)
        if not cycle:
            return {
                "success": False,
                "message": f"Task cycle {exec_status.cycle_id} not found.",
            }

        current_phase = cycle.current_phase

        # If caller specified a phase, validate it matches current
        if phase:
            try:
                requested_phase = CyclePhase(phase)
                if requested_phase != current_phase:
                    return {
                        "success": False,
                        "message": (
                            f"Requested approval for phase '{phase}' but execution "
                            f"is at '{current_phase.value}'"
                        ),
                    }
            except ValueError:
                return {
                    "success": False,
                    "message": f"Unknown phase: {phase}",
                }

        # Check this phase actually has a gate
        gate_type = PHASE_GATES.get(current_phase, GateType.NONE)
        if gate_type != GateType.STRICT:
            return {
                "success": False,
                "message": (
                    f"Phase '{current_phase.value}' has gate type {gate_type.value}, "
                    f"not STRICT. Only STRICT gates require approval."
                ),
            }

        # Determine the next phase using valid transitions
        from .task_cycle_contracts import VALID_TRANSITIONS
        valid_targets = VALID_TRANSITIONS.get(current_phase, [])
        # Pick the forward-progressing phase (not CANCELLED/FAILED)
        next_phase = None
        for target in valid_targets:
            if target not in (CyclePhase.CANCELLED, CyclePhase.FAILED):
                next_phase = target
                break

        if not next_phase:
            return {
                "success": False,
                "message": f"No valid forward transition from phase '{current_phase.value}'",
            }

        # Transition the cycle with approval
        transition_request = TransitionPhaseRequest(
            cycle_id=exec_status.cycle_id,
            target_phase=next_phase,
            triggered_by=user_id,
            trigger_type=TriggerType.MANUAL,
            approval_granted=True,
            notes=notes or f"Gate approved by {user_id}",
        )

        result = self._task_cycle_service.transition_phase(transition_request)
        if not result.success:
            return {
                "success": False,
                "message": f"Failed to transition phase: {result.error}",
            }

        # Re-enqueue execution job so worker resumes from the new phase
        resumed = False
        if self._execution_mode == "queue" and self._queue_publisher:
            try:
                from execution_queue import ExecutionJob, Priority

                # Get run record for context
                run = self._run_service.get_run(exec_status.run_id)

                # Get agent info for re-enqueue
                agent_id = run.metadata.get("agent_id", "") if run else ""

                job = ExecutionJob(
                    job_id=exec_status.run_id,
                    run_id=exec_status.run_id,
                    work_item_id=work_item_id,
                    agent_id=agent_id,
                    user_id=user_id,
                    project_id=project_id or "",
                    priority=Priority.HIGH,  # Gate approvals get high priority
                    org_id=org_id,
                    cycle_id=exec_status.cycle_id,
                    payload={
                        "cycle_id": exec_status.cycle_id,
                        "resume_from_phase": next_phase.value,
                        "gate_approved_by": user_id,
                        "gate_approved_notes": notes,
                        "exec_policy": run.metadata.get("execution_policy") if run else None,
                    },
                )

                await self._queue_publisher.enqueue(job)
                resumed = True
                logger.info(
                    f"Re-enqueued execution {exec_status.run_id} after gate approval "
                    f"(phase={next_phase.value})"
                )
            except Exception as e:
                logger.exception(f"Failed to re-enqueue after gate approval: {e}")
                return {
                    "success": True,
                    "message": (
                        f"Gate approved (phase transitioned to {next_phase.value}) "
                        f"but failed to re-enqueue execution: {e}"
                    ),
                    "run_id": exec_status.run_id,
                    "resumed": False,
                }

        # Update run status back to RUNNING
        try:
            self._run_service.update_progress(
                exec_status.run_id,
                RunProgressUpdate(
                    status="running",
                    current_step=f"Gate approved — resuming at {next_phase.value}",
                    metadata={
                        "phase": next_phase.value,
                        "gate_approved_by": user_id,
                        "step_type": "gate_approved",
                    },
                ),
            )
        except Exception as e:
            logger.warning(f"Failed to update run status after gate approval: {e}")

        # Emit telemetry
        self._telemetry.emit_event(
            event_type="work_item.gate.approved",
            payload={
                "work_item_id": work_item_id,
                "run_id": exec_status.run_id,
                "phase": current_phase.value,
                "next_phase": next_phase.value,
                "user_id": user_id,
                "notes": notes,
            },
            run_id=exec_status.run_id,
        )

        return {
            "success": True,
            "message": (
                f"Gate approved at {current_phase.value}. "
                f"Execution transitioning to {next_phase.value}."
            ),
            "run_id": exec_status.run_id,
            "resumed": resumed,
        }

    def list_executions(
        self,
        org_id: Optional[str] = None,
        project_id: Optional[str] = None,
        status: Optional[ExecutionState] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[ExecutionStatusResponse]:
        """List recent executions for an organization/project.

        Args:
        org_id: Organization ID (optional)
            project_id: Filter by project ID (optional)
            status: Filter by execution status (optional)
            limit: Maximum results (default 50)
            offset: Pagination offset

        Returns:
            List of execution status responses
        """
        # Query runs that are work item executions
        runs = self._run_service.list_runs(
            workflow_id="work_item_execution",
            limit=limit + offset,  # Get extra for offset handling
        )

        # Filter by org/project from metadata
        filtered_runs = []
        for run in runs:
            run_org_id = run.metadata.get("org_id")
            run_project_id = run.metadata.get("project_id")

            if org_id is not None and run_org_id != org_id:
                continue
            if project_id and run_project_id != project_id:
                continue

            # Filter by status if provided
            run_status = self._map_run_status(run.status)
            if status and run_status != status:
                continue

            filtered_runs.append(run)

        # Apply offset and limit
        filtered_runs = filtered_runs[offset:offset + limit]

        # Convert to ExecutionStatusResponse
        results = []
        for run in filtered_runs:
            work_item_id = run.metadata.get("work_item_id", "")
            cycle_id = run.metadata.get("cycle_id", "")

            # Get phase from cycle
            phase = CyclePhase.PLANNING.value
            if cycle_id:
                cycle = self._task_cycle_service.get_cycle(cycle_id)
                if cycle:
                    phase = cycle.current_phase.value

            results.append(
                self._execution_status_from_run(
                    run,
                    work_item_id=work_item_id,
                    cycle_id=cycle_id,
                    phase=phase,
                )
            )

        return results

    def get_execution_by_run_id(
        self,
        run_id: str,
        org_id: Optional[str] = None,
    ) -> Optional[ExecutionStatusResponse]:
        """Get execution status by run ID.

        Args:
            run_id: The run ID to look up
            org_id: Organization ID for validation (optional)

        Returns:
            Execution status or None if not found
        """
        try:
            run = self._run_service.get_run(run_id)
        except RunNotFoundError:
            return None

        # Validate org_id if provided
        if org_id:
            run_org_id = run.metadata.get("org_id")
            if run_org_id and run_org_id != org_id:
                return None

        # Get work item ID and cycle ID from metadata
        work_item_id = run.metadata.get("work_item_id", "")
        cycle_id = run.metadata.get("cycle_id", "")

        # Phase from GEP cycle unless this is a research pipeline run (metadata-driven).
        run_md = run.metadata or {}
        phase = CyclePhase.PLANNING.value
        if cycle_id:
            cycle = self._task_cycle_service.get_cycle(cycle_id)
            if cycle:
                phase = cycle.current_phase.value
        if run_md.get("execution_pipeline") == "research":
            rp = run_md.get("phase")
            if isinstance(rp, str) and rp.strip():
                phase = rp.strip()
        else:
            rp = run_md.get("phase")
            if (
                isinstance(rp, str)
                and rp.strip().startswith("research_")
                and phase == CyclePhase.PLANNING.value
            ):
                phase = rp.strip()

        return self._execution_status_from_run(
            run,
            work_item_id=work_item_id,
            cycle_id=cycle_id,
            phase=phase,
        )

    def get_execution_steps(
        self,
        run_id: str,
        org_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Get execution steps for a run.

        Returns step-by-step trace of execution including LLM calls, tool calls, etc.

        Args:
            run_id: The run ID to get steps for
            org_id: Organization ID for validation (optional)
            limit: Maximum steps to return
            offset: Pagination offset

        Returns:
            List of execution step dictionaries
        """
        try:
            run = self._run_service.get_run(run_id)
        except RunNotFoundError:
            return []

        # Validate org_id if provided
        if org_id:
            run_org_id = run.metadata.get("org_id")
            if run_org_id and run_org_id != org_id:
                return []

        # Get steps from run
        steps = run.steps[offset:offset + limit]

        # Convert RunStep to dict with execution-specific fields
        result = []
        for i, step in enumerate(steps):
            # RunStep has: step_id, name, status, started_at, completed_at, progress_pct, metadata
            step_metadata = self._step_metadata(step)
            tool_calls = step_metadata.get("tool_calls")
            duration_ms = step_metadata.get("duration_ms") or step_metadata.get("elapsed_ms")
            if not isinstance(duration_ms, int):
                duration_ms = self._duration_ms(step.started_at, step.completed_at)
            step_dict = {
                "step_id": step.step_id or f"{run_id}-step-{offset + i}",
                "step_number": offset + i + 1,
                "name": step.name,
                "status": step.status,
                "phase": step_metadata.get("phase", "unknown"),
                "step_type": step_metadata.get("step_type", step.name or "unknown"),
                "started_at": step.started_at,
                "completed_at": step.completed_at,
                "progress_pct": step.progress_pct,
                "duration_ms": duration_ms,
                "input_tokens": step_metadata.get("input_tokens", 0),
                "output_tokens": step_metadata.get("output_tokens", 0),
                "cost_usd": step_metadata.get("cost_usd"),
                "tool_calls": self._tool_call_count(tool_calls),
                "content_preview": step_metadata.get("content_preview"),
                "content_full": step_metadata.get("content_full"),  # Full content for detail view
                "tool_names": self._tool_names(tool_calls) or step_metadata.get("tool_names"),
                "model_id": step_metadata.get("model_id"),
                "error": step_metadata.get("error"),
                "metadata": step_metadata,
            }
            result.append(step_dict)

        return result

    async def _build_execution_resource_inventory(
        self,
        *,
        query: str,  # noqa: ARG002 - reserved for future query-specific fetching
        resource_type: Optional[str] = None,  # noqa: ARG002 - reserved for narrower fetches
        intent: Optional[str] = None,  # noqa: ARG002 - reserved for narrower fetches
        user_id: Optional[str] = None,  # noqa: ARG002 - access is enforced by underlying services
        org_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build an access-scoped resource inventory for agent analysis tools."""
        projects: List[Dict[str, Any]] = []
        boards_by_project: Dict[str, List[Dict[str, Any]]] = {}
        work_items_by_project: Dict[str, List[Dict[str, Any]]] = {}

        if project_id:
            projects.append({"project_id": project_id, "id": project_id, "name": project_id})
            try:
                boards = self._board_service.list_boards(
                    project_id=project_id,
                    org_id=org_id,
                    limit=100,
                    offset=0,
                )
                boards_by_project[project_id] = [self._resource_to_dict(board) for board in boards]
            except Exception as exc:
                logger.warning("resource_analysis.board_inventory_failed project_id=%s err=%s", project_id, exc)
                boards_by_project[project_id] = []
            try:
                items = self._board_service.list_work_items(
                    project_id=project_id,
                    org_id=org_id,
                    limit=100,
                    offset=0,
                )
                if isinstance(items, tuple):
                    items = items[0]
                work_items_by_project[project_id] = [self._resource_to_dict(item) for item in items]
            except Exception as exc:
                logger.warning("resource_analysis.work_item_inventory_failed project_id=%s err=%s", project_id, exc)
                work_items_by_project[project_id] = []

        try:
            runs = [self._resource_to_dict(run) for run in self._run_service.list_runs(limit=50)]
        except Exception as exc:
            logger.warning("resource_analysis.run_inventory_failed err=%s", exc)
            runs = []

        return {
            "projects": projects,
            "boards_by_project": boards_by_project,
            "work_items_by_project": work_items_by_project,
            "runs": runs,
            "agent_assignments": [],
        }

    def _map_run_status(self, run_status: str) -> ExecutionState:
        """Map RunStatus string to ExecutionState."""
        status_map = {
            RunStatus.PENDING: ExecutionState.PENDING,
            RunStatus.RUNNING: ExecutionState.RUNNING,
            RunStatus.COMPLETED: ExecutionState.COMPLETED,
            RunStatus.FAILED: ExecutionState.FAILED,
            RunStatus.CANCELLED: ExecutionState.CANCELLED,
        }
        # run_status is a string, compare to RunStatus values
        for rs, es in status_map.items():
            if run_status == rs:
                return es
        return ExecutionState.PENDING

    @staticmethod
    def _execution_observability_context(run: Run) -> Dict[str, Any]:
        metadata = run.metadata or {}
        raw_context = metadata.get("execution_observability")
        context = dict(raw_context) if isinstance(raw_context, dict) else {}
        for key in (
            "run_id",
            "cycle_id",
            "work_item_id",
            "project_id",
            "org_id",
            "agent_id",
            "model_id",
            "surface",
            "conversation_id",
            "message_id",
            "request_id",
            "execution_mode",
            "source_type",
            "queue_job_id",
        ):
            if context.get(key) is None and metadata.get(key) is not None:
                context[key] = metadata.get(key)
        return context

    @staticmethod
    def _step_metadata(step: RunStep) -> Dict[str, Any]:
        metadata = step.metadata or {}
        input_data = metadata.get("input_data")
        if isinstance(input_data, dict):
            return {**metadata, **input_data}
        return dict(metadata)

    @staticmethod
    def _tool_call_count(value: Any) -> int:
        if isinstance(value, list):
            return len(value)
        if isinstance(value, int):
            return value
        return 0

    @staticmethod
    def _tool_names(value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        return [
            str(tool_call.get("tool_name"))
            for tool_call in value
            if isinstance(tool_call, dict) and tool_call.get("tool_name")
        ]

    @staticmethod
    def _duration_ms(started_at: Optional[str], completed_at: Optional[str]) -> Optional[int]:
        if not started_at or not completed_at:
            return None
        try:
            start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            end = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        except ValueError:
            return None
        return max(0, int((end - start).total_seconds() * 1000))

    def _summarize_run_trace(self, run: Run) -> Dict[str, Any]:
        phase_timings: Dict[str, Dict[str, Any]] = {}
        total_input_tokens = 0
        total_output_tokens = 0
        total_cost_usd = 0.0
        total_cost_seen = False
        tool_count = 0
        last_error = run.error

        for step in run.steps:
            metadata = self._step_metadata(step)
            phase = str(metadata.get("phase") or "unknown")
            phase_entry = phase_timings.setdefault(
                phase,
                {
                    "step_count": 0,
                    "tool_count": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "duration_ms": 0,
                    "started_at": None,
                    "completed_at": None,
                },
            )
            input_tokens = int(metadata.get("input_tokens") or 0)
            output_tokens = int(metadata.get("output_tokens") or 0)
            step_tool_count = self._tool_call_count(metadata.get("tool_calls"))
            duration_ms = metadata.get("duration_ms") or metadata.get("elapsed_ms")
            if not isinstance(duration_ms, int):
                duration_ms = self._duration_ms(step.started_at, step.completed_at) or 0

            total_input_tokens += input_tokens
            total_output_tokens += output_tokens
            tool_count += step_tool_count
            if metadata.get("cost_usd") is not None:
                total_cost_seen = True
                total_cost_usd += float(metadata.get("cost_usd") or 0.0)
            if metadata.get("error"):
                last_error = str(metadata.get("error"))

            phase_entry["step_count"] += 1
            phase_entry["tool_count"] += step_tool_count
            phase_entry["input_tokens"] += input_tokens
            phase_entry["output_tokens"] += output_tokens
            phase_entry["duration_ms"] += duration_ms
            if step.started_at and (
                phase_entry["started_at"] is None or step.started_at < phase_entry["started_at"]
            ):
                phase_entry["started_at"] = step.started_at
            if step.completed_at and (
                phase_entry["completed_at"] is None or step.completed_at > phase_entry["completed_at"]
            ):
                phase_entry["completed_at"] = step.completed_at

        return {
            "phase_timings": phase_timings,
            "total_tokens": total_input_tokens + total_output_tokens,
            "total_cost_usd": total_cost_usd if total_cost_seen else None,
            "tool_count": tool_count,
            "last_error": last_error,
        }

    def _execution_status_from_run(
        self,
        run: Run,
        *,
        work_item_id: str,
        cycle_id: str,
        phase: str,
        pending_clarifications: Optional[List[Dict[str, Any]]] = None,
    ) -> ExecutionStatusResponse:
        metadata = run.metadata or {}
        context = self._execution_observability_context(run)
        summary = self._summarize_run_trace(run)
        queue_metadata = metadata.get("queue_metadata")
        if not isinstance(queue_metadata, dict):
            queue_metadata = {
                key: value
                for key, value in {
                    "queue_job_id": context.get("queue_job_id"),
                    "dispatch_mode": metadata.get("dispatch_mode"),
                    "queue_name": metadata.get("queue_name"),
                    "queue_attempt": metadata.get("queue_attempt"),
                }.items()
                if value is not None
            }
        from amprealize.knowledge_retrieval_receipt import (
            RECEIPT_METADATA_KEY,
            trace_summary_knowledge_slice,
        )

        raw_receipt = metadata.get(RECEIPT_METADATA_KEY)
        knowledge_retrieval = trace_summary_knowledge_slice(
            raw_receipt if isinstance(raw_receipt, dict) else None,
        )

        trace_summary = {
            "origin": {
                "surface": context.get("surface") or metadata.get("surface"),
                "source_type": context.get("source_type") or metadata.get("source_type"),
                "conversation_id": context.get("conversation_id") or metadata.get("conversation_id"),
                "message_id": context.get("message_id") or metadata.get("message_id"),
                "request_id": context.get("request_id") or metadata.get("request_id"),
            },
            "execution": {
                "run_id": run.run_id,
                "cycle_id": cycle_id,
                "work_item_id": work_item_id,
                "agent_id": context.get("agent_id") or metadata.get("agent_id"),
                "model_id": context.get("model_id") or metadata.get("model_id"),
                "execution_mode": context.get("execution_mode") or metadata.get("execution_mode"),
                "status": self._map_run_status(run.status).value,
                "phase": phase,
            },
            "queue": queue_metadata,
            "metrics": {
                "step_count": len(run.steps),
                "tool_count": summary["tool_count"],
                "total_tokens": summary["total_tokens"],
                "total_cost_usd": summary["total_cost_usd"],
            },
            "phase_timings": summary["phase_timings"],
            "last_error": summary["last_error"],
            "knowledge_retrieval": knowledge_retrieval,
        }

        return ExecutionStatusResponse(
            run_id=run.run_id,
            cycle_id=cycle_id,
            work_item_id=work_item_id,
            status=self._map_run_status(run.status),
            phase=phase,
            progress_pct=run.progress_pct,
            current_step=run.current_step,
            started_at=run.started_at,
            completed_at=run.completed_at,
            error=run.error,
            model_id=context.get("model_id") or metadata.get("model_id"),
            step_count=len(run.steps),
            pending_clarifications=pending_clarifications,
            agent_id=context.get("agent_id") or metadata.get("agent_id"),
            project_id=context.get("project_id") or metadata.get("project_id"),
            org_id=context.get("org_id") or metadata.get("org_id"),
            surface=context.get("surface") or metadata.get("surface"),
            source_type=context.get("source_type") or metadata.get("source_type"),
            conversation_id=context.get("conversation_id") or metadata.get("conversation_id"),
            message_id=context.get("message_id") or metadata.get("message_id"),
            request_id=context.get("request_id") or metadata.get("request_id"),
            execution_mode=context.get("execution_mode") or metadata.get("execution_mode"),
            queue_job_id=context.get("queue_job_id") or metadata.get("queue_job_id"),
            queue_metadata=queue_metadata,
            phase_timings=summary["phase_timings"],
            trace_summary=trace_summary,
            total_tokens=summary["total_tokens"],
            total_cost_usd=summary["total_cost_usd"],
            tool_count=summary["tool_count"],
            last_error=summary["last_error"],
            execution_workspace_kind=metadata.get("execution_workspace_kind"),
            connector_status=metadata.get("connector_status"),
        )

    @staticmethod
    def _resource_to_dict(value: Any) -> Dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return dict(value)
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if hasattr(value, "to_dict"):
            return value.to_dict()
        data: Dict[str, Any] = {}
        for key in dir(value):
            if key.startswith("_"):
                continue
            try:
                attr = getattr(value, key)
            except Exception:
                continue
            if callable(attr):
                continue
            data[key] = attr
        return data

    # =========================================================================
    # Private Helpers
    # =========================================================================

    def _get_work_item(
        self,
        work_item_id: str,
        org_id: Optional[str],
    ) -> Optional[WorkItem]:
        """Load a work item by ID."""
        try:
            return self._board_service.get_work_item(
                item_id=work_item_id,
                org_id=org_id,
            )
        except WorkItemNotFoundError:
            return None
        except Exception as e:
            logger.exception(f"Error loading work item {work_item_id}: {e}")
            return None

    def _load_agent(
        self,
        agent_id: str,
        org_id: Optional[str],  # noqa: ARG002 - reserved for future multi-tenant
    ) -> Tuple[Optional[Agent], Optional[AgentVersion]]:
        """Load agent and active version."""
        try:
            result = self._agent_registry.get_agent(agent_id)
            if result:
                # Result is dict with 'agent' and 'versions' keys
                agent_dict = result.get("agent")
                versions = result.get("versions", [])
                if agent_dict:
                    agent = Agent(**agent_dict) if isinstance(agent_dict, dict) else agent_dict
                    # Find active version from versions list
                    active_version = None
                    for v in versions:
                        if isinstance(v, dict):
                            # Remove fields not in AgentVersion dataclass
                            v_clean = {k: val for k, val in v.items() if k != "version_id"}
                            v_obj = AgentVersion(**v_clean)
                        else:
                            v_obj = v
                        if getattr(v_obj, "is_active", False) or v_obj.status == "ACTIVE":
                            active_version = v_obj
                            break
                    return agent, active_version
            return None, None
        except Exception as e:
            logger.exception(f"Error loading agent {agent_id}: {e}")
            return None, None

    def _resolve_ai_research_agent_id(self) -> str:
        """Resolve the builtin AI Research agent by stable slug."""
        agent = None
        if hasattr(self._agent_registry, "_find_agent_by_slug"):
            agent = self._agent_registry._find_agent_by_slug("ai_research")
        if agent is None:
            raise AgentNotFoundError(
                "Builtin AI Research agent is not registered; bootstrap agent playbooks before executing research work items"
            )
        return agent.agent_id

    def _get_agent_execution_policy(
        self,
        agent_version: Optional[AgentVersion],
    ) -> ExecutionPolicy:
        """Get execution policy from agent version metadata or use preset based on agent type."""
        if not agent_version:
            return ExecutionPolicy()

        # Check for explicit execution policy in agent metadata
        policy_data = agent_version.metadata.get("execution_policy", {})
        if policy_data:
            return ExecutionPolicy.from_dict(policy_data)

        # Use agent-specific presets based on agent name/slug
        agent_id_lower = (agent_version.agent_id or "").lower()
        agent_slug = agent_version.metadata.get("slug", "").lower()

        # Research agents: skip TESTING/FIXING/VERIFYING
        if any(x in agent_id_lower or x in agent_slug for x in ["research", "ai_research"]):
            logger.info(f"Using research agent preset for {agent_version.agent_id}")
            return ExecutionPolicy.for_research_agent()

        # Architect agents: skip TESTING/FIXING
        if any(x in agent_id_lower or x in agent_slug for x in ["architect", "architecture"]):
            logger.info(f"Using architect agent preset for {agent_version.agent_id}")
            return ExecutionPolicy.for_architect_agent()

        # Engineering agents: run all phases
        if any(x in agent_id_lower or x in agent_slug for x in ["engineer", "developer", "coding"]):
            logger.info(f"Using engineering agent preset for {agent_version.agent_id}")
            return ExecutionPolicy.for_engineering_agent()

        # Default: fully autonomous (no gates, all phases)
        return ExecutionPolicy.fully_autonomous()

    def _update_work_item_run(
        self,
        work_item_id: str,
        run_id: str,
        org_id: Optional[str],
    ) -> None:
        """Update work item with run_id link."""
        try:
            from amprealize.boards.contracts import UpdateWorkItemRequest
            from amprealize.services.board_service import Actor as BoardActor
            actor = BoardActor(id="system", role="system", surface="internal")
            request = UpdateWorkItemRequest(run_id=run_id)  # type: ignore[call-arg]
            self._board_service.update_work_item(
                item_id=work_item_id,
                request=request,
                actor=actor,
                org_id=org_id,
            )
        except Exception as e:
            logger.exception(f"Error updating work item {work_item_id} with run_id: {e}")

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
            actor = BoardActor(id="system", role="system", surface="internal")

            self._board_service.add_comment(
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
                f"{content[:100]}... (author: {author_id}, type: {author_type})"
            )
        except Exception as e:
            logger.exception(f"Error posting comment to work item {work_item_id}: {e}")

    def _move_to_completed(
        self,
        work_item_id: str,
        org_id: Optional[str],
    ) -> None:
        """Move work item to completed column."""
        try:
            from amprealize.boards.contracts import UpdateWorkItemRequest, WorkItemStatus, MoveWorkItemRequest
            from amprealize.services.board_service import Actor as BoardActor
            actor = BoardActor(id="system", role="system", surface="internal")

            # Update status to DONE
            request = UpdateWorkItemRequest(status=WorkItemStatus.DONE)  # type: ignore[call-arg]
            self._board_service.update_work_item(
                item_id=work_item_id,
                request=request,
                actor=actor,
                org_id=org_id,
            )

            # Find column with status_mapping=done and move item
            item = self._board_service.get_work_item(work_item_id, org_id=org_id)
            if item.board_id:
                done_column = self._board_service.get_column_by_status_mapping(
                    board_id=item.board_id,
                    status_mapping=WorkItemStatus.DONE,
                    org_id=org_id,
                )
                if done_column:
                    move_request = MoveWorkItemRequest(
                        column_id=done_column.column_id,
                        position=0,
                    )
                    self._board_service.move_work_item(
                        item_id=work_item_id,
                        request=move_request,
                        actor=actor,
                        org_id=org_id,
                    )
                    logger.info(f"Moved work item {work_item_id} to done column {done_column.column_id}")

        except Exception as e:
            logger.exception(f"Error moving work item {work_item_id} to completed: {e}")

    def _generate_summary(self, run: Run) -> str:
        """Generate a concise execution summary for posting as a comment."""
        # Build summary from run data
        lines = ["## Execution Summary\n"]

        # Status
        lines.append(f"**Status:** {run.status}")

        # Duration
        if run.duration_ms:
            duration_s = run.duration_ms / 1000
            if duration_s > 60:
                lines.append(f"**Duration:** {duration_s / 60:.1f} minutes")
            else:
                lines.append(f"**Duration:** {duration_s:.1f} seconds")

        # Steps completed
        if run.steps:
            lines.append(f"**Steps Completed:** {len(run.steps)}")

        # Outputs
        if run.outputs:
            lines.append("\n### Outputs")
            if "files_changed" in run.outputs:
                lines.append(f"- Files changed: {run.outputs['files_changed']}")
            if "pr_url" in run.outputs:
                lines.append(f"- PR: {run.outputs['pr_url']}")
            if "summary" in run.outputs:
                lines.append(f"\n{run.outputs['summary']}")

        # Error (if failed)
        if run.error:
            lines.append(f"\n### Error\n```\n{run.error}\n```")

        return "\n".join(lines)
