#!/usr/bin/env python3
"""
Amprealize MCP Server

Model Context Protocol server providing stdio-based JSON-RPC interface for Amprealize tools.
Enables AI assistants (Claude Desktop, Cursor, Cline) to authenticate and interact with
Amprealize via the standardized MCP protocol.

Supported Tools:
- auth.deviceLogin - OAuth 2.0 device authorization flow
- auth.authStatus - Check authentication status
- auth.refreshToken - Refresh expired access tokens
- auth.logout - Revoke tokens and clear storage
- [Future] behaviors.*, workflows.*, runs.*, etc.

Usage:
    # Run standalone:
    python -m amprealize.mcp_server

    # Configure in Claude Desktop (~/Library/Application Support/Claude/claude_desktop_config.json):
    {
      "mcpServers": {
        "amprealize": {
          "command": "python",
          "args": ["-m", "amprealize.mcp_server"]
        }
      }
    }

Protocol:
    - Input: JSON-RPC 2.0 requests via stdin
    - Output: JSON-RPC 2.0 responses via stdout
    - Logging: stderr (structured JSON logs)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set, TYPE_CHECKING, Union

from .mcp_tools_dir import get_mcp_tools_directory

# Heavy service modules are imported lazily (inside methods that need them)
# to keep MCP server startup fast (~0.5s instead of ~9s).
if TYPE_CHECKING:
    from .action_service import ActionService
    from .action_service_postgres import PostgresActionService
    from .bci_service import BCIService
    from .behavior_service import BehaviorService
    from .workflow_service import WorkflowService
    from .storage.postgres_pool import PostgresPool
    from .utils.dsn import apply_host_overrides
    from .knowledge_pack.activation_service import ActivationService


def _ensure_dsn_param(dsn: str, key: str, value: str) -> str:
    """Ensure a DSN query parameter is present (without overriding existing values)."""
    try:
        parsed = urlparse(dsn)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if key in query:
            return dsn
        query[key] = value
        return urlunparse(parsed._replace(query=urlencode(query)))
    except Exception:
        return dsn


def _mcp_expose_auth_tokens_in_responses() -> bool:
    """When True, MCP auth tool responses may include raw OAuth tokens (debugging only)."""
    return os.environ.get("MCP_EXPOSE_AUTH_TOKENS", "").lower() in ("1", "true", "yes")


def _redact_oauth_tokens_for_mcp_tool_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Strip OAuth secrets from dicts serialized to MCP clients; tokens are still saved when store_tokens is true.

    Session population and token persistence run on the full ``result`` before this runs.
    """
    if _mcp_expose_auth_tokens_in_responses():
        return result
    out = dict(result)
    had_access = out.pop("access_token", None) is not None
    had_refresh = out.pop("refresh_token", None) is not None
    if had_access or had_refresh:
        out["oauth_tokens_redacted"] = True
        out["oauth_tokens_note"] = (
            "Raw OAuth access and refresh tokens are omitted from MCP tool output for security. "
            "When store_tokens is true, tokens are still persisted to the configured token store. "
            "Set MCP_EXPOSE_AUTH_TOKENS=1 to include tokens in responses (debugging only)."
        )
    return out


# ============================================================================
# MCP Session Context (Phase 1: MCP_AUTH_IMPLEMENTATION_PLAN.md)
# ============================================================================

# Tools that don't require authentication (public tools)
PUBLIC_TOOLS: Set[str] = {
    "auth.deviceLogin",
    "auth.deviceInit",
    "auth.devicePoll",
    "auth.authStatus",
    "auth.clientCredentials",
    "auth.refreshToken",
    "auth.consentStatus",
    # Tool group management (meta-tools)
    "tools.listGroups",
    "tools.activateGroup",
    "tools.deactivateGroup",
    "tools.activeGroups",
}


@dataclass
class MCPSessionContext:
    """
    Authenticated session context for MCP connections.

    Tracks identity and authorization state for the duration of an MCP session.
    Populated after successful auth.deviceLogin or auth.clientCredentials.

    After authentication, the session knows:
    - Who the user is (user_id)
    - Whether they're an admin (is_admin) - can access all resources
    - What orgs they belong to (accessible_org_ids)
    - What projects they can access (accessible_project_ids)

    Tools use this context to:
    - Auto-inject user_id into handlers
    - Authorize access without requiring explicit org_id/project_id params
    - Allow admins to bypass access checks

    See MCP_AUTH_IMPLEMENTATION_PLAN.md Phase 1 for details.
    """
    user_id: Optional[str] = None
    org_id: Optional[str] = None  # Current/default org (if any)
    project_id: Optional[str] = None  # Current/default project (if any)
    service_principal_id: Optional[str] = None
    email: Optional[str] = None
    roles: List[str] = field(default_factory=list)
    granted_scopes: Set[str] = field(default_factory=set)
    auth_method: Literal["device_flow", "client_credentials", "none"] = "none"
    authenticated_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    # Authorization context - populated after auth
    is_admin: bool = False  # If True, can access all resources
    accessible_org_ids: Set[str] = field(default_factory=set)  # Orgs user belongs to
    accessible_project_ids: Set[str] = field(default_factory=set)  # Projects user can access

    @property
    def is_authenticated(self) -> bool:
        """Check if session has valid authentication."""
        if self.auth_method == "none":
            return False
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False
        return bool(self.user_id or self.service_principal_id)

    @property
    def identity(self) -> Optional[str]:
        """Get the primary identity (user_id or service_principal_id)."""
        return self.user_id or self.service_principal_id

    def has_scope(self, scope: str) -> bool:
        """Check if session has a specific scope granted.

        Args:
            scope: The scope to check (e.g., 'behaviors.read', 'runs.create')

        Returns:
            True if scope is in granted_scopes
        """
        return scope in self.granted_scopes

    def has_all_scopes(self, scopes: List[str]) -> bool:
        """Check if session has ALL specified scopes.

        Args:
            scopes: List of required scopes

        Returns:
            True if all scopes are granted
        """
        if not scopes:
            return True
        return set(scopes).issubset(self.granted_scopes)

    def has_any_scope(self, scopes: List[str]) -> bool:
        """Check if session has ANY of the specified scopes.

        Args:
            scopes: List of scopes (need at least one)

        Returns:
            True if at least one scope is granted
        """
        if not scopes:
            return True
        return bool(set(scopes) & self.granted_scopes)

    def missing_scopes(self, required: List[str]) -> Set[str]:
        """Get scopes that are required but not granted.

        Args:
            required: List of required scopes

        Returns:
            Set of missing scopes
        """
        return set(required) - self.granted_scopes

    def can_access_org(self, org_id: str) -> bool:
        """Check if user can access the specified organization.

        Args:
            org_id: Organization ID to check

        Returns:
            True if admin or org is in accessible_org_ids
        """
        if self.is_admin:
            return True
        return org_id in self.accessible_org_ids

    def can_access_project(self, project_id: str) -> bool:
        """Check if user can access the specified project.

        Args:
            project_id: Project ID to check

        Returns:
            True if admin or project is in accessible_project_ids
        """
        if self.is_admin:
            return True
        return project_id in self.accessible_project_ids


@dataclass
class MCPRequest:
    """MCP JSON-RPC 2.0 request."""
    jsonrpc: str = "2.0"
    id: Optional[str] = None
    method: str = ""
    params: Optional[Dict[str, Any]] = None


@dataclass
class MCPResponse:
    """MCP JSON-RPC 2.0 response."""
    jsonrpc: str = "2.0"
    id: Optional[str] = None
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None


@dataclass
class MCPError:
    """MCP JSON-RPC error object."""
    code: int
    message: str
    data: Optional[Any] = None


