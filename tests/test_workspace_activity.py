"""Tests for workspace activity tiers and fairness mode (global prioritization chat)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from amprealize.workspace_activity import (
    ProjectActivitySummary,
    build_workspace_activity_appendix,
    disclosure_required,
    fairness_mode_for_inventory,
    summarize_project_activity,
)

pytestmark = pytest.mark.unit


def test_summarize_marks_active_within_recency_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMPREALIZE_WORKSPACE_ACTIVITY_RECENCY_DAYS", "14")
    now = datetime.now(timezone.utc)
    inv = {
        "projects": [{"project_id": "p1", "name": "Alpha"}],
        "work_items_by_project": {
            "p1": [
                {
                    "item_id": "i1",
                    "updated_at": (now - timedelta(days=1)).isoformat(),
                }
            ],
        },
    }
    out = summarize_project_activity(inv)
    assert len(out) == 1
    assert out[0].project_id == "p1"
    assert out[0].tier == "active"


def test_summarize_quiet_when_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMPREALIZE_WORKSPACE_ACTIVITY_RECENCY_DAYS", "14")
    now = datetime.now(timezone.utc)
    inv = {
        "projects": [{"project_id": "p1", "name": "Alpha"}],
        "work_items_by_project": {
            "p1": [{"item_id": "i1", "updated_at": (now - timedelta(days=100)).isoformat()}],
        },
    }
    out = summarize_project_activity(inv)
    assert out[0].tier == "quiet"


def test_summarize_unknown_without_timestamps() -> None:
    inv = {
        "projects": [{"project_id": "p1", "name": "Alpha"}],
        "work_items_by_project": {"p1": [{"item_id": "i1", "title": "x"}]},
    }
    out = summarize_project_activity(inv)
    assert out[0].tier == "unknown"


def test_fairness_balanced_when_all_active() -> None:
    now = datetime.now(timezone.utc)
    s1 = ProjectActivitySummary("a", "A", "active", now)
    s2 = ProjectActivitySummary("b", "B", "active", now)
    assert fairness_mode_for_inventory([s1, s2], {"a", "b"}) == "balanced_multi_project"


def test_fairness_focused_when_quiet_present() -> None:
    now = datetime.now(timezone.utc)
    s1 = ProjectActivitySummary("a", "A", "active", now)
    s2 = ProjectActivitySummary("b", "B", "quiet", now)
    assert fairness_mode_for_inventory([s1, s2], {"a", "b"}) == "focused_with_disclosure"


def test_disclosure_required_matches_focused() -> None:
    assert disclosure_required("focused_with_disclosure") is True
    assert disclosure_required("balanced_multi_project") is False


def test_appendix_includes_zero_fetch_projects() -> None:
    now = datetime.now(timezone.utc)
    summaries = [
        ProjectActivitySummary("p1", "One", "active", now),
    ]
    text = build_workspace_activity_appendix(
        summaries=summaries,
        fairness_mode="focused_with_disclosure",
        rows_per_project={"p1": 5, "p2": 0},
        project_ids_in_plan=["p1", "p2"],
        allowed_project_ids={"p1", "p2"},
    )
    assert "p2" in text
    assert "no matching tasks" in text.lower()
