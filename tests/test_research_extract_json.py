"""Tests for ResearchService JSON recovery from LLM responses."""

from __future__ import annotations

import pytest

from amprealize.research_service import ResearchService, _normalize_comprehension_dict


@pytest.mark.unit
def test_extract_json_raw_decode_with_trailing_text() -> None:
    svc = ResearchService(context_dir=".")
    text = '{"core_idea": "hello", "problem_addressed": "p"}\n\nThanks for reading.'
    data = svc._extract_json(text)
    assert data["core_idea"] == "hello"
    assert data["problem_addressed"] == "p"


@pytest.mark.unit
def test_extract_json_from_fenced_block() -> None:
    svc = ResearchService(context_dir=".")
    text = 'Here is the result:\n```json\n{"a": 1}\n```\n'
    data = svc._extract_json(text)
    assert data["a"] == 1


@pytest.mark.unit
def test_normalize_comprehension_dict_merges_camel_case() -> None:
    raw = {
        "coreIdea": "Thesis from camel",
        "problemAddressed": "Problem here",
        "novelty_score": 7.0,
    }
    out = _normalize_comprehension_dict(raw)
    assert out["core_idea"] == "Thesis from camel"
    assert out["problem_addressed"] == "Problem here"
    assert out["novelty_score"] == 7.0
    assert "coreIdea" not in out


@pytest.mark.unit
def test_normalize_comprehension_dict_prefers_existing_snake_case() -> None:
    raw = {"coreIdea": "ignored", "core_idea": "keep snake"}
    out = _normalize_comprehension_dict(raw)
    assert out["core_idea"] == "keep snake"
