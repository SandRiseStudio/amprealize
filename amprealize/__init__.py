"""Amprealize core package providing service stubs used across parity surfaces.

Imports are **lazy** — heavy service modules are loaded on first attribute
access so that ``import amprealize`` (and any relative import from a sub-module)
does not pay a multi-second penalty for pulling in SQLAlchemy, asyncpg, etc.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

# ---------------------------------------------------------------------------
# Enterprise edition detection
# ---------------------------------------------------------------------------
try:
    import amprealize_enterprise as _enterprise  # noqa: F401

    HAS_ENTERPRISE = True
except ImportError:
    HAS_ENTERPRISE = False

# ---------------------------------------------------------------------------
# Lazy import mapping: attribute_name → (relative_module, attribute_name_in_module)
# ---------------------------------------------------------------------------
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    # action_service
    "ActionService": (".action_service", "ActionService"),
    "ActionServiceError": (".action_service", "ActionServiceError"),
    "ActionNotFoundError": (".action_service", "ActionNotFoundError"),
    "ReplayNotFoundError": (".action_service", "ReplayNotFoundError"),
    # action_service_postgres
    "PostgresActionService": (".action_service_postgres", "PostgresActionService"),
    # action_contracts
    "Action": (".action_contracts", "Action"),
    "ActionCreateRequest": (".action_contracts", "ActionCreateRequest"),
    "ReplayRequest": (".action_contracts", "ReplayRequest"),
    "ReplayStatus": (".action_contracts", "ReplayStatus"),
    "Actor": (".action_contracts", "Actor"),
    # bci_service
    "BCIService": (".bci_service", "BCIService"),
    # agent_auth
    "AgentAuthClient": (".agent_auth", "AgentAuthClient"),
    "DecisionReason": (".agent_auth", "DecisionReason"),
    "EnsureGrantRequest": (".agent_auth", "EnsureGrantRequest"),
    "EnsureGrantResponse": (".agent_auth", "EnsureGrantResponse"),
    "GrantDecision": (".agent_auth", "GrantDecision"),
    "GrantMetadata": (".agent_auth", "GrantMetadata"),
    "ListGrantsRequest": (".agent_auth", "ListGrantsRequest"),
    "Obligation": (".agent_auth", "Obligation"),
    "PolicyPreviewRequest": (".agent_auth", "PolicyPreviewRequest"),
    "PolicyPreviewResponse": (".agent_auth", "PolicyPreviewResponse"),
    "RevokeGrantRequest": (".agent_auth", "RevokeGrantRequest"),
    "RevokeGrantResponse": (".agent_auth", "RevokeGrantResponse"),
    # run_service
    "RunService": (".run_service", "RunService"),
    "PostgresRunService": (".run_service_postgres", "PostgresRunService"),
    # telemetry
    "TelemetryClient": (".telemetry", "TelemetryClient"),
    "TelemetryEvent": (".telemetry", "TelemetryEvent"),
    "InMemoryTelemetrySink": (".telemetry", "InMemoryTelemetrySink"),
    # task_assignments
    "TaskAssignmentService": (".task_assignments", "TaskAssignmentService"),
}

# Sub-module lazy mapping (for ``from amprealize import bci_contracts``)
_LAZY_SUBMODULES: dict[str, str] = {
    "bci_contracts": ".bci_contracts",
}


def __getattr__(name: str):  # noqa: N807
    if name in _LAZY_IMPORTS:
        module_path, attr = _LAZY_IMPORTS[name]
        mod = importlib.import_module(module_path, __name__)
        value = getattr(mod, attr)
        globals()[name] = value  # cache for subsequent accesses
        return value
    if name in _LAZY_SUBMODULES:
        mod = importlib.import_module(_LAZY_SUBMODULES[name], __name__)
        globals()[name] = mod
        return mod
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "HAS_ENTERPRISE",
    "ActionService",
    "ActionServiceError",
    "ActionNotFoundError",
    "ReplayNotFoundError",
    "PostgresActionService",
    "Action",
    "ActionCreateRequest",
    "ReplayRequest",
    "ReplayStatus",
    "Actor",
    "AgentAuthClient",
    "EnsureGrantRequest",
    "EnsureGrantResponse",
    "GrantMetadata",
    "GrantDecision",
    "DecisionReason",
    "Obligation",
    "RevokeGrantRequest",
    "RevokeGrantResponse",
    "ListGrantsRequest",
    "PolicyPreviewRequest",
    "PolicyPreviewResponse",
    "RunService",
    "PostgresRunService",
    "TelemetryClient",
    "TelemetryEvent",
    "InMemoryTelemetrySink",
    "TaskAssignmentService",
    "BCIService",
    "bci_contracts",
]
