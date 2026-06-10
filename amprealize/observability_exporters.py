"""Exporter payload builders for canonical observability records.

Following `behavior_instrument_metrics_pipeline` (Student): this module keeps
exporter-specific shapes derived from the canonical envelope so managed
Datadog/Langfuse profiles do not fork instrumentation at the call sites.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from amprealize.bci_contracts import SerializableDataclass
from amprealize.observability_contracts import (
    GenerationEnvelope,
    ObservabilityRecord,
    ObservabilityRecordKind,
    SpanEnvelope,
    ToolCallEnvelope,
    TraceEnvelope,
)


class ObservabilityExportTarget(str, Enum):
    """Managed exporter targets supported by the canonical envelope."""

    DATADOG = "datadog"
    LANGFUSE_CLOUD = "langfuse_cloud"


@dataclass(frozen=True)
class ObservabilityExporterProfile(SerializableDataclass):
    """Configuration-free contract for one managed exporter target."""

    target: ObservabilityExportTarget
    transport: str
    required_env: Sequence[str] = field(default_factory=tuple)
    exported_sections: Sequence[str] = field(default_factory=tuple)
    record_kinds: Sequence[str] = field(default_factory=tuple)
    notes: str = ""


def observability_exporter_profiles() -> Dict[str, Dict[str, Any]]:
    """Return managed exporter profile contracts without exposing secrets."""

    return {
        ObservabilityExportTarget.DATADOG.value: ObservabilityExporterProfile(
            target=ObservabilityExportTarget.DATADOG,
            transport="otlp_http",
            required_env=[
                "AMPREALIZE_DATADOG_OTLP_ENDPOINT",
                "AMPREALIZE_DATADOG_API_KEY",
            ],
            exported_sections=["spans", "logs", "metrics"],
            record_kinds=[kind.value for kind in ObservabilityRecordKind],
            notes="Exports canonical records as Datadog APM spans, logs, and numeric metrics.",
        ).to_dict(),
        ObservabilityExportTarget.LANGFUSE_CLOUD.value: ObservabilityExporterProfile(
            target=ObservabilityExportTarget.LANGFUSE_CLOUD,
            transport="langfuse_http",
            required_env=[
                "AMPREALIZE_LANGFUSE_PUBLIC_KEY",
                "AMPREALIZE_LANGFUSE_SECRET_KEY",
                "AMPREALIZE_LANGFUSE_HOST",
            ],
            exported_sections=["traces", "observations"],
            record_kinds=[
                ObservabilityRecordKind.TRACE.value,
                ObservabilityRecordKind.SPAN.value,
                ObservabilityRecordKind.GENERATION.value,
                ObservabilityRecordKind.TOOL_CALL.value,
                ObservabilityRecordKind.BEHAVIOR_CANDIDATE.value,
            ],
            notes="Exports trace roots plus LLM generations, spans, tools, and behavior-candidate provenance.",
        ).to_dict(),
    }


def build_datadog_export_payload(records: Iterable[ObservabilityRecord]) -> Dict[str, Any]:
    """Build a Datadog-ready payload from canonical records.

    The return value is intentionally HTTP-client agnostic. Runtime code can send
    the ``spans``, ``logs``, and ``metrics`` sections to Datadog with whichever
    transport is configured for the deployment.
    """

    spans: List[Dict[str, Any]] = []
    logs: List[Dict[str, Any]] = []
    metrics: List[Dict[str, Any]] = []

    for record in records:
        sanitized = record.to_sanitized_payload()
        tags = _datadog_tags(record)
        spans.append(_datadog_span(record, sanitized, tags))
        logs.append(_datadog_log(record, sanitized, tags))
        metrics.extend(_datadog_metrics(record, tags))

    return {
        "target": ObservabilityExportTarget.DATADOG.value,
        "profile": observability_exporter_profiles()[ObservabilityExportTarget.DATADOG.value],
        "spans": spans,
        "logs": logs,
        "metrics": metrics,
    }


def build_langfuse_export_payload(records: Iterable[ObservabilityRecord]) -> Dict[str, Any]:
    """Build a Langfuse-ready payload from canonical records."""

    traces: Dict[str, Dict[str, Any]] = {}
    observations: List[Dict[str, Any]] = []

    for record in records:
        sanitized = record.to_sanitized_payload()
        trace_id = record.correlation.trace_id
        traces.setdefault(trace_id, _langfuse_trace(record, sanitized))

        observation = _langfuse_observation(record, sanitized)
        if observation is not None:
            observations.append(observation)

    return {
        "target": ObservabilityExportTarget.LANGFUSE_CLOUD.value,
        "profile": observability_exporter_profiles()[ObservabilityExportTarget.LANGFUSE_CLOUD.value],
        "traces": list(traces.values()),
        "observations": observations,
    }


def _datadog_span(
    record: ObservabilityRecord,
    sanitized: Mapping[str, Any],
    tags: Sequence[str],
) -> Dict[str, Any]:
    correlation = record.correlation
    span: Dict[str, Any] = {
        "trace_id": correlation.trace_id,
        "span_id": correlation.span_id,
        "parent_span_id": correlation.parent_span_id,
        "name": record.name,
        "service": "amprealize",
        "resource": f"{record.kind.value}:{record.name}",
        "start": record.timestamp,
        "status": record.status.value,
        "tags": list(tags),
        "meta": {
            "record_id": record.record_id,
            "kind": record.kind.value,
            "sensitivity": record.sensitivity.value,
            "correlation": sanitized.get("correlation", {}),
            "attributes": sanitized.get("attributes", {}),
            "payload": sanitized,
        },
    }
    duration_ms = _record_duration_ms(record)
    if duration_ms is not None:
        span["duration_ms"] = duration_ms
    return span


def _datadog_log(
    record: ObservabilityRecord,
    sanitized: Mapping[str, Any],
    tags: Sequence[str],
) -> Dict[str, Any]:
    return {
        "timestamp": record.timestamp,
        "service": "amprealize",
        "status": record.status.value,
        "message": record.name,
        "dd.trace_id": record.correlation.trace_id,
        "dd.span_id": record.correlation.span_id,
        "tags": list(tags),
        "attributes": sanitized,
    }


def _datadog_metrics(
    record: ObservabilityRecord,
    tags: Sequence[str],
) -> List[Dict[str, Any]]:
    base = {
        "timestamp": record.timestamp,
        "tags": list(tags),
    }
    metrics: List[Dict[str, Any]] = [
        {
            **base,
            "name": f"amprealize.observability.{record.kind.value}.count",
            "type": "count",
            "value": 1,
        }
    ]

    duration_ms = _record_duration_ms(record)
    if duration_ms is not None:
        metrics.append(
            {
                **base,
                "name": "amprealize.observability.duration_ms",
                "type": "gauge",
                "value": duration_ms,
            }
        )

    if isinstance(record, GenerationEnvelope):
        for metric_name, value in (
            ("input_tokens", record.input_tokens),
            ("output_tokens", record.output_tokens),
            ("cost_usd", record.cost_usd),
            ("latency_ms", record.latency_ms),
            ("first_token_latency_ms", record.first_token_latency_ms),
        ):
            if value is not None:
                metrics.append(
                    {
                        **base,
                        "name": f"amprealize.observability.generation.{metric_name}",
                        "type": "gauge",
                        "value": value,
                    }
                )

    if isinstance(record, ToolCallEnvelope) and record.elapsed_ms is not None:
        metrics.append(
            {
                **base,
                "name": "amprealize.observability.tool.elapsed_ms",
                "type": "gauge",
                "value": record.elapsed_ms,
            }
        )

    return metrics


def _langfuse_trace(
    record: ObservabilityRecord,
    sanitized: Mapping[str, Any],
) -> Dict[str, Any]:
    correlation = record.correlation
    return {
        "id": correlation.trace_id,
        "name": record.name if record.kind is ObservabilityRecordKind.TRACE else "amprealize.trace",
        "timestamp": record.timestamp,
        "user_id": correlation.actor_id,
        "session_id": correlation.conversation_id or correlation.run_id,
        "metadata": {
            "record_id": record.record_id,
            "project_id": correlation.project_id,
            "work_item_id": correlation.work_item_id,
            "surface": correlation.surface,
            "root_record": sanitized,
        },
    }


def _langfuse_observation(
    record: ObservabilityRecord,
    sanitized: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    if isinstance(record, TraceEnvelope):
        return None

    base: Dict[str, Any] = {
        "id": record.correlation.span_id,
        "trace_id": record.correlation.trace_id,
        "parent_observation_id": record.correlation.parent_span_id,
        "name": record.name,
        "start_time": record.timestamp,
        "metadata": {
            "record_id": record.record_id,
            "kind": record.kind.value,
            "correlation": sanitized.get("correlation", {}),
            "attributes": sanitized.get("attributes", {}),
        },
    }

    if isinstance(record, GenerationEnvelope):
        base.update(
            {
                "type": "GENERATION",
                "model": record.model_id,
                "provider": record.provider,
                "input": record.prompt_summary,
                "output": record.output_summary,
                "usage": {
                    "input_tokens": record.input_tokens,
                    "output_tokens": record.output_tokens,
                    "total_tokens": _total_tokens(record),
                    "cost_usd": record.cost_usd,
                },
                "latency_ms": record.latency_ms,
                "time_to_first_token_ms": record.first_token_latency_ms,
            }
        )
        return base

    if isinstance(record, ToolCallEnvelope):
        base.update(
            {
                "type": "TOOL",
                "tool_name": record.tool_name,
                "input": sanitized.get("input_summary", {}),
                "output": sanitized.get("output_summary", {}),
                "latency_ms": record.elapsed_ms,
            }
        )
        return base

    base["type"] = "SPAN"
    duration_ms = _record_duration_ms(record)
    if duration_ms is not None:
        base["duration_ms"] = duration_ms
    return base


def _datadog_tags(record: ObservabilityRecord) -> List[str]:
    correlation = record.correlation
    tag_values = {
        "kind": record.kind.value,
        "status": record.status.value,
        "sensitivity": record.sensitivity.value,
        "project_id": correlation.project_id,
        "org_id": correlation.org_id,
        "surface": correlation.surface,
        "run_id": correlation.run_id,
        "work_item_id": correlation.work_item_id,
        "model_id": getattr(record, "model_id", None) or correlation.model_id,
    }
    return [f"{key}:{value}" for key, value in tag_values.items() if value]


def _record_duration_ms(record: ObservabilityRecord) -> Optional[float]:
    if isinstance(record, (TraceEnvelope, SpanEnvelope)):
        return record.duration_ms
    if isinstance(record, GenerationEnvelope):
        return record.latency_ms
    if isinstance(record, ToolCallEnvelope):
        return record.elapsed_ms
    return None


def _total_tokens(record: GenerationEnvelope) -> Optional[int]:
    if record.input_tokens is None and record.output_tokens is None:
        return None
    return (record.input_tokens or 0) + (record.output_tokens or 0)


__all__ = [
    "ObservabilityExportTarget",
    "ObservabilityExporterProfile",
    "build_datadog_export_payload",
    "build_langfuse_export_payload",
    "observability_exporter_profiles",
]
