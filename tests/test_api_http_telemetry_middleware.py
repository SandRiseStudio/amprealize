"""REST sampled telemetry helpers and optional full-app smoke test."""

from __future__ import annotations

import pytest
from amprealize.api_http_telemetry import api_http_route_key
from starlette.requests import Request


@pytest.mark.unit
def test_api_http_route_key_fallback_uuid_segment() -> None:
    scope = {
        "type": "http",
        "path": "/api/v1/runs/550e8400-e29b-41d4-a716-446655440000/status",
        "method": "GET",
        "headers": [],
    }
    req = Request(scope)
    assert "{id}" in api_http_route_key(req)


@pytest.mark.unit
def test_api_http_telemetry_emits_when_sample_rate_set(monkeypatch) -> None:
    try:
        from amprealize.api import create_app
    except ImportError:
        pytest.skip("Full API stack not importable in this environment")
    from fastapi.testclient import TestClient

    from amprealize.telemetry import InMemoryTelemetrySink

    sink = InMemoryTelemetrySink()
    monkeypatch.setenv("AMPREALIZE_API_HTTP_TELEMETRY_SAMPLE_RATE", "1")
    monkeypatch.setattr(
        "amprealize.api.create_sink_from_env",
        lambda **_: sink,
    )

    app = create_app(enable_auth_middleware=False)
    client = TestClient(app)

    r = client.get("/api/v1/capabilities")
    assert r.status_code == 200

    types = [e.event_type for e in sink.events]
    assert "api.http.completed" in types
    sample = next(e for e in sink.events if e.event_type == "api.http.completed")
    assert sample.payload.get("method") == "GET"
    assert sample.payload.get("status_code") == 200
    assert "elapsed_ms" in sample.payload
    assert sample.payload.get("execution_observability", {}).get("surface") == "api"
