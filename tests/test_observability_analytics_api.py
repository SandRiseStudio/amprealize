from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from amprealize.execution_observability import REDACTED_VALUE
from amprealize.observability_analytics import GovernedObservabilityQueryService
from amprealize.services.observability_analytics_api import (
    create_observability_analytics_routes,
)
from amprealize.telemetry import TelemetryEvent

pytestmark = pytest.mark.unit


def _event(
    event_type: str,
    *,
    run_id: str,
    surface: str,
    index: int,
) -> TelemetryEvent:
    return TelemetryEvent(
        event_id=f"{event_type}-{run_id}-{index}",
        timestamp=datetime.now(timezone.utc).isoformat(),
        event_type=event_type,
        actor={"id": "agent-1", "role": "AGENT", "surface": surface},
        run_id=run_id,
        action_id=None,
        session_id="session-1",
        payload={
            "execution_observability": {
                "run_id": run_id,
                "cycle_id": f"cycle-{index}",
                "work_item_id": "GUIDEAI-1112",
                "project_id": "proj-guideai",
                "surface": surface,
            },
            "raw_prompt": f"prompt token=secret-token-{index}",
            "inputs": {"api_key": f"secret-value-{index}", "path": "README.md"},
            "output_preview": f"output password=hidden-value-{index}",
            "elapsed_ms": index * 10,
        },
    )


def _events() -> Iterable[TelemetryEvent]:
    for index in range(5):
        yield _event(
            "execution.llm.completed" if index % 2 == 0 else "execution.tool.started",
            run_id=f"run-{index % 2}",
            surface="chat" if index % 2 == 0 else "mcp",
            index=index,
        )


def _current_user(**overrides: Any) -> Dict[str, Any]:
    return {
        "user_id": "user-1",
        "role": "viewer",
        **overrides,
    }


def _client(current_user: Dict[str, Any] | None = None) -> TestClient:
    app = FastAPI()
    service = GovernedObservabilityQueryService(event_provider=_events)
    app.include_router(
        create_observability_analytics_routes(
            observability_query_service=service,
            get_current_user=lambda: current_user or _current_user(),
        )
    )
    return TestClient(app)


def test_observability_events_endpoint_returns_viewer_safe_records() -> None:
    response = _client().post(
        "/v1/observability/events",
        json={"event_types": ["execution.llm.completed"], "limit": 2},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["access_tier"] == "viewer"
    assert payload["count"] == 2
    assert payload["truncated"] is True
    assert payload["query"]["event_types"] == ["execution.llm.completed"]
    for record in payload["records"]:
        assert record["payload"]["raw_prompt"] == REDACTED_VALUE
        assert record["payload"]["inputs"] == REDACTED_VALUE
        assert record["payload"]["output_preview"] == REDACTED_VALUE


def test_observability_events_endpoint_allows_admin_sanitized_records() -> None:
    response = _client(_current_user(role="admin")).post(
        "/v1/observability/events",
        json={"run_id": "run-1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["access_tier"] == "admin"
    assert payload["count"] == 2
    for record in payload["records"]:
        record_payload = record["payload"]
        assert record_payload["raw_prompt"].startswith(f"prompt token={REDACTED_VALUE}")
        assert record_payload["inputs"]["api_key"] == REDACTED_VALUE
        assert record_payload["output_preview"].startswith(f"output password={REDACTED_VALUE}")


def test_observability_dashboard_endpoint_returns_bounded_analyst_summary() -> None:
    response = _client(_current_user(role="data_analyst")).post(
        "/v1/observability/dashboard",
        json={"max_series": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["access_tier"] == "data_analyst"
    assert payload["event_count"] == 5
    assert payload["unique_run_count"] == 2
    assert len(payload["event_types"]) == 1
    assert len(payload["surfaces"]) == 1
    assert payload["truncated_series"]["event_types"] == 1
    assert payload["sample_events"][0]["payload"]["raw_prompt"] == REDACTED_VALUE
