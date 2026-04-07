"""Helpers for canonical actor surface handling.

This module centralizes normalization logic so every surface name stored in
runs, actions, telemetry, and analytics share consistent casing. Keeping
surfaces canonical avoids duplicate metrics (for example, `CLI` vs `cli`) and
simplifies downstream queries.
"""

from __future__ import annotations

from typing import Dict, Final, Optional

_DEFAULT_SURFACE: Final[str] = "unknown"

# Accept a broad set of legacy identifiers while converging on 5 canonical
# surfaces used across the product (web, cli, api, vscode, mcp). Aliases are
# stored in uppercase so lookups remain case-insensitive after we normalize
# incoming inputs (strip, replace hyphens/spaces with underscores, then upper).
_SURFACE_ALIASES: Final[Dict[str, str]] = {
    "WEB": "web",
    "CLI": "cli",
    "API": "api",
    "REST": "api",
    "REST_API": "api",
    "HTTP_API": "api",
    "DEVICE_FLOW": "api",
    "VS_CODE": "vscode",
    "VSCODE": "vscode",
    "VS-CODE": "vscode",
    "VS CODE": "vscode",
    "EXTENSION": "vscode",
    "IDE": "vscode",
    "MCP": "mcp",
    "MCP_SERVER": "mcp",
}


def normalize_actor_surface(surface: Optional[str]) -> str:
    """Return the canonical representation for an actor surface.

    Empty/None inputs resolve to ``"unknown"`` so downstream analytics can track
    data gaps explicitly. Known aliases collapse to their canonical form while
    unknown non-empty values fall back to a lowercase/underscored variant to
    keep reporting stable.
    """

    if surface is None:
        return _DEFAULT_SURFACE

    candidate = surface.strip()
    if not candidate:
        return _DEFAULT_SURFACE

    normalized = candidate.replace("-", "_").replace(" ", "_")
    canonical = _SURFACE_ALIASES.get(normalized.upper())
    if canonical:
        return canonical

    return normalized.lower()


__all__ = ["normalize_actor_surface"]
