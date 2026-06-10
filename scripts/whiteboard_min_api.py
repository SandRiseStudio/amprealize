"""Minimal whiteboard-only FastAPI app for local brainstorm whiteboarding.

This is the bare-minimum browser-facing API that the whiteboard-sync sidecar
talks to (PYTHON_API_BASE -> /api/v1/whiteboard/...). It deliberately avoids
booting the full ``amprealize.api`` app (which constructs dozens of services
and many Postgres pools). It serves only the whiteboard room/canvas/snapshot
routes, backed by the SAME storage the MCP server uses via
``create_storage_from_env()`` — so rooms the brainstorm agent creates over MCP
are visible here, and therefore to the browser.

Storage is selected by env (shared with the MCP server and the full API):

    WHITEBOARD_STORAGE_BACKEND = memory | sqlite | postgres
    WHITEBOARD_SQLITE_PATH     = path to the shared sqlite file (sqlite backend)
    WHITEBOARD_PG_DSN          = postgres DSN (postgres backend)

Auth: this is a LOCAL DEV server. A permissive middleware stamps every request
with a fixed dev identity (``WHITEBOARD_DEV_USER``, default ``mcp-user`` to
match the MCP brainstorm bridge's ``created_by``) so the whiteboard routes'
``request.state.user_id`` auth check passes and the sidecar's token validation
(GET .../rooms/{id}) returns 200. Do NOT expose this beyond localhost.

Run::

    WHITEBOARD_STORAGE_BACKEND=sqlite \\
    WHITEBOARD_SQLITE_PATH=/Users/nick/Main/amprealize/.whiteboard-dev.db \\
    uvicorn scripts.whiteboard_min_api:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

# Importing ``amprealize`` first registers ``packages/*/src`` on sys.path
# (see amprealize/__init__.py), which is what makes ``whiteboard`` importable.
import amprealize  # noqa: F401  (side effect: path setup)
from whiteboard import WhiteboardService, create_storage_from_env
from amprealize.services.whiteboard_api import create_whiteboard_routes

logging.basicConfig(level=os.environ.get("WHITEBOARD_MIN_API_LOG_LEVEL", "INFO"))
logger = logging.getLogger("whiteboard_min_api")

_DEV_USER = os.environ.get("WHITEBOARD_DEV_USER", "mcp-user")
_DEV_ORG = os.environ.get("WHITEBOARD_DEV_ORG") or None
_DEV_PROJECT = os.environ.get("WHITEBOARD_DEV_PROJECT") or None
# Comma-separated allowed origins for the local web-console (Vite).
_CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "WHITEBOARD_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if o.strip()
]


def _build_app() -> FastAPI:
    storage = create_storage_from_env()
    backend = os.environ.get("WHITEBOARD_STORAGE_BACKEND", "memory")
    logger.info("whiteboard_min_api storage backend=%s (%s)", backend, type(storage).__name__)

    service = WhiteboardService(storage=storage, hooks=None)

    app = FastAPI(title="Amprealize Whiteboard (minimal local API)", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _dev_auth(request: Request, call_next):
        # Local dev identity so whiteboard routes' user_id auth check passes.
        request.state.user_id = _DEV_USER
        request.state.org_id = _DEV_ORG
        request.state.project_id = _DEV_PROJECT
        return await call_next(request)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok", "storage": backend}

    # Mount at prefix "/api" so paths are /api/v1/whiteboard/... — matching the
    # sidecar's default PYTHON_API_BASE=http://localhost:8000/api/v1 and the
    # full app's own include_router(..., prefix="/api").
    routes = create_whiteboard_routes(service=service, tags=["whiteboard"])
    app.include_router(routes, prefix="/api")

    return app


app = _build_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("WHITEBOARD_MIN_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("WHITEBOARD_MIN_API_PORT", "8000")),
    )
