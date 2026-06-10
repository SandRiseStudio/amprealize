"""Context management for Amprealize — switch between named configurations.

This module implements kubectl-style context switching for Amprealize, allowing
users to maintain multiple named configurations (local, cloud, staging, etc.)
and switch between them seamlessly.

Usage:
    amprealize context current     # Show active context
    amprealize context list        # List all contexts with details
    amprealize context use <name>  # Switch to a named context

Config Format (v2):
    version: 2
    current_context: "local"
    contexts:
      local:
        storage:
          backend: sqlite
          sqlite:
            path: ~/.amprealize/data/amprealize.db
      cloud:
        storage:
          backend: postgres
          postgres:
            dsn: postgresql://user:pass@cloud.example.com:5432/amprealize
"""

from __future__ import annotations

import os
import socket
import sys
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

from amprealize.config.schema import (
    AmprealizeConfig,
    AmprealizeConfigV2,
    ContextConfig,
    StorageConfig,
    PostgresStorageConfig,
    SqliteStorageConfig,
    ServerConfig,
    AuthConfig,
    McpConfig,
    InfraConfig,
    LoggingConfig,
    expand_env_vars,
)

# Type alias for config objects (both v1 and v2 context configs)
ConfigType = Union[AmprealizeConfig, ContextConfig]

__all__ = [
    "ContextInfo",
    "STANDARD_LOCAL_POSTGRES_MAIN_DSN",
    "STANDARD_LOCAL_POSTGRES_TELEMETRY_DSN",
    "ensure_standard_local_postgres_contexts",
    "get_current_context",
    "get_context_name",
    "list_contexts",
    "use_context",
    "get_context_indicator",
    "check_port_conflicts",
    "validate_context_connection",
    "apply_context_to_environment",
    "postgres_dsn_uses_local_host",
    "active_amprealize_context_targets_remote_postgres",
    "suggest_local_postgres_context_names",
]

# Host-forwarded DSNs for BreakerAmp ``development`` / ``test`` in ``infra/environments.yaml``.
# Both stacks publish the same localhost ports when the matching Podman machine is active.
STANDARD_LOCAL_POSTGRES_MAIN_DSN = (
    "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize"  # pragma: allowlist secret
)
STANDARD_LOCAL_POSTGRES_TELEMETRY_DSN = (
    "postgresql://telemetry:telemetry_dev@localhost:5433/telemetry"  # pragma: allowlist secret
)

# Names created by :func:`ensure_standard_local_postgres_contexts` / ``context init-standard-local``.
STANDARD_SEEDED_LOCAL_CONTEXT_NAMES: frozenset[str] = frozenset(
    ("local-postgres-dev", "local-postgres-test")
)

# Path to user config file
AMPREALIZE_HOME = Path(os.environ.get("AMPREALIZE_HOME", "~/.amprealize")).expanduser()
USER_CONFIG_PATH = AMPREALIZE_HOME / "config.yaml"


@dataclass
class ContextInfo:
    """Information about a named context."""

    name: str
    is_current: bool
    storage_backend: str
    storage_location: str  # DSN or path
    port: Optional[int]
    is_valid: bool
    validation_error: Optional[str]
    has_port_conflict: bool
    conflict_with: Optional[str]


def _load_raw_config() -> Dict[str, Any]:
    """Load raw YAML config without validation."""
    if not USER_CONFIG_PATH.exists():
        return {"version": 1}

    try:
        with open(USER_CONFIG_PATH) as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {"version": 1}
    except (OSError, yaml.YAMLError):
        return {"version": 1}


