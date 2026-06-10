from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from amprealize.observability_trace_query import GovernedTraceReadService, TraceSummaryFilters
from amprealize.services.observability_trace_api import create_observability_trace_routes
from amprealize.tenant.permissions import NotAMember, PermissionDenied, ProjectPermission

pytestmark = pytest.mark.unit


class _FakeSink:
    def __init__(self) -> None:
        self.last_run_kwargs: Optional[Dict[str, Any]] = None
        self.last_conv_kwargs: Optional[Dict[str, Any]] = None
        self.last_span_kwargs: Optional[Dict[str, Any]] = None

    def query_run_summaries(self, **kwargs: Any) -> List[Dict[str, Any]]:
        self.last_run_kwargs = dict(kwargs)
        return [
            {
                "run_id": "run-a",
                "started_at": "2026-05-04T12:00:00+00:00",
                "last_event_at": "2026-05-04T12:01:00+00:00",
                "record_count": 3,
                "failed_record_count": 0,
                "generation_count": 1,
                "tool_call_count": 1,
                "span_count": 1,
                "primary_trace_id": "trace-1",
                "project_id": kwargs["project_id"],
                "work_item_id": None,
                "surface": "web",
            },
        ]

    def query_conversation_summaries(self, **kwargs: Any) -> List[Dict[str, Any]]:
        self.last_conv_kwargs = dict(kwargs)
        return [
            {
                "conversation_id": "conv-1",
                "started_at": "2026-05-04T12:00:00+00:00",
                "last_event_at": "2026-05-04T12:01:00+00:00",
                "record_count": 2,
                "trace_count": 1,
                "generation_count": 1,
                "tool_call_count": 0,
                "project_id": kwargs["project_id"],
                "surface": "web",
            },
        ]

    def query_span_tree(self, **kwargs: Any) -> List[Dict[str, Any]]:
        self.last_span_kwargs = dict(kwargs)
        return [
            {
                "record_id": "00000000-0000-0000-0000-000000000001",
                "record_timestamp": "2026-05-04T12:00:00+00:00",
                "trace_id": kwargs["trace_id"],
                "span_id": "s1",
                "parent_span_id": None,
                "name": "chat.span.test",
                "status": "ok",
                "kind": "span",
                "depth": 0,
            },
        ]


def _current_user(**overrides: Any) -> Dict[str, Any]:
    return {"user_id": "user-1", "role": "viewer", **overrides}


def _client(fake: _FakeSink | None) -> TestClient:
    app = FastAPI()

    def sink_provider():
        return fake

    service = GovernedTraceReadService(sink_provider=sink_provider)
    app.include_router(
        create_observability_trace_routes(
            trace_read_service=service,
            get_current_user=lambda: _current_user(),
        )
    )
    return TestClient(app)


def test_trace_runs_returns_records_and_tier() -> None:
    fake = _FakeSink()
    response = _client(fake).post(
        "/v1/observability/traces/runs",
        json={"project_id": "proj-x", "limit": 10},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["access_tier"] == "viewer"
    assert payload["count"] == 1
    assert payload["records"][0]["run_id"] == "run-a"
    assert fake.last_run_kwargs is not None
    assert fake.last_run_kwargs["project_id"] == "proj-x"


def test_trace_conversations_filters_conversation_id() -> None:
    fake = _FakeSink()
    response = _client(fake).post(
        "/v1/observability/traces/conversations",
        json={"project_id": "proj-x", "conversation_id": "conv-1"},
    )
    assert response.status_code == 200
    assert fake.last_conv_kwargs is not None
    assert fake.last_conv_kwargs["conversation_id"] == "conv-1"


def test_trace_spans_returns_tree() -> None:
    fake = _FakeSink()
    response = _client(fake).post(
        "/v1/observability/traces/spans",
        json={"project_id": "proj-x", "trace_id": "trace-1"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["trace_id"] == "trace-1"
    assert payload["records"][0]["span_id"] == "s1"
    assert fake.last_span_kwargs is not None
    assert fake.last_span_kwargs["project_id"] == "proj-x"


def test_governed_service_empty_without_sink() -> None:
    service = GovernedTraceReadService(sink_provider=lambda: None)
    out = service.list_run_summaries(
        {"role": "admin"},
        TraceSummaryFilters(project_id="p"),
    )
    assert out["records"] == []
    assert out["access_tier"] == "admin"


def test_trace_runs_401_when_user_id_missing() -> None:
    fake = _FakeSink()
    app = FastAPI()
    service = GovernedTraceReadService(sink_provider=lambda: fake)
    app.include_router(
        create_observability_trace_routes(
            trace_read_service=service,
            get_current_user=lambda: {"role": "viewer"},
        )
    )
    client = TestClient(app)
    response = client.post("/v1/observability/traces/runs", json={"project_id": "proj-x"})
    assert response.status_code == 401


def test_trace_runs_403_when_view_runs_denied() -> None:
    fake = _FakeSink()
    app = FastAPI()
    mock_perm = MagicMock()
    mock_perm.require_project_permission = AsyncMock(
        side_effect=PermissionDenied(ProjectPermission.VIEW_RUNS, "user-1", "proj-x"),
    )
    app.state.async_permission_service = mock_perm
    service = GovernedTraceReadService(sink_provider=lambda: fake)
    app.include_router(
        create_observability_trace_routes(
            trace_read_service=service,
            get_current_user=lambda: _current_user(),
        )
    )
    client = TestClient(app)
    response = client.post("/v1/observability/traces/runs", json={"project_id": "proj-x"})
    assert response.status_code == 403
    mock_perm.require_project_permission.assert_awaited_once()


def test_trace_runs_404_when_not_project_member() -> None:
    fake = _FakeSink()
    app = FastAPI()
    mock_perm = MagicMock()
    mock_perm.require_project_permission = AsyncMock(side_effect=NotAMember("user-1", "proj-x", "project"))
    app.state.async_permission_service = mock_perm
    service = GovernedTraceReadService(sink_provider=lambda: fake)
    app.include_router(
        create_observability_trace_routes(
            trace_read_service=service,
            get_current_user=lambda: _current_user(),
        )
    )
    client = TestClient(app)
    response = client.post("/v1/observability/traces/runs", json={"project_id": "proj-x"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"


def test_trace_runs_500_when_strict_and_no_permission_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMPREALIZE_AUTH_STRICT", "true")
    fake = _FakeSink()
    app = FastAPI()
    service = GovernedTraceReadService(sink_provider=lambda: fake)
    app.include_router(
        create_observability_trace_routes(
            trace_read_service=service,
            get_current_user=lambda: _current_user(),
        )
    )
    client = TestClient(app)
    response = client.post("/v1/observability/traces/runs", json={"project_id": "proj-x"})
    assert response.status_code == 500
