"""OpenInference-style and OTel GenAI attribute helpers for canonical observability records.

Maps :class:`~amprealize.observability_contracts.ObservabilityRecord` envelopes to attribute
dictionaries suitable for future OTLP / OpenInference exporters (GUIDEAI-1195).

Uses ``opentelemetry-semantic-conventions`` where available; falls back to stable string keys.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from amprealize.observability_contracts import (
    ActionEnvelope,
    ArtifactEnvelope,
    BehaviorCandidateEnvelope,
    EventEnvelope,
    GenerationEnvelope,
    ObservabilityCorrelation,
    ObservabilityRecord,
    ObservabilityRecordKind,
    OutcomeEnvelope,
    SpanEnvelope,
    ToolCallEnvelope,
    TraceEnvelope,
)

# --- OpenInference semantic convention strings (vendor-neutral; see OpenInference spec) ---

OPENINFERENCE_SPAN_KIND = "openinference.span.kind"

# LLM
LLM_MODEL_NAME = "llm.model_name"
LLM_INVOCATION_PARAMETERS = "llm.invocation_parameters"
LLM_INPUT_MESSAGES = "llm.input_messages"
LLM_OUTPUT_MESSAGES = "llm.output_messages"
LLM_TOKEN_COUNT_PROMPT = "llm.token_count.prompt"
LLM_TOKEN_COUNT_COMPLETION = "llm.token_count.completion"
LLM_TOKEN_COUNT_TOTAL = "llm.token_count.total"
LLM_SYSTEM = "llm.system"
LLM_PROVIDER = "llm.provider"

# Tool
TOOL_NAME = "tool.name"
INPUT_VALUE = "input.value"
OUTPUT_VALUE = "output.value"

# Session / user (OpenInference + common tracing)
SESSION_ID = "session.id"
USER_ID = "user.id"

# Agent
AGENT_NAME = "agent.name"

# Retriever (reserved for future RAG spans)
RETRIEVER_QUERY = "retrieval.query"

_OTEL_GEN_AI_KEYS: Optional[Dict[str, str]] = None


def _otel_gen_ai_keys() -> Dict[str, str]:
    """Resolve OTel GenAI attribute names from opentelemetry-semantic-conventions when present."""
    global _OTEL_GEN_AI_KEYS
    if _OTEL_GEN_AI_KEYS is not None:
        return _OTEL_GEN_AI_KEYS
    keys: Dict[str, str] = {
        "request_model": "gen_ai.request.model",
        "response_model": "gen_ai.response.model",
        "usage_input_tokens": "gen_ai.usage.input_tokens",
        "usage_output_tokens": "gen_ai.usage.output_tokens",
    }
    try:
        from opentelemetry.semantic_conventions.attributes import gen_ai_attributes as ga

        keys["request_model"] = str(ga.GEN_AI_REQUEST_MODEL)
        keys["response_model"] = str(ga.GEN_AI_RESPONSE_MODEL)
        keys["usage_input_tokens"] = str(ga.GEN_AI_USAGE_INPUT_TOKENS)
        keys["usage_output_tokens"] = str(ga.GEN_AI_USAGE_OUTPUT_TOKENS)
    except Exception:
        pass
    _OTEL_GEN_AI_KEYS = keys
    return keys


def _openinference_span_kind(kind: ObservabilityRecordKind) -> str:
    """Map canonical record kind to OpenInference span kind string."""
    return {
        ObservabilityRecordKind.TRACE: "CHAIN",
        ObservabilityRecordKind.SPAN: "CHAIN",
        ObservabilityRecordKind.EVENT: "CHAIN",
        ObservabilityRecordKind.GENERATION: "LLM",
        ObservabilityRecordKind.TOOL_CALL: "TOOL",
        ObservabilityRecordKind.ACTION: "CHAIN",
        ObservabilityRecordKind.ARTIFACT: "CHAIN",
        ObservabilityRecordKind.BEHAVIOR_CANDIDATE: "CHAIN",
        ObservabilityRecordKind.OUTCOME: "CHAIN",
    }[kind]


def _correlation_attributes(correlation: ObservabilityCorrelation) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    ga = _otel_gen_ai_keys()
    if correlation.conversation_id:
        out[SESSION_ID] = correlation.conversation_id
    if correlation.actor_id:
        out[USER_ID] = correlation.actor_id
    if correlation.model_id:
        out[LLM_MODEL_NAME] = correlation.model_id
        out[ga["request_model"]] = correlation.model_id
        out[ga["response_model"]] = correlation.model_id
    if correlation.trace_id:
        out["amprealize.trace_id"] = correlation.trace_id
    if correlation.span_id:
        out["amprealize.span_id"] = correlation.span_id
    if correlation.parent_span_id:
        out["amprealize.parent_span_id"] = correlation.parent_span_id
    if correlation.project_id:
        out["amprealize.project_id"] = correlation.project_id
    if correlation.surface:
        out["amprealize.surface"] = correlation.surface
    if correlation.run_id:
        out["amprealize.run_id"] = correlation.run_id
    if correlation.work_item_id:
        out["amprealize.work_item_id"] = correlation.work_item_id
    if correlation.tool_call_id:
        out["amprealize.tool_call_id"] = correlation.tool_call_id
    if correlation.llm_call_id:
        out["amprealize.llm_call_id"] = correlation.llm_call_id
    return out


def to_otel_attributes(record: ObservabilityRecord) -> Dict[str, Any]:
    """Build a flat attribute map with OpenInference keys plus OTel GenAI aliases where applicable."""
    attrs: Dict[str, Any] = {
        OPENINFERENCE_SPAN_KIND: _openinference_span_kind(record.kind),
        "amprealize.record_kind": record.kind.value,
        "amprealize.record_name": record.name,
    }
    attrs.update(_correlation_attributes(record.correlation))
    ga = _otel_gen_ai_keys()

    if isinstance(record, GenerationEnvelope):
        if record.provider:
            attrs[LLM_PROVIDER] = record.provider
        if record.model_id:
            attrs[LLM_MODEL_NAME] = record.model_id
            attrs[ga["request_model"]] = record.model_id
        if record.input_tokens is not None:
            attrs[LLM_TOKEN_COUNT_PROMPT] = record.input_tokens
            attrs[ga["usage_input_tokens"]] = record.input_tokens
        if record.output_tokens is not None:
            attrs[LLM_TOKEN_COUNT_COMPLETION] = record.output_tokens
            attrs[ga["usage_output_tokens"]] = record.output_tokens
        if record.input_tokens is not None and record.output_tokens is not None:
            attrs[LLM_TOKEN_COUNT_TOTAL] = record.input_tokens + record.output_tokens
        if record.latency_ms is not None:
            attrs["amprealize.latency_ms"] = record.latency_ms
        if record.first_token_latency_ms is not None:
            attrs["amprealize.first_token_latency_ms"] = record.first_token_latency_ms
        if record.cost_usd is not None:
            attrs["amprealize.cost_usd"] = record.cost_usd
        if record.prompt_summary:
            attrs[LLM_INPUT_MESSAGES] = record.prompt_summary
        if record.output_summary:
            attrs[LLM_OUTPUT_MESSAGES] = record.output_summary
        inv: Dict[str, Any] = {}
        if record.provider:
            inv["provider"] = record.provider
        if record.model_id:
            inv["model"] = record.model_id
        if inv:
            attrs[LLM_INVOCATION_PARAMETERS] = inv

    elif isinstance(record, ToolCallEnvelope):
        if record.tool_name:
            attrs[TOOL_NAME] = record.tool_name
        if record.input_summary:
            attrs[INPUT_VALUE] = record.input_summary
        if record.output_summary:
            attrs[OUTPUT_VALUE] = record.output_summary
        if record.elapsed_ms is not None:
            attrs["amprealize.elapsed_ms"] = record.elapsed_ms

    elif isinstance(record, SpanEnvelope):
        if record.duration_ms is not None:
            attrs["amprealize.duration_ms"] = record.duration_ms

    elif isinstance(record, TraceEnvelope):
        if record.duration_ms is not None:
            attrs["amprealize.duration_ms"] = record.duration_ms
        if record.ended_at:
            attrs["amprealize.ended_at"] = record.ended_at

    elif isinstance(record, ActionEnvelope):
        if record.action_type:
            attrs["amprealize.action_type"] = record.action_type
        if record.target_resource_type:
            attrs["amprealize.target_resource_type"] = record.target_resource_type
        if record.target_resource_id:
            attrs["amprealize.target_resource_id"] = record.target_resource_id

    elif isinstance(record, ArtifactEnvelope):
        if record.artifact_type:
            attrs["amprealize.artifact_type"] = record.artifact_type
        if record.artifact_id:
            attrs["amprealize.artifact_id"] = record.artifact_id
        if record.uri:
            attrs["amprealize.artifact_uri"] = record.uri

    elif isinstance(record, BehaviorCandidateEnvelope):
        if record.candidate_id:
            attrs["amprealize.candidate_id"] = record.candidate_id
        if record.confidence is not None:
            attrs["amprealize.candidate_confidence"] = record.confidence

    elif isinstance(record, OutcomeEnvelope):
        if record.outcome_type:
            attrs["amprealize.outcome_type"] = record.outcome_type
        if record.resource_type:
            attrs["amprealize.resource_type"] = record.resource_type
        if record.resource_id:
            attrs["amprealize.resource_id"] = record.resource_id

    # Strip None values for cleaner payloads
    return {k: v for k, v in attrs.items() if v is not None}


def merge_otel_into_attributes(
    record: ObservabilityRecord,
    existing: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Merge ``to_otel_attributes(record)`` into ``existing`` (shallow copy)."""
    base = dict(existing or {})
    base.update(to_otel_attributes(record))
    return base


__all__ = [
    "AGENT_NAME",
    "INPUT_VALUE",
    "LLM_INVOCATION_PARAMETERS",
    "LLM_MODEL_NAME",
    "LLM_OUTPUT_MESSAGES",
    "LLM_PROVIDER",
    "LLM_SYSTEM",
    "LLM_TOKEN_COUNT_COMPLETION",
    "LLM_TOKEN_COUNT_PROMPT",
    "LLM_TOKEN_COUNT_TOTAL",
    "OPENINFERENCE_SPAN_KIND",
    "OUTPUT_VALUE",
    "RETRIEVER_QUERY",
    "SESSION_ID",
    "TOOL_NAME",
    "USER_ID",
    "merge_otel_into_attributes",
    "to_otel_attributes",
]