def _save_raw_config(data: Dict[str, Any]) -> None:
    """Save raw dict to config file."""
    USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(USER_CONFIG_PATH, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _extract_port_from_dsn(dsn: str) -> Optional[int]:
    """Extract port number from a PostgreSQL DSN."""
    # postgresql://user:pass@host:5432/dbname
    if "@" not in dsn:
        return None

    # Get the host:port/db part after @
    after_at = dsn.split("@", 1)[1]

    # Handle IPv6 addresses in brackets [::1]
    if after_at.startswith("["):
        bracket_end = after_at.find("]")
        if bracket_end > 0:
            after_bracket = after_at[bracket_end + 1:]
            if after_bracket.startswith(":"):
                port_part = after_bracket[1:].split("/")[0]
                try:
                    return int(port_part)
                except ValueError:
                    return None
        return None

    # Standard host:port/db
    host_port = after_at.split("/")[0]
    if ":" in host_port:
        port_str = host_port.rsplit(":", 1)[1]
        try:
            return int(port_str)
        except ValueError:
            return None

    return 5432  # PostgreSQL default


def _postgres_host_port_from_dsn(dsn: str) -> Optional[Tuple[str, int]]:
    """Parse Postgres DSN into ``(host, port)`` for conflict grouping and probes.

    Remote Neon ``host:5432`` and local ``localhost:5432`` are distinct keys.
    """
    if not dsn or "@" not in dsn:
        return None
    port = _extract_port_from_dsn(dsn)
    if port is None:
        port = 5432
    after_at = dsn.split("@", 1)[1]
    host_port = after_at.split("/")[0]
    if host_port.startswith("["):
        bracket_end = host_port.find("]")
        host = host_port[1:bracket_end] if bracket_end > 0 else "localhost"
    else:
        host = host_port.rsplit(":", 1)[0] if ":" in host_port else host_port
    return (host.lower(), port)


def _loopback_normalize_for_port_conflicts(host: str) -> str:
    """Treat common loopback spellings as one host for port-overlap display."""
    h = host.lower()
    if h in ("localhost", "127.0.0.1", "::1"):
        return "loopback"
    return h


def _is_v2_config(data: Dict[str, Any]) -> bool:
    """Check if config is v2 format with contexts."""
    return data.get("version") == 2 and "contexts" in data


def _migrate_v1_to_v2(data: Dict[str, Any]) -> Dict[str, Any]:
    """Migrate v1 config format to v2 with contexts.

    Creates a 'default' context from existing v1 settings.
    """
    # Extract v1 settings (everything except version)
    v1_settings = {k: v for k, v in data.items() if k != "version"}

    return {
        "version": 2,
        "current_context": "default",
        "contexts": {
            "default": v1_settings or {
                "storage": {"backend": "sqlite"}
            }
        }
    }


def _context_to_config(context_data: Dict[str, Any]) -> ContextConfig:
    """Convert context dict to a ContextConfig instance.

    Uses the new ContextConfig model which supports env var expansion.
    """
    return ContextConfig(**context_data)


def get_context_name() -> str:
    """Get the name of the current active context.

    Returns 'default' for v1 configs or the current_context for v2.
    """
    data = _load_raw_config()

    if _is_v2_config(data):
        return data.get("current_context", "default")

    return "default"


def get_current_context() -> Tuple[str, ConfigType]:
    """Get the current context name and its configuration.

    If ``AMPREALIZE_CONTEXT`` is set to a name that exists in ``contexts``,
    that context wins over ``current_context`` in ``config.yaml``. Use this
    so MCP / IDE launch configs can pin a context without mutating the global
    active context on disk.

    Returns:
        Tuple of (context_name, config)
    """
    data = _load_raw_config()
    env_override = os.environ.get("AMPREALIZE_CONTEXT", "").strip()

    if _is_v2_config(data):
        contexts = data.get("contexts", {})
        if env_override and env_override in contexts:
            return env_override, _context_to_config(contexts[env_override])

        current = data.get("current_context", "default")

        if current in contexts:
            return current, _context_to_config(contexts[current])

        # Fallback: use first available context
        if contexts:
            first_name = next(iter(contexts))
            return first_name, _context_to_config(contexts[first_name])

        # No contexts defined - return defaults
        return "default", AmprealizeConfig()

    # v1 config - treat entire config as "default" context
    v1_settings = {k: v for k, v in data.items() if k != "version"}
    if v1_settings:
        return "default", _context_to_config(v1_settings)

    return "default", AmprealizeConfig()


def _get_storage_location(cfg: ConfigType) -> str:
    """Get human-readable storage location from config."""
    if cfg.storage.backend == "postgres":
        dsn = cfg.storage.postgres.dsn
        # Mask password in DSN for display
        if "@" in dsn:
            prefix, rest = dsn.split("@", 1)
            if ":" in prefix:
                proto_user = prefix.rsplit(":", 1)[0]
                return f"{proto_user}:****@{rest}"
        return dsn
    elif cfg.storage.backend == "sqlite":
        return cfg.storage.sqlite.path
    else:
        return "memory"


def _get_port(cfg: ConfigType) -> Optional[int]:
    """Extract port from config (PostgreSQL or server port)."""
    if cfg.storage.backend == "postgres":
        dsn = cfg.storage.postgres.dsn or ""
        hp = _postgres_host_port_from_dsn(dsn)
        return hp[1] if hp else _extract_port_from_dsn(dsn)
    return cfg.server.port if hasattr(cfg, "server") else None


def check_port_conflicts(contexts: Dict[str, Dict[str, Any]]) -> Dict[str, Tuple[str, str]]:
    """Check for port conflicts between contexts.

    Postgres contexts only conflict when **host and port** match (e.g. two
    ``localhost:5432`` URLs). A Neon ``*.neon.tech:5432`` context does not
    conflict with ``localhost:5432``.

    Two contexts that share the **same primary Postgres DSN** (e.g.
    ``local-postgres-dev`` and ``local-postgres-test`` seeded with identical
    URLs) are treated as aliases and do **not** surface a port conflict.

    Non-Postgres backends still key conflicts by numeric port only (legacy).

    Returns dict mapping context names to (conflict_context, conflicting_port) tuples.
    """
    conflicts: Dict[str, Tuple[str, str]] = {}
    key_to_context: Dict[str, str] = {}

    for name, ctx_data in contexts.items():
        try:
            cfg = _context_to_config(ctx_data)
            if cfg.storage.backend == "postgres":
                dsn = cfg.storage.postgres.dsn or ""
                hp = _postgres_host_port_from_dsn(dsn)
                if hp is None:
                    continue
                host, port = hp
                key = f"pg:{_loopback_normalize_for_port_conflicts(host)}:{port}"
            else:
                port = _get_port(cfg)
                if port is None:
                    continue
                key = f"np:{port}"

            if key in key_to_context:
                other = key_to_context[key]
                if cfg.storage.backend == "postgres":
                    dsn_self = (cfg.storage.postgres.dsn or "").strip()
                    try:
                        other_cfg = _context_to_config(contexts[other])
                        if other_cfg.storage.backend == "postgres":
                            dsn_other = (other_cfg.storage.postgres.dsn or "").strip()
                            if dsn_self and dsn_self == dsn_other:
                                continue
                    except Exception:
                        pass
                conflicts[name] = (other, str(port))
                if other not in conflicts:
                    conflicts[other] = (name, str(port))
            else:
                key_to_context[key] = name
        except Exception:
            continue

    return conflicts


def validate_context_connection(cfg: ConfigType) -> Tuple[bool, Optional[str]]:
    """Validate that a context's storage connection is reachable.

    For PostgreSQL, attempts a socket connection to the host:port.
    For SQLite, checks if the directory exists.

    Returns:
        (is_valid, error_message)
    """
    if cfg.storage.backend == "postgres":
        dsn = cfg.storage.postgres.dsn
        hp = _postgres_host_port_from_dsn(dsn or "")
        if hp is None:
            return False, "Invalid DSN format"

        host, port = hp

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            result = sock.connect_ex((host, port))
            sock.close()

            if result == 0:
                return True, None
            else:
                return False, f"Cannot connect to {host}:{port}"
        except socket.error as e:
            return False, f"Connection error: {e}"

    elif cfg.storage.backend == "sqlite":
        path = Path(cfg.storage.sqlite.path).expanduser()
        parent = path.parent

        if not parent.exists():
            # Parent doesn't exist - but we can create it
            return True, None

        if path.exists() and not path.is_file():
            return False, f"Path exists but is not a file: {path}"

        return True, None

    # Memory backend is always valid
    return True, None


def list_contexts() -> List[ContextInfo]:
    """List all available contexts with their details.

    Returns list of ContextInfo objects with validation status.
    """
    data = _load_raw_config()
    contexts: List[ContextInfo] = []

    if not _is_v2_config(data):
        # v1 config - show single "default" context
        v1_settings = {k: v for k, v in data.items() if k != "version"}
        try:
            cfg = _context_to_config(v1_settings) if v1_settings else AmprealizeConfig()
            is_valid, error = validate_context_connection(cfg)

            contexts.append(ContextInfo(
                name="default",
                is_current=True,
                storage_backend=cfg.storage.backend,
                storage_location=_get_storage_location(cfg),
                port=_get_port(cfg),
                is_valid=is_valid,
                validation_error=error,
                has_port_conflict=False,
                conflict_with=None,
            ))
        except Exception as e:
            contexts.append(ContextInfo(
                name="default",
                is_current=True,
                storage_backend="unknown",
                storage_location="error",
                port=None,
                is_valid=False,
                validation_error=str(e),
                has_port_conflict=False,
                conflict_with=None,
            ))
        return contexts

    # v2 config with contexts
    current_name = data.get("current_context", "default")
    ctx_dict = data.get("contexts", {})

    # Check for port conflicts
    conflicts = check_port_conflicts(ctx_dict)

    for name, ctx_data in ctx_dict.items():
        try:
            cfg = _context_to_config(ctx_data)
            is_valid, error = validate_context_connection(cfg)
            conflict_info = conflicts.get(name)

            contexts.append(ContextInfo(
                name=name,
                is_current=(name == current_name),
                storage_backend=cfg.storage.backend,
                storage_location=_get_storage_location(cfg),
                port=_get_port(cfg),
                is_valid=is_valid,
                validation_error=error,
                has_port_conflict=conflict_info is not None,
                conflict_with=conflict_info[0] if conflict_info else None,
            ))
        except Exception as e:
            contexts.append(ContextInfo(
                name=name,
                is_current=(name == current_name),
                storage_backend="unknown",
                storage_location="error",
                port=None,
                is_valid=False,
                validation_error=str(e),
                has_port_conflict=False,
                conflict_with=None,
            ))

    # Sort: current first, then alphabetically
    contexts.sort(key=lambda c: (not c.is_current, c.name))
    return contexts


def use_context(name: str) -> Tuple[bool, str]:
    """Switch to a named context.

    Args:
        name: Name of the context to switch to.

    Returns:
        (success, message)
    """
    data = _load_raw_config()

    # Ensure v2 format
    if not _is_v2_config(data):
        data = _migrate_v1_to_v2(data)

    contexts = data.get("contexts", {})

    if name not in contexts:
        available = ", ".join(sorted(contexts.keys())) if contexts else "(none)"
        msg = f"Context '{name}' not found. Available contexts: {available}"
        if name in STANDARD_SEEDED_LOCAL_CONTEXT_NAMES:
            msg += (
                "\n  Create BreakerAmp localhost contexts: amprealize context init-standard-local"
            )
        return False, msg

    # Validate the context before switching
    try:
        cfg = _context_to_config(contexts[name])
        is_valid, error = validate_context_connection(cfg)

        if not is_valid:
            # Still switch but warn
            data["current_context"] = name
            _save_raw_config(data)
            return True, f"Switched to context '{name}' (warning: {error})"
    except Exception as e:
        return False, f"Invalid context configuration: {e}"

    # Update current context
    data["current_context"] = name
    _save_raw_config(data)

    return True, f"Switched to context '{name}'"


def get_context_indicator() -> str:
    """Get a short context indicator for CLI output.

    Returns something like '[local]' or '[cloud:pg]' to show in CLI prompts.
    """
    name, cfg = get_current_context()

    # Short backend indicator
    backend_short = {
        "postgres": "pg",
        "sqlite": "sql",
        "memory": "mem",
    }.get(cfg.storage.backend, cfg.storage.backend[:3])

    if name == "default":
        return f"[{backend_short}]"

    return f"[{name}:{backend_short}]"


# Hosts treated as "local" for BreakerAmp / pytest safety (main app Postgres).
_LOCAL_POSTGRES_HOSTS_FOR_TESTS = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "::1",
        "host.containers.internal",
        "host.docker.internal",
    }
)


