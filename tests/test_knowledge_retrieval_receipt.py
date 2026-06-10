"""Tests for knowledge retrieval receipt merge and RunService persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from amprealize.action_contracts import Actor
from amprealize.knowledge_retrieval_receipt import (
    MAX_SPANS,
    RECEIPT_METADATA_KEY,
    merge_receipt_spans,
    trace_summary_knowledge_slice,
)
from amprealize.run_contracts import RunCreateRequest
from amprealize.run_service import RunService


@pytest.mark.unit
def test_merge_receipt_spans_appends_and_rollups() -> None:
    first = merge_receipt_spans(None, [{"channel": "eka", "source_type": "behavior", "title": "A"}])
    assert first["rollup"]["by_channel"]["eka"] == 1
    assert first["rollup"]["by_source"]["behavior"] == 1
    assert len(first["spans"]) == 1

    second = merge_receipt_spans(first, [{"channel": "mcp", "source_type": "behavior", "title": "B"}])
    assert second["rollup"]["by_channel"]["mcp"] == 1
    assert len(second["spans"]) == 2


@pytest.mark.unit
def test_merge_receipt_spans_caps_at_max() -> None:
    existing = None
    for i in range(MAX_SPANS + 10):
        existing = merge_receipt_spans(existing, [{"channel": "x", "source_type": "other", "title": str(i)}])
    assert len(existing["spans"]) == MAX_SPANS


@pytest.mark.unit
def test_trace_summary_knowledge_slice_tail() -> None:
    spans = [{"title": str(i), "channel": "c"} for i in range(60)]
    receipt = merge_receipt_spans(None, spans)
    slim = trace_summary_knowledge_slice(receipt, max_spans=10)
    assert slim["span_count"] == 60
    assert len(slim["spans"]) == 10
    assert slim["spans"][-1]["title"] == "59"


@pytest.mark.unit
def test_run_service_append_knowledge_receipt_spans(tmp_path: Path) -> None:
    db = tmp_path / "runs_kr.db"
    svc = RunService(db_path=db)
    actor = Actor(id="u-test", role="user", surface="test")
    run = svc.create_run(RunCreateRequest(actor=actor))
    rid = run.run_id

    svc.append_knowledge_receipt_spans(
        rid,
        [{"channel": "eka", "source_type": "behavior", "title": "behavior_use_raze_for_logging"}],
    )
    svc.append_knowledge_receipt_spans(
        rid,
        [{"channel": "bci", "source_type": "behavior", "title": "behavior_prefer_mcp_tools"}],
    )

    loaded = svc.get_run(rid)
    kr = loaded.metadata.get(RECEIPT_METADATA_KEY)
    assert isinstance(kr, dict)
    assert len(kr["spans"]) == 2
    assert kr["rollup"]["by_channel"]["eka"] == 1
    assert kr["rollup"]["by_channel"]["bci"] == 1


@pytest.mark.unit
def test_append_knowledge_receipt_spans_noop_on_empty(tmp_path: Path) -> None:
    svc = RunService(db_path=tmp_path / "runs_empty.db")
    actor = Actor(id="u-test", role="user", surface="test")
    run = svc.create_run(RunCreateRequest(actor=actor))
    svc.append_knowledge_receipt_spans(run.run_id, [])
    loaded = svc.get_run(run.run_id)
    assert RECEIPT_METADATA_KEY not in loaded.metadata
