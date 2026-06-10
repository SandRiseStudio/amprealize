"""Trace facade: TraceContext, contextvars propagation, and Tracer with non-fatal sink writes.

Chat paths use :class:`TraceContext` + :func:`attach_trace_context` / :func:`detach_trace_context`
(or :func:`bind_context`) so emitters avoid threading ``chat_trace`` through every call.

Work-item / gateway paths use :meth:`Tracer.emit_execution_gateway_event` and span helpers with
explicit :class:`~amprealize.observability_contracts.ObservabilityCorrelation` (no chat contextvar).

Canonical :class:`~amprealize.observability_contracts.ObservabilityRecord` emission uses
:class:`Tracer` (``observability.record`` telemetry event) for exporter-ready payloads.
"""

from __future__ import annotations

import contextvars
import logging
import uuid
from dataclasses import dataclass, replace
from typing import Any, Dict, Mapping, Optional

from amprealize.execution_observability import sanitize_observability_payload
from amprealize.observability_attributes import merge_otel_into_attributes
from amprealize.observability_contracts import (
    ActionEnvelope,
    EventEnvelope,
    GenerationEnvelope,
    ObservabilityCorrelation,
    ObservabilityRecord,
    ObservabilityRecordKind,
    ObservabilityRecordStatus,
    OutcomeEnvelope,
    ToolCallEnvelope,
    utc_now,
)
from amprealize.telemetry import TelemetryClient

_current_trace_context: contextvars.ContextVar[Optional["TraceContext"]] = contextvars.ContextVar(
    "amprealize_current_trace_context",
    default=None,
)


def _log_warning(message: str, **fields: Any) -> None:
    """Prefer Raze when installed; fall back to stdlib logging."""
    try:
        from raze import RazeLogger

        RazeLogger(service="observability-tracing").warning(message, **fields)
    except Exception:
        logging.getLogger(__name__).warning("%s %s", message, fields)


@dataclass(frozen=True)
class TraceContext:
    """Request-scoped trace identifiers plus the chat ``chat_trace`` payload dict."""

    trace_id: str
    span_id: str
    parent_span_id: Optional[str]
    chat_trace: Dict[str, Any]

    @classmethod
    def from_chat_trace(cls, chat_trace: Mapping[str, Any]) -> "TraceContext":
        data = dict(chat_trace)
        return cls(
            trace_id=str(data.get("trace_id") or ""),
            span_id=str(data.get("span_id") or ""),
            parent_span_id=data.get("parent_span_id"),
            chat_trace=data,
        )

    def child_context(self, span_name: str, **overrides: Any) -> "TraceContext":
        """Derive a child context: new ``span_id``, ``parent_span_id`` = current span."""
        new_span_id = str(
            overrides.pop("span_id", None) or f"ctx:{span_name}:{uuid.uuid4().hex[:12]}"
        )
        return TraceContext(
            trace_id=self.trace_id,
            span_id=new_span_id,
            parent_span_id=self.span_id,
            chat_trace=self.chat_trace,
        )


def current_trace_context() -> Optional[TraceContext]:
    return _current_trace_context.get()


def attach_trace_context(ctx: TraceContext) -> contextvars.Token[Optional[TraceContext]]:
    """Push ``ctx``; return a token for :func:`detach_trace_context`."""
    return _current_trace_context.set(ctx)


def detach_trace_context(token: Optional[contextvars.Token[Optional[TraceContext]]]) -> None:
    """Reset the context var using the token from :func:`attach_trace_context`."""
    if token is not None:
        _current_trace_context.reset(token)


class _BoundTraceContext:
    """Sync and async context manager for trace scope."""

    __slots__ = ("_ctx", "_token")

    def __init__(self, ctx: TraceContext) -> None:
        self._ctx = ctx
        self._token: Optional[contextvars.Token[Optional[TraceContext]]] = None

    def __enter__(self) -> TraceContext:
        self._token = attach_trace_context(self._ctx)
        return self._ctx

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        detach_trace_context(self._token)
        self._token = None
        return None

    async def __aenter__(self) -> TraceContext:
        self._token = attach_trace_context(self._ctx)
        return self._ctx

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        detach_trace_context(self._token)
        self._token = None
        return None


def bind_context(ctx: TraceContext) -> _BoundTraceContext:
    """Return a context manager usable as ``with bind_context(ctx)`` or ``async with bind_context(ctx)``."""
    return _BoundTraceContext(ctx)