def postgres_dsn_uses_local_host(dsn: str) -> bool:
    """Return True if the DSN's hostname is a loopback / container-bridge host."""
    parsed = urllib.parse.urlparse(dsn)
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    return host in _LOCAL_POSTGRES_HOSTS_FOR_TESTS


def active_amprealize_context_targets_remote_postgres() -> Tuple[bool, str, str]:
    """Detect whether the active context's primary Postgres DSN is non-local.

    Used before BreakerAmp ``--env test`` runs so the shell can warn when the
    user still has e.g. a Neon-backed ``neon`` context selected after using
    ``cloud-dev``.

    Returns:
        (is_remote, context_name, reason). When ``is_remote`` is False,
        ``reason`` is empty.
    """
    name, cfg = get_current_context()
    if cfg.storage.backend != "postgres":
        return False, name, ""
    dsn = (cfg.storage.postgres.dsn or "").strip()
    if not dsn:
        return False, name, ""
    if postgres_dsn_uses_local_host(dsn):
        return False, name, ""
    masked = _get_storage_location(cfg)
    return (
        True,
        name,
        f"active context '{name}' uses non-local Postgres ({masked})",
    )


def suggest_local_postgres_context_names() -> List[str]:
    """Context names whose primary Postgres DSN uses a local host, ordered for UX.

    Prefers ``local-postgres-test``, ``local-test``, ``local-postgres-dev``,
    ``local-postgres``, ``local``, ``default``, then remaining matching contexts
    alphabetically.
    """
    data = _load_raw_config()
    priority = (
        "local-postgres-test",
        "local-test",
        "local-postgres-dev",
        "local-postgres",
        "local",
        "default",
    )
    local_names: List[str] = []

    if not _is_v2_config(data):
        return list(priority)

    for nm, ctx_data in (data.get("contexts") or {}).items():
        try:
            cfg = _context_to_config(ctx_data)
            if cfg.storage.backend != "postgres":
                continue
            dsn = (cfg.storage.postgres.dsn or "").strip()
            if dsn and postgres_dsn_uses_local_host(dsn):
                local_names.append(nm)
        except Exception:
            continue

    ordered = [n for n in priority if n in local_names]
    rest = sorted(n for n in local_names if n not in ordered)
    return ordered + rest


