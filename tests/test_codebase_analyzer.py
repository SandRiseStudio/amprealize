"""Tests for research CodebaseAnalyzer stub hooks."""

from __future__ import annotations

from pathlib import Path

import pytest

from amprealize.research.codebase_analyzer import CodebaseAnalyzer, StructuralIndex


@pytest.mark.unit
def test_get_structural_index_returns_buckets(tmp_path: Path) -> None:
    """Minimal repo layout → non-empty structural index + context string."""
    (tmp_path / "amprealize" / "services").mkdir(parents=True)
    (tmp_path / "amprealize" / "services" / "board_service.py").write_text("# svc\n", encoding="utf-8")
    (tmp_path / "mcp" / "tools").mkdir(parents=True)
    (tmp_path / "mcp" / "tools" / "demo.json").write_text(
        '{"name": "demo.tool", "description": "x"}\n', encoding="utf-8"
    )
    (tmp_path / "AGENTS.md").write_text(
        "Follow `behavior_use_raze_for_logging` and `behavior_git_governance`.\n",
        encoding="utf-8",
    )
    mig = tmp_path / "migrations" / "versions"
    mig.mkdir(parents=True)
    (mig / "001_x.py").write_text(
        "def upgrade():\n    op.create_table('users', sa.Column('id', sa.Integer()))\n",
        encoding="utf-8",
    )
    sql_dir = tmp_path / "schema" / "migrations"
    sql_dir.mkdir(parents=True)
    (sql_dir / "001.sql").write_text(
        "CREATE TABLE IF NOT EXISTS sessions (id text);\n", encoding="utf-8"
    )

    idx = CodebaseAnalyzer(tmp_path).get_structural_index()
    assert isinstance(idx, StructuralIndex)
    assert "board_service" in idx.services
    assert "behavior_use_raze_for_logging" in idx.behaviors
    assert "behavior_git_governance" in idx.behaviors
    assert "demo.tool" in idx.mcp_tools
    assert "users" in idx.db_tables
    assert "sessions" in idx.db_tables
    ctx = idx.to_context_string()
    assert "board_service" in ctx
    assert "demo.tool" in ctx
    assert "behavior_use_raze_for_logging" in ctx


@pytest.mark.unit
def test_get_structural_index_empty_when_root_missing(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    idx = CodebaseAnalyzer(missing).get_structural_index()
    assert idx.services == []
    assert idx.to_context_string() == ""


@pytest.mark.unit
def test_init_accepts_project_root_kwarg(tmp_path: Path) -> None:
    analyzer = CodebaseAnalyzer(project_root=tmp_path, cache_ttl=1)
    assert analyzer.root_path == str(tmp_path)
    assert analyzer._config == {"cache_ttl": 1}


@pytest.mark.unit
def test_deep_dive_resolves_under_root(tmp_path: Path) -> None:
    f = tmp_path / "sample.txt"
    f.write_text("a\nb\nc\n", encoding="utf-8")
    analyzer = CodebaseAnalyzer(tmp_path)
    out = analyzer.deep_dive("sample.txt", start_line=1, end_line=2)
    assert "a" in out and "b" in out


@pytest.mark.unit
def test_deep_dive_rejects_escape(tmp_path: Path) -> None:
    analyzer = CodebaseAnalyzer(tmp_path)
    assert "outside root" in analyzer.deep_dive("../etc/passwd")
