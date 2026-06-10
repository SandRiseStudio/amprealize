"""Propagate `X-Web-Perf-Session` for server-side perf logs and DB telemetry.

The web console sets this header on API calls during a dashboard perf session
so `perf_span` lines, Postgres instrumented payloads, and optional Raze request
logs share the same correlation id as browser-side marks (`perf_session_id`).
"""

from __future__ import annotations

import contextlib
import contextvars
from typing import Iterator, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

_web_perf_session_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "web_perf_session_id",
    default=None,
)


def get_web_perf_session_id() -> Optional[str]:
    """Return the active web perf session id for this async task, if any."""
    return _web_perf_session_id.get()


@contextlib.contextmanager
def bind_web_perf_session(session_id: Optional[str]) -> Iterator[None]:
    """Temporarily set the web perf session id (tests and tools)."""
    token = _web_perf_session_id.set(session_id)
    try:
        yield
    finally:
        _web_perf_session_id.reset(token)


class WebPerfSessionMiddleware(BaseHTTPMiddleware):
    """Bind ``X-Web-Perf-Session`` to request scope + contextvar for downstream code."""

    async def dispatch(self, request: Request, call_next):
        raw = (
            request.headers.get("X-Web-Perf-Session")
            or request.headers.get("x-web-perf-session")
            or ""
        ).strip()
        token = _web_perf_session_id.set(raw or None)
        try:
            if raw:
                request.state.web_perf_session_id = raw
            return await call_next(request)
        finally:
            _web_perf_session_id.reset(token)
