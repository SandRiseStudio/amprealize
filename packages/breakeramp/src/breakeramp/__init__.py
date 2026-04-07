"""BreakerAmp - Infrastructure-as-Code orchestration with blueprint-driven container management.

BreakerAmp provides a Terraform-like workflow (plan → apply → destroy) for containerized
development environments, with built-in compliance gates, resource estimation, and
lifecycle management.

Basic usage:
    from breakeramp import BreakerAmpService, PlanRequest, ApplyRequest
    from breakeramp.executors import PodmanExecutor

    executor = PodmanExecutor()
    service = BreakerAmpService(executor=executor)

    plan = service.plan(PlanRequest(
        blueprint_id="postgres-dev",
        environment="development"
    ))
    result = service.apply(ApplyRequest(plan_id=plan.plan_id))

With hooks for external integration:
    from breakeramp import BreakerAmpService, BreakerAmpHooks

    hooks = BreakerAmpHooks(
        on_action=my_action_handler,
        on_compliance_step=my_compliance_handler,
        on_metric=my_metrics_handler,
    )
    service = BreakerAmpService(executor=executor, hooks=hooks)
"""

from breakeramp.models import (
    # Request/Response models
    PlanRequest,
    PlanResponse,
    ApplyRequest,
    ApplyResponse,
    StatusResponse,
    DestroyRequest,
    DestroyResponse,
    # Infrastructure models
    Blueprint,
    ServiceSpec,
    EnvironmentDefinition,
    RuntimeConfig,
    InfrastructureConfig,
    # Supporting models
    EnvironmentEstimates,
    HealthCheck,
    TelemetryData,
    AuditEntry,
    StatusEvent,
    # Validation models
    EnvironmentManifest,
    StrictEnvironmentDefinition,
    StrictRuntimeConfig,
    StrictInfrastructureConfig,
)
from breakeramp.hooks import BreakerAmpHooks
from breakeramp.service import BreakerAmpService

# Orchestrator for workspace management
from breakeramp.orchestrator import (
    AmpOrchestrator,
    WorkspaceConfig,
    WorkspaceInfo,
    OrchestratorHooks,
    OrchestratorError,
    WorkspaceNotFoundError,
    QuotaExceededError,
    ProvisionError,
    get_orchestrator,
)

# Quota service for plan-based limits
from breakeramp.quota import (
    QuotaService,
    QuotaLimits,
    PLAN_LIMITS,
    get_isolation_scope,
    parse_scope,
    get_quota_service,
    reset_quota_service,
    EnvironmentPlanResolver,
    DatabasePlanResolver,
)

__version__ = "0.1.0"
__all__ = [
    # Core service
    "BreakerAmpService",
    "BreakerAmpHooks",
    # Orchestrator
    "AmpOrchestrator",
    "WorkspaceConfig",
    "WorkspaceInfo",
    "OrchestratorHooks",
    "OrchestratorError",
    "WorkspaceNotFoundError",
    "QuotaExceededError",
    "ProvisionError",
    "get_orchestrator",
    # Quota service
    "QuotaService",
    "QuotaLimits",
    "PLAN_LIMITS",
    "get_isolation_scope",
    "parse_scope",
    "get_quota_service",
    "reset_quota_service",
    "EnvironmentPlanResolver",
    "DatabasePlanResolver",
    # Request/Response models
    "PlanRequest",
    "PlanResponse",
    "ApplyRequest",
    "ApplyResponse",
    "StatusResponse",
    "DestroyRequest",
    "DestroyResponse",
    # Infrastructure models
    "Blueprint",
    "ServiceSpec",
    "EnvironmentDefinition",
    "RuntimeConfig",
    "InfrastructureConfig",
    # Supporting models
    "EnvironmentEstimates",
    "HealthCheck",
    "TelemetryData",
    "AuditEntry",
    "StatusEvent",
    # Validation models
    "EnvironmentManifest",
    "StrictEnvironmentDefinition",
    "StrictRuntimeConfig",
    "StrictInfrastructureConfig",
    # Blueprints utilities
    "get_blueprint_path",
    "list_blueprints",
]

# Blueprint utilities
from breakeramp.blueprints import get_blueprint_path, list_blueprints