class MCPServiceRegistry:
    """Lazy initializer for MCP service singletons using PostgreSQL DSNs."""

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self._logger = logger or logging.getLogger("amprealize.mcp_server.services")
        self._behavior_service: Optional[BehaviorService] = None
        self._bci_service: Optional[BCIService] = None
        self._workflow_service: Optional[WorkflowService] = None
        self._action_service: Optional[Union[PostgresActionService, ActionService]] = None
        self._trace_analysis_service: Optional[Any] = None
        self._run_service: Optional[Any] = None
        self._metrics_service: Optional[Any] = None
        self._analytics_service: Optional[Any] = None
        self._agent_orchestrator_service: Optional[Any] = None
        self._compliance_service: Optional[Any] = None
        self._audit_log_service: Optional[Any] = None
        self._agent_auth_service: Optional[Any] = None
        self._consent_service: Optional[Any] = None  # Phase 6: JIT consent
        self._task_assignment_service: Optional[Any] = None
        self._raze_service: Optional[Any] = None
        self._breakeramp_service: Optional[Any] = None

        # Epic 7 Advanced Features services
        self._fine_tuning_service: Optional[Any] = None
        self._agent_review_service: Optional[Any] = None
        self._multi_tenant_service: Optional[Any] = None
        self._advanced_retrieval_service: Optional[Any] = None
        self._collaboration_service: Optional[Any] = None
        self._api_rate_limiting_service: Optional[Any] = None
        self._reflection_service: Optional[Any] = None

        # Multi-tenant services for orgs/projects/boards
        self._organization_service: Optional[Any] = None
        self._board_service: Optional[Any] = None
        self._agent_registry_service: Optional[Any] = None

        # Work item execution
        self._work_item_execution_service: Optional[Any] = None

        # File and GitHub services
        self._github_service: Optional[Any] = None

        # Config services
        self._credential_store: Optional[Any] = None

        # Research service
        self._research_service: Optional[Any] = None

        # Conversation/messaging service
        self._conversation_service: Optional[Any] = None

        # Conversation reply service (context-aware replies via ContextComposer)
        self._conversation_reply_service: Optional[Any] = None

        # LLM client singleton
        self._llm_client: Optional[Any] = None

        # ContextComposer singleton
        self._context_composer: Optional[Any] = None

        # Shared connection pools for PostgreSQL services
        # Note: Services create their own PostgresPool instances, but PostgresPool
        # internally caches engines by DSN, so multiple services with the same DSN
        # will share the same underlying connection pool (via _POOL_CACHE).
        self._pools: Dict[str, PostgresPool] = {}

    def _get_pool(self, dsn: str, service_name: str) -> PostgresPool:
        """
        Get or create a PostgresPool for the given DSN and service.

        This method is primarily for pre-warming pools or getting pool metrics.
        Services create their own PostgresPool instances, but the internal
        _POOL_CACHE ensures they share the same SQLAlchemy engine.
        """
        from .storage.postgres_pool import PostgresPool  # lazy

        if dsn not in self._pools:
            self._pools[dsn] = PostgresPool(dsn=dsn, service_name=service_name)
            self._logger.info(f"Created PostgresPool for {service_name}")
        return self._pools[dsn]

    def prewarm_pools(self) -> None:
        """Pre-warm connection pools for all configured PostgreSQL services.

        Validates database connectivity and provides clear error diagnostics
        including DSN comparison when connections fail.
        """
        from .utils.dsn import apply_host_overrides  # lazy

        dsn_map = {
            "AMPREALIZE_BEHAVIOR_PG_DSN": "behavior",
            "AMPREALIZE_WORKFLOW_PG_DSN": "workflow",
            "AMPREALIZE_ACTION_PG_DSN": "action",
            "AMPREALIZE_RUN_PG_DSN": "run",
            "AMPREALIZE_METRICS_PG_DSN": "metrics",
            "AMPREALIZE_COMPLIANCE_PG_DSN": "compliance",
            "AMPREALIZE_REFLECTION_PG_DSN": "reflection",
            "AMPREALIZE_COLLABORATION_PG_DSN": "collaboration",
        }

        failed_services: list[tuple[str, str, str]] = []  # (service, env_var, error)

        for env_var, service_name in dsn_map.items():
            raw_dsn = os.environ.get(env_var)
            dsn = apply_host_overrides(raw_dsn, service_name.upper())
            if dsn:
                try:
                    pool = self._get_pool(dsn, service_name)
                    # Test connection
                    with pool.connection() as conn:
                        cur = conn.cursor()
                        try:
                            cur.execute("SELECT 1")
                        finally:
                            cur.close()
                    self._logger.info(f"Pre-warmed {service_name} pool successfully")
                except Exception as e:
                    # Extract connection details for diagnostic (hide password)
                    dsn_diagnostic = self._sanitize_dsn_for_logging(dsn)
                    error_msg = str(e)
                    failed_services.append((service_name, env_var, error_msg))
                    self._logger.error(
                        f"❌ Database connection failed for {service_name}:\n"
                        f"   Environment variable: {env_var}\n"
                        f"   DSN (sanitized): {dsn_diagnostic}\n"
                        f"   Error: {error_msg}\n"
                        f"   💡 Check that .env matches your database configuration "
                        f"(port, credentials, database name)"
                    )

        # Log summary if any failures occurred
        if failed_services:
            service_names = ", ".join(s[0] for s in failed_services)
            self._logger.warning(
                f"⚠️  {len(failed_services)} database connection(s) failed: {service_names}\n"
                f"   Some MCP tools may not work. Check your .env configuration."
            )

    def _sanitize_dsn_for_logging(self, dsn: str) -> str:
        """Remove password from DSN for safe logging."""
        import re
        # Match patterns like :password@ or password=xxx
        sanitized = re.sub(r':([^:@/]+)@', r':***@', dsn)
        sanitized = re.sub(r'password=[^&\s]+', 'password=***', sanitized)
        return sanitized

    def breakeramp_service(self) -> Any:
        if not self._breakeramp_service:
            from .breakeramp import BreakerAmpService
            # It needs action_service, compliance_service, and metrics_service
            self._breakeramp_service = BreakerAmpService(
                action_service=self.action_service(),
                compliance_service=self.compliance_service(),
                metrics_service=self.metrics_service()
            )
        return self._breakeramp_service

    def behavior_service(self) -> BehaviorService:
        if self._behavior_service is None:
            from .behavior_service import BehaviorService  # lazy

            service = BehaviorService()
            dsn_repr = getattr(service, "_dsn", "<hidden>")
            self._logger.info(
                "Initialized BehaviorService for MCP with PostgreSQL backend (dsn=%s)",
                dsn_repr,
            )
            self._behavior_service = service
        return self._behavior_service

    def bci_service(self) -> BCIService:
        """Get or create BCIService singleton for MCP."""
        if self._bci_service is None:
            from .bci_service import BCIService  # lazy

            service = BCIService()
            self._logger.info("Initialized BCIService for MCP")
            self._bci_service = service
        return self._bci_service

    def workflow_service(self) -> WorkflowService:
        if self._workflow_service is None:
            from .workflow_service import WorkflowService  # lazy

            service = WorkflowService(
                dsn=None,
                behavior_service=self.behavior_service(),
            )
            dsn_repr = getattr(service, "dsn", "<hidden>")
            self._logger.info(
                "Initialized WorkflowService for MCP with PostgreSQL backend (dsn=%s)",
                dsn_repr,
            )
            self._workflow_service = service
        return self._workflow_service

    def action_service(self) -> Union[PostgresActionService, ActionService]:
        if self._action_service is None:
            from .utils.dsn import apply_host_overrides  # lazy

            dsn = apply_host_overrides(os.environ.get("AMPREALIZE_ACTION_PG_DSN"), "ACTION")
            if dsn:
                from .action_service_postgres import PostgresActionService  # lazy
                from .telemetry import TelemetryClient

                service: Union[PostgresActionService, ActionService] = PostgresActionService(
                    dsn=dsn, telemetry=TelemetryClient.noop()
                )
                self._logger.info(
                    "Initialized PostgresActionService for MCP with PostgreSQL backend"
                )
            else:
                # Fallback to in-memory for development
                from .action_service import ActionService  # lazy

                service = ActionService()
                self._logger.warning(
                    "Using in-memory ActionService (AMPREALIZE_ACTION_PG_DSN not set)"
                )
            self._action_service = service
        return self._action_service

    def trace_analysis_service(self) -> Any:
        """Get or create TraceAnalysisService singleton for MCP."""
        if self._trace_analysis_service is None:
            from .trace_analysis_service import TraceAnalysisService
            from .utils.dsn import apply_host_overrides  # lazy

            dsn = apply_host_overrides(os.environ.get("AMPREALIZE_TRACE_ANALYSIS_PG_DSN"), "TRACE_ANALYSIS")
            if dsn:
                try:
                    from .trace_analysis_service_postgres import PostgresTraceAnalysisService
                    storage = PostgresTraceAnalysisService(dsn=dsn)
                    service = TraceAnalysisService(storage=storage)
                    self._logger.info(
                        "Initialized TraceAnalysisService for MCP with PostgreSQL backend"
                    )
                except ImportError:
                    service = TraceAnalysisService()
                    self._logger.warning(
                        "Using in-memory TraceAnalysisService (PostgreSQL backend unavailable)"
                    )
            else:
                service = TraceAnalysisService()
                self._logger.info(
                    "Initialized TraceAnalysisService for MCP (in-memory mode)"
                )
            self._trace_analysis_service = service
        return self._trace_analysis_service

    def run_service(self) -> Any:
        """Get or create RunService singleton for MCP."""
        if self._run_service is None:
            from .utils.dsn import apply_host_overrides  # lazy

            dsn = apply_host_overrides(os.environ.get("AMPREALIZE_RUN_PG_DSN"), "RUN")
            if dsn:
                try:
                    from .run_service_postgres import PostgresRunService
                    from .telemetry import TelemetryClient

                    service = PostgresRunService(dsn=dsn, telemetry=TelemetryClient.noop())
                    self._logger.info(
                        "Initialized PostgresRunService for MCP with PostgreSQL backend"
                    )
                except ImportError:
                    from .run_service import RunService

                    service = RunService()
                    self._logger.warning(
                        "Using in-memory RunService (PostgreSQL backend unavailable)"
                    )
            else:
                from .run_service import RunService

                service = RunService()
                self._logger.info(
                    "Initialized RunService for MCP (in-memory mode, AMPREALIZE_RUN_PG_DSN not set)"
                )
            self._run_service = service
        return self._run_service

    def metrics_service(self) -> Any:
        """Get or create MetricsService singleton for MCP."""
        if self._metrics_service is None:
            from .utils.dsn import apply_host_overrides  # lazy

            dsn = apply_host_overrides(os.environ.get("AMPREALIZE_METRICS_PG_DSN"), "METRICS")
            if dsn:
                try:
                    from .metrics_service_postgres import PostgresMetricsService

                    service = PostgresMetricsService(dsn=dsn)
                    self._logger.info(
                        "Initialized PostgresMetricsService for MCP with PostgreSQL backend"
                    )
                except ImportError:
                    from .metrics_service import MetricsService

                    service = MetricsService()
                    self._logger.warning(
                        "Using in-memory MetricsService (PostgreSQL backend unavailable)"
                    )
            else:
                from .metrics_service import MetricsService

                service = MetricsService()
                self._logger.info(
                    "Initialized MetricsService for MCP (in-memory mode, AMPREALIZE_METRICS_PG_DSN not set)"
                )
            self._metrics_service = service
        return self._metrics_service

    def analytics_service(self) -> Any:
        """Get or create AnalyticsWarehouse singleton for MCP."""
        if self._analytics_service is None:
            from .analytics.warehouse import AnalyticsWarehouse

            # Check for custom DuckDB path from environment
            db_path = os.environ.get("AMPREALIZE_ANALYTICS_DUCKDB_PATH")
            service = AnalyticsWarehouse(db_path=db_path) if db_path else AnalyticsWarehouse()
            self._logger.info(
                "Initialized AnalyticsWarehouse for MCP (db_path=%s)",
                db_path or "<default: data/telemetry.duckdb>",
            )
            self._analytics_service = service
        return self._analytics_service

    def agent_orchestrator_service(self) -> Any:
        """Get or create AgentOrchestratorService singleton for MCP."""
        if self._agent_orchestrator_service is None:
            from .agent_orchestrator_service import AgentOrchestratorService

            service = AgentOrchestratorService()
            self._logger.info("Initialized AgentOrchestratorService for MCP (in-memory mode)")
            self._agent_orchestrator_service = service
        return self._agent_orchestrator_service

    def compliance_service(self) -> Any:
        """Get or create ComplianceService singleton for MCP."""
        if self._compliance_service is None:
            from .compliance_service import ComplianceService

            # ComplianceService uses PostgreSQL; resolves DSN from AMPREALIZE_COMPLIANCE_PG_DSN env var
            service = ComplianceService(dsn=None)
            self._logger.info("Initialized ComplianceService for MCP (PostgreSQL backend)")
            self._compliance_service = service
        return self._compliance_service

    def audit_log_service(self) -> Any:
        """Get or create AuditLogService singleton for MCP."""
        if self._audit_log_service is None:
            from .services.audit_log_service import AuditLogService
            from .utils.dsn import apply_host_overrides  # lazy

            # AuditLogService uses PostgreSQL hot tier; resolves DSN from AMPREALIZE_AUDIT_PG_DSN env var
            # Also uses S3 for warm tier (WORM storage) and OpenSearch for indexing
            dsn = apply_host_overrides(os.environ.get("AMPREALIZE_AUDIT_PG_DSN"), "AUDIT")
            service = AuditLogService(dsn=dsn)
            if dsn:
                self._logger.info(
                    "Initialized AuditLogService for MCP (PostgreSQL + S3 + OpenSearch)"
                )
            else:
                self._logger.info(
                    "Initialized AuditLogService for MCP (in-memory mode, AMPREALIZE_AUDIT_PG_DSN not set)"
                )
            self._audit_log_service = service
        return self._audit_log_service

    def agent_auth_service(self) -> Any:
        """Get or create AgentAuthService singleton for MCP."""
        if self._agent_auth_service is None:
            from .services.agent_auth_service import AgentAuthService
            from .telemetry import TelemetryClient

            # AgentAuthService uses PostgreSQL; prefer AMPREALIZE_AGENTAUTH_PG_DSN env override when set
            dsn = os.environ.get("AMPREALIZE_AGENTAUTH_PG_DSN")
            service = AgentAuthService(dsn=dsn, telemetry=TelemetryClient.noop())
            if dsn:
                self._logger.info(
                    "Initialized AgentAuthService for MCP (PostgreSQL backend, custom DSN override)"
                )
            else:
                self._logger.info("Initialized AgentAuthService for MCP (PostgreSQL backend)")
            self._agent_auth_service = service
        return self._agent_auth_service

    def consent_service(self) -> Any:
        """Get or create ConsentService singleton for MCP.

        Phase 6: JIT (Just-In-Time) authorization consent flows.
        Uses PostgreSQL backend; resolves DSN from AMPREALIZE_CONSENT_PG_DSN or AMPREALIZE_PG_DSN.
        """
        if self._consent_service is None:
            from .auth.consent_service import ConsentService
            from .storage.postgres_pool import PostgresPool  # lazy
            from .utils.dsn import apply_host_overrides  # lazy

            dsn = apply_host_overrides(
                os.environ.get("AMPREALIZE_CONSENT_PG_DSN") or os.environ.get("AMPREALIZE_PG_DSN"),
                "CONSENT"
            )
            if not dsn:
                # Fallback DSN for local development
                dsn = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize"
                self._logger.warning("Using default ConsentService DSN (AMPREALIZE_CONSENT_PG_DSN not set)")

            pool = PostgresPool(dsn)
            service = ConsentService(pool=pool)
            self._logger.info("Initialized ConsentService for MCP (PostgreSQL backend)")
            self._consent_service = service
        return self._consent_service

    def task_assignment_service(self) -> Any:
        """Get or create TaskService singleton for MCP (replaces stub)."""
        if self._task_assignment_service is None:
            from .services.task_service import TaskService

            # TaskService uses PostgreSQL telemetry database
            # Priority order: AMPREALIZE_TASK_PG_DSN -> AMPREALIZE_TELEMETRY_PG_DSN -> legacy default
            dsn_source = "AMPREALIZE_TASK_PG_DSN"
            dsn = os.environ.get("AMPREALIZE_TASK_PG_DSN")

            if not dsn:
                dsn = os.environ.get("AMPREALIZE_TELEMETRY_PG_DSN")
                dsn_source = "AMPREALIZE_TELEMETRY_PG_DSN"

            if not dsn:
                dsn = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize"
                dsn_source = "default_amprealize_db"
                self._logger.warning(
                    "TaskService falling back to default amprealize DSN; set "
                    "AMPREALIZE_TASK_PG_DSN for custom configuration"
                )

            service = TaskService(dsn=dsn)
            self._logger.info(
                "Initialized TaskService for MCP (PostgreSQL backend, dsn_source=%s)",
                dsn_source,
            )
            self._task_assignment_service = service
        return self._task_assignment_service

    def fine_tuning_service(self) -> Any:
        """Get or create MidnighterService singleton for MCP."""
        if self._fine_tuning_service is None:
            from .midnighter import create_midnighter_service

            # Pass the shared BehaviorService so midnighter can retrieve behaviors
            service = create_midnighter_service(
                behavior_service=self.behavior_service(),
            )
            self._logger.info("Initialized MidnighterService for MCP (with shared BehaviorService)")
            self._fine_tuning_service = service
        return self._fine_tuning_service

    def agent_review_service(self) -> Any:
        """Get or create AgentReviewService singleton for MCP."""
        if self._agent_review_service is None:
            from .agent_review_service import AgentReviewService

            service = AgentReviewService()
            self._logger.info("Initialized AgentReviewService for MCP (in-memory mode)")
            self._agent_review_service = service
        return self._agent_review_service

    def multi_tenant_service(self) -> Any:
        """Get or create MultiTenantService singleton for MCP."""
        if self._multi_tenant_service is None:
            from .multi_tenant_service import MultiTenantService

            service = MultiTenantService()
            self._logger.info("Initialized MultiTenantService for MCP (in-memory mode)")
            self._multi_tenant_service = service
        return self._multi_tenant_service

    def advanced_retrieval_service(self) -> Any:
        """Get or create AdvancedRetrievalService singleton for MCP."""
        if self._advanced_retrieval_service is None:
            from .advanced_retrieval_service import AdvancedRetrievalService

            service = AdvancedRetrievalService()
            self._logger.info("Initialized AdvancedRetrievalService for MCP (in-memory mode)")
            self._advanced_retrieval_service = service
        return self._advanced_retrieval_service

    def collaboration_service(self) -> Any:
        """Get or create CollaborationService singleton for MCP.

        Uses PostgreSQL backend when AMPREALIZE_COLLABORATION_PG_DSN is set,
        otherwise falls back to in-memory implementation.
        """
        if self._collaboration_service is None:
            from .utils.dsn import apply_host_overrides  # lazy

            dsn = apply_host_overrides(os.environ.get("AMPREALIZE_COLLABORATION_PG_DSN"), "COLLABORATION")
            if dsn:
                from .collaboration_service_postgres import PostgresCollaborationService
                from .telemetry import TelemetryClient

                service = PostgresCollaborationService(dsn=dsn, telemetry=TelemetryClient.noop())
                self._logger.info("Initialized PostgresCollaborationService for MCP (PostgreSQL backend)")
            else:
                from .collaboration_service import CollaborationService
                service = CollaborationService()
                self._logger.info("Initialized CollaborationService for MCP (in-memory mode)")
            self._collaboration_service = service
        return self._collaboration_service

    def reflection_service(self) -> Any:
        """Get or create ReflectionService singleton for MCP.

        Uses PostgreSQL backend when AMPREALIZE_REFLECTION_PG_DSN is set,
        otherwise falls back to in-memory implementation.
        """
        if self._reflection_service is None:
            from .utils.dsn import apply_host_overrides  # lazy

            dsn = apply_host_overrides(os.environ.get("AMPREALIZE_REFLECTION_PG_DSN"), "REFLECTION")
            if dsn:
                from .reflection_service_postgres import PostgresReflectionService
                from .telemetry import TelemetryClient

                service = PostgresReflectionService(
                    dsn=dsn,
                    behavior_service=self.behavior_service(),
                    bci_service=self.bci_service(),
                    telemetry=TelemetryClient.noop(),
                )
                self._logger.info("Initialized PostgresReflectionService for MCP (PostgreSQL backend)")
            else:
                from .reflection_service import ReflectionService
                service = ReflectionService(
                    behavior_service=self.behavior_service(),
                    bci_service=self.bci_service(),
                )
                self._logger.info("Initialized ReflectionService for MCP (in-memory mode)")
            self._reflection_service = service
        return self._reflection_service

    def api_rate_limiting_service(self) -> Any:
        """Get or create APIRateLimitingService singleton for MCP."""
        if self._api_rate_limiting_service is None:
            from .api_rate_limiting_service import APIRateLimitingService

            service = APIRateLimitingService()
            self._logger.info("Initialized APIRateLimitingService for MCP (in-memory mode)")
            self._api_rate_limiting_service = service
        return self._api_rate_limiting_service

    def raze_service(self) -> Any:
        """Get or create RazeService singleton for MCP structured logging."""
        if self._raze_service is None:
            try:
                from raze import RazeService
                from raze.sinks import InMemorySink

                # Check for TimescaleDB configuration
                raze_dsn = os.environ.get("RAZE_TIMESCALEDB_DSN") or os.environ.get("AMPREALIZE_RAZE_DSN")
                if raze_dsn:
                    try:
                        from raze.sinks import TimescaleDBSink
                        sink = TimescaleDBSink(dsn=raze_dsn)
                        self._logger.info("Initialized RazeService for MCP (TimescaleDB backend)")
                    except Exception as e:
                        self._logger.warning(f"TimescaleDB unavailable, using in-memory sink: {e}")
                        sink = InMemorySink()
                else:
                    sink = InMemorySink()
                    self._logger.info("Initialized RazeService for MCP (in-memory mode)")

                self._raze_service = RazeService(
                    sink=sink,
                    service_name="amprealize-mcp",
                    batch_size=1000,
                    linger_ms=100,
                )
            except ImportError:
                self._logger.warning("Raze package not installed, raze tools unavailable")
                self._raze_service = None
        return self._raze_service

    def organization_service(self) -> Any:
        """Get or create OrganizationService singleton for MCP."""
        if self._organization_service is None:
            from .multi_tenant.organization_service import OrganizationService
            from .utils.dsn import apply_host_overrides  # lazy

            dsn = apply_host_overrides(
                os.environ.get("AMPREALIZE_ORG_PG_DSN") or os.environ.get("AMPREALIZE_MULTI_TENANT_PG_DSN") or os.environ.get("AMPREALIZE_PG_DSN"),
                "ORG"
            )
            if dsn:
                service = OrganizationService(dsn=dsn)
                self._logger.info("Initialized OrganizationService for MCP (PostgreSQL backend)")
            else:
                # Fallback DSN for local development - include auth schema in search_path
                service = OrganizationService(dsn="postgresql://amprealize:amprealize_dev@localhost:5432/amprealize?options=-csearch_path%3Dauth")
                self._logger.warning("Using default OrganizationService DSN (AMPREALIZE_ORG_PG_DSN not set)")
            self._organization_service = service
        return self._organization_service

    def board_service(self) -> Any:
        """Get or create BoardService singleton for MCP."""
        if self._board_service is None:
            from .services.board_service import BoardService
            from .utils.dsn import apply_host_overrides  # lazy

            dsn = apply_host_overrides(
                os.environ.get("AMPREALIZE_BOARD_PG_DSN") or os.environ.get("AMPREALIZE_PG_DSN"),
                "BOARD"
            )
            if dsn:
                service = BoardService(dsn=dsn)
                self._logger.info("Initialized BoardService for MCP (PostgreSQL backend)")
            else:
                # Fallback DSN for local development
                service = BoardService(dsn="postgresql://amprealize:amprealize_dev@localhost:5432/amprealize")
                self._logger.warning("Using default BoardService DSN (AMPREALIZE_BOARD_PG_DSN not set)")
            self._board_service = service
        return self._board_service

    def agent_registry_service(self) -> Any:
        """Get or create AgentRegistryService singleton for MCP.

        Used by agentRegistry.* tools for bootstrap, publish, search operations.
        """
        if self._agent_registry_service is None:
            from .agent_registry_service import AgentRegistryService
            from .telemetry import TelemetryClient
            from .utils.dsn import apply_host_overrides  # lazy

            dsn = apply_host_overrides(
                os.environ.get("AMPREALIZE_AGENT_REGISTRY_PG_DSN") or os.environ.get("AMPREALIZE_PG_DSN"),
                "AGENT_REGISTRY"
            )
            if dsn:
                service = AgentRegistryService(dsn=dsn, telemetry=TelemetryClient.noop())
                self._logger.info("Initialized AgentRegistryService for MCP (PostgreSQL backend)")
            else:
                # Fallback DSN for local development
                service = AgentRegistryService(
                    dsn="postgresql://amprealize:amprealize_dev@localhost:5432/amprealize",
                    telemetry=TelemetryClient.noop(),
                )
                self._logger.warning("Using default AgentRegistryService DSN (AMPREALIZE_AGENT_REGISTRY_PG_DSN not set)")
            self._agent_registry_service = service
        return self._agent_registry_service

    def github_service(self) -> Any:
        """Get or create GitHubService singleton for MCP.

        Used by github.* tools for PR and commit operations.
        Uses GITHUB_TOKEN or GH_TOKEN environment variable for authentication.
        """
        if self._github_service is None:
            from .services.github_service import GitHubService

            service = GitHubService()
            self._logger.info("Initialized GitHubService for MCP")
            self._github_service = service
        return self._github_service

    def credential_store(self) -> Any:
        """Get or create CredentialStore singleton for MCP.

        Used by config.* tools for model availability queries.
        Manages LLM provider credentials at platform/org/project scope.
        """
        if self._credential_store is None:
            from .work_item_execution_service import CredentialStore
            from .auth.llm_credential_repository import LLMCredentialRepository
            from .utils.dsn import apply_host_overrides  # lazy

            # CredentialStore needs LLMCredentialRepository for BYOK credentials
            # Get DSN from environment for database access
            dsn = apply_host_overrides(
                os.environ.get("AMPREALIZE_PG_DSN"),
                "CREDENTIAL_STORE"
            )
            if not dsn:
                dsn = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize"

            from .storage.postgres_pool import PostgresPool
            pool = PostgresPool(dsn)
            credential_repo = LLMCredentialRepository(pool=pool)

            # CredentialStore loads platform credentials from environment
            # and can resolve org/project BYOK credentials from database
            store = CredentialStore(pool=pool, credential_repository=credential_repo)
            self._logger.info("Initialized CredentialStore for MCP with LLMCredentialRepository")
            self._credential_store = store
        return self._credential_store

    def research_service(self) -> Any:
        """Get or create ResearchService singleton for MCP.

        Used by research.* tools for AI paper evaluation, search, and retrieval.
        Uses PostgreSQL when AMPREALIZE_RESEARCH_PG_DSN or AMPREALIZE_PG_DSN is set,
        falls back to SQLite for local storage.
        """
        if self._research_service is None:
            from .research_service import ResearchService
            from .utils.dsn import apply_host_overrides  # lazy

            dsn = apply_host_overrides(
                os.environ.get("AMPREALIZE_RESEARCH_PG_DSN") or os.environ.get("AMPREALIZE_PG_DSN"),
                "RESEARCH"
            )
            if dsn:
                pool = self._get_pool(dsn, "research")
                service = ResearchService(pool=pool)
                self._logger.info("Initialized ResearchService for MCP (PostgreSQL backend)")
            else:
                service = ResearchService()
                self._logger.info("Initialized ResearchService for MCP (SQLite backend)")
            self._research_service = service
        return self._research_service

    def conversation_service(self) -> Any:
        """Get or create ConversationService singleton for MCP.

        Provides conversation and messaging operations (AMPREALIZE-573).
        """
        if self._conversation_service is None:
            from .services.conversation_service import ConversationService
            from .utils.dsn import apply_host_overrides  # lazy

            dsn = apply_host_overrides(
                os.environ.get("AMPREALIZE_MESSAGING_PG_DSN") or os.environ.get("AMPREALIZE_PG_DSN"),
                "MESSAGING"
            )
            if dsn:
                service = ConversationService(dsn=dsn)
                self._logger.info("Initialized ConversationService for MCP (PostgreSQL backend)")
            else:
                service = ConversationService(
                    dsn="postgresql://amprealize:amprealize_dev@localhost:5432/amprealize"
                )
                self._logger.warning("Using default ConversationService DSN (AMPREALIZE_MESSAGING_PG_DSN not set)")
            self._conversation_service = service
        return self._conversation_service

    def llm_client(self) -> Any:
        """Get or create LLMClient singleton for MCP.

        Unified LLM client for all provider interactions.
        Supports sync and async modes with cost/token tracking.
        """
        if self._llm_client is None:
            from .llm.client import LLMClient

            # Create credential resolver from credential store if available
            credential_resolver = None
            if self._credential_store is not None:
                def _resolver(provider: str, project_id: str = None, org_id: str = None) -> Optional[str]:
                    store = self._credential_store
                    # Try provider-specific key first
                    key = store.get(f"{provider.upper()}_API_KEY")
                    if key:
                        return key
                    # Fall back to generic API key
                    return store.get("OPENAI_API_KEY") or store.get("ANTHROPIC_API_KEY")
                credential_resolver = _resolver

            client = LLMClient(credential_resolver=credential_resolver)
            self._logger.info("Initialized LLMClient for MCP")
            self._llm_client = client
        return self._llm_client

    def context_composer(self) -> Any:
        """Get or create ContextComposer singleton for MCP.

        Assembles context from six data sources (conversation history, user profile,
        behavior guidance, work items, runs, external references) with token budget.
        """
        if self._context_composer is None:
            from .context_composer import ContextComposer

            composer = ContextComposer(
                telemetry=self.telemetry_client(),
            )
            self._logger.info("Initialized ContextComposer for MCP")
            self._context_composer = composer
        return self._context_composer

    def conversation_reply_service(self) -> Any:
        """Get or create ConversationReplyService singleton for MCP.

        Orchestrates context-aware agent replies in conversations using ContextComposer.
        Implements AMPREALIZE-581 integration of ContextComposer with conversation replies.
        """
        if self._conversation_reply_service is None:
            from .services.conversation_reply_service import ConversationReplyService

            service = ConversationReplyService(
                context_composer=self.context_composer(),
                conversation_service=self.conversation_service(),
                llm_client=self.llm_client(),
                telemetry=self.telemetry_client(),
            )
            self._logger.info("Initialized ConversationReplyService for MCP")
            self._conversation_reply_service = service
        return self._conversation_reply_service

    def work_item_execution_service(self) -> Any:
        """Get or create WorkItemExecutionService singleton for MCP.

        Orchestrates the Amprealize execution protocol (GEP) for work item execution
        through 8 phases: PLANNING → CLARIFYING → ARCHITECTING → EXECUTING →
        TESTING → FIXING → VERIFYING → COMPLETING.

        Uses wire_execution_service to connect AgentExecutionLoop + AgentLLMClient
        for real agent execution.
        """
        if self._work_item_execution_service is None:
            from .execution_wiring import wire_execution_service
            from .utils.dsn import apply_host_overrides  # lazy

            # WorkItemExecutionService needs PostgreSQL for execution state
            dsn = apply_host_overrides(
                os.environ.get("AMPREALIZE_EXECUTION_PG_DSN") or os.environ.get("AMPREALIZE_PG_DSN"),
                "EXECUTION"
            )
            if not dsn:
                # Fallback DSN for local development
                dsn = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize"
                self._logger.warning("Using default WorkItemExecutionService DSN (AMPREALIZE_EXECUTION_PG_DSN not set)")

            # Use wire_execution_service to create fully-wired service
            # This connects AgentExecutionLoop + AgentLLMClient for real execution
            service = wire_execution_service(
                dsn=dsn,
                run_service=self.run_service(),
                telemetry=self.telemetry_client(),
            )
            self._logger.info("Initialized WorkItemExecutionService for MCP with AgentExecutionLoop wired")
            self._work_item_execution_service = service
        return self._work_item_execution_service


