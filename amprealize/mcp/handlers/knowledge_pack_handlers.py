"""MCP tool handlers for Knowledge Pack operations.

Provides handlers for building, validating, inspecting, and listing knowledge packs.
Following `behavior_prefer_mcp_tools` - MCP provides consistent schemas and automatic telemetry.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict

from ...knowledge_pack.validator import validate_manifest
from ...knowledge_pack.schema import (
    KnowledgePackManifest,
    ValidationResult,
)


# ==============================================================================
# Serialization Helpers
# ==============================================================================


def _serialize_value(value: Any) -> Any:
    """Recursively serialize values for JSON output."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):  # Enum
        return value.value
    if hasattr(value, "model_dump"):  # Pydantic model
        return {k: _serialize_value(v) for k, v in value.model_dump().items()}
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_value(v) for v in value]
    return str(value)


def _manifest_to_dict(manifest: KnowledgePackManifest) -> Dict[str, Any]:
    """Convert KnowledgePackManifest to dict with serialized values."""
    result = manifest.model_dump()
    return {k: _serialize_value(v) for k, v in result.items()}


def _get_actor(arguments: Dict[str, Any]) -> Dict[str, str]:
    """Extract actor from arguments or create default."""
    actor = arguments.get("actor", {})
    return {
        "id": actor.get("id", "mcp-user"),
        "role": actor.get("role", "user"),
        "surface": actor.get("surface", "MCP"),
    }


# ==============================================================================
# Knowledge Pack Handlers
# ==============================================================================


