from __future__ import annotations

import json

import pytest

from amprealize.execution_observability import REDACTED_VALUE
from amprealize.observability_contracts import (
    GenerationEnvelope,
    ObservabilityCorrelation,
    ObservabilityRecordKind,
    ObservabilitySensitivity,
    SpanEnvelope,
    ToolCallEnvelope,
    TraceEnvelope,
)
from amprealize.observability_exporters import (
    build_datadog_export_payload,
    build_langfuse_export_payload,
    observability_exporter_profiles,
)

pytestmark = pytest.mark.unit


def _correlation(*, span_id: str, parent_span_id: str | None = "span-root") -> ObservabilityCorrelation:
    return ObservabilityCorrelation(
        trace_id="trace-1",
        span_id=span_id,
        parent_span_id=parent_span_id,
        project_id="proj-1",
        org_id="org-1",
        conversation_id="conv-1",
        message_id="msg-1",
        run_id="run-1",
        work_item_id="GUIDEAI-1109",
        actor_id="user-1",
        actor_role="Student",
        surface="chat",
        model_id="gpt-example",
    )


def _records() -> list[TraceEnvelope | SpanEnvelope | GenerationEnvelope | ToolCallEnvelope]:
    timestamp = "2026-04-28T00:00:00+00:00"
    return [
        TraceEnvelope(
            record_id="trace-record-1",
            kind=ObservabilityRecordKind.TRACE,
            name="chat.execution",
            timestamp=timestamp,
            correlation=_correlation(span_id="span-root", parent_span_id=None),
            duration_ms=1500.0,
        ),
        SpanEnvelope(
            record_id="span-record-1",
            kind=ObservabilityRecordKind.SPAN,
            name="chat.routing",
            timestamp=timestamp,
            correlation=_correlation(span_id="span-routing"),
            duration_ms=12.5,
            attributes={"route": "llm"},
        ),
        GenerationEnvelope(
            record_id="generation-record-1",
            kind=ObservabilityRecordKind.GENERATION,
            name="llm.generation",
            timestamp=timestamp,
            correlation=_correlation(span_id="span-generation"),
            sensitivity=ObservabilitySensitivity.SUMMARY,
            provider="openai",
            model_id="gpt-example",
            input_tokens=100,
            output_tokens=40,
            cost_usd=0.0012,
            latency_ms=250.0,
            first_token_latency_ms=50.0,
            prompt_summary="Summarize token=super-secret-token",
            output_summary="Created safe summary",
        ),
        ToolCallEnvelope(
            record_id="tool-record-1",
            kind=ObservabilityRecordKind.TOOL_CALL,
            name="tool.workitems_update",
            timestamp=timestamp,
            correlation=_correlation(span_id="span-tool"),
            sensitivity=ObservabilitySensitivity.RESTRICTED,
            tool_name="workitems_update",
            call_id="tool-call-1",
            elapsed_ms=30.0,
            input_summary={"api_key": "secret-value", "item_id": "GUIDEAI-1109"},  # pragma: allowlist secret
            output_summary={"status": "done"},
        ),
    ]


def test_exporter_profiles_are_secret_free_and_cover_managed_targets() -> None:
    profiles = observability_exporter_profiles()

    assert set(profiles) == {"datadog", "langfuse_cloud"}
    assert profiles["datadog"]["transport"] == "otlp_http"
    assert profiles["datadog"]["exported_sections"] == ["spans", "logs", "metrics"]
    assert "AMPREALIZE_DATADOG_API_KEY" in profiles["datadog"]["required_env"]
    assert profiles["langfuse_cloud"]["exported_sections"] == ["traces", "observations"]
    assert "generation" in profiles["langfuse_cloud"]["record_kinds"]
    json.dumps(profiles)


def test_datadog_export_payload_preserves_correlation_and_metrics_without_raw_secrets() -> None:
    payload = build_datadog_export_payload(_records())

    assert payload["target"] == "datadog"
    assert len(payload["spans"]) == 4
    assert len(payload["logs"]) == 4
    assert payload["spans"][2]["trace_id"] == "trace-1"
    assert payload["spans"][2]["span_id"] == "span-generation"
    assert "project_id:proj-1" in payload["spans"][2]["tags"]
    assert any(
        metric["name"] == "amprealize.observability.generation.input_tokens"
        and metric["value"] == 100
        for metric in payload["metrics"]
    )

    tool_log = next(log for log in payload["logs"] if log["message"] == "tool.workitems_update")
    assert tool_log["attributes"]["input_summary"]["api_key"] == REDACTED_VALUE
    assert "secret-value" not in json.dumps(payload)


def test_langfuse_export_payload_maps_generations_and_tool_calls() -> None:
    payload = build_langfuse_export_payload(_records())

    assert payload["target"] == "langfuse_cloud"
    assert payload["traces"] == [
        {
            "id": "trace-1",
            "name": "chat.execution",
            "timestamp": "2026-04-28T00:00:00+00:00",
            "user_id": "user-1",
            "session_id": "conv-1",
            "metadata": {
                "record_id": "trace-record-1",
                "project_id": "proj-1",
                "work_item_id": "GUIDEAI-1109",
                "surface": "chat",
                "root_record": _records()[0].to_sanitized_payload(),
            },
        }
    ]

    generation = next(
        observation for observation in payload["observations"] if observation["type"] == "GENERATION"
    )
    assert generation["model"] == "gpt-example"
    assert generation["provider"] == "openai"
    assert generation["usage"] == {
        "input_tokens": 100,
        "output_tokens": 40,
        "total_tokens": 140,
        "cost_usd": 0.0012,
    }
    assert generation["time_to_first_token_ms"] == 50.0

    tool = next(observation for observation in payload["observations"] if observation["type"] == "TOOL")
    assert tool["tool_name"] == "workitems_update"
    assert tool["input"]["api_key"] == REDACTED_VALUE
    assert tool["input"]["item_id"] == "GUIDEAI-1109"
    assert "secret-value" not in json.dumps(payload)
