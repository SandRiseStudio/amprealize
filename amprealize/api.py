"""FastAPI application exposing Amprealize service stubs over HTTP."""

from __future__ import annotations

# Load environment variables from .env files before anything else
from pathlib import Path as _Path
from dotenv import load_dotenv as _load_dotenv

_project_root = _Path(__file__).parent.parent
for _env_file in [".env", ".env.github-oauth", ".env.google-oauth"]:
    _env_path = _project_root / _env_file
    if _env_path.exists():
        _load_dotenv(_env_path)

# Apply active context DSN(s) to environment after loading .env.
# This overrides hardcoded localhost DSNs in .env with the active context's
# DSN (e.g., Neon cloud DB), ensuring API services connect to the right DB.
try:
    from amprealize.context import apply_context_to_environment as _apply_ctx
    _apply_ctx(force=True)
except Exception:
    pass  # Context bridge is best-effort; don't block API startup

import asyncio
import base64
from datetime import datetime, timezone
import html
import json
import logging
import os
import secrets
import textwrap
import uuid
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, cast

from fastapi import FastAPI, HTTPException, Query, Response, status, Request, Form, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, ValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.websockets import WebSocket, WebSocketDisconnect

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class _UnavailableFeatureAdapter:
    def __init__(self, feature_name: str, reason: Exception) -> None:
        self._feature_name = feature_name
        self._reason = reason

    def __getattr__(self, method_name: str) -> Any:
        def _raise_unavailable(*args: Any, **kwargs: Any) -> Any:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"{self._feature_name} is unavailable: {self._reason}",
            )

        return _raise_unavailable

from .action_service import (
    ActionNotFoundError,
    ActionService,
    ActionServiceError,
    ReplayNotFoundError,
)
from .action_contracts import Actor
from .action_service_postgres import PostgresActionService
from .execution_event_hub import ExecutionEventHub
from .adapters import (
    RestActionServiceAdapter,
    RestAgentAuthServiceAdapter,
    RestAgentOrchestratorAdapter,
    RestAgentRegistryAdapter,
    RestBreakerAmpAdapter,
    RestBehaviorServiceAdapter,
    RestBCIAdapter,
    RestComplianceServiceAdapter,
    RestMetricsServiceAdapter,
    RestReflectionAdapter,
    RestRunServiceAdapter,
    RestTaskAssignmentAdapter,
    RestAssignmentAdapter,
    RestWorkflowServiceAdapter,
)
from .breakeramp import (
    PlanRequest,
    PlanResponse,
    ApplyRequest,
    ApplyResponse,
    StatusResponse,
    DestroyRequest,
    DestroyResponse,
    BreakerAmpService,
)
from .behavior_service import (
    BehaviorNotFoundError,
    BehaviorService,
    BehaviorServiceError,
)

# Agent Registry imports (lazy to avoid circular imports at startup)
try:
    from .agent_registry_service import (
        AgentRegistryService,
        AgentNotFoundError,
        AgentVersionNotFoundError,
        AgentRegistryError,
    )
    AGENT_REGISTRY_AVAILABLE = True
except ImportError:
    AGENT_REGISTRY_AVAILABLE = False
    AgentRegistryService = None  # type: ignore[assignment, misc]
    AgentNotFoundError = Exception  # type: ignore[assignment, misc]
    AgentVersionNotFoundError = Exception  # type: ignore[assignment, misc]
    AgentRegistryError = Exception  # type: ignore[assignment, misc]
from .compliance_service import (
    ChecklistNotFoundError,
    ComplianceService,
    ComplianceServiceError,
)
from .agent_auth import AgentAuthClient
from .auth.providers import InvalidCredentialsError, OAuthError
from .auth.providers.github import GitHubOAuthProvider
from .auth.providers.google import GoogleOAuthProvider
from .auth.user_auth_service import UserAuthService
from .auth.service_principal_service import (
    ServicePrincipalService,
    CreateServicePrincipalRequest,
)
from .device_flow import (
    DeviceAuthorizationStatus,
    DeviceAuthorizationSession,
    DeviceFlowManager,
    DeviceTokens,
    DeviceCodeNotFoundError,
    UserCodeNotFoundError,
    DeviceCodeExpiredError,
    DeviceFlowError,
    RefreshTokenNotFoundError,
    RefreshTokenExpiredError,
)
from .task_assignments import TaskAssignmentService
from .telemetry import TelemetryClient, create_sink_from_env
from .workflow_service import WorkflowService, WorkflowStatus
from .analytics.telemetry_kpi_projector import TelemetryKPIProjector, TelemetryProjection
from .analytics.warehouse import AnalyticsWarehouse
from .metrics_service import MetricsService
from .metrics_service_postgres import PostgresMetricsService
from .collaboration_contracts import (
    CollaborationRole,
    CreateDocumentRequest,
    CreateWorkspaceRequest,
    EditOperationType,
    RealTimeEditRequest,
)
from .collaboration_service import CollaborationService, VersionConflictError
from .collaboration_service_postgres import PostgresCollaborationService
from .projects_api import create_project_routes
from .run_service import RunService, RunNotFoundError
from .run_service_postgres import PostgresRunService
from .utils.dsn import resolve_optional_postgres_dsn
from .services.board_service import BoardService
from .services.assignment_service import AssignmentService
from .services.board_api_v2 import create_board_routes

# Notification system
try:
    from .notifications.gate_notifier import GateNotifier
    from .notifications.webhook_dispatcher import WebhookDispatcher
    NOTIFICATIONS_AVAILABLE = True
except ImportError:
    NOTIFICATIONS_AVAILABLE = False
    GateNotifier = None  # type: ignore[assignment, misc]
    WebhookDispatcher = None  # type: ignore[assignment, misc]

# Work Item Execution Service (optional - requires dependencies)
try:
    from .work_item_execution_service import WorkItemExecutionService
    from .execution_wiring import wire_execution_service
    WORK_ITEM_EXECUTION_AVAILABLE = True
except Exception as exc:
    WORK_ITEM_EXECUTION_AVAILABLE = False
    WorkItemExecutionService = None  # type: ignore[assignment, misc]
    wire_execution_service = None  # type: ignore[assignment, misc]
    logger.warning("Work item execution imports unavailable: %s", exc)

# Raze structured logging (optional dependency)
try:
    from raze import RazeService, RazeLogger
    from raze.sinks import InMemorySink
    from raze.integrations.fastapi import create_log_routes, RazeMiddleware
    RAZE_AVAILABLE = True
except ImportError:
    RAZE_AVAILABLE = False
    RazeService = None  # type: ignore[assignment, misc]
    RazeLogger = None  # type: ignore[assignment, misc]

# Multi-tenant organization management (optional - requires PostgreSQL)
try:
    from .multi_tenant.organization_service import OrganizationService
    from .multi_tenant.invitation_service import InvitationService
    from .multi_tenant.settings import SettingsService
    from .multi_tenant.api import ORG_ROUTES_AVAILABLE, create_org_routes
    from .multi_tenant.settings_api import SETTINGS_ROUTES_AVAILABLE, create_settings_routes
    MULTI_TENANT_AVAILABLE = OrganizationService is not None
except ImportError:
    MULTI_TENANT_AVAILABLE = False
    ORG_ROUTES_AVAILABLE = False
    SETTINGS_ROUTES_AVAILABLE = False
    OrganizationService = None  # type: ignore[assignment, misc]
    InvitationService = None  # type: ignore[assignment, misc]
    SettingsService = None  # type: ignore[assignment, misc]
    create_org_routes = None  # type: ignore[assignment, misc]
    create_settings_routes = None  # type: ignore[assignment, misc]

# Lightweight OSS project service (fallback when enterprise not installed)
from .projects.service import OSSProjectService

# Billing service (optional - requires billing package)
try:
    from billing import BillingService, MockBillingProvider
    try:
        from billing.providers.stripe import StripeBillingProvider
        STRIPE_AVAILABLE = True
    except ImportError:
        STRIPE_AVAILABLE = False
        StripeBillingProvider = None  # type: ignore[assignment, misc]
    from .billing.api import create_billing_router
    BILLING_AVAILABLE = True
except ImportError:
    BILLING_AVAILABLE = False
    BillingService = None  # type: ignore[assignment, misc]
    MockBillingProvider = None  # type: ignore[assignment, misc]
    StripeBillingProvider = None  # type: ignore[assignment, misc]
    create_billing_router = None  # type: ignore[assignment, misc]
    STRIPE_AVAILABLE = False