def handle_knowledge_pack_build(
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build a knowledge pack from registered sources.

    MCP Tool: knowledgePacks.build
    """
    # Import lazily to avoid circular dependencies
    from ...knowledge_pack.builder import PackBuilder, PackBuildConfig
    from ...knowledge_pack.extractor import SourceExtractor
    from ...knowledge_pack.source_registry import SourceRegistryService

    pack_id = arguments.get("pack_id")
    version = arguments.get("version", "1.0.0")
    workspace_profiles = arguments.get("workspace_profiles", [])
    target_surfaces = arguments.get("target_surfaces", [])
    source_filter = arguments.get("source_filter")
    actor = _get_actor(arguments)

    if not pack_id:
        return {
            "success": False,
            "error": "pack_id is required",
        }

    try:
        # Create builder with source registry and extractor
        registry = SourceRegistryService()
        extractor = SourceExtractor()
        builder = PackBuilder(registry=registry, extractor=extractor)

        # Create build config
        config = PackBuildConfig(
            pack_id=pack_id,
            version=version,
            workspace_profiles=workspace_profiles,
            target_surfaces=target_surfaces,
            source_filter=source_filter,
            created_by=actor.get("id", "mcp-user"),
        )

        # Build the pack
        artifact = builder.build(config)

        # Persist the artifact to storage
        from ...knowledge_pack.storage import KnowledgePackStorage
        storage = KnowledgePackStorage()
        save_result = storage.save_artifact(
            artifact,
            status="published",
            created_by=actor.get("id", "mcp-user"),
        )

        # Calculate statistics from the artifact
        overlays_by_kind: Dict[str, int] = {}
        for overlay in artifact.overlays:
            ok = overlay.kind.value
            overlays_by_kind[ok] = overlays_by_kind.get(ok, 0) + 1

        sources_by_type: Dict[str, int] = {}
        for source in artifact.manifest.sources:
            st = source.type.value
            sources_by_type[st] = sources_by_type.get(st, 0) + 1

        return {
            "success": True,
            "pack_id": artifact.manifest.pack_id,
            "version": artifact.manifest.version,
            "scope": artifact.manifest.scope.value,
            "overlay_count": len(artifact.overlays),
            "source_count": len(artifact.manifest.sources),
            "primer_chars": len(artifact.primer_text),
            "overlay_count_stored": save_result.get("overlay_count", 0),
            "statistics": {
                "overlays_by_kind": overlays_by_kind,
                "sources_by_type": sources_by_type,
            },
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def handle_knowledge_pack_validate(
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Validate a knowledge pack manifest.

    MCP Tool: knowledgePacks.validate
    """
    manifest_data = arguments.get("manifest")
    manifest_path = arguments.get("manifest_path")
    strict = arguments.get("strict", False)
    _actor = _get_actor(arguments)

    if not manifest_data and not manifest_path:
        return {
            "success": False,
            "error": "Either manifest or manifest_path is required",
        }

    try:
        # Load manifest from path if provided
        if manifest_path:
            with open(manifest_path, "r") as f:
                manifest_data = json.load(f)

        # Parse into Pydantic model for validation
        parsed_manifest = KnowledgePackManifest.model_validate(manifest_data)

        # Use the validator function for semantic checks
        result: ValidationResult = validate_manifest(parsed_manifest)

        # Convert issues to dicts
        error_issues = [
            {
                "severity": "error",
                "code": issue.level,
                "message": issue.message,
                "path": issue.path,
            }
            for issue in result.errors
        ]
        warning_issues = [
            {
                "severity": "warning",
                "code": issue.level,
                "message": issue.message,
                "path": issue.path,
            }
            for issue in result.warnings
        ]
        all_issues = error_issues + warning_issues

        error_count = len(result.errors)
        warning_count = len(result.warnings)

        # In strict mode, warnings count as failures
        valid = result.valid and (not strict or warning_count == 0)

        return {
            "success": True,
            "valid": valid,
            "error_count": error_count,
            "warning_count": warning_count,
            "issues": all_issues,
        }

    except FileNotFoundError:
        return {
            "success": False,
            "error": f"Manifest file not found: {manifest_path}",
        }
    except json.JSONDecodeError as e:
        return {
            "success": False,
            "error": f"Invalid JSON in manifest file: {e}",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def handle_knowledge_pack_inspect(
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Inspect a built knowledge pack from storage.

    MCP Tool: knowledgePacks.inspect
    """
    from ...knowledge_pack.storage import KnowledgePackStorage, PackNotFoundError

    pack_id = arguments.get("pack_id")
    version = arguments.get("version")
    include_overlays = arguments.get("include_overlays", True)
    include_primer = arguments.get("include_primer", False)
    _actor = _get_actor(arguments)

    if not pack_id:
        return {
            "success": False,
            "error": "pack_id is required",
        }

    try:
        storage = KnowledgePackStorage()
        manifest_data = storage.get_manifest(pack_id, version)

        result: Dict[str, Any] = {
            "success": True,
            "pack_id": manifest_data.get("pack_id", pack_id),
            "version": manifest_data.get("version", version),
            "scope": manifest_data.get("scope"),
            "behavior_refs": manifest_data.get("behavior_refs", []),
            "sources": manifest_data.get("sources", []),
            "constraints": manifest_data.get("constraints"),
            "storage_meta": manifest_data.get("_storage_meta"),
        }

        if include_primer:
            result["primer_text"] = manifest_data.get("_primer_text")

        if include_overlays:
            v = manifest_data.get("version", version)
            overlays = storage.get_overlays(pack_id, v)
            result["overlays"] = overlays
            result["overlay_count"] = len(overlays)

        return result

    except PackNotFoundError:
        return {
            "success": False,
            "error": f"Pack {pack_id}{'@' + version if version else ' (latest)'} not found",
            "pack_id": pack_id,
            "version": version,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def handle_knowledge_pack_list(
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    List available knowledge packs from storage.

    MCP Tool: knowledgePacks.list
    """
    from ...knowledge_pack.storage import KnowledgePackStorage

    scope = arguments.get("scope")
    status = arguments.get("status")
    limit = arguments.get("limit", 50)
    offset = arguments.get("offset", 0)
    _actor = _get_actor(arguments)

    try:
        storage = KnowledgePackStorage()
        result = storage.list_packs(
            scope=scope,
            status=status,
            limit=limit,
            offset=offset,
        )
        result["success"] = True
        return result

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "packs": [],
            "total_count": 0,
            "limit": limit,
            "offset": offset,
        }


# ==============================================================================
# Handler Registry
# ==============================================================================


KNOWLEDGE_PACK_HANDLERS = {
    "knowledgePacks.build": handle_knowledge_pack_build,
    "knowledgePacks.validate": handle_knowledge_pack_validate,
    "knowledgePacks.inspect": handle_knowledge_pack_inspect,
    "knowledgePacks.list": handle_knowledge_pack_list,
}
