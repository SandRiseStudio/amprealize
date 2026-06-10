"""Tests for TraceContext, contextvars propagation, and Tracer chat emitters."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

import pytest

from amprealize.observability_tracing import (
    TraceContext,
    Tracer,
    attach_trace_context,
    bind_context,
    correlation_from_trace_context,
    current_trace_context,
    detach_trace_context,
)

pytestmark = pytest.mark.unit


def test_attach_detach_clears_context() -> None:
    ct = TraceContext.from_chat_trace(
        {
            "trace_id": "tid",
            "span_id": "sid",
            "reply_message_id": "mid",
            "project_id": "pid",
        }
    )
    token = attach_trace_context(ct)
    assert current_trace_context() is not None
    assert current_trace_context().trace_id == "tid"
    detach_trace_context(token)
    assert current_trace_context() is None


def test_nested_attach_restores_outer() -> None:
    outer = TraceContext.from_chat_trace(
        {"trace_id": "outer", "span_id": "so", "reply_message_id": "m"}
    )
    inner = TraceContext.from_chat_trace(
        {"trace_id": "inner", "span_id": "si", "reply_message_id": "m"}
    )
    t1 = attach_trace_context(outer)
    assert current_trace_context().trace_id == "outer"
    t2 = attach_trace_context(inner)
    assert current_trace_context().trace_id == "inner"
    detach_trace_context(t2)
    assert current_trace_context().trace_id == "outer"
    detach_trace_context(t1)
    assert current_trace_context() is None


def test_correlation_from_trace_context_unknown_project() -> None:
    ctx = TraceContext.from_chat_trace({"trace_id": "a", "span_id": "b", "reply_message_id": "c"})
    corr = correlation_from_trace_context(ctx)
    assert corr.project_id == "unknown"


def test_tracer_emit_chat_span_completed_resolves_chat_trace_from_context() -> None:
    telemetry = MagicMock()
    tracer = Tracer(telemetry)
    ct = TraceContext.from_chat_trace(
        {
            "trace_id": "tid",
            "span_id": "sid",
            "reply_message_id": "rid",
            "project_id": "proj",
        }
    )
    token = attach_trace_context(ct)
    try:

        class _Req:
            conversation_id = "conv"
            user_message_id = "um"
            user_id = "u1"
            org_id = "o1"
            project_id = "proj"
            work_item_id = None
            run_id = None

        t0 = time.monotonic()
        tracer.emit_chat_span_completed(_Req(), span_name="routing", started_at=t0)
    finally:
        detach_trace_context(token)

    telemetry.emit_event.assert_called_once()
    kwargs = telemetry.emit_event.call_args.kwargs
    assert kwargs["event_type"] == "chat.span.completed"
    assert kwargs["payload"]["span_name"] == "routing"
    assert kwargs["payload"]["trace_id"] == "tid"


def test_emit_execution_gateway_event_forwards_to_telemetry() -> None:
    telemetry = MagicMock()
    tracer = Tracer(telemetry, service_name="execution-gateway")
    tracer.emit_execution_gateway_event(
        event_type="execution.gateway.started",
        payload={"run_id": "r1", "mode": "container_isolated"},
        actor={"id": "u1", "role": "user", "surface": "api"},
        run_id="r1",
        session_id=None,
    )
    telemetry.emit_event.assert_called_once()
    kw = telemetry.emit_event.call_args.kwargs
    assert kw["event_type"] == "execution.gateway.started"
    assert kw["payload"]["run_id"] == "r1"
    assert kw["actor"]["id"] == "u1"
    assert kw["run_id"] == "r1"


def test_tracer_emit_chat_trace_event_missing_context_logs_and_skips() -> None:
    telemetry = MagicMock()
    tracer = Tracer(telemetry)

    class _Req:
        conversation_id = "c"
        user_message_id = "u"
        user_id = "u1"
        org_id = "o1"
        project_id = "p"
        work_item_id = None
        run_id = None

    tracer.emit_chat_trace_event(_Req(), "chat.trace.started", {"status": "started"})
    telemetry.emit_event.assert_not_called()


@pytest.mark.asyncio
async def test_bind_context_async_restores() -> None:
    ct = TraceContext.from_chat_trace(
        {"trace_id": "async-t", "span_id": "async-s", "reply_message_id": "m"}
    )
    assert current_trace_context() is None
    async with bind_context(ct):
        assert current_trace_context().trace_id == "async-t"
    assert current_trace_context() is None


@pytest.mark.asyncio
async def test_async_gather_preserves_distinct_trace_context_per_task() -> None:
    """Concurrent chat replies must not leak trace identifiers across asyncio tasks (GUIDEAI-1191)."""
    telemetry = MagicMock()
    tracer = Tracer(telemetry)

    class _Req:
        conversation_id = "c"
        user_message_id = "u"
        user_id = "u1"
        org_id = "o1"
        project_id = "proj"
        work_item_id = None
        run_id = None

    async def emit_one(suffix: str) -> None:
        ct = TraceContext.from_chat_trace(
            {
                "trace_id": f"tid-{suffix}",
                "span_id": f"sid-{suffix}",
                "reply_message_id": f"mid-{suffix}",
                "project_id": "proj",
            }
        )
        async with bind_context(ct):
            await asyncio.sleep(0)
            tracer.emit_chat_trace_event(_Req(), "chat.trace.started", {"phase": suffix})

    await asyncio.gather(emit_one("a"), emit_one("b"), emit_one("c"))

    assert telemetry.emit_event.call_count == 3
    trace_ids = {c.kwargs["payload"]["trace_id"] for c in telemetry.emit_event.call_args_list}
    assert trace_ids == {"tid-a", "tid-b", "tid-c"}
