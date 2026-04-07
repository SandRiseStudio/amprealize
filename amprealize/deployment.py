"""Deployment resolver — resolve service endpoints from deployment config.

Maps the deployment mode (local / cloud / hybrid) to concrete endpoints
for each service (storage, compute, auth).

Part of Phase 1 of GUIDEAI-619 (Modular Installation System v3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from amprealize import HAS_ENTERPRISE

if TYPE_CHECKING:
    from amprealize.config.schema import DeploymentConfig


# ---------------------------------------------------------------------------
# Service endpoints
# ---------------------------------------------------------------------------


@dataclass
class ServiceEndpoints:
    """Resolved endpoints for each service layer."""

    storage: str  # "local" or a cloud URL
    compute: str  # "local" or a cloud URL
    auth: str  # "local" or a cloud URL


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


def resolve_service_endpoints(config: DeploymentConfig) -> ServiceEndpoints:
    """Map deployment config to concrete service endpoints.

    * ``local`` → all services are ``"local"``
    * ``cloud`` → all services point to ``config.cloud_url``
    * ``hybrid`` → per-service override from ``config.services``
    """
    cloud_url = config.cloud_url

    if config.mode == "local":
        return ServiceEndpoints(
            storage="local",
            compute="local",
            auth="local",
        )

    if config.mode == "cloud":
        return ServiceEndpoints(
            storage=f"{cloud_url}/storage",
            compute=f"{cloud_url}/compute",
            auth=f"{cloud_url}/auth",
        )

    # hybrid — per-service
    def _resolve(svc_mode: str, path: str) -> str:
        return "local" if svc_mode == "local" else f"{cloud_url}/{path}"

    return ServiceEndpoints(
        storage=_resolve(config.services.storage, "storage"),
        compute=_resolve(config.services.compute, "compute"),
        # Auth is always driven by deployment mode in hybrid — local
        auth="local",
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_deployment(config: DeploymentConfig) -> list[str]:
    """Return list of error messages, or empty list if valid."""
    errors: list[str] = []

    if config.mode in ("cloud", "hybrid") and not HAS_ENTERPRISE:
        errors.append(
            f"Deployment mode {config.mode!r} requires amprealize-enterprise. "
            f"Install with: pip install amprealize-enterprise"
        )

    if config.mode == "cloud" and (
        config.services.storage == "local"
        or config.services.compute == "local"
    ):
        # In cloud mode the services config is ignored, but warn if set oddly
        pass  # Not an error — cloud mode overrides everything

    if config.mode != "hybrid" and (
        config.services.storage != "local"
        or config.services.compute != "local"
    ):
        # Non-default services config outside hybrid mode
        errors.append(
            f"services overrides are only meaningful when deployment.mode "
            f"is 'hybrid', but mode is {config.mode!r}"
        )

    if not config.cloud_url.startswith("https://"):
        errors.append(
            f"cloud_url must start with https://, got {config.cloud_url!r}"
        )

    return errors
