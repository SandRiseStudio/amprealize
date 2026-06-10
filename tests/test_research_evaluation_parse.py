"""Tests for tolerant parsing of evaluation-phase LLM JSON."""

import pytest

from amprealize.research_contracts import Complexity, Priority, Verdict
from amprealize.research.evaluation_parse import (
    coerce_estimated_effort,
    ensure_str_list,
    parse_affected_components,
    parse_claimed_results,
    parse_competitive_landscape,
    parse_complexity,
    parse_conflict_items,
    parse_implementation_steps,
    parse_parsed_sections,
    parse_structured_cons,
    paper_summaries_from_postgres_search,
    paper_summaries_from_sqlite_rows,
    paper_summary_from_sqlite_tuple,
    parse_recommendation_priority,
)

pytestmark = pytest.mark.unit


def test_parse_conflict_items_mixed_dict_and_string():
    raw = [
        {"behavior_name": "b1", "description": "d1", "severity": "high"},
        "Plain string conflict",
    ]
    items = parse_conflict_items(raw)
    assert len(items) == 2
    assert items[0].behavior_name == "b1"
    assert items[0].description == "d1"
    assert items[1].behavior_name == ""
    assert items[1].description == "Plain string conflict"
    assert items[1].severity == "medium"


def test_parse_conflict_items_non_list_returns_empty():
    assert parse_conflict_items(None) == []
    assert parse_conflict_items("x") == []
    assert parse_conflict_items({}) == []


def test_parse_competitive_landscape_string_entry():
    raw = [{"name": "X", "category": "library", "description": "d"}]
    items = parse_competitive_landscape(raw)
    assert len(items) == 1
    assert items[0].name == "X"
    assert items[0].category == "library"
    raw2 = ["LangChain does retrieval"]
    items2 = parse_competitive_landscape(raw2)
    assert len(items2) == 1
    assert "LangChain" in items2[0].description


def test_parse_structured_cons_string_entry():
    raw = ["Vendor lock-in risk"]
    items = parse_structured_cons(raw)
    assert len(items) == 1
    assert items[0].description == "Vendor lock-in risk"
    assert items[0].severity == "medium"


def test_parse_claimed_results_dict_and_string():
    raw = [{"metric": "acc", "improvement": "+2%", "conditions": "s1"}, "Plain claim text"]
    items = parse_claimed_results(raw)
    assert len(items) == 2
    assert items[0].metric == "acc"
    assert items[1].improvement == "Plain claim text"


def test_parse_claimed_results_claim_evidence_aliases():
    raw = [{"claim": "F1", "evidence": "table 3"}]
    items = parse_claimed_results(raw)
    assert items[0].metric == "F1"
    assert items[0].improvement == "table 3"


def test_parse_affected_components_mixed():
    raw = [{"path": "a.py", "what_changes": "wire X"}, "Refactor tests"]
    items = parse_affected_components(raw)
    assert len(items) == 2
    assert items[0].path == "a.py"
    assert items[1].what_changes == "Refactor tests"


def test_parse_implementation_steps_dict_and_string():
    raw = [{"order": 2, "description": "Ship", "effort": "S"}, "Quick doc update"]
    steps = parse_implementation_steps(raw)
    assert len(steps) == 2
    assert steps[0].order == 2
    assert steps[1].order == 2
    assert "doc" in steps[1].description


def test_parse_conflict_items_component_alias():
    raw = [{"component": "auth", "description": "overlap", "severity": "high"}]
    items = parse_conflict_items(raw)
    assert items[0].behavior_name == "auth"


def test_ensure_str_list():
    assert ensure_str_list(None) == []
    assert ensure_str_list("one") == ["one"]
    assert ensure_str_list([" a ", "b", 3]) == ["a", "b", "3"]


def test_parse_parsed_sections_dict_and_string():
    raw = [{"title": "Intro", "content": "c1", "level": 2}, "orphan paragraph"]
    secs = parse_parsed_sections(raw)
    assert len(secs) == 2
    assert secs[0].name == "Intro"
    assert secs[0].level == 2
    assert secs[1].content == "orphan paragraph"
    assert secs[1].level == 1


def test_parse_parsed_sections_bad_level_defaults():
    raw = [{"name": "x", "content": "y", "level": "nope"}]
    secs = parse_parsed_sections(raw)
    assert secs[0].level == 1


def test_parse_parsed_sections_non_list():
    assert parse_parsed_sections(None) == []
    assert parse_parsed_sections({}) == []


def test_paper_summaries_from_postgres_search_skips_bad_rows():
    raw = {
        "papers": [
            None,
            "bad",
            {"title": "orphan"},
            {
                "paper_id": "p1",
                "title": "T",
                "source_type": "url",
                "overall_score": "7",
                "verdict": "ADOPT",
                "core_idea": "c",
                "created_at": "2026-01-01T12:00:00Z",
            },
        ]
    }
    items = paper_summaries_from_postgres_search(raw)
    assert len(items) == 1
    assert items[0].paper_id == "p1"
    assert items[0].overall_score == 7.0


def test_paper_summary_from_sqlite_tuple_coercion():
    row = (
        "pid",
        "Title",
        "url",
        "8.5",
        "ADOPT",
        "idea",
        "2026-03-15T10:00:00Z",
    )
    s = paper_summary_from_sqlite_tuple(row)
    assert s is not None
    assert s.paper_id == "pid"
    assert s.overall_score == 8.5
    assert s.verdict.value == "ADOPT"


def test_paper_summary_from_sqlite_tuple_bad_enum_defaults():
    row = ("p2", "T", "not_a_source_type", None, "nope", "", "2026-01-01")
    s = paper_summary_from_sqlite_tuple(row)
    assert s is not None
    assert s.source_type.value == "url"
    assert s.verdict == Verdict.DEFER


def test_paper_summary_from_sqlite_tuple_short_row():
    assert paper_summary_from_sqlite_tuple((1, 2, 3)) is None
    assert paper_summary_from_sqlite_tuple(None) is None


def test_parse_recommendation_priority_low_and_p_labels():
    assert parse_recommendation_priority("low") == Priority.P4
    assert parse_recommendation_priority("HIGH") == Priority.P2
    assert parse_recommendation_priority("p2") == Priority.P2
    assert parse_recommendation_priority(None) == Priority.P3
    assert parse_recommendation_priority("not-a-priority") == Priority.P3


def test_parse_complexity_medium_high_and_valid():
    assert parse_complexity("MEDIUM_HIGH") == Complexity.HIGH
    assert parse_complexity("medium-high") == Complexity.HIGH
    assert parse_complexity("LOW") == Complexity.LOW
    assert parse_complexity(Complexity.VERY_HIGH) == Complexity.VERY_HIGH
    assert parse_complexity(None) == Complexity.MEDIUM
    assert parse_complexity("not-a-complexity") == Complexity.MEDIUM


def test_coerce_estimated_effort_dict_and_string():
    assert coerce_estimated_effort({"weeks": 3, "size": "L"}) == '{"weeks": 3, "size": "L"}'
    assert coerce_estimated_effort("  XL — two sprints  ") == "XL — two sprints"
    assert coerce_estimated_effort(None) == "M - Moderate effort"
    assert coerce_estimated_effort("") == "M - Moderate effort"


def test_paper_summaries_from_sqlite_rows_filters():
    rows = [
        ("good", "T", "url", 1, "DEFER", "c", "2026-01-02T00:00:00+00:00"),
        (None, "x", "url", 1, "DEFER", "c", "2026-01-02"),
    ]
    items = paper_summaries_from_sqlite_rows(rows)
    assert len(items) == 1
    assert items[0].paper_id == "good"
