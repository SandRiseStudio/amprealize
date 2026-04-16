"""Platform shell metadata — version, distribution, edition, active context.

Used by the web console sidebar and other surfaces that need a single
read-only snapshot without duplicating edition or context resolution logic.
"""

from __future__ import annotations

import importlib.metadata
from typing import Any, Literal

from amprealize.context import get_context_name
from amprealize.edition import Edition, detect_edition


def _normalize_context_name(raw: str) -> str:
    """Drop backend-only suffixes such as ``:pg`` from context labels."""
    name = raw.strip() or "default"
    if name.endswith(":pg"):
        return name[:-3]
    return name


def _resolve_installed_version() -> str:
    """Prefer installed dist metadata; fall back to ``0.1.0``."""
    for dist_name in ("amprealize-enterprise", "amprealize"):
        try:
            return importlib.metadata.version(dist_name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return "0.1.0"


def build_platform_runtime_dict() -> dict[str, Any]:
    """Assemble payload for ``GET /api/v1/platform/runtime``."""
    edition = detect_edition()
    ctx = _normalize_context_name(get_context_name())
    version = _resolve_installed_version()

    if edition == Edition.OSS:
        return {
            "version": version,
            "distribution": "oss",
            "edition": None,
            "context_name": ctx,
        }

    tier: Literal["starter", "premium"] = (
        "premium" if edition == Edition.ENTERPRISE_PREMIUM else "starter"
    )
    return {
        "version": version,
        "distribution": "enterprise",
        "edition": tier,
        "context_name": ctx,
    }