def add_context(
    name: str,
    storage_backend: str = "sqlite",
    dsn: Optional[str] = None,
    sqlite_path: Optional[str] = None,
    telemetry_dsn: Optional[str] = None,
    description: Optional[str] = None,
) -> Tuple[bool, str]:
    """Add a new named context.

    Args:
        name: Unique name for the context.
        storage_backend: 'postgres', 'sqlite', or 'memory'.
        dsn: PostgreSQL DSN (required if backend is postgres).
        sqlite_path: SQLite file path (optional, has default).
        telemetry_dsn: Telemetry database DSN (optional).
        description: Human-readable description for this context.

    Returns:
        (success, message)
    """
    data = _load_raw_config()

    # Ensure v2 format
    if not _is_v2_config(data):
        data = _migrate_v1_to_v2(data)

    contexts = data.setdefault("contexts", {})

    if name in contexts:
        return False, f"Context '{name}' already exists"

    # Build context configuration
    ctx_config: Dict[str, Any] = {
        "storage": {
            "backend": storage_backend,
        }
    }

    if storage_backend == "postgres":
        if not dsn:
            return False, "PostgreSQL backend requires --dsn"
        pg_config: Dict[str, Any] = {"dsn": dsn}
        if telemetry_dsn:
            pg_config["telemetry_dsn"] = telemetry_dsn
        ctx_config["storage"]["postgres"] = pg_config
    elif storage_backend == "sqlite":
        path = sqlite_path or f"~/.amprealize/data/{name}.db"
        ctx_config["storage"]["sqlite"] = {"path": path}

    if description:
        ctx_config["description"] = description

    # Validate before saving
    try:
        cfg = _context_to_config(ctx_config)
    except Exception as e:
        return False, f"Invalid configuration: {e}"

    contexts[name] = ctx_config
    _save_raw_config(data)

    return True, f"Created context '{name}'"


