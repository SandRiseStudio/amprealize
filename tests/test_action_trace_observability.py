"""Tests for action trace/span observability linkage."""

from __future__ import annotations

import pytest

from amprealize.action_contracts import ActionCreateRequest, Actor, ReplayRequest
from amprealize.action_service import ActionService
from amprealize.telemetry import InMemoryTelemetrySink, TelemetryClient

pytestmark = pytest.mark.unit


def _service() -> tuple[ActionService, InMemoryTelemetrySink]:
    sink = InMemoryTelemetrySink()
    return ActionService(telemetry=TelemetryClient(sink=sink)), sink


def test_create_action_derives_trace_fields_and_sanitizes_telemetry_metadata():
    service, sink = _service()
    actor = Actor(id="user-1", role="STUDENT", surface="CLI")

    action = service.create_action(
        ActionCreateRequest(
            artifact_path="docs/trace.md",
            summary="Document trace linkage",
            behaviors_cited=["behavior_unify_execution_records"],
            metadata={
                "execution_observability": {
                    "run_id": "run-1",
                    "cycle_id": "cycle-1",
                    "work_item_id": "wi-1",
                    "project_id": "proj-1",
                },
                "auth_token": "secret-value",
            },
            outcome_ref="work_item:wi-1",
        ),
        actor,
    )

    assert action.trace_id == "run-1"
    assert action.span_id == f"action:{action.action_id}"
    assert action.parent_span_id == "cycle-1"
    assert action.outcome_ref == "work_item:wi-1"

    recorded = next(event for event in sink.events if event.event_type == "action_recorded")
    outcome = next(event for event in sink.events if event.event_type == "action.business_outcome")
    assert recorded.payload["trace_id"] == "run-1"
    assert recorded.payload["span_id"] == f"action:{action.action_id}"
    assert recorded.payload["metadata"]["auth_token"] == "***REDACTED***"
    assert outcome.payload["outcome_type"] == "action_recorded"
    assert outcome.payload["outcome_ref"] == "work_item:wi-1"
    assert outcome.payload["trace_id"] == "run-1"


def test_replay_events_include_action_trace_and_outcome_linkage():
    service, sink = _service()
    actor = Actor(id="user-1", role="STUDENT", surface="CLI")
    action = service.create_action(
        ActionCreateRequest(
            artifact_path="docs/replay.md",
            summary="Replay traceable action",
            behaviors_cited=["behavior_unify_execution_records"],
            metadata={"action_type": "generic"},
            trace_id="trace-1",
            span_id="span-1",
            parent_span_id="root-span",
            outcome_ref="outcome:initial",
        ),
        actor,
    )

    replay = service.replay_actions(
        ReplayRequest(action_ids=[action.action_id], strategy="SEQUENTIAL"),
        actor,
    )

    assert replay.trace_id == "trace-1"
    assert replay.parent_span_id == "span-1"
    assert replay.outcome_ref == replay.audit_log_event_id

    replay_start = next(event for event in sink.events if event.event_type == "action_replay_start")
    replay_complete = next(event for event in sink.events if event.event_type == "action_replay_complete")
    replay_performance = next(event for event in sink.events if event.event_type == "action.replay.performance")
    replay_outcomes = [
        event for event in sink.events
        if event.event_type == "action.business_outcome"
        and event.payload["outcome_type"] == "action_replay"
    ]
    execution_start = next(event for event in sink.events if event.event_type == "action_execution_start")
    execution_complete = next(event for event in sink.events if event.event_type == "action_execution_complete")
    execution_performance = next(event for event in sink.events if event.event_type == "action.execution.performance")

    assert replay_start.payload["trace_id"] == "trace-1"
    assert replay_start.payload["parent_span_id"] == "span-1"
    assert replay_complete.payload["span_id"] == replay.span_id
    assert replay_performance.payload["status"] == "SUCCEEDED"
    assert replay_performance.payload["succeeded_count"] == 1
    assert replay_outcomes[0].payload["outcome_ref"] == replay.audit_log_event_id
    assert execution_start.payload["trace_id"] == "trace-1"
    assert execution_start.payload["span_id"] == "span-1"
    assert execution_complete.payload["outcome_ref"] == "outcome:initial"
    assert execution_performance.payload["status"] == "SUCCEEDED"
    assert execution_performance.payload["action_type"] == "generic"
