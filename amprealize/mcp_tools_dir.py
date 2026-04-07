"""Resolve the directory containing MCP tool JSON manifests (wheel vs monorepo)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def get_mcp_tools_directory() -> Path | None:
    """Return the active MCP tools directory, or None if no manifests are available.

    Resolution order:
    1. Monorepo checkout: ``<repo>/mcp/tools`` (next to the ``amprealize`` package) so
       developers edit canonical manifests without running sync.
    2. Bundled wheel/sdist: ``amprealize/mcp_tool_manifests`` (copied from ``mcp/tools`` at
       release time via ``scripts/sync_mcp_tool_manifests.py``).
    """

    amprealize_pkg = Path(__file__).resolve().parent
    repo_candidate = amprealize_pkg.parent / "mcp" / "tools"
    if repo_candidate.is_dir() and any(repo_candidate.glob("*.json")):
        return repo_candidate

    bundled = amprealize_pkg / "mcp_tool_manifests"
    if bundled.is_dir() and any(bundled.glob("*.json")):
        return bundled

    return None