class _UnavailableWarehouse:
    """Fallback analytics warehouse that raises a helpful error when invoked."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def _unavailable(self, *_: Any, **__: Any) -> List[Dict[str, Any]]:
        raise RuntimeError(self._reason)

    get_kpi_summary = _unavailable
    get_behavior_usage = _unavailable
    get_token_savings = _unavailable
    get_compliance_coverage = _unavailable


class RouteCapabilitiesResponse(BaseModel):
    projects: bool = False
    participants: bool = False
    orgs: bool = False
    settings: bool = False
    executions: bool = False


class ServiceCapabilitiesResponse(BaseModel):
    project_service: bool = False
    org_service: bool = False
    settings_service: bool = False
    execution_enabled: bool = False
    execution_service: bool = False


class ApiCapabilitiesResponse(BaseModel):
    routes: RouteCapabilitiesResponse
    services: ServiceCapabilitiesResponse


class PlatformRuntimeMetadataResponse(BaseModel):
    """Shell footer metadata: semantic version, distribution, optional tier, context."""

    version: str
    distribution: Literal["oss", "enterprise"]
    edition: Optional[Literal["starter", "premium"]] = None
    context_name: str


def _env_flag(name: str, default: Optional[bool] = None) -> Optional[bool]:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


class _ServiceContainer:
    """Lazily constructed service instances shared by API routes."""

    def __init__(
        self,
        *,
        behavior_db_path: Optional[Path] = None,
        workflow_db_path: Optional[Path] = None,
        execution_event_hub: Optional[ExecutionEventHub] = None,
    ) -> None:
        logger = logging.getLogger(__name__)
        telemetry = TelemetryClient(
            sink=create_sink_from_env(),
            default_actor={
                "id": "amprealize-api",
                "role": "SYSTEM",
                "surface": "api",
            },
        )
        self.project_service_available = False
        self.participants_available = False
        self.org_routes_available = False
        self.settings_routes_available = False
        self.execution_service_available = False
        self.execution_enabled = False

        # ActionService now uses PostgreSQL DSN from environment or default
        action_dsn = resolve_optional_postgres_dsn(
            service="ACTION",
            explicit_dsn=None,
            env_var="AMPREALIZE_ACTION_PG_DSN",
        )
        if action_dsn:
            self.action_service = PostgresActionService(dsn=action_dsn, telemetry=telemetry)
        else:
            # Fallback to in-memory for testing
            self.action_service = ActionService(telemetry=telemetry)
        self.action_adapter = RestActionServiceAdapter(self.action_service)

        # ComplianceService uses PostgreSQL (required); resolves DSN from AMPREALIZE_COMPLIANCE_PG_DSN env var
        self.compliance_service = ComplianceService(dsn=None, telemetry=telemetry)
        self.compliance_adapter = RestComplianceServiceAdapter(self.compliance_service)

        # BehaviorService now uses PostgreSQL DSN from environment or default
        # behavior_db_path parameter is deprecated (was SQLite path)
        self.behavior_service = BehaviorService(
            dsn=None,  # Uses AMPREALIZE_BEHAVIOR_PG_DSN environment variable
            telemetry=telemetry,
        )
        self.behavior_adapter = RestBehaviorServiceAdapter(self.behavior_service)

        # Initialize ServicePrincipalService early so it can be injected into AgentRegistryService
        # Uses auth schema for persistence
        try:
            self.service_principal_service = ServicePrincipalService()
            logger.info("ServicePrincipalService initialized for agent API credentials")
        except Exception as exc:
            self.service_principal_service = None  # type: ignore[assignment]
            logger.warning("ServicePrincipalService unavailable: %s", exc)

        # AgentRegistryService uses PostgreSQL DSN from environment
        self.agent_registry_service = None
        self.agent_registry_adapter = None
        if AGENT_REGISTRY_AVAILABLE:
            agent_dsn = resolve_optional_postgres_dsn(
                service="AGENT_REGISTRY",
                explicit_dsn=None,
                env_var="AMPREALIZE_AGENT_REGISTRY_PG_DSN",
            )
            if agent_dsn:
                self.agent_registry_service = AgentRegistryService(
                    dsn=agent_dsn,
                    telemetry=telemetry,
                    service_principal_service=self.service_principal_service,
                )
                self.agent_registry_adapter = RestAgentRegistryAdapter(self.agent_registry_service)
            else:
                logger.warning("AgentRegistryService skipped: No DSN configured")

        self.behavior_retriever = None
        self.bci_service = None
        self.reflection_service = None
        try:
            # Import lazily to avoid pulling heavy BCI/retrieval dependencies during API module import.
            # This keeps unit tests that mock _ServiceContainer lightweight and avoids optional import churn.
            # The real service container still gets the full implementation here when dependencies are healthy.
            from .behavior_retriever import BehaviorRetriever
            from .bci_service import BCIService

            self.behavior_retriever = BehaviorRetriever(
                behavior_service=self.behavior_service,
                telemetry=telemetry,
                eager_load_model=False,  # Disable eager model loading to avoid OOM in staging
            )
            setattr(self.behavior_service, "_behavior_retriever", self.behavior_retriever)

            self.bci_service = BCIService(
                behavior_service=self.behavior_service,
                telemetry=telemetry,
                behavior_retriever=self.behavior_retriever,
            )
            self.bci_adapter = RestBCIAdapter(self.bci_service)

            # ReflectionService uses PostgreSQL DSN from environment or fallback to in-memory
            from .reflection_service import ReflectionService
            from .reflection_service_postgres import PostgresReflectionService

            reflection_dsn = resolve_optional_postgres_dsn(
                service="REFLECTION",
                explicit_dsn=None,
                env_var="AMPREALIZE_REFLECTION_PG_DSN",
            )
            if reflection_dsn:
                self.reflection_service = PostgresReflectionService(
                    dsn=reflection_dsn,
                    behavior_service=self.behavior_service,
                    bci_service=self.bci_service,
                    telemetry=telemetry,
                )
            else:
                self.reflection_service = ReflectionService(
                    behavior_service=self.behavior_service,
                    bci_service=self.bci_service,
                    telemetry=telemetry,
                )
            self.reflection_adapter = RestReflectionAdapter(self.reflection_service)
        except Exception as exc:
            logger.warning("BCI/Reflection services unavailable: %s", exc)
            self.bci_adapter = _UnavailableFeatureAdapter("BCI", exc)
            self.reflection_adapter = _UnavailableFeatureAdapter("Reflection", exc)

        # WorkflowService now uses PostgreSQL DSN from environment or default
        # workflow_db_path parameter is deprecated (was SQLite path)
        self.workflow_service = WorkflowService(
            dsn=None,  # Uses AMPREALIZE_WORKFLOW_PG_DSN environment variable
            behavior_service=self.behavior_service,
        )
        self.workflow_adapter = RestWorkflowServiceAdapter(self.workflow_service)

        # MetricsService uses PostgreSQL DSN from environment or fallback to in-memory cache
        metrics_dsn = resolve_optional_postgres_dsn(
            service="METRICS",
            explicit_dsn=None,
            env_var="AMPREALIZE_METRICS_PG_DSN",
        )
        if metrics_dsn:
            self.metrics_service = PostgresMetricsService(dsn=metrics_dsn)
        else:
            self.metrics_service = MetricsService()
        self.metrics_adapter = RestMetricsServiceAdapter(self.metrics_service)

        self.breakeramp_service = BreakerAmpService(
            action_service=cast(ActionService, self.action_service),
            compliance_service=self.compliance_service,
            metrics_service=self.metrics_service,
        )
        self.breakeramp_adapter = RestBreakerAmpAdapter(self.breakeramp_service)

        self.execution_event_hub = execution_event_hub

        # Initialize AgentAuth client and adapter
        self.agent_auth_client = AgentAuthClient(telemetry=telemetry)
        self.agent_auth_adapter = RestAgentAuthServiceAdapter(self.agent_auth_client)

        # Initialize UserAuthService for user lookup and management.
        # This uses auth.users table and replaces the deprecated InternalAuthProvider.
        user_auth_service: Optional[UserAuthService]
        try:
            user_auth_service = UserAuthService(dsn=None)
        except Exception as exc:
            user_auth_service = None
            logger.warning("UserAuthService unavailable; continuing without user auth: %s", exc)

        # Store for use by identity linking and other services
        self.user_auth_service = user_auth_service

        # Initialize device flow manager with PostgreSQL backing for shared state
        # This allows MCP server and API to share device flow sessions
        self.postgres_device_store = None
        auth_dsn = resolve_optional_postgres_dsn(
            service="AUTH",
            explicit_dsn=os.getenv("AMPREALIZE_AUTH_PG_DSN"),
            env_var="AMPREALIZE_AUTH_PG_DSN",
        )
        if auth_dsn:
            try:
                from amprealize.storage.postgres_pool import PostgresPool
                from amprealize.auth.postgres_device_flow import PostgresDeviceFlowStore

                auth_pool = PostgresPool(auth_dsn, schema="auth")
                self.postgres_device_store = PostgresDeviceFlowStore(pool=auth_pool)
                logger.info("PostgreSQL device flow store initialized for shared auth state")
            except Exception as exc:
                logger.warning(f"PostgreSQL device flow store unavailable: {exc}")

        # Fallback to in-memory manager (legacy)
        self.device_flow_manager = DeviceFlowManager(
            telemetry=telemetry,
            provider=None,  # InternalAuthProvider removed - device flow uses OAuth only
        )

        # Initialize OAuth providers for social login (GitHub, Google)
        # These are optional; if credentials are not set, the provider will be None
        self.github_provider: Optional[GitHubOAuthProvider] = None
        self.google_provider: Optional[GoogleOAuthProvider] = None

        github_client_id = os.getenv("GITHUB_CLIENT_ID") or os.getenv("OAUTH_CLIENT_ID")
        github_client_secret = os.getenv("GITHUB_CLIENT_SECRET") or os.getenv("OAUTH_CLIENT_SECRET")
        if github_client_id and github_client_secret:
            self.github_provider = GitHubOAuthProvider(
                client_id=github_client_id,
                client_secret=github_client_secret,
            )
            logger.info("GitHub OAuth provider initialized for social login")
        else:
            logger.info("GitHub OAuth provider not configured (missing GITHUB_CLIENT_ID/SECRET)")

        google_client_id = os.getenv("GOOGLE_CLIENT_ID")
        google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        if google_client_id and google_client_secret:
            self.google_provider = GoogleOAuthProvider(
                client_id=google_client_id,
                client_secret=google_client_secret,
            )
            logger.info("Google OAuth provider initialized for social login")
        else:
            logger.info("Google OAuth provider not configured (missing GOOGLE_CLIENT_ID/SECRET)")

        # RunService uses PostgreSQL DSN from environment or fallback to SQLite
        run_dsn = resolve_optional_postgres_dsn(
            service="RUN",
            explicit_dsn=None,
            env_var="AMPREALIZE_RUN_PG_DSN",
        )
        if run_dsn:
            self.run_service = PostgresRunService(dsn=run_dsn, telemetry=telemetry, event_hub=execution_event_hub)
        else:
            self.run_service = RunService(telemetry=telemetry, event_hub=execution_event_hub)
        self.run_adapter = RestRunServiceAdapter(self.run_service)

        # CollaborationService uses PostgreSQL DSN from environment or falls back to in-memory.
        collaboration_dsn = resolve_optional_postgres_dsn(
            service="COLLABORATION",
            explicit_dsn=None,
            env_var="AMPREALIZE_COLLABORATION_PG_DSN",
        )
        if collaboration_dsn:
            self.collaboration_service = PostgresCollaborationService(dsn=collaboration_dsn, telemetry=telemetry)
        else:
            self.collaboration_service = CollaborationService(telemetry=telemetry)

        self.task_assignment_service = TaskAssignmentService()
        self.task_adapter = RestTaskAssignmentAdapter(self.task_assignment_service)

        # Projects use OrganizationService exclusively

        # Board/Assignment services for agent suggestions
        self.board_service = BoardService(pool=None, telemetry=telemetry)

        # Wire up agent validator to prevent orphaned agent assignments
        # This validates that assigned agents actually exist in the registry
        def _validate_agent_exists(agent_id: str, org_id: Optional[str]) -> bool:
            """Check if an agent exists in the registry (execution.agents table)."""
            if not self.agent_registry_service:
                logger.warning("Agent validation skipped: AgentRegistryService not available")
                return True  # Permissive fallback if service unavailable
            try:
                # Try to fetch the agent - if it exists, validation passes
                self.agent_registry_service.get_agent(agent_id)
                return True
            except AgentNotFoundError:
                logger.warning(f"Agent validation failed: Agent '{agent_id}' not found in registry")
                return False
            except Exception as e:
                logger.warning(f"Agent validation error for {agent_id}: {e}")
                return False

        self.board_service.set_agent_validator(_validate_agent_exists)

        self.assignment_service = AssignmentService(
            dsn=None,
            telemetry=telemetry,
            board_service=self.board_service,
        )
        self.assignment_adapter = RestAssignmentAdapter(self.assignment_service)

        # Multi-tenant organization services (requires PostgreSQL)
        self.org_service: Optional[Any] = None
        self.invitation_service: Optional[Any] = None
        self.settings_service: Optional[Any] = None
        org_dsn = resolve_optional_postgres_dsn(
            service="ORG",
            explicit_dsn=os.getenv("AMPREALIZE_ORG_PG_DSN") or os.getenv("AMPREALIZE_AUTH_PG_DSN"),
            env_var="AMPREALIZE_ORG_PG_DSN",
        )
        enterprise_org_routes_available = bool(
            MULTI_TENANT_AVAILABLE
            and ORG_ROUTES_AVAILABLE
            and SETTINGS_ROUTES_AVAILABLE
            and OrganizationService is not None
            and InvitationService is not None
            and SettingsService is not None
            and create_org_routes is not None
            and create_settings_routes is not None
        )
        if enterprise_org_routes_available and org_dsn:
            self.org_service = OrganizationService(
                dsn=org_dsn,
                board_service=self.board_service,
            )
            self.invitation_service = InvitationService(
                dsn=org_dsn,
                base_url=os.getenv("AMPREALIZE_BASE_URL", "https://amprealize.com"),
            )
            self.settings_service = SettingsService(dsn=org_dsn)
        elif org_dsn:
            # OSS fallback: project-scoped features only, no org/settings route families.
            self.org_service = OSSProjectService(dsn=org_dsn)
            logger.info("Using OSS project service (enterprise not installed)")
        self.project_service_available = self.org_service is not None
        self.participants_available = self.project_service_available
        self.org_routes_available = bool(
            enterprise_org_routes_available
            and self.org_service is not None
            and self.invitation_service is not None
        )
        self.settings_routes_available = bool(
            enterprise_org_routes_available
            and self.settings_service is not None
        )

        # Billing service (uses Stripe if credentials provided, otherwise mock)
        self.billing_service: Optional[Any] = None
        if BILLING_AVAILABLE:
            stripe_api_key = os.getenv("AMPREALIZE_STRIPE_API_KEY")
            stripe_webhook_secret = os.getenv("AMPREALIZE_STRIPE_WEBHOOK_SECRET")
            if STRIPE_AVAILABLE and stripe_api_key:
                provider = StripeBillingProvider(
                    api_key=stripe_api_key,
                    webhook_secret=stripe_webhook_secret,
                )
                logger.info("BillingService initialized with Stripe provider")
            else:
                provider = MockBillingProvider()
                logger.info("BillingService initialized with Mock provider (no Stripe credentials)")
            self.billing_service = BillingService(provider=provider)

        # Analytics: supports DuckDB (AMPREALIZE_ANALYTICS_WAREHOUSE_PATH) or
        # Postgres/TimescaleDB (AMPREALIZE_ANALYTICS_PG_DSN or AMPREALIZE_TELEMETRY_PG_DSN)
        warehouse_path = os.getenv("AMPREALIZE_ANALYTICS_WAREHOUSE_PATH")
        analytics_dsn = resolve_optional_postgres_dsn(
            service="ANALYTICS",
            explicit_dsn=os.getenv("AMPREALIZE_ANALYTICS_PG_DSN") or os.getenv("AMPREALIZE_TELEMETRY_PG_DSN"),
            env_var="AMPREALIZE_ANALYTICS_PG_DSN",
        )
        if AnalyticsWarehouse is None:
            self.analytics_warehouse = _UnavailableWarehouse("Analytics warehouse not available (enterprise)")
        elif warehouse_path:
            self.analytics_warehouse = AnalyticsWarehouse(db_path=Path(warehouse_path))
        elif analytics_dsn:
            self.analytics_warehouse = AnalyticsWarehouse(dsn=analytics_dsn)
        else:
            self.analytics_warehouse = _UnavailableWarehouse("Analytics warehouse not configured")

        self.telemetry_projector = TelemetryKPIProjector()

        # Raze structured logging service (optional)
        self.raze_service: Optional[Any] = None
        if RAZE_AVAILABLE:
            raze_dsn = os.getenv("RAZE_TIMESCALEDB_DSN") or os.getenv("AMPREALIZE_RAZE_DSN")
            if raze_dsn:
                try:
                    from raze.sinks import TimescaleDBSink
                    raze_sink = TimescaleDBSink(dsn=raze_dsn)
                except Exception:
                    # Fallback to in-memory if TimescaleDB unavailable
                    raze_sink = InMemorySink()
            else:
                # Use in-memory sink for development/testing
                raze_sink = InMemorySink()

            self.raze_service = RazeService(
                sink=raze_sink,
                batch_size=1000,
                linger_ms=100,
            )

        # Initialize GateNotifier for execution pipeline notifications (SSE/webhook/Slack)
        self.gate_notifier: Optional[Any] = None
        if NOTIFICATIONS_AVAILABLE and execution_event_hub is not None:
            try:
                webhook_dispatcher = WebhookDispatcher()
                self.gate_notifier = GateNotifier(
                    event_hub=execution_event_hub,
                    webhook_dispatcher=webhook_dispatcher,
                )
                logger.info("GateNotifier initialized for execution notifications")
            except Exception as exc:
                logger.warning(f"GateNotifier initialization failed: {exc}")

        # Work Item Execution Service (optional - uses PostgreSQL)
        # Uses wire_execution_service to connect AgentExecutionLoop + AgentLLMClient
        self.work_item_execution_service: Optional[Any] = None
        explicit_execution_dsn = os.getenv("AMPREALIZE_EXECUTION_PG_DSN")
        execution_dsn = resolve_optional_postgres_dsn(
            service="EXECUTION",
            explicit_dsn=explicit_execution_dsn,
            env_var="AMPREALIZE_EXECUTION_PG_DSN",
        )
        execution_enabled = _env_flag("AMPREALIZE_EXECUTION_ENABLED")
        if execution_enabled is None:
            execution_enabled = bool(execution_dsn)
        self.execution_enabled = bool(execution_enabled)

        if self.execution_enabled:
            if not execution_dsn:
                execution_dsn = os.getenv("DATABASE_URL")
            if not WORK_ITEM_EXECUTION_AVAILABLE or wire_execution_service is None:
                logger.warning(
                    "Work item execution requested but dependencies unavailable; disabling"
                )
                self.execution_enabled = False
            elif not execution_dsn:
                logger.warning(
                    "Work item execution requested but no DSN configured; disabling"
                )
                self.execution_enabled = False
            else:
                try:
                    self.work_item_execution_service = wire_execution_service(
                        dsn=execution_dsn,
                        board_service=self.board_service,
                        run_service=self.run_service,
                        telemetry=telemetry,
                        gate_notifier=self.gate_notifier,
                    )
                    logger.info("WorkItemExecutionService initialized with AgentExecutionLoop wired")
                except Exception as exc:
                    logger.warning(
                        "Work item execution service initialization failed: %s; disabling", exc
                    )
                    self.execution_enabled = False
        if not self.execution_enabled:
            logger.info("WorkItemExecutionService disabled by capability gating")

        self.execution_service_available = self.work_item_execution_service is not None
        self.api_capabilities = ApiCapabilitiesResponse(
            routes=RouteCapabilitiesResponse(
                projects=self.project_service_available,
                participants=self.participants_available,
                orgs=self.org_routes_available,
                settings=self.settings_routes_available,
                executions=self.execution_service_available,
            ),
            services=ServiceCapabilitiesResponse(
                project_service=self.project_service_available,
                org_service=self.org_service is not None,
                settings_service=self.settings_service is not None,
                execution_enabled=self.execution_enabled,
                execution_service=self.execution_service_available,
            ),
        )


def _normalize_user_code(user_code: str) -> str:
    """Normalise user code input (case-insensitive, remove separators)."""

    alphanumeric = "".join(ch for ch in user_code if ch.isalnum())
    if not alphanumeric:
        raise ValueError("user_code must contain letters or numbers")
    upper = alphanumeric.upper()
    if len(upper) >= 8:
        midpoint = len(upper) // 2
        return f"{upper[:midpoint]}-{upper[midpoint:]}"
    return upper


def _render_device_activation_page(
    *,
    user_code: str = "",
    session: Optional[DeviceAuthorizationSession] = None,
    message: Optional[str] = None,
    error: Optional[str] = None,
) -> HTMLResponse:
    safe_code = html.escape(user_code or "")

    banners: List[str] = []
    if error:
        banners.append(f'<div class="alert alert-error">{html.escape(error)}</div>')
    if message:
        banners.append(f'<div class="alert alert-success">{html.escape(message)}</div>')
    alerts_html = "\n".join(banners)

    details_html = ""
    if session is not None:
        status_class = session.status.value.lower()
        scopes_display = ", ".join(session.scopes) or "-"
        metadata_html = "\n".join(
            f"<li><strong>{html.escape(str(key))}</strong> {html.escape(str(value))}</li>"
            for key, value in sorted(session.metadata.items())
        ) or "<li>No additional metadata</li>"

        tokens_html = ""
        if session.tokens is not None:
            access_expires = session.tokens.access_token_expires_at.isoformat()
            refresh_expires = session.tokens.refresh_token_expires_at.isoformat()
            tokens_html = textwrap.dedent(
                f"""
                <div class=\"token-card\">
                    <h3>Issued Tokens</h3>
                    <dl>
                        <div>
                            <dt>Access token expires</dt>
                            <dd>{html.escape(access_expires)} ({session.tokens.access_expires_in()}s)</dd>
                        </div>
                        <div>
                            <dt>Refresh token expires</dt>
                            <dd>{html.escape(refresh_expires)} ({session.tokens.refresh_expires_in()}s)</dd>
                        </div>
                    </dl>
                </div>
                """
            ).strip()

        actions_html = ""
        if session.status is DeviceAuthorizationStatus.PENDING:
            actions_html = textwrap.dedent(
                f"""
                <div class=\"action-grid\">
                    <form method=\"post\" class=\"card\">
                        <h3>Approve access</h3>
                        <input type=\"hidden\" name=\"action\" value=\"approve\" />
                        <input type=\"hidden\" name=\"user_code\" value=\"{html.escape(session.user_code)}\" />
                        <label for=\"approve-name\">Approver name</label>
                        <input id=\"approve-name\" name=\"approver\" value=\"web-reviewer\" required />
                        <label for=\"approve-roles\">Roles (comma-separated)</label>
                        <input id=\"approve-roles\" name=\"roles\" value=\"STRATEGIST\" />
                        <label class=\"checkbox\">
                            <input type=\"checkbox\" name=\"mfa_verified\" value=\"true\" /> MFA verified
                        </label>
                        <button type=\"submit\" class=\"btn primary\">Approve</button>
                    </form>
                    <form method=\"post\" class=\"card\">
                        <h3>Deny request</h3>
                        <input type=\"hidden\" name=\"action\" value=\"deny\" />
                        <input type=\"hidden\" name=\"user_code\" value=\"{html.escape(session.user_code)}\" />
                        <label for=\"deny-name\">Responder</label>
                        <input id=\"deny-name\" name=\"approver\" value=\"web-reviewer\" required />
                        <label for=\"deny-reason\">Reason</label>
                        <input id=\"deny-reason\" name=\"reason\" placeholder=\"Optional reason\" />
                        <button type=\"submit\" class=\"btn danger\">Deny</button>
                    </form>
                </div>
                """
            ).strip()

        details_html = textwrap.dedent(
            f"""
            <section class=\"card\">
                <h2>Consent request</h2>
                <div class=\"status-row\">
                    <span class=\"status-badge status-{status_class}\">{html.escape(session.status.value.title())}</span>
                    <span class=\"status-meta\">Expires in {session.expires_in()}s</span>
                </div>
                <dl class=\"details\">
                    <div><dt>User code</dt><dd>{html.escape(session.user_code)}</dd></div>
                    <div><dt>Client ID</dt><dd>{html.escape(session.client_id)}</dd></div>
                    <div><dt>Surface</dt><dd>{html.escape(session.surface)}</dd></div>
                    <div><dt>Scopes</dt><dd>{html.escape(scopes_display)}</dd></div>
                    <div><dt>Created</dt><dd>{html.escape(session.created_at.isoformat())}</dd></div>
                    <div><dt>Expires</dt><dd>{html.escape(session.expires_at.isoformat())}</dd></div>
                </dl>
                <div class=\"metadata\">
                    <h3>Metadata</h3>
                    <ul>{metadata_html}</ul>
                </div>
                {tokens_html}
            </section>
            {actions_html}
            """
        ).strip()

    page = textwrap.dedent(
        f"""
        <!DOCTYPE html>
        <html lang=\"en\">
        <head>
            <meta charset=\"utf-8\" />
            <title>Amprealize Device Activation</title>
            <style>
                :root {{
                    font-family: 'Inter', system-ui, sans-serif;
                    color: #0f172a;
                    background: #f8fafc;
                }}
                body {{
                    margin: 0;
                    padding: 0 16px 32px;
                    display: flex;
                    justify-content: center;
                }}
                main {{
                    max-width: 720px;
                    width: 100%;
                }}
                h1 {{
                    font-size: 1.75rem;
                    margin-top: 32px;
                    margin-bottom: 8px;
                }}
                p.subtitle {{
                    margin-top: 0;
                    color: #475569;
                }}
                .card {{
                    background: #ffffff;
                    border-radius: 16px;
                    padding: 24px;
                    margin-top: 24px;
                }}
                label {{
                    display: block;
                    font-weight: 600;
                    margin-bottom: 6px;
                }}
                input[type=\"text\"], input:not([type]) {{
                    width: 100%;
                    padding: 12px;
                    border-radius: 10px;
                    border: 1px solid #cbd5f5;
                    margin-bottom: 16px;
                    font-size: 1rem;
                }}
                button {{
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    padding: 12px 20px;
                    border-radius: 999px;
                    border: none;
                    font-weight: 600;
                    cursor: pointer;
                    transition: transform 0.15s ease;
                }}
                button:hover {{
                    transform: translateY(-1px);
                }}
                .btn.primary {{
                    background: #2563eb;
                    color: #fff;
                }}
                .btn.danger {{
                    background: #dc2626;
                    color: #fff;
                }}
                .alert {{
                    margin-top: 20px;
                    padding: 14px 18px;
                    border-radius: 12px;
                    font-weight: 600;
                }}
                .alert-error {{
                    background: rgba(239, 68, 68, 0.12);
                    color: #b91c1c;
                }}
                .alert-success {{
                    background: rgba(16, 185, 129, 0.12);
                    color: #047857;
                }}
                .status-row {{
                    display: flex;
                    align-items: center;
                    gap: 12px;
                    margin-bottom: 16px;
                }}
                .status-badge {{
                    padding: 6px 14px;
                    border-radius: 999px;
                    font-size: 0.875rem;
                    font-weight: 600;
                }}
                .status-pending {{ background: #fef3c7; color: #92400e; }}
                .status-approved {{ background: #dcfce7; color: #166534; }}
                .status-denied {{ background: #fee2e2; color: #991b1b; }}
                .status-expired {{ background: #e2e8f0; color: #475569; }}
                dl.details {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                    gap: 12px;
                }}
                dl.details div {{
                    background: #f8fafc;
                    border-radius: 12px;
                    padding: 12px;
                }}
                dl.details dt {{
                    font-size: 0.75rem;
                    text-transform: uppercase;
                    color: #64748b;
                    margin-bottom: 4px;
                }}
                dl.details dd {{
                    margin: 0;
                    font-weight: 600;
                }}
                .metadata ul {{
                    margin: 0;
                    padding-left: 18px;
                }}
                .token-card {{
                    margin-top: 18px;
                    background: #f0f9ff;
                    border-radius: 12px;
                    padding: 16px;
                }}
                .token-card h3 {{
                    margin-top: 0;
                }}
                .action-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
                    gap: 16px;
                    margin-top: 16px;
                }}
                .checkbox {{
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    font-weight: 500;
                    margin-bottom: 16px;
                }}
                footer {{
                    margin-top: 32px;
                    text-align: center;
                    color: #94a3b8;
                }}
            </style>
        </head>
        <body>
            <main>
                <h1>Amprealize Device Activation</h1>
                <p class=\"subtitle\">Enter the code shown on your CLI or IDE to approve access.</p>
                {alerts_html}
                <section class=\"card\">
                    <h2>Lookup consent request</h2>
                    <form method=\"post\">
                        <input type=\"hidden\" name=\"action\" value=\"lookup\" />
                        <label for=\"lookup-user-code\">User code</label>
                        <input id=\"lookup-user-code\" name=\"user_code\" value=\"{safe_code}\" placeholder=\"ABCD-EFGH\" required />
                        <button type=\"submit\" class=\"btn primary\">Lookup code</button>
                    </form>
                </section>
                {details_html}
                <footer>Device flow prototype · Amprealize</footer>
            </main>
        </body>
        </html>
        """
    ).strip()

    return HTMLResponse(content=page)


def create_app(
    *,
    behavior_db_path: Optional[Path] = None,
    workflow_db_path: Optional[Path] = None,
    enable_auth_middleware: Optional[bool] = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        behavior_db_path: Deprecated. Path for SQLite behavior DB.
        workflow_db_path: Deprecated. Path for SQLite workflow DB.
        enable_auth_middleware: Enable JWT auth middleware. Defaults to env var AMPREALIZE_AUTH_ENABLED.
    """

    # Ensure a single in-process JWT secret is available for any JWT validation/issuance.
    # For multi-worker deployments, set AMPREALIZE_JWT_SECRET explicitly in the environment.
    #
    # Optional dev convenience: set AMPREALIZE_JWT_SECRET_FILE to persist a generated secret
    # across server restarts (avoids device-flow sessions being invalidated on reload).
    if not os.getenv("AMPREALIZE_JWT_SECRET"):
        secret_file = os.getenv("AMPREALIZE_JWT_SECRET_FILE")
        if secret_file:
            try:
                secret_path = Path(secret_file).expanduser()
                if secret_path.exists():
                    existing = secret_path.read_text(encoding="utf-8").strip()
                    if existing:
                        os.environ["AMPREALIZE_JWT_SECRET"] = existing
                else:
                    secret_path.parent.mkdir(parents=True, exist_ok=True)
                    generated = secrets.token_urlsafe(32)
                    secret_path.write_text(generated, encoding="utf-8")
                    os.environ["AMPREALIZE_JWT_SECRET"] = generated
            except Exception:
                # Fall back to in-memory secret if the file is not usable.
                os.environ["AMPREALIZE_JWT_SECRET"] = secrets.token_urlsafe(32)
        else:
            os.environ["AMPREALIZE_JWT_SECRET"] = secrets.token_urlsafe(32)

    app = FastAPI(title="Amprealize API", version="0.1.0")

    @app.middleware("http")
    async def _legacy_v1_prefix_compat(request: Request, call_next):
        """Rewrite legacy /v1 routes to /api/v1 for backward compatibility."""
        original_path = request.scope.get("path", "")
        if original_path == "/v1" or original_path.startswith("/v1/"):
            remapped_path = f"/api{original_path}"
            request.scope["path"] = remapped_path
            request.scope["raw_path"] = remapped_path.encode("utf-8")
        return await call_next(request)

    # ------------------------------------------------------------------
    # Module-gated API routes
    # ------------------------------------------------------------------
    # Resolve disabled API router tags once at app startup so the
    # per-request middleware only does a fast set-lookup.
    _disabled_api_routers: set[str] = set()
    _edition_gated_api_routers: dict[str, str] = {}
    try:
        from amprealize.config.loader import get_config as _get_cfg
        from amprealize.module_registry import (
            get_enabled_api_routers as _get_enabled_routers,
            get_all_module_api_routers as _get_all_routers,
            get_edition_gated_api_routers as _get_edition_gated,
        )

        _mod_cfg_api = _get_cfg().modules
        _all_routers = _get_all_routers()
        _enabled_routers = _get_enabled_routers(_mod_cfg_api)
        _disabled_api_routers = _all_routers - _enabled_routers
        _edition_gated_api_routers = _get_edition_gated()
    except Exception:
        pass  # No config yet (first run / init) -- allow everything

    if _disabled_api_routers:

        @app.middleware("http")
        async def _module_gate_api_routes(request: Request, call_next):
            """Return 404 for API routes belonging to disabled modules.

            Routes that require a higher edition tier get 403 with an
            upgrade message instead of the generic not-enabled 404.
            """
            path = request.scope.get("path", "")
            if path.startswith("/api/v1/"):
                # Extract the resource segment: /api/v1/<resource>/...
                segment = path[len("/api/v1/"):].split("/")[0].split(":")[0]
                if segment in _disabled_api_routers:
                    # Edition-gated routes get a 403 with upgrade guidance
                    required_edition = _edition_gated_api_routers.get(segment)
                    if required_edition:
                        return JSONResponse(
                            status_code=403,
                            content={
                                "detail": (
                                    f"The '{segment}' feature requires "
                                    f"{required_edition.replace('_', ' ').title()} edition."
                                ),
                                "edition_required": required_edition,
                            },
                        )
                    return JSONResponse(
                        status_code=404,
                        content={
                            "detail": (
                                f"The '{segment}' module is not enabled. "
                                "Reconfigure modules via 'amprealize init' or config."
                            ),
                        },
                    )
            return await call_next(request)

    # ------------------------------------------------------------------
    # CORS Configuration
    # ------------------------------------------------------------------
    def _parse_cors_origins(raw: str | None) -> list[str]:
        if not raw:
            return []
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    # Allow requests from local development servers (safe dev default).
    #
    # If AMPREALIZE_CORS_ORIGINS is set, it is used as the explicit allowlist.
    # Additionally, we allow an opt-in localhost regex (enabled by default) to
    # prevent common dev breakages when the Vite port changes.
    cors_origins = _parse_cors_origins(os.getenv("AMPREALIZE_CORS_ORIGINS"))
    cors_origin_regex = os.getenv("AMPREALIZE_CORS_ORIGIN_REGEX")
    allow_localhost_regex = os.getenv("AMPREALIZE_CORS_ALLOW_LOCALHOST", "true").lower() in ("true", "1", "yes")
    if allow_localhost_regex and not cors_origin_regex:
        cors_origin_regex = r"^http://(localhost|127\.0\.0\.1)(:\d+)?$"

    # Default allowed origins for CORS header injection on error responses
    default_cors_origins = ["http://localhost:5173", "http://localhost:5174", "http://localhost:3000"]

    # ------------------------------------------------------------------
    # Edition & Caps Exception Handlers
    # ------------------------------------------------------------------
    # These must be registered before the catch-all Exception handler
    # so they take priority.  Endpoints that call @requires_edition,
    # @requires_capability, or caps_enforcer.enforce() automatically
    # surface proper HTTP status codes.

    from amprealize.edition import EditionGateError
    from amprealize.caps_enforcer import CapsExceededError

    @app.exception_handler(EditionGateError)
    async def _edition_gate_handler(request: Request, exc: EditionGateError):
        return JSONResponse(
            status_code=403,
            content={
                "detail": str(exc),
                "edition_required": exc.required.value,
                "edition_current": exc.current.value,
                "feature": exc.feature,
            },
        )

    @app.exception_handler(CapsExceededError)
    async def _caps_exceeded_handler(request: Request, exc: CapsExceededError):
        return JSONResponse(
            status_code=429,
            content={
                "detail": str(exc),
                "resource": exc.resource,
                "limit": exc.limit,
                "current": exc.current,
            },
        )

    # ------------------------------------------------------------------
    # Exception Handler with CORS headers
    # ------------------------------------------------------------------
    # FastAPI/Starlette's default exception handler returns responses that bypass
    # the CORSMiddleware. We add a custom handler to ensure CORS headers are present
    # on error responses (especially 500s) so the browser can read the error.
    @app.exception_handler(Exception)
    async def cors_exception_handler(request: Request, exc: Exception):
        """Catch-all exception handler that ensures CORS headers on errors."""
        from starlette.responses import JSONResponse
        import traceback
        import re

        origin = request.headers.get("origin", "")

        # Determine if origin is allowed
        allowed = False
        if origin:
            if origin in default_cors_origins or origin in cors_origins:
                allowed = True
            elif cors_origin_regex:
                allowed = bool(re.match(cors_origin_regex, origin))

        # Build CORS headers if origin is allowed
        cors_headers = {}
        if allowed:
            cors_headers = {
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Credentials": "true",
            }

        # Log the exception for debugging
        import logging
        logging.getLogger(__name__).exception(
            f"Unhandled exception in {request.method} {request.url.path}",
            exc_info=exc,
        )

        # Return JSON error response with CORS headers
        return JSONResponse(
            status_code=500,
            content={
                "detail": str(exc),
                "type": type(exc).__name__,
            },
            headers=cors_headers,
        )

    execution_event_hub = ExecutionEventHub()
    app.state.execution_event_hub = execution_event_hub

    container = _ServiceContainer(
        behavior_db_path=behavior_db_path,
        workflow_db_path=workflow_db_path,
        execution_event_hub=execution_event_hub,
    )
    app.state.container = container
    app.state.api_capabilities = container.api_capabilities

    # ------------------------------------------------------------------
    # Auth Middleware & Permission Service
    # ------------------------------------------------------------------
    # Check if auth should be enabled (env var or explicit parameter)
    auth_enabled = enable_auth_middleware
    if auth_enabled is None:
        auth_enabled = os.getenv("AMPREALIZE_AUTH_ENABLED", "").lower() in ("true", "1", "yes")

    # Always add auth middleware when device_flow_manager is available (for ga_* token validation)
    # This ensures OAuth users get their user_id populated in request.state
    from amprealize.auth.middleware import AuthMiddleware, AuthConfig

    auth_config = AuthConfig(
        skip_paths={
            "/health", "/health/", "/metrics", "/docs", "/openapi.json", "/redoc",
            "/api/v1/capabilities",
            "/api/v1/platform/runtime",
            "/api/v1/device/authorize",  # Device flow doesn't need auth
            "/api/v1/device/token",  # Token endpoint
            "/api/v1/activate",  # Activation page
            "/api/v1/auth/oauth",  # OAuth flow endpoints
        },
        auth_required=auth_enabled,
    )

    # Mount TenantMiddleware for PostgreSQL RLS (added before AuthMiddleware
    # in code so Auth wraps Tenant in ASGI stack: Auth → Tenant → app).
    # Auth-derived tenant takes priority; header-based sources disabled.
    if auth_enabled:
        _tenant_dsn = resolve_optional_postgres_dsn(
            service="TENANT",
            explicit_dsn=os.getenv("AMPREALIZE_ORG_PG_DSN") or os.getenv("AMPREALIZE_AUTH_PG_DSN"),
            env_var="AMPREALIZE_ORG_PG_DSN",
        )
        if _tenant_dsn:
            from amprealize.tenant.context import TenantMiddleware
            from amprealize.storage.postgres_pool import PostgresPool
            _tenant_pool = PostgresPool(dsn=_tenant_dsn)
            app.add_middleware(
                TenantMiddleware,
                pool=_tenant_pool,
                enable_header=False,  # Headers stripped by nginx; auth-derived only
                enable_subdomain=False,
                enable_path=False,
                enable_auth_context=True,
                skip_paths=auth_config.skip_paths,
                apply_limits=True,
            )

    app.add_middleware(
        AuthMiddleware,
        config=auth_config,
        device_flow_manager=container.postgres_device_store or container.device_flow_manager,
    )

    @app.get("/api/v1/capabilities", response_model=ApiCapabilitiesResponse, tags=["platform"])
    def get_api_capabilities() -> ApiCapabilitiesResponse:
        return app.state.api_capabilities

    @app.get(
        "/api/v1/platform/runtime",
        response_model=PlatformRuntimeMetadataResponse,
        tags=["platform"],
    )
    def get_platform_runtime_metadata() -> PlatformRuntimeMetadataResponse:
        from amprealize.platform_runtime import build_platform_runtime_dict

        return PlatformRuntimeMetadataResponse(**build_platform_runtime_dict())

    @app.get("/api/v1/modules", tags=["platform"])
    def get_enabled_modules() -> Dict[str, Any]:
        """Return the set of enabled modules so the web console can show/hide sections."""
        try:
            from amprealize.config.loader import get_config as _gcfg
            from amprealize.module_registry import (
                get_enabled_modules as _gem,
                get_enabled_capability_flags as _gcf,
                MODULE_REGISTRY,
            )

            _mcfg = _gcfg().modules
            enabled = _gem(_mcfg)
            flags = _gcf(_mcfg)
            return {
                "enabled_modules": sorted(enabled),
                "capability_flags": sorted(flags),
                "all_modules": sorted(MODULE_REGISTRY.keys()),
            }
        except Exception:
            # No config yet -- report all modules as available
            from amprealize.module_registry import MODULE_REGISTRY

            all_names = sorted(MODULE_REGISTRY.keys())
            return {
                "enabled_modules": all_names,
                "capability_flags": [],
                "all_modules": all_names,
            }

    if auth_enabled:
        from amprealize.tenant.permissions import AsyncPermissionService

        # Initialize async permission service if DSN is available
        auth_dsn = resolve_optional_postgres_dsn(
            service="AUTH",
            explicit_dsn=None,
            env_var="AMPREALIZE_AUTH_PG_DSN",
        )
        if auth_dsn:
            try:
                app.state.async_permission_service = AsyncPermissionService(dsn=auth_dsn)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(
                    f"Failed to initialize AsyncPermissionService: {exc}. "
                    "Permission checks will not be available."
                )
                app.state.async_permission_service = None
        else:
            app.state.async_permission_service = None

    def _validated_uuid(value: str, resource_name: str) -> str:
        try:
            uuid.UUID(value)
            return value
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{resource_name} not found",
            ) from exc

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    @app.post("/api/v1/actions", status_code=status.HTTP_201_CREATED)
    def create_action(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.action_adapter.create_action(payload)
        except ActionServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/v1/actions")
    def list_actions() -> List[Dict[str, Any]]:
        return container.action_adapter.list_actions()

    @app.get("/api/v1/actions/{action_id}")
    def get_action(action_id: str) -> Dict[str, Any]:
        try:
            return container.action_adapter.get_action(action_id)
        except ActionNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @app.post("/api/v1/actions:replay", status_code=status.HTTP_202_ACCEPTED)
    def replay_actions(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.action_adapter.replay_actions(payload)
        except ActionNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ActionServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/v1/actions/replays/{replay_id}")
    def get_replay_status(replay_id: str) -> Dict[str, Any]:
        try:
            return container.action_adapter.get_replay_status(replay_id)
        except (ActionNotFoundError, ReplayNotFoundError) as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # Behaviors
    # ------------------------------------------------------------------
    @app.get("/api/v1/behaviors")
    def list_behaviors(
        status_filter: Optional[str] = Query(default=None, alias="status"),
        tags: Optional[List[str]] = Query(default=None),
        role_focus: Optional[str] = Query(default=None),
    ) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {}
        if status_filter:
            payload["status"] = status_filter
        if tags:
            payload["tags"] = list(tags)
        if role_focus:
            payload["role_focus"] = role_focus
        return container.behavior_adapter.list_behaviors(payload)

    @app.post("/api/v1/behaviors", status_code=status.HTTP_201_CREATED)
    def create_behavior(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.behavior_adapter.create_draft(payload)
        except (BehaviorServiceError, KeyError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/behaviors:search")
    def search_behaviors(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        try:
            return container.behavior_adapter.search_behaviors(payload)
        except BehaviorServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/v1/behaviors/{behavior_id}")
    def get_behavior(behavior_id: str, version: Optional[str] = None) -> Dict[str, Any]:
        try:
            return container.behavior_adapter.get_behavior(behavior_id, version)
        except BehaviorNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @app.patch("/api/v1/behaviors/{behavior_id}/versions/{version}")
    def update_behavior(behavior_id: str, version: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.behavior_adapter.update_draft(behavior_id, version, payload)
        except BehaviorNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except BehaviorServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/behaviors/{behavior_id}/versions/{version}:submit")
    def submit_behavior(behavior_id: str, version: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.behavior_adapter.submit_for_review(behavior_id, version, payload)
        except BehaviorNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except BehaviorServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/behaviors/{behavior_id}:approve")
    def approve_behavior(behavior_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.behavior_adapter.approve(behavior_id, payload)
        except BehaviorNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except BehaviorServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/behaviors/{behavior_id}:deprecate")
    def deprecate_behavior(behavior_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.behavior_adapter.deprecate(behavior_id, payload)
        except BehaviorNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except BehaviorServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.delete("/api/v1/behaviors/{behavior_id}/versions/{version}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_behavior_draft(behavior_id: str, version: str, payload: Dict[str, Any]) -> Response:
        try:
            container.behavior_adapter.delete_draft(behavior_id, version, payload)
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        except BehaviorNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except BehaviorServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # Behavior Effectiveness & Admin
    # ------------------------------------------------------------------
    @app.get("/api/v1/admin/behaviors/effectiveness")
    def get_behavior_effectiveness(
        status_filter: Optional[str] = Query(default=None, alias="status"),
        sort_by: Optional[str] = Query(default="usage_count", description="Sort by: usage_count, avg_accuracy, token_reduction"),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> Dict[str, Any]:
        """Get behavior effectiveness metrics for admin dashboard."""
        try:
            return container.behavior_adapter.get_effectiveness_metrics(
                status_filter=status_filter,
                sort_by=sort_by,
                limit=limit,
            )
        except BehaviorServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/admin/behaviors/{behavior_id}/feedback", status_code=status.HTTP_201_CREATED)
    def submit_behavior_feedback(behavior_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Submit curator feedback for a behavior."""
        try:
            required = ["relevance_score", "actor_id"]
            missing = [f for f in required if f not in payload]
            if missing:
                raise ValueError(f"Missing required fields: {missing}")

            return container.behavior_adapter.record_feedback(
                behavior_id=behavior_id,
                relevance_score=payload["relevance_score"],
                helpfulness_score=payload.get("helpfulness_score"),
                token_reduction_observed=payload.get("token_reduction_observed"),
                comment=payload.get("comment"),
                actor_id=payload["actor_id"],
                context=payload.get("context", {}),
            )
        except BehaviorNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except (BehaviorServiceError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/v1/admin/behaviors/{behavior_id}/feedback")
    def get_behavior_feedback(
        behavior_id: str,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> List[Dict[str, Any]]:
        """Get feedback entries for a specific behavior."""
        try:
            return container.behavior_adapter.get_feedback(behavior_id=behavior_id, limit=limit)
        except BehaviorNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @app.get("/api/v1/admin/behaviors/benchmark")
    def get_behavior_benchmark_results(
        limit: int = Query(default=20, ge=1, le=100),
    ) -> Dict[str, Any]:
        """Get latest benchmark results for behavior retrieval performance."""
        try:
            return container.behavior_adapter.get_benchmark_results(limit=limit)
        except BehaviorServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/admin/behaviors/benchmark:run", status_code=status.HTTP_202_ACCEPTED)
    def trigger_behavior_benchmark(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Trigger a new benchmark run (async)."""
        try:
            return container.behavior_adapter.trigger_benchmark(
                corpus_path=payload.get("corpus_path"),
                sample_size=payload.get("sample_size", 100),
                actor_id=payload.get("actor_id", "system"),
            )
        except BehaviorServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # Agent Registry
    # ------------------------------------------------------------------
    @app.get("/api/v1/agents")
    def list_agents(
        status_filter: Optional[str] = Query(default=None, alias="status"),
        visibility: Optional[str] = Query(default=None),
        role_alignment: Optional[str] = Query(default=None),
        builtin: Optional[bool] = Query(default=None),
        owner_id: Optional[str] = Query(default=None),
        tags: Optional[List[str]] = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> Dict[str, Any]:
        """List agents with optional filters."""
        if container.agent_registry_adapter is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent registry service not available",
            )
        payload: Dict[str, Any] = {"limit": limit, "offset": offset}
        if status_filter:
            payload["status"] = status_filter
        if visibility:
            payload["visibility"] = visibility
        if role_alignment:
            payload["role_alignment"] = role_alignment
        if builtin is not None:
            payload["builtin"] = builtin
        if owner_id:
            payload["owner_id"] = owner_id
        if tags:
            payload["tags"] = list(tags)
        try:
            agents = container.agent_registry_adapter.list_agents(payload)
            return {"agents": agents, "total": len(agents), "limit": limit, "offset": offset}
        except AgentRegistryError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/agents", status_code=status.HTTP_201_CREATED)
    def create_agent(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new agent."""
        if container.agent_registry_adapter is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent registry service not available",
            )
        try:
            return container.agent_registry_adapter.create_agent(payload)
        except AgentRegistryError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/agents:search")
    def search_agents(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Search agents using full-text search and filters."""
        if container.agent_registry_adapter is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent registry service not available",
            )
        try:
            return container.agent_registry_adapter.search_agents(payload)
        except AgentRegistryError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/v1/agents/{agent_id}")
    def get_agent(
        agent_id: str,
        version: Optional[int] = Query(default=None),
        include_history: bool = Query(default=False),
    ) -> Dict[str, Any]:
        """Get a specific agent by ID."""
        if container.agent_registry_adapter is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent registry service not available",
            )
        try:
            return container.agent_registry_adapter.get_agent(
                agent_id, version=version, include_history=include_history
            )
        except AgentNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except AgentRegistryError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.patch("/api/v1/agents/{agent_id}")
    def update_agent(agent_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing agent (creates new version if published)."""
        if container.agent_registry_adapter is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent registry service not available",
            )
        try:
            return container.agent_registry_adapter.update_agent(agent_id, payload)
        except AgentNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except AgentRegistryError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.delete("/api/v1/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_agent(agent_id: str) -> None:
        """Delete an agent (only drafts can be deleted)."""
        if container.agent_registry_adapter is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent registry service not available",
            )
        try:
            container.agent_registry_adapter.delete_agent(agent_id)
        except AgentNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except AgentRegistryError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/agents/{agent_id}/versions", status_code=status.HTTP_201_CREATED)
    def create_agent_version(agent_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new version of an agent."""
        if container.agent_registry_adapter is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent registry service not available",
            )
        try:
            return container.agent_registry_adapter.create_new_version(agent_id, payload)
        except AgentNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except AgentRegistryError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/agents/{agent_id}:publish")
    def publish_agent(agent_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Publish an agent (change status from DRAFT to PUBLISHED)."""
        if container.agent_registry_adapter is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent registry service not available",
            )
        try:
            return container.agent_registry_adapter.publish_agent(agent_id, payload)
        except AgentNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except AgentRegistryError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/agents/{agent_id}:deprecate")
    def deprecate_agent(agent_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Deprecate an agent (change status to DEPRECATED)."""
        if container.agent_registry_adapter is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent registry service not available",
            )
        try:
            return container.agent_registry_adapter.deprecate_agent(agent_id, payload)
        except AgentNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except AgentRegistryError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/admin/agents:bootstrap", status_code=status.HTTP_202_ACCEPTED)
    def bootstrap_agents(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Bootstrap builtin agents from playbook files (admin only)."""
        if container.agent_registry_adapter is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent registry service not available",
            )
        try:
            return container.agent_registry_adapter.bootstrap_from_playbooks(payload)
        except AgentRegistryError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # Agent Interaction (Delegate, Consult, Handoff)
    # ------------------------------------------------------------------

    @app.post("/api/v1/agents/{agent_id}:delegate", status_code=status.HTTP_201_CREATED)
    def delegate_to_agent(agent_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Delegate a subtask to another agent.

        Creates a child run that executes under the target agent's persona.
        When wait_for_completion=true (default), blocks until subtask completes.

        Args:
            agent_id: Target agent to delegate the subtask to
            payload: {
                "run_id": Optional parent run ID,
                "subtask": Required task description,
                "context": Optional additional context dict,
                "timeout_seconds": Optional timeout (default 300),
                "wait_for_completion": Whether to wait for result (default true)
            }

        Returns:
            DelegationResponse with delegation_id, delegated_run_id, status, result
        """
        service = container.services.agent_orchestrator_service()
        adapter = RestAgentOrchestratorAdapter(service=service)
        try:
            return adapter.delegate(agent_id, payload)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing required field: {exc}",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

    @app.post("/api/v1/agents/{agent_id}:consult")
    def consult_agent(agent_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Get advisory input from another agent without delegation.

        Lightweight query for expert opinion without creating a separate run.
        Respects MAX_CONSULTATION_DEPTH (3) to prevent infinite loops.

        Args:
            agent_id: Target agent to consult
            payload: {
                "run_id": Optional requesting run ID,
                "question": Required question to ask,
                "context": Optional additional context dict,
                "max_tokens": Optional response length limit (default 2000)
            }

        Returns:
            ConsultationResponse with consultation_id, response, confidence, depth
        """
        service = container.services.agent_orchestrator_service()
        adapter = RestAgentOrchestratorAdapter(service=service)
        try:
            return adapter.consult(agent_id, payload)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing required field: {exc}",
            ) from exc
        except ValueError as exc:
            if "depth" in str(exc).lower():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(exc),
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

    @app.post("/api/v1/agents/{agent_id}:handoff")
    def handoff_to_agent(agent_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Transfer execution to another agent.

        Terminates current run and creates a new run under target agent.
        Optionally transfers context and outputs from the source run.

        Args:
            agent_id: Target agent to hand off to
            payload: {
                "run_id": Optional source run ID,
                "reason": Required explanation for the handoff,
                "transfer_context": Whether to pass context (default true),
                "transfer_outputs": Whether to pass outputs (default true)
            }

        Returns:
            HandoffResponse with handoff_id, new_run_id, previous_run_id, status
        """
        service = container.services.agent_orchestrator_service()
        adapter = RestAgentOrchestratorAdapter(service=service)
        try:
            return adapter.handoff(agent_id, payload)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing required field: {exc}",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

    # ------------------------------------------------------------------
    # Escalations (Section 11.4 - Human Escalation)
    # ------------------------------------------------------------------

    @app.post("/api/v1/escalations:help", status_code=status.HTTP_201_CREATED)
    def request_help(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Request non-blocking human guidance.

        Creates an escalation that allows execution to continue
        while awaiting human input.

        Args:
            payload: {
                "reason": Required - why help is needed,
                "context": Optional additional context,
                "run_id": Optional run ID for tracking,
                "work_item_id": Optional associated work item,
                "urgency": "low" | "normal" | "high" | "urgent" (default: normal)
            }

        Returns:
            HelpResponse with escalation_id, status, notification_sent
        """
        from .adapters import RestEscalationAdapter

        service = container.services.agent_orchestrator_service()
        adapter = RestEscalationAdapter(service=service)
        try:
            return adapter.request_help(payload)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing required field: {exc}",
            ) from exc

    @app.post("/api/v1/escalations:approval", status_code=status.HTTP_201_CREATED)
    def request_approval(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Request blocking human approval.

        Creates an escalation that pauses execution until a human
        approves or rejects the decision.

        Args:
            payload: {
                "decision": Required - what decision needs approval,
                "options": Required - list of choices (min 2),
                "context": Optional additional context,
                "run_id": Optional run ID for tracking,
                "work_item_id": Optional associated work item,
                "timeout_seconds": How long to wait (default: 3600 = 1 hour)
            }

        Returns:
            ApprovalResponse with escalation_id, status, expires_at
        """
        from .adapters import RestEscalationAdapter

        service = container.services.agent_orchestrator_service()
        adapter = RestEscalationAdapter(service=service)
        try:
            return adapter.request_approval(payload)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing required field: {exc}",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    @app.post("/api/v1/escalations:blocked", status_code=status.HTTP_201_CREATED)
    def notify_blocked(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Notify that execution is blocked.

        Creates an escalation to inform humans that the agent
        cannot proceed without external intervention.

        Args:
            payload: {
                "reason": Required - why execution is blocked,
                "blocker_details": Optional details about the blocker,
                "suggested_actions": Optional list of actions to resolve,
                "run_id": Optional run ID for tracking,
                "work_item_id": Optional associated work item
            }

        Returns:
            BlockedResponse with escalation_id, status, notification_sent
        """
        from .adapters import RestEscalationAdapter

        service = container.services.agent_orchestrator_service()
        adapter = RestEscalationAdapter(service=service)
        try:
            return adapter.notify_blocked(payload)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing required field: {exc}",
            ) from exc

    @app.get("/api/v1/escalations/{escalation_id}")
    def get_escalation(escalation_id: str) -> Dict[str, Any]:
        """Get escalation details by ID.

        Args:
            escalation_id: The escalation ID

        Returns:
            Escalation response (Help, Approval, or Blocked depending on type)
        """
        from .adapters import RestEscalationAdapter

        service = container.services.agent_orchestrator_service()
        adapter = RestEscalationAdapter(service=service)
        result = adapter.get_escalation(escalation_id)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Escalation not found: {escalation_id}",
            )
        return result

    @app.post("/api/v1/escalations/{escalation_id}:resolve")
    def resolve_help_escalation(escalation_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve a help escalation with guidance.

        Args:
            escalation_id: The help escalation ID
            payload: {
                "guidance": Required - the human's guidance,
                "resolved_by": Optional user identifier
            }

        Returns:
            Updated HelpResponse with status=resolved
        """
        from .adapters import RestEscalationAdapter

        service = container.services.agent_orchestrator_service()
        adapter = RestEscalationAdapter(service=service)
        try:
            return adapter.resolve_help(escalation_id, payload)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing required field: {exc}",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

    @app.post("/api/v1/escalations/{escalation_id}:approve")
    def approve_escalation(escalation_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Approve an approval escalation.

        Args:
            escalation_id: The approval escalation ID
            payload: {
                "selected_option": Optional which option was chosen,
                "reason": Optional explanation,
                "resolved_by": Optional user identifier
            }

        Returns:
            Updated ApprovalResponse with status=approved, approved=true
        """
        from .adapters import RestEscalationAdapter

        service = container.services.agent_orchestrator_service()
        adapter = RestEscalationAdapter(service=service)
        try:
            return adapter.resolve_approval(escalation_id, approved=True, payload=payload)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

    @app.post("/api/v1/escalations/{escalation_id}:reject")
    def reject_escalation(escalation_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Reject an approval escalation.

        Args:
            escalation_id: The approval escalation ID
            payload: {
                "selected_option": Optional which option was chosen,
                "reason": Optional explanation,
                "resolved_by": Optional user identifier
            }

        Returns:
            Updated ApprovalResponse with status=rejected, approved=false
        """
        from .adapters import RestEscalationAdapter

        service = container.services.agent_orchestrator_service()
        adapter = RestEscalationAdapter(service=service)
        try:
            return adapter.resolve_approval(escalation_id, approved=False, payload=payload)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

    @app.post("/api/v1/escalations/{escalation_id}:acknowledge")
    def acknowledge_blocked_escalation(escalation_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Acknowledge a blocked escalation.

        Args:
            escalation_id: The blocked escalation ID
            payload: {
                "acknowledged_by": Optional user identifier,
                "resolution": Optional how the blocker was/will be resolved
            }

        Returns:
            Updated BlockedResponse with status=acknowledged or resolved
        """
        from .adapters import RestEscalationAdapter

        service = container.services.agent_orchestrator_service()
        adapter = RestEscalationAdapter(service=service)
        try:
            return adapter.acknowledge_blocked(escalation_id, payload)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

    # ------------------------------------------------------------------
    # Config / Models (Section 11.6)
    # ------------------------------------------------------------------

    @app.get("/api/v1/projects/{project_id}/models")
    def get_project_model_availability(
        project_id: str,
        org_id: Optional[str] = Query(None, description="Organization ID (if project belongs to an org)"),
        include_pricing: bool = Query(True, description="Include pricing information"),
        provider_filter: Optional[str] = Query(None, description="Filter by provider (anthropic, openai, openrouter, local)"),
    ) -> Dict[str, Any]:
        """Get available LLM models for a project.

        Returns models based on credential resolution order:
        1. Project credential (BYOK) - highest priority
        2. Org credential (BYOK) - if project belongs to an org
        3. Platform credential - admin-managed defaults

        Works for both user-owned projects and org projects.
        """
        from .work_item_execution_service import CredentialStore
        from .mcp.handlers.config_handlers import handle_get_model_availability

        credential_store = CredentialStore()

        try:
            return handle_get_model_availability(
                credential_store,
                {
                    "project_id": project_id,
                    "org_id": org_id,
                    "include_pricing": include_pricing,
                    "provider_filter": provider_filter,
                },
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing required field: {exc}",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    @app.get("/api/v1/config/models")
    def list_all_available_models(
        include_pricing: bool = Query(True, description="Include pricing information"),
        provider_filter: Optional[str] = Query(None, description="Filter by provider"),
    ) -> Dict[str, Any]:
        """List all models available at the platform level.

        Returns models that have platform-level credentials configured.
        Use /api/v1/projects/{project_id}/models for project-specific availability.
        """
        from .work_item_execution_service import CredentialStore
        from .mcp.handlers.config_handlers import handle_get_model_availability

        credential_store = CredentialStore()

        try:
            return handle_get_model_availability(
                credential_store,
                {
                    "project_id": "_platform",  # Special ID for platform-level query
                    "include_pricing": include_pricing,
                    "provider_filter": provider_filter,
                },
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    # ------------------------------------------------------------------
    # BYOK Credentials (Section 11.6 - Credential Management)
    # ------------------------------------------------------------------

    @app.post("/api/v1/projects/{project_id}/credentials", status_code=status.HTTP_201_CREATED)
    def create_project_credential(
        project_id: str,
        payload: Dict[str, Any],
        actor_id: str = Query(..., description="ID of the user creating the credential"),
    ) -> Dict[str, Any]:
        """Add or replace a BYOK credential for a project.

        Args:
            project_id: Project ID
            payload: {
                "provider": "anthropic" | "openai" | "openrouter",
                "api_key": "sk-xxx...",
                "name": Optional display name
            }
            actor_id: User creating the credential

        Returns:
            Created credential info (without the key itself)
        """
        from .auth.llm_credential_repository import (
            LLMCredentialRepository,
            CreateCredentialRequest,
            CredentialScopeType,
        )
        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()
        repo = LLMCredentialRepository(pool)

        try:
            provider = payload.get("provider")
            api_key = payload.get("api_key")
            name = payload.get("name")

            if not provider:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="provider is required",
                )
            if not api_key:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="api_key is required",
                )

            # Default name if not provided
            if not name:
                name = f"{provider} API Key"

            request = CreateCredentialRequest(
                scope_type=CredentialScopeType.PROJECT,
                scope_id=project_id,
                provider=provider,
                api_key=api_key,
                name=name,
                created_by=actor_id,
            )

            credential = repo.create(request)
            return credential.to_dict()

        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    @app.get("/api/v1/projects/{project_id}/credentials")
    def list_project_credentials(project_id: str) -> List[Dict[str, Any]]:
        """List BYOK credentials for a project.

        Returns credentials without the actual API keys (only prefix shown).
        """
        from .auth.llm_credential_repository import (
            LLMCredentialRepository,
            CredentialScopeType,
        )
        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()
        repo = LLMCredentialRepository(pool)

        credentials = repo.get_for_scope(
            scope_type=CredentialScopeType.PROJECT,
            scope_id=project_id,
            decrypt=False,
        )
        return [cred.to_dict() for cred in credentials]

    @app.delete("/api/v1/projects/{project_id}/credentials/{credential_id}")
    def delete_project_credential(
        project_id: str,
        credential_id: str,
        actor_id: str = Query(..., description="ID of the user deleting the credential"),
    ) -> Dict[str, Any]:
        """Delete a BYOK credential from a project.

        Args:
            project_id: Project ID (used for authorization check)
            credential_id: Credential ID to delete
            actor_id: User deleting the credential
        """
        from .auth.llm_credential_repository import (
            LLMCredentialRepository,
            CredentialScopeType,
        )
        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()
        repo = LLMCredentialRepository(pool)

        # Verify credential belongs to this project
        credential = repo.get_by_id(credential_id)
        if not credential:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Credential not found",
            )
        if credential.scope_type != CredentialScopeType.PROJECT or credential.scope_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Credential does not belong to this project",
            )

        if repo.delete(credential_id, actor_id=actor_id):
            return {"deleted": True, "credential_id": credential_id}
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Credential not found",
            )

    @app.post("/api/v1/projects/{project_id}/credentials/{credential_id}:re-enable")
    def reenable_project_credential(
        project_id: str,
        credential_id: str,
        payload: Dict[str, Any],
        actor_id: str = Query(..., description="ID of the user re-enabling the credential"),
    ) -> Dict[str, Any]:
        """Re-enable a disabled BYOK credential after providing a new key.

        Args:
            project_id: Project ID
            credential_id: Credential ID to re-enable
            payload: {"api_key": "new-sk-xxx..."}
            actor_id: User re-enabling the credential
        """
        from .auth.llm_credential_repository import (
            LLMCredentialRepository,
            CredentialScopeType,
        )
        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()
        repo = LLMCredentialRepository(pool)

        # Verify credential belongs to this project
        credential = repo.get_by_id(credential_id)
        if not credential:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Credential not found",
            )
        if credential.scope_type != CredentialScopeType.PROJECT or credential.scope_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Credential does not belong to this project",
            )

        new_api_key = payload.get("api_key")
        if not new_api_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="api_key is required to re-enable a credential",
            )

        updated = repo.re_enable(credential_id, new_api_key, actor_id=actor_id)
        if updated:
            return updated.to_dict()
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Credential not found",
            )

    @app.get("/api/v1/projects/{project_id}/credentials/{credential_id}/audit")
    def get_project_credential_audit_log(
        project_id: str,
        credential_id: str,
        limit: int = Query(50, ge=1, le=500, description="Max entries to return"),
    ) -> List[Dict[str, Any]]:
        """Get audit log for a project credential.

        Returns recent operations on this credential for compliance/debugging.
        """
        from .auth.llm_credential_repository import (
            LLMCredentialRepository,
            CredentialScopeType,
        )
        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()
        repo = LLMCredentialRepository(pool)

        # Verify credential belongs to this project
        credential = repo.get_by_id(credential_id)
        if not credential:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Credential not found",
            )
        if credential.scope_type != CredentialScopeType.PROJECT or credential.scope_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Credential does not belong to this project",
            )

        return repo.get_audit_log(credential_id, limit=limit)

    # --- Organization Credentials ---

    @app.post("/api/v1/orgs/{org_id}/credentials", status_code=status.HTTP_201_CREATED)
    def create_org_credential(
        org_id: str,
        payload: Dict[str, Any],
        actor_id: str = Query(..., description="ID of the user creating the credential"),
    ) -> Dict[str, Any]:
        """Add or replace a BYOK credential for an organization.

        Args:
            org_id: Organization ID
            payload: {
                "provider": "anthropic" | "openai" | "openrouter",
                "api_key": "sk-xxx...",
                "name": Optional display name
            }
            actor_id: User creating the credential

        Returns:
            Created credential info (without the key itself)
        """
        from .auth.llm_credential_repository import (
            LLMCredentialRepository,
            CreateCredentialRequest,
            CredentialScopeType,
        )
        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()
        repo = LLMCredentialRepository(pool)

        try:
            provider = payload.get("provider")
            api_key = payload.get("api_key")
            name = payload.get("name")

            if not provider:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="provider is required",
                )
            if not api_key:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="api_key is required",
                )

            # Default name if not provided
            if not name:
                name = f"{provider} API Key"

            request = CreateCredentialRequest(
                scope_type=CredentialScopeType.ORG,
                scope_id=org_id,
                provider=provider,
                api_key=api_key,
                name=name,
                created_by=actor_id,
            )

            credential = repo.create(request)
            return credential.to_dict()

        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    @app.get("/api/v1/orgs/{org_id}/credentials")
    def list_org_credentials(org_id: str) -> List[Dict[str, Any]]:
        """List BYOK credentials for an organization.

        Returns credentials without the actual API keys (only prefix shown).
        """
        from .auth.llm_credential_repository import (
            LLMCredentialRepository,
            CredentialScopeType,
        )
        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()
        repo = LLMCredentialRepository(pool)

        credentials = repo.get_for_scope(
            scope_type=CredentialScopeType.ORG,
            scope_id=org_id,
            decrypt=False,
        )
        return [cred.to_dict() for cred in credentials]

    @app.delete("/api/v1/orgs/{org_id}/credentials/{credential_id}")
    def delete_org_credential(
        org_id: str,
        credential_id: str,
        actor_id: str = Query(..., description="ID of the user deleting the credential"),
    ) -> Dict[str, Any]:
        """Delete a BYOK credential from an organization.

        Args:
            org_id: Organization ID (used for authorization check)
            credential_id: Credential ID to delete
            actor_id: User deleting the credential
        """
        from .auth.llm_credential_repository import (
            LLMCredentialRepository,
            CredentialScopeType,
        )
        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()
        repo = LLMCredentialRepository(pool)

        # Verify credential belongs to this org
        credential = repo.get_by_id(credential_id)
        if not credential:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Credential not found",
            )
        if credential.scope_type != CredentialScopeType.ORG or credential.scope_id != org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Credential does not belong to this organization",
            )

        if repo.delete(credential_id, actor_id=actor_id):
            return {"deleted": True, "credential_id": credential_id}
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Credential not found",
            )

    @app.post("/api/v1/orgs/{org_id}/credentials/{credential_id}:re-enable")
    def reenable_org_credential(
        org_id: str,
        credential_id: str,
        payload: Dict[str, Any],
        actor_id: str = Query(..., description="ID of the user re-enabling the credential"),
    ) -> Dict[str, Any]:
        """Re-enable a disabled BYOK credential after providing a new key.

        Args:
            org_id: Organization ID
            credential_id: Credential ID to re-enable
            payload: {"api_key": "new-sk-xxx..."}
            actor_id: User re-enabling the credential
        """
        from .auth.llm_credential_repository import (
            LLMCredentialRepository,
            CredentialScopeType,
        )
        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()
        repo = LLMCredentialRepository(pool)

        # Verify credential belongs to this org
        credential = repo.get_by_id(credential_id)
        if not credential:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Credential not found",
            )
        if credential.scope_type != CredentialScopeType.ORG or credential.scope_id != org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Credential does not belong to this organization",
            )

        new_api_key = payload.get("api_key")
        if not new_api_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="api_key is required to re-enable a credential",
            )

        updated = repo.re_enable(credential_id, new_api_key, actor_id=actor_id)
        if updated:
            return updated.to_dict()
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Credential not found",
            )

    @app.get("/api/v1/orgs/{org_id}/credentials/{credential_id}/audit")
    def get_org_credential_audit_log(
        org_id: str,
        credential_id: str,
        limit: int = Query(50, ge=1, le=500, description="Max entries to return"),
    ) -> List[Dict[str, Any]]:
        """Get audit log for an organization credential.

        Returns recent operations on this credential for compliance/debugging.
        """
        from .auth.llm_credential_repository import (
            LLMCredentialRepository,
            CredentialScopeType,
        )
        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()
        repo = LLMCredentialRepository(pool)

        # Verify credential belongs to this org
        credential = repo.get_by_id(credential_id)
        if not credential:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Credential not found",
            )
        if credential.scope_type != CredentialScopeType.ORG or credential.scope_id != org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Credential does not belong to this organization",
            )

        return repo.get_audit_log(credential_id, limit=limit)

    # ------------------------------------------------------------------
    # GitHub Credentials (BYOK)
    # ------------------------------------------------------------------

    @app.post("/api/v1/projects/{project_id}/github-credential", status_code=status.HTTP_201_CREATED)
    def create_project_github_credential(
        project_id: str,
        payload: Dict[str, Any],
        actor_id: str = Query(..., description="ID of the user creating the credential"),
    ) -> Dict[str, Any]:
        """Add or replace a BYOK GitHub PAT for a project.

        The token will be validated against GitHub API before saving.
        Token type is auto-detected from prefix (ghp_, github_pat_, ghs_).

        Args:
            project_id: Project ID
            payload: {
                "token": "ghp_xxx..." or "github_pat_xxx...",
                "name": Optional display name (defaults to "GitHub PAT (username)")
            }
            actor_id: User creating the credential

        Returns:
            Created credential info (without the token itself), plus scope warning if applicable
        """
        from .auth.github_credential_repository import (
            GitHubCredentialRepository,
            CreateGitHubCredentialRequest,
            CredentialScopeType,
        )
        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()
        repo = GitHubCredentialRepository(pool)

        try:
            token = payload.get("token")
            name = payload.get("name")

            if not token:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="token is required",
                )

            request = CreateGitHubCredentialRequest(
                scope_type=CredentialScopeType.PROJECT,
                scope_id=project_id,
                token=token,
                name=name,
                created_by=actor_id,
            )

            credential, warning = repo.create(request)
            result = credential.to_dict()
            if warning:
                result["warning"] = warning
            return result

        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    @app.get("/api/v1/projects/{project_id}/github-credential")
    def get_project_github_credential(project_id: str) -> Optional[Dict[str, Any]]:
        """Get the GitHub credential for a project.

        Returns credential without the actual token (only prefix shown),
        or null if no credential is configured.
        """
        from .auth.github_credential_repository import (
            GitHubCredentialRepository,
            CredentialScopeType,
        )
        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()
        repo = GitHubCredentialRepository(pool)

        credential = repo.get_for_scope(
            scope_type=CredentialScopeType.PROJECT,
            scope_id=project_id,
            decrypt=False,
        )
        if not credential:
            return None
        return credential.to_dict()

    @app.delete("/api/v1/projects/{project_id}/github-credential")
    def delete_project_github_credential(
        project_id: str,
        actor_id: str = Query(..., description="ID of the user deleting the credential"),
    ) -> Dict[str, Any]:
        """Delete the GitHub credential from a project.

        Args:
            project_id: Project ID
            actor_id: User deleting the credential
        """
        from .auth.github_credential_repository import (
            GitHubCredentialRepository,
            CredentialScopeType,
        )
        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()
        repo = GitHubCredentialRepository(pool)

        # Get the credential for this project
        credential = repo.get_for_scope(
            scope_type=CredentialScopeType.PROJECT,
            scope_id=project_id,
        )
        if not credential:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No GitHub credential configured for this project",
            )

        if repo.delete(credential.id, actor_id=actor_id):
            return {"deleted": True, "credential_id": credential.id}
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Credential not found",
            )

    @app.post("/api/v1/projects/{project_id}/github-credential:re-enable")
    def reenable_project_github_credential(
        project_id: str,
        payload: Dict[str, Any],
        actor_id: str = Query(..., description="ID of the user re-enabling the credential"),
    ) -> Dict[str, Any]:
        """Re-enable a disabled GitHub credential with a new token.

        The new token will be validated against GitHub API.

        Args:
            project_id: Project ID
            payload: {"token": "new-ghp_xxx..."}
            actor_id: User re-enabling the credential
        """
        from .auth.github_credential_repository import (
            GitHubCredentialRepository,
            CredentialScopeType,
        )
        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()
        repo = GitHubCredentialRepository(pool)

        # Get the credential for this project
        credential = repo.get_for_scope(
            scope_type=CredentialScopeType.PROJECT,
            scope_id=project_id,
        )
        if not credential:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No GitHub credential configured for this project",
            )

        new_token = payload.get("token")
        if not new_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="token is required to re-enable a credential",
            )

        try:
            updated = repo.re_enable(credential.id, new_token, actor_id=actor_id)
            if updated:
                return updated.to_dict()
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Credential not found",
                )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    @app.get("/api/v1/projects/{project_id}/github-credential/audit")
    def get_project_github_credential_audit_log(
        project_id: str,
        limit: int = Query(50, ge=1, le=500, description="Max entries to return"),
    ) -> List[Dict[str, Any]]:
        """Get audit log for a project's GitHub credential.

        Returns recent operations on this credential for compliance/debugging.
        """
        from .auth.github_credential_repository import (
            GitHubCredentialRepository,
            CredentialScopeType,
        )
        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()
        repo = GitHubCredentialRepository(pool)

        credential = repo.get_for_scope(
            scope_type=CredentialScopeType.PROJECT,
            scope_id=project_id,
        )
        if not credential:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No GitHub credential configured for this project",
            )

        entries = repo.get_audit_log(credential.id, limit=limit)
        return [
            {
                "id": entry.id,
                "credential_id": entry.credential_id,
                "action": entry.action.value,
                "actor_id": entry.actor_id,
                "actor_type": entry.actor_type.value,
                "details": entry.details,
                "created_at": entry.created_at.isoformat() if entry.created_at else None,
            }
            for entry in entries
        ]

    # --- Organization GitHub Credentials ---

    @app.post("/api/v1/orgs/{org_id}/github-credential", status_code=status.HTTP_201_CREATED)
    def create_org_github_credential(
        org_id: str,
        payload: Dict[str, Any],
        actor_id: str = Query(..., description="ID of the user creating the credential"),
    ) -> Dict[str, Any]:
        """Add or replace a BYOK GitHub PAT for an organization.

        The token will be validated against GitHub API before saving.
        Token type is auto-detected from prefix (ghp_, github_pat_, ghs_).

        Args:
            org_id: Organization ID
            payload: {
                "token": "ghp_xxx..." or "github_pat_xxx...",
                "name": Optional display name
            }
            actor_id: User creating the credential

        Returns:
            Created credential info (without the token itself), plus scope warning if applicable
        """
        from .auth.github_credential_repository import (
            GitHubCredentialRepository,
            CreateGitHubCredentialRequest,
            CredentialScopeType,
        )
        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()
        repo = GitHubCredentialRepository(pool)

        try:
            token = payload.get("token")
            name = payload.get("name")

            if not token:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="token is required",
                )

            request = CreateGitHubCredentialRequest(
                scope_type=CredentialScopeType.ORG,
                scope_id=org_id,
                token=token,
                name=name,
                created_by=actor_id,
            )

            credential, warning = repo.create(request)
            result = credential.to_dict()
            if warning:
                result["warning"] = warning
            return result

        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    @app.get("/api/v1/orgs/{org_id}/github-credential")
    def get_org_github_credential(org_id: str) -> Dict[str, Any]:
        """Get the GitHub credential for an organization.

        Returns credential without the actual token (only prefix shown).
        """
        from .auth.github_credential_repository import (
            GitHubCredentialRepository,
            CredentialScopeType,
        )
        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()
        repo = GitHubCredentialRepository(pool)

        credential = repo.get_for_scope(
            scope_type=CredentialScopeType.ORG,
            scope_id=org_id,
            decrypt=False,
        )
        if not credential:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No GitHub credential configured for this organization",
            )
        return credential.to_dict()

    @app.delete("/api/v1/orgs/{org_id}/github-credential")
    def delete_org_github_credential(
        org_id: str,
        actor_id: str = Query(..., description="ID of the user deleting the credential"),
    ) -> Dict[str, Any]:
        """Delete the GitHub credential from an organization.

        Args:
            org_id: Organization ID
            actor_id: User deleting the credential
        """
        from .auth.github_credential_repository import (
            GitHubCredentialRepository,
            CredentialScopeType,
        )
        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()
        repo = GitHubCredentialRepository(pool)

        credential = repo.get_for_scope(
            scope_type=CredentialScopeType.ORG,
            scope_id=org_id,
        )
        if not credential:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No GitHub credential configured for this organization",
            )

        if repo.delete(credential.id, actor_id=actor_id):
            return {"deleted": True, "credential_id": credential.id}
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Credential not found",
            )

    @app.post("/api/v1/orgs/{org_id}/github-credential:re-enable")
    def reenable_org_github_credential(
        org_id: str,
        payload: Dict[str, Any],
        actor_id: str = Query(..., description="ID of the user re-enabling the credential"),
    ) -> Dict[str, Any]:
        """Re-enable a disabled GitHub credential with a new token.

        The new token will be validated against GitHub API.

        Args:
            org_id: Organization ID
            payload: {"token": "new-ghp_xxx..."}
            actor_id: User re-enabling the credential
        """
        from .auth.github_credential_repository import (
            GitHubCredentialRepository,
            CredentialScopeType,
        )
        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()
        repo = GitHubCredentialRepository(pool)

        credential = repo.get_for_scope(
            scope_type=CredentialScopeType.ORG,
            scope_id=org_id,
        )
        if not credential:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No GitHub credential configured for this organization",
            )

        new_token = payload.get("token")
        if not new_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="token is required to re-enable a credential",
            )

        try:
            updated = repo.re_enable(credential.id, new_token, actor_id=actor_id)
            if updated:
                return updated.to_dict()
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Credential not found",
                )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    @app.get("/api/v1/orgs/{org_id}/github-credential/audit")
    def get_org_github_credential_audit_log(
        org_id: str,
        limit: int = Query(50, ge=1, le=500, description="Max entries to return"),
    ) -> List[Dict[str, Any]]:
        """Get audit log for an organization's GitHub credential.

        Returns recent operations on this credential for compliance/debugging.
        """
        from .auth.github_credential_repository import (
            GitHubCredentialRepository,
            CredentialScopeType,
        )
        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()
        repo = GitHubCredentialRepository(pool)

        credential = repo.get_for_scope(
            scope_type=CredentialScopeType.ORG,
            scope_id=org_id,
        )
        if not credential:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No GitHub credential configured for this organization",
            )

        entries = repo.get_audit_log(credential.id, limit=limit)
        return [
            {
                "id": entry.id,
                "credential_id": entry.credential_id,
                "action": entry.action.value,
                "actor_id": entry.actor_id,
                "actor_type": entry.actor_type.value,
                "details": entry.details,
                "created_at": entry.created_at.isoformat() if entry.created_at else None,
            }
            for entry in entries
        ]

    # ------------------------------------------------------------------
    # GitHub App (Recommended over PAT)
    # ------------------------------------------------------------------

    @app.get("/api/v1/github-app/status")
    def get_github_app_status() -> Dict[str, Any]:
        """Check if GitHub App is configured.

        Returns whether the GitHub App integration is available.
        """
        from .auth.github_app_service import get_github_app_service

        service = get_github_app_service()
        return {
            "configured": service.is_configured,
            "message": "GitHub App is configured" if service.is_configured
                else "GitHub App not configured. Set GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY, etc.",
        }

    @app.get("/api/v1/github-app/installations")
    async def list_github_app_installations() -> List[Dict[str, Any]]:
        """List GitHub App installations available to the app."""
        from .auth.github_app_service import get_github_app_service

        service = get_github_app_service()
        if not service.is_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="GitHub App not configured",
            )

        installations = await service.list_installations()
        app_slug = service._config.slug if service._config else None

        summaries: List[Dict[str, Any]] = []
        for inst in installations:
            account = inst.get("account", {}) if isinstance(inst, dict) else {}
            summaries.append({
                "installation_id": inst.get("id"),
                "account_login": account.get("login"),
                "account_type": account.get("type"),
                "account_avatar_url": account.get("avatar_url"),
                "repository_selection": inst.get("repository_selection"),
                "html_url": inst.get("html_url"),
                "app_slug": app_slug,
            })

        return summaries

    @app.get("/api/v1/github-app/install-url")
    def get_github_app_install_url(
        scope_type: str = Query(..., description="Scope type: 'project' or 'org'"),
        scope_id: str = Query(..., description="Project or organization ID"),
        redirect_uri: Optional[str] = Query(None, description="Where to redirect after installation"),
    ) -> Dict[str, str]:
        """Get URL to install/configure the GitHub App.

        Initiates OAuth-like flow for GitHub App installation.
        User will be redirected to GitHub to authorize the app.
        """
        from .auth.github_app_service import get_github_app_service

        service = get_github_app_service()
        if not service.is_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="GitHub App not configured. Contact administrator.",
            )

        try:
            url, state = service.get_install_url(
                scope_type=scope_type,
                scope_id=scope_id,
                redirect_uri=redirect_uri,
            )
            return {"url": url, "state": state}
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    @app.get("/api/v1/github-app/callback")
    async def github_app_callback(
        installation_id: int = Query(..., description="GitHub App installation ID"),
        setup_action: str = Query("install", description="Action: install, update, delete"),
        state: str = Query(..., description="Signed state for CSRF verification"),
        actor_id: Optional[str] = Query(None, description="User who initiated the flow"),
    ) -> RedirectResponse:
        """Handle GitHub App installation callback.

        Called when GitHub redirects back after app installation.
        Verifies state, fetches installation details, and stores them.
        """
        from .auth.github_app_service import get_github_app_service, InstallationState

        service = get_github_app_service()
        if not service.is_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="GitHub App not configured",
            )

        try:
            installation = await service.handle_installation_callback(
                installation_id=installation_id,
                setup_action=setup_action,
                state=state,
                installed_by=actor_id,
            )

            # Decode state to get redirect URI
            decoded_state = InstallationState.decode(state, service._state_secret)
            redirect_uri = decoded_state.redirect_uri if decoded_state else None

            # Build redirect URL
            if redirect_uri:
                redirect_url = redirect_uri
            elif decoded_state:
                if decoded_state.scope_type == "project":
                    redirect_url = f"/projects/{decoded_state.scope_id}/settings?github=connected"
                else:
                    redirect_url = f"/orgs/{decoded_state.scope_id}/settings?github=connected"
            else:
                redirect_url = "/"

            # Add status to redirect
            if setup_action == "delete":
                redirect_url += "&status=disconnected" if "?" in redirect_url else "?status=disconnected"

            return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

        except ValueError as exc:
            logger.warning(f"GitHub App callback failed: {exc}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    @app.get("/api/v1/projects/{project_id}/github-app-installation")
    def get_project_github_app_installation(project_id: str) -> Optional[Dict[str, Any]]:
        """Get the GitHub App installation for a project.

        Returns installation details or null if not connected.
        """
        from .auth.github_app_service import get_github_app_service
        from .auth.github_credential_repository import CredentialScopeType

        service = get_github_app_service()
        if not service.is_configured:
            return None

        installation = service.get_installation_for_scope(
            scope_type=CredentialScopeType.PROJECT,
            scope_id=project_id,
        )
        if not installation:
            return None
        return installation.to_dict()

    @app.post("/api/v1/projects/{project_id}/github-app-installation/link")
    async def link_project_to_github_app_installation(
        project_id: str,
        payload: Dict[str, Any],
        actor_id: str = Query(..., description="User linking the installation"),
    ) -> Dict[str, Any]:
        """Link a project to an existing GitHub App installation.

        Useful when multiple projects should share the same installation.
        If the installation isn't in our database yet, fetches from GitHub API.

        Args:
            project_id: Project ID
            payload: {"installation_id": 12345}
            actor_id: User performing the link
        """
        from .auth.github_app_service import get_github_app_service
        from .auth.github_credential_repository import CredentialScopeType

        service = get_github_app_service()
        if not service.is_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="GitHub App not configured",
            )

        installation_id = payload.get("installation_id")
        if not installation_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="installation_id is required",
            )

        success = await service.link_existing_installation(
            installation_id=installation_id,
            scope_type=CredentialScopeType.PROJECT,
            scope_id=project_id,
            linked_by=actor_id,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Installation not found or inactive",
            )

        installation = service.get_installation_for_scope(
            scope_type=CredentialScopeType.PROJECT,
            scope_id=project_id,
        )
        return installation.to_dict() if installation else {"linked": True}

    @app.delete("/api/v1/projects/{project_id}/github-app-installation")
    def unlink_project_github_app_installation(
        project_id: str,
        actor_id: str = Query(..., description="User unlinking the installation"),
    ) -> Dict[str, Any]:
        """Unlink GitHub App installation from a project.

        Note: This does NOT uninstall the app from GitHub, just removes
        the link between this project and the installation.
        """
        from .auth.github_app_service import get_github_app_service
        from .auth.github_credential_repository import CredentialScopeType

        service = get_github_app_service()
        if not service.is_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="GitHub App not configured",
            )

        success = service.unlink_installation(
            scope_type=CredentialScopeType.PROJECT,
            scope_id=project_id,
        )

        return {"unlinked": success}

    @app.get("/api/v1/github-app/installation/{installation_id}/configure-url")
    def get_github_app_configure_url(installation_id: int) -> Dict[str, str]:
        """Get URL to configure an existing GitHub App installation.

        Use this to let users modify which repos the app can access.
        """
        from .auth.github_app_service import get_github_app_service

        service = get_github_app_service()
        if not service.is_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="GitHub App not configured",
            )

        url = service.get_configure_url(installation_id)
        return {"url": url}

    # --- Organization GitHub App ---

    @app.get("/api/v1/orgs/{org_id}/github-app-installation")
    def get_org_github_app_installation(org_id: str) -> Optional[Dict[str, Any]]:
        """Get the GitHub App installation for an organization.

        Returns installation details or null if not connected.
        """
        from .auth.github_app_service import get_github_app_service
        from .auth.github_credential_repository import CredentialScopeType

        service = get_github_app_service()
        if not service.is_configured:
            return None

        installation = service.get_installation_for_scope(
            scope_type=CredentialScopeType.ORG,
            scope_id=org_id,
        )
        if not installation:
            return None
        return installation.to_dict()

    @app.delete("/api/v1/orgs/{org_id}/github-app-installation")
    def unlink_org_github_app_installation(
        org_id: str,
        actor_id: str = Query(..., description="User unlinking the installation"),
    ) -> Dict[str, Any]:
        """Unlink GitHub App installation from an organization.

        Note: This does NOT uninstall the app from GitHub.
        """
        from .auth.github_app_service import get_github_app_service
        from .auth.github_credential_repository import CredentialScopeType

        service = get_github_app_service()
        if not service.is_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="GitHub App not configured",
            )

        success = service.unlink_installation(
            scope_type=CredentialScopeType.ORG,
            scope_id=org_id,
        )

        return {"unlinked": success}

    # ------------------------------------------------------------------
    # Per-User GitHub Credential Links
    # ------------------------------------------------------------------
    # These endpoints manage user-specific GitHub credential links.
    # Users link their personal GitHub credentials (PAT or App installation)
    # to projects so that agents executing work items use the correct
    # user's GitHub access.

    @app.get("/api/v1/projects/{project_id}/github/my-link")
    def get_my_project_github_link(
        project_id: str,
        request: Request,
    ) -> Optional[Dict[str, Any]]:
        """Get the current user's GitHub credential link for a project.

        Returns the user's linked credential (PAT or App) or null if not linked.
        """
        user_id = _require_user_id(request)

        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()

        try:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT
                            upl.id,
                            upl.link_type,
                            upl.github_credential_id,
                            upl.installation_link_id,
                            upl.priority,
                            upl.created_at,
                            upl.last_used_at,
                            CASE
                                WHEN upl.link_type = 'pat' THEN gc.name
                                WHEN upl.link_type = 'app' THEN gai.account_login
                            END AS credential_name,
                            CASE
                                WHEN upl.link_type = 'pat' THEN gc.github_username
                                WHEN upl.link_type = 'app' THEN gai.account_login
                            END AS github_identity
                        FROM auth.user_project_github_links upl
                        LEFT JOIN credentials.github_credentials gc
                            ON upl.github_credential_id = gc.id
                        LEFT JOIN auth.github_app_installation_links gail
                            ON upl.installation_link_id = gail.id
                        LEFT JOIN auth.github_app_installations gai
                            ON gail.installation_id = gai.installation_id
                        WHERE upl.user_id = %s
                          AND upl.project_id = %s
                        ORDER BY upl.priority ASC
                        LIMIT 1
                    """, (user_id, project_id))
                    row = cur.fetchone()

            if not row:
                return None

            (
                link_id, link_type, credential_id, installation_link_id,
                priority, created_at, last_used_at, credential_name, github_identity
            ) = row

            return {
                "id": link_id,
                "link_type": link_type,
                "github_credential_id": credential_id,
                "installation_link_id": installation_link_id,
                "priority": priority,
                "credential_name": credential_name,
                "github_identity": github_identity,
                "created_at": created_at.isoformat() if created_at else None,
                "last_used_at": last_used_at.isoformat() if last_used_at else None,
            }

        except Exception as exc:
            logger.exception(f"Error getting user GitHub link: {exc}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to get GitHub link",
            ) from exc

    @app.post("/api/v1/projects/{project_id}/github/link-pat")
    def link_my_pat_to_project(
        project_id: str,
        payload: Dict[str, Any],
        request: Request,
    ) -> Dict[str, Any]:
        """Link the current user's PAT credential to a project.

        Args:
            project_id: Project ID
            payload: {
                "github_credential_id": "uuid-of-existing-pat"
                OR
                "token": "ghp_xxx..." (to create a new PAT)
                "name": Optional name for new PAT
            }

        The PAT must belong to the current user (created_by matches user_id).
        """
        user_id = _require_user_id(request)

        from .auth.github_credential_repository import (
            GitHubCredentialRepository,
            CreateGitHubCredentialRequest,
            CredentialScopeType,
        )
        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()
        repo = GitHubCredentialRepository(pool)

        credential_id = payload.get("github_credential_id")
        token = payload.get("token")

        if not credential_id and not token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either github_credential_id or token is required",
            )

        # If token provided, create a new credential first
        if token:
            try:
                request_obj = CreateGitHubCredentialRequest(
                    scope_type=CredentialScopeType.USER,
                    scope_id=user_id,
                    token=token,
                    name=payload.get("name"),
                    created_by=user_id,
                )
                credential, warning = repo.create(request_obj)
                credential_id = credential.id
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(exc),
                ) from exc
        else:
            # Verify the credential belongs to this user
            credential = repo.get_by_id(credential_id, decrypt=False)
            if not credential:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Credential not found",
                )
            if credential.created_by != user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cannot link another user's credential",
                )

        # Create or update the link
        try:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO auth.user_project_github_links
                            (user_id, project_id, link_type, github_credential_id, priority)
                        VALUES (%s, %s, 'pat', %s, 0)
                        ON CONFLICT (user_id, project_id, link_type)
                        DO UPDATE SET
                            github_credential_id = EXCLUDED.github_credential_id,
                            installation_link_id = NULL,
                            updated_at = NOW()
                        RETURNING id
                    """, (user_id, project_id, credential_id))
                    link_id = cur.fetchone()[0]
                conn.commit()

            return {
                "id": link_id,
                "link_type": "pat",
                "github_credential_id": credential_id,
                "linked": True,
            }

        except Exception as exc:
            logger.exception(f"Error linking PAT to project: {exc}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to link PAT",
            ) from exc

    @app.post("/api/v1/projects/{project_id}/github/link-app")
    async def link_my_app_to_project(
        project_id: str,
        payload: Dict[str, Any],
        request: Request,
    ) -> Dict[str, Any]:
        """Link the current user's GitHub App installation to a project.

        Args:
            project_id: Project ID
            payload: {
                "installation_link_id": "uuid-of-existing-installation-link"
                OR
                "installation_id": 12345 (GitHub's installation ID)
            }

        GitHub App installations are shareable, so any user with access to
        the installation can link it to their projects.
        If the installation isn't in our database yet, fetches from GitHub API.
        """
        user_id = _require_user_id(request)

        from .auth.github_app_service import get_github_app_service
        from .auth.github_credential_repository import CredentialScopeType
        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()

        installation_link_id = payload.get("installation_link_id")
        installation_id = payload.get("installation_id")

        if not installation_link_id and not installation_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either installation_link_id or installation_id is required",
            )

        # If installation_id provided, find or create the link
        if installation_id:
            service = get_github_app_service()
            if not service.is_configured:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="GitHub App not configured",
                )

            # Link the installation (fetches from GitHub if not in DB)
            success = await service.link_existing_installation(
                installation_id=installation_id,
                scope_type=CredentialScopeType.PROJECT,
                scope_id=project_id,
                linked_by=user_id,
            )

            if not success:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to link installation",
                )

            # Get the installation link ID
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id FROM auth.github_app_installation_links
                        WHERE installation_id = %s AND scope_type = 'PROJECT' AND scope_id = %s
                    """, (installation_id, project_id))
                    row = cur.fetchone()

            if row:
                installation_link_id = row[0]
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to find installation link",
                )
        else:
            # Verify the installation link exists
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id FROM auth.github_app_installation_links
                        WHERE id = %s
                    """, (installation_link_id,))
                    if not cur.fetchone():
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail="Installation link not found",
                        )

        # Create or update the user link
        try:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO auth.user_project_github_links
                            (user_id, project_id, link_type, installation_link_id, priority)
                        VALUES (%s, %s, 'app', %s, 0)
                        ON CONFLICT (user_id, project_id, link_type)
                        DO UPDATE SET
                            installation_link_id = EXCLUDED.installation_link_id,
                            github_credential_id = NULL,
                            updated_at = NOW()
                        RETURNING id
                    """, (user_id, project_id, installation_link_id))
                    link_id = cur.fetchone()[0]
                conn.commit()

            return {
                "id": link_id,
                "link_type": "app",
                "installation_link_id": installation_link_id,
                "linked": True,
            }

        except Exception as exc:
            logger.exception(f"Error linking App to project: {exc}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to link App installation",
            ) from exc

    @app.delete("/api/v1/projects/{project_id}/github/my-link")
    def unlink_my_github_from_project(
        project_id: str,
        link_type: Optional[str] = Query(default=None, description="'pat' or 'app', or omit for all"),
        request: Request = None,
    ) -> Dict[str, Any]:
        """Remove the current user's GitHub credential link from a project.

        Args:
            project_id: Project ID
            link_type: Optional - 'pat', 'app', or omit to remove all links
        """
        user_id = _require_user_id(request)

        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()

        try:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    if link_type:
                        cur.execute("""
                            DELETE FROM auth.user_project_github_links
                            WHERE user_id = %s AND project_id = %s AND link_type = %s
                            RETURNING id
                        """, (user_id, project_id, link_type))
                    else:
                        cur.execute("""
                            DELETE FROM auth.user_project_github_links
                            WHERE user_id = %s AND project_id = %s
                            RETURNING id
                        """, (user_id, project_id))
                    deleted = cur.fetchall()
                conn.commit()

            return {
                "unlinked": len(deleted) > 0,
                "deleted_count": len(deleted),
            }

        except Exception as exc:
            logger.exception(f"Error unlinking GitHub from project: {exc}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to unlink GitHub",
            ) from exc

    @app.get("/api/v1/projects/{project_id}/github/resolution")
    def get_github_resolution_for_project(
        project_id: str,
        request: Request,
    ) -> Dict[str, Any]:
        """Show which GitHub credential would be used for the current user + project.

        This helps users understand the credential resolution hierarchy and
        verify their configuration before running work items.
        """
        user_id = _require_user_id(request)

        from .services.github_service import GitHubCredentialStore
        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()

        # Get the project's org_id for resolution
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT org_id FROM projects WHERE id = %s", (project_id,))
                row = cur.fetchone()
                org_id = row[0] if row else None

        store = GitHubCredentialStore(pool=pool)
        resolved = store.get_resolved_token(
            project_id=project_id,
            org_id=org_id,
            user_id=user_id,
        )

        if not resolved:
            return {
                "has_credential": False,
                "source": None,
                "message": "No GitHub credential available for this project",
                "resolution_order": [
                    "1. User's linked GitHub App installation",
                    "2. User's linked PAT",
                    "3. Project's shared GitHub App installation",
                    "4. Project's shared PAT",
                    "5. Organization's GitHub App installation",
                    "6. Organization's PAT",
                    "7. Platform-level fallback token",
                ],
            }

        return {
            "has_credential": True,
            "source": resolved.source,
            "credential_id": resolved.credential_id,
            "installation_id": resolved.installation_id,
            "github_username": resolved.github_username,
            "token_type": resolved.token_type,
            "has_required_scopes": resolved.has_required_scopes,
            "scope_warning": resolved.scope_warning,
            "resolved_for_user_id": resolved.resolved_for_user_id,
            "link_id": resolved.link_id,
        }

    # ------------------------------------------------------------------
    # User GitHub Preferences
    # ------------------------------------------------------------------

    @app.get("/api/v1/users/me/github-preferences")
    def get_my_github_preferences(request: Request) -> Dict[str, Any]:
        """Get the current user's GitHub preferences.

        Returns default credential settings and auto-link preferences.
        """
        user_id = _require_user_id(request)

        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()

        try:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT
                            default_pat_credential_id,
                            default_app_installation_id,
                            auto_link_new_projects,
                            prefer_app_over_pat,
                            created_at,
                            updated_at
                        FROM auth.user_github_preferences
                        WHERE user_id = %s
                    """, (user_id,))
                    row = cur.fetchone()

            if not row:
                # Return defaults
                return {
                    "default_pat_credential_id": None,
                    "default_app_installation_id": None,
                    "auto_link_new_projects": False,
                    "prefer_app_over_pat": True,  # Default: prefer App if both available
                }

            (
                default_pat_credential_id, default_app_installation_id,
                auto_link_new_projects, prefer_app_over_pat,
                created_at, updated_at
            ) = row

            return {
                "default_pat_credential_id": default_pat_credential_id,
                "default_app_installation_id": default_app_installation_id,
                "auto_link_new_projects": auto_link_new_projects,
                "prefer_app_over_pat": prefer_app_over_pat,
                "created_at": created_at.isoformat() if created_at else None,
                "updated_at": updated_at.isoformat() if updated_at else None,
            }

        except Exception as exc:
            logger.exception(f"Error getting user GitHub preferences: {exc}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to get preferences",
            ) from exc

    @app.put("/api/v1/users/me/github-preferences")
    def update_my_github_preferences(
        payload: Dict[str, Any],
        request: Request,
    ) -> Dict[str, Any]:
        """Update the current user's GitHub preferences.

        Args:
            payload: {
                "default_pat_credential_id": "uuid" or null,
                "default_app_installation_id": 12345 or null,
                "auto_link_new_projects": true/false,
                "prefer_app_over_pat": true/false
            }
        """
        user_id = _require_user_id(request)

        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()

        try:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO auth.user_github_preferences
                            (user_id, default_pat_credential_id, default_app_installation_id,
                             auto_link_new_projects, prefer_app_over_pat)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (user_id)
                        DO UPDATE SET
                            default_pat_credential_id = EXCLUDED.default_pat_credential_id,
                            default_app_installation_id = EXCLUDED.default_app_installation_id,
                            auto_link_new_projects = EXCLUDED.auto_link_new_projects,
                            prefer_app_over_pat = EXCLUDED.prefer_app_over_pat,
                            updated_at = NOW()
                        RETURNING
                            default_pat_credential_id, default_app_installation_id,
                            auto_link_new_projects, prefer_app_over_pat, updated_at
                    """, (
                        user_id,
                        payload.get("default_pat_credential_id"),
                        payload.get("default_app_installation_id"),
                        payload.get("auto_link_new_projects", False),
                        payload.get("prefer_app_over_pat", True),
                    ))
                    row = cur.fetchone()
                conn.commit()

            (
                default_pat_credential_id, default_app_installation_id,
                auto_link_new_projects, prefer_app_over_pat, updated_at
            ) = row

            return {
                "default_pat_credential_id": default_pat_credential_id,
                "default_app_installation_id": default_app_installation_id,
                "auto_link_new_projects": auto_link_new_projects,
                "prefer_app_over_pat": prefer_app_over_pat,
                "updated_at": updated_at.isoformat() if updated_at else None,
            }

        except Exception as exc:
            logger.exception(f"Error updating user GitHub preferences: {exc}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update preferences",
            ) from exc

    @app.get("/api/v1/users/me/github-credentials")
    def list_my_github_credentials(request: Request) -> List[Dict[str, Any]]:
        """List all GitHub credentials owned by the current user.

        Returns PATs created by the user (without actual token values).
        """
        user_id = _require_user_id(request)

        from .auth.github_credential_repository import GitHubCredentialRepository
        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()
        repo = GitHubCredentialRepository(pool)

        credentials = repo.list_by_creator(user_id)
        return [c.to_dict() for c in credentials]

    @app.get("/api/v1/users/me/github-app-installations")
    def list_my_github_app_installations(request: Request) -> List[Dict[str, Any]]:
        """List GitHub App installations accessible to the current user.

        Returns installations the user has linked to their projects, plus
        installations linked to projects/orgs the user has access to.
        """
        user_id = _require_user_id(request)

        from .auth.github_app_service import get_github_app_service
        from .storage.postgres_pool import PostgresPool

        pool = PostgresPool()
        service = get_github_app_service()

        if not service.is_configured:
            return []

        try:
            # Get installations user has personally linked
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT DISTINCT
                            gai.installation_id,
                            gai.account_type,
                            gai.account_login,
                            gai.account_id,
                            gai.permissions,
                            gai.is_active
                        FROM auth.github_app_installations gai
                        JOIN auth.github_app_installation_links gail
                            ON gai.installation_id = gail.installation_id
                        WHERE gail.linked_by = %s
                           OR EXISTS (
                               SELECT 1 FROM auth.user_project_github_links upl
                               WHERE upl.installation_link_id = gail.id
                                 AND upl.user_id = %s
                           )
                        ORDER BY gai.account_login
                    """, (user_id, user_id))
                    rows = cur.fetchall()

            return [
                {
                    "installation_id": row[0],
                    "account_type": row[1],
                    "account_login": row[2],
                    "account_id": row[3],
                    "permissions": row[4],
                    "is_active": row[5],
                }
                for row in rows
            ]

        except Exception as exc:
            logger.exception(f"Error listing user GitHub App installations: {exc}")
            return []

    # ------------------------------------------------------------------
    # Workflows
    # ------------------------------------------------------------------
    @app.post("/api/v1/workflows/templates", status_code=status.HTTP_201_CREATED)
    def create_workflow_template(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.workflow_adapter.create_template(payload)
        except Exception as exc:  # pylint: disable=broad-except
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/v1/workflows/templates")
    def list_workflow_templates(
        role_focus: Optional[str] = Query(default=None),
        tags: Optional[List[str]] = Query(default=None),
    ) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {}
        if role_focus:
            payload["role_focus"] = role_focus
        if tags:
            payload["tags"] = list(tags)
        return container.workflow_adapter.list_templates(payload)

    @app.get("/api/v1/workflows/templates/{template_id}")
    def get_workflow_template(template_id: str) -> Dict[str, Any]:
        template = container.workflow_adapter.get_template(template_id)
        if template is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow template not found")
        return template

    @app.post("/api/v1/workflows/runs", status_code=status.HTTP_201_CREATED)
    def start_workflow_run(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.workflow_adapter.run_workflow(payload)
        except Exception as exc:  # pylint: disable=broad-except
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/v1/workflows/runs/{run_id}")
    def get_workflow_run(run_id: str) -> Dict[str, Any]:
        run = container.workflow_adapter.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found")
        return run

    @app.patch("/api/v1/workflows/runs/{run_id}")
    def update_workflow_run(run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            status_value = payload.get("status")
            if status_value is not None:
                WorkflowStatus(status_value)  # Validate value early
            return container.workflow_adapter.update_run_status(run_id, payload)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # BreakerAmp
    # ------------------------------------------------------------------
    @app.post("/api/v1/breakeramp/plan", status_code=status.HTTP_202_ACCEPTED)
    def breakeramp_plan(
        payload: PlanRequest,
        actor_id: str = Query(..., description="ID of the actor requesting the plan"),
        actor_role: str = Query(..., description="Role of the actor"),
    ) -> PlanResponse:
        """Create an execution plan for a given goal."""
        actor = Actor(id=actor_id, role=actor_role, surface="api")
        return container.breakeramp_adapter.plan(payload, actor=actor)

    @app.post("/api/v1/breakeramp/apply", status_code=status.HTTP_202_ACCEPTED)
    def breakeramp_apply(
        payload: ApplyRequest,
        actor_id: str = Query(..., description="ID of the actor applying the plan"),
        actor_role: str = Query(..., description="Role of the actor"),
    ) -> ApplyResponse:
        """Apply a previously created plan."""
        actor = Actor(id=actor_id, role=actor_role, surface="api")
        return container.breakeramp_adapter.apply(payload, actor=actor)

    @app.get("/api/v1/breakeramp/status/{run_id}")
    def breakeramp_status(run_id: str) -> StatusResponse:
        """Get the status of a plan or apply operation."""
        return container.breakeramp_adapter.status(run_id)

    @app.post("/api/v1/breakeramp/destroy", status_code=status.HTTP_202_ACCEPTED)
    def breakeramp_destroy(
        payload: DestroyRequest,
        actor_id: str = Query(..., description="ID of the actor requesting destruction"),
        actor_role: str = Query(..., description="Role of the actor"),
    ) -> DestroyResponse:
        """Destroy resources associated with a deployment."""
        actor = Actor(id=actor_id, role=actor_role, surface="api")
        return container.breakeramp_adapter.destroy(payload, actor=actor)

    # ------------------------------------------------------------------
    # Collaboration
    # ------------------------------------------------------------------
    @app.post("/api/v1/collaboration/workspaces", status_code=status.HTTP_201_CREATED)
    def create_collaboration_workspace(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            request = CreateWorkspaceRequest(
                name=str(payload.get("name") or ""),
                description=str(payload.get("description") or ""),
                owner_id=str(payload.get("owner_id") or ""),
                settings=payload.get("settings"),
                tags=payload.get("tags"),
                is_shared=bool(payload.get("is_shared", False)),
            )
            workspace = container.collaboration_service.create_workspace(request)
            return workspace.to_dict()
        except Exception as exc:  # pylint: disable=broad-except
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/v1/collaboration/workspaces/{workspace_id}")
    def get_collaboration_workspace(workspace_id: str) -> Dict[str, Any]:
        workspace = container.collaboration_service.get_workspace(workspace_id)
        if workspace is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        return workspace.to_dict()

    @app.get("/api/v1/collaboration/workspaces/{workspace_id}/documents")
    def list_collaboration_documents(workspace_id: str) -> List[Dict[str, Any]]:
        documents = container.collaboration_service.get_workspace_documents(workspace_id)
        return [doc.to_dict() for doc in documents]

    @app.post("/api/v1/collaboration/documents", status_code=status.HTTP_201_CREATED)
    def create_collaboration_document(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            request = CreateDocumentRequest(
                workspace_id=str(payload.get("workspace_id") or ""),
                title=str(payload.get("title") or ""),
                content=str(payload.get("content") or ""),
                document_type=str(payload.get("document_type") or "markdown"),
                created_by=str(payload.get("created_by") or ""),
                metadata=payload.get("metadata"),
            )
            document = container.collaboration_service.create_document(request)
            return document.to_dict()
        except Exception as exc:  # pylint: disable=broad-except
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/v1/collaboration/documents/{document_id}")
    def get_collaboration_document(document_id: str) -> Dict[str, Any]:
        document = container.collaboration_service.get_document(document_id)
        if document is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        return document.to_dict()

    @app.get("/api/v1/collaboration/documents/{document_id}/operations")
    def get_collaboration_document_operations(
        document_id: str,
        limit: int = Query(default=100),
    ) -> List[Dict[str, Any]]:
        operations = container.collaboration_service.get_document_operations(document_id, limit=limit)
        return [op.to_dict() for op in operations]

    class _CollaborationHub:
        def __init__(self) -> None:
            self._connections: Dict[str, List[WebSocket]] = {}
            self._doc_locks: Dict[str, asyncio.Lock] = {}

        def _lock_for(self, document_id: str) -> asyncio.Lock:
            if document_id not in self._doc_locks:
                self._doc_locks[document_id] = asyncio.Lock()
            return self._doc_locks[document_id]

        async def connect(self, document_id: str, websocket: WebSocket) -> None:
            await websocket.accept()
            self._connections.setdefault(document_id, []).append(websocket)

        async def disconnect(self, document_id: str, websocket: WebSocket) -> None:
            conns = self._connections.get(document_id)
            if not conns:
                return
            try:
                conns.remove(websocket)
            except ValueError:
                return
            if not conns:
                self._connections.pop(document_id, None)
                self._doc_locks.pop(document_id, None)

        async def broadcast(self, document_id: str, message: Dict[str, Any]) -> None:
            conns = list(self._connections.get(document_id, []))
            for conn in conns:
                try:
                    await conn.send_json(message)
                except Exception:
                    # Best-effort cleanup; actual disconnect handled by receiver loop.
                    pass

    if not hasattr(app.state, "collaboration_hub"):
        app.state.collaboration_hub = _CollaborationHub()

    @app.websocket("/api/v1/collaboration/ws/{document_id}")
    async def collaboration_ws(websocket: WebSocket, document_id: str) -> None:
        hub: _CollaborationHub = app.state.collaboration_hub

        user_id = websocket.query_params.get("user_id") or ""
        requested_session_id = websocket.query_params.get("session_id")
        session_id: Optional[str] = None

        document = container.collaboration_service.get_document(document_id)
        if document is None:
            await websocket.accept()
            await websocket.send_json(
                {"type": "error", "code": "NOT_FOUND", "message": "Document not found"}
            )
            await websocket.close(code=1008)
            return

        await hub.connect(document_id, websocket)
        try:
            session_id = requested_session_id or container.collaboration_service.start_collaboration_session(document_id, user_id)
            await websocket.send_json({"type": "snapshot", "document": document.to_dict()})

            collaborators = container.collaboration_service.get_active_collaborators(document_id)
            for collaborator in collaborators:
                collaborator_user_id = collaborator.get("user_id")
                if not collaborator_user_id or collaborator_user_id == user_id:
                    continue

                await websocket.send_json(
                    {
                        "type": "presence",
                        "user_id": collaborator_user_id,
                        "status": collaborator.get("status", "active"),
                    }
                )

                cursor_position = collaborator.get("cursor_position")
                if cursor_position is not None:
                    await websocket.send_json(
                        {
                            "type": "cursor",
                            "user_id": collaborator_user_id,
                            "position": cursor_position,
                            "selection_end": collaborator.get("selection_end"),
                        }
                    )

            await hub.broadcast(
                document_id,
                {
                    "type": "presence",
                    "user_id": user_id,
                    "status": "active",
                },
            )

            while True:
                message = await websocket.receive_json()
                msg_type = message.get("type")

                if msg_type == "ping":
                    if session_id:
                        container.collaboration_service.touch_collaboration_session(session_id, status="active")
                    await websocket.send_json({"type": "pong"})
                    continue

                if msg_type == "cursor":
                    position = int(message.get("position", 0))
                    selection_end = message.get("selection_end")
                    if session_id:
                        container.collaboration_service.touch_collaboration_session(
                            session_id,
                            cursor_position=position,
                            selection_end=int(selection_end) if selection_end is not None else None,
                            status="active",
                        )
                    await hub.broadcast(
                        document_id,
                        {
                            "type": "cursor",
                            "user_id": user_id,
                            "position": position,
                            "selection_end": selection_end,
                        },
                    )
                    continue

                if msg_type == "presence":
                    status_value = str(message.get("status") or "active")
                    if session_id:
                        container.collaboration_service.touch_collaboration_session(
                            session_id,
                            status=status_value,
                        )
                    await hub.broadcast(
                        document_id,
                        {
                            "type": "presence",
                            "user_id": user_id,
                            "status": status_value,
                        },
                    )
                    continue

                if msg_type != "edit":
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "BAD_REQUEST",
                            "message": "Unsupported message type",
                        }
                    )
                    continue

                op = message.get("operation") or {}
                try:
                    op_type = EditOperationType(str(op.get("operation_type")))
                    base_version = int(op.get("version"))
                    position = int(op.get("position"))
                    content = str(op.get("content") or "")

                    request = RealTimeEditRequest(
                        document_id=document_id,
                        user_id=str(op.get("user_id") or user_id),
                        operation_type=op_type,
                        position=position,
                        content=content,
                        version=base_version,
                        session_id=str(op.get("session_id") or session_id) if (op.get("session_id") or session_id) else None,
                    )
                except Exception as exc:  # pylint: disable=broad-except
                    await websocket.send_json(
                        {"type": "error", "code": "BAD_REQUEST", "message": str(exc)}
                    )
                    continue

                async with hub._lock_for(document_id):
                    try:
                        if session_id:
                            container.collaboration_service.touch_collaboration_session(session_id, status="active")
                        operation = container.collaboration_service.apply_real_time_edit(request)
                        updated = container.collaboration_service.get_document(document_id)
                        await hub.broadcast(
                            document_id,
                            {
                                "type": "operation",
                                "operation": operation.to_dict(),
                                "document": updated.to_dict() if updated else None,
                            },
                        )
                    except VersionConflictError as exc:
                        current = container.collaboration_service.get_document(document_id)
                        await websocket.send_json(
                            {
                                "type": "error",
                                "code": "VERSION_CONFLICT",
                                "message": str(exc),
                                "expected_version": exc.expected_version,
                                "got_version": exc.got_version,
                                "document": current.to_dict() if current else None,
                            }
                        )
                    except Exception as exc:  # pylint: disable=broad-except
                        await websocket.send_json(
                            {"type": "error", "code": "APPLY_FAILED", "message": str(exc)}
                        )
        except WebSocketDisconnect:
            if session_id:
                container.collaboration_service.end_collaboration_session(session_id)
                await hub.broadcast(
                    document_id,
                    {
                        "type": "presence",
                        "user_id": user_id,
                        "status": "disconnected",
                    },
                )
            await hub.disconnect(document_id, websocket)
        except Exception:
            if session_id:
                container.collaboration_service.end_collaboration_session(session_id)
                await hub.broadcast(
                    document_id,
                    {
                        "type": "presence",
                        "user_id": user_id,
                        "status": "disconnected",
                    },
                )
            await hub.disconnect(document_id, websocket)
            raise

    # ------------------------------------------------------------------
    # Work Item Execution Streaming
    # ------------------------------------------------------------------

    if container.execution_service_available:
        @app.get("/api/v1/executions/{run_id}/steps")
        def get_execution_steps(
            run_id: str,
            org_id: Optional[str] = None,
            project_id: Optional[str] = None,
        ) -> Dict[str, Any]:
            """Get execution steps for a run."""
            run_id = _validated_uuid(run_id, "Run")

            try:
                run = container.run_service.get_run(run_id)
                steps = []
                for step in run.steps:
                    step_dict = step.to_dict()
                    metadata = step_dict.get("metadata", {})
                    input_data = metadata.get("input_data", {})
                    if isinstance(input_data, dict):
                        input_tokens = input_data.get("input_tokens", 0)
                        output_tokens = input_data.get("output_tokens", 0)
                        step_type = input_data.get("step_type", step_dict.get("name", "step"))
                        phase = input_data.get("phase", "unknown")
                        content_preview = input_data.get("content_preview")
                    else:
                        input_tokens = metadata.get("input_tokens", 0)
                        output_tokens = metadata.get("output_tokens", 0)
                        step_type = metadata.get("step_type", step_dict.get("name", "step"))
                        phase = metadata.get("phase", "unknown")
                        content_preview = metadata.get("content_preview")

                    tool_calls_data = (
                        input_data.get("tool_calls")
                        if isinstance(input_data, dict)
                        else metadata.get("tool_calls")
                    )
                    if isinstance(tool_calls_data, list):
                        tool_call_count = len(tool_calls_data)
                        tool_names = [
                            tc.get("tool_name")
                            for tc in tool_calls_data
                            if isinstance(tc, dict) and tc.get("tool_name")
                        ]
                    elif isinstance(tool_calls_data, int):
                        tool_call_count = tool_calls_data
                        tool_names = metadata.get("tool_names") or []
                    else:
                        tool_call_count = 0
                        tool_names = metadata.get("tool_names") or []

                    steps.append(
                        {
                            "step_id": step_dict.get("id") or step_dict.get("step_id", ""),
                            "phase": phase,
                            "step_type": step_type,
                            "started_at": step_dict.get("started_at") or step_dict.get("created_at", ""),
                            "completed_at": step_dict.get("completed_at"),
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "tool_calls": tool_call_count,
                            "content_preview": content_preview,
                            "content_full": metadata.get("content_full"),
                            "tool_names": tool_names if tool_names else None,
                            "model_id": metadata.get("model_id"),
                        }
                    )

                steps.sort(key=lambda s: s.get("started_at") or "")
                return {"steps": steps, "total": len(steps)}
            except RunNotFoundError:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run {run_id} not found")
            except Exception as exc:
                logger.exception(f"Error fetching execution steps for run {run_id}")
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

        @app.websocket("/api/v1/executions/ws")
        async def executions_ws(websocket: WebSocket) -> None:
            hub: ExecutionEventHub = app.state.execution_event_hub

            run_id = websocket.query_params.get("run_id")
            org_id = websocket.query_params.get("org_id")
            project_id = websocket.query_params.get("project_id")

            if not run_id and not (org_id and project_id):
                await websocket.accept()
                await websocket.send_json(
                    {
                        "type": "error",
                        "code": "BAD_REQUEST",
                        "message": "Provide run_id or org_id + project_id",
                    }
                )
                await websocket.close(code=1008)
                return

            await hub.connect(websocket, run_id=run_id, org_id=org_id, project_id=project_id)

            try:
                if run_id and container.work_item_execution_service:
                    status = container.work_item_execution_service.get_execution_by_run_id(run_id, org_id)
                    steps = container.work_item_execution_service.get_execution_steps(run_id, org_id)
                    await websocket.send_json(
                        {
                            "type": "execution.snapshot",
                            "payload": {
                                "run_id": run_id,
                                "status": status.to_dict() if status else None,
                                "steps": steps,
                            },
                        }
                    )
                else:
                    await websocket.send_json(
                        {
                            "type": "execution.ready",
                            "payload": {
                                "run_id": run_id,
                                "org_id": org_id,
                                "project_id": project_id,
                            },
                        }
                    )

                while True:
                    message = await websocket.receive_json()
                    if message.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
            except WebSocketDisconnect:
                await hub.disconnect(websocket)
            except Exception:
                await hub.disconnect(websocket)
                raise

    # ------------------------------------------------------------------
    # BCI
    # ------------------------------------------------------------------
    @app.post("/api/v1/bci:retrieve")
    def bci_retrieve(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.retrieve(payload)

    @app.post("/api/v1/bci/retrieve")
    def bci_retrieve_rest(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.retrieve(payload)

    @app.post("/api/v1/bci:retrieveHybrid")
    def bci_retrieve_hybrid(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.retrieve_hybrid(payload)

    @app.post("/api/v1/bci:rebuildIndex")
    def bci_rebuild_index() -> Dict[str, Any]:
        return container.bci_adapter.rebuild_index()

    @app.post("/api/v1/bci/rebuild-index")
    def bci_rebuild_index_rest() -> Dict[str, Any]:
        return container.bci_adapter.rebuild_index()

    @app.post("/api/v1/bci:composePrompt")
    def bci_compose_prompt(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.compose_prompt(payload)

    @app.post("/api/v1/bci/compose-prompt")
    def bci_compose_prompt_rest(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.compose_prompt(payload)

    @app.post("/api/v1/bci:composeBatchPrompts")
    def bci_compose_batch_prompts(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.compose_batch_prompts(payload)

    @app.post("/api/v1/bci:parseCitations")
    def bci_parse_citations(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.parse_citations(payload)

    @app.post("/api/v1/bci:validateCitations")
    def bci_validate_citations(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.validate_citations(payload)

    @app.post("/api/v1/bci/validate-citations")
    def bci_validate_citations_rest(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.validate_citations(payload)

    @app.post("/api/v1/bci:computeTokenSavings")
    def bci_compute_token_savings(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.compute_token_savings(payload)

    @app.post("/api/v1/bci:segmentTrace")
    def bci_segment_trace(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.segment_trace(payload)

    @app.post("/api/v1/bci:detectPatterns")
    def bci_detect_patterns(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.detect_patterns(payload)

    @app.post("/api/v1/bci:scoreReusability")
    def bci_score_reusability(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.score_reusability(payload)

    @app.post("/api/v1/bci:generate")
    def bci_generate(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.generate(payload)

    @app.post("/api/v1/bci/generate")
    def bci_generate_rest(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.generate(payload)

    @app.post("/api/v1/bci:improve")
    def bci_improve(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.improve(payload)

    @app.post("/api/v1/bci/improve")
    def bci_improve_rest(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.bci_adapter.improve(payload)

    # ------------------------------------------------------------------
    # Reflection
    # ------------------------------------------------------------------
    @app.post("/api/v1/reflection:extract")
    def reflection_extract(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.reflection_adapter.extract(payload)

    @app.post("/api/v1/reflection/extract")
    def reflection_extract_rest(payload: Dict[str, Any]) -> Dict[str, Any]:
        return container.reflection_adapter.extract(payload)

    @app.get("/api/v1/reflection/candidates")
    def list_reflection_candidates(
        status_filter: Optional[str] = Query(default=None, alias="status"),
        role: Optional[str] = Query(default=None),
        min_confidence: Optional[float] = Query(default=None),
        limit: int = Query(default=50),
        offset: int = Query(default=0),
    ) -> Dict[str, Any]:
        """List extracted behavior candidates for review.

        Query params:
            status: Filter by status (proposed, approved, rejected, merged)
            role: Filter by role (Student, Teacher, Metacognitive Strategist)
            min_confidence: Filter by minimum confidence score (0.0-1.0)
            limit: Maximum number of results (default: 50)
            offset: Pagination offset (default: 0)

        Returns:
            { candidates: [...], total: int }
        """
        payload: Dict[str, Any] = {"limit": limit, "offset": offset}
        if status_filter:
            payload["status"] = status_filter
        if role:
            payload["role"] = role
        if min_confidence is not None:
            payload["min_confidence"] = min_confidence
        return container.reflection_adapter.list_candidates(payload)

    @app.post("/api/v1/reflection/candidates/approve")
    def reflection_approve_candidate(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Approve an extracted behavior candidate and add to handbook.

        payload: {
            slug: str,              # Candidate slug (e.g., "behavior_validate_inputs")
            status: str,            # "approved" or "auto_approved"
            reviewer_notes?: str,   # Optional notes from reviewer
        }
        """
        return container.reflection_adapter.approve_candidate(payload)

    @app.post("/api/v1/reflection/candidates/reject")
    def reflection_reject_candidate(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Reject an extracted behavior candidate.

        payload: {
            slug: str,        # Candidate slug to reject
            reason?: str,     # Optional rejection reason
        }
        """
        return container.reflection_adapter.reject_candidate(payload)

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------
    @app.post("/api/v1/runs", status_code=status.HTTP_201_CREATED)
    def create_run(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.run_adapter.create_run(payload)
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/v1/runs")
    def list_runs(
        status_filter: Optional[str] = Query(default=None, alias="status"),
        workflow_id: Optional[str] = Query(default=None),
        template_id: Optional[str] = Query(default=None),
        limit: int = Query(default=50),
    ) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {}
        if status_filter:
            payload["status"] = status_filter
        if workflow_id:
            payload["workflow_id"] = workflow_id
        if template_id:
            payload["template_id"] = template_id
        payload["limit"] = limit
        return container.run_adapter.list_runs(payload)

    @app.get("/api/v1/runs/{run_id}")
    def get_run(run_id: str) -> Dict[str, Any]:
        run_id = _validated_uuid(run_id, "Run")
        try:
            return container.run_adapter.get_run(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @app.post("/api/v1/runs/{run_id}/progress")
    def update_run_progress(run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        run_id = _validated_uuid(run_id, "Run")
        try:
            return container.run_adapter.update_run(run_id, payload)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/runs/{run_id}/complete")
    def complete_run(run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        run_id = _validated_uuid(run_id, "Run")
        try:
            return container.run_adapter.complete_run(run_id, payload)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/runs/{run_id}/cancel")
    def cancel_run(run_id: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        run_id = _validated_uuid(run_id, "Run")
        try:
            return container.run_adapter.cancel_run(run_id, payload or {})
        except RunNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.delete("/api/v1/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_run(run_id: str) -> None:
        run_id = _validated_uuid(run_id, "Run")
        try:
            container.run_adapter.delete_run(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @app.patch("/api/v1/runs/{run_id}/status")
    def update_run_status(run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Update only the status of a run (convenience endpoint)."""
        run_id = _validated_uuid(run_id, "Run")
        if "status" not in payload:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing required field: status",
            )
        try:
            return container.run_adapter.update_status(run_id, payload)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/v1/runs/{run_id}/logs")
    async def get_run_logs(
        run_id: str,
        level: Optional[str] = Query(default=None, description="Minimum log level"),
        start_time: Optional[str] = Query(default=None, description="Start time (ISO 8601)"),
        end_time: Optional[str] = Query(default=None, description="End time (ISO 8601)"),
        limit: int = Query(default=100, ge=1, le=1000, description="Max log entries"),
        after: Optional[str] = Query(default=None, description="Cursor for pagination"),
        search: Optional[str] = Query(default=None, description="Full-text search"),
        include_steps: bool = Query(default=True, description="Include run steps"),
    ) -> Dict[str, Any]:
        """Fetch execution logs for a run from Raze logging system."""
        run_id = _validated_uuid(run_id, "Run")
        payload = {
            "level": level,
            "start_time": start_time,
            "end_time": end_time,
            "limit": limit,
            "after": after,
            "search": search,
            "include_steps": include_steps,
        }
        try:
            return await container.run_adapter.fetch_logs(
                run_id, payload, container.raze_service
            )
        except RunNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # Compliance
    # ------------------------------------------------------------------
    @app.post("/api/v1/compliance/checklists", status_code=status.HTTP_201_CREATED)
    def create_checklist(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.compliance_adapter.create_checklist(payload)
        except ComplianceServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/v1/compliance/checklists")
    def list_checklists(
        milestone: Optional[str] = Query(default=None),
        compliance_category: Optional[List[str]] = Query(default=None),
        status_filter: Optional[str] = Query(default=None),
    ) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {}
        if milestone:
            payload["milestone"] = milestone
        if compliance_category:
            payload["compliance_category"] = list(compliance_category)
        if status_filter:
            payload["status_filter"] = status_filter
        return container.compliance_adapter.list_checklists(payload)

    @app.get("/api/v1/compliance/checklists/{checklist_id}")
    def get_checklist(checklist_id: str) -> Dict[str, Any]:
        checklist_id = _validated_uuid(checklist_id, "Checklist")
        try:
            return container.compliance_adapter.get_checklist(checklist_id)
        except ChecklistNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @app.post("/api/v1/compliance/checklists/{checklist_id}/steps", status_code=status.HTTP_201_CREATED)
    def record_step(checklist_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        checklist_id = _validated_uuid(checklist_id, "Checklist")
        payload = dict(payload)
        payload["checklist_id"] = checklist_id
        try:
            return container.compliance_adapter.record_step(payload)
        except ChecklistNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ComplianceServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/compliance/checklists/{checklist_id}:validate")
    def validate_checklist(checklist_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        checklist_id = _validated_uuid(checklist_id, "Checklist")
        payload = dict(payload)
        payload["checklist_id"] = checklist_id
        try:
            return container.compliance_adapter.validate_checklist(payload)
        except ChecklistNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ComplianceServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/compliance/actions/{action_id}:validate")
    def validate_by_action_id(action_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Validate compliance for all checklists related to an action."""
        payload = dict(payload)
        payload["action_id"] = action_id
        try:
            return container.compliance_adapter.validate_by_action_id(payload)
        except ComplianceServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/v1/compliance/policies", status_code=status.HTTP_201_CREATED)
    def create_policy(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new compliance policy."""
        try:
            return container.compliance_adapter.create_policy(payload)
        except ComplianceServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/v1/compliance/policies")
    def list_policies(
        org_id: Optional[str] = Query(default=None),
        project_id: Optional[str] = Query(default=None),
        policy_type: Optional[str] = Query(default=None),
        enforcement_level: Optional[str] = Query(default=None),
        is_active: Optional[bool] = Query(default=None),
        include_global: bool = Query(default=True),
    ) -> List[Dict[str, Any]]:
        """List compliance policies with optional filters."""
        payload: Dict[str, Any] = {"include_global": include_global}
        if org_id:
            payload["org_id"] = org_id
        if project_id:
            payload["project_id"] = project_id
        if policy_type:
            payload["policy_type"] = policy_type
        if enforcement_level:
            payload["enforcement_level"] = enforcement_level
        if is_active is not None:
            payload["is_active"] = is_active
        return container.compliance_adapter.list_policies(payload)

    @app.get("/api/v1/compliance/policies/{policy_id}")
    def get_policy(policy_id: str) -> Dict[str, Any]:
        """Retrieve a single policy by ID."""
        from .compliance_service import PolicyNotFoundError
        policy_id = _validated_uuid(policy_id, "Policy")
        try:
            return container.compliance_adapter.get_policy(policy_id)
        except PolicyNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @app.get("/api/v1/compliance/audit")
    def get_audit_trail(
        run_id: Optional[str] = Query(default=None),
        checklist_id: Optional[str] = Query(default=None),
        action_id: Optional[str] = Query(default=None),
        start_date: Optional[str] = Query(default=None),
        end_date: Optional[str] = Query(default=None),
    ) -> Dict[str, Any]:
        """Generate an audit trail report."""
        payload: Dict[str, Any] = {}
        if run_id:
            payload["run_id"] = run_id
        if checklist_id:
            payload["checklist_id"] = checklist_id
        if action_id:
            payload["action_id"] = action_id
        if start_date:
            payload["start_date"] = start_date
        if end_date:
            payload["end_date"] = end_date
        return container.compliance_adapter.get_audit_trail(payload)

    # ------------------------------------------------------------------
    # Task assignments
    # ------------------------------------------------------------------
    @app.post("/api/v1/tasks:listAssignments")
    def list_task_assignments(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        try:
            return container.task_adapter.list_assignments(payload)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/v1/assignments:suggestAgent")
    def suggest_agent(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return container.assignment_adapter.suggest_agent(payload)
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # pragma: no cover - unexpected failures
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------
    @app.post("/api/v1/analytics:projectKPI")
    def project_kpi(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Project KPI metrics from telemetry events (in-memory)."""
        events = payload.get("events", [])
        include_facts = payload.get("include_facts", True)
        projection: TelemetryProjection = container.telemetry_projector.project(events)
        response: Dict[str, Any] = {
            "summary": projection.summary,
        }
        if include_facts:
            response.update(
                {
                    "fact_behavior_usage": projection.fact_behavior_usage,
                    "fact_token_savings": projection.fact_token_savings,
                    "fact_execution_status": projection.fact_execution_status,
                    "fact_compliance_steps": projection.fact_compliance_steps,
                }
            )
        return response

    @app.get("/api/v1/analytics/kpi-summary")
    def get_kpi_summary(
        start_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        end_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
    ) -> Dict[str, Any]:
        """Query KPI summary from DuckDB warehouse."""
        try:
            records = container.analytics_warehouse.get_kpi_summary(
                start_date=start_date,
                end_date=end_date,
            )
            return {"records": records, "count": len(records)}
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Warehouse query failed: {exc}",
            ) from exc

    @app.get("/api/v1/analytics/behavior-usage")
    def get_behavior_usage(
        start_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        end_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        limit: int = Query(100, description="Maximum number of records", ge=1, le=1000),
    ) -> Dict[str, Any]:
        """Query behavior usage facts from DuckDB warehouse."""
        try:
            records = container.analytics_warehouse.get_behavior_usage(
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )
            return {"records": records, "count": len(records)}
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Warehouse query failed: {exc}",
            ) from exc

    @app.get("/api/v1/analytics/token-savings")
    def get_token_savings(
        start_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        end_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        limit: int = Query(100, description="Maximum number of records", ge=1, le=1000),
    ) -> Dict[str, Any]:
        """Query token savings facts from DuckDB warehouse."""
        try:
            records = container.analytics_warehouse.get_token_savings(
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )
            return {"records": records, "count": len(records)}
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Warehouse query failed: {exc}",
            ) from exc

    @app.get("/api/v1/analytics/compliance-coverage")
    def get_compliance_coverage(
        start_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        end_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        limit: int = Query(100, description="Maximum number of records", ge=1, le=1000),
    ) -> Dict[str, Any]:
        """Query compliance coverage facts from DuckDB warehouse."""
        try:
            records = container.analytics_warehouse.get_compliance_coverage(
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )
            return {"records": records, "count": len(records)}
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Warehouse query failed: {exc}",
            ) from exc

    # ------------------------------------------------------------------
    # Cost Optimization Analytics (PRD 8.17)
    # ------------------------------------------------------------------
    @app.get("/api/v1/analytics/cost-by-service")
    def get_cost_by_service(
        start_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        end_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        service_name: Optional[str] = Query(None, description="Filter by service name"),
    ) -> Dict[str, Any]:
        """Query cost breakdown by service from DuckDB warehouse."""
        try:
            records = container.analytics_warehouse.get_cost_by_service(
                start_date=start_date,
                end_date=end_date,
                service_name=service_name,
            )
            return {"records": records, "count": len(records)}
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Warehouse query failed: {exc}",
            ) from exc

    @app.get("/api/v1/analytics/cost-per-run")
    def get_cost_per_run(
        start_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        end_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        template_id: Optional[str] = Query(None, description="Filter by template ID"),
        limit: int = Query(100, description="Maximum number of records", ge=1, le=1000),
    ) -> Dict[str, Any]:
        """Query cost breakdown per run from DuckDB warehouse."""
        try:
            records = container.analytics_warehouse.get_cost_per_run(
                start_date=start_date,
                end_date=end_date,
                template_id=template_id,
                limit=limit,
            )
            return {"records": records, "count": len(records)}
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Warehouse query failed: {exc}",
            ) from exc

    @app.get("/api/v1/analytics/roi-summary")
    def get_roi_summary() -> Dict[str, Any]:
        """Query ROI analysis summary from DuckDB warehouse."""
        try:
            record = container.analytics_warehouse.get_roi_summary()
            settings = get_settings()
            return {
                "roi": record,
                "budget_threshold_usd": settings.cost.daily_budget_usd,
                "budget_status": "over" if (record or {}).get("total_cost_usd", 0) > settings.cost.daily_budget_usd else "ok",
            }
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Warehouse query failed: {exc}",
            ) from exc

    @app.get("/api/v1/analytics/daily-costs")
    def get_daily_costs(
        start_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        end_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        limit: int = Query(30, description="Maximum number of days", ge=1, le=365),
    ) -> Dict[str, Any]:
        """Query daily cost summary for budget tracking from DuckDB warehouse."""
        try:
            records = container.analytics_warehouse.get_daily_cost_summary(
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )
            settings = get_settings()
            budget = settings.cost.daily_budget_usd
            # Add budget status to each record
            for record in records:
                record["over_budget"] = record.get("daily_cost_usd", 0) > budget
            return {
                "records": records,
                "count": len(records),
                "budget_threshold_usd": budget,
            }
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Warehouse query failed: {exc}",
            ) from exc

    @app.get("/api/v1/analytics/top-expensive")
    def get_top_expensive(
        limit: int = Query(10, description="Number of workflows to return", ge=1, le=100),
    ) -> Dict[str, Any]:
        """Query top expensive workflows from DuckDB warehouse."""
        try:
            records = container.analytics_warehouse.get_top_expensive_workflows(limit=limit)
            return {"records": records, "count": len(records)}
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Warehouse query failed: {exc}",
            ) from exc

    # ------------------------------------------------------------------
    # Metrics (Real-Time Aggregation with Caching)
    # ------------------------------------------------------------------
    @app.get("/api/v1/metrics/summary")
    def get_metrics_summary(
        start_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        end_date: Optional[str] = Query(None, description="ISO format date (YYYY-MM-DD)"),
        use_cache: bool = Query(True, description="Use cached data if available"),
    ) -> Dict[str, Any]:
        """Get real-time metrics summary with PRD KPI targets."""
        try:
            payload: Dict[str, Any] = {"use_cache": use_cache}
            if start_date:
                payload["start_date"] = start_date
            if end_date:
                payload["end_date"] = end_date
            return container.metrics_adapter.get_summary(payload)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Metrics query failed: {exc}",
            ) from exc

    @app.post("/api/v1/metrics/export")
    def export_metrics(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Export metrics data to specified format."""
        try:
            return container.metrics_adapter.export_metrics(payload)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Export failed: {exc}",
            ) from exc

    @app.post("/api/v1/metrics/subscriptions")
    def create_metrics_subscription(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new metrics subscription for real-time streaming."""
        try:
            return container.metrics_adapter.create_subscription(payload)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Subscription creation failed: {exc}",
            ) from exc

    @app.delete("/api/v1/metrics/subscriptions/{subscription_id}")
    def cancel_metrics_subscription(subscription_id: str) -> Dict[str, Any]:
        """Cancel an active metrics subscription."""
        try:
            return container.metrics_adapter.cancel_subscription(subscription_id)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND if "not found" in str(exc).lower() else status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    # ------------------------------------------------------------------
    # AgentAuth
    # ------------------------------------------------------------------
    @app.post("/api/v1/auth/device", status_code=status.HTTP_201_CREATED)
    @app.post("/api/v1/auth/device/authorize", status_code=status.HTTP_201_CREATED)
    def start_device_flow(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Initiate device authorization for CLI or partner surfaces."""

        try:
            # Use PostgreSQL store for shared state if available
            if container.postgres_device_store:
                session = container.postgres_device_store.create_session(
                    client_id=payload["client_id"],
                    scopes=payload["scopes"],
                    surface=payload.get("surface", "CLI"),
                    metadata=payload.get("metadata"),
                )
                verification_uri = os.getenv("AMPREALIZE_DEVICE_VERIFICATION_URI", "https://device.amprealize.dev/activate")
                return {
                    "device_code": session.device_code,
                    "user_code": session.user_code,
                    "verification_uri": verification_uri,
                    "verification_uri_complete": f"{verification_uri}?user_code={session.user_code}",
                    "expires_in": int((session.expires_at - session.created_at).total_seconds()),
                    "interval": session.poll_interval,
                    "status": session.status,
                }

            # Fallback to in-memory manager
            session = container.device_flow_manager.start_authorization(
                client_id=payload["client_id"],
                scopes=payload["scopes"],
                surface=payload.get("surface", "CLI"),
                metadata=payload.get("metadata"),
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing required field: {exc.args[0]}",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        return {
            "device_code": session.device_code,
            "user_code": session.user_code,
            "verification_uri": session.verification_uri,
            "verification_uri_complete": session.verification_uri_complete,
            "expires_in": session.expires_in(),
            "interval": session.poll_interval,
            "status": session.status.value,
        }

    @app.post("/api/v1/auth/device/lookup")
    def lookup_device_flow(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Look up a device authorization request by user code."""

        raw_code = payload.get("user_code")
        if not raw_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="user_code is required",
            )
        try:
            normalized = _normalize_user_code(raw_code)

            # Use PostgreSQL store for shared state if available
            if container.postgres_device_store:
                session = container.postgres_device_store.get_by_user_code(normalized)
                if session is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"No authorization request found for user code: {normalized}",
                    )
                expires_in = int((session.expires_at - datetime.now(timezone.utc)).total_seconds())
                return {
                    "status": session.status,
                    "client_id": session.client_id,
                    "scopes": session.scopes,
                    "surface": session.surface or "CLI",
                    "user_code": session.user_code,
                    "verification_uri": os.getenv("AMPREALIZE_DEVICE_VERIFICATION_URI", "https://device.amprealize.dev/activate"),
                    "expires_in": max(0, expires_in),
                    "created_at": session.created_at.isoformat(),
                }

            # Fallback to in-memory manager
            session = container.device_flow_manager.describe_user_code(normalized)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except UserCodeNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

        return {
            "status": session.status.value,
            "client_id": session.client_id,
            "scopes": session.scopes,
            "surface": session.surface,
            "user_code": session.user_code,
            "verification_uri": session.verification_uri,
            "expires_in": session.expires_in(),
            "created_at": session.created_at.isoformat(),
        }

    @app.post("/api/v1/auth/device/approve")
    def approve_device_flow(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Approve a device authorization request."""

        raw_code = payload.get("user_code")
        approver = payload.get("approver")
        if not raw_code or not approver:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="user_code and approver are required",
            )
        roles = payload.get("roles") or []
        mfa_verified = bool(payload.get("mfa_verified", False))
        surface = payload.get("surface", "WEB")
        try:
            normalized = _normalize_user_code(raw_code)

            # Use PostgreSQL store for shared state if available
            if container.postgres_device_store:
                session = container.postgres_device_store.approve_by_user_code(
                    user_code=normalized,
                    approver=approver,
                    approver_surface=surface,
                )
                if session is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"No pending authorization request found for user code: {normalized}",
                    )

                # Resolve the approver's identity from auth.users so the
                # resulting token maps to a real user. This fixes the bug
                # where oauth_user_id was never set during device approval.
                _resolve_approver_identity(
                    container.postgres_device_store,
                    session.device_code,
                    approver,
                )

                return {
                    "status": session.status,
                    "client_id": session.client_id,
                    "scopes": session.scopes,
                    "approved_at": session.approved_at.isoformat() if session.approved_at else None,
                }

            # Fallback to in-memory manager
            session = container.device_flow_manager.approve_user_code(
                normalized,
                approver,
                approver_surface=surface,
                roles=roles,
                mfa_verified=mfa_verified,
            )
        except (ValueError, DeviceCodeExpiredError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except UserCodeNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except DeviceFlowError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        return {
            "status": session.status.value,
            "client_id": session.client_id,
            "scopes": session.scopes,
            "approved_at": session.approved_at.isoformat() if session.approved_at else None,
        }

    @app.post("/api/v1/auth/device/deny")
    def deny_device_flow(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Deny a device authorization request."""

        raw_code = payload.get("user_code")
        approver = payload.get("approver")
        if not raw_code or not approver:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="user_code and approver are required",
            )
        reason = payload.get("reason")
        surface = payload.get("surface", "WEB")
        try:
            normalized = _normalize_user_code(raw_code)

            # Use PostgreSQL store for shared state if available
            if container.postgres_device_store:
                session = container.postgres_device_store.deny_by_user_code(
                    user_code=normalized,
                    approver=approver,
                    approver_surface=surface,
                    reason=reason,
                )
                if session is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"No pending authorization request found for user code: {normalized}",
                    )
                return {
                    "status": session.status,
                    "client_id": session.client_id,
                    "scopes": session.scopes,
                    "denied_reason": session.denied_reason,
                }

            # Fallback to in-memory manager
            session = container.device_flow_manager.deny_user_code(
                normalized,
                approver,
                approver_surface=surface,
                reason=reason,
            )
        except (ValueError, DeviceCodeExpiredError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except UserCodeNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except DeviceFlowError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        return {
            "status": session.status.value,
            "client_id": session.client_id,
            "scopes": session.scopes,
            "denied_reason": session.denied_reason,
        }

    @app.post("/api/v1/auth/device/token")
    def poll_device_flow(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Poll a device authorization for tokens."""

        device_code = payload.get("device_code")
        if not device_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="device_code is required",
            )
        try:
            # Use PostgreSQL store for shared state if available
            if container.postgres_device_store:
                session = container.postgres_device_store.get_by_device_code(device_code)
                if session is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"No authorization request found for device code",
                    )

                # Per RFC 8628, pending authorization should return 400 with authorization_pending error
                if session.status == "pending":
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={
                            "error": "authorization_pending",
                            "error_description": "The authorization request is still pending.",
                            "interval": session.poll_interval,
                        },
                    )

                if session.status == "denied":
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={
                            "error": "access_denied",
                            "error_description": session.denied_reason or "The user denied the authorization request.",
                        },
                    )

                if session.status == "expired" or (session.expires_at and session.expires_at < datetime.now(timezone.utc)):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={
                            "error": "expired_token",
                            "error_description": "The device code has expired.",
                        },
                    )

                # Only APPROVED status gets here
                if session.access_token is None:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Session approved but tokens not generated",
                    )

                # Calculate expires_in from token expiry
                access_expires_in = 3600  # default 1 hour
                refresh_expires_in = 86400 * 7  # default 7 days
                if session.access_token_expires_at:
                    access_expires_in = int((session.access_token_expires_at - datetime.now(timezone.utc)).total_seconds())
                if session.refresh_token_expires_at:
                    refresh_expires_in = int((session.refresh_token_expires_at - datetime.now(timezone.utc)).total_seconds())

                return {
                    "access_token": session.access_token,
                    "refresh_token": session.refresh_token,
                    "token_type": "Bearer",
                    "expires_in": max(0, access_expires_in),
                    "refresh_expires_in": max(0, refresh_expires_in),
                    "scope": " ".join(session.scopes) if session.scopes else "",
                }

            # Fallback to in-memory manager
            result = container.device_flow_manager.poll_device_code(device_code)
        except DeviceCodeNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

        # Per RFC 8628, pending authorization should return 400 with authorization_pending error
        if result.status is DeviceAuthorizationStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "authorization_pending",
                    "error_description": "The authorization request is still pending.",
                    "interval": result.retry_after or 5,
                },
            )

        if result.status is DeviceAuthorizationStatus.DENIED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "access_denied",
                    "error_description": result.denied_reason or "The user denied the authorization request.",
                },
            )

        if result.status is DeviceAuthorizationStatus.EXPIRED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "expired_token",
                    "error_description": "The device code has expired.",
                },
            )

        # Only APPROVED status gets here
        assert result.tokens is not None
        tokens = result.tokens
        return {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "token_type": tokens.token_type,
            "expires_in": tokens.access_expires_in(),
            "refresh_expires_in": tokens.refresh_expires_in(),
            "scope": " ".join(result.scopes),
        }

    @app.post("/api/v1/auth/device/refresh")
    def refresh_device_flow(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Refresh an access token using a stored refresh token."""

        refresh_token = payload.get("refresh_token")
        if not refresh_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="refresh_token is required",
            )
        try:
            session = container.device_flow_manager.refresh_access_token(refresh_token)
        except RefreshTokenNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except (RefreshTokenExpiredError, DeviceCodeExpiredError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except DeviceFlowError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        tokens = session.tokens
        assert tokens is not None, "refreshed session must include tokens"

        return {
            "status": session.status.value,
            "client_id": session.client_id,
            "scopes": session.scopes,
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "token_type": tokens.token_type,
            "access_token_expires_at": tokens.access_token_expires_at.isoformat(),
            "refresh_token_expires_at": tokens.refresh_token_expires_at.isoformat(),
            "access_expires_in": tokens.access_expires_in(),
            "refresh_expires_in": tokens.refresh_expires_in(),
        }

    @app.post("/api/v1/auth/token/refresh")
    def refresh_token_alias(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Alias for refreshing access tokens (web-console compatibility).

        The web console API client expects `/v1/auth/token/refresh` to return an OAuth-like
        response shape with `expires_in`. Internally this is backed by the device-flow
        refresh token store.
        """

        refresh_token = payload.get("refresh_token")
        if not refresh_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="refresh_token is required",
            )

        try:
            session = container.device_flow_manager.refresh_access_token(refresh_token)
        except RefreshTokenNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except (RefreshTokenExpiredError, DeviceCodeExpiredError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except DeviceFlowError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        tokens = session.tokens
        assert tokens is not None, "refreshed session must include tokens"

        return {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "expires_in": tokens.access_expires_in(),
            "token_type": tokens.token_type,
        }

    @app.get("/api/v1/auth/me")
    def get_current_user(request: Request) -> Dict[str, Any]:
        """Get current user info from the access token."""
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid Authorization header",
            )

        access_token = auth_header[7:]  # Remove "Bearer " prefix

        # Try PostgreSQL store first for shared state
        user_info = None
        if container.postgres_device_store:
            user_info = container.postgres_device_store.get_user_info_from_access_token(access_token)

        # Fallback to in-memory manager
        if user_info is None:
            user_info = container.device_flow_manager.get_user_info_from_access_token(access_token)

        if user_info is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired access token",
            )

        return {
            "sub": user_info.get("sub", ""),
            "name": user_info.get("name", "User"),
            "email": user_info.get("email"),
            "picture": None,
            "roles": ["STUDENT"],  # Default role for device flow auth
            "scopes": user_info.get("scopes", []),
        }

    def _resolve_approver_identity(
        postgres_store,
        device_code: str,
        approver: str,
    ) -> None:
        """Look up the approver in auth.users and populate oauth identity fields.

        Tries to match the approver string against auth.users by id first,
        then by email. If found, updates the device session with the user's
        identity so the resulting token resolves to a real user_id.

        This is a best-effort operation — if the lookup fails, the session
        still works with the approver string as the 'sub' claim.
        """
        import logging
        _logger = logging.getLogger("amprealize.auth.resolve_approver")

        try:
            user_row = None

            def _lookup(conn) -> None:
                nonlocal user_row
                with conn.cursor() as cur:
                    # Try by id first (e.g., "112316240869466547718")
                    cur.execute(
                        "SELECT id, email, display_name FROM auth.users WHERE id = %s",
                        (approver,),
                    )
                    user_row = cur.fetchone()
                    if not user_row:
                        # Try by email (e.g., "nick.sanders.a@gmail.com")
                        cur.execute(
                            "SELECT id, email, display_name FROM auth.users WHERE email = %s",
                            (approver,),
                        )
                        user_row = cur.fetchone()

            if hasattr(postgres_store, '_pool'):
                postgres_store._pool.run_transaction(
                    operation="resolve_approver_identity",
                    service_prefix="auth",
                    actor=approver,
                    metadata={"device_code": device_code},
                    executor=_lookup,
                    telemetry=None,
                )

            if user_row:
                user_id, email, display_name = user_row
                postgres_store.update_oauth_identity(
                    device_code=device_code,
                    oauth_user_id=user_id,
                    oauth_email=email,
                    oauth_display_name=display_name,
                    oauth_provider="device_flow",
                )
                _logger.info(
                    f"Resolved approver identity: approver={approver} -> user_id={user_id}, email={email}"
                )
            else:
                _logger.info(
                    f"Approver '{approver}' not found in auth.users — "
                    f"token will use approver string as sub claim"
                )
        except Exception as e:
            _logger.warning(f"Failed to resolve approver identity: {e}")

    def _require_user_id(request: Request) -> str:
        """Extract authenticated user_id from bearer token."""
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid Authorization header",
            )

        access_token = auth_header[7:]

        # Try PostgreSQL store first for shared state
        user_info = None
        if container.postgres_device_store:
            user_info = container.postgres_device_store.get_user_info_from_access_token(access_token)

        # Fallback to in-memory manager
        if user_info is None:
            user_info = container.device_flow_manager.get_user_info_from_access_token(access_token)

        if user_info is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired access token",
            )

        user_id = user_info.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token subject",
            )
        return str(user_id)

    # ------------------------------------------------------------------
    # Additional Device Flow REST API Endpoints (Integration Test Support)
    # ------------------------------------------------------------------
    @app.post("/api/v1/auth/device/login", status_code=status.HTTP_201_CREATED)
    def device_login_alias(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Alias for /v1/auth/device to support integration test expectations.
        Initiates device authorization flow with client_id and scopes.
        """
        return start_device_flow(payload)

    @app.get("/api/v1/auth/status")
    def get_auth_status(client_id: str = Query("amprealize-staging-client")) -> Dict[str, Any]:
        """
        Check authentication status for a client_id.
        Reads tokens from FileTokenStore and returns validity, expiry, scopes.
        """
        try:
            from .auth_tokens import FileTokenStore

            store = FileTokenStore()
            bundle = store.load()

            if bundle is None or bundle.client_id != client_id:
                return {
                    "is_authenticated": False,
                    "access_token_valid": False,
                    "refresh_token_valid": False,
                    "client_id": client_id,
                    "needs_login": True,
                }

            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            access_token_valid = bundle.expires_at > now
            refresh_token_valid = bundle.refresh_expires_at > now

            return {
                "is_authenticated": access_token_valid or refresh_token_valid,
                "access_token_valid": access_token_valid,
                "refresh_token_valid": refresh_token_valid,
                "client_id": bundle.client_id,
                "scopes": bundle.scopes,
                "expires_in": int((bundle.expires_at - now).total_seconds()),
                "expires_at": bundle.expires_at.isoformat(),
                "refresh_expires_in": int((bundle.refresh_expires_at - now).total_seconds()),
                "refresh_expires_at": bundle.refresh_expires_at.isoformat(),
                "needs_refresh": not access_token_valid and refresh_token_valid,
                "needs_login": not access_token_valid and not refresh_token_valid,
            }

        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to read auth status: {exc}",
            ) from exc

    @app.post("/api/v1/auth/refresh")
    def token_refresh_alias(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Alias for /v1/auth/device/refresh to support integration test expectations.
        Refreshes access token using stored refresh token.
        """
        return refresh_device_flow(payload)

    @app.post("/api/v1/auth/logout")
    def logout_device_flow(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Revoke tokens and clear local storage for a client_id.
        Clears FileTokenStore for the specified client.
        """
        client_id = payload.get("client_id", "amprealize-staging-client")

        try:
            from .auth_tokens import FileTokenStore

            store = FileTokenStore()
            bundle = store.load()

            tokens_cleared = False
            if bundle and bundle.client_id == client_id:
                store.clear()
                tokens_cleared = True

            status_value = "logged_out" if tokens_cleared else "no_tokens"

            return {
                "status": status_value,
                "tokens_cleared": tokens_cleared,
                "client_id": client_id,
                "access_token_revoked": False,  # Remote revocation not implemented
                "refresh_token_revoked": False,
            }

        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to logout: {exc}",
            ) from exc

    # -------------------------------------------------------------------------
    # Internal Authentication Endpoints
    # -------------------------------------------------------------------------

    @app.get("/api/v1/auth/providers")
    def list_auth_providers() -> Dict[str, Any]:
        """
        List available authentication providers.

        Returns information about configured OAuth providers and internal password auth.
        """
        providers = []

        # GitHub OAuth (always available via device flow)
        providers.append({
            "name": "github",
            "type": "oauth",
            "device_flow": True,
            "enabled": True,
            "description": "GitHub OAuth (device flow)",
        })

        # Google OAuth (if configured)
        if container.google_provider is not None:
            providers.append({
                "name": "google",
                "type": "oauth",
                "device_flow": False,
                "enabled": True,
                "description": "Google OAuth",
            })

        # Internal password auth
        providers.append({
            "name": "internal",
            "type": "password",
            "device_flow": False,
            "enabled": True,
            "description": "Internal username/password authentication",
        })

        return {"providers": providers}

    @app.post("/api/v1/auth/internal/register", status_code=status.HTTP_201_CREATED)
    async def internal_register(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Register a new internal auth user and return authentication tokens.

        Request body:
            username (str): Username (min 3 characters)
            password (str): Password (min 8 characters)
            email (str, optional): Email address

        Returns:
            Authentication tokens and user info
        """
        username = payload.get("username")
        password = payload.get("password")
        email = payload.get("email")

        # Validation
        if not username or len(username) < 3:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username must be at least 3 characters",
            )
        if not password or len(password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 8 characters",
            )

        try:
            tokens = await container.device_flow_manager.register_internal_user(
                username=username,
                password=password,
                email=email,
                surface="API",
                metadata={"endpoint": "/api/v1/auth/internal/register"},
            )

            # Calculate expiry times
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)

            return {
                "status": "registered",
                "username": username,
                "provider": "internal",
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
                "token_type": tokens.token_type,
                "expires_in": int((tokens.access_token_expires_at - now).total_seconds()),
                "expires_at": tokens.access_token_expires_at.isoformat(),
                "refresh_expires_in": int((tokens.refresh_token_expires_at - now).total_seconds()),
                "refresh_expires_at": tokens.refresh_token_expires_at.isoformat(),
            }

        except (DeviceFlowError, OAuthError) as exc:
            # Check for duplicate user errors
            error_msg = str(exc).lower()
            if "duplicate" in error_msg or "exists" in error_msg or "already registered" in error_msg:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Username '{username}' already exists",
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Registration failed: {exc}",
            ) from exc

    @app.post("/api/v1/auth/internal/login")
    async def internal_login(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Authenticate with username/password and return tokens.

        Request body:
            username (str): Username
            password (str): Password

        Returns:
            Authentication tokens and user info
        """
        username = payload.get("username")
        password = payload.get("password")

        if not username or not password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username and password required",
            )

        try:
            tokens = await container.device_flow_manager.start_authorization_internal(
                username=username,
                password=password,
                surface="API",
                metadata={"endpoint": "/api/v1/auth/internal/login"},
            )

            # Calculate expiry times
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)

            return {
                "status": "authenticated",
                "username": username,
                "provider": "internal",
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
                "token_type": tokens.token_type,
                "expires_in": int((tokens.access_token_expires_at - now).total_seconds()),
                "expires_at": tokens.access_token_expires_at.isoformat(),
                "refresh_expires_in": int((tokens.refresh_token_expires_at - now).total_seconds()),
                "refresh_expires_at": tokens.refresh_token_expires_at.isoformat(),
            }

        except InvalidCredentialsError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
            ) from exc
        except DeviceFlowError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Authentication failed: {exc}",
            ) from exc

    @app.post("/api/v1/auth/email/send-verification")
    async def send_email_verification(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send an email verification link to the user's email address.

        Request body:
            email (str): Email address to verify
            user_id (str, optional): User ID if known, otherwise lookup by email

        Returns:
            Status message
        """
        email = payload.get("email")
        user_id = payload.get("user_id")

        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email address required",
            )

        try:
            # Get user auth service
            if not container.user_auth_service:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="User service not available",
                )

            # Look up user by email if user_id not provided
            if not user_id:
                user = container.user_auth_service.get_user_by_email(email)
                if not user:
                    # Don't reveal if email exists - return success anyway for security
                    return {"status": "sent", "message": "If the email exists, a verification link has been sent"}
                user_id = user.id
            else:
                user = container.user_auth_service.get_user_by_id(user_id)
                if not user or user.email != email:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="User not found or email mismatch",
                    )

            # Check if already verified
            if user.email_verified:
                return {"status": "already_verified", "message": "Email is already verified"}

            # Create verification token
            token = container.user_auth_service.create_email_verification_token(user_id, email)

            # TODO: Send email with verification link
            # For now, return the token for testing (in production, this would send an email)
            # verification_url = f"{settings.APP_URL}/verify-email?token={token}"
            # await send_email(email, "Verify your email", f"Click here: {verification_url}")

            return {
                "status": "sent",
                "message": "Verification email sent",
                # Include token in dev/test mode only (remove in production)
                "token": token,  # TODO: Remove in production
            }

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to send verification email: {exc}",
            ) from exc

    @app.post("/api/v1/auth/email/verify")
    async def verify_email(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Verify an email address using a verification token.

        Request body:
            token (str): Verification token from email

        Returns:
            Status and user info
        """
        token = payload.get("token")

        if not token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Verification token required",
            )

        try:
            if not container.user_auth_service:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="User service not available",
                )

            result = container.user_auth_service.verify_email_token(token)

            if not result:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid or expired verification token",
                )

            return {
                "status": "verified",
                "message": "Email verified successfully",
                "user_id": result["user_id"],
                "email": result["email"],
            }

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Email verification failed: {exc}",
            ) from exc

    @app.get("/api/v1/auth/email/status")
    async def email_verification_status(
        user_id: str = Query(..., description="User ID to check"),
    ) -> Dict[str, Any]:
        """
        Check email verification status for a user.

        Query params:
            user_id: User ID

        Returns:
            Email verification status

        Note:
            For OAuth users (Google, GitHub), email is verified by the OAuth provider.
            The internal_users table has been deprecated - all users now use auth.users.
        """
        try:
            # First try to get from auth.users table (OAuth users)
            # Try multiple sources for database pool
            pool = getattr(container.org_service, 'pool', None) if hasattr(container, 'org_service') else None

            # If no pool from org_service, try DATABASE_URL directly
            if pool is None:
                database_url = os.environ.get("DATABASE_URL")
                if database_url:
                    try:
                        import psycopg2
                        with psycopg2.connect(database_url) as conn:
                            with conn.cursor() as cur:
                                cur.execute(
                                    "SELECT email, email_verified FROM auth.users WHERE id = %s",
                                    (user_id,)
                                )
                                row = cur.fetchone()
                                if row:
                                    return {
                                        "user_id": user_id,
                                        "email": row[0],
                                        "email_verified": row[1] if row[1] is not None else True,
                                        "verification_pending": False,
                                    }
                    except Exception as e:
                        logger.warning(f"Failed to query auth.users via DATABASE_URL: {e}")
            elif pool:
                try:
                    with pool.connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                "SELECT email, email_verified FROM auth.users WHERE id = %s",
                                (user_id,)
                            )
                            row = cur.fetchone()
                            if row:
                                return {
                                    "user_id": user_id,
                                    "email": row[0],
                                    "email_verified": row[1] if row[1] is not None else True,
                                    "verification_pending": False,
                                }
                except Exception as e:
                    logger.warning(f"Failed to query auth.users via pool: {e}")

            # Fallback: use UserAuthService (replaces deprecated internal_users table)
            if container.user_auth_service:
                user = container.user_auth_service.get_user_by_id(user_id)
                if user:
                    return {
                        "user_id": user_id,
                        "email": user.email,
                        "email_verified": user.email_verified if hasattr(user, 'email_verified') else True,
                        "verification_pending": False,
                    }

            # User not found in either system - return default for OAuth
            # This handles the case where user authenticated via OAuth
            # but isn't in our user tables yet
            return {
                "user_id": user_id,
                "email": None,
                "email_verified": True,  # OAuth provider verified
                "verification_pending": False,
            }

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get verification status: {exc}",
            ) from exc

    # =========================================================================
    # JIT CONSENT ENDPOINTS (Phase 6: Consent UX Dashboard)
    # =========================================================================

    @app.get("/api/v1/consent/{user_code}")
    async def get_consent_request(user_code: str) -> Dict[str, Any]:
        """
        Look up a consent request by user code.

        Used by the consent approval dashboard to display request details.

        Args:
            user_code: User-friendly code (e.g., 'ABCD-1234')

        Returns:
            Consent request details or 404 if not found
        """
        try:
            from .auth.consent_service import get_consent_service
            from .storage.postgres_pool import PostgresPool

            dsn = os.environ.get("AMPREALIZE_CONSENT_PG_DSN") or os.environ.get("AMPREALIZE_PG_DSN")
            if not dsn:
                dsn = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize"

            pool = PostgresPool(dsn)
            consent_service = get_consent_service(pool)

            request = await consent_service.get_by_user_code(user_code)
            if not request:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Consent request not found for code: {user_code}",
                )

            return request.to_dict()

        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"Failed to get consent request: {exc}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get consent request: {exc}",
            ) from exc

    @app.post("/api/v1/consent/{user_code}/approve")
    async def approve_consent_request(
        user_code: str,
        request: Request,
        payload: Dict[str, Any] = Body(default={}),
    ) -> Dict[str, Any]:
        """
        Approve a consent request.

        Requires authentication - the approver must be the user the consent is for.

        Args:
            user_code: User-friendly code (e.g., 'ABCD-1234')
            reason: Optional approval reason

        Returns:
            Success status
        """
        try:
            approver_id = _require_user_id(request)
            reason = payload.get("reason")

            from .auth.consent_service import get_consent_service
            from .storage.postgres_pool import PostgresPool

            dsn = os.environ.get("AMPREALIZE_CONSENT_PG_DSN") or os.environ.get("AMPREALIZE_PG_DSN")
            if not dsn:
                dsn = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize"

            pool = PostgresPool(dsn)
            consent_service = get_consent_service(pool)

            # Verify the request exists and user is authorized
            consent_req = await consent_service.get_by_user_code(user_code)
            if not consent_req:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Consent request not found for code: {user_code}",
                )

            if consent_req.user_id != approver_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cannot approve consent for another user",
                )

            success = await consent_service.approve(
                user_code=user_code,
                approver_id=approver_id,
                reason=reason,
            )

            return {
                "success": success,
                "user_code": user_code,
                "status": "approved" if success else "failed",
            }

        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"Failed to approve consent: {exc}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to approve consent: {exc}",
            ) from exc

    @app.post("/api/v1/consent/{user_code}/deny")
    async def deny_consent_request(
        user_code: str,
        request: Request,
        payload: Dict[str, Any] = Body(default={}),
    ) -> Dict[str, Any]:
        """
        Deny a consent request.

        Requires authentication - the denier must be the user the consent is for.

        Args:
            user_code: User-friendly code (e.g., 'ABCD-1234')
            reason: Optional denial reason

        Returns:
            Success status
        """
        try:
            approver_id = _require_user_id(request)
            reason = payload.get("reason")

            from .auth.consent_service import get_consent_service
            from .storage.postgres_pool import PostgresPool

            dsn = os.environ.get("AMPREALIZE_CONSENT_PG_DSN") or os.environ.get("AMPREALIZE_PG_DSN")
            if not dsn:
                dsn = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize"

            pool = PostgresPool(dsn)
            consent_service = get_consent_service(pool)

            # Verify the request exists and user is authorized
            consent_req = await consent_service.get_by_user_code(user_code)
            if not consent_req:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Consent request not found for code: {user_code}",
                )

            if consent_req.user_id != approver_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cannot deny consent for another user",
                )

            success = await consent_service.deny(
                user_code=user_code,
                approver_id=approver_id,
                reason=reason,
            )

            return {
                "success": success,
                "user_code": user_code,
                "status": "denied" if success else "failed",
            }

        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"Failed to deny consent: {exc}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to deny consent: {exc}",
            ) from exc

    @app.get("/api/v1/consent/{user_code}/status")
    async def poll_consent_status(user_code: str) -> Dict[str, Any]:
        """
        Poll the status of a consent request.

        Used by CLI/MCP clients waiting for user approval.
        Does not require authentication - only the user code is needed.

        Args:
            user_code: User-friendly code (e.g., 'ABCD-1234')

        Returns:
            Current status (pending, approved, denied, expired, not_found)
        """
        try:
            from .auth.consent_service import get_consent_service
            from .storage.postgres_pool import PostgresPool

            dsn = os.environ.get("AMPREALIZE_CONSENT_PG_DSN") or os.environ.get("AMPREALIZE_PG_DSN")
            if not dsn:
                dsn = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize"

            pool = PostgresPool(dsn)
            consent_service = get_consent_service(pool)

            poll_result = await consent_service.poll_status(user_code)
            return poll_result.to_dict()

        except Exception as exc:
            logger.error(f"Failed to poll consent status: {exc}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to poll consent status: {exc}",
            ) from exc

    @app.get("/api/v1/consent/pending")
    async def list_pending_consents(request: Request) -> Dict[str, Any]:
        """
        List pending consent requests for the authenticated user.

        Requires authentication.

        Returns:
            List of pending consent requests
        """
        try:
            user_id = _require_user_id(request)

            from .auth.consent_service import get_consent_service
            from .storage.postgres_pool import PostgresPool

            dsn = os.environ.get("AMPREALIZE_CONSENT_PG_DSN") or os.environ.get("AMPREALIZE_PG_DSN")
            if not dsn:
                dsn = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize"

            pool = PostgresPool(dsn)
            consent_service = get_consent_service(pool)

            requests = await consent_service.list_pending_for_user(user_id)

            return {
                "requests": [r.to_dict() for r in requests],
                "total": len(requests),
            }

        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"Failed to list pending consents: {exc}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to list pending consents: {exc}",
            ) from exc

    # =========================================================================
    # OAUTH SOCIAL LOGIN ENDPOINTS (Web-based Authorization Code Flow)
    # =========================================================================

    @app.get("/api/v1/auth/oauth/{provider}/authorize")
    async def oauth_authorize(
        provider: str,
        redirect_uri: str = Query(..., description="Client callback URL"),
        state: Optional[str] = Query(None, description="CSRF state parameter"),
    ) -> RedirectResponse:
        """
        Redirect to OAuth provider authorization page.

        Supports GitHub and Google OAuth for web-based social login.
        After user authorizes, they are redirected to redirect_uri with code.

        Args:
            provider: OAuth provider (github or google)
            redirect_uri: Where to redirect after authorization
            state: Optional CSRF protection state

        Returns:
            Redirect to OAuth provider authorization URL
        """
        try:
            if provider == "github":
                oauth_provider = container.github_provider
            elif provider == "google":
                oauth_provider = container.google_provider
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unsupported OAuth provider: {provider}. Supported: github, google",
                )

            if oauth_provider is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"OAuth provider '{provider}' is not configured",
                )

            logger.info("Generating auth URL for provider=%s, redirect_uri=%s, state=%s", provider, redirect_uri, state)
            logger.info("Provider instance: %s", oauth_provider)

            auth_url = oauth_provider.get_authorization_url(
                redirect_uri=redirect_uri,
                state=state,
            )

            return RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)

        except NotImplementedError:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail=f"OAuth provider '{provider}' does not support authorization code flow",
            )
        except Exception as exc:
            logger.error("Error in oauth_authorize: %s", exc, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to generate authorization URL: {exc}",
            ) from exc

    @app.post("/api/v1/auth/oauth/callback")
    async def oauth_callback(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Exchange OAuth authorization code for access token.

        Called by web client after user authorizes with OAuth provider.
        Creates an Amprealize session and returns Amprealize tokens that work with
        the standard device flow refresh endpoints.

        Request body:
            code (str): Authorization code from OAuth callback
            state (str, optional): CSRF state to verify
            redirect_uri (str): Same redirect_uri used in authorize request

        Returns:
            access_token, token_type, expires_in, refresh_token, user info
        """
        code = payload.get("code")
        state = payload.get("state")
        redirect_uri = payload.get("redirect_uri")

        if not code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Authorization code required",
            )
        if not redirect_uri:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="redirect_uri required",
            )

        def _parse_oauth_state_provider(raw_state: Optional[str]) -> Optional[str]:
            if not raw_state:
                return None
            if raw_state in ("github", "google"):
                return raw_state
            try:
                padded = raw_state + "=" * (-len(raw_state) % 4)
                decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
                data = json.loads(decoded)
                provider_hint = data.get("provider")
                if provider_hint in ("github", "google"):
                    return provider_hint
            except Exception:
                return None
            return None

        provider_hint = _parse_oauth_state_provider(state)
        provider = None
        token_response = None
        user_info = None
        last_error: Optional[str] = None

        providers_to_try = [provider_hint] if provider_hint else ["github", "google"]
        for try_provider in providers_to_try:
            try:
                if try_provider == "github":
                    oauth_provider = container.github_provider
                else:
                    oauth_provider = container.google_provider

                if oauth_provider is None:
                    last_error = f"OAuth provider '{try_provider}' is not configured."
                    continue

                token_response = await oauth_provider.exchange_code(code, redirect_uri)
                user_info = await oauth_provider.validate_token(token_response.access_token)
                provider = try_provider
                break

            except OAuthError as exc:
                last_error = f"{try_provider} OAuth error: {exc}"
                logger.warning(f"OAuth error for {try_provider}: {exc}")
                continue
            except Exception as exc:
                last_error = f"{try_provider} OAuth exchange failed: {exc}"
                logger.error(f"OAuth exchange failed for {try_provider}: {exc}", exc_info=True)
                continue

        if not token_response or not user_info:
            logger.error(f"OAuth callback failed. Last error: {last_error}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=last_error or "Failed to exchange authorization code. Code may be invalid or expired.",
            )

        # Use OAuth user ID directly - no more internal_users table
        # The user is created in auth.users via the SQL insert below
        internal_user_id = user_info.user_id
        logger.info(f"OAuth user authenticated: {provider}:{user_info.user_id}")

        # Ensure user exists in auth.users for FK constraints (projects, boards, etc.)
        try:
            # Get pool from org_service which has the auth schema connection
            pool = getattr(container.org_service, 'pool', None) if hasattr(container, 'org_service') else None
            if pool:
                with pool.connection() as conn:
                    with conn.cursor() as cur:
                        # Check if user already exists
                        cur.execute("SELECT id FROM auth.users WHERE id = %s", (internal_user_id,))
                        if not cur.fetchone():
                            # Create user record
                            cur.execute("""
                                INSERT INTO auth.users (id, email, display_name, avatar_url, is_active, email_verified)
                                VALUES (%s, %s, %s, %s, true, true)
                                ON CONFLICT (id) DO NOTHING
                            """, (
                                internal_user_id,
                                user_info.email or f"{internal_user_id}@oauth.local",
                                user_info.display_name or user_info.username or "OAuth User",
                                getattr(user_info, "picture", None),
                            ))
                            conn.commit()
                            logger.info(f"Created auth.users record for OAuth user: {internal_user_id}")
                        else:
                            logger.debug(f"User {internal_user_id} already exists in auth.users")
            else:
                logger.warning("No PostgreSQL pool available, skipping user creation")
        except Exception as e:
            logger.error(f"Failed to ensure user exists in auth.users: {e}")

        # Create an Amprealize session from OAuth credentials
        # This bridges OAuth tokens to device flow tokens, enabling standard refresh
        amprealize_tokens = container.device_flow_manager.create_session_from_oauth(
            provider=provider,
            user_id=internal_user_id,  # Use internal user ID if linked
            email=user_info.email,
            name=user_info.display_name or user_info.username,
            picture=getattr(user_info, "picture", None),
            provider_access_token=token_response.access_token,
            provider_refresh_token=token_response.refresh_token,
            scopes=token_response.scope.split() if token_response.scope else None,
        )

        # Return Amprealize tokens (not raw provider tokens) so they work with
        # standard device flow refresh endpoints (/api/v1/auth/device/refresh)
        return {
            "access_token": amprealize_tokens.access_token,
            "token_type": "Bearer",
            "expires_in": int(amprealize_tokens.access_expires_in()),
            "refresh_token": amprealize_tokens.refresh_token,
            "scope": token_response.scope,
            "user": {
                "id": user_info.user_id,
                "email": user_info.email,
                "display_name": user_info.display_name or user_info.username,
                "provider": provider,
            },
        }

    # =========================================================================
    # SERVICE PRINCIPAL (Machine/Agent API Credentials) ENDPOINTS
    # =========================================================================

    @app.post("/api/v1/auth/service-principals", status_code=status.HTTP_201_CREATED)
    def create_service_principal(payload: Dict[str, Any], request: Request) -> Dict[str, Any]:
        """
        Create a new service principal for agent/service API authentication.

        Request body:
            name (str): Display name for the service principal
            description (str, optional): Brief description
            allowed_scopes (list[str], optional): Scopes the principal can request (default: ["read", "write"])
            rate_limit (int, optional): Requests per minute (default: 100)
            role (str, optional): Role for authorization (STRATEGIST|TEACHER|STUDENT|ADMIN|OBSERVER)
            metadata (dict, optional): Additional metadata

        Returns:
            Service principal details including client_id and client_secret (only returned once)
        """
        if not container.service_principal_service:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Service principal management not available",
            )

        name = payload.get("name")
        if not name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="name is required",
            )

        try:
            create_request = CreateServicePrincipalRequest(
                name=name,
                description=payload.get("description"),
                allowed_scopes=payload.get("allowed_scopes", ["read", "write"]),
                rate_limit=payload.get("rate_limit", 100),
                role=payload.get("role", "STUDENT"),
                metadata=payload.get("metadata", {}),
            )
            created_by = payload.get("created_by")
            if not created_by:
                auth_header = request.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    try:
                        created_by = _require_user_id(request)
                    except HTTPException:
                        created_by = None
            response = container.service_principal_service.create(create_request, created_by=created_by)

            result = response.service_principal.to_dict()
            result["client_secret"] = response.client_secret
            return result

        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to create service principal: {exc}",
            ) from exc

    @app.get("/api/v1/auth/service-principals")
    def list_service_principals(
        created_by: Optional[str] = Query(None, description="Filter by creator user ID"),
        is_active: Optional[bool] = Query(None, description="Filter by active status"),
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ) -> Dict[str, Any]:
        """List service principals with optional filtering."""
        if not container.service_principal_service:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Service principal management not available",
            )

        principals = container.service_principal_service.list_all(
            created_by=created_by,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )

        return {
            "items": [sp.to_dict() for sp in principals],
            "count": len(principals),
            "limit": limit,
            "offset": offset,
        }

    @app.get("/api/v1/auth/service-principals/{sp_id}")
    def get_service_principal(sp_id: str) -> Dict[str, Any]:
        """Get a service principal by ID."""
        if not container.service_principal_service:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Service principal management not available",
            )

        sp = container.service_principal_service.get_by_id(sp_id)
        if not sp:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Service principal not found: {sp_id}",
            )

        return sp.to_dict()

    @app.put("/api/v1/auth/service-principals/{sp_id}")
    def update_service_principal(sp_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update a service principal.

        Request body:
            name (str, optional): New display name
            description (str, optional): New description
            allowed_scopes (list[str], optional): New allowed scopes
            rate_limit (int, optional): New rate limit
            role (str, optional): New role
            is_active (bool, optional): Active status
            metadata (dict, optional): New metadata
        """
        if not container.service_principal_service:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Service principal management not available",
            )

        updated = container.service_principal_service.update(
            sp_id,
            name=payload.get("name"),
            description=payload.get("description"),
            allowed_scopes=payload.get("allowed_scopes"),
            rate_limit=payload.get("rate_limit"),
            role=payload.get("role"),
            is_active=payload.get("is_active"),
            metadata=payload.get("metadata"),
        )

        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Service principal not found: {sp_id}",
            )

        return updated.to_dict()

    @app.delete("/api/v1/auth/service-principals/{sp_id}")
    def delete_service_principal(sp_id: str) -> Dict[str, Any]:
        """Delete a service principal permanently."""
        if not container.service_principal_service:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Service principal management not available",
            )

        deleted = container.service_principal_service.delete(sp_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Service principal not found: {sp_id}",
            )

        return {"status": "deleted", "id": sp_id}

    @app.post("/api/v1/auth/service-principals/{sp_id}/deactivate")
    def deactivate_service_principal(sp_id: str) -> Dict[str, Any]:
        """Deactivate a service principal (soft delete)."""
        if not container.service_principal_service:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Service principal management not available",
            )

        deactivated = container.service_principal_service.deactivate(sp_id)
        if not deactivated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Service principal not found: {sp_id}",
            )

        return deactivated.to_dict()

    @app.post("/api/v1/auth/service-principals/{sp_id}/rotate-secret")
    def rotate_service_principal_secret(sp_id: str) -> Dict[str, Any]:
        """
        Rotate the client secret for a service principal.

        Returns the new client_secret (only returned once).
        """
        if not container.service_principal_service:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Service principal management not available",
            )

        new_secret = container.service_principal_service.rotate_secret(sp_id)
        if not new_secret:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Service principal not found: {sp_id}",
            )

        return {
            "status": "rotated",
            "id": sp_id,
            "client_secret": new_secret,
        }

    @app.post("/api/v1/auth/service-principals/authenticate")
    def authenticate_service_principal(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Authenticate a service principal using client credentials.

        This is the OAuth2 client_credentials flow for machine-to-machine auth.

        Request body:
            client_id (str): Service principal client ID
            client_secret (str): Service principal client secret

        Returns:
            Access token and service principal details
        """
        if not container.service_principal_service:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Service principal management not available",
            )

        client_id = payload.get("client_id")
        client_secret = payload.get("client_secret")

        if not client_id or not client_secret:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="client_id and client_secret are required",
            )

        sp = container.service_principal_service.authenticate(client_id, client_secret)
        if not sp:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid client credentials",
            )

        # Create a device session for the SP so the token is stored and
        # validatable by _require_user_id() and the auth middleware.
        # This fixes the bug where SP tokens were random strings that
        # could never be validated (GS2.1).
        access_token_ttl = 3600  # 1 hour
        refresh_token_ttl = 604800  # 7 days

        if container.postgres_device_store:
            # Create a pre-approved session with SP identity
            session = container.postgres_device_store.create_session(
                client_id=client_id,
                scopes=sp.allowed_scopes,
                surface="SERVICE_PRINCIPAL",
                metadata={
                    "sp_id": sp.id,
                    "sp_name": sp.name,
                    "sp_role": sp.role,
                    "auth_method": "client_credentials",
                },
            )
            # Immediately approve with SP identity
            approved = container.postgres_device_store.approve(
                session.device_code,
                approver=sp.id,
                approver_surface="SERVICE_PRINCIPAL",
                access_token_ttl=access_token_ttl,
                refresh_token_ttl=refresh_token_ttl,
            )
            if not approved:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to generate access token for service principal",
                )
            token_subject = sp.created_by or "system"
            # Update the session with identity info so token resolves to a real
            # auth.users principal when the service principal has a creator.
            container.postgres_device_store.update_oauth_identity(
                device_code=session.device_code,
                oauth_user_id=token_subject,
                oauth_username=sp.name,
                oauth_email=f"{sp.client_id}@service-principal.amprealize.local",
                oauth_display_name=sp.name,
                oauth_provider="service_principal",
            )
            access_token = approved.access_token
            refresh_token = approved.refresh_token
        else:
            # Fallback to in-memory device flow manager
            session = container.device_flow_manager.create_session(
                client_id=client_id,
                scopes=sp.allowed_scopes,
            )
            container.device_flow_manager.approve_user_code(
                session.user_code,
                approver=sp.created_by or "system",
                approver_surface="SERVICE_PRINCIPAL",
            )
            access_token = session.access_token
            refresh_token = getattr(session, 'refresh_token', None)

        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": access_token_ttl,
            "scope": " ".join(sp.allowed_scopes),
            "service_principal": {
                "id": sp.id,
                "name": sp.name,
                "role": sp.role,
            },
        }

    # =========================================================================
    # MFA (Multi-Factor Authentication) ENDPOINTS
    # =========================================================================

    @app.post("/api/v1/auth/mfa/setup")
    async def mfa_setup(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Start MFA setup by generating a TOTP secret and QR code.

        Request body:
            user_id (str): User ID
            device_name (str, optional): Friendly name for the device

        Returns:
            QR code and secret for authenticator app setup
        """
        user_id = payload.get("user_id")
        device_name = payload.get("device_name", "Authenticator App")

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User ID required",
            )

        try:
            from amprealize.auth.mfa_service import MfaService
            import os

            if not container.user_auth_service:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="User service not available",
                )

            # Get user
            user = container.user_auth_service.get_user_by_id(user_id)
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found",
                )

            # Get or create MFA encryption key
            mfa_key = os.environ.get("MFA_ENCRYPTION_KEY")
            if not mfa_key:
                # Generate a key for development (should be set in production)
                mfa_key = MfaService.generate_encryption_key()
                os.environ["MFA_ENCRYPTION_KEY"] = mfa_key

            mfa_service = MfaService(mfa_key)

            # Generate new secret
            secret = mfa_service.generate_secret()
            encrypted_secret = mfa_service.encrypt_secret(secret)

            # Create MFA device record (unverified)
            device_id = container.user_auth_service.create_mfa_device(
                user_id=user_id,
                secret_encrypted=encrypted_secret,
                device_type="totp",
                device_name=device_name,
            )

            # Generate QR code
            qr_code_base64 = mfa_service.generate_qr_code_base64(
                secret=secret,
                username=user.email or user.username,
                issuer="Amprealize",
            )

            # Generate backup codes
            backup_codes = mfa_service.generate_backup_codes()
            encrypted_backup_codes = mfa_service.encrypt_backup_codes(backup_codes)

            return {
                "status": "pending_verification",
                "device_id": device_id,
                "device_name": device_name,
                "secret": secret,  # Show once for manual entry
                "qr_code": f"data:image/png;base64,{qr_code_base64}",
                "backup_codes": backup_codes,  # Show once, store encrypted
                "provisioning_uri": mfa_service.get_provisioning_uri(
                    secret, user.email or user.username, "Amprealize"
                ),
                "instructions": "Scan the QR code with your authenticator app, then verify with a code",
            }

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"MFA setup failed: {exc}",
            ) from exc

    @app.post("/api/v1/auth/mfa/verify-setup")
    async def mfa_verify_setup(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Verify MFA setup by confirming a TOTP code.

        Request body:
            device_id (str): MFA device ID from setup
            code (str): 6-digit code from authenticator app
            user_id (str): User ID

        Returns:
            Verification status
        """
        device_id = payload.get("device_id")
        code = payload.get("code")
        user_id = payload.get("user_id")

        if not all([device_id, code, user_id]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="device_id, code, and user_id required",
            )

        try:
            from amprealize.auth.mfa_service import MfaService
            import os

            if not container.user_auth_service:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="User service not available",
                )

            mfa_key = os.environ.get("MFA_ENCRYPTION_KEY")
            if not mfa_key:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="MFA not configured",
                )

            mfa_service = MfaService(mfa_key)

            # Get encrypted secret from database
            # Note: We need to get all devices including unverified for setup verification
            devices = container.user_auth_service.get_user_mfa_devices(user_id, verified_only=False)
            device = next((d for d in devices if d["id"] == device_id), None)

            if not device:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="MFA device not found",
                )

            if device.get("is_verified"):
                return {
                    "status": "already_verified",
                    "device_id": device_id,
                }

            # Get the secret (need to query separately as it's not in the safe dict)
            encrypted_secret = user_service.get_mfa_device_secret(device_id, user_id)
            if not encrypted_secret:
                # Unverified devices need a different query
                with user_service._connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT secret_encrypted FROM mfa_devices WHERE id = %s AND user_id = %s",
                            (device_id, user_id),
                        )
                        row = cur.fetchone()
                        encrypted_secret = row[0] if row else None

            if not encrypted_secret:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="MFA device secret not found",
                )

            # Decrypt and verify
            secret = mfa_service.decrypt_secret(encrypted_secret)
            if not mfa_service.verify_code(secret, code):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid verification code",
                )

            # Mark device as verified
            user_service.verify_mfa_device(device_id)

            # Set as primary if it's the first verified device
            existing_devices = user_service.get_user_mfa_devices(user_id, verified_only=True)
            if len(existing_devices) <= 1:  # Just this one
                user_service.set_primary_mfa_device(user_id, device_id)

            return {
                "status": "verified",
                "device_id": device_id,
                "is_primary": len(existing_devices) <= 1,
                "message": "MFA device verified and activated",
            }

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"MFA verification failed: {exc}",
            ) from exc

    @app.post("/api/v1/auth/mfa/verify")
    async def mfa_verify(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Verify an MFA code during login.

        Request body:
            user_id (str): User ID
            code (str): 6-digit TOTP code or backup code

        Returns:
            Verification result
        """
        user_id = payload.get("user_id")
        code = payload.get("code")

        if not all([user_id, code]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="user_id and code required",
            )

        try:
            from amprealize.auth.mfa_service import MfaService
            import os

            if not container.user_auth_service:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="User service not available",
                )

            mfa_key = os.environ.get("MFA_ENCRYPTION_KEY")
            if not mfa_key:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="MFA not configured",
                )

            mfa_service = MfaService(mfa_key)

            # Get user's verified MFA devices
            devices = container.user_auth_service.get_user_mfa_devices(user_id, verified_only=True)

            if not devices:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No MFA devices configured for this user",
                )

            # Try TOTP verification on each device
            for device in devices:
                if device["device_type"] == "totp":
                    encrypted_secret = user_service.get_mfa_device_secret(device["id"], user_id)
                    if encrypted_secret:
                        secret = mfa_service.decrypt_secret(encrypted_secret)
                        if mfa_service.verify_code(secret, code):
                            user_service.update_mfa_device_last_used(device["id"])
                            return {
                                "status": "verified",
                                "method": "totp",
                                "device_id": device["id"],
                            }

            # If TOTP failed, could be a backup code (implement if needed)
            # For now, just return failure
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid MFA code",
            )

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"MFA verification failed: {exc}",
            ) from exc

    @app.get("/api/v1/auth/mfa/devices")
    async def list_mfa_devices(
        user_id: str = Query(..., description="User ID"),
    ) -> Dict[str, Any]:
        """
        List MFA devices for a user.

        Query params:
            user_id: User ID

        Returns:
            List of MFA devices (secrets excluded)
        """
        try:
            if not container.user_auth_service:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="User service not available",
                )

            devices = container.user_auth_service.get_user_mfa_devices(user_id, verified_only=True)

            return {
                "user_id": user_id,
                "devices": devices,
                "has_mfa": len(devices) > 0,
            }

        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to list MFA devices: {exc}",
            ) from exc

    @app.delete("/api/v1/auth/mfa/devices/{device_id}")
    async def delete_mfa_device(
        device_id: str,
        user_id: str = Query(..., description="User ID"),
    ) -> Dict[str, Any]:
        """
        Delete an MFA device.

        Path params:
            device_id: MFA device ID

        Query params:
            user_id: User ID (for verification)

        Returns:
            Deletion status
        """
        try:
            if not container.user_auth_service:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="User service not available",
                )

            # Check if this is the only MFA device
            devices = container.user_auth_service.get_user_mfa_devices(user_id, verified_only=True)
            if len(devices) <= 1:
                # Allow deletion but warn that MFA will be disabled
                pass

            deleted = container.user_auth_service.delete_mfa_device(device_id, user_id)

            if not deleted:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="MFA device not found",
                )

            remaining_devices = container.user_auth_service.get_user_mfa_devices(user_id, verified_only=True)

            return {
                "status": "deleted",
                "device_id": device_id,
                "mfa_still_enabled": len(remaining_devices) > 0,
                "remaining_devices": len(remaining_devices),
            }

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete MFA device: {exc}",
            ) from exc

    @app.get("/api/v1/auth/mfa/status")
    async def mfa_status(
        user_id: str = Query(..., description="User ID"),
    ) -> Dict[str, Any]:
        """
        Check MFA status for a user.

        Query params:
            user_id: User ID

        Returns:
            MFA configuration status
        """
        try:
            if not container.user_auth_service:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="User service not available",
                )

            has_mfa = container.user_auth_service.user_has_verified_mfa(user_id)
            devices = container.user_auth_service.get_user_mfa_devices(user_id, verified_only=True)

            return {
                "user_id": user_id,
                "mfa_enabled": has_mfa,
                "device_count": len(devices),
                "primary_device": next(
                    (d for d in devices if d.get("is_primary")), None
                ),
            }

        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get MFA status: {exc}",
            ) from exc

    # ===== IDENTITY LINKING ENDPOINTS =====

    @app.post("/api/v1/auth/identity/link")
    async def link_oauth_identity(
        provider: str = Body(..., description="OAuth provider (github, google)"),
        oauth_access_token: str = Body(..., description="OAuth access token"),
        oauth_refresh_token: Optional[str] = Body(None, description="OAuth refresh token"),
        password_confirmation: Optional[str] = Body(None, description="Password for manual linking"),
        target_user_id: Optional[str] = Body(None, description="User ID to link to (for manual linking)"),
    ) -> Dict[str, Any]:
        """
        Link an OAuth identity to an internal user account.

        This endpoint handles:
        1. Auto-linking for new users (creates account)
        2. Auto-linking when OAuth email matches existing verified user
        3. Manual linking with password confirmation (for security)

        Returns:
            Linking result with user and identity info
        """
        # DEPRECATED: Identity linking has been simplified.
        # OAuth users are now automatically created in auth.users during OAuth callback.
        # This endpoint is kept for backwards compatibility but returns a simple response.
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Identity linking has been deprecated. OAuth users are automatically linked during login.",
        )

    @app.post("/api/v1/auth/identity/unlink")
    async def unlink_oauth_identity(
        user_id: str = Body(..., description="User ID"),
        provider: str = Body(..., description="OAuth provider to unlink (github, google)"),
        password_confirmation: str = Body(..., description="Password to confirm unlinking"),
    ) -> Dict[str, Any]:
        """
        Unlink an OAuth identity from a user account.

        Requires password confirmation for security.
        Cannot unlink the last authentication method without setting a password.

        Returns:
            Unlinking result
        """
        # DEPRECATED: Identity unlinking has been deprecated with the removal of internal_users.
        # OAuth is now the primary authentication method.
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Identity unlinking has been deprecated. OAuth is the primary authentication method.",
        )

    @app.get("/api/v1/auth/identity/providers")
    async def list_linked_providers(
        user_id: str = Query(..., description="User ID"),
    ) -> Dict[str, Any]:
        """
        List all OAuth providers linked to a user account.

        Returns:
            List of linked OAuth identities
        """
        # DEPRECATED: Identity linking has been deprecated.
        # OAuth is now the primary authentication method.
        # Users are stored in auth.users with their OAuth provider ID.
        try:
            if not container.user_auth_service:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="User service not available",
                )

            user = container.user_auth_service.get_user_by_id(user_id)
            if not user:
                # Return empty list for unknown users (OAuth users may not be in auth.users yet)
                return {
                    "user_id": user_id,
                    "has_password": False,
                    "linked_providers": [],
                    "provider_count": 0,
                    "message": "OAuth is the primary authentication method. User profiles are stored in auth.users.",
                }

            return {
                "user_id": user_id,
                "has_password": False,  # Passwords deprecated
                "linked_providers": [],  # Identity linking deprecated
                "provider_count": 0,
                "email": user.email,
                "message": "OAuth is the primary authentication method. Identity linking has been deprecated.",
            }

        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to list providers: {exc}",
            ) from exc

    @app.get("/api/v1/telemetry/events")
    def get_telemetry_events(
        event_type: Optional[str] = Query(None),
        since: Optional[str] = Query(None),
        until: Optional[str] = Query(None),
        run_id: Optional[str] = Query(None),
        session_id: Optional[str] = Query(None),
        actor_surface: Optional[str] = Query(None),
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ) -> Dict[str, Any]:
        """
        Query telemetry events with filtering and pagination.

        Part of E4 — Learning Loop, Analytics, and Governance (AMPREALIZE-278 / T4.1.3).
        """
        from amprealize.storage.postgres_telemetry import PostgresTelemetrySink

        telemetry_dsn = resolve_optional_postgres_dsn(
            service="TELEMETRY",
            explicit_dsn=None,
            env_var="AMPREALIZE_TELEMETRY_PG_DSN",
        )
        if not telemetry_dsn:
            return {
                "events": [],
                "count": 0,
                "message": "Telemetry query requires PostgreSQL (set AMPREALIZE_TELEMETRY_PG_DSN)",
                "filters": {"event_type": event_type, "since": since, "limit": limit},
            }

        try:
            sink = PostgresTelemetrySink(dsn=telemetry_dsn)
            events = sink.query_events(
                event_type=event_type,
                since=since,
                until=until,
                run_id=run_id,
                session_id=session_id,
                actor_surface=actor_surface,
                limit=limit,
                offset=offset,
            )
            return {"events": events, "count": len(events)}
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Telemetry query failed: {exc}",
            ) from exc

    def _pg_session_to_auth_session(pg_session) -> DeviceAuthorizationSession:
        """Convert a PostgreSQL DeviceSession to DeviceAuthorizationSession for rendering."""
        tokens = None
        if pg_session.access_token and pg_session.access_token_expires_at:
            tokens = DeviceTokens(
                access_token=pg_session.access_token,
                refresh_token=pg_session.refresh_token or "",
                access_token_expires_at=pg_session.access_token_expires_at,
                refresh_token_expires_at=pg_session.refresh_token_expires_at or pg_session.access_token_expires_at,
            )
        return DeviceAuthorizationSession(
            device_code=pg_session.device_code,
            user_code=pg_session.user_code,
            client_id=pg_session.client_id,
            scopes=pg_session.scopes if isinstance(pg_session.scopes, list) else [pg_session.scopes],
            surface=pg_session.surface,
            verification_uri="",
            verification_uri_complete="",
            created_at=pg_session.created_at,
            expires_at=pg_session.expires_at,
            poll_interval=pg_session.poll_interval,
            metadata=pg_session.metadata or {},
            status=DeviceAuthorizationStatus(pg_session.status),
            tokens=tokens,
            approver=pg_session.approver,
            approved_at=pg_session.approved_at,
        )

    @app.get("/device/activate", response_class=HTMLResponse)
    def show_device_activation_form(user_code: Optional[str] = None) -> HTMLResponse:
        normalized = ""
        session: Optional[DeviceAuthorizationSession] = None
        error: Optional[str] = None

        if user_code:
            try:
                normalized = _normalize_user_code(user_code)
                # Check PostgreSQL store first
                if container.postgres_device_store:
                    pg_session = container.postgres_device_store.get_by_user_code(normalized)
                    if pg_session:
                        session = _pg_session_to_auth_session(pg_session)
                if session is None and not error:
                    # Fall back to in-memory device flow manager
                    try:
                        session = container.device_flow_manager.describe_user_code(normalized)
                    except Exception:
                        pass
                if session is None and not error:
                    error = "No consent request found for that code."
            except ValueError as exc:
                error = str(exc)
                normalized = user_code
            except UserCodeNotFoundError:
                error = "No consent request found for that code."
                normalized = user_code

        return _render_device_activation_page(
            user_code=normalized or (user_code or ""),
            session=session,
            error=error,
        )

    # Backwards-compatible aliases for device activation.
    # Some clients/proxies expect a versioned `/v1/device/authorize` path.
    @app.get("/api/v1/device/authorize", response_class=HTMLResponse)
    def show_device_activation_form_v1(user_code: Optional[str] = None) -> HTMLResponse:
        return show_device_activation_form(user_code=user_code)

    @app.post("/device/activate", response_class=HTMLResponse)
    def submit_device_activation(
        user_code: str = Form(...),
        action: str = Form(...),
        approver: str = Form("web-reviewer"),
        roles: Optional[str] = Form(None),
        reason: Optional[str] = Form(None),
        mfa_verified: Optional[str] = Form(None),
    ) -> HTMLResponse:
        try:
            normalized = _normalize_user_code(user_code)
        except ValueError as exc:
            return _render_device_activation_page(user_code=user_code, error=str(exc))

        action_key = action.lower().strip()
        roles_value = roles or "STRATEGIST"
        role_list = [role.strip() for role in roles_value.split(",") if role.strip()]
        mfa_flag = bool(mfa_verified)

        session: Optional[DeviceAuthorizationSession] = None
        message: Optional[str] = None
        error: Optional[str] = None

        try:
            if container.postgres_device_store:
                # Use PostgreSQL store for shared state
                if action_key == "lookup":
                    pg_session = container.postgres_device_store.get_by_user_code(normalized)
                    if pg_session:
                        session = _pg_session_to_auth_session(pg_session)
                        message = "Consent request loaded."
                    else:
                        error = "No consent request found for that code."
                elif action_key == "approve":
                    pg_session = container.postgres_device_store.approve_by_user_code(
                        normalized,
                        approver=approver,
                        approver_surface="WEB",
                    )
                    if pg_session:
                        _resolve_approver_identity(
                            container.postgres_device_store,
                            pg_session.device_code,
                            approver,
                        )
                        session = _pg_session_to_auth_session(pg_session)
                        message = "Consent approved successfully."
                    else:
                        error = "No consent request found for that code."
                elif action_key == "deny":
                    pg_session = container.postgres_device_store.deny_by_user_code(
                        normalized,
                        approver=approver,
                        approver_surface="WEB",
                        reason=reason,
                    )
                    if pg_session:
                        session = _pg_session_to_auth_session(pg_session)
                        message = "Consent request denied."
                    else:
                        error = "No consent request found for that code."
                else:
                    session = None
                    error = "Unsupported action requested."
            else:
                # Fallback to in-memory manager
                if action_key == "lookup":
                    session = container.device_flow_manager.describe_user_code(normalized)
                    message = "Consent request loaded."
                elif action_key == "approve":
                    session = container.device_flow_manager.approve_user_code(
                        normalized,
                        approver,
                        approver_surface="WEB",
                        roles=role_list,
                        mfa_verified=mfa_flag,
                    )
                    message = "Consent approved successfully."
                elif action_key == "deny":
                    session = container.device_flow_manager.deny_user_code(
                        normalized,
                        approver,
                        approver_surface="WEB",
                        reason=reason,
                    )
                    message = "Consent request denied."
                else:
                    session = None
                    error = "Unsupported action requested."
        except UserCodeNotFoundError:
            session = None
            error = "No consent request found for that code."
        except DeviceCodeExpiredError as exc:
            session = None
            error = str(exc)
        except DeviceFlowError as exc:
            session = None
            error = str(exc)

        return _render_device_activation_page(
            user_code=normalized,
            session=session,
            message=message,
            error=error,
        )

    @app.post("/api/v1/device/authorize", response_class=HTMLResponse)
    def submit_device_activation_v1(
        user_code: str = Form(...),
        action: str = Form(...),
        approver: str = Form("web-reviewer"),
        roles: Optional[str] = Form(None),
        reason: Optional[str] = Form(None),
        mfa_verified: Optional[str] = Form(None),
    ) -> HTMLResponse:
        return submit_device_activation(
            user_code=user_code,
            action=action,
            approver=approver,
            roles=roles,
            reason=reason,
            mfa_verified=mfa_verified,
        )

    @app.get("/api/v1/activate")
    def activate_redirect(user_code: Optional[str] = None) -> Response:
        target = "/api/v1/device/authorize"
        if user_code:
            target = f"{target}?user_code={user_code}"
        return RedirectResponse(url=target, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    @app.get("/favicon.ico")
    def favicon() -> Response:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/api/v1/auth/grants")
    def ensure_grant(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Request an authorization grant for a tool and scopes."""
        try:
            return container.agent_auth_adapter.ensure_grant(payload)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Grant request failed: {exc}",
            ) from exc

    @app.get("/api/v1/auth/grants")
    def list_grants(
        agent_id: str = Query(..., description="Agent ID"),
        user_id: Optional[str] = Query(None),
        tool_name: Optional[str] = Query(None),
        include_expired: bool = Query(False),
    ) -> List[Dict[str, Any]]:
        """List authorization grants for an agent."""
        try:
            filters = {
                "agent_id": agent_id,
                "include_expired": include_expired,
            }
            if user_id:
                filters["user_id"] = user_id
            if tool_name:
                filters["tool_name"] = tool_name
            return container.agent_auth_adapter.list_grants(filters)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to list grants: {exc}",
            ) from exc

    @app.post("/api/v1/auth/policy-preview")
    def policy_preview(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Preview policy evaluation without creating a grant."""
        try:
            return container.agent_auth_adapter.policy_preview(payload)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Policy preview failed: {exc}",
            ) from exc

    @app.delete("/api/v1/auth/grants/{grant_id}")
    def revoke_grant(
        grant_id: str,
        revoked_by: str = Query(..., description="ID of user/system revoking grant"),
        reason: Optional[str] = Query(None, description="Reason for revocation"),
    ) -> Dict[str, Any]:
        """Revoke a specific authorization grant."""
        try:
            payload = {"revoked_by": revoked_by}
            if reason:
                payload["reason"] = reason
            return container.agent_auth_adapter.revoke_grant(grant_id, payload)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND if "not found" in str(exc).lower() else status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    # ------------------------------------------------------------------
    # Security
    # ------------------------------------------------------------------
    @app.post("/api/v1/security/scan-secrets", status_code=status.HTTP_200_OK)
    def scan_secrets(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Run gitleaks secret scan and return findings.

        Request body:
            paths (list[str], optional): Paths to scan (default: ["."])
            redact (bool, optional): Redact secrets in output (default: true)
            report_format (str, optional): Output format - "json" or "table" (default: "json")
            fail_on_findings (bool, optional): Return error status if secrets found (default: false)
            audit_archive_path (str, optional): Path to archive scan results

        Returns:
            Dictionary with:
            - scan_id: Unique identifier for this scan
            - status: "PASSED" or "FAILED"
            - findings_count: Number of potential secrets found
            - findings: List of finding objects (if any)
            - started_at: ISO timestamp of scan start
            - finished_at: ISO timestamp of scan completion
            - report_path: Path to saved report (if audit_archive_path provided)
        """
        import subprocess
        import tempfile
        from datetime import datetime, timezone

        scan_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc).isoformat()

        paths = payload.get("paths", ["."])
        redact = payload.get("redact", True)
        fail_on_findings = payload.get("fail_on_findings", False)
        audit_archive_path = payload.get("audit_archive_path")

        # Create temp file for report
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp:
            report_path = Path(tmp.name)

        try:
            # Build gitleaks command
            cmd = [
                "pre-commit", "run", "gitleaks", "--all-files",
                "--hook-stage", "manual", "--",
                "--report-format", "json",
                "--report-path", str(report_path),
            ]
            if redact:
                cmd.append("--redact")

            # Add paths if specified
            for path in paths:
                cmd.extend(["--", path])

            # Run scan
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,  # 2 minute timeout
            )

            # Parse findings
            findings: List[Dict[str, Any]] = []
            if report_path.exists():
                raw = report_path.read_text(encoding="utf-8")
                if raw.strip():
                    try:
                        data = json.loads(raw)
                        if isinstance(data, list):
                            findings = data
                        elif isinstance(data, dict) and "findings" in data:
                            findings = data.get("findings", [])
                    except json.JSONDecodeError:
                        pass

            finished_at = datetime.now(timezone.utc).isoformat()
            scan_status = "FAILED" if findings else "PASSED"

            # Archive report if requested
            saved_report_path = None
            if audit_archive_path:
                archive_dir = Path(audit_archive_path).expanduser().resolve()
                archive_dir.mkdir(parents=True, exist_ok=True)
                saved_report = archive_dir / f"scan_{scan_id}.json"
                saved_report.write_text(json.dumps({
                    "scan_id": scan_id,
                    "status": scan_status,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "findings": findings,
                }, indent=2))
                saved_report_path = str(saved_report)

            response = {
                "scan_id": scan_id,
                "status": scan_status,
                "findings_count": len(findings),
                "findings": findings,
                "started_at": started_at,
                "finished_at": finished_at,
                "report_path": saved_report_path,
            }

            if fail_on_findings and findings:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "message": f"Secret scan found {len(findings)} potential secret(s)",
                        **response,
                    },
                )

            return response

        except subprocess.TimeoutExpired:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Secret scan timed out after 120 seconds",
            )
        except FileNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="pre-commit or gitleaks not installed. Run: pip install pre-commit && pre-commit install",
            )
        finally:
            # Cleanup temp file
            if report_path.exists():
                report_path.unlink(missing_ok=True)

    @app.get("/api/v1/security/scan-secrets/history")
    def get_scan_history(
        limit: int = Query(default=10, ge=1, le=100),
        archive_path: str = Query(default="security/scan_reports"),
    ) -> Dict[str, Any]:
        """Get history of past secret scans from archive.

        Query parameters:
            limit: Maximum number of scans to return (default: 10, max: 100)
            archive_path: Path to scan archive directory

        Returns:
            Dictionary with list of past scan summaries.
        """
        archive_dir = Path(archive_path).expanduser().resolve()
        scans: List[Dict[str, Any]] = []

        if archive_dir.exists():
            scan_files = sorted(
                archive_dir.glob("scan_*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:limit]

            for scan_file in scan_files:
                try:
                    data = json.loads(scan_file.read_text())
                    scans.append({
                        "scan_id": data.get("scan_id"),
                        "status": data.get("status"),
                        "findings_count": len(data.get("findings", [])),
                        "started_at": data.get("started_at"),
                        "finished_at": data.get("finished_at"),
                        "report_file": scan_file.name,
                    })
                except (json.JSONDecodeError, KeyError):
                    continue

        return {
            "scans": scans,
            "total": len(scans),
            "archive_path": str(archive_dir),
        }

    # ------------------------------------------------------------------
    # Raze Structured Logging
    # ------------------------------------------------------------------
    if RAZE_AVAILABLE and container.raze_service is not None:
        # Add Raze log routes at /api/v1/logs/*
        log_routes = create_log_routes(container.raze_service, tags=["logs"])
        app.include_router(log_routes, prefix="/api")

        # Optionally add middleware for automatic request logging
        # Disabled by default to avoid noise; enable via env var
        if os.getenv("RAZE_ENABLE_MIDDLEWARE", "").lower() in ("true", "1", "yes"):
            app.add_middleware(
                RazeMiddleware,
                service=container.raze_service,
                service_name="amprealize-api",
                exclude_paths={"/health", "/metrics", "/api/v1/logs/ingest"},
            )

    # ------------------------------------------------------------------
    # Multi-tenant Organization Management
    # ------------------------------------------------------------------
    if getattr(container, "org_routes_available", False) is True:
        # Add organization management routes at /api/v1/orgs/*
        org_routes = create_org_routes(
            org_service=container.org_service,
            invitation_service=container.invitation_service,
            get_user_id=_require_user_id,
            tags=["organizations"],
        )
        app.include_router(org_routes, prefix="/api")

    # ------------------------------------------------------------------
    # Settings Management (Project and Org settings)
    # ------------------------------------------------------------------
    if getattr(container, "settings_routes_available", False) is True:
        # Add settings routes at /api/v1/projects/{project_id}/settings/*
        settings_routes = create_settings_routes(
            settings_service=container.settings_service,
            get_user_id=_require_user_id,
            tags=["settings"],
        )
        app.include_router(settings_routes, prefix="/api")

    # ------------------------------------------------------------------
    # Projects (always available when a project service exists)
    # ------------------------------------------------------------------
    if getattr(container, "project_service_available", False) is True:
        app.include_router(
            create_project_routes(
                org_service=container.org_service,
                get_user_id=_require_user_id,
                tags=["projects"],
            ),
            prefix="/api",
        )
    else:
        logger.warning("Project routes unavailable — no database DSN configured")

    # ------------------------------------------------------------------
    # Board Management (Unified WorkItem CRUD)
    # ------------------------------------------------------------------
    # Add board routes for Agile hierarchy management
    board_routes = create_board_routes(
        board_service=container.board_service,
        tags=["boards"],
    )
    app.include_router(board_routes, prefix="/api")

    # ------------------------------------------------------------------
    # Work Item Execution (Agent execution of work items)
    # ------------------------------------------------------------------
    if getattr(container, "execution_service_available", False) is True:
        from .services.work_item_execution_api import create_work_item_execution_routes
        from .services.run_events_api import create_run_events_routes

        execution_routes = create_work_item_execution_routes(
            service=container.work_item_execution_service,
        )
        app.include_router(execution_routes, prefix="/api")
        logger.info("Work item execution routes registered at /api/v1/work-items/*")

        # Register SSE endpoint for real-time execution events
        if container.execution_event_hub is not None:
            sse_routes = create_run_events_routes(event_hub=container.execution_event_hub)
            app.include_router(sse_routes, prefix="/api")
            logger.info("Run events SSE routes registered at /api/v1/runs/{run_id}/events")

    logger.info(
        "API route capabilities mounted: projects=%s participants=%s orgs=%s settings=%s executions=%s",
        container.api_capabilities.routes.projects,
        container.api_capabilities.routes.participants,
        container.api_capabilities.routes.orgs,
        container.api_capabilities.routes.settings,
        container.api_capabilities.routes.executions,
    )

    # ------------------------------------------------------------------
    # Billing Service
    # ------------------------------------------------------------------
    if BILLING_AVAILABLE and container.billing_service is not None and create_billing_router is not None:
        try:
            # Add billing routes at /api/v1/billing/*
            billing_routes = create_billing_router(
                billing_service=container.billing_service,
            )
        except NotImplementedError as exc:
            logger.warning("Billing routes unavailable: %s", exc)
        else:
            app.include_router(billing_routes, prefix="/api")

    # ------------------------------------------------------------------
    # Research (AI Paper Evaluation — read-only)
    # ------------------------------------------------------------------
    research_dsn = resolve_optional_postgres_dsn(
        service="RESEARCH",
        explicit_dsn=None,
        env_var="AMPREALIZE_RESEARCH_PG_DSN",
    )
    if research_dsn:
        try:
            from amprealize.storage.postgres_pool import PostgresPool
            from amprealize.storage.research_storage_postgres import ResearchStoragePostgres
            from amprealize.services.research_api import create_research_routes

            research_pool = PostgresPool(research_dsn, "research")
            research_storage = ResearchStoragePostgres(research_pool)
            research_routes = create_research_routes(storage=research_storage, tags=["research"])
            app.include_router(research_routes, prefix="/api")
            logger.info("Research routes registered at /api/v1/research/*")
        except Exception as exc:
            logger.warning("Research routes unavailable: %s", exc)

    # ------------------------------------------------------------------
    # Whiteboard (collaborative brainstorm canvas)
    # ------------------------------------------------------------------
    if os.getenv("AMPREALIZE_ENABLE_WHITEBOARD", "").lower() in ("true", "1", "yes"):
        try:
            from whiteboard import WhiteboardService, InMemoryStorage
            from amprealize.services.whiteboard_api import create_whiteboard_routes

            # Use context system to resolve whiteboard DB — falls back to
            # InMemoryStorage when no Postgres DSN is available.
            whiteboard_dsn = resolve_optional_postgres_dsn(
                service="WHITEBOARD",
                explicit_dsn=os.getenv("AMPREALIZE_WHITEBOARD_PG_DSN"),
                env_var="AMPREALIZE_WHITEBOARD_PG_DSN",
            )
            if whiteboard_dsn:
                from amprealize.storage.postgres_pool import PostgresPool
                from amprealize.storage.whiteboard_postgres import PostgresWhiteboardStorage

                whiteboard_pool = PostgresPool(whiteboard_dsn, service_name="whiteboard")
                postgres_whiteboard_storage = PostgresWhiteboardStorage(pool=whiteboard_pool)
                try:
                    postgres_whiteboard_storage.ensure_schema_ready()
                    whiteboard_storage = postgres_whiteboard_storage
                    logger.info("Whiteboard using PostgreSQL storage (context system)")
                except Exception as exc:
                    whiteboard_storage = InMemoryStorage()
                    logger.warning(
                        "Whiteboard PostgreSQL storage unavailable (%s); falling back to InMemoryStorage",
                        exc,
                    )
            else:
                whiteboard_storage = InMemoryStorage()
                logger.info("Whiteboard using InMemoryStorage (no DB configured)")

            # Wire telemetry hooks (Raze) for whiteboard events
            whiteboard_hooks = None
            if RAZE_AVAILABLE and container.raze_service is not None:
                from amprealize.services.whiteboard_hooks import AmprealizeWhiteboardHooks
                whiteboard_hooks = AmprealizeWhiteboardHooks(raze_service=container.raze_service)

            whiteboard_service = WhiteboardService(storage=whiteboard_storage, hooks=whiteboard_hooks)
            whiteboard_routes = create_whiteboard_routes(service=whiteboard_service, tags=["whiteboard"])
            app.include_router(whiteboard_routes, prefix="/api")
            logger.info("Whiteboard routes registered at /api/v1/whiteboard/*")
        except Exception as exc:
            logger.warning("Whiteboard routes unavailable: %s", exc)

    # ------------------------------------------------------------------
    # Wiki Routes (read-only, filesystem-based — no DB required)
    # ------------------------------------------------------------------
    try:
        from amprealize.services.wiki_api import create_wiki_routes

        wiki_routes = create_wiki_routes()
        app.include_router(wiki_routes, prefix="/api")
        logger.info("Wiki routes registered at /api/v1/wiki/*")
    except Exception as exc:
        logger.warning("Wiki routes unavailable: %s", exc)

    # ------------------------------------------------------------------
    # Conversation / Messaging Routes
    # ------------------------------------------------------------------
    conversation_dsn = resolve_optional_postgres_dsn(
        service="MESSAGING",
        explicit_dsn=None,
        env_var="AMPREALIZE_MESSAGING_PG_DSN",
    )
    if not conversation_dsn:
        conversation_dsn = resolve_optional_postgres_dsn(
            service="BOARD",
            explicit_dsn=None,
            env_var="AMPREALIZE_BOARD_PG_DSN",
        )
    if not conversation_dsn:
        conversation_dsn = os.environ.get("DATABASE_URL")
    if conversation_dsn:
        try:
            from amprealize.storage.postgres_pool import PostgresPool as _MsgPool
            from amprealize.services.conversation_service import ConversationService
            from amprealize.services.conversation_api import create_conversation_routes
            from amprealize.conversation_event_hub import ConversationEventHub
            from amprealize.services.conversation_events_api import (
                create_conversation_ws_routes,
                register_conversation_ws,
            )

            msg_pool = _MsgPool(conversation_dsn, "messaging")
            conversation_event_hub = ConversationEventHub()
            conversation_service = ConversationService(
                dsn=conversation_dsn,
                pool=msg_pool,
                event_hub=conversation_event_hub,
            )
            conversation_routes = create_conversation_routes(
                conversation_service=conversation_service,
                tags=["conversations"],
            )
            app.include_router(conversation_routes, prefix="/api")

            # SSE routes for token streaming and conversation events
            conversation_ws_routes = create_conversation_ws_routes(
                conversation_event_hub=conversation_event_hub,
                conversation_service=conversation_service,
            )
            app.include_router(conversation_ws_routes, prefix="/api")

            # WebSocket endpoint (must be registered on app directly)
            register_conversation_ws(app, conversation_event_hub, conversation_service)

            app.state.conversation_event_hub = conversation_event_hub
            app.state.conversation_service = conversation_service
            logger.info("Conversation routes + WS/SSE registered at /api/v1/conversations/*")
        except Exception as exc:
            logger.warning("Conversation routes unavailable: %s", exc)

    # ------------------------------------------------------------------
    # Slack Bridge (Phase 7 — AMPREALIZE-566)
    # ------------------------------------------------------------------
    if conversation_dsn and hasattr(app.state, "conversation_service"):
        try:
            from amprealize.config.settings import SlackConfig
            from amprealize.services.slack_bridge import SlackBridgeService
            from amprealize.services.slack_bridge_api import create_slack_bridge_routes

            slack_config = SlackConfig()
            if slack_config.is_configured():
                slack_bridge = SlackBridgeService(
                    config=slack_config,
                    conversation_service=app.state.conversation_service,
                    event_hub=app.state.conversation_event_hub,
                )
                slack_routes = create_slack_bridge_routes(
                    slack_bridge=slack_bridge,
                    tags=["integrations", "slack"],
                )
                app.include_router(slack_routes, prefix="/api")
                app.state.slack_bridge = slack_bridge

                @app.on_event("startup")
                async def _start_slack_bridge() -> None:
                    await slack_bridge.start_outbound_subscription()
                    logger.info("Slack bridge outbound subscription started")

                @app.on_event("shutdown")
                async def _stop_slack_bridge() -> None:
                    await slack_bridge.close()
                    logger.info("Slack bridge closed")

                logger.info("Slack bridge routes registered at /api/v1/integrations/slack/*")
            else:
                logger.info(
                    "Slack bridge not configured (SLACK_BOT_TOKEN / SLACK_SIGNING_SECRET unset)"
                )
        except Exception as exc:
            logger.warning("Slack bridge unavailable: %s", exc)

    # ------------------------------------------------------------------
    # Conversation Retention Worker + Analytics (Phase 8 — AMPREALIZE-567)
    # ------------------------------------------------------------------
    if conversation_dsn and hasattr(app.state, "conversation_service"):
        try:
            from amprealize.config.settings import MessagingRetentionConfig
            from amprealize.services.retention_worker import RetentionWorker
            from amprealize.services.conversation_analytics_api import (
                create_conversation_analytics_routes,
            )

            retention_config = MessagingRetentionConfig()

            # Try to set up S3 storage for cold export (enterprise only)
            _retention_storage = None
            if retention_config.cold_export_enabled:
                try:
                    from amprealize.storage.s3_storage import S3Storage
                    _retention_storage = S3Storage()
                except Exception as _s3_exc:
                    logger.warning("Cold export S3 storage unavailable: %s", _s3_exc)

            retention_worker = RetentionWorker(
                conversation_service=app.state.conversation_service,
                retention_config=retention_config,
                storage=_retention_storage,
            )
            app.state.retention_worker = retention_worker

            # Register analytics + retention policy routes
            analytics_routes = create_conversation_analytics_routes(
                conversation_service=app.state.conversation_service,
                retention_worker=retention_worker,
                tags=["conversations", "analytics"],
            )
            app.include_router(analytics_routes, prefix="/api")

            @app.on_event("startup")
            async def _start_retention_worker() -> None:
                await retention_worker.start()
                logger.info("Retention worker started")

            @app.on_event("shutdown")
            async def _stop_retention_worker() -> None:
                await retention_worker.stop()
                logger.info("Retention worker stopped")

            logger.info(
                "Retention worker + analytics routes registered "
                "(archive_after=%dd, cold_export=%s)",
                retention_config.archive_after_days,
                "enabled" if retention_config.cold_export_enabled else "disabled",
            )
        except Exception as exc:
            logger.warning("Retention worker unavailable: %s", exc)

    # ------------------------------------------------------------------
    # Dashboard Stats
    # ------------------------------------------------------------------
    @app.get("/api/v1/dashboard/stats")
    async def dashboard_stats() -> Dict[str, Any]:
        """
        Get aggregated dashboard statistics.

        Returns counts and summaries for display on the main dashboard.
        """
        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Get counts from services
        total_behaviors = 0
        total_runs = 0
        running_runs = 0
        completed_today = 0
        failed_today = 0

        try:
            behaviors = container.behavior_service.list_behaviors()
            total_behaviors = len(behaviors)
        except Exception:
            pass

        try:
            runs = container.run_service.list_runs(limit=1000)
            total_runs = len(runs)
            for run in runs:
                if run.get("status") == "RUNNING":
                    running_runs += 1
                started_at = run.get("started_at", "")
                if started_at and started_at.startswith(today):
                    if run.get("status") == "COMPLETED":
                        completed_today += 1
                    elif run.get("status") == "FAILED":
                        failed_today += 1
        except Exception:
            pass

        return {
            "total_projects": 0,  # Projects not implemented yet
            "total_agents": 0,  # Agents not implemented yet
            "active_agents": 0,
            "busy_agents": 0,
            "total_runs": total_runs,
            "running_runs": running_runs,
            "completed_runs_today": completed_today,
            "failed_runs_today": failed_today,
            "total_behaviors": total_behaviors,
        }

    # ------------------------------------------------------------------
    # Operations & Monitoring
    # ------------------------------------------------------------------
    @app.get("/health")
    def health() -> Dict[str, Any]:
        """Health check endpoint with detailed service status and pool metrics.

        Returns:
            Dictionary with overall health status and per-service details including:
            - status: "healthy" or "degraded"
            - services: List of service health checks
            - pools: Connection pool statistics for PostgreSQL services
        """
        from amprealize.storage import postgres_metrics

        services_health = []
        pools_stats = []
        overall_healthy = True

        # Check each service adapter
        service_checks = [
            ("action", container.action_service),
            ("behavior", container.behavior_service),
            ("compliance", container.compliance_service),
            ("workflow", container.workflow_service),
            ("run", container.run_service),
        ]

        for service_name, service in service_checks:
            try:
                # Check if service has PostgresPool (may be lazy-initialized)
                if hasattr(service, "_pool"):
                    pool = service._pool
                    if pool is None:
                        # Pool exists but not initialized yet (lazy initialization)
                        # Try to get pool via _get_pool() if available
                        if hasattr(service, "_get_pool"):
                            try:
                                pool = service._get_pool()
                            except Exception:
                                # Pool initialization failed - service not ready
                                services_health.append({
                                    "service": service_name,
                                    "status": "not_initialized",
                                    "pool": None,
                                })
                                continue
                        else:
                            # Has _pool attr but it's None and no _get_pool method
                            services_health.append({
                                "service": service_name,
                                "status": "not_initialized",
                                "pool": None,
                            })
                            continue

                    pool_stats = pool.get_pool_stats()
                    pools_stats.append(pool_stats)

                    # Service is degraded if checked_out >= pool_size (no available connections)
                    is_healthy = pool_stats["available"] > 0
                    services_health.append({
                        "service": service_name,
                        "status": "healthy" if is_healthy else "degraded",
                        "pool": pool_stats,
                    })
                    overall_healthy = overall_healthy and is_healthy
                else:
                    # Non-pooled service (in-memory, etc.)
                    services_health.append({
                        "service": service_name,
                        "status": "healthy",
                        "pool": None,
                    })
            except Exception as exc:
                services_health.append({
                    "service": service_name,
                    "status": "error",
                    "error": str(exc),
                })
                overall_healthy = False

        return {
            "status": "healthy" if overall_healthy else "degraded",
            "services": services_health,
            "pools_summary": {
                "total_checked_out": sum(p["checked_out"] for p in pools_stats),
                "total_available": sum(p["available"] for p in pools_stats),
                "total_pool_size": sum(p["pool_size"] for p in pools_stats),
            } if pools_stats else None,
        }

    @app.get("/metrics")
    def metrics() -> Response:
        """Prometheus metrics endpoint exposing connection pool and transaction metrics.

        Returns:
            Prometheus exposition format metrics including:
            - amprealize_pool_connections_*: Pool utilization metrics
            - amprealize_transaction_*: Transaction execution metrics
            - amprealize_query_*: Query performance metrics
            - amprealize_embedding_*: Embedding model performance metrics (Phase 2)
            - amprealize_retrieval_*: BCI retrieval latency and quality metrics (Phase 2)
        """
        try:
            from prometheus_client import REGISTRY, generate_latest
            # Use prometheus_client's default registry which includes embedding metrics
            metrics_data = generate_latest(REGISTRY).decode("utf-8")
        except ImportError:
            # Fallback to postgres-only metrics if prometheus_client not installed
            from amprealize.storage import postgres_metrics

            # Update all registered pool metrics before export
            for service_name, service in [
                ("action", container.action_service),
                ("behavior", container.behavior_service),
                ("compliance", container.compliance_service),
                ("workflow", container.workflow_service),
                ("run", container.run_service),
            ]:
                if hasattr(service, "_pool") and hasattr(service._pool._engine, "_update_pool_metrics"):
                    service._pool._engine._update_pool_metrics()  # type: ignore[attr-defined]

            metrics_data = postgres_metrics.get_metrics()

        return Response(content=metrics_data, media_type="text/plain; version=0.0.4")

    # GZip must be registered BEFORE CORSMiddleware. Starlette stacks middleware
    # in reverse-registration order (last registered = outermost). GZip inner,
    # CORS outer ensures Access-Control-Allow-Origin is always present.
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # Add CORS middleware last so it wraps everything (outermost layer)
    # This ensures CORS headers are present even on 500 errors from inner layers
    #
    # Origins are resolved from AMPREALIZE_CORS_ORIGINS (comma-separated), with
    # an opt-in localhost regex (default on) for dev convenience.
    _cors_allow_origins = cors_origins if cors_origins else default_cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_allow_origins,
        allow_origin_regex=cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return app


app = create_app()
"""Default application exported for `uvicorn amprealize.api:app`."""
