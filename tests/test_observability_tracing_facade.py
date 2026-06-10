"""Regression tests for :class:`~amprealize.observability_tracing.Tracer` (non-fatal sink, correlation)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from amprealize.observability_tracing import (
    TraceContext,
    Tracer,
    attach_trace_context,
    correlation_from_trace_context,
    current_trace_context,
    detach_trace_context,
)

pytestmark = pytest.mark.unit


class _ChatReq:
    conversation_id = "conv"
    user_message_id = "um"
    user_id = "u1"
    org_id = "o1"
    project_id = "proj"
    work_item_id = None
    run_id = None


def test_emit_chat_event_swallows_telemetry_exception() -> None:
    telemetry = MagicMock()
    telemetry.emit_event.side_effect = RuntimeError("sink unavailable")
    tracer = Tracer(telemetry)
    tracer.emit_chat_event(_ChatReq(), "chat.foo", {"x": 1})
    # Must not raise


def test_emit_execution_gateway_event_swallows_telemetry_exception() -> None:
    telemetry = MagicMock()
    telemetry.emit_event.side_effect = OSError("network")
    tracer = Tracer(telemetry, service_name="execution-gateway")
    tracer.emit_execution_gateway_event(
        event_type="execution.gateway.started",
        payload={"run_id": "r1"},
        run_id="r1",
    )


def test_record_generation_resolves_correlation_from_contextvars() -> None:
    telemetry = MagicMock()
    tracer = Tracer(telemetry)
    ct = TraceContext.from_chat_trace(
        {
            "trace_id": "tr-ctx",
            "span_id": "sp-ctx",
            "reply_message_id": "rmid",
            "project_id": "proj-x",
            "conversation_id": "c1",
            "user_message_id": "u1",
        }
    )
    token = attach_trace_context(ct)
    try:
        tracer.record_generation(name="reply", model_id="gpt-test", input_tokens=1, output_tokens=2)
    finally:
        detach_trace_context(token)

    telemetry.emit_event.assert_called_once()
    kw = telemetry.emit_event.call_args.kwargs
    assert kw["event_type"] == "observability.record"
    payload = kw["payload"]["record"]
    assert payload["correlation"]["trace_id"] == "tr-ctx"
    assert payload["model_id"] == "gpt-test"
    assert payload["kind"] == "generation"


def test_record_generation_warns_when_correlation_missing_model_id(mocker: pytest.MockerFixture) -> None:
    warn = mocker.patch("amprealize.observability_tracing._log_warning")
    telemetry = MagicMock()
    tracer = Tracer(telemetry)
    ct = TraceContext.from_chat_trace(
        {
            "trace_id": "tr-w",
            "span_id": "sp-w",
            "reply_message_id": "rm",
            "project_id": "p",
        }
    )
    token = attach_trace_context(ct)
    try:
        tracer.record_generation(name="reply")
    finally:
        detach_trace_context(token)

    telemetry.emit_event.assert_called_once()
    warn.assert_called()
    assert "model_id" in (warn.call_args.kwargs.get("missing") or "")


def test_correlation_from_trace_context_maps_chat_surface() -> None:
    ct = TraceContext.from_chat_trace(
        {"trace_id": "a", "span_id": "b", "reply_message_id": "c", "project_id": "p9"}
    )
    corr = correlation_from_trace_context(ct)
    assert corr.surface == "chat"
    assert corr.project_id == "p9"
