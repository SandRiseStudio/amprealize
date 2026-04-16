"""Shared helpers for Postgres DSN resolution and overrides.

Applies behavior_externalize_configuration by ensuring all services honor
AMPREALIZE_PG_HOST_* and AMPREALIZE_PG_PORT_* overrides even when full DSNs are
predefined via environment variables. This allows Podman/Docker containers to
connect to host databases without mutating every DSN string manually.
"""

from __future__ import annotations

import os
from typing import Optional
from urllib.parse import urlparse, urlunparse, quote


def _component_env(service: str, suffix: str) -> Optional[str]:
    """Fetch a AMPREALIZE_PG_{suffix}_{service} environment variable."""

    key = f"AMPREALIZE_PG_{suffix}_{service.upper()}"
    return os.getenv(key)


def apply_host_overrides(dsn: Optional[str], service: str) -> Optional[str]:
    """Rewrite DSN host/port when AMPREALIZE_PG_HOST/PORT overrides are present.

    Args:
        dsn: Original DSN string or None.
        service: Service identifier suffix (e.g., "BEHAVIOR").

    Returns:
        DSN string with host/port overrides applied if configured.
    """

    if not dsn:
        return dsn

    override_host = _component_env(service, "HOST")
    override_port = _component_env(service, "PORT")
    if not override_host and not override_port:
        return dsn

    parsed = urlparse(dsn)
    hostname = override_host or (parsed.hostname or "")
    port = override_port or (str(parsed.port) if parsed.port else "")

    # Reconstruct credentials with proper encoding.
    auth = ""
    if parsed.username:
        auth = quote(parsed.username, safe="")
        if parsed.password is not None:
            auth += f":{quote(parsed.password, safe='')}"
        auth += "@"

    host_display = hostname
    if ":" in hostname and not hostname.startswith("["):
        host_display = f"[{hostname}]"

    netloc = auth + host_display
    if port:
        netloc += f":{port}"

    rebuilt = parsed._replace(netloc=netloc)
    return urlunparse(rebuilt)


def build_dsn_from_components(service: str) -> Optional[str]:
    """Construct a DSN purely from AMPREALIZE_PG_* components if available."""

    host = _component_env(service, "HOST")
    port = _component_env(service, "PORT")
    user = _component_env(service, "USER")
    password = _component_env(service, "PASS")
    dbname = _component_env(service, "DB") or f"amprealize_{service.lower()}"

    if not all([host, port, user, password]):
        return None

    auth = quote(user, safe="")
    auth += f":{quote(password, safe='')}" if password else ""
    netloc = f"{auth}@{host}:{port}"

    params = _component_env(service, "PARAMS")
    query = params if params and params.startswith("?") else (f"?{params}" if params else "")
    return f"postgresql://{netloc}/{dbname}{query}"


def resolve_postgres_dsn(
    *,
    service: str,
    explicit_dsn: Optional[str],
    env_var: str,
    default_dsn: str,
) -> str:
    """Resolve and normalize DSNs for services with layered fallbacks.

    Resolution order:
    1. explicit_dsn (passed directly to constructor)
    2. Service-specific env var (e.g., AMPREALIZE_TASK_CYCLE_PG_DSN)
    3. Build from AMPREALIZE_PG_* components
    4. DATABASE_URL (universal fallback for containerized environments)
    5. default_dsn (localhost fallback for local development)
    """

    candidate = (
        explicit_dsn
        or os.getenv(env_var)
        or build_dsn_from_components(service)
        or os.getenv("DATABASE_URL")  # Universal fallback for containers
        or default_dsn
    )
    return apply_host_overrides(candidate, service)


def resolve_optional_postgres_dsn(
    *,
    service: str,
    explicit_dsn: Optional[str],
    env_var: str,
) -> Optional[str]:
    """Resolve DSN but return None if no configuration found.

    Unlike resolve_postgres_dsn, this does not provide a default and can return None,
    allowing callers to handle the absence of database configuration gracefully.
    """
    candidate = (
        explicit_dsn
        or os.getenv(env_var)
        or build_dsn_from_components(service)
        or os.getenv("DATABASE_URL")  # Fallback: active context or container default
    )
    if not candidate:
        return None
    return apply_host_overrides(candidate, service)
