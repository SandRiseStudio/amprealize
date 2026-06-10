"""Canonical observability trace envelope contracts.

Following `behavior_instrument_metrics_pipeline` (Student): these records define
the shared schema that chat, execution, storage, exporter, and behavior-mining
surfaces can target without coupling to one backend.

Normative documentation: ``docs/contracts/CANONICAL_TRACE_CONTRACT.md`` (capture
policy, projection matrix, documented gaps). JSON Schema (wire / exporter
validation): ``docs/contracts/schemas/canonical_observability_envelope.schema.json``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence

from amprealize.bci_contracts import SerializableDataclass
from amprealize.execution_observability import (
    ExecutionObservabilityContext,
    sanitize_observability_payload,
)


class ObservabilityRecordKind(str, Enum):
    """Record types supported by the canonical observability envelope."""

    TRACE = "trace"
    SPAN = "span"
    EVENT = "event"
    GENERATION = "generation"
    TOOL_CALL = "tool_call"
    ACTION = "action"
    ARTIFACT = "artifact"
    BEHAVIOR_CANDIDATE = "behavior_candidate"
    OUTCOME = "outcome"


class ObservabilityRecordStatus(str, Enum):
    """Lifecycle state for records that describe work."""

    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    DENIED = "denied"
    SKIPPED = "skipped"


class ObservabilitySensitivity(str, Enum):
    """Sensitivity classes used by retention and access-control policies."""

    METADATA = "metadata"
    SUMMARY = "summary"
    RESTRICTED = "restricted"
    RAW = "raw"


class ObservabilityDataClass(str, Enum):
    """Concrete data classes used by retention and purge policies."""

    METADATA_TRACE = "metadata_trace"
    SUMMARY = "summary"
    HASH = "hash"
    BEHAVIOR_MINING_FEATURE = "behavior_mining_feature"
    RAW_PROMPT = "raw_prompt"
    RAW_RESPONSE = "raw_response"
    TOOL_ARGS = "tool_args"
    OUTPUT_PREVIEW = "output_preview"
    COMMAND_OUTPUT = "command_output"
    FILE_DIFF = "file_diff"


class ObservabilityBackendProfile(str, Enum):
    """Deployment profiles that consume the canonical envelope."""

    OSS = "oss"
    SELF_HOSTED_ENTERPRISE = "self_hosted_enterprise"
    MANAGED_ENTERPRISE = "managed_enterprise"


class ObservabilityDashboardSource(str, Enum):
    """Dashboard surfaces supported by observability storage profiles."""

    METABASE = "metabase"
    LOOKER = "looker"


@dataclass(frozen=True)
class ObservabilityRetentionRule(SerializableDataclass):
    """Retention and access policy for one observability data class."""

    data_class: ObservabilityDataClass
    sensitivity: ObservabilitySensitivity
    default_retention_days: int
    max_retention_days: int
    archive_years: int = 0
    allowed_access_tiers: Sequence[str] = field(default_factory=tuple)
    purge_action: str = "delete"
    anonymize_on_delete: bool = False
    notes: str = ""


@dataclass(frozen=True)
class ObservabilityDashboardDataset(SerializableDataclass):
    """Queryable source used by dashboard cards and drilldowns."""

    name: str
    source: str
    description: str
    grain: str
    dimensions: Sequence[str] = field(default_factory=tuple)
    measures: Sequence[str] = field(default_factory=tuple)
    drilldown_fields: Sequence[str] = field(default_factory=tuple)
    access_tier: str = "data_analyst"


@dataclass(frozen=True)
class ObservabilityDashboardProfile(SerializableDataclass):
    """Dashboard source profile for self-hosted and managed deployments."""

    dashboard: ObservabilityDashboardSource
    backend_profile: ObservabilityBackendProfile
    connection_env: Sequence[str] = field(default_factory=tuple)
    datasets: Sequence[ObservabilityDashboardDataset] = field(default_factory=tuple)
    trace_drilldown_url_template: str = ""
    notes: str = ""


@dataclass(frozen=True)
class ObservabilityCorrelation(SerializableDataclass):
    """Shared correlation fields for chat and agent execution traces."""

    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    org_id: Optional[str] = None
    project_id: Optional[str] = None
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    run_id: Optional[str] = None
    cycle_id: Optional[str] = None
    work_item_id: Optional[str] = None
    action_id: Optional[str] = None
    tool_call_id: Optional[str] = None
    llm_call_id: Optional[str] = None
    behavior_id: Optional[str] = None
    actor_id: Optional[str] = None
    actor_role: Optional[str] = None
    surface: Optional[str] = None
    permission_action: Optional[str] = None
    model_id: Optional[str] = None
    queue_job_id: Optional[str] = None
    phase: Optional[str] = None

    @classmethod
    def from_execution_context(
        cls,
        context: ExecutionObservabilityContext,
        *,
        trace_id: str,
        span_id: str,
        parent_span_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        actor_role: Optional[str] = None,
        phase: Optional[str] = None,
    ) -> "ObservabilityCorrelation":
        """Build canonical correlation from the execution context used today."""

        return cls(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            org_id=context.org_id,
            project_id=context.project_id,
            conversation_id=context.conversation_id,
            message_id=context.message_id,
            run_id=context.run_id,
            cycle_id=context.cycle_id,
            work_item_id=context.work_item_id,
            actor_id=actor_id,
            actor_role=actor_role,
            surface=context.surface,
            model_id=context.model_id,
            queue_job_id=context.queue_job_id,
            phase=phase,
        )


@dataclass(frozen=True)
class ObservabilityRecord(SerializableDataclass):
    """Base envelope shared by every canonical observability record."""

    record_id: str
    kind: ObservabilityRecordKind
    name: str
    timestamp: str
    correlation: ObservabilityCorrelation
    status: ObservabilityRecordStatus = ObservabilityRecordStatus.COMPLETED
    sensitivity: ObservabilitySensitivity = ObservabilitySensitivity.METADATA
    attributes: Dict[str, Any] = field(default_factory=dict)

    def missing_required_correlation(self) -> List[str]:
        """Return required correlation fields missing for this record kind."""

        correlation = self.correlation.to_dict()
        return [
            field_name
            for field_name in _required_correlation_fields(self.kind)
            if not correlation.get(field_name)
        ]

    def to_sanitized_payload(self) -> Dict[str, Any]:
        """Return a telemetry/exporter-safe payload representation."""

        return sanitize_observability_payload(self.to_dict())


@dataclass(frozen=True)
class TraceEnvelope(ObservabilityRecord):
    """Root trace for a chat reply, execution run, or behavior-mining flow."""

    ended_at: Optional[str] = None
    duration_ms: Optional[float] = None


@dataclass(frozen=True)
class SpanEnvelope(ObservabilityRecord):
    """Timed child span for route, context, generation, tool, or phase work."""

    duration_ms: Optional[float] = None


@dataclass(frozen=True)
class EventEnvelope(ObservabilityRecord):
    """Point-in-time event attached to a trace/span."""


@dataclass(frozen=True)
class GenerationEnvelope(ObservabilityRecord):
    """LLM generation record compatible with Langfuse-style exports."""

    provider: Optional[str] = None
    model_id: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    latency_ms: Optional[float] = None
    first_token_latency_ms: Optional[float] = None
    prompt_summary: Optional[str] = None
    output_summary: Optional[str] = None


@dataclass(frozen=True)
class ToolCallEnvelope(ObservabilityRecord):
    """Tool-call record for MCP, platform actions, and execution tools."""

    tool_name: Optional[str] = None
    call_id: Optional[str] = None
    elapsed_ms: Optional[float] = None
    input_summary: Dict[str, Any] = field(default_factory=dict)
    output_summary: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionEnvelope(ObservabilityRecord):
    """Governed platform or replay action record."""

    action_type: Optional[str] = None
    target_resource_type: Optional[str] = None
    target_resource_id: Optional[str] = None


@dataclass(frozen=True)
class ArtifactEnvelope(ObservabilityRecord):
    """Artifact emitted by chat, execution, or behavior workflows."""

    artifact_type: Optional[str] = None
    artifact_id: Optional[str] = None
    uri: Optional[str] = None


@dataclass(frozen=True)
class BehaviorCandidateEnvelope(ObservabilityRecord):
    """Behavior candidate provenance record derived from trace analysis."""

    candidate_id: Optional[str] = None
    source_trace_ids: Sequence[str] = field(default_factory=tuple)
    confidence: Optional[float] = None


@dataclass(frozen=True)
class OutcomeEnvelope(ObservabilityRecord):
    """Business outcome separated from performance telemetry."""

    outcome_type: Optional[str] = None
    outcome_ref: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None


def utc_now() -> str:
    """Return the canonical timestamp format used by observability records."""

    return datetime.now(timezone.utc).isoformat()


def canonical_trace_examples() -> Dict[str, Dict[str, Any]]:
    """Return compact examples for every canonical record kind."""

    correlation = ObservabilityCorrelation(
        trace_id="trace-chat-run-1",
        span_id="span-root",
        org_id="org-1",
        project_id="proj-1",
        conversation_id="conv-1",
        message_id="msg-1",
        run_id="run-1",
        cycle_id="cycle-1",
        work_item_id="guideai-1091",
        actor_id="user-1",
        actor_role="Student",
        surface="chat",
        model_id="gpt-example",
    )
    timestamp = "2026-04-28T00:00:00+00:00"
    records: Iterable[ObservabilityRecord] = (
        TraceEnvelope(
            record_id="trace-record-1",
            kind=ObservabilityRecordKind.TRACE,
            name="chat.execution",
            timestamp=timestamp,
            correlation=correlation,
        ),
        SpanEnvelope(
            record_id="span-record-1",
            kind=ObservabilityRecordKind.SPAN,
            name="chat.routing",
            timestamp=timestamp,
            correlation=correlation,
            duration_ms=12.5,
        ),
        EventEnvelope(
            record_id="event-record-1",
            kind=ObservabilityRecordKind.EVENT,
            name="execution.gateway.started",
            timestamp=timestamp,
            correlation=correlation,
        ),
        GenerationEnvelope(
            record_id="generation-record-1",
            kind=ObservabilityRecordKind.GENERATION,
            name="llm.generation",
            timestamp=timestamp,
            correlation=correlation,
            provider="openai",
            model_id="gpt-example",
            input_tokens=100,
            output_tokens=40,
        ),
        ToolCallEnvelope(
            record_id="tool-record-1",
            kind=ObservabilityRecordKind.TOOL_CALL,
            name="tool.workitems_update",
            timestamp=timestamp,
            correlation=correlation,
            tool_name="workitems_update",
            call_id="tool-call-1",
        ),
        ActionEnvelope(
            record_id="action-record-1",
            kind=ObservabilityRecordKind.ACTION,
            name="work_item.update",
            timestamp=timestamp,
            correlation=correlation,
            action_type="work_item.update",
            target_resource_type="work_item",
            target_resource_id="guideai-1091",
        ),
        ArtifactEnvelope(
            record_id="artifact-record-1",
            kind=ObservabilityRecordKind.ARTIFACT,
            name="plan.artifact",
            timestamp=timestamp,
            correlation=correlation,
            artifact_type="plan",
            artifact_id="plan-1",
        ),
        BehaviorCandidateEnvelope(
            record_id="candidate-record-1",
            kind=ObservabilityRecordKind.BEHAVIOR_CANDIDATE,
            name="reflection.candidate",
            timestamp=timestamp,
            correlation=correlation,
            candidate_id="candidate-1",
            source_trace_ids=["trace-chat-run-1"],
            confidence=0.82,
        ),
        OutcomeEnvelope(
            record_id="outcome-record-1",
            kind=ObservabilityRecordKind.OUTCOME,
            name="work_item.created",
            timestamp=timestamp,
            correlation=correlation,
            outcome_type="created_resource",
            resource_type="work_item",
            resource_id="guideai-1092",
        ),
    )
    return {record.kind.value: record.to_dict() for record in records}


def observability_backend_targets() -> Dict[str, Dict[str, Any]]:
    """Return the tested profile matrix for canonical trace records."""

    record_kinds = [kind.value for kind in ObservabilityRecordKind]
    timescale_schema = observability_timescale_schema()
    dashboard_sources = observability_dashboard_sources()
    return {
        ObservabilityBackendProfile.OSS.value: {
            "primary_store": "postgres",
            "dashboard": "local_ui",
            "llm_trace_export": "disabled",
            "record_kinds": record_kinds,
            "notes": "Local and OSS installs keep canonical records in Postgres-compatible telemetry tables.",
        },
        ObservabilityBackendProfile.SELF_HOSTED_ENTERPRISE.value: {
            "primary_store": "timescale_postgres",
            "search_store": "opensearch_optional",
            "dashboard": "metabase",
            "llm_trace_export": "self_hosted_langfuse_optional",
            "record_kinds": record_kinds,
            "tables": timescale_schema["tables"],
            "views": timescale_schema["views"],
            "dashboard_sources": [ObservabilityDashboardSource.METABASE.value],
            "dashboard_datasets": [
                dataset["name"]
                for dataset in dashboard_sources[ObservabilityDashboardSource.METABASE.value][
                    "datasets"
                ]
            ],
            "notes": "Self-hosted enterprise keeps the canonical envelope in Timescale/Postgres and may project searchable summaries to OpenSearch.",
        },
        ObservabilityBackendProfile.MANAGED_ENTERPRISE.value: {
            "primary_store": "enterprise_warehouse",
            "trace_export": "datadog",
            "llm_trace_export": "langfuse_cloud",
            "dashboard": "looker",
            "record_kinds": record_kinds,
            "dashboard_sources": [ObservabilityDashboardSource.LOOKER.value],
            "dashboard_datasets": [
                dataset["name"]
                for dataset in dashboard_sources[ObservabilityDashboardSource.LOOKER.value][
                    "datasets"
                ]
            ],
            "notes": "Managed enterprise exports the same canonical envelope to Datadog, Langfuse Cloud, and warehouse-backed Looker models.",
        },
    }


def observability_timescale_schema() -> Dict[str, Any]:
    """Return the self-hosted Timescale/Postgres storage contract."""

    return {
        "schema": "public",
        "hypertables": ["observability_records"],
        "tables": [
            "observability_records",
            "observability_generations",
            "observability_tool_calls",
            "observability_actions",
            "observability_outcomes",
            "observability_retention_policies",
        ],
        "views": [
            "observability_trace_summary",
            "observability_generation_metrics",
            "observability_tool_performance",
            "observability_business_outcomes",
            "observability_behavior_candidate_lifecycle",
            "observability_span_tree",
            "observability_run_summary",
            "observability_conversation_summary",
        ],
        "record_table": {
            "primary_key": ["record_id", "record_timestamp"],
            "required_columns": [
                "record_id",
                "record_timestamp",
                "kind",
                "name",
                "status",
                "sensitivity",
                "trace_id",
                "span_id",
                "project_id",
                "surface",
                "correlation",
                "attributes",
                "payload",
                "data_class",
                "retention_until",
            ],
        },
        "projection_tables": {
            "generation": "observability_generations",
            "tool_call": "observability_tool_calls",
            "action": "observability_actions",
            "outcome": "observability_outcomes",
        },
        "dashboard_profile": "metabase",
        "migration_revision": "20260505_observability_analytics",
    }


def observability_dashboard_sources() -> Dict[str, Dict[str, Any]]:
    """Return dashboard source contracts for Metabase and Looker."""

    metabase_datasets = [
        ObservabilityDashboardDataset(
            name="trace_summary",
            source="observability_trace_summary",
            description="Trace-level rollup for chat, execution, and behavior-mining drilldowns.",
            grain="trace_id",
            dimensions=(
                "trace_id",
                "run_id",
                "work_item_id",
                "conversation_id",
                "surface",
                "project_id",
            ),
            measures=(
                "record_count",
                "failed_record_count",
                "generation_count",
                "tool_call_count",
            ),
            drilldown_fields=("trace_id", "run_id", "work_item_id", "conversation_id"),
        ),
        ObservabilityDashboardDataset(
            name="generation_metrics",
            source="observability_generation_metrics",
            description="Hourly LLM volume, token, cost, latency, and first-token latency metrics.",
            grain="bucket, provider, model_id, status",
            dimensions=("bucket", "provider", "model_id", "status"),
            measures=(
                "generation_count",
                "input_tokens",
                "output_tokens",
                "cost_usd",
                "avg_latency_ms",
                "avg_first_token_latency_ms",
            ),
            drilldown_fields=("provider", "model_id", "status"),
        ),
        ObservabilityDashboardDataset(
            name="tool_performance",
            source="observability_tool_performance",
            description="Hourly MCP/platform/execution tool latency and failure aggregates.",
            grain="bucket, tool_name, status",
            dimensions=("bucket", "tool_name", "status"),
            measures=("call_count", "avg_elapsed_ms", "failed_count"),
            drilldown_fields=("tool_name", "status"),
        ),
        ObservabilityDashboardDataset(
            name="business_outcomes",
            source="observability_business_outcomes",
            description="Daily business outcomes separated from performance telemetry.",
            grain="bucket, outcome_type, resource_type, status",
            dimensions=("bucket", "outcome_type", "resource_type", "status"),
            measures=("outcome_count",),
            drilldown_fields=("outcome_type", "resource_type", "status"),
        ),
        ObservabilityDashboardDataset(
            name="behavior_candidate_lifecycle",
            source="observability_behavior_candidate_lifecycle",
            description="Hourly behavior-candidate extraction, approval, rejection, token savings, and decay metrics.",
            grain="bucket, reviewer_role, rejection_reason",
            dimensions=("bucket", "reviewer_role", "rejection_reason"),
            measures=(
                "candidate_extracted_count",
                "candidate_approved_count",
                "candidate_rejected_count",
                "approval_rate",
                "estimated_token_savings",
                "decayed_behavior_count",
            ),
            drilldown_fields=("reviewer_role", "rejection_reason"),
        ),
        ObservabilityDashboardDataset(
            name="span_tree",
            source="observability_span_tree",
            description="Recursive span hierarchy for trace drilldown (kind=span rows linked by parent_span_id).",
            grain="trace_id, span_id",
            dimensions=("trace_id", "span_id", "parent_span_id", "depth", "project_id", "status"),
            measures=("record_id",),
            drilldown_fields=("trace_id", "span_id", "parent_span_id"),
        ),
        ObservabilityDashboardDataset(
            name="run_summary",
            source="observability_run_summary",
            description="Per-run rollup of observability records for execution dashboards.",
            grain="run_id",
            dimensions=("run_id", "project_id", "work_item_id", "surface", "primary_trace_id"),
            measures=(
                "record_count",
                "failed_record_count",
                "generation_count",
                "tool_call_count",
                "span_count",
            ),
            drilldown_fields=("run_id", "work_item_id", "primary_trace_id"),
        ),
        ObservabilityDashboardDataset(
            name="conversation_summary",
            source="observability_conversation_summary",
            description="Per-conversation session rollup for chat observability.",
            grain="conversation_id",
            dimensions=("conversation_id", "project_id", "surface"),
            measures=("record_count", "trace_count", "generation_count", "tool_call_count"),
            drilldown_fields=("conversation_id", "project_id"),
        ),
    ]

    looker_datasets = [
        ObservabilityDashboardDataset(
            name="observability_trace_summary",
            source="enterprise_warehouse.observability_trace_summary",
            description="Warehouse-mode trace rollup with Datadog and Langfuse drilldown links.",
            grain="trace_id",
            dimensions=(
                "trace_id",
                "run_id",
                "work_item_id",
                "conversation_id",
                "surface",
                "project_id",
                "datadog_trace_url",
                "langfuse_trace_url",
            ),
            measures=(
                "record_count",
                "failed_record_count",
                "generation_count",
                "tool_call_count",
            ),
            drilldown_fields=(
                "trace_id",
                "run_id",
                "work_item_id",
                "datadog_trace_url",
                "langfuse_trace_url",
            ),
        ),
        ObservabilityDashboardDataset(
            name="observability_generation_metrics",
            source="enterprise_warehouse.observability_generation_metrics",
            description="Warehouse projection for managed LLM usage, cost, and latency reporting.",
            grain="bucket, provider, model_id, status",
            dimensions=("bucket", "provider", "model_id", "status"),
            measures=(
                "generation_count",
                "input_tokens",
                "output_tokens",
                "cost_usd",
                "avg_latency_ms",
                "avg_first_token_latency_ms",
            ),
            drilldown_fields=("provider", "model_id", "status"),
        ),
        ObservabilityDashboardDataset(
            name="observability_tool_performance",
            source="enterprise_warehouse.observability_tool_performance",
            description="Warehouse projection for managed tool latency, denial, and failure analysis.",
            grain="bucket, tool_name, status",
            dimensions=("bucket", "tool_name", "status"),
            measures=("call_count", "avg_elapsed_ms", "failed_count"),
            drilldown_fields=("tool_name", "status"),
        ),
        ObservabilityDashboardDataset(
            name="observability_business_outcomes",
            source="enterprise_warehouse.observability_business_outcomes",
            description="Warehouse projection for resources and outcomes produced by agents and tools.",
            grain="bucket, outcome_type, resource_type, status",
            dimensions=("bucket", "outcome_type", "resource_type", "status"),
            measures=("outcome_count",),
            drilldown_fields=("outcome_type", "resource_type", "status"),
        ),
        ObservabilityDashboardDataset(
            name="observability_behavior_candidate_lifecycle",
            source="enterprise_warehouse.observability_behavior_candidate_lifecycle",
            description="Warehouse projection for behavior-candidate extraction rate, approval rate, rejection reasons, token savings, and decay.",
            grain="bucket, reviewer_role, rejection_reason",
            dimensions=("bucket", "reviewer_role", "rejection_reason"),
            measures=(
                "candidate_extracted_count",
                "candidate_approved_count",
                "candidate_rejected_count",
                "approval_rate",
                "estimated_token_savings",
                "decayed_behavior_count",
            ),
            drilldown_fields=("reviewer_role", "rejection_reason"),
        ),
        ObservabilityDashboardDataset(
            name="observability_span_tree",
            source="enterprise_warehouse.observability_span_tree",
            description="Warehouse span hierarchy view aligned with self-hosted observability_span_tree.",
            grain="trace_id, span_id",
            dimensions=("trace_id", "span_id", "parent_span_id", "depth", "project_id"),
            measures=("record_id",),
            drilldown_fields=("trace_id", "span_id"),
        ),
        ObservabilityDashboardDataset(
            name="observability_run_summary",
            source="enterprise_warehouse.observability_run_summary",
            description="Warehouse per-run rollup aligned with self-hosted observability_run_summary.",
            grain="run_id",
            dimensions=("run_id", "project_id", "work_item_id", "surface"),
            measures=(
                "record_count",
                "failed_record_count",
                "generation_count",
                "tool_call_count",
                "span_count",
            ),
            drilldown_fields=("run_id", "work_item_id"),
        ),
        ObservabilityDashboardDataset(
            name="observability_conversation_summary",
            source="enterprise_warehouse.observability_conversation_summary",
            description="Warehouse per-conversation rollup aligned with self-hosted observability_conversation_summary.",
            grain="conversation_id",
            dimensions=("conversation_id", "project_id", "surface"),
            measures=("record_count", "trace_count", "generation_count", "tool_call_count"),
            drilldown_fields=("conversation_id",),
        ),
    ]

    return {
        ObservabilityDashboardSource.METABASE.value: ObservabilityDashboardProfile(
            dashboard=ObservabilityDashboardSource.METABASE,
            backend_profile=ObservabilityBackendProfile.SELF_HOSTED_ENTERPRISE,
            connection_env=(
                "AMPREALIZE_TELEMETRY_PG_DSN",
                "METABASE_URL",
                "METABASE_USERNAME",
            ),
            datasets=metabase_datasets,
            trace_drilldown_url_template="/work-items/{work_item_id}?trace_id={trace_id}",
            notes="Metabase reads Timescale/Postgres views directly for self-hosted dashboards.",
        ).to_dict(),
        ObservabilityDashboardSource.LOOKER.value: ObservabilityDashboardProfile(
            dashboard=ObservabilityDashboardSource.LOOKER,
            backend_profile=ObservabilityBackendProfile.MANAGED_ENTERPRISE,
            connection_env=(
                "AMPREALIZE_ENTERPRISE_WAREHOUSE_DSN",
                "LOOKER_MODEL",
            ),
            datasets=looker_datasets,
            trace_drilldown_url_template=(
                "https://app.datadoghq.com/apm/trace/{trace_id}"
            ),
            notes="Looker reads warehouse projections enriched with Datadog and Langfuse trace links.",
        ).to_dict(),
    }


def observability_retention_rules() -> Dict[str, Dict[str, Any]]:
    """Return retention and sensitivity classes for canonical observability data."""

    rules = (
        ObservabilityRetentionRule(
            data_class=ObservabilityDataClass.METADATA_TRACE,
            sensitivity=ObservabilitySensitivity.METADATA,
            default_retention_days=365 * 3,
            max_retention_days=365 * 7,
            archive_years=7,
            allowed_access_tiers=("viewer", "data_analyst", "admin", "compliance"),
            purge_action="anonymize_actor",
            anonymize_on_delete=True,
            notes="Trace/span/event metadata, correlation IDs, statuses, timings, token counts, costs, and aggregate dimensions.",
        ),
        ObservabilityRetentionRule(
            data_class=ObservabilityDataClass.SUMMARY,
            sensitivity=ObservabilitySensitivity.SUMMARY,
            default_retention_days=365 * 3,
            max_retention_days=365 * 7,
            archive_years=7,
            allowed_access_tiers=("viewer", "data_analyst", "admin", "compliance"),
            purge_action="anonymize_actor",
            anonymize_on_delete=True,
            notes="Bounded prompt/output/tool summaries that have passed observability sanitization.",
        ),
        ObservabilityRetentionRule(
            data_class=ObservabilityDataClass.HASH,
            sensitivity=ObservabilitySensitivity.METADATA,
            default_retention_days=365 * 7,
            max_retention_days=365 * 7,
            archive_years=7,
            allowed_access_tiers=("data_analyst", "admin", "compliance"),
            purge_action="retain_non_reversible_hash",
            anonymize_on_delete=True,
            notes="Non-reversible content hashes used for deduplication, replay integrity, and behavior-mining joins.",
        ),
        ObservabilityRetentionRule(
            data_class=ObservabilityDataClass.BEHAVIOR_MINING_FEATURE,
            sensitivity=ObservabilitySensitivity.SUMMARY,
            default_retention_days=365 * 3,
            max_retention_days=365 * 7,
            archive_years=7,
            allowed_access_tiers=("data_analyst", "admin", "compliance"),
            purge_action="anonymize_actor",
            anonymize_on_delete=True,
            notes="Derived feature vectors, extracted snippets, and candidate provenance without raw secrets.",
        ),
        ObservabilityRetentionRule(
            data_class=ObservabilityDataClass.RAW_PROMPT,
            sensitivity=ObservabilitySensitivity.RAW,
            default_retention_days=30,
            max_retention_days=90,
            allowed_access_tiers=("admin", "compliance"),
            purge_action="delete",
            notes="Raw user or system prompt bodies; disabled for aggregate viewers and retained only for approved debugging windows.",
        ),
        ObservabilityRetentionRule(
            data_class=ObservabilityDataClass.RAW_RESPONSE,
            sensitivity=ObservabilitySensitivity.RAW,
            default_retention_days=30,
            max_retention_days=90,
            allowed_access_tiers=("admin", "compliance"),
            purge_action="delete",
            notes="Raw model responses and unbounded generation outputs.",
        ),
        ObservabilityRetentionRule(
            data_class=ObservabilityDataClass.TOOL_ARGS,
            sensitivity=ObservabilitySensitivity.RESTRICTED,
            default_retention_days=30,
            max_retention_days=90,
            allowed_access_tiers=("admin", "compliance"),
            purge_action="delete",
            notes="Tool input arguments, MCP payloads, platform-action request bodies, and command arguments.",
        ),
        ObservabilityRetentionRule(
            data_class=ObservabilityDataClass.OUTPUT_PREVIEW,
            sensitivity=ObservabilitySensitivity.RESTRICTED,
            default_retention_days=30,
            max_retention_days=90,
            allowed_access_tiers=("admin", "compliance"),
            purge_action="delete",
            notes="Bounded but potentially sensitive tool/model output previews.",
        ),
        ObservabilityRetentionRule(
            data_class=ObservabilityDataClass.COMMAND_OUTPUT,
            sensitivity=ObservabilitySensitivity.RESTRICTED,
            default_retention_days=30,
            max_retention_days=90,
            allowed_access_tiers=("admin", "compliance"),
            purge_action="delete",
            notes="Shell command output and process logs captured during execution.",
        ),
        ObservabilityRetentionRule(
            data_class=ObservabilityDataClass.FILE_DIFF,
            sensitivity=ObservabilitySensitivity.RESTRICTED,
            default_retention_days=30,
            max_retention_days=90,
            allowed_access_tiers=("admin", "compliance"),
            purge_action="delete",
            notes="File diffs and content patches generated during execution.",
        ),
    )
    serialized_rules = {}
    for rule in rules:
        payload = rule.to_dict()
        payload["allowed_access_tiers"] = list(rule.allowed_access_tiers)
        serialized_rules[rule.data_class.value] = payload
    return serialized_rules


def retention_rule_for(data_class: ObservabilityDataClass | str) -> Dict[str, Any]:
    """Return the retention rule for a data class."""

    return observability_retention_rules()[ObservabilityDataClass(data_class).value]


def _required_correlation_fields(kind: ObservabilityRecordKind) -> Sequence[str]:
    base = ("trace_id", "span_id", "project_id", "surface")
    by_kind = {
        ObservabilityRecordKind.TRACE: base,
        ObservabilityRecordKind.SPAN: base,
        ObservabilityRecordKind.EVENT: base,
        ObservabilityRecordKind.GENERATION: (*base, "model_id"),
        ObservabilityRecordKind.TOOL_CALL: base,
        ObservabilityRecordKind.ACTION: base,
        ObservabilityRecordKind.ARTIFACT: base,
        ObservabilityRecordKind.BEHAVIOR_CANDIDATE: base,
        ObservabilityRecordKind.OUTCOME: base,
    }
    return by_kind[kind]


__all__ = [
    "ActionEnvelope",
    "ArtifactEnvelope",
    "BehaviorCandidateEnvelope",
    "EventEnvelope",
    "GenerationEnvelope",
    "ObservabilityBackendProfile",
    "ObservabilityCorrelation",
    "ObservabilityDashboardDataset",
    "ObservabilityDashboardProfile",
    "ObservabilityDashboardSource",
    "ObservabilityDataClass",
    "ObservabilityRecord",
    "ObservabilityRecordKind",
    "ObservabilityRecordStatus",
    "ObservabilityRetentionRule",
    "ObservabilitySensitivity",
    "OutcomeEnvelope",
    "SpanEnvelope",
    "ToolCallEnvelope",
    "TraceEnvelope",
    "canonical_trace_examples",
    "observability_backend_targets",
    "observability_dashboard_sources",
    "observability_retention_rules",
    "observability_timescale_schema",
    "retention_rule_for",
    "utc_now",
]
