"""MCP handler parity tests for research tools."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from amprealize.mcp.handlers.research_handlers import (
    RESEARCH_HANDLERS,
    ResearchToolValidationError,
    handle_evaluate,
    handle_search,
)
from amprealize.research_contracts import SourceType, Verdict
from amprealize.research_contracts import SearchPapersRequest
from amprealize.research_service import ResearchStorage


pytestmark = pytest.mark.unit


def _manifest_names() -> set[str]:
    root = Path(__file__).resolve().parents[1]
    return {
        json.loads(path.read_text())["name"]
        for path in (root / "mcp" / "tools").glob("research.*.json")
    }


def test_research_manifests_have_handlers() -> None:
    assert _manifest_names() == set(RESEARCH_HANDLERS)


def test_evaluate_requires_source() -> None:
    with pytest.raises(ResearchToolValidationError):
        asyncio.run(handle_evaluate(MagicMock(), {}))


def test_search_rejects_invalid_source_type() -> None:
    with pytest.raises(ResearchToolValidationError):
        asyncio.run(handle_search(MagicMock(), {"source_type": "video"}))


def test_search_parses_filters_and_session_identity() -> None:
    service = MagicMock()
    service.search_papers.return_value = SimpleNamespace(papers=[], total_count=0, has_more=False)

    result = asyncio.run(
        handle_search(
            service,
            {
                "query": "agent evaluation",
                "verdict": "adopt",
                "source_type": "arxiv",
                "limit": "7",
                "offset": "2",
                "_session": {"user_id": "user-1", "org_id": "org-1"},
            },
        )
    )

    assert result == {"success": True, "papers": [], "total_count": 0, "has_more": False}
    request = service.search_papers.call_args.args[0]
    assert request.query == "agent evaluation"
    assert request.verdict == Verdict.ADOPT
    assert request.source_type == SourceType.ARXIV
    assert request.limit == 7
    assert request.offset == 2
    assert service.search_papers.call_args.kwargs == {"owner_id": "user-1", "org_id": "org-1"}


def test_sqlite_search_applies_query_and_max_score_filters(tmp_path) -> None:
    storage = ResearchStorage(str(tmp_path / "research.db"))
    import sqlite3

    conn = sqlite3.connect(storage.db_path)
    try:
        now = "2026-04-24T00:00:00"
        conn.execute(
            """
            INSERT INTO research_papers
                (id, title, source_type, raw_text, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("paper-1", "Agent Evaluation Loops", "arxiv", "raw", now),
        )
        conn.execute(
            """
            INSERT INTO comprehensions
                (id, paper_id, core_idea, created_at)
            VALUES (?, ?, ?, ?)
            """,
            ("comp-1", "paper-1", "Evaluator optimizer agents", now),
        )
        conn.execute(
            """
            INSERT INTO evaluations
                (id, paper_id, comprehension_id, overall_score, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("eval-1", "paper-1", "comp-1", 6.5, now),
        )
        conn.execute(
            """
            INSERT INTO recommendations
                (id, paper_id, evaluation_id, verdict, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("rec-1", "paper-1", "eval-1", "ADAPT", now),
        )
        conn.commit()
    finally:
        conn.close()

    matching = storage.search_papers(SearchPapersRequest(query="optimizer", max_score=7.0))
    too_low = storage.search_papers(SearchPapersRequest(query="optimizer", max_score=6.0))

    assert matching.total_count == 1
    assert matching.papers[0].paper_id == "paper-1"
    assert too_low.total_count == 0
