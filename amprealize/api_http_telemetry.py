"""REST HTTP sampled telemetry helpers (kept import-light for tests)."""

from __future__ import annotations

from typing import List

from starlette.requests import Request


def api_http_telemetry_skip_path(path: str) -> bool:
    """Paths excluded from sampled HTTP request telemetry."""

    if not path:
        return True
    if path in {"/health", "/metrics", "/docs", "/openapi.json", "/redoc", "/favicon.ico"}:
        return True
    if path.startswith("/health") or path.startswith("/metrics"):
        return True
    return False


def api_http_route_key(request: Request) -> str:
    """Low-cardinality route key (OpenAPI template or sanitized path)."""

    route = request.scope.get("route")
    template = getattr(route, "path", None) if route is not None else None
    if template:
        return str(template)
    raw = request.url.path or "/"
    segments: List[str] = []
    for segment in raw.strip("/").split("/"):
        if not segment:
            continue
        lower = segment.lower()
        if (
            len(segment) == 36
            and segment.count("-") == 4
            and all(c in "0123456789abcdef-" for c in lower)
        ):
            segments.append("{id}")
        elif segment.isdigit():
            segments.append("{id}")
        else:
            segments.append(segment)
    return "/" + "/".join(segments) if segments else "/"
