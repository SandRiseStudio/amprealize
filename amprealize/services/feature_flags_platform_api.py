"""HTTP API for viewing and toggling global boolean feature flags (admin UI).

Persists to the ``feature_flags`` Postgres table (global scope) and updates
:mod:`amprealize.feature_flag_runtime` so changes apply in-process immediately.

Access control (any one is sufficient):

- JWT / device token with ``role`` claim equal to ``ADMIN``, or
- Header ``X-Amprealize-Feature-Flags-Admin`` matching env
  ``AMPREALIZE_FEATURE_FLAGS_ADMIN_SECRET`` (for automation / break-glass).

DSN resolution follows the **Amprealize context system** (see ``amprealize.context``):

- Active **postgres** contexts (e.g. Neon, local-postgres) set ``DATABASE_URL`` and
  per-service DSNs via ``apply_context_to_environment()``; this module uses
  ``AMPREALIZE_FEATURE_FLAGS_PG_DSN`` (also set from the active context) with
  ``DATABASE_URL`` as fallback through ``resolve_optional_postgres_dsn``.
- **SQLite** or other non-postgres active contexts: no Postgres ``feature_flags``
  persistence is used (returns unconfigured; toggles are Postgres-only today).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from fastapi import Body, FastAPI, Request
from starlette.responses import JSONResponse

from amprealize.feature_flags import DEFAULT_FLAGS, FeatureFlagService, FlagType
from amprealize.feature_flag_runtime import get_boolean_override, replace_overrides, set_override
from amprealize.storage.feature_flags_pg import load_global_boolean_overrides, upsert_global_boolean
from amprealize.utils.dsn import resolve_optional_postgres_dsn

_CATALOG_NAMES = frozenset(f.name for f in DEFAULT_FLAGS)


def _feature_flags_dsn() -> str | None:
    """Resolve DSN for the ``feature_flags`` table, honoring the active storage context."""
    try:
        from amprealize.context import get_current_context

        _ctx_name, cfg = get_current_context()
        if cfg.storage.backend != "postgres":
            return None
    except Exception:
        pass

    return resolve_optional_postgres_dsn(
        service="FEATURE_FLAGS",
        explicit_dsn=os.getenv("AMPREALIZE_FEATURE_FLAGS_PG_DSN"),
        env_var="AMPREALIZE_FEATURE_FLAGS_PG_DSN",
    )


def _is_feature_flags_admin(request: Request) -> bool:
    secret = (os.getenv("AMPREALIZE_FEATURE_FLAGS_ADMIN_SECRET") or "").strip()
    if secret:
        hdr = (request.headers.get("X-Amprealize-Feature-Flags-Admin") or "").strip()
        if hdr == secret:
            return True
    claims = getattr(request.state, "token_claims", None) or {}
    role = claims.get("role")
    if isinstance(role, str) and role.upper() == "ADMIN":
        return True
    return False


def _merge_flag_payload() -> List[Dict[str, Any]]:
    svc = FeatureFlagService()
    out: List[Dict[str, Any]] = []
    for flag in svc.list_flags():
        src = "default"
        eff_enabled = flag.enabled
        if flag.flag_type == FlagType.BOOLEAN:
            ov = get_boolean_override(flag.name)
            if ov is not None:
                eff_enabled = ov
                src = "database"
        row: Dict[str, Any] = {
            "name": flag.name,
            "flag_type": flag.flag_type.value,
            "description": flag.description,
            "effective_enabled": eff_enabled,
            "registry_enabled": flag.enabled,
            "source": src,
        }
        if flag.flag_type == FlagType.PERCENTAGE:
            row["percentage"] = flag.percentage
        if flag.flag_type == FlagType.USER_LIST:
            row["user_list"] = list(flag.user_list)
        out.append(row)
    return out


def register_feature_flags_platform_routes(app: FastAPI) -> None:
    """Mount GET/PUT ``/api/v1/platform/feature-flags`` on *app*."""

    @app.on_event("startup")
    async def _hydrate_feature_flag_runtime() -> None:
        dsn = _feature_flags_dsn()
        if not dsn:
            return
        loaded = load_global_boolean_overrides(dsn)
        replace_overrides(loaded)

    @app.get("/api/v1/platform/feature-flags", tags=["platform"])
    def list_platform_feature_flags(request: Request) -> JSONResponse:
        if not _is_feature_flags_admin(request):
            return JSONResponse(status_code=403, content={"detail": "Forbidden"})
        dsn = _feature_flags_dsn()
        return JSONResponse(
            content={
                "database_configured": bool(dsn),
                "flags": _merge_flag_payload(),
            }
        )

    @app.put("/api/v1/platform/feature-flags/{flag_name:path}", tags=["platform"])
    def put_platform_feature_flag(
        flag_name: str,
        request: Request,
        payload: Dict[str, Any] = Body(...),
    ) -> JSONResponse:
        if not _is_feature_flags_admin(request):
            return JSONResponse(status_code=403, content={"detail": "Forbidden"})
        if flag_name not in _CATALOG_NAMES:
            return JSONResponse(status_code=404, content={"detail": "Unknown flag"})
        svc = FeatureFlagService()
        reg = svc.get_flag(flag_name)
        if reg is None or reg.flag_type != FlagType.BOOLEAN:
            return JSONResponse(
                status_code=400,
                content={"detail": "Only boolean catalogue flags can be toggled from this UI"},
            )
        dsn = _feature_flags_dsn()
        if not dsn:
            return JSONResponse(
                status_code=501,
                content={"detail": "No Postgres DSN configured for feature flag persistence"},
            )
        enabled = bool(payload.get("enabled", False))
        try:
            upsert_global_boolean(dsn, flag_name, enabled)
        except Exception as exc:
            return JSONResponse(status_code=500, content={"detail": str(exc)})
        set_override(flag_name, enabled)
        return JSONResponse(content={"name": flag_name, "enabled": enabled, "persisted": True})