def ensure_standard_local_postgres_contexts() -> Tuple[int, List[str]]:
    """Create ``local-postgres-dev`` and ``local-postgres-test`` if they do not exist.

    Uses :data:`STANDARD_LOCAL_POSTGRES_MAIN_DSN` and
    :data:`STANDARD_LOCAL_POSTGRES_TELEMETRY_DSN` (aligned with
    ``infra/environments.yaml`` host port forwards). Idempotent.

    Returns:
        ``(created_count, human-readable status lines)``
    """
    specs: Tuple[Tuple[str, str, str, str], ...] = (
        (
            "local-postgres-dev",
            STANDARD_LOCAL_POSTGRES_MAIN_DSN,
            STANDARD_LOCAL_POSTGRES_TELEMETRY_DSN,
            "BreakerAmp development (infra environments `development` / blueprint `local-dev`)",
        ),
        (
            "local-postgres-test",
            STANDARD_LOCAL_POSTGRES_MAIN_DSN,
            STANDARD_LOCAL_POSTGRES_TELEMETRY_DSN,
            "BreakerAmp pytest stack (infra environments `test` / blueprint `local-test-env`)",
        ),
    )
    created = 0
    lines: List[str] = []
    for name, dsn, telemetry_dsn, description in specs:
        ok, msg = add_context(
            name=name,
            storage_backend="postgres",
            dsn=dsn,
            telemetry_dsn=telemetry_dsn,
            description=description,
        )
        lines.append(msg)
        if ok:
            created += 1
    return created, lines


