from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable

import pytest

from amprealize.execution_observability import REDACTED_VALUE
from amprealize.observability_analytics import (
    GovernedObservabilityQueryService,
    ObservabilityQuery,
)
from amprealize.telemetry import TelemetryEvent

pytestmark = pytest.mark.unit


def _event(
    event_type: str,
    *,
    run_id: str,
    payload: Dict[str, Any],
) -> TelemetryEvent:
    return TelemetryEvent(
        event_id=f"{event_type}-{run_id}",
        timestamp=datetime.now(timezone.utc).isoformat(),
        event_type=event_type,
        actor={"id": "user-1", "role": "ADMIN", "surface": "web"},
        run_id=run_id,
        action_id=None,
        session_id="session-1",
        payload=payload,
    )


def _events() -> Iterable[TelemetryEvent]:
    for index in range(6):
        yield _event(
            "execution.llm.completed" if index % 2 == 0 else "execution.tool.started",
            run_id=f"run-{index % 3}",
            payload={
                "execution_observability": {
                    "run_id": f"run-{index % 3}",
                    "cycle_id": f"cycle-{index}",
                    "work_item_id": "GUIDEAI-1113",
                    "project_id": "proj-guideai",
                    "surface": "chat" if index % 2 == 0 else "mcp",
                },
                "raw_prompt": f"prompt token=secret-token-{index}",
                "inputs": {"api_key": f"secret-value-{index}", "path": "README.md"},
                "output_preview": f"output password=hidden-value-{index}",
                "elapsed_ms": index * 10,
            },
        )


def test_governed_observability_query_redacts_viewer_records() -> None:
    service = GovernedObservabilityQueryService(event_provider=_events)

    result = service.list_events(
        ObservabilityQuery(
            actor={"id": "viewer-1", "role": "viewer"},
            event_types=("execution.llm.completed",),
            limit=2,
        )
    )

    assert result["access_tier"] == "viewer"
    assert result["count"] == 2
    assert result["truncated"] is True
    for record in result["records"]:
        payload = record["payload"]
        assert payload["raw_prompt"] == REDACTED_VALUE
        assert payload["inputs"] == REDACTED_VALUE
        assert payload["output_preview"] == REDACTED_VALUE
        assert payload["execution_observability"]["work_item_id"] == "GUIDEAI-1113"


def test_governed_observability_query_allows_admin_sanitized_records() -> None:
    service = GovernedObservabilityQueryService(event_provider=_events)

    result = service.list_events(
        ObservabilityQuery(
            actor={"id": "admin-1", "role": "admin"},
            run_id="run-1",
        )
    )

    assert result["access_tier"] == "admin"
    assert result["count"] == 2
    for record in result["records"]:
        payload = record["payload"]
        assert payload["raw_prompt"].startswith(f"prompt token={REDACTED_VALUE}")
        assert payload["inputs"]["api_key"] == REDACTED_VALUE
        assert payload["output_preview"].startswith(f"output password={REDACTED_VALUE}")


def test_governed_observability_dashboard_uses_actor_tier_and_bounded_series() -> None:
    service = GovernedObservabilityQueryService(event_provider=_events)

    result = service.dashboard_summary(
        ObservabilityQuery(
            actor={"id": "analyst-1", "role": "data_analyst"},
            max_series=1,
        )
    )

    assert result["access_tier"] == "data_analyst"
    assert result["event_count"] == 6
    assert result["unique_run_count"] == 3
    assert len(result["event_types"]) == 1
    assert len(result["surfaces"]) == 1
    assert result["truncated_series"]["event_types"] == 1
    assert result["sample_events"][0]["payload"]["raw_prompt"] == REDACTED_VALUE
