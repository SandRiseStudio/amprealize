"""Regression: Research wiki ingest must embed full evaluation markdown."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from amprealize.wiki_service import WikiService, _strip_first_markdown_h1


def test_strip_first_markdown_h1_removes_title_only() -> None:
    md = "# My Title\n\n## Section\n\nBody."
    assert _strip_first_markdown_h1(md) == "## Section\n\nBody."


def test_strip_first_markdown_h1_no_heading_unchanged() -> None:
    s = "## Only h2\n\ntext"
    assert _strip_first_markdown_h1(s) == s


@pytest.fixture()
def wiki_tmp(tmp_path: Path) -> WikiService:
    base = tmp_path / "repo"
    wr = base / "wiki" / "research"
    wr.mkdir(parents=True)
    (wr / "index.md").write_text(
        "# Research Wiki\n\n## Evaluation Summaries\n\n_No evaluation-summary pages yet._\n",
        encoding="utf-8",
    )
    (wr / "log.md").write_text(
        "# Log\n\n| When | Op | Details |\n|------|----|----|\n",
        encoding="utf-8",
    )
    return WikiService(repo_root=str(base))


def test_ingest_research_evaluation_embeds_full_report(wiki_tmp: WikiService) -> None:
    report = "# Micro batch research\n\n## Paper\n\nDetails here.\n\n## Recommendation\n\nVerdict text.\n"
    out = wiki_tmp.ingest_research_evaluation(
        paper_title="Micro batch research",
        paper_id="paper_x",
        verdict="DEFER",
        overall_score=5.3,
        markdown_report=report,
        sources=["https://example.com"],
    )
    assert out.get("success") is not False
    path = wiki_tmp._resolve_page_path("research", "evaluations/micro-batch-research.md")
    text = path.read_text(encoding="utf-8")
    assert "## Full evaluation report" in text
    assert "## Paper" in text
    assert "Details here." in text
    assert "## Recommendation" in text


def test_ingest_research_evaluation_rerun_overwrites_eval_page(wiki_tmp: WikiService) -> None:
    """Same paper_title maps to the same path; second ingest must replace, not skip."""
    title = "Wiki overwrite fixture paper"
    first = wiki_tmp.ingest_research_evaluation(
        paper_title=title,
        paper_id="paper_first",
        verdict="DEFER",
        overall_score=5.3,
        markdown_report=f"# {title}\n\n## Paper\n\nFIRST_MARKER body.\n",
        sources=["https://a.example"],
    )
    slug_path = "evaluations/wiki-overwrite-fixture-paper.md"
    assert slug_path in first.get("created_pages", [])

    second = wiki_tmp.ingest_research_evaluation(
        paper_title=title,
        paper_id="paper_second",
        verdict="REJECT",
        overall_score=4.7,
        markdown_report=f"# {title}\n\n## Paper\n\nSECOND_MARKER only.\n",
        sources=["https://b.example"],
    )
    assert slug_path in second.get("updated_pages", [])
    assert slug_path not in second.get("created_pages", [])

    text = wiki_tmp._resolve_page_path("research", slug_path).read_text(encoding="utf-8")
    assert "SECOND_MARKER only." in text
    assert "FIRST_MARKER" not in text
    assert "**Score**: 4.7/10" in text
    assert "https://b.example" in text
    assert "https://a.example" not in text