def remove_context(name: str) -> Tuple[bool, str]:
    """Remove a named context.

    Cannot remove the current context or the last remaining context.

    Returns:
        (success, message)
    """
    data = _load_raw_config()

    if not _is_v2_config(data):
        return False, "Cannot remove context from v1 config. Use 'amprealize context use' first."

    contexts = data.get("contexts", {})
    current = data.get("current_context")

    if name not in contexts:
        return False, f"Context '{name}' not found"

    if name == current:
        return False, f"Cannot remove current context. Switch to another context first."

    if len(contexts) <= 1:
        return False, "Cannot remove the last context"

    del contexts[name]
    _save_raw_config(data)

    return True, f"Removed context '{name}'"


def _build_service_dsn(base_dsn: str, search_path: Optional[str]) -> str:
    """Build a per-service DSN from a base DSN by appending search_path options.

    If ``search_path`` is None the base DSN is returned unchanged.
    If the base DSN already contains an ``options=`` query parameter it is
    replaced with the correct ``search_path`` value.
    """
    if not search_path:
        return base_dsn

    from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

    parsed = urlparse(base_dsn)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    qs["options"] = [f"-csearch_path={search_path}"]
    new_query = urlencode(qs, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


# Map of per-service env vars → search_path schema (None = no search_path).
# This is the single source of truth for how the context system derives
# per-service DSNs from the base context DSN.
_SERVICE_DSN_MAP: Dict[str, Optional[str]] = {
    # Core services with schema isolation
    "AMPREALIZE_AUTH_PG_DSN": "auth",
    "AMPREALIZE_ORG_PG_DSN": "auth",
    "AMPREALIZE_MULTI_TENANT_PG_DSN": "auth",
    "AMPREALIZE_AGENTAUTH_PG_DSN": "auth",
    "AMPREALIZE_BOARD_PG_DSN": "board",
    "AMPREALIZE_BEHAVIOR_PG_DSN": "behavior",
    "AMPREALIZE_ACTION_PG_DSN": "execution",
    "AMPREALIZE_RUN_PG_DSN": "execution",
    "AMPREALIZE_EXECUTION_PG_DSN": "execution",
    "AMPREALIZE_WORKFLOW_PG_DSN": "workflow",
    "AMPREALIZE_COMPLIANCE_PG_DSN": "compliance",
    "AMPREALIZE_CONSENT_PG_DSN": "consent",
    "AMPREALIZE_AUDIT_PG_DSN": "audit",
    "AMPREALIZE_MESSAGING_PG_DSN": "messaging",
    "AMPREALIZE_RESEARCH_PG_DSN": "research",
    "AMPREALIZE_COLLABORATION_PG_DSN": None,
    "AMPREALIZE_REFLECTION_PG_DSN": None,
    "AMPREALIZE_TRACE_ANALYSIS_PG_DSN": None,
    # Services that use public schema / no search_path
    "AMPREALIZE_PG_DSN": None,
    "AMPREALIZE_TASK_PG_DSN": None,
    "AMPREALIZE_METRICS_PG_DSN": None,
    "AMPREALIZE_AGENT_REGISTRY_PG_DSN": None,
    "AMPREALIZE_AGENT_ORCHESTRATOR_PG_DSN": None,
    "AMPREALIZE_WHITEBOARD_PG_DSN": None,
    # Platform feature-flag admin UI / runtime overrides (public.feature_flags)
    "AMPREALIZE_FEATURE_FLAGS_PG_DSN": None,
}


def apply_context_to_environment(force: bool = False) -> Optional[str]:
    """Apply the active context's DSN(s) to environment variables.

    This bridges the gap between the context system (config.yaml) and the
    service layer (which reads DATABASE_URL / AMPREALIZE_*_PG_DSN env vars).

    The active context is ``get_current_context()`` — including an optional
    ``AMPREALIZE_CONTEXT`` env override when it names a valid entry under
    ``contexts`` in config.

    Sets:
        DATABASE_URL              — main DB DSN (universal fallback)
        TELEMETRY_DATABASE_URL    — telemetry DB DSN
        AMPREALIZE_*_PG_DSN       — every per-service DSN (with correct search_path)

    When force=False (default), only sets env vars that are NOT already
    explicitly set, so .env / CLI flags still take precedence.

    When force=True, always overwrites — used by explicit context commands
    like ``context migrate`` where the user intends to target the active context.

    Returns:
        Name of the applied context, or None if no postgres context is active.
    """
    name, cfg = get_current_context()

    if cfg.storage.backend != "postgres":
        return None

    dsn = cfg.storage.postgres.dsn
    telemetry_dsn = cfg.storage.postgres.get_explicit_telemetry_dsn()

    # Set DATABASE_URL as universal fallback (dsn.py checks this)
    if force or not os.environ.get("DATABASE_URL"):
        os.environ["DATABASE_URL"] = dsn

    # Set telemetry DSN only when explicitly configured by the context.
    if telemetry_dsn:
        if force or not os.environ.get("TELEMETRY_DATABASE_URL"):
            os.environ["TELEMETRY_DATABASE_URL"] = telemetry_dsn
    elif force:
        os.environ.pop("TELEMETRY_DATABASE_URL", None)

    # Set ALL per-service DSNs so that services which read their own
    # AMPREALIZE_*_PG_DSN env var (before DATABASE_URL fallback) also pick up
    # the context DSN.  Each service gets its appropriate search_path suffix.
    for env_var, search_path in _SERVICE_DSN_MAP.items():
        if force or not os.environ.get(env_var):
            os.environ[env_var] = _build_service_dsn(dsn, search_path)

    # Telemetry-specific services only get a DSN when telemetry is explicit.
    if telemetry_dsn:
        if force or not os.environ.get("AMPREALIZE_TELEMETRY_PG_DSN"):
            os.environ["AMPREALIZE_TELEMETRY_PG_DSN"] = telemetry_dsn
    elif force:
        os.environ.pop("AMPREALIZE_TELEMETRY_PG_DSN", None)

    return name
