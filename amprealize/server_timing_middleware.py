"""Optional ``Server-Timing`` header for infra/gateway latency validation (guideai-1144).

Enable with ``AMPREALIZE_SERVER_TIMING=1`` (or ``true`` / ``yes``). Intended for staging
and debugging — disable in production unless you explicitly want timing metadata exposed.
"""

from __future__ import annotations

import os
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


def server_timing_enabled() -> bool:
    return os.getenv("AMPREALIZE_SERVER_TIMING", "").strip().lower() in ("1", "true", "yes")


class ServerTimingMiddleware(BaseHTTPMiddleware):
    """Attach ``Server-Timing: total;dur=...`` for app-side request duration (milliseconds)."""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        dur_ms = (time.perf_counter() - start) * 1000.0
        response.headers["Server-Timing"] = f"total;dur={dur_ms:.2f}"
        return response
