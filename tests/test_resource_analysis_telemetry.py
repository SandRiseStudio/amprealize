"""Telemetry hooks for ResourceAnalysisService."""

from __future__ import annotations

import pytest

from amprealize.resource_analysis import ResourceAnalysisService

pytestmark = pytest.mark.unit


def test_answer_sync_emits_telemetry_event(monkeypatch) -> None:
    calls: list[tuple[str, str, str]] = []

    def _capture(
        answer,
        *,
        query: str,
        actor_surface: str,
    ) -> None:
        calls.append((answer.query_plan.resource_type, query, actor_surface))

    monkeypatch.setattr(
        "amprealize.resource_analysis._emit_resource_analysis_telemetry",
        _capture,
    )

    inv = {
        "projects": [
            {"project_id": "p1", "name": "A", "slug": "a"},
        ],
    }
    ResourceAnalysisService().answer_sync(
        query="what projects are available?",
        inventory=inv,
    )

    assert len(calls) == 1
    assert calls[0][0] == "projects"
    assert "project" in calls[0][1]
    assert calls[0][2] == "sync_inventory_fragment"


@pytest.mark.asyncio
async def test_async_answer_emits_telemetry_event(monkeypatch) -> None:
    calls: list[str] = []

    def _capture(answer, *, query: str, actor_surface: str) -> None:
        calls.append(actor_surface)

    monkeypatch.setattr(
        "amprealize.resource_analysis._emit_resource_analysis_telemetry",
        _capture,
    )

    inv = {
        "projects": [{"project_id": "p1", "name": "A", "slug": "a"}],
    }
    await ResourceAnalysisService().answer(
        query="how many projects do I have?",
        inventory=inv,
    )

    assert calls == ["async"]


def test_row_label_includes_slug_when_distinct_from_name() -> None:
    label = ResourceAnalysisService._row_label(
        {
            "name": "Alpha",
            "slug": "alpha",
            "id": "proj-1",
        }
    )
    assert "Alpha (alpha)" in label
    assert "[proj-1]" in label