def _resolve_chat_trace(explicit: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if explicit is not None:
        return dict(explicit)
    cur = current_trace_context()
    if cur is None:
        return None
    return cur.chat_trace


def correlation_from_trace_context(ctx: TraceContext) -> ObservabilityCorrelation:
    ct = ctx.chat_trace
    return ObservabilityCorrelation(
        trace_id=ctx.trace_id,
        span_id=ctx.span_id,
        parent_span_id=ctx.parent_span_id,
        org_id=ct.get("org_id") if ct.get("org_id") else None,
        project_id=str(ct.get("project_id") or "unknown"),
        conversation_id=ct.get("conversation_id"),
        message_id=ct.get("user_message_id"),
        run_id=ct.get("run_id"),
        work_item_id=ct.get("work_item_id"),
        surface="chat",
    )


class Tracer:
    """Facade for product telemetry (chat, execution gateway) and canonical observability records.

    All sink writes are **non-fatal** (``_safe_call`` / ``_log_warning``). Chat helpers merge
    ``chat_trace`` / correlation from ``contextvars`` where applicable. Gateway / work-item
    lifecycle events use :meth:`emit_execution_gateway_event` with **caller-defined payloads**
    per ``event_type`` (still sanitized at emit).
    """

    def __init__(self, telemetry: Optional[TelemetryClient], *, service_name: str = "amprealize") -> None:
        self._telemetry = telemetry
        self._service_name = service_name

    def _safe_call(self, label: str, fn: Any) -> None:
        try:
            fn()
        except Exception as exc:
            _log_warning("observability_tracing_sink_failed", label=label, error=str(exc))

    def _emit_telemetry(
        self,
        *,
        event_type: str,
        payload: Dict[str, Any],
        actor: Optional[Dict[str, str]] = None,
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        if not self._telemetry:
            return

        def _go() -> None:
            self._telemetry.emit_event(
                event_type=event_type,
                payload=sanitize_observability_payload(payload),
                actor=actor,
                run_id=run_id,
                session_id=session_id,
            )

        self._safe_call(f"emit_event:{event_type}", _go)

    def _base_chat_payload(self, request: Any) -> Dict[str, Any]:
        return {
            "conversation_id": request.conversation_id,
            "user_message_id": request.user_message_id,
            "user_id": request.user_id,
            "org_id": request.org_id,
            "project_id": request.project_id,
            "work_item_id": request.work_item_id,
            "run_id": request.run_id,
        }

    def _chat_actor(self, request: Any) -> Dict[str, str]:
        return {
            "id": request.user_id,
            "role": "user",
            "surface": "chat",
        }

    def emit_chat_event(
        self,
        request: Any,
        event_type: str,
        payload: Dict[str, Any],
    ) -> None:
        """Emit a chat-domain telemetry event (no trace_id merge)."""
        merged = {**self._base_chat_payload(request), **payload}
        self._emit_telemetry(
            event_type=event_type,
            payload=merged,
            actor=self._chat_actor(request),
            run_id=request.run_id,
            session_id=request.conversation_id,
        )

    def emit_chat_trace_event(
        self,
        request: Any,
        event_type: str,
        payload: Dict[str, Any],
        chat_trace: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """Emit an event that includes ``trace_id`` / ``span_id`` / ``chat_trace``."""
        ct = _resolve_chat_trace(chat_trace)
        if ct is None:
            _log_warning("observability_tracing_missing_chat_trace", event_type=event_type)
            return
        merged = {
            **self._base_chat_payload(request),
            "trace_id": ct.get("trace_id"),
            "span_id": ct.get("span_id"),
            "parent_span_id": ct.get("parent_span_id"),
            "chat_trace": ct,
            **payload,
        }
        self._emit_telemetry(
            event_type=event_type,
            payload=merged,
            actor=self._chat_actor(request),
            run_id=request.run_id,
            session_id=request.conversation_id,
        )

    def emit_chat_span_completed(
        self,
        request: Any,
        *,
        span_name: str,
        started_at: float,
        attributes: Optional[Dict[str, Any]] = None,
        chat_trace: Optional[Mapping[str, Any]] = None,
    ) -> None:
        import time as _time

        ct = _resolve_chat_trace(chat_trace)
        if ct is None:
            _log_warning(
                "observability_tracing_missing_chat_trace",
                event_type="chat.span.completed",
                span_name=span_name,
            )
            return
        reply_mid = ct.get("reply_message_id")
        self.emit_chat_event(
            request,
            "chat.span.completed",
            {
                "trace_id": ct.get("trace_id"),
                "span_id": f"chat:{span_name}:{reply_mid}",
                "parent_span_id": ct.get("span_id"),
                "span_name": span_name,
                "status": "completed",
                "latency_ms": (_time.monotonic() - started_at) * 1000,
                "chat_trace": ct,
                "attributes": attributes or {},
            },
        )

    def emit_chat_span_failed(
        self,
        request: Any,
        *,
        span_name: str,
        started_at: float,
        error: BaseException,
        failure_metadata: Dict[str, Any],
        chat_trace: Optional[Mapping[str, Any]] = None,
    ) -> None:
        import time as _time

        ct = _resolve_chat_trace(chat_trace)
        if ct is None:
            _log_warning(
                "observability_tracing_missing_chat_trace",
                event_type="chat.span.failed",
                span_name=span_name,
            )
            return
        reply_mid = ct.get("reply_message_id")
        self.emit_chat_event(
            request,
            "chat.span.failed",
            {
                "trace_id": ct.get("trace_id"),
                "span_id": f"chat:{span_name}:{reply_mid}",
                "parent_span_id": ct.get("span_id"),
                "span_name": span_name,
                "status": "failed",
                "latency_ms": (_time.monotonic() - started_at) * 1000,
                "chat_trace": ct,
                "error": str(error),
                **failure_metadata,
            },
        )

    def emit_execution_gateway_event(
        self,
        *,
        event_type: str,
        payload: Dict[str, Any],
        actor: Optional[Dict[str, str]] = None,
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """Emit work-item / gateway / policy-audit style product telemetry.

        ``payload`` is **event-specific** (e.g. ``execution.gateway.started`` vs
        ``policy.composition.*``); this method does not enforce a fixed schema beyond
        :func:`~amprealize.execution_observability.sanitize_observability_payload`.
        Pass ``actor`` when the event is attributable; omit to use the sink's default actor.
        """
        self._emit_telemetry(
            event_type=event_type,
            payload=payload,
            actor=actor,
            run_id=run_id,
            session_id=session_id,
        )

    def _resolve_correlation(
        self, correlation: Optional[ObservabilityCorrelation]
    ) -> Optional[ObservabilityCorrelation]:
        if correlation is not None:
            return correlation
        ctx = current_trace_context()
        if ctx is None:
            return None
        return correlation_from_trace_context(ctx)

    def _emit_canonical_record(self, record: ObservabilityRecord) -> None:
        if not self._telemetry:
            return
        missing = record.missing_required_correlation()
        if missing:
            _log_warning(
                "observability_tracing_incomplete_correlation",
                missing=",".join(missing),
                kind=record.kind.value,
                name=record.name,
            )
        merged_attrs = merge_otel_into_attributes(record, dict(record.attributes))
        record = replace(record, attributes=merged_attrs)

        def _go() -> None:
            self._telemetry.emit_event(
                event_type="observability.record",
                payload=sanitize_observability_payload({"record": record.to_dict()}),
                actor={"id": "system", "role": "service", "surface": "internal"},
                run_id=record.correlation.run_id,
                session_id=record.correlation.conversation_id,
            )

        self._safe_call("observability.record", _go)

    def start_execution_span(
        self,
        *,
        operation_name: str,
        correlation: Optional[ObservabilityCorrelation] = None,
        run_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> Any:
        corr = self._resolve_correlation(correlation)
        if not self._telemetry or corr is None:
            return None

        def _go() -> Any:
            fn = getattr(self._telemetry, "start_execution_span", None)
            if not callable(fn):
                return None
            return fn(
                trace_id=corr.trace_id,
                span_id=corr.span_id,
                operation_name=operation_name,
                service_name=self._service_name,
                parent_span_id=corr.parent_span_id,
                run_id=run_id or corr.run_id,
                attributes=dict(attributes or {}),
            )

        try:
            return _go()
        except Exception as exc:
            _log_warning(
                "observability_tracing_start_span_failed",
                operation_name=operation_name,
                error=str(exc),
            )
            return None

    def end_execution_span(self, span: Any, **kwargs: Any) -> None:
        if not self._telemetry or span is None:
            return

        def _go() -> None:
            self._telemetry.end_execution_span(span, **kwargs)

        self._safe_call("end_execution_span", _go)

    def record_completed_execution_trace(self, **kwargs: Any) -> None:
        if not self._telemetry:
            return

        def _go() -> None:
            self._telemetry.record_completed_execution_trace(**kwargs)

        self._safe_call("record_completed_execution_trace", _go)

    def record_event(
        self,
        *,
        name: str,
        correlation: Optional[ObservabilityCorrelation] = None,
        status: ObservabilityRecordStatus = ObservabilityRecordStatus.COMPLETED,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        corr = self._resolve_correlation(correlation)
        if corr is None:
            return
        record = EventEnvelope(
            record_id=str(uuid.uuid4()),
            kind=ObservabilityRecordKind.EVENT,
            name=name,
            timestamp=utc_now(),
            correlation=corr,
            status=status,
            attributes=dict(attributes or {}),
        )
        self._emit_canonical_record(record)

    def record_generation(
        self,
        *,
        name: str,
        correlation: Optional[ObservabilityCorrelation] = None,
        provider: Optional[str] = None,
        model_id: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        cost_usd: Optional[float] = None,
        latency_ms: Optional[float] = None,
        first_token_latency_ms: Optional[float] = None,
        prompt_summary: Optional[str] = None,
        output_summary: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        corr = self._resolve_correlation(correlation)
        if corr is None:
            return
        record = GenerationEnvelope(
            record_id=str(uuid.uuid4()),
            kind=ObservabilityRecordKind.GENERATION,
            name=name,
            timestamp=utc_now(),
            correlation=corr,
            attributes=dict(attributes or {}),
            provider=provider,
            model_id=model_id or corr.model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            first_token_latency_ms=first_token_latency_ms,
            prompt_summary=prompt_summary,
            output_summary=output_summary,
        )
        self._emit_canonical_record(record)

    def record_tool_call(
        self,
        *,
        name: str,
        correlation: Optional[ObservabilityCorrelation] = None,
        tool_name: Optional[str] = None,
        call_id: Optional[str] = None,
        elapsed_ms: Optional[float] = None,
        input_summary: Optional[Dict[str, Any]] = None,
        output_summary: Optional[Dict[str, Any]] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        corr = self._resolve_correlation(correlation)
        if corr is None:
            return
        record = ToolCallEnvelope(
            record_id=str(uuid.uuid4()),
            kind=ObservabilityRecordKind.TOOL_CALL,
            name=name,
            timestamp=utc_now(),
            correlation=corr,
            attributes=dict(attributes or {}),
            tool_name=tool_name,
            call_id=call_id,
            elapsed_ms=elapsed_ms,
            input_summary=dict(input_summary or {}),
            output_summary=dict(output_summary or {}),
        )
        self._emit_canonical_record(record)

    def record_action(
        self,
        *,
        name: str,
        correlation: Optional[ObservabilityCorrelation] = None,
        action_type: Optional[str] = None,
        target_resource_type: Optional[str] = None,
        target_resource_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        corr = self._resolve_correlation(correlation)
        if corr is None:
            return
        record = ActionEnvelope(
            record_id=str(uuid.uuid4()),
            kind=ObservabilityRecordKind.ACTION,
            name=name,
            timestamp=utc_now(),
            correlation=corr,
            attributes=dict(attributes or {}),
            action_type=action_type,
            target_resource_type=target_resource_type,
            target_resource_id=target_resource_id,
        )
        self._emit_canonical_record(record)

    def record_outcome(
        self,
        *,
        name: str,
        correlation: Optional[ObservabilityCorrelation] = None,
        outcome_type: Optional[str] = None,
        outcome_ref: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        corr = self._resolve_correlation(correlation)
        if corr is None:
            return
        record = OutcomeEnvelope(
            record_id=str(uuid.uuid4()),
            kind=ObservabilityRecordKind.OUTCOME,
            name=name,
            timestamp=utc_now(),
            correlation=corr,
            attributes=dict(attributes or {}),
            outcome_type=outcome_type,
            outcome_ref=outcome_ref,
            resource_type=resource_type,
            resource_id=resource_id,
        )
        self._emit_canonical_record(record)


__all__ = [
    "TraceContext",
    "Tracer",
    "attach_trace_context",
    "bind_context",
    "correlation_from_trace_context",
    "current_trace_context",
    "detach_trace_context",
]
