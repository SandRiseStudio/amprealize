"""
MCP Lazy Tool Loader

Implements dynamic tool loading based on:
1. Core tools always loaded (essential subset)
2. Tool groups activated on demand via activate_* tools
3. Context-aware auto-activation based on conversation keywords
4. Respects 128 tool limit with intelligent pruning

This follows MCP best practices:
- "Ruthless Curation: Aim for 5-15 tools per server"
- We implement this as 5-15 tools per *active group*, not per server
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .mcp_tools_dir import get_mcp_tools_directory
from .mcp_tool_groups import (
    CORE_TOOLS,
    OUTCOME_TOOLS,
    TOOL_GROUPS,
    ToolGroup,
    ToolGroupId,
    calculate_tool_allocation,
    get_max_tools_budget,
    match_tool_to_group,
    suggest_groups_for_query,
)


@dataclass
class ToolLoadState:
    """Tracks the state of loaded tools and active groups."""

    active_groups: Set[ToolGroupId] = field(default_factory=lambda: {ToolGroupId.CORE})
    loaded_tools: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    tool_scopes: Dict[str, List[str]] = field(default_factory=dict)
    last_activation: Dict[ToolGroupId, datetime] = field(default_factory=dict)
    activation_count: Dict[ToolGroupId, int] = field(default_factory=dict)

    # Auto-deactivation after inactivity (15 minutes)
    auto_deactivate_minutes: int = 15

    def is_group_active(self, group_id: ToolGroupId) -> bool:
        """Check if a tool group is currently active."""
        return group_id in self.active_groups

    def get_stale_groups(self) -> List[ToolGroupId]:
        """Get groups that haven't been used recently and could be deactivated."""
        now = datetime.utcnow()
        stale = []

        for group_id in self.active_groups:
            if group_id == ToolGroupId.CORE:
                continue  # Never deactivate core

            last_use = self.last_activation.get(group_id)
            if last_use and (now - last_use) > timedelta(minutes=self.auto_deactivate_minutes):
                stale.append(group_id)

        return stale