class MCPServer:
    """
    Amprealize MCP server implementing JSON-RPC 2.0 over stdio.

    Handles tool discovery, capability negotiation, and tool execution
    for device flow authentication and future Amprealize capabilities.
    """

    # JSON-RPC error codes
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    RATE_LIMITED = -32000  # Custom code for rate limiting
    AUTH_REQUIRED = -32001  # Custom code for authentication required
    ACCESS_DENIED = -32003  # Custom code for authorization denied

    def __init__(self) -> None:
        """Initialize MCP server with tool handlers."""
        self._setup_logging()
        self._logger = logging.getLogger("amprealize.mcp_server")
        self._services = MCPServiceRegistry(logger=self._logger)

        # Session context for authentication (Phase 1: MCP_AUTH_IMPLEMENTATION_PLAN.md)
        self._session_context = MCPSessionContext()

        # Stdio framing mode detection.
        # Some MCP clients (including VS Code/Copilot) use LSP-style Content-Length framing.
        # Keep backward compatibility with line-delimited JSON used by older/manual clients.
        self._stdio_framing: Literal["unknown", "newline", "content-length"] = "unknown"

        # Initialize rate limiter for abuse prevention (docs/contracts/MCP_SERVER_DESIGN.md §9)
        from .mcp_rate_limiter import MCPRateLimiter, DistributedRateLimiter
        self._rate_limiter = MCPRateLimiter()
        # Only create distributed limiter when rate limiting is enabled
        _rl_enabled = os.environ.get("MCP_RATE_LIMIT_ENABLED", "true").lower() not in ("false", "0", "no", "off")
        self._distributed_rate_limiter = DistributedRateLimiter() if _rl_enabled else None  # Phase 5: Redis-backed
        self._client_id: Optional[str] = None  # Set during initialize

        # Connection stability (Epic 6 - MCP Server Stability)
        self._shutdown_requested = False
        self._pending_requests: Dict[str, asyncio.Task[Any]] = {}
        self._last_activity = time.time()
        self._idle_timeout_seconds = float(os.environ.get("MCP_IDLE_TIMEOUT", "3600"))  # 1 hour default
        self._idle_check_task: Optional[asyncio.Task[Any]] = None
        self._graceful_shutdown_timeout = float(os.environ.get("MCP_SHUTDOWN_TIMEOUT", "30"))  # 30s default

        # Optional pre-warm. Disabled by default to avoid startup hangs when DB/network is slow.
        self._prewarm_pools_on_startup = os.environ.get("MCP_PREWARM_POOLS", "false").lower() == "true"
        if self._prewarm_pools_on_startup:
            self._logger.info("Pre-warming PostgreSQL connection pools...")
            self._services.prewarm_pools()
        else:
            self._logger.info("Skipping PostgreSQL pool prewarm on startup (MCP_PREWARM_POOLS=false)")

        # Initialize PostgreSQL device flow store for shared auth state
        self._postgres_device_store = None
        try:
            auth_dsn = os.environ.get("AMPREALIZE_AUTH_PG_DSN") or os.environ.get("AMPREALIZE_ORG_PG_DSN") or os.environ.get("AMPREALIZE_MULTI_TENANT_PG_DSN") or os.environ.get("AMPREALIZE_PG_DSN")
            if auth_dsn:
                from .auth.postgres_device_flow import PostgresDeviceFlowStore
                # Ensure auth schema is used
                if "search_path" not in auth_dsn:
                    if "?" in auth_dsn:
                        auth_dsn = f"{auth_dsn}&options=-c%20search_path%3Dauth"
                    else:
                        auth_dsn = f"{auth_dsn}?options=-c%20search_path%3Dauth"
                auth_dsn = _ensure_dsn_param(auth_dsn, "connect_timeout", os.environ.get("MCP_DB_CONNECT_TIMEOUT_SECONDS", "3"))
                from .storage.postgres_pool import PostgresPool as _PgPool  # lazy
                auth_pool = _PgPool(dsn=auth_dsn, service_name="device_auth")
                self._postgres_device_store = PostgresDeviceFlowStore(pool=auth_pool)
                self._logger.info("PostgreSQL device flow store initialized for shared auth state")
            else:
                self._logger.warning("No PostgreSQL DSN available - using in-memory device flow (not shared with API)")
        except Exception as e:
            self._logger.error(f"Failed to initialize PostgreSQL device flow store: {e}")
            self._postgres_device_store = None

        # Import device flow handler
        try:
            from .mcp_device_flow import MCPDeviceFlowHandler, MCPDeviceFlowService

            # Initialize service with optional AgentAuthService integration and PostgreSQL store.
            # Eager agent auth service init can trigger DB work, so keep it opt-in.
            eager_agent_auth = os.environ.get("MCP_EAGER_AGENT_AUTH_SERVICE", "false").lower() == "true"
            agent_auth_service = self._services.agent_auth_service() if eager_agent_auth else None
            device_flow_service = MCPDeviceFlowService(
                agent_auth_service=agent_auth_service,
                postgres_store=self._postgres_device_store,
            )
            self._device_flow_handler = MCPDeviceFlowHandler(service=device_flow_service)

            # Session restore can touch DB/keychain and block in constrained environments.
            # Keep it opt-in so public auth/context tools return promptly.
            self._restore_session_on_startup = os.environ.get("MCP_RESTORE_SESSION_ON_STARTUP", "false").lower() == "true"
            if self._restore_session_on_startup:
                self._try_restore_session_from_tokens()
            else:
                self._logger.info("Skipping session restore on startup (MCP_RESTORE_SESSION_ON_STARTUP=false)")
        except ImportError as e:
            self._logger.error(f"Failed to import device flow handler: {e}")
            self._device_flow_handler = None

        # Import task handler
        try:
            from .mcp_task_handler import MCPTaskHandler

            # Initialize handler with TaskService integration
            self._task_handler = MCPTaskHandler(task_service=self._services.task_assignment_service())
        except ImportError as e:
            self._logger.error(f"Failed to import task handler: {e}")
            self._task_handler = None
        except Exception as e:
            self._logger.warning(f"TaskService unavailable (non-fatal): {e}")
            self._task_handler = None

        # Initialize BreakerAmp adapter lazily to avoid heavy adapters.py import chain
        self._breakeramp_adapter = None  # lazy: created on first use via _get_breakeramp_adapter()

        # Tool registry - now using lazy loader for <128 tool limit compliance
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._tool_scopes: Dict[str, List[str]] = {}  # Phase 3: tool_name -> required_scopes

        # Initialize lazy tool loader (MCP best practices: stay under 128 tools)
        from .mcp_lazy_loader import MCPLazyToolLoader
        self._lazy_loader = MCPLazyToolLoader(logger=self._logger)

        # Check if lazy loading is enabled (can be disabled for backwards compatibility)
        self._lazy_loading_enabled = os.environ.get("MCP_LAZY_LOADING", "true").lower() == "true"

        if self._lazy_loading_enabled:
            # Use lazy loader - only loads core tools + outcome tools initially
            # Apply module gating to filter tools by enabled modules
            try:
                from amprealize.config.loader import get_config
                from amprealize.module_registry import (
                    get_enabled_mcp_tool_prefixes,
                    get_all_module_mcp_prefixes,
                )
                _mod_cfg = get_config().modules
                self._lazy_loader.set_module_filter(
                    enabled_prefixes=get_enabled_mcp_tool_prefixes(_mod_cfg),
                    all_module_prefixes=get_all_module_mcp_prefixes(),
                )
            except Exception:
                pass  # No config yet — allow all tools

            self._lazy_loader.initialize()
            self._tools = self._lazy_loader.get_active_tools()
            self._tool_scopes = self._lazy_loader.get_tool_scopes()
        else:
            # Legacy mode - load all tools (may exceed 128 limit)
            self._load_tool_manifests()

        # Initialize long-running operation handler with keepalive support
        from .mcp_long_running import MCPLongRunningHandler
        self._long_running_handler = MCPLongRunningHandler(
            progress_callback=self._send_notification,
            logger=self._logger,
        )

        # Performance metrics
        self._metrics = {
            "requests_total": 0,
            "requests_by_method": {},
            "tool_calls_total": 0,
            "tool_calls_by_name": {},
            "tool_latency_seconds": {},
            "errors_total": 0,
            "batch_requests_total": 0,
            "tool_groups_activated": 0,
            "tool_groups_deactivated": 0,
        }

        self._logger.info(
            f"Amprealize MCP Server initialized with {len(self._tools)} active tools "
            f"(lazy_loading={'enabled' if self._lazy_loading_enabled else 'disabled'})"
        )

    def _get_breakeramp_adapter(self) -> Any:
        """Lazy-init the BreakerAmp adapter to avoid loading adapters.py at startup."""
        if self._breakeramp_adapter is None:
            try:
                from .adapters import MCPBreakerAmpAdapter
                self._breakeramp_adapter = MCPBreakerAmpAdapter(
                    service=self._services.breakeramp_service()
                )
            except Exception as e:
                self._logger.error(f"Failed to initialize BreakerAmp adapter: {e}")
        return self._breakeramp_adapter

    def _setup_logging(self) -> None:
        """Configure structured logging to stderr."""
        logging.basicConfig(
            level=logging.INFO,
            format='{"timestamp":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
            stream=sys.stderr,
        )

    def _write_stdout_message(self, message: str) -> None:
        """Write a JSON-RPC message to stdout using the active framing mode."""
        if self._stdio_framing == "content-length":
            body = message.encode("utf-8")
            header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
            sys.stdout.buffer.write(header)
            sys.stdout.buffer.write(body)
            sys.stdout.buffer.flush()
        else:
            # Default to newline-delimited framing.
            sys.stdout.write(message + "\n")
            sys.stdout.flush()

    def _read_stdin_message_blocking(self) -> Optional[str]:
        """Read a single JSON-RPC message from stdin.

        Supports either:
        - newline-delimited JSON (one JSON object per line), or
        - LSP-style Content-Length framing.

        Returns:
            The raw JSON string payload, or None on EOF.
        """
        buf = sys.stdin.buffer

        while True:
            first_line = buf.readline()
            if first_line == b"":
                return None

            # Ignore empty lines (common in content-length framing between messages).
            if first_line in (b"\r\n", b"\n") or first_line.strip() == b"":
                if self._stdio_framing == "newline":
                    continue
                # In unknown/content-length mode, treat blank lines as separators.
                continue

            # Detect framing if unknown.
            if self._stdio_framing == "unknown":
                stripped = first_line.lstrip()
                if stripped.lower().startswith(b"content-length:"):
                    self._stdio_framing = "content-length"
                elif stripped.startswith(b"{") or stripped.startswith(b"["):
                    self._stdio_framing = "newline"
                    return first_line.decode("utf-8", errors="replace").strip()
                else:
                    # Unknown/noise line. Keep scanning.
                    continue

            if self._stdio_framing == "newline":
                return first_line.decode("utf-8", errors="replace").strip()

            # Content-Length framing.
            headers: Dict[str, str] = {}
            header_line = first_line

            while True:
                if header_line in (b"\r\n", b"\n", b""):
                    break
                try:
                    decoded = header_line.decode("utf-8", errors="replace")
                    key, value = decoded.split(":", 1)
                    headers[key.strip().lower()] = value.strip()
                except ValueError:
                    # Malformed header; ignore.
                    pass

                header_line = buf.readline()
                if header_line == b"":
                    return None

            content_length_value = headers.get("content-length")
            if not content_length_value:
                self._logger.warning("Missing Content-Length header; falling back to newline framing")
                self._stdio_framing = "newline"
                continue

            try:
                content_length = int(content_length_value)
            except ValueError:
                self._logger.warning("Invalid Content-Length header; falling back to newline framing")
                self._stdio_framing = "newline"
                continue

            body = buf.read(content_length)
            if body == b"":
                return None

            return body.decode("utf-8", errors="replace")

    def _normalize_tool_name(self, name: str) -> str:
        """Normalize tool name to be VS Code MCP compliant.

        VS Code currently validates tool names against: [a-z0-9_-]
        """
        normalized = name.replace(".", "_").replace("/", "_")
        normalized = normalized.lower()
        normalized = re.sub(r"[^a-z0-9_-]", "_", normalized)
        return normalized

    def _resolve_json_refs(
        self, obj: Any, base_path: Path, root_doc: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Recursively resolve $ref references in JSON schema objects.

        This inlines external and internal $ref references so VS Code/Copilot can
        understand the tool schemas without needing to resolve file paths.

        Args:
            obj: The JSON object to process
            base_path: The base path for resolving relative $ref paths
            root_doc: The root document for resolving internal #/ refs

        Returns:
            The object with all $ref references resolved/inlined
        """
        if isinstance(obj, dict):
            # Check if this is a $ref that needs resolution
            if "$ref" in obj and isinstance(obj["$ref"], str):
                ref = obj["$ref"]

                # Handle internal refs like #/definitions/BehaviorSnippet
                if ref.startswith("#/") and root_doc is not None:
                    try:
                        parts = ref[2:].split("/")  # Remove leading #/
                        target = root_doc
                        for part in parts:
                            if isinstance(target, dict) and part in target:
                                target = target[part]
                            else:
                                # Can't resolve internal pointer
                                return {"type": "object", "additionalProperties": True}
                        # Recursively resolve, but don't infinitely loop on same ref
                        return self._resolve_json_refs(target, base_path, root_doc)
                    except Exception:
                        return {"type": "object", "additionalProperties": True}

                # Handle file-based external refs (includes bare filenames like "trace.json#...")
                elif (
                    ref.startswith("../../")
                    or ref.startswith("../")
                    or ref.startswith("./")
                    or (ref.split("#")[0].endswith(".json") and not ref.startswith("#"))
                ):
                    try:
                        # Parse the ref: "../../schema/bci/v1/prompt.json#/definitions/ComposePromptRequest"
                        # or "trace.json#/definitions/TraceFormat"
                        if "#" in ref:
                            file_path, json_pointer = ref.split("#", 1)
                        else:
                            file_path, json_pointer = ref, ""

                        # Resolve the file path
                        resolved_path = (base_path / file_path).resolve()
                        if resolved_path.exists():
                            with open(resolved_path) as f:
                                schema_doc = json.load(f)

                            # Navigate to the referenced definition using JSON pointer
                            if json_pointer:
                                parts = json_pointer.strip("/").split("/")
                                target = schema_doc
                                for part in parts:
                                    if isinstance(target, dict) and part in target:
                                        target = target[part]
                                    else:
                                        # Can't resolve pointer, return simplified schema
                                        self._logger.warning(
                                            f"Could not resolve JSON pointer {json_pointer} in {resolved_path}"
                                        )
                                        return {"type": "object", "additionalProperties": True}

                                # Recursively resolve any nested $refs, using schema_doc as root
                                return self._resolve_json_refs(target, resolved_path.parent, schema_doc)
                            else:
                                return self._resolve_json_refs(schema_doc, resolved_path.parent, schema_doc)
                        else:
                            self._logger.warning(f"Referenced schema file not found: {resolved_path}")
                            return {"type": "object", "additionalProperties": True}
                    except Exception as e:
                        self._logger.warning(f"Failed to resolve $ref {ref}: {e}")
                        return {"type": "object", "additionalProperties": True}

            # Process all keys in the dict, resolving any nested $refs
            return {k: self._resolve_json_refs(v, base_path, root_doc) for k, v in obj.items()}

        elif isinstance(obj, list):
            return [self._resolve_json_refs(item, base_path, root_doc) for item in obj]

        return obj

    def _load_tool_manifests(self) -> None:
        """Load MCP tool manifests from the monorepo or bundled wheel directory."""
        mcp_tools_dir = get_mcp_tools_directory()

        if not mcp_tools_dir:
            self._logger.warning("MCP tools directory not found (monorepo mcp/tools or bundled manifests)")
            return

        # Load all .json tool manifests
        for manifest_path in mcp_tools_dir.glob("*.json"):
            try:
                with open(manifest_path) as f:
                    manifest = json.load(f)

                original_name = manifest.get("name")
                if not original_name:
                    self._logger.warning(f"Tool manifest missing 'name': {manifest_path}")
                    continue

                # Normalize tool name for MCP compliance (VS Code only allows [a-z0-9_-])
                tool_name = self._normalize_tool_name(original_name)
                manifest["name"] = tool_name  # Update manifest with normalized name
                manifest["_original_name"] = original_name  # Keep original for handler lookup

                # Resolve $ref references in inputSchema so VS Code/Copilot can parse them
                if "inputSchema" in manifest:
                    manifest["inputSchema"] = self._resolve_json_refs(
                        manifest["inputSchema"], manifest_path.parent
                    )

                if tool_name in self._tools:
                    existing_original = self._tools[tool_name].get("_original_name")
                    if existing_original != original_name:
                        self._logger.error(
                            "Tool name collision after normalization: "
                            f"{original_name} -> {tool_name} conflicts with {existing_original}"
                        )
                        continue

                self._tools[tool_name] = manifest

                # Extract required_scopes for authorization (Phase 3)
                required_scopes = manifest.get("required_scopes", [])
                if required_scopes:
                    self._tool_scopes[tool_name] = required_scopes

                self._logger.info(f"Loaded tool: {tool_name}")

            except Exception as e:
                self._logger.error(f"Failed to load tool manifest {manifest_path}: {e}")

    async def handle_request(self, request_line: str) -> Optional[str]:
        """
        Handle a single JSON-RPC request or batch request.

        Args:
            request_line: JSON-RPC request as string (single or array)

        Returns:
            JSON-RPC response as string, or None for notifications
        """
        try:
            request_data = json.loads(request_line)
        except json.JSONDecodeError as e:
            return self._error_response(
                None,
                self.PARSE_ERROR,
                f"Parse error: {e}",
            )

        # Handle batch requests (array of requests)
        if isinstance(request_data, list):
            return await self._handle_batch_request(request_data)

        # Handle single request
        return await self._handle_single_request(request_data)

    async def _handle_batch_request(self, requests: List[Dict[str, Any]]) -> str:
        """
        Handle a batch of JSON-RPC requests in parallel.

        Args:
            requests: List of JSON-RPC request objects

        Returns:
            JSON array of responses
        """
        self._logger.info(f"Handling batch request with {len(requests)} items")

        # Process all requests in parallel
        tasks = [self._handle_single_request(req) for req in requests]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to error responses
        results = []
        for i, response in enumerate(responses):
            if isinstance(response, Exception):
                request_id = requests[i].get("id")
                error_response = self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Batch item {i} failed: {str(response)}",
                )
                results.append(json.loads(error_response))
            elif response and isinstance(response, str):  # Skip None (notifications)
                results.append(json.loads(response))

        return json.dumps(results)

    async def _handle_single_request(self, request_data: Dict[str, Any]) -> Optional[str]:
        """
        Handle a single JSON-RPC request.

        Args:
            request_data: Parsed JSON-RPC request object

        Returns:
            JSON-RPC response as string, or None for notifications
        """
        request_id = request_data.get("id")
        method = request_data.get("method")
        params = request_data.get("params", {})

        # JSON-RPC 2.0: Notifications have no "id" field and expect no response
        # Per spec, notifications MUST NOT receive a response (not even an error)
        if request_id is None:
            self._logger.debug(f"Received notification: {method} (no response expected)")
            return None

        self._logger.info(f"Received request: method={method}, id={request_id}")

        # Handle MCP protocol methods
        if method == "initialize":
            return self._handle_initialize(request_id, params)
        elif method == "tools/list":
            return self._handle_tools_list(request_id)
        elif method == "tools/call":
            return await self._handle_tools_call(request_id, params)
        elif method in ("resources/list", "resources/templates/list"):
            return self._success_response(request_id, {"resources": []})
        elif method == "prompts/list":
            return self._success_response(request_id, {"prompts": []})
        elif method == "ping":
            return self._success_response(request_id, {"status": "ok"})
        elif method == "health":
            return self._success_response(request_id, self.get_health_status())
        elif method == "metrics":
            return self._success_response(request_id, self.get_metrics_summary())
        else:
            return self._error_response(
                request_id,
                self.METHOD_NOT_FOUND,
                f"Method not found: {method}",
            )

    def _handle_initialize(self, request_id: Optional[str], params: Dict[str, Any]) -> str:
        """Handle MCP initialize request."""
        client_info = params.get("clientInfo", {})
        self._logger.info(f"Client connected: {client_info}")

        # Capture client ID for rate limiting
        # Use client name + version as unique identifier, fallback to session
        client_name = client_info.get("name", "unknown")
        client_version = client_info.get("version", "0.0.0")
        self._client_id = f"{client_name}:{client_version}:{id(self)}"
        self._logger.info(f"Rate limiter client ID: {self._client_id}")

        result = {
            "protocolVersion": "2024-11-05",
            "serverInfo": {
                "name": "amprealize",
                "version": "0.1.0",
            },
            "capabilities": {
                "tools": {
                    "listChanged": False,
                },
            },
        }

        return self._success_response(request_id, result)

    async def _send_notification(self, method: str, params: Dict[str, Any]) -> None:
        """Send an MCP notification (no response expected).

        Used for progress updates, keepalive heartbeats, etc.
        """
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        self._write_stdout_message(json.dumps(notification))

    def _handle_tools_list(self, request_id: Optional[str]) -> str:
        """Handle MCP tools/list request.

        Returns currently active tools. With lazy loading enabled,
        this returns core tools + any activated groups.
        """
        # Refresh tools from lazy loader if enabled
        if self._lazy_loading_enabled:
            self._tools = self._lazy_loader.get_active_tools()
            self._tool_scopes = self._lazy_loader.get_tool_scopes()

        tools_list = []

        for tool_name, manifest in self._tools.items():
            tools_list.append({
                "name": tool_name,
                "description": manifest.get("description", ""),
                "inputSchema": manifest.get("inputSchema", {}),
            })

        # Add metadata about lazy loading
        result = {
            "tools": tools_list,
        }

        # Include lazy loading stats if enabled
        if self._lazy_loading_enabled:
            stats = self._lazy_loader.get_stats()
            result["_meta"] = {
                "active_tools": stats["active_tools"],
                "total_available": stats["total_available_tools"],
                "active_groups": stats["active_groups"],
                "headroom": stats["headroom"],
                "lazy_loading": True,
            }

        return self._success_response(request_id, result)

    async def _handle_tools_call(self, request_id: Optional[str], params: Dict[str, Any]) -> str:
        """Handle MCP tools/call request with rate limiting, timeout, and latency tracking."""
        from .mcp_rate_limiter import RateLimitDecision
        import uuid as uuid_module

        # Generate unique trace ID for this tool call (for debugging hangs)
        trace_id = str(uuid_module.uuid4())[:8]

        tool_name = params.get("name")
        tool_params = params.get("arguments", {})

        self._logger.debug(f"[{trace_id}] TOOL_CALL_START: {tool_name}, request_id={request_id}")

        if not tool_name:
            self._logger.warning(f"[{trace_id}] TOOL_CALL_ERROR: Missing tool name")
            return self._error_response(
                request_id,
                self.INVALID_PARAMS,
                "Missing required parameter: name",
            )

        # Apply rate limiting (docs/contracts/MCP_SERVER_DESIGN.md §9)
        client_id = self._client_id or f"anonymous:{id(self)}"
        self._logger.debug(f"[{trace_id}] RATE_LIMIT_CHECK: client={client_id}, tool={tool_name}")
        rate_result = self._rate_limiter.check(client_id, tool_name)

        if rate_result.decision == RateLimitDecision.DENY:
            self._logger.warning(
                f"Rate limit blocked: client={client_id}, tool={tool_name}, "
                f"rule={rate_result.rule_name}, retry_after={rate_result.retry_after_seconds}"
            )
            return self._error_response(
                request_id,
                self.RATE_LIMITED,
                rate_result.message,
                data={
                    "retry_after_seconds": rate_result.retry_after_seconds,
                    "remaining_tokens": rate_result.remaining_tokens,
                    "rule": rate_result.rule_name,
                },
            )
        elif rate_result.decision == RateLimitDecision.WARN:
            self._logger.info(
                f"Rate limit warning: client={client_id}, tool={tool_name}, "
                f"remaining={rate_result.remaining_tokens:.2f}"
            )

        # Start timing
        start_time = time.time()

        self._logger.info(f"[{trace_id}] TOOL_DISPATCH_START: {tool_name}")
        self._logger.debug(f"[{trace_id}] TOOL_PARAMS: {tool_params}")

        # Increment counters
        self._metrics["tool_calls_total"] += 1
        self._metrics["tool_calls_by_name"][tool_name] = self._metrics["tool_calls_by_name"].get(tool_name, 0) + 1

        # Configurable timeout for tool execution (default 60s to catch hanging tools)
        tool_timeout = float(os.environ.get("MCP_TOOL_TIMEOUT_SECONDS", "60"))

        try:
            # Wrap dispatch in timeout to catch hanging tools
            self._logger.debug(f"[{trace_id}] AWAITING_DISPATCH: timeout={tool_timeout}s")
            result_str = await asyncio.wait_for(
                self._dispatch_tool_call(request_id, tool_name, tool_params, trace_id),
                timeout=tool_timeout
            )

            # Record latency
            duration = time.time() - start_time
            if tool_name not in self._metrics["tool_latency_seconds"]:
                self._metrics["tool_latency_seconds"][tool_name] = []
            self._metrics["tool_latency_seconds"][tool_name].append(duration)

            self._logger.info(f"[{trace_id}] TOOL_COMPLETE: {tool_name} in {duration:.3f}s")
            return result_str

        except asyncio.TimeoutError:
            duration = time.time() - start_time
            self._metrics["errors_total"] += 1
            self._logger.error(
                f"[{trace_id}] TOOL_TIMEOUT: {tool_name} exceeded {tool_timeout}s timeout after {duration:.3f}s"
            )
            return self._error_response(
                request_id,
                self.INTERNAL_ERROR,
                f"Tool '{tool_name}' timed out after {tool_timeout}s. Check MCP server logs for trace_id={trace_id}",
                data={"trace_id": trace_id, "timeout_seconds": tool_timeout, "duration": duration},
            )
        except Exception as e:
            self._metrics["errors_total"] += 1
            duration = time.time() - start_time
            self._logger.error(f"[{trace_id}] TOOL_ERROR: {tool_name} failed after {duration:.3f}s: {e}", exc_info=True)
            raise

    def _denormalize_tool_name(self, normalized_name: str) -> str:
        """Convert underscore-normalized tool name back to dot notation for handler dispatch.

        This reverses the normalization done in _normalize_tool_name.
        Tool names follow the pattern: namespace_action or namespace_subnamespace_action
        We need to restore the first underscore to a dot for namespace.action format.
        """
        # First check if we have the original name stored in the tool manifest
        tools = getattr(self, "_tools", {}) or {}
        if normalized_name in tools:
            tool_def = tools[normalized_name]
            if "_original_name" in tool_def:
                return tool_def["_original_name"]

        # Fallback: Convert first underscore to dot (handles namespace_action pattern)
        # This is a heuristic for tools not in manifest
        parts = normalized_name.split("_", 1)
        if len(parts) == 2:
            return f"{parts[0]}.{parts[1]}"
        return normalized_name

    async def _dispatch_tool_call(self, request_id: Optional[str], tool_name: str, tool_params: Dict[str, Any], trace_id: str = "unknown") -> str:
        """Dispatch tool call to appropriate handler with authentication checks.

        Args:
            request_id: JSON-RPC request ID
            tool_name: Normalized tool name (with underscores)
            tool_params: Tool parameters
            trace_id: Unique trace ID for debugging hangs
        """
        from datetime import timedelta

        # Convert from normalized name (underscores) back to internal format (dots)
        internal_tool_name = self._denormalize_tool_name(tool_name)
        self._logger.debug(f"[{trace_id}] DISPATCH: normalized={tool_name} -> internal={internal_tool_name}")

        # ====================================================================
        # Authentication Check (Phase 1: MCP_AUTH_IMPLEMENTATION_PLAN.md)
        # ====================================================================
        session_context = getattr(self, "_session_context", None)

        # Check if tool requires authentication
        if internal_tool_name not in PUBLIC_TOOLS:
            self._logger.debug(f"[{trace_id}] AUTH_CHECK: tool requires authentication")
            if session_context is not None and not session_context.is_authenticated:
                self._logger.warning(f"[{trace_id}] AUTH_FAIL: Unauthenticated call to {internal_tool_name}")
                return self._error_response(
                    request_id,
                    self.AUTH_REQUIRED,
                    "Authentication required. Call auth.deviceLogin or auth.clientCredentials first.",
                    data={"tool": internal_tool_name, "public_tools": list(PUBLIC_TOOLS)}
                )

            # ====================================================================
            # Scope Authorization (Phase 3: MCP_AUTH_IMPLEMENTATION_PLAN.md)
            # ====================================================================
            # Check if user/SP has required scopes for this tool
            tool_scopes = getattr(self, "_tool_scopes", {}) or {}
            required_scopes = tool_scopes.get(internal_tool_name, [])
            if required_scopes:
                if session_context is None:
                    missing = set(required_scopes)
                else:
                    missing = session_context.missing_scopes(required_scopes)
                if missing:
                    self._logger.warning(
                        f"Access denied to {internal_tool_name}: "
                        f"identity={getattr(session_context, 'identity', None)}, "
                        f"missing_scopes={missing}"
                    )
                    return self._error_response(
                        request_id,
                        self.ACCESS_DENIED,
                        f"Access denied: missing required scopes: {', '.join(sorted(missing))}",
                        data={
                            "tool": internal_tool_name,
                            "required_scopes": required_scopes,
                            "granted_scopes": list(getattr(session_context, "granted_scopes", set())),
                            "missing_scopes": list(missing),
                        }
                    )

            # ====================================================================
            # Tenant-Aware Rate Limiting (Phase 5: MCP_AUTH_IMPLEMENTATION_PLAN.md)
            # ====================================================================
            # Check distributed rate limits based on org/user/tier
            from .mcp_rate_limiter import SubscriptionTier

            # Determine subscription tier (default to FREE, could be looked up from org)
            tier = SubscriptionTier.FREE
            if session_context and session_context.org_id:
                # TODO: Look up org subscription tier from database
                # For now, use PRO if authenticated with an org
                tier = SubscriptionTier.PRO

            distributed_rate_limiter = getattr(self, "_distributed_rate_limiter", None)
            if distributed_rate_limiter is not None and session_context is not None:
                tenant_rate_result = await distributed_rate_limiter.check_tenant_limit(
                    org_id=session_context.org_id,
                    user_id=session_context.user_id,
                    service_principal_id=session_context.service_principal_id,
                tier=tier,
                tool_name=internal_tool_name,
                )

                if not tenant_rate_result.allowed:
                    self._logger.warning(
                        f"Tenant rate limit exceeded: org={session_context.org_id}, "
                        f"user={session_context.user_id}, tier={tier.value}, "
                        f"limit_type={tenant_rate_result.limit_type}, "
                        f"retry_after={tenant_rate_result.retry_after}"
                    )
                    return self._error_response(
                        request_id,
                        self.RATE_LIMITED,
                        f"Rate limit exceeded ({tenant_rate_result.limit_type}). "
                        f"Retry after {tenant_rate_result.retry_after} seconds.",
                        data=tenant_rate_result.to_dict(),
                    )

        # ====================================================================
        # Route tool group management tools (Lazy Loading)
        # ====================================================================
        if internal_tool_name.startswith("tools."):
            result = await self._handle_tools_management(internal_tool_name, tool_params)

            mcp_result = {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, indent=2),
                    }
                ]
            }

            return self._success_response(request_id, mcp_result)

        # ====================================================================
        # Route high-level outcome tools (consolidated operations)
        # Following MCP best practice: "Focus on Outcomes, Not Operations"
        # ====================================================================
        outcome_tools = {
            "project.setupComplete",
            "behavior.analyzeAndRetrieve",
            "workItem.executeWithTracking",
            "analytics.fullReport",
            "compliance.fullValidation",
        }
        if internal_tool_name in outcome_tools:
            result = await self._handle_outcome_tool(internal_tool_name, tool_params, trace_id)

            mcp_result = {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, indent=2),
                    }
                ]
            }

            return self._success_response(request_id, mcp_result)

        # Route device flow tools
        if internal_tool_name.startswith("auth."):
            if not self._device_flow_handler:
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    "Device flow handler not available",
                )

            # Handle client credentials flow (Phase 2: Service Principal Auth)
            if internal_tool_name == "auth.clientCredentials":
                result = await self._handle_client_credentials(tool_params)
            else:
                result = await self._device_flow_handler.handle_tool_call(internal_tool_name, tool_params)

            # Populate session context on successful device flow auth
            # Works for both auth.deviceLogin (blocking) and auth.devicePoll (non-blocking)
            if internal_tool_name in ("auth.deviceLogin", "auth.devicePoll") and result.get("status") == "authorized":
                self._populate_session_from_device_flow(result)
                self._logger.info(f"Session populated from device flow: user_id={self._session_context.user_id}")

            # Update session context on successful token refresh
            if internal_tool_name in ("auth.refreshToken", "auth.refresh") and result.get("status") == "refreshed":
                self._update_session_from_refresh(result)
                self._logger.info(f"Session updated from token refresh: user_id={self._session_context.user_id}, new_expires_at={self._session_context.expires_at}")

            # Do not echo raw OAuth tokens to MCP clients (IDE chat logs, etc.) unless debugging.
            response_for_mcp = _redact_oauth_tokens_for_mcp_tool_result(result)

            # Wrap result in MCP content format
            mcp_result = {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(response_for_mcp, indent=2),
                    }
                ]
            }

            return self._success_response(request_id, mcp_result)

        # ====================================================================
        # Route JIT consent tools (Phase 6: Consent UX Dashboard)
        # ====================================================================
        if internal_tool_name.startswith("consent."):
            result = await self._handle_consent_tool(internal_tool_name, tool_params)

            mcp_result = {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, indent=2),
                    }
                ]
            }

            return self._success_response(request_id, mcp_result)

        # ====================================================================
        # Route context switching tools (Phase 4: Tenant Context & Isolation)
        # ====================================================================
        if internal_tool_name.startswith("context."):
            result = await self._handle_context_tool(internal_tool_name, tool_params)

            mcp_result = {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, indent=2),
                    }
                ]
            }

            return self._success_response(request_id, mcp_result)

        # ====================================================================
        # Route rate limit tools (Phase 5: Distributed Rate Limiting)
        # ====================================================================
        if internal_tool_name.startswith("ratelimit."):
            result = await self._handle_ratelimit_tool(internal_tool_name, tool_params)

            mcp_result = {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, indent=2),
                    }
                ]
            }

            return self._success_response(request_id, mcp_result)

        # Route task management tools
        if internal_tool_name.startswith("tasks."):
            if not self._task_handler:
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    "Task handler not available",
                )

            # Dispatch to appropriate handler method
            if internal_tool_name == "tasks.listAssignments":
                result = await self._task_handler.handle_list_assignments(tool_params)
            elif internal_tool_name == "tasks.create":
                result = await self._task_handler.handle_create_task(tool_params)
            elif internal_tool_name == "tasks.updateStatus":
                result = await self._task_handler.handle_update_status(tool_params)
            elif internal_tool_name == "tasks.getStats":
                result = await self._task_handler.handle_get_stats(tool_params)
            else:
                return self._error_response(
                    request_id,
                    self.METHOD_NOT_FOUND,
                    f"Unknown task tool: {internal_tool_name}",
                )

            # Wrap result in MCP content format
            mcp_result = {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, indent=2),
                    }
                ]
            }

            return self._success_response(request_id, mcp_result)

        # Route BreakerAmp tools
        if internal_tool_name.startswith("breakeramp."):
            _amp = self._get_breakeramp_adapter()
            if not _amp:
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    "BreakerAmp adapter not available",
                )

            try:
                if internal_tool_name == "breakeramp.plan":
                    result = _amp.plan(
                        blueprint_id=tool_params["blueprint_id"],
                        environment=tool_params.get("environment", "development"),
                        checklist_id=tool_params.get("checklist_id"),
                        lifetime=tool_params.get("lifetime", "90m"),
                        compliance_tier=tool_params.get("compliance_tier", "dev"),
                        behaviors=tool_params.get("behaviors"),
                        variables=tool_params.get("variables"),
                    )
                elif internal_tool_name == "breakeramp.apply":
                    result = _amp.apply(
                        plan_id=tool_params.get("plan_id"),
                        manifest_file=tool_params.get("manifest_file"),
                        watch=tool_params.get("watch", False),
                        resume=tool_params.get("resume", False),
                    )
                elif internal_tool_name == "breakeramp.status":
                    result = _amp.status(
                        run_id=tool_params["run_id"]
                    )
                elif internal_tool_name == "breakeramp.destroy":
                    result = _amp.destroy(
                        run_id=tool_params["run_id"],
                        cascade=tool_params.get("cascade", True),
                        reason=tool_params.get("reason", "MANUAL"),
                    )
                elif internal_tool_name == "breakeramp.listBlueprints":
                    result = _amp.list_blueprints(
                        source=tool_params.get("source", "all"),
                    )
                elif internal_tool_name == "breakeramp.listEnvironments":
                    result = _amp.list_environments(
                        phase=tool_params.get("phase", "all"),
                    )
                elif internal_tool_name == "breakeramp.configure":
                    result = _amp.configure(
                        config_dir=tool_params.get("config_dir"),
                        include_blueprints=tool_params.get("include_blueprints", False),
                        blueprints=tool_params.get("blueprints"),
                        force=tool_params.get("force", False),
                    )
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown BreakerAmp tool: {internal_tool_name}",
                    )
            except KeyError as e:
                return self._error_response(
                    request_id,
                    self.INVALID_PARAMS,
                    f"Missing required parameter: {e}",
                )

            # Wrap result in MCP content format
            mcp_result = {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, indent=2),
                    }
                ]
            }

            return self._success_response(request_id, mcp_result)

        # Route pattern analysis tools
        if internal_tool_name.startswith("patterns."):
            try:
                from .adapters import MCPTraceAnalysisServiceAdapter

                adapter = MCPTraceAnalysisServiceAdapter(self._services.trace_analysis_service())

                if internal_tool_name == "patterns.detectPatterns":
                    # Send progress notification for long-running operation
                    self._send_notification(
                        "tool/progress",
                        {
                            "request_id": request_id,
                            "tool": internal_tool_name,
                            "status": "starting",
                            "message": "Analyzing trace for recurring patterns...",
                        }
                    )

                    result = adapter.detectPatterns(tool_params)

                    # Send completion notification
                    self._send_notification(
                        "tool/progress",
                        {
                            "request_id": request_id,
                            "tool": internal_tool_name,
                            "status": "complete",
                            "message": f"Detected {len(result.get('patterns', []))} patterns",
                        }
                    )
                elif internal_tool_name == "patterns.scoreReusability":
                    result = adapter.scoreReusability(tool_params)
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown patterns tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Pattern tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Pattern tool execution failed: {str(e)}",
                )

        # Route action service tools
        if internal_tool_name.startswith("actions."):
            try:
                from .adapters import MCPActionServiceAdapter

                adapter = MCPActionServiceAdapter(self._services.action_service())

                if internal_tool_name == "actions.create":
                    result = adapter.create(tool_params)
                elif internal_tool_name == "actions.list":
                    result = adapter.list()
                elif internal_tool_name == "actions.get":
                    action_id = tool_params.get("action_id")
                    if not action_id:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: action_id",
                        )
                    result = adapter.get(action_id)
                elif internal_tool_name == "actions.replay":
                    result = adapter.replay(tool_params)
                elif internal_tool_name == "actions.replayStatus":
                    replay_id = tool_params.get("replay_id")
                    if not replay_id:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: replay_id",
                        )
                    result = adapter.get_replay_status(replay_id)
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown actions tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Action tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Action tool execution failed: {str(e)}",
                )

        # Route behavior service tools
        if internal_tool_name.startswith("behaviors."):
            try:
                from .adapters import MCPBehaviorServiceAdapter

                adapter = MCPBehaviorServiceAdapter(self._services.behavior_service())

                if internal_tool_name == "behaviors.create":
                    result = adapter.create(tool_params)
                elif internal_tool_name == "behaviors.list":
                    result = adapter.list(tool_params)
                elif internal_tool_name == "behaviors.search":
                    query = tool_params.get("query")
                    if not query:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: query",
                        )
                    result = adapter.search(tool_params)
                elif internal_tool_name == "behaviors.get":
                    behavior_id = tool_params.get("behavior_id")
                    if not behavior_id:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: behavior_id",
                        )
                    result = adapter.get(tool_params)
                elif internal_tool_name == "behaviors.getForTask":
                    task_description = tool_params.get("task_description")
                    if not task_description:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: task_description",
                        )
                    result = adapter.get_for_task(tool_params)
                elif internal_tool_name == "behaviors.update":
                    behavior_id = tool_params.get("behavior_id")
                    version = tool_params.get("version")
                    if not behavior_id or not version:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameters: behavior_id, version",
                        )
                    result = adapter.update(tool_params)
                elif internal_tool_name == "behaviors.submit":
                    behavior_id = tool_params.get("behavior_id")
                    version = tool_params.get("version")
                    if not behavior_id or not version:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameters: behavior_id, version",
                        )
                    result = adapter.submit(tool_params)
                elif internal_tool_name == "behaviors.approve":
                    behavior_id = tool_params.get("behavior_id")
                    version = tool_params.get("version")
                    effective_from = tool_params.get("effective_from")
                    if not behavior_id or not version or not effective_from:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameters: behavior_id, version, effective_from",
                        )
                    result = adapter.approve(tool_params)
                elif internal_tool_name == "behaviors.deprecate":
                    behavior_id = tool_params.get("behavior_id")
                    version = tool_params.get("version")
                    effective_to = tool_params.get("effective_to")
                    if not behavior_id or not version or not effective_to:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameters: behavior_id, version, effective_to",
                        )
                    result = adapter.deprecate(tool_params)
                elif internal_tool_name == "behaviors.deleteDraft":
                    behavior_id = tool_params.get("behavior_id")
                    version = tool_params.get("version")
                    if not behavior_id or not version:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameters: behavior_id, version",
                        )
                    adapter.delete_draft(tool_params)
                    result = {"success": True, "message": f"Draft {behavior_id} v{version} deleted"}
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown behaviors tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Behavior tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Behavior tool execution failed: {str(e)}",
                )

        # ComplianceService tool routing
        if internal_tool_name.startswith("compliance/"):
            from amprealize.compliance_service import RecordStepRequest, Actor

            try:
                compliance_service = self._services.compliance_service()
                actor = Actor(id="test-strategist", role="STRATEGIST", surface="mcp")

                if internal_tool_name == "compliance/create-checklist":
                    result = compliance_service.create_checklist(
                        title=tool_params["title"],
                        description=tool_params.get("description", ""),
                        template_id=tool_params.get("template_id"),
                        milestone=tool_params.get("milestone"),
                        compliance_category=tool_params.get("compliance_category", []),
                        actor=actor,
                    )
                    result_dict = {
                        "checklist_id": result.checklist_id,
                        "title": result.title,
                        "description": result.description,
                        "template_id": result.template_id,
                        "milestone": result.milestone,
                        "compliance_category": result.compliance_category,
                        "steps": [],
                        "created_at": result.created_at,
                        "completed_at": result.completed_at,
                        "coverage_score": result.coverage_score,
                    }

                elif internal_tool_name == "compliance/list-checklists":
                    checklists = compliance_service.list_checklists(
                        milestone=tool_params.get("milestone"),
                        compliance_category=tool_params.get("compliance_category"),
                        status_filter=tool_params.get("status_filter"),
                    )
                    result_dict = {
                        "checklists": [
                            {
                                "checklist_id": c.checklist_id,
                                "title": c.title,
                                "description": c.description,
                                "template_id": c.template_id,
                                "milestone": c.milestone,
                                "compliance_category": c.compliance_category,
                                "steps": [
                                    {
                                        "step_id": s.step_id,
                                        "checklist_id": s.checklist_id,
                                        "title": s.title,
                                        "status": s.status,
                                        "actor": {"id": s.actor.id, "role": s.actor.role, "surface": s.actor.surface},
                                        "evidence": s.evidence,
                                        "behaviors_cited": s.behaviors_cited,
                                        "related_run_id": s.related_run_id,
                                        "audit_log_event_id": s.audit_log_event_id,
                                        "validation_result": s.validation_result,
                                        "timestamp": s.timestamp,
                                    }
                                    for s in c.steps
                                ],
                                "created_at": c.created_at,
                                "completed_at": c.completed_at,
                                "coverage_score": c.coverage_score,
                            }
                            for c in checklists
                        ]
                    }

                elif internal_tool_name == "compliance/get-checklist":
                    checklist = compliance_service.get_checklist(
                        checklist_id=tool_params["checklist_id"]
                    )
                    result_dict = {
                        "checklist_id": checklist.checklist_id,
                        "title": checklist.title,
                        "description": checklist.description,
                        "template_id": checklist.template_id,
                        "milestone": checklist.milestone,
                        "compliance_category": checklist.compliance_category,
                        "steps": [
                            {
                                "step_id": s.step_id,
                                "checklist_id": s.checklist_id,
                                "title": s.title,
                                "status": s.status,
                                "actor": {"id": s.actor.id, "role": s.actor.role, "surface": s.actor.surface},
                                "evidence": s.evidence,
                                "behaviors_cited": s.behaviors_cited,
                                "related_run_id": s.related_run_id,
                                "audit_log_event_id": s.audit_log_event_id,
                                "validation_result": s.validation_result,
                                "timestamp": s.timestamp,
                            }
                            for s in checklist.steps
                        ],
                        "created_at": checklist.created_at,
                        "completed_at": checklist.completed_at,
                        "coverage_score": checklist.coverage_score,
                    }

                elif internal_tool_name == "compliance/record-step":
                    record_req = RecordStepRequest(
                        checklist_id=tool_params["checklist_id"],
                        title=tool_params["title"],
                        status=tool_params["status"],
                        evidence=tool_params.get("evidence"),
                        behaviors_cited=tool_params.get("behaviors_cited", []),
                        related_run_id=tool_params.get("related_run_id"),
                    )
                    step = compliance_service.record_step(record_req, actor)
                    result_dict = {
                        "step_id": step.step_id,
                        "checklist_id": step.checklist_id,
                        "title": step.title,
                        "status": step.status,
                        "actor": {"id": step.actor.id, "role": step.actor.role, "surface": step.actor.surface},
                        "evidence": step.evidence,
                        "behaviors_cited": step.behaviors_cited,
                        "related_run_id": step.related_run_id,
                        "audit_log_event_id": step.audit_log_event_id,
                        "validation_result": step.validation_result,
                        "timestamp": step.timestamp,
                    }

                elif internal_tool_name == "compliance/validate-compliance":
                    validation = compliance_service.validate_checklist(
                        checklist_id=tool_params["checklist_id"],
                        actor=actor,
                    )
                    result_dict = {
                        "checklist_id": validation.checklist_id,
                        "valid": validation.valid,
                        "coverage_score": validation.coverage_score,
                        "missing_steps": validation.missing_steps,
                        "failed_steps": validation.failed_steps,
                        "warnings": validation.warnings,
                    }

                elif internal_tool_name == "compliance/validate-by-action":
                    validation = compliance_service.validate_by_action_id(
                        action_id=tool_params["action_id"],
                        actor=actor,
                    )
                    result_dict = {
                        "checklist_id": validation.checklist_id,
                        "valid": validation.valid,
                        "coverage_score": validation.coverage_score,
                        "missing_steps": validation.missing_steps,
                        "failed_steps": validation.failed_steps,
                        "warnings": validation.warnings,
                    }

                elif internal_tool_name == "compliance/create-policy":
                    policy = compliance_service.create_policy(
                        name=tool_params["name"],
                        description=tool_params.get("description", ""),
                        policy_type=tool_params["policy_type"],
                        enforcement_level=tool_params["enforcement_level"],
                        actor=actor,
                        org_id=tool_params.get("org_id"),
                        project_id=tool_params.get("project_id"),
                        version=tool_params.get("version", "1.0.0"),
                        rules=tool_params.get("rules"),
                        required_behaviors=tool_params.get("required_behaviors"),
                        compliance_categories=tool_params.get("compliance_categories"),
                        metadata=tool_params.get("metadata"),
                    )
                    result_dict = policy.to_dict()

                elif internal_tool_name == "compliance/get-policy":
                    policy = compliance_service.get_policy(tool_params["policy_id"])
                    result_dict = policy.to_dict()

                elif internal_tool_name == "compliance/list-policies":
                    policies = compliance_service.list_policies(
                        org_id=tool_params.get("org_id"),
                        project_id=tool_params.get("project_id"),
                        policy_type=tool_params.get("policy_type"),
                        enforcement_level=tool_params.get("enforcement_level"),
                        is_active=tool_params.get("is_active"),
                        include_global=tool_params.get("include_global", True),
                    )
                    result_dict = {"policies": [p.to_dict() for p in policies]}

                elif internal_tool_name == "compliance/audit-trail":
                    report = compliance_service.get_audit_trail(
                        run_id=tool_params.get("run_id"),
                        checklist_id=tool_params.get("checklist_id"),
                        action_id=tool_params.get("action_id"),
                        start_date=tool_params.get("start_date"),
                        end_date=tool_params.get("end_date"),
                    )
                    result_dict = report.to_dict()

                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown compliance tool: {internal_tool_name}",
                    )

                # Wrap result in MCP format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result_dict, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Compliance tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Compliance tool execution failed: {str(e)}",
                )

        # Route run service tools
        if internal_tool_name.startswith("runs."):
            try:
                from .adapters import MCPRunServiceAdapter

                adapter = MCPRunServiceAdapter(self._services.run_service())

                if internal_tool_name == "runs.create":
                    result = adapter.create(tool_params)
                elif internal_tool_name == "runs.list":
                    result = {"runs": adapter.list(tool_params)}
                elif internal_tool_name == "runs.get":
                    run_id = tool_params.get("run_id")
                    if not run_id:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: run_id",
                        )
                    result = adapter.get(run_id)
                elif internal_tool_name == "runs.updateProgress":
                    run_id = tool_params.get("run_id")
                    if not run_id:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: run_id",
                        )
                    result = adapter.update(run_id, tool_params)
                elif internal_tool_name == "runs.complete":
                    run_id = tool_params.get("run_id")
                    if not run_id:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: run_id",
                        )
                    result = adapter.complete(run_id, tool_params)
                elif internal_tool_name == "runs.cancel":
                    run_id = tool_params.get("run_id")
                    if not run_id:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: run_id",
                        )
                    result = adapter.cancel(run_id, tool_params)
                elif internal_tool_name == "runs.updateStatus":
                    run_id = tool_params.get("run_id")
                    if not run_id:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: run_id",
                        )
                    if "status" not in tool_params:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: status",
                        )
                    result = adapter.update_status(run_id, tool_params)
                elif internal_tool_name == "runs.fetchLogs":
                    run_id = tool_params.get("run_id")
                    if not run_id:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: run_id",
                        )
                    # Get RazeService for log queries
                    raze_service = self._get_raze_service()
                    # Note: asyncio is already imported at module level (line 36)
                    # Run async method
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(
                                asyncio.run,
                                adapter.fetch_logs(run_id, tool_params, raze_service)
                            )
                            result = future.result()
                    else:
                        result = loop.run_until_complete(
                            adapter.fetch_logs(run_id, tool_params, raze_service)
                        )
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown runs tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Run tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Run tool execution failed: {str(e)}",
                )

        # Workflow tools: workflow.template.*, workflow.run.*
        if internal_tool_name.startswith("workflow."):
            try:
                from .adapters import MCPWorkflowServiceAdapter

                adapter = MCPWorkflowServiceAdapter(self._services.workflow_service())

                if internal_tool_name == "workflow.template.create":
                    result = adapter.create_template(tool_params)
                elif internal_tool_name == "workflow.template.list":
                    result = {"templates": adapter.list_templates(tool_params)}
                elif internal_tool_name == "workflow.template.get":
                    template_id = tool_params.get("template_id")
                    if not template_id:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: template_id",
                        )
                    result = adapter.get_template(template_id)
                    if result is None:
                        return self._error_response(
                            request_id,
                            self.INTERNAL_ERROR,
                            f"Template not found: {template_id}",
                        )
                elif internal_tool_name == "workflow.run.start":
                    result = adapter.run_workflow(tool_params)
                elif internal_tool_name == "workflow.run.status":
                    run_id = tool_params.get("run_id")
                    if not run_id:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: run_id",
                        )
                    result = adapter.get_run(run_id)
                    if result is None:
                        return self._error_response(
                            request_id,
                            self.INTERNAL_ERROR,
                            f"Workflow run not found: {run_id}",
                        )
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown workflow tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Workflow tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Workflow tool execution failed: {str(e)}",
                )

        # BCI tools: bci.*
        if internal_tool_name.startswith("bci."):
            try:
                from .mcp.handlers import bci_handlers

                service = self._services.bci_service()

                if internal_tool_name == "bci.retrieve":
                    result = bci_handlers.bci_retrieve(tool_params)
                elif internal_tool_name == "bci.retrieveHybrid":
                    result = bci_handlers.bci_retrieve_hybrid(tool_params)
                elif internal_tool_name == "bci.composePrompt":
                    result = bci_handlers.bci_compose_prompt(tool_params)
                elif internal_tool_name == "bci.composeBatchPrompts":
                    result = bci_handlers.bci_compose_prompts_batch(tool_params)
                elif internal_tool_name == "bci.parseCitations":
                    result = bci_handlers.bci_parse_citations(tool_params)
                elif internal_tool_name == "bci.validateCitations":
                    result = bci_handlers.bci_validate_citations(tool_params)
                elif internal_tool_name == "bci.computeTokenSavings":
                    result = bci_handlers.bci_compute_token_savings(tool_params)
                elif internal_tool_name == "bci.segmentTrace":
                    result = bci_handlers.bci_segment_trace(tool_params)
                elif internal_tool_name == "bci.detectPatterns":
                    result = bci_handlers.bci_detect_patterns(tool_params)
                elif internal_tool_name == "bci.scoreReusability":
                    result = bci_handlers.bci_score_reusability(tool_params)
                elif internal_tool_name == "bci.rebuildIndex":
                    result = bci_handlers.bci_rebuild_index(tool_params)
                elif internal_tool_name == "bci.generate":
                    result = bci_handlers.bci_generate(tool_params)
                elif internal_tool_name == "bci.improve":
                    result = bci_handlers.bci_improve(tool_params)
                elif internal_tool_name == "bci.inject":
                    result = bci_handlers.bci_inject(tool_params)
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown BCI tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"BCI tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"BCI tool execution failed: {str(e)}",
                )

        # Handle metrics.* tools
        if internal_tool_name.startswith("metrics."):
            try:
                from .adapters import MCPMetricsServiceAdapter

                service = self._services.metrics_service()
                adapter = MCPMetricsServiceAdapter(service=service)

                if internal_tool_name == "metrics.getSummary":
                    result = adapter.get_summary(tool_params or {})
                elif internal_tool_name == "metrics.export":
                    result = adapter.export(tool_params or {})
                elif internal_tool_name == "metrics.subscribe":
                    result = adapter.subscribe(tool_params or {})
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown metrics tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Metrics tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Metrics tool execution failed: {str(e)}",
                )

        # Handle analytics.* tools
        if internal_tool_name.startswith("analytics."):
            try:
                from .adapters import MCPAnalyticsServiceAdapter

                service = self._services.analytics_service()
                adapter = MCPAnalyticsServiceAdapter(service=service)

                if internal_tool_name == "analytics.kpiSummary":
                    result = adapter.kpi_summary(tool_params or {})
                elif internal_tool_name == "analytics.behaviorUsage":
                    result = adapter.behavior_usage(tool_params or {})
                elif internal_tool_name == "analytics.tokenSavings":
                    result = adapter.token_savings(tool_params or {})
                elif internal_tool_name == "analytics.complianceCoverage":
                    result = adapter.compliance_coverage(tool_params or {})
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown analytics tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Analytics tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Analytics tool execution failed: {str(e)}",
                )

        # Handle audit.* tools (compliance-grade audit log access)
        if internal_tool_name.startswith("audit."):
            try:
                from .adapters import MCPAuditServiceAdapter

                service = self._services.audit_log_service()
                adapter = MCPAuditServiceAdapter(service=service)

                if internal_tool_name == "audit.query":
                    result = await adapter.query(tool_params or {})
                elif internal_tool_name == "audit.archive":
                    result = await adapter.archive(tool_params or {})
                elif internal_tool_name == "audit.verify":
                    result = await adapter.verify(tool_params or {})
                elif internal_tool_name == "audit.status":
                    result = await adapter.status(tool_params or {})
                elif internal_tool_name == "audit.listArchives":
                    result = adapter.list_archives(tool_params or {})
                elif internal_tool_name == "audit.getRetention":
                    result = adapter.get_retention(tool_params or {})
                elif internal_tool_name == "audit.verifyArchive":
                    result = adapter.verify_archive(tool_params or {})
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown audit tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Audit tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Audit tool execution failed: {str(e)}",
                )

        # Handle agents.* tools
        if internal_tool_name.startswith("agents."):
            try:
                from .adapters import MCPAgentOrchestratorAdapter

                service = self._services.agent_orchestrator_service()
                adapter = MCPAgentOrchestratorAdapter(service=service)

                if internal_tool_name == "agents.assign":
                    result = adapter.assign(tool_params or {})
                elif internal_tool_name == "agents.switch":
                    result = adapter.switch(tool_params or {})
                elif internal_tool_name == "agents.status":
                    result = adapter.status(tool_params or {})
                    if result is None:
                        return self._error_response(
                            request_id,
                            self.INTERNAL_ERROR,
                            "Agent assignment not found",
                        )
                elif internal_tool_name == "agents.delegate":
                    result = adapter.delegate(tool_params or {})
                elif internal_tool_name == "agents.consult":
                    result = adapter.consult(tool_params or {})
                elif internal_tool_name == "agents.handoff":
                    result = adapter.handoff(tool_params or {})
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown agents tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except KeyError as e:
                self._logger.error(f"Agent orchestration validation failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INVALID_PARAMS,
                    f"Invalid parameters: {str(e)}",
                )
            except Exception as e:
                self._logger.error(f"Agent orchestration tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Agent orchestration tool execution failed: {str(e)}",
                )

        # Handle escalation.* tools (Section 11.4 - Human Escalation)
        if internal_tool_name.startswith("escalation."):
            try:
                from .adapters import MCPEscalationAdapter

                service = self._services.agent_orchestrator_service()
                adapter = MCPEscalationAdapter(service)

                if internal_tool_name == "escalation.requestHelp":
                    result = adapter.request_help(tool_params or {})
                elif internal_tool_name == "escalation.requestApproval":
                    result = adapter.request_approval(tool_params or {})
                elif internal_tool_name == "escalation.notifyBlocked":
                    result = adapter.notify_blocked(tool_params or {})
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown escalation tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except KeyError as e:
                self._logger.error(f"Escalation validation failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INVALID_PARAMS,
                    f"Invalid parameters: {str(e)}",
                )
            except ValueError as e:
                self._logger.error(f"Escalation validation failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INVALID_PARAMS,
                    f"Validation error: {str(e)}",
                )
            except Exception as e:
                self._logger.error(f"Escalation tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Escalation tool execution failed: {str(e)}",
                )

        # Handle agentRegistry.* tools (agent CRUD operations)
        if internal_tool_name.startswith("agentRegistry."):
            try:
                from .mcp.handlers.agent_registry_handlers import AGENT_REGISTRY_HANDLERS

                handler = AGENT_REGISTRY_HANDLERS.get(internal_tool_name)
                if not handler:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown agentRegistry tool: {internal_tool_name}",
                    )

                # All agentRegistry.* tools use AgentRegistryService
                service = self._services.agent_registry_service()

                # Call the async handler
                result = await handler(service=service, params=tool_params)

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"agentRegistry tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"agentRegistry tool execution failed: {str(e)}",
                )

        # Handle reflection.* tools
        if internal_tool_name.startswith("reflection."):
            try:
                from .adapters import MCPReflectionServiceAdapter

                # Use registry's reflection_service (PostgreSQL or in-memory)
                service = self._services.reflection_service()
                adapter = MCPReflectionServiceAdapter(service=service)

                if internal_tool_name == "reflection.extract":
                    result = adapter.extract(tool_params or {})
                elif internal_tool_name == "reflection.listCandidates":
                    result = adapter.list_candidates(tool_params or {})
                elif internal_tool_name == "reflection.approveCandidate":
                    result = adapter.approve_candidate(tool_params or {})
                elif internal_tool_name == "reflection.rejectCandidate":
                    result = adapter.reject_candidate(tool_params or {})
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown reflection tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Reflection tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Reflection tool execution failed: {str(e)}",
                )

        # Handle security.* tools
        if internal_tool_name.startswith("security."):
            try:
                if internal_tool_name == "security.scanSecrets":
                    # Integrate with existing gitleaks scanner
                    repo_path = tool_params.get("repo_path", ".")
                    result = subprocess.run(
                        ["./scripts/scan_secrets.sh"],
                        cwd=repo_path,
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )

                    scan_result = {
                        "repo_path": repo_path,
                        "exit_code": result.returncode,
                        "clean": result.returncode == 0,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "message": "No secrets detected" if result.returncode == 0 else "Secrets detected or scan failed",
                    }
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown security tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(scan_result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except subprocess.TimeoutExpired:
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    "Secret scanning timed out after 60 seconds",
                )
            except Exception as e:
                self._logger.error(f"Security tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Security tool execution failed: {str(e)}",
                )

        # Handle tasks.* tools
        if internal_tool_name.startswith("tasks."):
            try:
                from .adapters import MCPTaskAssignmentAdapter

                service = self._services.task_assignment_service()
                adapter = MCPTaskAssignmentAdapter(service=service)

                if internal_tool_name == "tasks.listAssignments":
                    result = adapter.list_assignments(tool_params)
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown tasks tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Tasks tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Tasks tool execution failed: {str(e)}",
                )

        # Handle auth.* tools
        if internal_tool_name.startswith("auth."):
            try:
                from .adapters import MCPAgentAuthServiceAdapter

                service = self._services.agent_auth_service()
                adapter = MCPAgentAuthServiceAdapter(client=service)

                if internal_tool_name == "auth.ensureGrant":
                    result = adapter.ensure_grant(tool_params)
                elif internal_tool_name == "auth.listGrants":
                    result = adapter.list_grants(tool_params)
                elif internal_tool_name == "auth.policy.preview":
                    result = adapter.policy_preview(tool_params)
                elif internal_tool_name == "auth.revoke":
                    result = adapter.revoke(tool_params)
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown auth tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Auth tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Auth tool execution failed: {str(e)}",
                )

        # Handle fine-tuning.* tools (using midnighter package)
        if internal_tool_name.startswith("fine-tuning."):
            try:
                from .adapters import MCPFineTuningServiceAdapter

                service = self._services.fine_tuning_service()
                adapter = MCPFineTuningServiceAdapter(service=service)

                if internal_tool_name == "fine-tuning.create-corpus":
                    result = adapter.create_corpus(tool_params)
                elif internal_tool_name == "fine-tuning.generate-corpus":
                    result = adapter.generate_corpus(tool_params)
                elif internal_tool_name == "fine-tuning.start-job":
                    result = adapter.start_job(tool_params)
                elif internal_tool_name == "fine-tuning.status":
                    result = adapter.get_status(tool_params)
                elif internal_tool_name == "fine-tuning.list":
                    result = adapter.list_jobs(tool_params)
                elif internal_tool_name == "fine-tuning.list-corpora":
                    result = adapter.list_corpora(tool_params)
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown fine-tuning tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Fine-tuning tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Fine-tuning tool execution failed: {str(e)}",
                )

        # Handle reviews.* tools
        if internal_tool_name.startswith("reviews."):
            try:
                from .adapters import MCPAgentReviewServiceAdapter

                service = self._services.agent_review_service()
                adapter = MCPAgentReviewServiceAdapter(service=service)

                if internal_tool_name == "reviews.create":
                    result = adapter.create_review(tool_params)
                elif internal_tool_name == "reviews.status":
                    result = adapter.get_review_status(tool_params)
                elif internal_tool_name == "reviews.list":
                    result = adapter.list_reviews(tool_params)
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown reviews tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Reviews tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Reviews tool execution failed: {str(e)}",
                )

        # Handle tenants.* tools
        if internal_tool_name.startswith("tenants."):
            try:
                from .adapters import MCPMultiTenantServiceAdapter

                service = self._services.multi_tenant_service()
                adapter = MCPMultiTenantServiceAdapter(service=service)

                if internal_tool_name == "tenants.create":
                    result = adapter.create_tenant(tool_params)
                elif internal_tool_name == "tenants.status":
                    result = adapter.get_tenant_status(tool_params)
                elif internal_tool_name == "tenants.list":
                    result = adapter.list_tenants(tool_params)
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown tenants tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Tenants tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Tenants tool execution failed: {str(e)}",
                )

        # Handle retrieval.* tools
        if internal_tool_name.startswith("retrieval."):
            try:
                from .adapters import MCPAdvancedRetrievalServiceAdapter

                service = self._services.advanced_retrieval_service()
                adapter = MCPAdvancedRetrievalServiceAdapter(service=service)

                if internal_tool_name == "retrieval.advanced-search":
                    result = adapter.advanced_search(tool_params)
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown retrieval tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Retrieval tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Retrieval tool execution failed: {str(e)}",
                )

        # Handle collaboration.* tools
        if internal_tool_name.startswith("collaboration."):
            try:
                from .adapters import MCPCollaborationServiceAdapter

                service = self._services.collaboration_service()
                adapter = MCPCollaborationServiceAdapter(service=service)

                if internal_tool_name == "collaboration.workspace.create":
                    result = adapter.create_workspace(tool_params)
                elif internal_tool_name == "collaboration.workspace.status":
                    result = adapter.get_workspace_status(tool_params)
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown collaboration tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Collaboration tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Collaboration tool execution failed: {str(e)}",
                )

        # Handle mcp-rate-limits.* tools (MCP server rate limiting)
        if internal_tool_name.startswith("mcp-rate-limits."):
            try:
                if internal_tool_name == "mcp-rate-limits.status":
                    client_id = tool_params.get("client_id") or self._client_id or f"anonymous:{id(self)}"
                    status = self._rate_limiter.get_client_status(client_id)
                    if status is None:
                        result = {"error": f"No rate limit state for client: {client_id}"}
                    else:
                        result = status
                elif internal_tool_name == "mcp-rate-limits.metrics":
                    result = self._rate_limiter.get_metrics()
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown mcp-rate-limits tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"MCP rate limits tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"MCP rate limits tool execution failed: {str(e)}",
                )

        # Handle rate-limits.* tools (API rate limiting)
        if internal_tool_name.startswith("rate-limits."):
            try:
                from .adapters import MCPAPIRateLimitingServiceAdapter

                service = self._services.api_rate_limiting_service()
                adapter = MCPAPIRateLimitingServiceAdapter(service=service)

                if internal_tool_name == "rate-limits.configure":
                    result = adapter.configure_rate_limits(tool_params)
                elif internal_tool_name == "rate-limits.status":
                    result = adapter.get_rate_limit_status(tool_params)
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown rate-limits tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Rate limits tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Rate limits tool execution failed: {str(e)}",
                )

        # Handle raze.* tools for structured logging
        if internal_tool_name.startswith("raze."):
            try:
                service = self._services.raze_service()
                if service is None:
                    return self._error_response(
                        request_id,
                        self.INTERNAL_ERROR,
                        "Raze service not available (package not installed)",
                    )

                if internal_tool_name == "raze.emit":
                    # Emit a single log entry
                    result = service.emit(
                        level=tool_params.get("level", "info"),
                        message=tool_params["message"],
                        context=tool_params.get("context", {}),
                        run_id=tool_params.get("run_id"),
                        behavior_id=tool_params.get("behavior_id"),
                        tags=tool_params.get("tags", []),
                    )
                elif internal_tool_name == "raze.emit-batch":
                    # Emit multiple log entries
                    entries = tool_params.get("entries", [])
                    result = service.emit_batch(entries)
                elif internal_tool_name == "raze.query":
                    # Query logs with filters
                    result = service.query(
                        start_time=tool_params.get("start_time"),
                        end_time=tool_params.get("end_time"),
                        levels=tool_params.get("levels"),
                        run_id=tool_params.get("run_id"),
                        behavior_id=tool_params.get("behavior_id"),
                        tags=tool_params.get("tags"),
                        limit=tool_params.get("limit", 100),
                        offset=tool_params.get("offset", 0),
                    )
                elif internal_tool_name == "raze.aggregate":
                    # Get aggregated statistics
                    result = service.aggregate(
                        start_time=tool_params.get("start_time"),
                        end_time=tool_params.get("end_time"),
                        group_by=tool_params.get("group_by", ["level"]),
                        run_id=tool_params.get("run_id"),
                    )
                elif internal_tool_name == "raze.flush":
                    # Flush pending logs to sink
                    result = service.flush()
                elif internal_tool_name == "raze.status":
                    # Get service status
                    result = service.status()
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown raze tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Raze tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Raze tool execution failed: {str(e)}",
                )

        # Handle telemetry.* tools for telemetry querying and dashboards
        if internal_tool_name.startswith("telemetry."):
            try:
                if internal_tool_name == "telemetry.query":
                    # Query telemetry events using RazeService
                    service = self._services.raze_service()
                    if service is None:
                        return self._error_response(
                            request_id,
                            self.INTERNAL_ERROR,
                            "Telemetry service not available (Raze package not installed)",
                        )

                    # Parse date parameters with relative date support
                    from datetime import datetime, timezone, timedelta
                    import re

                    def _parse_relative_datetime(date_str: str) -> datetime:
                        if not date_str:
                            return datetime.now(timezone.utc)
                        # Try relative format (e.g., "7d", "24h", "30m")
                        match = re.match(r"^(\d+)([dhms])$", date_str.lower())
                        if match:
                            value = int(match.group(1))
                            unit = match.group(2)
                            delta_map = {"d": timedelta(days=value), "h": timedelta(hours=value),
                                         "m": timedelta(minutes=value), "s": timedelta(seconds=value)}
                            return datetime.now(timezone.utc) - delta_map[unit]
                        # Try ISO format
                        if len(date_str) == 10:
                            return datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
                        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))

                    start_time = tool_params.get("start_time") or "7d"
                    end_time = tool_params.get("end_time")

                    query_params = {
                        "start_time": _parse_relative_datetime(start_time).isoformat() if start_time else None,
                        "end_time": _parse_relative_datetime(end_time).isoformat() if end_time else None,
                        "limit": tool_params.get("limit", 100),
                        "offset": tool_params.get("offset", 0),
                    }

                    # Add optional filters
                    if tool_params.get("event_type"):
                        query_params["event_type"] = tool_params["event_type"]
                    if tool_params.get("run_id"):
                        query_params["run_id"] = tool_params["run_id"]
                    if tool_params.get("action_id"):
                        query_params["action_id"] = tool_params["action_id"]
                    if tool_params.get("session_id"):
                        query_params["session_id"] = tool_params["session_id"]
                    if tool_params.get("actor_surface"):
                        query_params["actor_surface"] = tool_params["actor_surface"].replace("-", "_").lower()
                    if tool_params.get("level"):
                        query_params["level"] = tool_params["level"].upper()
                    if tool_params.get("search"):
                        query_params["search"] = tool_params["search"]

                    query_result = service.query(**query_params)
                    logs = query_result.logs if hasattr(query_result, 'logs') else query_result

                    result = {
                        "events": [log.to_dict() if hasattr(log, 'to_dict') else log for log in (logs or [])],
                        "total": len(logs) if logs else 0,
                        "limit": query_params["limit"],
                        "offset": query_params["offset"],
                    }

                elif internal_tool_name == "telemetry.dashboard":
                    # Dashboard using AnalyticsWarehouse
                    from datetime import datetime, timezone, timedelta
                    warehouse = self._services.analytics_service()

                    start_date = tool_params.get("start_date") or (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
                    end_date = tool_params.get("end_date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    run_id = tool_params.get("run_id")

                    if run_id:
                        # Drill-down to specific run
                        token_data = warehouse.get_token_savings(run_id=run_id, limit=1)
                        cost_data = warehouse.get_cost_per_run(run_id=run_id)
                        record = token_data[0] if token_data else {}

                        result = {
                            "period": {"start": start_date, "end": end_date},
                            "run_detail": {
                                "run_id": run_id,
                                "token_accounting": {
                                    "baseline_tokens": record.get("baseline_tokens", 0),
                                    "actual_tokens": record.get("actual_tokens", 0),
                                    "tokens_saved": record.get("tokens_saved", 0),
                                    "savings_rate_pct": record.get("savings_rate_pct", 0),
                                },
                                "cost_breakdown": cost_data or [],
                            },
                        }
                    else:
                        # Summary dashboard
                        include_kpi = tool_params.get("include_kpi", True)
                        include_token_savings = tool_params.get("include_token_savings", True)
                        include_daily_costs = tool_params.get("include_daily_costs", True)
                        token_savings_limit = tool_params.get("token_savings_limit", 10)

                        result = {"period": {"start": start_date, "end": end_date}}

                        if include_kpi:
                            kpi_records = warehouse.get_kpi_summary(start_date=start_date, end_date=end_date)
                            latest = kpi_records[-1] if kpi_records else {}
                            result["kpi_summary"] = {
                                "behavior_reuse_rate_pct": latest.get("reuse_rate_pct", 0),
                                "token_savings_rate_pct": latest.get("avg_savings_rate_pct", 0),
                                "task_completion_rate_pct": latest.get("completion_rate_pct", 0),
                                "compliance_coverage_pct": latest.get("avg_coverage_rate_pct", 0),
                            }

                        if include_token_savings:
                            result["token_savings"] = warehouse.get_token_savings(
                                start_date=start_date, end_date=end_date, limit=token_savings_limit
                            )

                        if include_daily_costs:
                            result["daily_costs"] = warehouse.get_daily_cost_summary(
                                start_date=start_date, end_date=end_date
                            )

                        # Calculate totals
                        total_saved = sum(r.get("tokens_saved", 0) for r in result.get("token_savings", []))
                        total_cost = sum(r.get("total_cost_usd", 0) for r in result.get("daily_costs", []))
                        total_runs = sum(r.get("total_runs", 0) for r in result.get("daily_costs", []))
                        result["totals"] = {
                            "total_tokens_saved": total_saved,
                            "total_cost_usd": total_cost,
                            "total_runs": total_runs,
                        }

                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown telemetry tool: {internal_tool_name}",
                    )

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2, default=str),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Telemetry tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Telemetry tool execution failed: {str(e)}",
                )

        # Handle orgs.* tools (organization management)
        if internal_tool_name.startswith("orgs."):
            try:
                from .mcp.handlers.org_handlers import ORG_HANDLERS

                handler = ORG_HANDLERS.get(internal_tool_name)
                if not handler:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown orgs tool: {internal_tool_name}",
                    )

                # Get the organization service
                org_service = self._services.organization_service()

                # Inject session context into tool params if authenticated
                # This allows handlers to use user_id from session without requiring it as parameter
                enriched_params = self._inject_session_context(tool_params)

                # Call the sync handler in a thread to avoid blocking
                result = await asyncio.to_thread(handler, org_service, enriched_params)

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Orgs tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Orgs tool execution failed: {str(e)}",
                )

        # Handle projects.* tools (project management)
        if internal_tool_name.startswith("projects."):
            self._logger.debug(f"[{trace_id}] ROUTE_PROJECTS: {internal_tool_name}")
            try:
                from .mcp.handlers.project_handlers import PROJECT_HANDLERS

                handler = PROJECT_HANDLERS.get(internal_tool_name)
                if not handler:
                    self._logger.warning(f"[{trace_id}] PROJECTS_HANDLER_MISSING: {internal_tool_name}")
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown projects tool: {internal_tool_name}",
                    )

                # Get services - OrganizationService handles both orgs and projects
                self._logger.debug(f"[{trace_id}] PROJECTS_GET_SERVICE")
                org_service = self._services.organization_service()

                # Inject session context into tool params if authenticated
                enriched_params = self._inject_session_context(tool_params)

                # Call the sync handler in a thread to avoid blocking
                self._logger.debug(f"[{trace_id}] PROJECTS_EXEC_HANDLER: {handler.__name__ if hasattr(handler, '__name__') else 'anon'}")
                result = await asyncio.to_thread(handler, org_service, org_service, enriched_params)
                self._logger.debug(f"[{trace_id}] PROJECTS_HANDLER_COMPLETE")

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Projects tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Projects tool execution failed: {str(e)}",
                )

        # Handle boards.* tools (board management)
        if internal_tool_name.startswith("board."):
            try:
                from .services.board_service import Actor, BoardService
                from .multi_tenant.board_contracts import (
                    CreateLabelRequest,
                    LabelColor,
                    UpdateLabelRequest,
                )

                # Use service registry when available; allow lightweight test instances
                # created via MCPServer.__new__ to instantiate directly.
                if hasattr(self, "_services") and self._services is not None:
                    board_service = self._services.board_service()
                else:
                    board_service = BoardService()

                actor_payload = tool_params.get("actor") or {}
                actor = Actor(
                    id=actor_payload.get("id") or tool_params.get("user_id") or "mcp-user",
                    role=actor_payload.get("type") or tool_params.get("actor_role") or "user",
                    surface=tool_params.get("actor_surface") or "mcp",
                )
                org_id = tool_params.get("org_id")

                if internal_tool_name == "board.listLabels":
                    project_id = tool_params.get("project_id")
                    if not project_id:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: project_id",
                        )

                    labels_response = board_service.list_labels(
                        project_id=project_id,
                        org_id=org_id,
                        limit=tool_params.get("limit", 100),
                        offset=tool_params.get("offset", 0),
                    )
                    result = {
                        "labels": [label.model_dump(mode="json") for label in labels_response.labels],
                        "total": labels_response.total,
                    }

                elif internal_tool_name == "board.createLabel":
                    project_id = tool_params.get("project_id")
                    name = tool_params.get("name")
                    if not project_id or not name:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameters: project_id, name",
                        )

                    request = CreateLabelRequest(
                        name=name,
                        color=LabelColor(tool_params.get("color", "gray")),
                        description=tool_params.get("description"),
                    )
                    label = board_service.create_label(project_id, request, actor, org_id=org_id)
                    result = {
                        "success": True,
                        "label": label.model_dump(mode="json"),
                    }

                elif internal_tool_name == "board.updateLabel":
                    label_id = tool_params.get("label_id")
                    if not label_id:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: label_id",
                        )

                    color = tool_params.get("color")
                    request = UpdateLabelRequest(
                        name=tool_params.get("name"),
                        color=LabelColor(color) if color is not None else None,
                        description=tool_params.get("description"),
                    )
                    label = board_service.update_label(label_id, request, actor, org_id=org_id)
                    result = {
                        "success": True,
                        "label": label.model_dump(mode="json"),
                    }

                elif internal_tool_name == "board.deleteLabel":
                    label_id = tool_params.get("label_id")
                    if not label_id:
                        return self._error_response(
                            request_id,
                            self.INVALID_PARAMS,
                            "Missing required parameter: label_id",
                        )

                    delete_result = board_service.delete_label(label_id, actor, org_id=org_id)
                    result = {
                        "success": True,
                        "deleted_id": delete_result.deleted_id,
                    }

                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown board tool: {internal_tool_name}",
                    )

                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except KeyError as exc:
                return self._error_response(
                    request_id,
                    self.INVALID_PARAMS,
                    f"Missing required field: {exc}",
                )
            except ValueError as exc:
                return self._error_response(
                    request_id,
                    self.INVALID_PARAMS,
                    str(exc),
                )
            except Exception as e:
                self._logger.error(f"Board tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Board tool execution failed: {str(e)}",
                )

        if internal_tool_name.startswith("boards."):
            try:
                from .mcp.handlers.board_handlers import BOARD_HANDLERS

                handler = BOARD_HANDLERS.get(internal_tool_name)
                if not handler:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown boards tool: {internal_tool_name}",
                    )

                # Get the board service
                board_service = self._services.board_service()

                # Call the sync handler in a thread to avoid blocking
                result = await asyncio.to_thread(handler, board_service, tool_params)

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Boards tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Boards tool execution failed: {str(e)}",
                )

        if internal_tool_name.startswith("columns."):
            try:
                from .mcp.handlers.board_handlers import COLUMN_HANDLERS

                handler = COLUMN_HANDLERS.get(internal_tool_name)
                if not handler:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown columns tool: {internal_tool_name}",
                    )

                board_service = self._services.board_service()
                result = await asyncio.to_thread(handler, board_service, tool_params)

                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Columns tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Columns tool execution failed: {str(e)}",
                )

        # Handle workItems.* tools (work item management and execution)
        if internal_tool_name.startswith("workItems."):
            # Execution tools (workItems.execute, executionStatus, etc.)
            execution_tools = {
                "workItems.execute",
                "workItems.executionStatus",
                "workItems.cancelExecution",
                "workItems.provideClarification",
                "workItems.listExecutions",
            }

            if internal_tool_name in execution_tools:
                try:
                    from .mcp.handlers.work_item_execution_handlers import (
                        create_work_item_execution_handlers,
                    )

                    # Get the work item execution service
                    work_item_execution_service = self._services.work_item_execution_service()

                    # Create handlers (pass board_service for display-ID resolution)
                    board_svc = self._services.board_service()
                    handlers = create_work_item_execution_handlers(
                        work_item_execution_service,
                        board_service=board_svc,
                    )
                    handler = handlers.get(internal_tool_name)

                    if not handler:
                        return self._error_response(
                            request_id,
                            self.METHOD_NOT_FOUND,
                            f"Unknown work item execution tool: {internal_tool_name}",
                        )

                    # Call the async handler
                    result = await handler(tool_params)

                    # Wrap result in MCP content format
                    mcp_result = {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result, indent=2),
                            }
                        ]
                    }

                    return self._success_response(request_id, mcp_result)

                except Exception as e:
                    self._logger.error(f"Work item execution tool failed: {e}", exc_info=True)
                    return self._error_response(
                        request_id,
                        self.INTERNAL_ERROR,
                        f"Work item execution tool failed: {str(e)}",
                    )

            # Board management tools (workItems.create, update, delete, etc.)
            try:
                from .mcp.handlers.board_handlers import WORK_ITEM_HANDLERS

                handler = WORK_ITEM_HANDLERS.get(internal_tool_name)
                if not handler:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown workItems tool: {internal_tool_name}",
                    )

                # Get the board service (work items are managed by BoardService)
                board_service = self._services.board_service()

                # Call the sync handler in a thread to avoid blocking
                result = await asyncio.to_thread(handler, board_service, tool_params)

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"WorkItems tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"WorkItems tool execution failed: {str(e)}",
                )

        # Handle files.* tools (file operations)
        if internal_tool_name.startswith("files."):
            try:
                from .mcp.handlers.file_handlers import FILE_HANDLERS

                handler = FILE_HANDLERS.get(internal_tool_name)
                if not handler:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown files tool: {internal_tool_name}",
                    )

                # File handlers don't need a service - they operate on the filesystem
                # Call the sync handler in a thread to avoid blocking
                result = await asyncio.to_thread(handler, None, tool_params)

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Files tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Files tool execution failed: {str(e)}",
                )

        # Handle github.* tools (GitHub PR and commit operations)
        if internal_tool_name.startswith("github."):
            try:
                from .mcp.handlers.github_handlers import GITHUB_HANDLERS

                handler = GITHUB_HANDLERS.get(internal_tool_name)
                if not handler:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown github tool: {internal_tool_name}",
                    )

                # Get the GitHub service
                github_service = self._services.github_service()

                # Call the sync handler in a thread to avoid blocking
                result = await asyncio.to_thread(handler, github_service, tool_params)

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"GitHub tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"GitHub tool execution failed: {str(e)}",
                )

        # Handle config.* tools (configuration and model availability)
        if internal_tool_name.startswith("config."):
            try:
                from .mcp.handlers.config_handlers import CONFIG_HANDLERS

                handler = CONFIG_HANDLERS.get(internal_tool_name)
                if not handler:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown config tool: {internal_tool_name}",
                    )

                # Get the credential store for model availability queries
                credential_store = self._services.credential_store()

                # Call the sync handler in a thread to avoid blocking
                result = await asyncio.to_thread(handler, credential_store, tool_params)

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except KeyError as exc:
                return self._error_response(
                    request_id,
                    self.INVALID_PARAMS,
                    f"Missing required field: {exc}",
                )
            except ValueError as exc:
                return self._error_response(
                    request_id,
                    self.INVALID_PARAMS,
                    str(exc),
                )
            except Exception as e:
                self._logger.error(f"Config tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Config tool execution failed: {str(e)}",
                )

        # Handle bootstrap.* tools (workspace profiling and initialization)
        if internal_tool_name.startswith("bootstrap."):
            try:
                from .mcp.handlers.bootstrap_handlers import BOOTSTRAP_HANDLERS

                handler = BOOTSTRAP_HANDLERS.get(internal_tool_name)
                if not handler:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown bootstrap tool: {internal_tool_name}",
                    )

                # Call the sync handler in a thread to avoid blocking
                result = await asyncio.to_thread(handler, tool_params)

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except KeyError as exc:
                return self._error_response(
                    request_id,
                    self.INVALID_PARAMS,
                    f"Missing required field: {exc}",
                )
            except ValueError as exc:
                return self._error_response(
                    request_id,
                    self.INVALID_PARAMS,
                    str(exc),
                )
            except Exception as e:
                self._logger.error(f"Bootstrap tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Bootstrap tool execution failed: {str(e)}",
                )

        # Handle research.* tools (AI paper evaluation)
        if internal_tool_name.startswith("research."):
            try:
                from .mcp.handlers.research_handlers import RESEARCH_HANDLERS

                handler = RESEARCH_HANDLERS.get(internal_tool_name)
                if not handler:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown research tool: {internal_tool_name}",
                    )

                service = self._services.research_service()
                enriched_params = self._inject_session_context(tool_params)
                result = await handler(service=service, params=enriched_params)

                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2, default=str),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Research tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Research tool execution failed: {str(e)}",
                )

        # Handle conversations.* and messages.* tools (messaging system)
        if internal_tool_name.startswith("conversations.") or internal_tool_name.startswith("messages."):
            try:
                from .mcp.handlers.conversation_handlers import (
                    ASYNC_MESSAGE_HANDLERS,
                    CONVERSATION_HANDLERS,
                    MESSAGE_HANDLERS,
                )

                all_sync_handlers = {**CONVERSATION_HANDLERS, **MESSAGE_HANDLERS}
                conversation_service = self._services.conversation_service()
                enriched_params = self._inject_session_context(tool_params)

                # Check for async handlers first (e.g., messages.generateReply)
                if internal_tool_name in ASYNC_MESSAGE_HANDLERS:
                    handler = ASYNC_MESSAGE_HANDLERS[internal_tool_name]
                    reply_service = self._services.conversation_reply_service()
                    result = await handler(
                        conversation_service,
                        enriched_params,
                        reply_service=reply_service,
                    )
                elif internal_tool_name in all_sync_handlers:
                    handler = all_sync_handlers[internal_tool_name]
                    result = await asyncio.to_thread(handler, conversation_service, enriched_params)
                else:
                    return self._error_response(
                        request_id,
                        self.METHOD_NOT_FOUND,
                        f"Unknown conversation/messaging tool: {internal_tool_name}",
                    )

                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2, default=str),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Conversation tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Conversation tool execution failed: {str(e)}",
                )

        # Unknown tool prefix
        self._logger.warning(f"[{trace_id}] UNKNOWN_TOOL: No handler for {internal_tool_name}")
        return self._error_response(
            request_id,
            self.METHOD_NOT_FOUND,
            f"Unknown tool: {internal_tool_name}",
        )

    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get metrics summary for monitoring."""
        import statistics

        latency_summary = {}
        for tool_name, latencies in self._metrics["tool_latency_seconds"].items():
            if latencies:
                latency_summary[tool_name] = {
                    "count": len(latencies),
                    "mean": statistics.mean(latencies),
                    "median": statistics.median(latencies),
                    "min": min(latencies),
                    "max": max(latencies),
                    "p95": statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies),
                }

        return {
            "requests_total": self._metrics["requests_total"],
            "requests_by_method": dict(self._metrics["requests_by_method"]),
            "tool_calls_total": self._metrics["tool_calls_total"],
            "tool_calls_by_name": dict(self._metrics["tool_calls_by_name"]),
            "tool_latency_summary": latency_summary,
            "errors_total": self._metrics["errors_total"],
            "batch_requests_total": self._metrics["batch_requests_total"],
            "rate_limiting": self._rate_limiter.get_metrics(),
        }

    def get_health_status(self) -> Dict[str, Any]:
        """
        Get comprehensive health status for MCP server (Epic 6 - Health Check Endpoints).

        Returns health status including:
        - Overall status: "healthy", "degraded", or "unhealthy"
        - PostgreSQL connection pool stats per service
        - Tool manifest availability
        - Service registry status
        - Memory and uptime metrics

        Used by Dockerfile HEALTHCHECK and container orchestration.
        """
        import psutil

        health_checks: Dict[str, Dict[str, Any]] = {}
        overall_status = "healthy"
        degraded_services: List[str] = []
        failed_services: List[str] = []

        # Check PostgreSQL pools
        pool_checks: Dict[str, Any] = {}
        for dsn, pool in self._services._pools.items():
            try:
                stats = pool.get_pool_stats()
                service_name = stats.get("service", "unknown")
                pool_status = "healthy"

                # Check if pool is exhausted (available = 0 and connections checked out)
                if stats.get("available", 0) == 0 and stats.get("checked_out", 0) > 0:
                    pool_status = "degraded"
                    degraded_services.append(f"pool:{service_name}")

                pool_checks[service_name] = {
                    "status": pool_status,
                    "checked_out": stats.get("checked_out", 0),
                    "available": stats.get("available", 0),
                    "pool_size": stats.get("pool_size", 0),
                    "overflow": stats.get("overflow", 0),
                }
            except Exception as e:
                service_name = dsn[:20] + "..." if len(dsn) > 20 else dsn
                pool_checks[service_name] = {
                    "status": "unhealthy",
                    "error": str(e),
                }
                failed_services.append(f"pool:{service_name}")

        health_checks["postgres_pools"] = pool_checks

        # Check service registry status
        services_status: Dict[str, str] = {}
        for service_name, attr_name in [
            ("behavior", "_behavior_service"),
            ("bci", "_bci_service"),
            ("workflow", "_workflow_service"),
            ("action", "_action_service"),
            ("run", "_run_service"),
            ("compliance", "_compliance_service"),
            ("agent_auth", "_agent_auth_service"),
            ("metrics", "_metrics_service"),
        ]:
            # Check if service has been initialized (lazy loading)
            service = getattr(self._services, attr_name, None)
            if service is not None:
                services_status[service_name] = "initialized"
            else:
                services_status[service_name] = "not_loaded"  # Lazy - will initialize on first use

        health_checks["services"] = services_status

        # Check tool manifests
        tools_status = {
            "loaded_count": len(self._tools),
            "status": "healthy" if len(self._tools) > 0 else "degraded",
            "tools": list(self._tools.keys())[:10],  # First 10 tools
            "total_tools": len(self._tools),
        }
        if len(self._tools) == 0:
            degraded_services.append("tools")

        health_checks["tools"] = tools_status

        # Memory and process metrics
        try:
            process = psutil.Process()
            memory_info = process.memory_info()
            health_checks["process"] = {
                "memory_rss_mb": round(memory_info.rss / 1024 / 1024, 2),
                "memory_vms_mb": round(memory_info.vms / 1024 / 1024, 2),
                "cpu_percent": process.cpu_percent(interval=0.1),
                "num_threads": process.num_threads(),
                "open_files": len(process.open_files()),
                "uptime_seconds": round(time.time() - process.create_time(), 2),
            }
        except Exception as e:
            health_checks["process"] = {"status": "unavailable", "error": str(e)}

        # Connection stability metrics
        health_checks["connection"] = {
            "idle_seconds": round(time.time() - self._last_activity, 2),
            "idle_timeout_seconds": self._idle_timeout_seconds,
            "shutdown_requested": self._shutdown_requested,
            "pending_requests": len(self._pending_requests),
        }

        # Determine overall status
        if failed_services:
            overall_status = "unhealthy"
        elif degraded_services:
            overall_status = "degraded"

        return {
            "status": overall_status,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "version": "0.1.0",
            "environment": os.environ.get("AMPREALIZE_ENV", os.environ.get("ENVIRONMENT", "development")),
            "transport": os.environ.get("MCP_TRANSPORT", "stdio"),
            "checks": health_checks,
            "degraded_services": degraded_services,
            "failed_services": failed_services,
        }

    # ========================================================================
    # Session Management (Phase 1 & 2: MCP_AUTH_IMPLEMENTATION_PLAN.md)
    # ========================================================================

    def _resolve_user_id(self, email_or_id: Optional[str]) -> Optional[str]:
        """Resolve an email address to the canonical user ID from auth.users.

        If the input looks like an email, queries auth.users to find the
        corresponding user ID. Returns the original value if no match is found
        or if it doesn't look like an email.
        """
        if not email_or_id or "@" not in email_or_id:
            return email_or_id
        try:
            import os
            from .storage.postgres_pool import PostgresPool

            auth_dsn = (
                os.environ.get("AMPREALIZE_ORG_PG_DSN")
                or os.environ.get("AMPREALIZE_AUTH_PG_DSN")
                or os.environ.get("AMPREALIZE_PG_DSN")
            )
            if not auth_dsn:
                return email_or_id

            pool = PostgresPool(dsn=auth_dsn, service_name="resolve_user")
            with pool.connection() as conn:
                cur = conn.cursor()
                try:
                    cur.execute(
                        "SELECT id FROM auth.users WHERE email = %s LIMIT 1",
                        (email_or_id,),
                    )
                    row = cur.fetchone()
                    if row:
                        self._logger.debug(
                            f"Resolved email {email_or_id} -> user_id {row[0]}"
                        )
                        return row[0]
                finally:
                    cur.close()
        except Exception as exc:
            self._logger.warning(f"Failed to resolve user_id from email: {exc}")
        return email_or_id

    def _populate_session_from_device_flow(self, result: Dict[str, Any]) -> None:
        """Populate session context from successful device flow authorization.

        Called after auth.deviceLogin returns status='authorized'.
        """
        from datetime import datetime, timedelta

        raw_user_id = result.get("user_id") or result.get("email")
        self._session_context.user_id = self._resolve_user_id(raw_user_id)
        self._session_context.org_id = result.get("org_id")
        self._session_context.granted_scopes = set(result.get("scopes", []))
        self._session_context.auth_method = "device_flow"
        self._session_context.roles = set(result.get("roles", []))

        # Set expiration from token if available, otherwise default 1 hour
        expires_in = result.get("expires_in", 3600)
        self._session_context.expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

        self._logger.info(
            f"Session populated: user={self._session_context.user_id}, "
            f"org={self._session_context.org_id}, "
            f"scopes={self._session_context.granted_scopes}, "
            f"expires_at={self._session_context.expires_at}"
        )

        # Populate authorization context (orgs, projects, admin status)
        self._populate_authorization_context()

    def _update_session_from_refresh(self, result: Dict[str, Any]) -> None:
        """Update session context after successful token refresh.

        Called after auth.refreshToken returns status='refreshed'.
        Updates the expiration time, scopes, and populates user info if needed.

        This handles the case where the MCP server restarted and the session
        wasn't restored - the refresh can re-establish the session context.
        """
        from datetime import datetime, timedelta

        # Update expiration from new token
        expires_in = result.get("expires_in", 3600)
        self._session_context.expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

        # Update scopes if provided (they may have changed)
        if result.get("scopes"):
            self._session_context.granted_scopes = set(result["scopes"])

        # If session wasn't already authenticated (e.g., server restarted),
        # populate user info from the refresh response
        if not self._session_context.user_id:
            raw_user_id = result.get("user_id") or result.get("email")
            if raw_user_id:
                self._session_context.user_id = self._resolve_user_id(raw_user_id)
                self._session_context.auth_method = "device_flow"
                # Populate authorization context (orgs, projects, admin status)
                self._populate_authorization_context()
                self._logger.info(
                    f"Session re-established from refresh: user={self._session_context.user_id}"
                )

        # Ensure auth_method is set (may have been "none" if session wasn't populated)
        if self._session_context.auth_method == "none":
            self._session_context.auth_method = "device_flow"

        self._logger.info(
            f"Session refreshed: user={self._session_context.user_id}, "
            f"new_expires_at={self._session_context.expires_at}, "
            f"scopes={self._session_context.granted_scopes}"
        )

    def _try_restore_session_from_tokens(self) -> None:
        """Try to restore session from stored tokens on startup.

        This enables session persistence across MCP server restarts when using
        stdio transport (where each tool call starts a fresh process).

        Checks:
        1. PostgreSQL device_sessions table for valid access tokens
        2. Local keychain/file token store
        """
        from datetime import datetime, timedelta, timezone

        self._logger.debug("Attempting to restore session from stored tokens...")

        # First, try PostgreSQL device sessions (most reliable for shared state)
        # Always try SQL query if DSN is available, regardless of _postgres_device_store
        try:
            from .storage.postgres_pool import PostgresPool
            import os

            auth_dsn = os.environ.get("AMPREALIZE_ORG_PG_DSN") or os.environ.get("AMPREALIZE_MULTI_TENANT_PG_DSN") or os.environ.get("AMPREALIZE_PG_DSN")
            if auth_dsn:
                self._logger.debug(f"Found auth DSN, attempting PostgreSQL session restore...")
                # Ensure auth schema
                if "search_path" not in auth_dsn:
                    if "?" in auth_dsn:
                        auth_dsn = f"{auth_dsn}&options=-c%20search_path%3Dauth"
                    else:
                        auth_dsn = f"{auth_dsn}?options=-c%20search_path%3Dauth"
                auth_dsn = _ensure_dsn_param(auth_dsn, "connect_timeout", os.environ.get("MCP_DB_CONNECT_TIMEOUT_SECONDS", "3"))

                pool = PostgresPool(dsn=auth_dsn, service_name="session_restore")
                with pool.connection() as conn:
                    cur = conn.cursor()
                    try:
                        # Find most recent approved session with valid access token
                        cur.execute("""
                            SELECT
                                access_token,
                                scopes,
                                approver,
                                access_token_expires_at
                            FROM auth.device_sessions
                            WHERE status = 'APPROVED'
                                AND access_token IS NOT NULL
                                AND access_token_expires_at > NOW()
                            ORDER BY approved_at DESC
                            LIMIT 1
                        """)
                        row = cur.fetchone()
                        if row:
                            access_token, scopes, approver, expires_at = row

                            # Populate session context
                            self._session_context.user_id = self._resolve_user_id(approver)
                            self._session_context.granted_scopes = set(scopes) if scopes else set()
                            self._session_context.auth_method = "device_flow"
                            self._session_context.expires_at = expires_at.replace(tzinfo=None) if expires_at else datetime.utcnow() + timedelta(hours=1)

                            self._logger.info(
                                f"Session restored from PostgreSQL: user_id={approver}, "
                                f"scopes={self._session_context.granted_scopes}, "
                                f"expires_at={self._session_context.expires_at}"
                            )
                            # Populate authorization context (orgs, projects, admin status)
                            self._populate_authorization_context()
                            return  # Success - no need to check token store
                    finally:
                        cur.close()
        except Exception as e:
            self._logger.warning(f"Failed to restore session from PostgreSQL: {e}")

        # Fallback: try local token store (keychain or file)
        try:
            from .mcp_device_flow import MCPDeviceFlowService
            from .device_flow.token_store import KeychainTokenStore, FileTokenStore, TokenStoreError

            store = None
            try:
                store = KeychainTokenStore()
            except Exception:
                store = FileTokenStore()

            bundle = store.load()
            if bundle and bundle.access_token:
                now = datetime.now(timezone.utc)
                if bundle.expires_at > now:
                    # Token is still valid - restore session
                    self._session_context.granted_scopes = set(bundle.scopes) if bundle.scopes else set()
                    self._session_context.auth_method = "device_flow"
                    self._session_context.expires_at = bundle.expires_at.replace(tzinfo=None)

                    # We don't have user_id in the token bundle, but we can try to look it up
                    # For now, just mark as authenticated without user_id (tools can still work)
                    # The user_id will be populated on the next explicit auth call
                    self._logger.info(
                        f"Session restored from token store: "
                        f"scopes={self._session_context.granted_scopes}, "
                        f"expires_at={self._session_context.expires_at}"
                    )
                else:
                    self._logger.debug(f"Stored token expired at {bundle.expires_at}")
        except Exception as e:
            self._logger.debug(f"No valid session restored from token store: {e}")

    def _populate_authorization_context(self) -> None:
        """Populate authorization context after session is authenticated.

        This enriches the session with:
        - is_admin: True if user is in DEV_ADMIN_USERS env var
        - accessible_org_ids: Orgs the user belongs to
        - accessible_project_ids: Projects the user can access (personal + org)
        """
        import os

        if not self._session_context.user_id:
            return

        # Check if user is an admin (from env var)
        admin_users = os.environ.get("AMPREALIZE_DEV_ADMIN_USERS", "admin,dev-admin").split(",")
        admin_users = [u.strip() for u in admin_users if u.strip()]
        self._session_context.is_admin = self._session_context.user_id in admin_users

        if self._session_context.is_admin:
            self._logger.info(f"User {self._session_context.user_id} is an admin - full access granted")

        # Populate accessible orgs and projects from database
        try:
            org_service = self._services.organization_service()

            # Get orgs user belongs to
            user_orgs = org_service.list_user_organizations(user_id=self._session_context.user_id)
            self._session_context.accessible_org_ids = {org.id for org in user_orgs}

            # Get projects user can access (calls list_projects without org_id)
            # This returns user-owned projects + org projects
            from .mcp.handlers.project_handlers import handle_list_projects
            result = handle_list_projects(
                project_service=org_service,
                org_service=org_service,
                arguments={"user_id": self._session_context.user_id}
            )
            if result.get("success"):
                self._session_context.accessible_project_ids = {
                    p["id"] for p in result.get("projects", [])
                }

            self._logger.debug(
                f"Authorization context populated: "
                f"is_admin={self._session_context.is_admin}, "
                f"orgs={len(self._session_context.accessible_org_ids)}, "
                f"projects={len(self._session_context.accessible_project_ids)}"
            )
        except Exception as e:
            self._logger.warning(f"Failed to populate authorization context: {e}")

    async def _handle_client_credentials(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle auth.clientCredentials tool - Service Principal authentication.

        Phase 2: MCP_AUTH_IMPLEMENTATION_PLAN.md

        Args:
            params: {client_id: str, client_secret: str, scopes?: List[str]}

        Returns:
            On success: {status: 'authorized', service_principal_id, org_id, scopes, expires_in}
            On failure: {status: 'error', error: str, error_code: str}
        """
        from datetime import datetime, timedelta
        from amprealize.auth.service_principal_service import ServicePrincipalService

        client_id = params.get("client_id")
        client_secret = params.get("client_secret")
        requested_scopes = params.get("scopes", [])

        if not client_id or not client_secret:
            return {
                "status": "error",
                "error": "Missing required parameters: client_id and client_secret",
                "error_code": "INVALID_REQUEST",
            }

        try:
            # Use ServicePrincipalService to authenticate
            sp_service = ServicePrincipalService()
            service_principal = await asyncio.get_event_loop().run_in_executor(
                None, sp_service.authenticate, client_id, client_secret
            )

            if not service_principal:
                self._logger.warning(f"Client credentials auth failed for client_id={client_id}")
                return {
                    "status": "error",
                    "error": "Invalid client credentials",
                    "error_code": "INVALID_CLIENT",
                }

            # Check if service principal is active
            if not service_principal.is_active:
                self._logger.warning(f"Inactive service principal: {service_principal.id}")
                return {
                    "status": "error",
                    "error": "Service principal is inactive",
                    "error_code": "INACTIVE_CLIENT",
                }

            # Validate requested scopes against allowed scopes
            allowed_scopes = set(service_principal.allowed_scopes or [])
            if requested_scopes:
                requested_set = set(requested_scopes)
                if not requested_set.issubset(allowed_scopes):
                    invalid_scopes = requested_set - allowed_scopes
                    return {
                        "status": "error",
                        "error": f"Requested scopes not allowed: {invalid_scopes}",
                        "error_code": "INVALID_SCOPE",
                    }
                granted_scopes = requested_set
            else:
                granted_scopes = allowed_scopes

            # Populate session context (org_id is optional - may be None)
            self._session_context.service_principal_id = str(service_principal.id)
            self._session_context.org_id = str(service_principal.org_id) if service_principal.org_id else None
            self._session_context.granted_scopes = granted_scopes
            self._session_context.auth_method = "client_credentials"
            self._session_context.roles = {service_principal.role} if service_principal.role else {"service"}

            # Service principals get 24 hour sessions by default
            expires_in = 86400
            self._session_context.expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

            self._logger.info(
                f"Service principal authenticated: sp_id={service_principal.id}, "
                f"org={service_principal.org_id}, scopes={granted_scopes}"
            )

            # Build response - org_id only included if present
            response = {
                "status": "authorized",
                "service_principal_id": str(service_principal.id),
                "name": service_principal.name,
                "scopes": list(granted_scopes),
                "role": service_principal.role,
                "expires_in": expires_in,
            }
            if service_principal.org_id:
                response["org_id"] = str(service_principal.org_id)

            return response

        except Exception as e:
            self._logger.error(f"Client credentials auth error: {e}", exc_info=True)
            return {
                "status": "error",
                "error": f"Authentication failed: {str(e)}",
                "error_code": "SERVER_ERROR",
            }

    # ========================================================================
    # High-Level Outcome Tools (Consolidated Operations)
    # ========================================================================

    async def _handle_outcome_tool(
        self, tool_name: str, params: Dict[str, Any], trace_id: str
    ) -> Dict[str, Any]:
        """
        Handle high-level outcome tools that consolidate multiple operations.

        Following MCP best practice: "Focus on Outcomes, Not Operations"
        - One tool call achieves what previously required multiple round-trips
        - Reduces context window usage and latency

        Supports:
        - project.setupComplete: Create project + board + invite members
        - behavior.analyzeAndRetrieve: Get behaviors + compose BCI prompt
        - workItem.executeWithTracking: Full execution with progress updates
        - analytics.fullReport: Comprehensive cost/performance report
        - compliance.fullValidation: Full compliance check with audit trail
        """
        from .mcp_long_running import is_long_running_tool

        try:
            if tool_name == "project.setupComplete":
                return await self._outcome_project_setup(params, trace_id)

            elif tool_name == "behavior.analyzeAndRetrieve":
                return await self._outcome_behavior_analyze(params, trace_id)

            elif tool_name == "workItem.executeWithTracking":
                # Use long-running handler with keepalive for execution
                if is_long_running_tool(tool_name):
                    return await self._outcome_workitem_execute_with_keepalive(params, trace_id)
                return await self._outcome_workitem_execute(params, trace_id)

            elif tool_name == "analytics.fullReport":
                return await self._outcome_analytics_report(params, trace_id)

            elif tool_name == "compliance.fullValidation":
                return await self._outcome_compliance_validate(params, trace_id)

            else:
                return {
                    "success": False,
                    "error": f"Unknown outcome tool: {tool_name}",
                    "error_code": "UNKNOWN_TOOL",
                }

        except Exception as e:
            self._logger.error(f"[{trace_id}] Outcome tool error: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Outcome operation failed: {str(e)}",
                "error_code": "SERVER_ERROR",
                "trace_id": trace_id,
            }

    async def _outcome_project_setup(self, params: Dict[str, Any], trace_id: str) -> Dict[str, Any]:
        """Create a complete project with board and team members in one operation."""
        org_service = self._services.organization_service()

        # Extract params
        name = params.get("name")
        description = params.get("description", "")
        org_id = params.get("org_id")
        board_name = params.get("board_name", "Main Board")
        member_emails = params.get("member_emails", [])

        if not name:
            return {"success": False, "error": "name is required", "error_code": "MISSING_PARAM"}
        if not org_id:
            return {"success": False, "error": "org_id is required", "error_code": "MISSING_PARAM"}

        results = {"steps": []}

        # Step 1: Create project
        try:
            project = await asyncio.to_thread(
                org_service.create_project,
                org_id=org_id,
                name=name,
                description=description,
                created_by=self._session_context.user_id or "system",
            )
            results["project"] = {"id": project.id, "name": project.name}
            results["steps"].append({"step": "create_project", "success": True})
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to create project: {e}",
                "error_code": "PROJECT_CREATE_FAILED",
                "completed_steps": results["steps"],
            }

        # Step 2: Create default board
        try:
            board_service = self._services.board_service()
            board = await asyncio.to_thread(
                board_service.create_board,
                project_id=project.id,
                name=board_name,
                created_by=self._session_context.user_id or "system",
            )
            results["board"] = {"id": board.id, "name": board.name}
            results["steps"].append({"step": "create_board", "success": True})
        except Exception as e:
            self._logger.warning(f"[{trace_id}] Board creation failed (non-fatal): {e}")
            results["steps"].append({"step": "create_board", "success": False, "error": str(e)})

        # Step 3: Invite members
        invited_count = 0
        for email in member_emails:
            try:
                await asyncio.to_thread(
                    org_service.add_project_member,
                    project_id=project.id,
                    email=email,
                    role="member",
                    added_by=self._session_context.user_id or "system",
                )
                invited_count += 1
            except Exception as e:
                self._logger.warning(f"[{trace_id}] Failed to invite {email}: {e}")

        if member_emails:
            results["steps"].append({
                "step": "invite_members",
                "success": invited_count > 0,
                "invited": invited_count,
                "total": len(member_emails),
            })

        results["success"] = True
        results["message"] = f"Project '{name}' set up successfully with {len(results['steps'])} steps completed"
        return results

    async def _outcome_behavior_analyze(self, params: Dict[str, Any], trace_id: str) -> Dict[str, Any]:
        """Analyze a task, retrieve relevant behaviors, and get recommendations."""
        task_description = params.get("task_description")
        role = params.get("role", "Student")
        include_prompt = params.get("include_prompt", True)

        if not task_description:
            return {"success": False, "error": "task_description is required", "error_code": "MISSING_PARAM"}

        behavior_service = self._services.behavior_service()
        bci_service = self._services.bci_service()

        results = {"task_description": task_description, "role": role}

        # Step 1: Get relevant behaviors
        try:
            behaviors = await asyncio.to_thread(
                behavior_service.get_for_task,
                task_description=task_description,
                role=role,
                limit=5,
            )
            results["behaviors"] = [
                {"id": b.id, "name": b.name, "description": b.description[:200] if b.description else ""}
                for b in behaviors
            ]
        except Exception as e:
            self._logger.warning(f"[{trace_id}] Behavior retrieval failed: {e}")
            results["behaviors"] = []
            results["behavior_error"] = str(e)

        # Step 2: Compose BCI prompt if requested
        if include_prompt and results.get("behaviors"):
            try:
                prompt_result = await asyncio.to_thread(
                    bci_service.compose_prompt,
                    query=task_description,
                    behaviors=results["behaviors"],
                    role=role,
                )
                results["composed_prompt"] = prompt_result.get("prompt", "")[:2000]  # Truncate for response
                results["token_estimate"] = prompt_result.get("token_count", 0)
            except Exception as e:
                self._logger.warning(f"[{trace_id}] BCI prompt composition failed: {e}")
                results["prompt_error"] = str(e)

        results["success"] = True
        results["advisory"] = self._get_role_advisory(role, results.get("behaviors", []))
        return results

    def _get_role_advisory(self, role: str, behaviors: list) -> str:
        """Generate role-specific advisory text."""
        if not behaviors:
            return f"No behaviors found for this task. Consider proposing new behaviors as a {role}."

        if role == "Student":
            return f"Found {len(behaviors)} applicable behavior(s). Follow them during execution and cite in your work."
        elif role == "Teacher":
            return f"Found {len(behaviors)} behavior(s). Validate they are appropriate and create examples if needed."
        else:  # Strategist
            return f"Found {len(behaviors)} behavior(s). Analyze for gaps and consider proposing improvements."

    async def _outcome_workitem_execute(self, params: Dict[str, Any], trace_id: str) -> Dict[str, Any]:
        """Execute a work item with tracking (without keepalive, for shorter operations)."""
        work_item_id = params.get("work_item_id")
        agent_id = params.get("agent_id")

        if not work_item_id:
            return {"success": False, "error": "work_item_id is required", "error_code": "MISSING_PARAM"}

        execution_service = self._services.work_item_execution_service()

        try:
            result = await asyncio.to_thread(
                execution_service.execute,
                work_item_id=work_item_id,
                agent_id=agent_id,
                user_id=self._session_context.user_id,
            )
            return {
                "success": True,
                "run_id": result.get("run_id"),
                "status": result.get("status"),
                "message": "Work item execution started",
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Execution failed: {e}",
                "error_code": "EXECUTION_FAILED",
            }

    async def _outcome_workitem_execute_with_keepalive(self, params: Dict[str, Any], trace_id: str) -> Dict[str, Any]:
        """Execute a work item with keepalive support for long-running operations."""
        from .mcp_long_running import ProgressReporter

        work_item_id = params.get("work_item_id")
        agent_id = params.get("agent_id")

        if not work_item_id:
            return {"success": False, "error": "work_item_id is required", "error_code": "MISSING_PARAM"}

        async def execute_with_progress(reporter: ProgressReporter):
            execution_service = self._services.work_item_execution_service()

            await reporter.update(10, "Initializing execution...")

            result = await asyncio.to_thread(
                execution_service.execute,
                work_item_id=work_item_id,
                agent_id=agent_id,
                user_id=self._session_context.user_id,
            )

            await reporter.update(100, "Execution complete")
            return result

        try:
            result = await self._long_running_handler.run_with_keepalive(
                "workItem.executeWithTracking",
                execute_with_progress,
                timeout=1800,  # 30 minutes
                heartbeat_interval=30,
            )
            return {
                "success": True,
                "run_id": result.get("run_id"),
                "status": result.get("status"),
                "message": "Work item execution completed",
            }
        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": "Execution timed out after 30 minutes",
                "error_code": "EXECUTION_TIMEOUT",
            }

    async def _outcome_analytics_report(self, params: Dict[str, Any], trace_id: str) -> Dict[str, Any]:
        """Generate a comprehensive analytics report."""
        org_id = params.get("org_id") or self._session_context.org_id
        period_days = params.get("period_days", 30)
        include_trends = params.get("include_trends", True)

        analytics_service = self._services.analytics_service()

        report = {
            "org_id": org_id,
            "period_days": period_days,
            "generated_at": datetime.utcnow().isoformat(),
        }

        # Aggregate multiple analytics calls
        try:
            # Cost summary
            cost_data = await asyncio.to_thread(
                analytics_service.get_cost_summary,
                org_id=org_id,
                days=period_days,
            )
            report["costs"] = cost_data
        except Exception as e:
            self._logger.warning(f"[{trace_id}] Cost analysis failed: {e}")
            report["cost_error"] = str(e)

        try:
            # KPI summary
            kpi_data = await asyncio.to_thread(
                analytics_service.get_kpi_summary,
                org_id=org_id,
                days=period_days,
            )
            report["kpis"] = kpi_data
        except Exception as e:
            self._logger.warning(f"[{trace_id}] KPI analysis failed: {e}")
            report["kpi_error"] = str(e)

        if include_trends:
            try:
                # Daily trends
                trend_data = await asyncio.to_thread(
                    analytics_service.get_daily_trends,
                    org_id=org_id,
                    days=period_days,
                )
                report["trends"] = trend_data
            except Exception as e:
                self._logger.warning(f"[{trace_id}] Trend analysis failed: {e}")
                report["trend_error"] = str(e)

        report["success"] = True
        return report

    async def _outcome_compliance_validate(self, params: Dict[str, Any], trace_id: str) -> Dict[str, Any]:
        """Perform comprehensive compliance validation."""
        action_id = params.get("action_id")
        policy_ids = params.get("policy_ids", [])
        generate_audit_trail = params.get("generate_audit_trail", True)

        if not action_id:
            return {"success": False, "error": "action_id is required", "error_code": "MISSING_PARAM"}

        compliance_service = self._services.compliance_service()

        validation = {
            "action_id": action_id,
            "validated_at": datetime.utcnow().isoformat(),
            "policy_results": [],
        }

        # Validate against policies
        try:
            result = await asyncio.to_thread(
                compliance_service.validate_by_action,
                action_id=action_id,
                policy_ids=policy_ids if policy_ids else None,
            )
            validation["policy_results"] = result.get("results", [])
            validation["compliant"] = result.get("compliant", False)
        except Exception as e:
            self._logger.warning(f"[{trace_id}] Policy validation failed: {e}")
            validation["policy_error"] = str(e)
            validation["compliant"] = False

        # Generate audit trail if requested
        if generate_audit_trail:
            try:
                audit_result = await asyncio.to_thread(
                    compliance_service.record_audit_entry,
                    action_id=action_id,
                    event_type="compliance_validation",
                    details=validation,
                    user_id=self._session_context.user_id,
                )
                validation["audit_entry_id"] = audit_result.get("id")
            except Exception as e:
                self._logger.warning(f"[{trace_id}] Audit trail generation failed: {e}")
                validation["audit_error"] = str(e)

        validation["success"] = True
        return validation

    # ========================================================================
    # Tool Group Management (Lazy Loading)
    # ========================================================================

    async def _handle_tools_management(
        self, tool_name: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Handle tools.* meta-tools for managing tool groups.

        MCP Best Practices Implementation:
        - Keep active tools < 128 to avoid model limits
        - Curate tools per group (5-15 per active group)
        - Dynamic activation based on context

        Supports:
        - tools.listGroups: List available tool groups with activation status
        - tools.activateGroup: Activate a tool group to load its tools
        - tools.deactivateGroup: Deactivate a group to free up context
        - tools.activeGroups: Get currently active groups and stats
        """
        try:
            if not self._lazy_loading_enabled:
                return {
                    "success": False,
                    "error": "Lazy loading is disabled. Set MCP_LAZY_LOADING=true to enable tool groups.",
                    "error_code": "LAZY_LOADING_DISABLED",
                }

            if tool_name == "tools.listGroups":
                include_keywords = params.get("include_keywords", False)
                groups = self._lazy_loader.list_available_groups()

                if not include_keywords:
                    # Remove keywords from response for cleaner output
                    for g in groups:
                        g.pop("keywords", None)

                return {
                    "success": True,
                    "groups": groups,
                    "total_groups": len(groups),
                    "active_count": sum(1 for g in groups if g.get("is_active")),
                }

            elif tool_name == "tools.activateGroup":
                group_name = params.get("group_name")
                if not group_name:
                    return {
                        "success": False,
                        "error": "group_name is required",
                        "error_code": "MISSING_PARAM",
                    }

                success, message, tools_loaded = self._lazy_loader.activate_group(group_name)

                if success:
                    self._metrics["tool_groups_activated"] += 1
                    # Refresh tools dict
                    self._tools = self._lazy_loader.get_active_tools()
                    self._tool_scopes = self._lazy_loader.get_tool_scopes()

                return {
                    "success": success,
                    "message": message,
                    "tools_loaded": tools_loaded,
                    "total_active_tools": len(self._tools),
                }

            elif tool_name == "tools.deactivateGroup":
                group_name = params.get("group_name")
                if not group_name:
                    return {
                        "success": False,
                        "error": "group_name is required",
                        "error_code": "MISSING_PARAM",
                    }

                success, message, tools_removed = self._lazy_loader.deactivate_group(group_name)

                if success and tools_removed > 0:
                    self._metrics["tool_groups_deactivated"] += 1
                    # Refresh tools dict
                    self._tools = self._lazy_loader.get_active_tools()
                    self._tool_scopes = self._lazy_loader.get_tool_scopes()

                return {
                    "success": success,
                    "message": message,
                    "tools_removed": tools_removed,
                    "total_active_tools": len(self._tools),
                }

            elif tool_name == "tools.activeGroups":
                active = self._lazy_loader.get_active_groups()
                stats = self._lazy_loader.get_stats()

                return {
                    "success": True,
                    "active_groups": active,
                    "stats": stats,
                }

            else:
                return {
                    "success": False,
                    "error": f"Unknown tools management tool: {tool_name}",
                    "error_code": "UNKNOWN_TOOL",
                }

        except Exception as e:
            self._logger.error(f"Tools management error: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Tool group operation failed: {str(e)}",
                "error_code": "SERVER_ERROR",
            }

    # ========================================================================
    # Context Switching (Phase 4: Tenant Context & Isolation)
    # ========================================================================

    async def _handle_context_tool(
        self, tool_name: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Handle context.* tools for tenant context switching.

        Phase 4: MCP_AUTH_IMPLEMENTATION_PLAN.md

        Supports:
        - context.setOrg: Switch to a different organization
        - context.setProject: Switch to a different project
        - context.getContext: Get current context state
        - context.clearContext: Clear org/project context

        Important: org_id is OPTIONAL - users can operate without an org.
        """
        try:
            if tool_name == "context.getContext":
                # Return current context (no auth check needed beyond session)
                return self._get_current_context(params)

            elif tool_name == "context.setOrg":
                org_id = params.get("org_id")
                if not org_id:
                    return {
                        "success": False,
                        "error": "org_id is required",
                        "error_code": "MISSING_PARAM",
                    }
                return await self._set_org_context(org_id)

            elif tool_name == "context.setProject":
                project_id = params.get("project_id")
                if not project_id:
                    return {
                        "success": False,
                        "error": "project_id is required",
                        "error_code": "MISSING_PARAM",
                    }
                return await self._set_project_context(project_id)

            elif tool_name == "context.clearContext":
                return self._clear_context()

            else:
                return {
                    "success": False,
                    "error": f"Unknown context tool: {tool_name}",
                    "error_code": "UNKNOWN_TOOL",
                }

        except Exception as e:
            self._logger.error(f"Context tool error: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Context operation failed: {str(e)}",
                "error_code": "SERVER_ERROR",
            }

    def _get_current_context(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Get the current session context state.

        Parameters
        ----------
        params:
            Optional parameters including workspace_id for knowledge pack lookup.

        Returns
        -------
        Dict containing session context plus active knowledge pack if available.
        """
        params = params or {}
        workspace_id = params.get("workspace_id")

        # Resolve human-friendly names for org/project (both optional)
        org_name = None
        project_name = None
        try:
            svc = self._services.organization_service()
            if svc:
                if self._session_context.org_id:
                    try:
                        org = svc.get(self._session_context.org_id)
                        org_name = org.name if org else None
                    except Exception as e:
                        self._logger.debug(f"Could not resolve org name: {e}")
                if self._session_context.project_id:
                    try:
                        proj = svc.get_project(self._session_context.project_id)
                        project_name = proj.name if proj else None
                    except Exception as e:
                        self._logger.debug(f"Could not resolve project name: {e}")
        except Exception:
            pass  # Service unavailable — names stay None

        result = {
            "user_id": self._session_context.user_id,
            "service_principal_id": self._session_context.service_principal_id,
            "email": self._session_context.email,
            "org_id": self._session_context.org_id,
            "org_name": org_name,
            "project_id": self._session_context.project_id,
            "project_name": project_name,
            "auth_method": self._session_context.auth_method,
            "roles": list(self._session_context.roles) if self._session_context.roles else [],
            "scopes": list(self._session_context.granted_scopes) if self._session_context.granted_scopes else [],
            "is_authenticated": self._session_context.is_authenticated,
            "is_admin": self._session_context.is_admin,
            "accessible_org_ids": list(self._session_context.accessible_org_ids) if self._session_context.accessible_org_ids else [],
            "accessible_project_ids": list(self._session_context.accessible_project_ids) if self._session_context.accessible_project_ids else [],
            "authenticated_at": self._session_context.authenticated_at.isoformat() if self._session_context.authenticated_at else None,
            "workspace_id": workspace_id,
            "active_pack": None,
        }

        # Look up active knowledge pack for workspace
        if workspace_id:
            try:
                from amprealize.knowledge_pack.activation_service import ActivationService
                activation_service = ActivationService()
                active = activation_service.get_active_pack(workspace_id)
                if active:
                    result["active_pack"] = {
                        "pack_id": active.pack_id,
                        "pack_version": active.pack_version,
                        "profile": active.profile,
                        "activated_at": active.activated_at.isoformat() if active.activated_at else None,
                        "activated_by": active.activated_by,
                    }
            except Exception as e:
                # Log but don't fail context retrieval
                self._logger.warning(f"Failed to get active pack for workspace {workspace_id}: {e}")

        return result

    async def _set_org_context(self, org_id: str) -> Dict[str, Any]:
        """
        Switch to a different organization context.

        Verifies the user/SP has access to the target org before switching.
        """
        identity = self._session_context.user_id or self._session_context.service_principal_id

        if not identity:
            return {
                "success": False,
                "error": "Not authenticated",
                "error_code": "NOT_AUTHENTICATED",
            }

        # Get permission service to verify org access
        permission_service = self._get_permission_service()

        if permission_service:
            try:
                # Check if user has any role in the org
                role = await permission_service.get_user_org_role(identity, org_id)

                if role is None:
                    self._logger.warning(
                        f"Context switch denied: identity={identity} has no access to org={org_id}"
                    )
                    return {
                        "success": False,
                        "error": f"Access denied to organization {org_id}",
                        "error_code": "ACCESS_DENIED",
                    }

                # Get permissions for this role
                permissions = []
                try:
                    perms = await permission_service.get_user_org_permissions(identity, org_id)
                    permissions = [p.value for p in perms]
                except Exception as perm_err:
                    self._logger.debug(f"Could not fetch permissions: {perm_err}")

                # Get org name if org service available
                org_name = None
                try:
                    org_service = self._services.organization_service()
                    if org_service:
                        org = org_service.get(org_id)
                        org_name = org.name if org else None
                except Exception as org_err:
                    self._logger.debug(f"Could not fetch org details: {org_err}")

                # Update session context
                self._session_context.org_id = org_id
                self._session_context.project_id = None  # Reset project when switching org

                self._logger.info(
                    f"Context switched: identity={identity}, org={org_id}, role={role.value}"
                )

                return {
                    "success": True,
                    "org_id": org_id,
                    "org_name": org_name,
                    "role": role.value if role else None,
                    "permissions": permissions,
                }

            except Exception as e:
                self._logger.error(f"Permission check failed: {e}")
                return {
                    "success": False,
                    "error": f"Failed to verify org access: {e}",
                    "error_code": "PERMISSION_CHECK_FAILED",
                }

        # If no permission service (dev mode), allow switching
        self._logger.warning(f"No permission service - allowing org switch without verification")
        self._session_context.org_id = org_id
        self._session_context.project_id = None

        return {
            "success": True,
            "org_id": org_id,
            "warning": "Permission verification skipped (no permission service)",
        }

    async def _set_project_context(self, project_id: str) -> Dict[str, Any]:
        """
        Switch to a different project context.

        For org-owned projects, verifies the project belongs to the current org
        (if one is set) and user has access. For user-owned projects, verifies ownership.
        """
        identity = self._session_context.user_id or self._session_context.service_principal_id

        if not identity:
            return {
                "success": False,
                "error": "Not authenticated",
                "error_code": "NOT_AUTHENTICATED",
            }

        # Get project service
        try:
            project_service = self._services.organization_service()
        except Exception:
            project_service = None

        project = None
        project_name = None
        project_org_id = None

        if project_service:
            try:
                project = project_service.get_project(project_id)
                if not project:
                    return {
                        "success": False,
                        "error": f"Project {project_id} not found",
                        "error_code": "PROJECT_NOT_FOUND",
                    }

                project_name = project.name
                project_org_id = project.org_id

                # If project belongs to an org, verify access
                if project.org_id:
                    # If we have a current org context, verify it matches
                    if self._session_context.org_id and project.org_id != self._session_context.org_id:
                        return {
                            "success": False,
                            "error": f"Project {project_id} belongs to a different organization. "
                                   f"Switch org context first with context.setOrg.",
                            "error_code": "ORG_MISMATCH",
                        }

                    # Verify user has access to the project's org
                    permission_service = self._get_permission_service()
                    if permission_service:
                        role = await permission_service.get_user_org_role(identity, project.org_id)
                        if role is None:
                            return {
                                "success": False,
                                "error": f"Access denied to project's organization",
                                "error_code": "ACCESS_DENIED",
                            }
                else:
                    # User-owned project - verify ownership or collaboration
                    if hasattr(project, 'owner_id') and project.owner_id != identity:
                        # TODO: Check collaborators when that feature is implemented
                        self._logger.debug(
                            f"Project owner mismatch: project.owner_id={project.owner_id}, identity={identity}"
                        )
                        # For now, allow access (collaborator check not implemented)

            except Exception as e:
                self._logger.error(f"Project lookup failed: {e}")
                return {
                    "success": False,
                    "error": f"Failed to verify project access: {e}",
                    "error_code": "PROJECT_LOOKUP_FAILED",
                }

        # Update session context
        self._session_context.project_id = project_id

        # Also set org context if project has one and we don't have one set
        if project_org_id and not self._session_context.org_id:
            self._session_context.org_id = project_org_id

        self._logger.info(
            f"Project context set: identity={identity}, project={project_id}, org={self._session_context.org_id}"
        )

        return {
            "success": True,
            "project_id": project_id,
            "project_name": project_name,
            "org_id": self._session_context.org_id,
        }

    def _clear_context(self) -> Dict[str, Any]:
        """Clear the org and project context."""
        self._session_context.org_id = None
        self._session_context.project_id = None

        self._logger.info(f"Context cleared for identity={self._session_context.identity}")

        return {
            "success": True,
            "message": "Organization and project context cleared",
        }

    # ========================================================================
    # Rate Limiting Tools (Phase 5: Distributed Rate Limiting)
    # ========================================================================

    async def _handle_ratelimit_tool(
        self, tool_name: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Handle ratelimit.* tools for rate limit management.

        Phase 5: MCP_AUTH_IMPLEMENTATION_PLAN.md

        Supports:
        - ratelimit.getUsage: Get current usage for org/user
        - ratelimit.getLimits: Get tier limit configuration
        - ratelimit.getMetrics: Get rate limiter metrics
        - ratelimit.reset: Reset rate limits (admin)
        """
        from .mcp_rate_limiter import SubscriptionTier, get_tier_limits

        try:
            if tool_name == "ratelimit.getUsage":
                org_id = params.get("org_id")
                user_id = params.get("user_id")

                # Default to current context if no params provided
                if not org_id and not user_id:
                    org_id = self._session_context.org_id
                    user_id = self._session_context.user_id

                return await self._distributed_rate_limiter.get_usage(
                    org_id=org_id,
                    user_id=user_id,
                )

            elif tool_name == "ratelimit.getLimits":
                tier_str = params.get("tier", "free")
                try:
                    tier = SubscriptionTier(tier_str)
                except ValueError:
                    tier = SubscriptionTier.FREE

                limits = get_tier_limits(tier)
                return {
                    "tier": tier.value,
                    "limits": limits.to_dict(),
                }

            elif tool_name == "ratelimit.getMetrics":
                return self._distributed_rate_limiter.get_metrics()

            elif tool_name == "ratelimit.reset":
                org_id = params.get("org_id")
                user_id = params.get("user_id")

                if not org_id and not user_id:
                    return {
                        "success": False,
                        "error": "org_id or user_id is required",
                        "error_code": "MISSING_PARAM",
                    }

                return await self._distributed_rate_limiter.reset_limits(
                    org_id=org_id,
                    user_id=user_id,
                )

            else:
                return {
                    "success": False,
                    "error": f"Unknown ratelimit tool: {tool_name}",
                    "error_code": "UNKNOWN_TOOL",
                }

        except Exception as e:
            self._logger.error(f"Ratelimit tool error: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Rate limit operation failed: {str(e)}",
                "error_code": "SERVER_ERROR",
            }

    async def _handle_consent_tool(
        self, tool_name: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Handle consent.* tools for JIT (Just-In-Time) authorization.

        Phase 6: MCP_AUTH_IMPLEMENTATION_PLAN.md - Consent UX Dashboard

        Supports:
        - consent.create: Create a new consent request
        - consent.lookup: Look up consent request by user code
        - consent.approve: Approve a consent request
        - consent.deny: Deny a consent request
        - consent.poll: Poll consent status (for waiting clients)
        - consent.list: List pending consent requests for a user
        """
        try:
            consent_service = self._services.consent_service()

            if tool_name == "consent.create":
                user_id = params.get("user_id")
                agent_id = params.get("agent_id")
                tool_req = params.get("tool_name")
                scopes = params.get("scopes", [])
                context = params.get("context", {})
                expires_in = params.get("expires_in", 600)

                if not user_id or not agent_id or not tool_req:
                    return {
                        "success": False,
                        "error": "user_id, agent_id, and tool_name are required",
                        "error_code": "MISSING_PARAM",
                    }

                request = await consent_service.create_request(
                    user_id=user_id,
                    agent_id=agent_id,
                    tool_name=tool_req,
                    scopes=scopes,
                    context=context,
                    expires_in=expires_in,
                )

                return {
                    "success": True,
                    "id": request.id,
                    "user_code": request.user_code,
                    "verification_uri": request.verification_uri,
                    "expires_at": request.expires_at.isoformat() if request.expires_at else None,
                }

            elif tool_name == "consent.lookup":
                user_code = params.get("user_code")
                if not user_code:
                    return {
                        "success": False,
                        "error": "user_code is required",
                        "error_code": "MISSING_PARAM",
                    }

                request = await consent_service.get_by_user_code(user_code)
                if not request:
                    return {
                        "status": "not_found",
                        "error": f"No pending consent request found for code: {user_code}",
                    }

                return request.to_dict()

            elif tool_name == "consent.approve":
                user_code = params.get("user_code")
                approver = params.get("approver") or self._session_context.user_id
                reason = params.get("reason")

                if not user_code:
                    return {
                        "success": False,
                        "error": "user_code is required",
                        "error_code": "MISSING_PARAM",
                    }

                if not approver:
                    return {
                        "success": False,
                        "error": "approver is required (or authenticate first)",
                        "error_code": "MISSING_PARAM",
                    }

                success = await consent_service.approve(
                    user_code=user_code,
                    approver_id=approver,
                    reason=reason,
                )

                return {
                    "success": success,
                    "user_code": user_code,
                    "status": "approved" if success else "not_found",
                }

            elif tool_name == "consent.deny":
                user_code = params.get("user_code")
                approver = params.get("approver") or self._session_context.user_id
                reason = params.get("reason")

                if not user_code:
                    return {
                        "success": False,
                        "error": "user_code is required",
                        "error_code": "MISSING_PARAM",
                    }

                if not approver:
                    return {
                        "success": False,
                        "error": "approver is required (or authenticate first)",
                        "error_code": "MISSING_PARAM",
                    }

                success = await consent_service.deny(
                    user_code=user_code,
                    approver_id=approver,
                    reason=reason,
                )

                return {
                    "success": success,
                    "user_code": user_code,
                    "status": "denied" if success else "not_found",
                }

            elif tool_name == "consent.poll":
                user_code = params.get("user_code")
                if not user_code:
                    return {
                        "success": False,
                        "error": "user_code is required",
                        "error_code": "MISSING_PARAM",
                    }

                poll_result = await consent_service.poll_status(user_code)
                return poll_result.to_dict()

            elif tool_name == "consent.list":
                user_id = params.get("user_id") or self._session_context.user_id
                if not user_id:
                    return {
                        "success": False,
                        "error": "user_id is required (or authenticate first)",
                        "error_code": "MISSING_PARAM",
                    }

                requests = await consent_service.list_pending_for_user(user_id)
                return {
                    "requests": [r.to_dict() for r in requests],
                    "total": len(requests),
                }

            else:
                return {
                    "success": False,
                    "error": f"Unknown consent tool: {tool_name}",
                    "error_code": "UNKNOWN_TOOL",
                }

        except Exception as e:
            self._logger.error(f"Consent tool error: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Consent operation failed: {str(e)}",
                "error_code": "SERVER_ERROR",
            }

    def _get_permission_service(self):
        """Get the AsyncPermissionService if available."""
        try:
            # Try to get from services registry
            from .multi_tenant.permissions import AsyncPermissionService

            dsn = os.environ.get("AMPREALIZE_AUTH_PG_DSN")
            if dsn:
                return AsyncPermissionService(dsn=dsn)

            # Fallback to pool-based DSN
            dsn = os.environ.get("AMPREALIZE_PG_DSN")
            if dsn:
                return AsyncPermissionService(dsn=dsn)

            return None
        except Exception as e:
            self._logger.debug(f"Could not initialize permission service: {e}")
            return None

    def _inject_session_context(self, tool_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Inject authenticated session context into tool parameters.

        This method enriches tool parameters with session identity information,
        allowing handlers to access user_id, org_id, etc. from the authenticated
        session without requiring callers to pass them explicitly.

        Priority order for each field:
        1. Explicit parameter from caller (preserved if provided)
        2. Session context value (injected if authenticated)
        3. None (if neither available)

        Args:
            tool_params: Original tool parameters from the MCP call.

        Returns:
            Enriched parameters dict with session context injected.
        """
        enriched = dict(tool_params)  # Copy to avoid mutating original

        if self._session_context.is_authenticated:
            # Inject user_id if not explicitly provided
            if "user_id" not in enriched and self._session_context.user_id:
                enriched["user_id"] = self._session_context.user_id

            # Inject org_id if not explicitly provided (for org-scoped operations)
            if "org_id" not in enriched and self._session_context.org_id:
                enriched["org_id"] = self._session_context.org_id

            # Inject project_id if not explicitly provided
            if "project_id" not in enriched and self._session_context.project_id:
                enriched["project_id"] = self._session_context.project_id

            # Add session metadata for audit/logging and authorization
            enriched["_session"] = {
                "user_id": self._session_context.user_id,
                "org_id": self._session_context.org_id,
                "project_id": self._session_context.project_id,
                "auth_method": self._session_context.auth_method,
                "roles": list(self._session_context.roles) if self._session_context.roles else [],
                "scopes": list(self._session_context.granted_scopes),
                "is_admin": self._session_context.is_admin,
                "accessible_org_ids": list(self._session_context.accessible_org_ids),
                "accessible_project_ids": list(self._session_context.accessible_project_ids),
            }

        return enriched

    def _success_response(self, request_id: Optional[str], result: Any) -> str:
        """Build JSON-RPC success response."""
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        }
        return json.dumps(response)

    def _send_notification(self, method: str, params: Dict[str, Any]) -> None:
        """
        Send a JSON-RPC notification (no response expected).

        Notifications are JSON-RPC messages without an 'id' field.
        They're useful for progress updates during long-running operations.
        """
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        self._write_stdout_message(json.dumps(notification))
        self._logger.debug(f"Sent notification: {method}")

    def _error_response(self, request_id: Optional[str], code: int, message: str, data: Any = None) -> str:
        """Build JSON-RPC error response."""
        error = {
            "code": code,
            "message": message,
        }
        if data is not None:
            error["data"] = data

        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": error,
        }
        return json.dumps(response)

    async def run(self) -> None:
        """Run MCP server main loop (stdio)."""
        self._logger.info("Amprealize MCP Server starting...")
        self._logger.info(f"Loaded {len(self._tools)} tools: {', '.join(self._tools.keys())}")
        self._logger.info(f"Idle timeout: {self._idle_timeout_seconds}s, Shutdown timeout: {self._graceful_shutdown_timeout}s")

        # Setup signal handlers for graceful shutdown (Epic 6 - Connection Stability)
        loop = asyncio.get_event_loop()

        def signal_handler(signum: int) -> None:
            sig_name = signal.Signals(signum).name
            self._logger.info(f"Received {sig_name}, initiating graceful shutdown...")
            self._shutdown_requested = True

        # Register signal handlers (Unix only)
        if sys.platform != "win32":
            for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
                loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))

        # Start idle connection cleanup task
        self._idle_check_task = asyncio.create_task(self._idle_connection_monitor())

        # Use a dedicated single thread + asyncio.Queue for stdin reading.
        # This prevents the old pattern where asyncio.wait_for + run_in_executor
        # spawns multiple threads competing for the stdin buffer lock.
        stdin_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

        def _stdin_reader_thread() -> None:
            """Dedicated thread that reads stdin and pushes messages into the queue."""
            while not self._shutdown_requested:
                try:
                    msg = self._read_stdin_message_blocking()
                    loop.call_soon_threadsafe(stdin_queue.put_nowait, msg)
                    if msg is None:
                        break  # EOF
                except Exception:
                    loop.call_soon_threadsafe(stdin_queue.put_nowait, None)
                    break

        import threading as _threading
        reader_thread = _threading.Thread(target=_stdin_reader_thread, daemon=True, name="mcp-stdin-reader")
        reader_thread.start()

        try:
            # Read requests from stdin via the dedicated reader queue
            while not self._shutdown_requested:
                try:
                    request_line = await asyncio.wait_for(
                        stdin_queue.get(),
                        timeout=1.0  # Check shutdown flag every second
                    )
                except asyncio.TimeoutError:
                    continue  # Check shutdown flag and continue

                if not request_line:
                    self._logger.info("Stdin closed, shutting down")
                    break

                request_line = request_line.strip()
                if not request_line:
                    continue

                # Update last activity for idle tracking
                self._last_activity = time.time()

                # Handle request
                response = await self.handle_request(request_line)

                if response:
                    self._write_stdout_message(response)

        except KeyboardInterrupt:
            self._logger.info("Received keyboard interrupt")
            self._shutdown_requested = True
        except Exception as e:
            self._logger.error(f"Server error: {e}", exc_info=True)
            self._shutdown_requested = True
        finally:
            await self._graceful_shutdown()

    async def _idle_connection_monitor(self) -> None:
        """Monitor for idle connections and cleanup resources (Epic 6 - Connection Stability)."""
        self._logger.info(f"Starting idle connection monitor (timeout: {self._idle_timeout_seconds}s)")

        while not self._shutdown_requested:
            try:
                await asyncio.sleep(60)  # Check every minute

                idle_duration = time.time() - self._last_activity
                if idle_duration >= self._idle_timeout_seconds:
                    self._logger.warning(
                        f"Connection idle for {idle_duration:.0f}s (threshold: {self._idle_timeout_seconds}s), "
                        "initiating idle cleanup..."
                    )
                    # Perform idle cleanup
                    await self._cleanup_idle_resources()
                    # Reset activity timer after cleanup
                    self._last_activity = time.time()
                elif idle_duration > self._idle_timeout_seconds * 0.8:
                    # Warn when approaching idle timeout
                    self._logger.info(
                        f"Connection approaching idle timeout: {idle_duration:.0f}s / {self._idle_timeout_seconds}s"
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error(f"Error in idle monitor: {e}", exc_info=True)

    async def _cleanup_idle_resources(self) -> None:
        """Clean up resources when connection is idle (Epic 6 - Connection Stability)."""
        self._logger.info("Performing idle resource cleanup...")

        try:
            # Release service caches to free memory
            self._services._behavior_service = None
            self._services._bci_service = None
            self._services._workflow_service = None
            self._services._trace_analysis_service = None
            self._services._run_service = None
            self._services._metrics_service = None
            self._services._analytics_service = None

            # Note: We keep action_service and agent_auth_service as they hold auth state
            # They'll be re-initialized lazily on next request

            self._logger.info("Idle cleanup completed - services will be re-initialized on next request")
        except Exception as e:
            self._logger.error(f"Error during idle cleanup: {e}", exc_info=True)

    async def _graceful_shutdown(self) -> None:
        """Gracefully shutdown server, draining pending requests (Epic 6 - Connection Stability)."""
        self._logger.info("Starting graceful shutdown...")

        # Cancel idle monitor
        if self._idle_check_task and not self._idle_check_task.done():
            self._idle_check_task.cancel()
            try:
                await self._idle_check_task
            except asyncio.CancelledError:
                pass

        # Wait for pending requests to complete with timeout
        if self._pending_requests:
            self._logger.info(f"Waiting for {len(self._pending_requests)} pending requests to complete...")
            pending_tasks = list(self._pending_requests.values())

            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending_tasks, return_exceptions=True),
                    timeout=self._graceful_shutdown_timeout
                )
                self._logger.info("All pending requests completed")
            except asyncio.TimeoutError:
                self._logger.warning(
                    f"Shutdown timeout ({self._graceful_shutdown_timeout}s) reached, "
                    f"cancelling {len(pending_tasks)} remaining requests"
                )
                for task in pending_tasks:
                    task.cancel()

        # Cleanup services
        self._logger.info("Cleaning up services...")
        try:
            # Close database pools
            if self._services._pools:
                for dsn, pool in self._services._pools.items():
                    try:
                        pool.close()
                        self._logger.info(f"Closed pool for DSN: {dsn[:50]}...")
                    except Exception as e:
                        self._logger.error(f"Error closing pool: {e}")
                self._services._pools.clear()
        except Exception as e:
            self._logger.error(f"Error closing database pools: {e}")

        self._logger.info("Graceful shutdown completed")


async def main() -> None:
    """Main entry point for MCP server."""
    server = MCPServer()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())
