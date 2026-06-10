"""Amprealize BreakerAmp integration.

This module provides a thin wrapper around the standalone breakeramp package,
wiring it to amprealize services (ActionService, ComplianceService, MetricsService).

For standalone usage without amprealize, use the breakeramp package directly:
    pip install breakeramp
    from breakeramp import BreakerAmpService, PlanRequest

NOTE: The standalone breakeramp package is REQUIRED. Install with:
    pip install -e ./packages/breakeramp
"""

from __future__ import annotations

import importlib.util
import site
import sys
from pathlib import Path


def _ensure_site_packages_breakeramp() -> None:
    """Register the real ``breakeramp`` distribution before ``from breakeramp import``.

    When ``PYTHONPATH`` includes the inner ``amprealize`` package directory, Python also
    exposes a **top-level** ``breakeramp`` package from ``amprealize/breakeramp/``. A bare
    ``import breakeramp`` then loads this shim as ``breakeramp``, and
    ``from breakeramp import …`` inside this file circular-imports. Loading the
    site-packages (or editable ``packages/breakeramp``) tree first fixes that.

    Prefer ``PYTHONPATH=<repo-root>`` so only ``import amprealize`` resolves the inner
    package and ``import breakeramp`` hits site-packages naturally.
    """

    existing = sys.modules.get("breakeramp")
    if existing is not None:
        mod_file = (getattr(existing, "__file__", "") or "").replace("\\", "/")
        if "site-packages" in mod_file:
            return
        if "/packages/breakeramp/" in mod_file:
            return

    roots: list[Path] = []
    for sp in site.getsitepackages():
        roots.append(Path(sp) / "breakeramp")
    user_site = site.getusersitepackages()
    if user_site:
        roots.append(Path(user_site) / "breakeramp")

    _here = Path(__file__).resolve()
    repo_root = _here.parent.parent.parent
    roots.append(repo_root / "packages" / "breakeramp" / "src" / "breakeramp")

    vendor_init: Path | None = None
    for root in roots:
        candidate = root / "__init__.py"
        if candidate.is_file():
            vendor_init = candidate
            break

    if vendor_init is None:
        raise ImportError(
            "The standalone 'breakeramp' package is required. Install with:\n"
            "  pip install -e ./packages/breakeramp\n"
            "If PYTHONPATH points at the inner amprealize sources directory, either "
            "point it at the repository root (parent of the inner `amprealize` folder) "
            "or rely on this loader (above paths searched)."
        )

    if "breakeramp" in sys.modules:
        del sys.modules["breakeramp"]
    for key in list(sys.modules):
        if key.startswith("breakeramp."):
            del sys.modules[key]

    spec = importlib.util.spec_from_file_location(
        "breakeramp",
        vendor_init,
        submodule_search_locations=[str(vendor_init.parent)],
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load breakeramp from {vendor_init}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["breakeramp"] = mod
    spec.loader.exec_module(mod)


_ensure_site_packages_breakeramp()

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