class MCPLazyToolLoader:
    """Manages lazy loading of MCP tools with group-based activation."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self._logger = logger or logging.getLogger("amprealize.mcp_tool_loader")
        self._state = ToolLoadState()
        self._all_tool_manifests: Dict[str, Dict[str, Any]] = {}
        self._tools_dir: Optional[Path] = None
        self._initialized = False

        # Module gating — when set, only tools matching enabled prefixes
        # (or not belonging to any module) are loaded.
        self._enabled_mcp_prefixes: Optional[Set[str]] = None
        self._all_module_mcp_prefixes: Optional[Set[str]] = None

    def set_module_filter(
        self,
        enabled_prefixes: Set[str],
        all_module_prefixes: Set[str],
    ) -> None:
        """Configure module-based tool filtering.

        Args:
            enabled_prefixes: MCP tool prefixes from currently enabled modules.
            all_module_prefixes: MCP tool prefixes from ALL modules (for ownership check).
        """
        self._enabled_mcp_prefixes = enabled_prefixes
        self._all_module_mcp_prefixes = all_module_prefixes
        self._logger.info(
            f"Module filter set: {len(enabled_prefixes)} enabled prefixes, "
            f"{len(all_module_prefixes)} total module prefixes"
        )

    def _is_tool_allowed_by_module(self, tool_name: str) -> bool:
        """Check if a tool is allowed based on module gating.

        A tool is allowed if:
        - No module filter is configured (all tools pass), OR
        - The tool does NOT belong to any module (platform/infra tool), OR
        - The tool's prefix is in the enabled set.
        """
        if self._all_module_mcp_prefixes is None:
            return True  # No filter configured

        # Check if tool belongs to any module
        for prefix in self._all_module_mcp_prefixes:
            if tool_name.startswith(f"{prefix}.") or tool_name.startswith(f"{prefix}_"):
                # Module-owned tool — check if its module is enabled
                return prefix in (self._enabled_mcp_prefixes or set())

        # Not module-owned — always allowed
        return True

    def initialize(self, tools_dir: Optional[Path] = None) -> None:
        """Initialize the loader by scanning all available tool manifests.

        Args:
            tools_dir: Path to mcp/tools directory. Defaults to standard location.
        """
        if tools_dir:
            self._tools_dir = tools_dir
        else:
            resolved = get_mcp_tools_directory()
            self._tools_dir = resolved

        if not self._tools_dir or not self._tools_dir.exists():
            self._logger.warning(
                f"MCP tools directory not found: {self._tools_dir!r}"
            )
            return

        # Scan all manifests but don't load into active set yet
        self._scan_all_manifests()

        # Load core tools
        self._activate_group(ToolGroupId.CORE)

        # Load outcome tools (high-level consolidated tools)
        self._load_outcome_tools()

        self._initialized = True
        self._logger.info(
            f"MCPLazyToolLoader initialized: {len(self._all_tool_manifests)} total tools, "
            f"{len(self._state.loaded_tools)} active (core + outcome tools)"
        )

    def _scan_all_manifests(self) -> None:
        """Scan all tool manifests without loading them into active set."""
        if not self._tools_dir:
            return

        for manifest_path in self._tools_dir.glob("*.json"):
            try:
                with open(manifest_path) as f:
                    manifest = json.load(f)

                original_name = manifest.get("name")
                if not original_name:
                    continue

                # Store with original name as key
                self._all_tool_manifests[original_name] = {
                    "manifest": manifest,
                    "path": manifest_path,
                    "group": match_tool_to_group(original_name),
                }

            except Exception as e:
                self._logger.error(f"Failed to scan manifest {manifest_path}: {e}")

    def _normalize_tool_name(self, name: str) -> str:
        """Normalize tool name for MCP compliance."""
        normalized = name.replace(".", "_").replace("/", "_")
        normalized = normalized.lower()
        normalized = re.sub(r"[^a-z0-9_-]", "_", normalized)
        return normalized

    def _load_tool_manifest(self, original_name: str) -> Optional[Dict[str, Any]]:
        """Load a specific tool manifest into the active set."""
        tool_info = self._all_tool_manifests.get(original_name)
        if not tool_info:
            return None

        manifest = tool_info["manifest"].copy()
        normalized_name = self._normalize_tool_name(original_name)

        manifest["name"] = normalized_name
        manifest["_original_name"] = original_name

        # Resolve $refs in inputSchema
        if "inputSchema" in manifest and self._tools_dir:
            manifest["inputSchema"] = self._resolve_json_refs(
                manifest["inputSchema"],
                tool_info["path"].parent
            )

        self._state.loaded_tools[normalized_name] = manifest

        # Track scopes
        if "required_scopes" in manifest:
            self._state.tool_scopes[normalized_name] = manifest["required_scopes"]

        return manifest

    def _resolve_json_refs(self, obj: Any, base_path: Path, root_doc: Optional[Dict] = None) -> Any:
        """Resolve $ref references in JSON schema objects."""
        if isinstance(obj, dict):
            if "$ref" in obj and isinstance(obj["$ref"], str):
                ref = obj["$ref"]

                # Handle internal refs
                if ref.startswith("#/") and root_doc is not None:
                    try:
                        parts = ref[2:].split("/")
                        target = root_doc
                        for part in parts:
                            if isinstance(target, dict) and part in target:
                                target = target[part]
                            else:
                                return {"type": "object", "additionalProperties": True}
                        return self._resolve_json_refs(target, base_path, root_doc)
                    except Exception:
                        return {"type": "object", "additionalProperties": True}

                # Handle file refs
                elif "#" in ref or ref.endswith(".json"):
                    try:
                        if "#" in ref:
                            file_path, json_pointer = ref.split("#", 1)
                        else:
                            file_path, json_pointer = ref, ""

                        resolved_path = (base_path / file_path).resolve()
                        if resolved_path.exists():
                            with open(resolved_path) as f:
                                schema_doc = json.load(f)

                            if json_pointer:
                                parts = json_pointer.strip("/").split("/")
                                target = schema_doc
                                for part in parts:
                                    if isinstance(target, dict) and part in target:
                                        target = target[part]
                                    else:
                                        return {"type": "object", "additionalProperties": True}
                                return self._resolve_json_refs(target, resolved_path.parent, schema_doc)
                            else:
                                return self._resolve_json_refs(schema_doc, resolved_path.parent, schema_doc)
                    except Exception:
                        return {"type": "object", "additionalProperties": True}

            return {k: self._resolve_json_refs(v, base_path, root_doc) for k, v in obj.items()}

        elif isinstance(obj, list):
            return [self._resolve_json_refs(item, base_path, root_doc) for item in obj]

        return obj

    def _load_outcome_tools(self) -> None:
        """Load high-level outcome-focused tools."""
        for tool_name, tool_def in OUTCOME_TOOLS.items():
            # Module gating — skip tools whose module is disabled
            if not self._is_tool_allowed_by_module(tool_name):
                self._logger.debug(f"Skipping outcome tool (module disabled): {tool_name}")
                continue

            normalized_name = self._normalize_tool_name(tool_name)

            manifest = {
                "name": normalized_name,
                "_original_name": tool_name,
                "description": tool_def["description"],
                "inputSchema": tool_def["inputSchema"],
                "_is_outcome_tool": True,
                "_replaces": tool_def.get("replaces", []),
            }

            self._state.loaded_tools[normalized_name] = manifest
            self._logger.debug(f"Loaded outcome tool: {tool_name}")

    def _activate_group(self, group_id: ToolGroupId) -> int:
        """Activate a tool group, loading its tools into the active set.

        Returns:
            Number of tools loaded for this group
        """
        if group_id not in TOOL_GROUPS:
            self._logger.warning(f"Unknown tool group: {group_id}")
            return 0

        group = TOOL_GROUPS[group_id]
        loaded_count = 0

        # Find tools matching this group's prefixes
        for original_name, tool_info in self._all_tool_manifests.items():
            if group_id == ToolGroupId.CORE:
                # CORE group uses CORE_TOOLS as the authoritative set —
                # it contains tools from many prefixes (auth, behaviors,
                # research_wiki, tools, etc.) so prefix matching alone
                # would miss cross-cutting tools.
                if original_name not in CORE_TOOLS:
                    continue
            else:
                # Non-core groups use prefix matching
                matches_group = False
                for prefix in group.tool_prefixes:
                    if original_name.startswith(prefix):
                        matches_group = True
                        break

                if not matches_group:
                    continue

            # Module gating — skip tools whose module is disabled
            if not self._is_tool_allowed_by_module(original_name):
                continue

            # Check budget
            if loaded_count >= group.max_tools:
                break

            # Load if not already loaded
            normalized = self._normalize_tool_name(original_name)
            if normalized not in self._state.loaded_tools:
                if self._load_tool_manifest(original_name):
                    loaded_count += 1

        self._state.active_groups.add(group_id)
        self._state.last_activation[group_id] = datetime.utcnow()
        self._state.activation_count[group_id] = self._state.activation_count.get(group_id, 0) + 1

        self._logger.info(f"Activated group {group_id.value}: loaded {loaded_count} tools")
        return loaded_count

    def _deactivate_group(self, group_id: ToolGroupId) -> int:
        """Deactivate a tool group, removing its tools from the active set.

        Returns:
            Number of tools removed
        """
        if group_id == ToolGroupId.CORE:
            self._logger.warning("Cannot deactivate core tool group")
            return 0

        if group_id not in self._state.active_groups:
            return 0

        group = TOOL_GROUPS.get(group_id)
        if not group:
            return 0

        removed_count = 0
        tools_to_remove = []

        # Find tools belonging to this group
        for normalized_name, manifest in list(self._state.loaded_tools.items()):
            original_name = manifest.get("_original_name", normalized_name)

            # Skip outcome tools
            if manifest.get("_is_outcome_tool"):
                continue

            # Check if belongs to this group
            for prefix in group.tool_prefixes:
                if original_name.startswith(prefix):
                    tools_to_remove.append(normalized_name)
                    break

        for name in tools_to_remove:
            del self._state.loaded_tools[name]
            if name in self._state.tool_scopes:
                del self._state.tool_scopes[name]
            removed_count += 1

        self._state.active_groups.discard(group_id)
        self._logger.info(f"Deactivated group {group_id.value}: removed {removed_count} tools")
        return removed_count

    def activate_group(self, group_name: str) -> Tuple[bool, str, int]:
        """Public API to activate a tool group by name.

        Returns:
            (success, message, tools_loaded)
        """
        # Check current tool count
        current_count = len(self._state.loaded_tools)
        budget = get_max_tools_budget()

        # Find group by name
        group_id = None
        for gid in ToolGroupId:
            if gid.value == group_name.lower():
                group_id = gid
                break

        if not group_id:
            return False, f"Unknown tool group: {group_name}. Available: {[g.value for g in ToolGroupId]}", 0

        if group_id in self._state.active_groups:
            return True, f"Tool group '{group_name}' is already active", 0

        # Check if we need to deactivate stale groups first
        if current_count >= budget - 20:  # Leave 20 tool buffer
            stale = self._state.get_stale_groups()
            for stale_group in stale:
                self._deactivate_group(stale_group)

        # Activate
        loaded = self._activate_group(group_id)

        return True, f"Activated tool group '{group_name}' with {loaded} tools", loaded

    def deactivate_group(self, group_name: str) -> Tuple[bool, str, int]:
        """Public API to deactivate a tool group by name.

        Returns:
            (success, message, tools_removed)
        """
        group_id = None
        for gid in ToolGroupId:
            if gid.value == group_name.lower():
                group_id = gid
                break

        if not group_id:
            return False, f"Unknown tool group: {group_name}", 0

        if group_id == ToolGroupId.CORE:
            return False, "Cannot deactivate core tool group", 0

        if group_id not in self._state.active_groups:
            return True, f"Tool group '{group_name}' is not active", 0

        removed = self._deactivate_group(group_id)
        return True, f"Deactivated tool group '{group_name}', removed {removed} tools", removed

    def get_active_tools(self) -> Dict[str, Dict[str, Any]]:
        """Get all currently active tools."""
        return self._state.loaded_tools.copy()

    def get_tool_scopes(self) -> Dict[str, List[str]]:
        """Get scope requirements for discovered tools.

        Scope metadata must be available even for tools that have not yet been
        activated, so auth checks and capability inspection can work before
        lazy-loading a group.
        """
        scopes = self._state.tool_scopes.copy()
        for original_name, tool_info in self._all_tool_manifests.items():
            normalized_name = self._normalize_tool_name(original_name)
            scopes.setdefault(
                normalized_name,
                list(tool_info["manifest"].get("required_scopes", [])),
            )
        return scopes

    def get_active_groups(self) -> List[Dict[str, Any]]:
        """Get list of active tool groups with metadata."""
        result = []
        for group_id in self._state.active_groups:
            group = TOOL_GROUPS.get(group_id)
            if group:
                # Count tools in this group
                tool_count = sum(
                    1 for m in self._state.loaded_tools.values()
                    if any(m.get("_original_name", "").startswith(p) for p in group.tool_prefixes)
                )
                result.append({
                    "id": group_id.value,
                    "name": group.name,
                    "description": group.description,
                    "tool_count": tool_count,
                    "last_activation": self._state.last_activation.get(group_id, datetime.utcnow()).isoformat(),
                })
        return result

    def list_available_groups(self) -> List[Dict[str, Any]]:
        """List all available tool groups with their activation status."""
        result = []
        for group_id, group in TOOL_GROUPS.items():
            # Count available tools for this group
            available_tools = sum(
                1 for name in self._all_tool_manifests
                if any(name.startswith(p) for p in group.tool_prefixes)
            )

            result.append({
                "id": group_id.value,
                "name": group.name,
                "description": group.description,
                "is_active": group_id in self._state.active_groups,
                "available_tools": available_tools,
                "max_tools": group.max_tools,
                "keywords": group.activation_keywords,
            })
        return result

    def auto_activate_for_query(self, query: str) -> List[str]:
        """Automatically activate relevant tool groups based on a query.

        Returns:
            List of activated group names
        """
        suggestions = suggest_groups_for_query(query)
        activated = []

        for group_id in suggestions:
            if group_id not in self._state.active_groups:
                success, _, _ = self.activate_group(group_id.value)
                if success:
                    activated.append(group_id.value)

        return activated

    def get_stats(self) -> Dict[str, Any]:
        """Get loader statistics."""
        return {
            "total_available_tools": len(self._all_tool_manifests),
            "active_tools": len(self._state.loaded_tools),
            "active_groups": [g.value for g in self._state.active_groups],
            "max_tools_budget": get_max_tools_budget(),
            "headroom": get_max_tools_budget() - len(self._state.loaded_tools),
            "outcome_tools": sum(1 for m in self._state.loaded_tools.values() if m.get("_is_outcome_tool")),
            "activation_counts": {g.value: c for g, c in self._state.activation_count.items()},
        }
