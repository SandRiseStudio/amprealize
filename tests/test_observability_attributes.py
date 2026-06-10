"""Tests for OpenInference / OTel attribute mapping on canonical records."""

from __future__ import annotations

import pytest

from amprealize.observability_attributes import (
    LLM_MODEL_NAME,
    OPENINFERENCE_SPAN_KIND,
    TOOL_NAME,
    merge_otel_into_attributes,
    to_otel_attributes,
)
from amprealize.observability_contracts import (
    GenerationEnvelope,
    ObservabilityCorrelation,
    ObservabilityRecordKind,
    ToolCallEnvelope,
)

pytestmark = pytest.mark.unit


def _corr(*, model_id: str | None = None) -> ObservabilityCorrelation:
    return ObservabilityCorrelation(
        trace_id="tr-1",
        span_id="sp-1",
        project_id="proj-1",
        surface="chat",
        model_id=model_id,
    )


def test_generation_maps_openinference_llm() -> None:
    rec = GenerationEnvelope(
        record_id="rec-1",
        kind=ObservabilityRecordKind.GENERATION,
        name="completion",
        timestamp="2026-05-04T12:00:00+00:00",
        correlation=_corr(model_id="test-model"),
        provider="stub",
        model_id="test-model",
        input_tokens=3,
        output_tokens=7,
    )
    attrs = to_otel_attributes(rec)
    assert attrs[OPENINFERENCE_SPAN_KIND] == "LLM"
    assert attrs[LLM_MODEL_NAME] == "test-model"


def test_tool_call_maps_openinference_tool() -> None:
    rec = ToolCallEnvelope(
        record_id="rec-2",
        kind=ObservabilityRecordKind.TOOL_CALL,
        name="invoke",
        timestamp="2026-05-04T12:00:00+00:00",
        correlation=_corr(),
        tool_name="list_dir",
    )
    attrs = to_otel_attributes(rec)
    assert attrs[OPENINFERENCE_SPAN_KIND] == "TOOL"
    assert attrs[TOOL_NAME] == "list_dir"


def test_merge_otel_into_attributes_preserves_existing() -> None:
    rec = ToolCallEnvelope(
        record_id="rec-3",
        kind=ObservabilityRecordKind.TOOL_CALL,
        name="invoke",
        timestamp="2026-05-04T12:00:00+00:00",
        correlation=_corr(),
        tool_name="x",
    )
    merged = merge_otel_into_attributes(rec, {"custom": 42})
    assert merged["custom"] == 42
    assert merged[TOOL_NAME] == "x"
