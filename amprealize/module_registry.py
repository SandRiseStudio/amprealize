"""Module registry — definitions, presets, and helpers for the modular install system.

Each module is an independently toggleable feature set. Goals is always enabled
as the base module. Agents and behaviors can be enabled/disabled at any time
without data loss.

Part of Phase 1 of GUIDEAI-619 (Modular Installation System v3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from amprealize.config.schema import ModulesConfig


# ---------------------------------------------------------------------------
# Module definition
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModuleDefinition:
    """Describes a single toggleable feature module."""

    name: str
    display_name: str
    description: str
    always_enabled: bool = False
    depends_on: tuple[str, ...] = ()
    enterprise_only: bool = False
    # Minimum edition required (None = any edition, string matches Edition.value)
    min_edition: str | None = None  # "enterprise_starter" or "enterprise_premium"

    # Gating metadata — what this module "owns"
    db_schemas: tuple[str, ...] = ()
    mcp_tool_prefixes: tuple[str, ...] = ()
    cli_groups: tuple[str, ...] = ()
    api_routers: tuple[str, ...] = ()
    capability_flags: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

MODULE_REGISTRY: dict[str, ModuleDefinition] = {
    "goals": ModuleDefinition(
        name="goals",
        display_name="Goals",
        description="Projects, boards, work items, sprints, labels, comments",
        always_enabled=True,
        db_schemas=(
            "projects",
            "boards",
            "work_items",
            "sprints",
            "labels",
            "comments",
        ),
        mcp_tool_prefixes=(
            "projects",
            "boards",
            "workitems",
            "sprints",
            "labels",
        ),
        cli_groups=("project", "board", "item", "sprint", "label"),
        api_routers=("projects", "boards", "work_items", "sprints"),
        capability_flags=("projects", "boards", "work_items"),
    ),
    "agents": ModuleDefinition(
        name="agents",
        display_name="Agents",
        description="Agent execution, task runners, agent registry",
        depends_on=("goals",),
        db_schemas=("agents", "runs", "execution"),
        mcp_tool_prefixes=("agents", "runs", "execution"),
        cli_groups=("agent", "run"),
        api_routers=("agents", "runs"),
        capability_flags=("agents", "runs"),
    ),
    "behaviors": ModuleDefinition(
        name="behaviors",
        display_name="Behaviors",
        description="Behavior engine, BCI, retrieval, handbook",
        depends_on=("goals",),
        db_schemas=("behaviors", "bci", "reflection"),
        mcp_tool_prefixes=("behaviors", "bci", "reflection"),
        cli_groups=("behavior", "bci", "reflection"),
        api_routers=("behaviors", "bci", "reflection"),
        capability_flags=("behaviors", "bci", "reflection"),
    ),
    "self_improving": ModuleDefinition(
        name="self_improving",
        display_name="Self-Improving Behaviors",
        description="Auto-reflection, auto-propose, auto-approve behaviors",
        depends_on=("behaviors",),
        enterprise_only=True,
        min_edition="enterprise_premium",
        db_schemas=("auto_reflection",),
        capability_flags=("auto_reflection",),
    ),
    "collaboration": ModuleDefinition(
        name="collaboration",
        display_name="Collaboration",
        description="Team workspaces, real-time editing, conversations",
        depends_on=("goals",),
        enterprise_only=True,
        min_edition="enterprise_starter",
        db_schemas=("workspaces", "conversations", "documents"),
        mcp_tool_prefixes=("collaboration", "conversations"),
        cli_groups=("workspace", "conversation"),
        api_routers=("collaboration", "conversations"),
        capability_flags=("collaboration", "conversations"),
    ),
    "whiteboard": ModuleDefinition(
        name="whiteboard",
        display_name="Whiteboard",
        description="Real-time collaborative brainstorm canvas with tldraw",
        depends_on=("goals",),
        db_schemas=("whiteboard_rooms",),
        mcp_tool_prefixes=("whiteboard",),
        cli_groups=("whiteboard",),
        api_routers=("whiteboard",),
        capability_flags=("whiteboard",),
    ),
}

# ---------------------------------------------------------------------------
# Presets — named module combos
# ---------------------------------------------------------------------------

PRESETS: dict[str, tuple[str, ...]] = {
    "goals": ("goals",),
    "goals-agents": ("goals", "agents"),
    "goals-behaviors": ("goals", "behaviors"),
    "full": ("goals", "agents", "behaviors"),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def resolve_preset(name: str) -> tuple[str, ...]:
    """Return module names for a preset, or raise ``KeyError``."""
    return PRESETS[name]


def get_enabled_modules(modules_config: ModulesConfig) -> list[ModuleDefinition]:
    """Return ``ModuleDefinition`` objects for every enabled module."""
    enabled: list[ModuleDefinition] = []
    for mod_name, mod_def in MODULE_REGISTRY.items():
        if mod_def.always_enabled:
            enabled.append(mod_def)
            continue
        if mod_def.enterprise_only:
            # Enterprise-only modules are handled separately
            continue
        if getattr(modules_config, mod_name, False):
            enabled.append(mod_def)
    return enabled


def get_enabled_mcp_tool_prefixes(modules_config: ModulesConfig) -> set[str]:
    """Collect all MCP tool prefixes from enabled modules."""
    prefixes: set[str] = set()
    for mod in get_enabled_modules(modules_config):
        prefixes.update(mod.mcp_tool_prefixes)
    return prefixes


def get_enabled_cli_groups(modules_config: ModulesConfig) -> set[str]:
    """Collect all CLI groups from enabled modules."""
    groups: set[str] = set()
    for mod in get_enabled_modules(modules_config):
        groups.update(mod.cli_groups)
    return groups


def get_enabled_capability_flags(modules_config: ModulesConfig) -> set[str]:
    """Collect all capability flags from enabled modules."""
    flags: set[str] = set()
    for mod in get_enabled_modules(modules_config):
        flags.update(mod.capability_flags)
    return flags


def get_enabled_api_routers(modules_config: ModulesConfig) -> set[str]:
    """Collect all API router tags from enabled modules."""
    routers: set[str] = set()
    for mod in get_enabled_modules(modules_config):
        routers.update(mod.api_routers)
    return routers


def get_enabled_db_schemas(modules_config: ModulesConfig) -> set[str]:
    """Collect all DB schema tags from enabled modules."""
    schemas: set[str] = set()
    for mod in get_enabled_modules(modules_config):
        schemas.update(mod.db_schemas)
    return schemas


def get_all_module_mcp_prefixes() -> set[str]:
    """Return ALL MCP tool prefixes across all modules (including disabled)."""
    prefixes: set[str] = set()
    for mod in MODULE_REGISTRY.values():
        prefixes.update(mod.mcp_tool_prefixes)
    return prefixes


def get_edition_gated_api_routers() -> dict[str, str]:
    """Return API router tags that require a specific edition.

    Maps *router_tag* → *min_edition* for enterprise-only modules.
    Used by the API middleware to return 403 with upgrade guidance
    instead of a generic 404 for module-disabled routes.
    """
    gated: dict[str, str] = {}
    for mod in MODULE_REGISTRY.values():
        if mod.enterprise_only and mod.min_edition:
            for router in mod.api_routers:
                gated[router] = mod.min_edition
    return gated


def get_edition_gated_cli_groups() -> dict[str, str]:
    """Return CLI groups that require a specific edition.

    Maps *cli_group* → *min_edition* for enterprise-only modules.
    Used by CLI gating to show an upgrade message instead of a
    generic module-disabled error.
    """
    gated: dict[str, str] = {}
    for mod in MODULE_REGISTRY.values():
        if mod.enterprise_only and mod.min_edition:
            for group in mod.cli_groups:
                gated[group] = mod.min_edition
    return gated


def get_all_module_api_routers() -> set[str]:
    """Return ALL API router tags across all modules (including disabled)."""
    routers: set[str] = set()
    for mod in MODULE_REGISTRY.values():
        routers.update(mod.api_routers)
    return routers


def validate_module_dependencies(module_names: tuple[str, ...]) -> list[str]:
    """Return list of error messages if dependencies are unmet, else empty."""
    errors: list[str] = []
    name_set = set(module_names)
    for name in module_names:
        mod = MODULE_REGISTRY.get(name)
        if mod is None:
            errors.append(f"Unknown module: {name!r}")
            continue
        for dep in mod.depends_on:
            if dep not in name_set:
                errors.append(
                    f"Module {name!r} depends on {dep!r}, "
                    f"which is not in the enabled set"
                )
    return errors


def is_module_edition_allowed(module_name: str) -> bool:
    """Check if *module_name* is allowed by the current edition.

    Returns ``True`` for modules with no edition requirement.
    Returns ``True`` when edition detection fails (safe default).
    """
    mod_def = MODULE_REGISTRY.get(module_name)
    if mod_def is None:
        return True
    if mod_def.min_edition is None and not mod_def.enterprise_only:
        return True

    try:
        from amprealize.edition import Edition, edition_at_least

        if mod_def.min_edition is not None:
            required = Edition(mod_def.min_edition)
        else:
            # enterprise_only=True without min_edition → Starter minimum
            required = Edition.ENTERPRISE_STARTER
        return edition_at_least(required)
    except Exception:
        return True  # safe default on failure


def is_module_enabled_for_migration(module_name: str) -> bool:
    """Check if *module_name* is enabled — safe to call from Alembic migrations.

    Returns ``True`` when config is unavailable (first run / test) so that
    migrations default to running.
    """
    import os

    if os.environ.get("AMPREALIZE_MIGRATE_ALL", ""):
        return True

    try:
        from amprealize.config.loader import get_config

        cfg = get_config()
        enabled_names = {m.name for m in get_enabled_modules(cfg.modules)}
        return module_name in enabled_names
    except Exception:
        return True
