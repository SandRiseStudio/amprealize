"""Amprealize BreakerAmp integration.

This module provides a thin wrapper around the standalone breakeramp package,
wiring it to amprealize services (ActionService, ComplianceService, MetricsService).

For standalone usage without amprealize, use the breakeramp package directly:
    pip install breakeramp
    from breakeramp import BreakerAmpService, PlanRequest

NOTE: The standalone breakeramp package is REQUIRED. Install with:
    pip install -e ./packages/breakeramp
"""

# Re-export models from standalone package
from breakeramp import (
    # Request/Response models
    PlanRequest,
    PlanResponse,
    EnvironmentEstimates,
    ApplyRequest,
    ApplyResponse,
    StatusResponse,
    HealthCheck,
    TelemetryData,
    DestroyRequest,
    DestroyResponse,
    # Infrastructure models
    Blueprint,
    ServiceSpec,
    EnvironmentDefinition,
    RuntimeConfig,
    InfrastructureConfig,
    AuditEntry,
    StatusEvent,
    # Hooks
    BreakerAmpHooks,
    # Blueprint utilities
    get_blueprint_path,
    list_blueprints,
    # Bandwidth enforcement
)
from breakeramp.service import BandwidthEnforcer

# Import the Amprealize-integrated service wrapper
from .service import AmprealizeBreakerAmpService as BreakerAmpService
from .service import RedisNotAvailableError

__all__ = [
    # Request/Response models
    "PlanRequest",
    "PlanResponse",
    "EnvironmentEstimates",
    "ApplyRequest",
    "ApplyResponse",
    "StatusResponse",
    "HealthCheck",
    "TelemetryData",
    "DestroyRequest",
    "DestroyResponse",
    # Infrastructure models
    "Blueprint",
    "ServiceSpec",
    "EnvironmentDefinition",
    "RuntimeConfig",
    "InfrastructureConfig",
    "AuditEntry",
    "StatusEvent",
    # Hooks
    "BreakerAmpHooks",
    # Service (amprealize-integrated wrapper)
    "BreakerAmpService",
    # Errors
    "RedisNotAvailableError",
    # Blueprint utilities
    "get_blueprint_path",
    "list_blueprints",
    # Bandwidth enforcement
    "BandwidthEnforcer",
]
