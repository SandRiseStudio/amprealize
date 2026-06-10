"""MCP tool handlers for Bootstrap operations.

Provides handlers for workspace profile detection, bootstrap status, and initialization.
Following `behavior_prefer_mcp_tools` - MCP provides consistent schemas and automatic telemetry.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from ...bootstrap.profile import WorkspaceProfile
from ...bootstrap.detector import WorkspaceDetector
from ...bootstrap.service import BootstrapService


# ==============================================================================
# Helpers
# ==============================================================================


def _resolve_workspace_path(arguments: Dict[str, Any]) -> Path:
    """Resolve workspace path from arguments or use current directory."""
    path_str = arguments.get("workspace_path")
    if path_str:
        return Path(path_str).resolve()
    return Path.cwd()


def _parse_profile(profile_str: Optional[str]) -> Optional[WorkspaceProfile]:
    """Parse profile string to WorkspaceProfile enum."""
    if not profile_str:
        return None
    # WorkspaceProfile values are like "solo-dev", "api-backend" etc.
    for profile in WorkspaceProfile:
        if profile.value == profile_str:
            return profile
    return None


# ==============================================================================
# Bootstrap Handlers
# ==============================================================================


def handle_bootstrap_detect(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Detect workspace profile by analyzing directory structure.

    MCP Tool: bootstrap.detect
    """
    workspace_path = _resolve_workspace_path(arguments)

    if not workspace_path.exists():
        return {
            "error": f"Workspace path does not exist: {workspace_path}",
            "profile": None,
            "confidence": 0.0,
            "is_ambiguous": False,
            "signals": [],
        }

    detector = WorkspaceDetector()
    result = detector.detect(workspace_path)

    return {
        "profile": result.profile.value,
        "confidence": result.confidence,
        "is_ambiguous": result.is_ambiguous,
        "runner_up": result.runner_up.value if result.runner_up else None,
        "signals": [
            {
                "signal_name": s.signal_name,
                "detected": s.detected,
                "confidence": s.confidence,
                "evidence": s.evidence,
            }
            for s in result.signals
        ],
    }


def handle_bootstrap_status(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get bootstrap status for a workspace.

    MCP Tool: bootstrap.status
    """
    workspace_path = _resolve_workspace_path(arguments)

    if not workspace_path.exists():
        return {
            "is_bootstrapped": False,
            "profile": None,
            "pack_id": None,
            "pack_version": None,
            "agents_md_exists": False,
            "amprealize_dir_exists": False,
            "last_updated": None,
        }

    agents_md = workspace_path / "AGENTS.md"
    amprealize_dir = workspace_path / ".amprealize"
    runtime_primer = amprealize_dir / "runtime-primer.md"
    manifest = amprealize_dir / "pack-manifest.json"

    agents_exists = agents_md.exists()
    amprealize_workspace_dir_exists = amprealize_dir.exists()

    # Determine if bootstrapped - has either AGENTS.md or .amprealize/ dir
    is_bootstrapped = agents_exists or amprealize_workspace_dir_exists

    # Try to determine profile from AGENTS.md or manifest
    profile = None
    pack_id = None
    pack_version = None
    last_updated = None

    if manifest.exists():
        import json
        try:
            manifest_data = json.loads(manifest.read_text())
            pack_id = manifest_data.get("id") or manifest_data.get("pack_id")
            pack_version = manifest_data.get("version")
        except (json.JSONDecodeError, IOError):
            pass

    # Get last updated time from most recent bootstrap file
    timestamps = []
    for f in [agents_md, runtime_primer, manifest]:
        if f.exists():
            timestamps.append(f.stat().st_mtime)

    if timestamps:
        last_updated = datetime.fromtimestamp(max(timestamps)).isoformat()

    # Try to detect current profile
    if is_bootstrapped and (agents_exists or amprealize_workspace_dir_exists):
        detector = WorkspaceDetector()
        detection = detector.detect(workspace_path)
        profile = detection.profile.value

    return {
        "is_bootstrapped": is_bootstrapped,
        "profile": profile,
        "pack_id": pack_id,
        "pack_version": pack_version,
        "agents_md_exists": agents_exists,
        "amprealize_dir_exists": amprealize_workspace_dir_exists,
        "last_updated": last_updated,
    }


def handle_bootstrap_init(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Initialize a workspace with Amprealize.

    MCP Tool: bootstrap.init
    """
    workspace_path = _resolve_workspace_path(arguments)
    profile_str = arguments.get("profile")
    skip_primer = arguments.get("skip_primer", False)
    skip_pack = arguments.get("skip_pack", False)
    force = arguments.get("force", False)

    if not workspace_path.exists():
        return {
            "success": False,
            "error": f"Workspace path does not exist: {workspace_path}",
            "profile": None,
            "files_written": [],
            "notes": [],
        }

    # Check for existing files if not forcing
    agents_md = workspace_path / "AGENTS.md"
    if agents_md.exists() and not force and not skip_primer:
        return {
            "success": False,
            "error": "AGENTS.md already exists. Use force=true to overwrite.",
            "profile": None,
            "files_written": [],
            "notes": ["Existing AGENTS.md would be overwritten"],
        }

    profile_override = _parse_profile(profile_str)

    svc = BootstrapService()
    result = svc.bootstrap(
        workspace_path,
        profile=profile_override,
        skip_primer=skip_primer,
        skip_pack=skip_pack,
    )

    return {
        "success": True,
        "profile": result.profile.value,
        "detection": result.detection_result.to_dict() if result.detection_result else None,
        "pack_id": result.pack_id,
        "pack_version": result.pack_version,
        "files_written": result.files_written,
        "notes": result.notes,
    }


# ==============================================================================
# Handler Registry
# ==============================================================================

BOOTSTRAP_HANDLERS = {
    "bootstrap.detect": handle_bootstrap_detect,
    "bootstrap.status": handle_bootstrap_status,
    "bootstrap.init": handle_bootstrap_init,
}
