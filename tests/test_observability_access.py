from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict

import pytest

from amprealize.execution_observability import REDACTED_VALUE
from amprealize.observability_access import (
    ObservabilityAccessTier,
    filter_observability_event,
    summarize_observability_events,
)
from amprealize.telemetry import TelemetryEvent

pytestmark = pytest.mark.unit


def _event(
    *,
    event_type: str = "execution.llm.completed",
    run_id: str = "run-1",
    payload: Dict[str, Any] | None = None,
) -> TelemetryEvent:
    return TelemetryEvent(
        event_id=f"event-{event_type}-{run_id}",
        timestamp=datetime.now(timezone.utc).isoformat(),
        event_type=event_type,
        actor={"id": "user-1", "role": "DATA_ANALYST", "surface": "web"},
        run_id=run_id,
        action_id=None,
        session_id="session-1",
        payload=payload
        or {
            "execution_observability": {
                "run_id": run_id,
                "cycle_id": "cycle-1",
                "work_item_id": "GUIDEAI-1123",
                "project_id": "proj-guideai",
                "surface": "breakeramp",
                "source_type": "breakeramp",
                "queue_job_id": "breakeramp-job-1",
            },
            "raw_prompt": "Summarize token=super-secret-token across traces",
            "output_preview": "The answer included password=hidden-value",
            "inputs": {"path": "README.md", "api_key": "secret-value"},  # pragma: allowlist secret
            "safe_metric": 42,
        },
    )


def test_observability_viewer_and_data_analyst_cannot_read_restricted_payloads() -> None:
    viewer_event = filter_observability_event(
        _event(),
        tier=ObservabilityAccessTier.VIEWER,
    )
    analyst_event = filter_observability_event(
        _event(),
        tier=ObservabilityAccessTier.DATA_ANALYST,
    )

    for filtered in (viewer_event, analyst_event):
        payload = filtered["payload"]
        assert payload["raw_prompt"] == REDACTED_VALUE
        assert payload["output_preview"] == REDACTED_VALUE
        assert payload["inputs"] == REDACTED_VALUE
        assert payload["safe_metric"] == 42
        assert payload["execution_observability"]["queue_job_id"] == "breakeramp-job-1"


def test_observability_admin_can_read_sanitized_restricted_payloads() -> None:
    filtered = filter_observability_event(
        _event(),
        tier=ObservabilityAccessTier.ADMIN,
    )

    payload = filtered["payload"]
    assert payload["raw_prompt"] == f"Summarize token={REDACTED_VALUE} across traces"
    assert payload["output_preview"] == f"The answer included password={REDACTED_VALUE}"
    assert payload["inputs"]["api_key"] == REDACTED_VALUE
    assert payload["execution_observability"]["source_type"] == "breakeramp"


def test_observability_dashboard_summary_bounds_high_cardinality_series() -> None:
    events = [
        _event(
            event_type=f"execution.span.{index % 37}",
            run_id=f"run-{index}",
            payload={
                "execution_observability": {
                    "run_id": f"run-{index}",
                    "cycle_id": f"cycle-{index}",
                    "work_item_id": "GUIDEAI-1123",
                    "project_id": "proj-guideai",
                    "surface": f"surface-{index % 11}",
                    "source_type": "breakeramp",
                    "queue_job_id": f"breakeramp-job-{index}",
                },
                "raw_prompt": f"prompt with token=secret-token-{index}",
                "output_preview": f"output {index}",
            },
        )
        for index in range(500)
    ]

    summary = summarize_observability_events(
        events,
        tier=ObservabilityAccessTier.DATA_ANALYST,
        max_series=7,
    )

    assert summary["event_count"] == 500
    assert summary["unique_run_count"] == 500
    assert len(summary["event_types"]) == 7
    assert len(summary["surfaces"]) == 7
    assert summary["truncated_series"]["event_types"] == 30
    assert summary["truncated_series"]["surfaces"] == 4
    assert summary["sample_events"][0]["payload"]["raw_prompt"] == REDACTED_VALUE
    json.dumps(summary)
