"""Tests for chat insight narrator and bounded analysis runner."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from amprealize.chat_action_router import ChatWorkspaceIntent
from amprealize.chat_analysis_runner import ChatAnalysisRunner
from amprealize.chat_insight_narrator import maybe_append_insight_narration
from amprealize.feature_flags import FeatureFlagService
from amprealize.resource_analysis import (
    ResourceAnalysisAnswer,
    ResourceAnalysisIntent,
    ResourceAnalysisService,
    ResourceQueryPlan,
)


def test_chat_analysis_flags_default_on_without_org() -> None:
    """Boolean chat flags use user_id context; org_id is not required."""

    svc = FeatureFlagService()
    assert svc.is_enabled("feature.chat_insight_narrator", {"user_id": "u-1"}) is True
    assert svc.is_enabled("feature.chat_analysis_runner", {"user_id": "u-1"}) is True


def test_insight_narrator_respects_disabled_flag() -> None:
    ff = FeatureFlagService()
    ff.set_flag("feature.chat_insight_narrator", enabled=False)
    out = maybe_append_insight_narration(
        structured_payload={
            "card_kind": "resource_analysis",
            "insights": {"by_item_type": [{"item_type": "bug", "count": 1}]},
        },
        user_message="how is velocity",
        chat_query_intent=ChatWorkspaceIntent.ANALYTICS_OR_RATE.value,
        llm_client=object(),
        feature_flags=ff,
        user_id="u1",
        org_id=None,
        project_id=None,
        model_id="m",
        prefer_user_credential=False,
    )
    assert out == ""


def test_insight_narrator_appends_when_enabled() -> None:
    ff = FeatureFlagService()
    ff.set_flag("feature.chat_insight_narrator", enabled=True)

    class _Resp:
        content = "Consider drilling into blocked items by board."

    class _LLM:
        def call(self, *a, **k):
            return _Resp()

    out = maybe_append_insight_narration(
        structured_payload={
            "card_kind": "resource_analysis",
            "insights": {"by_item_type": [{"item_type": "bug", "count": 2}]},
        },
        user_message="trends?",
        chat_query_intent=ChatWorkspaceIntent.LIST_INVENTORY.value,
        llm_client=_LLM(),
        feature_flags=ff,
        user_id="u1",
        org_id=None,
        project_id=None,
        model_id="m",
        prefer_user_credential=False,
    )
    assert out.startswith("\n\n")
    assert "Consider drilling" in out


@pytest.mark.asyncio
async def test_analysis_runner_multi_query_cells(monkeypatch: pytest.MonkeyPatch) -> None:
    ff = FeatureFlagService()
    ff.set_flag("feature.chat_analysis_runner", enabled=True)

    class _Resp:
        content = '{"sub_queries":["alpha probe","beta match"]}'

    class _LLM:
        def call(self, *a, **k):
            return _Resp()

    plan = ResourceQueryPlan(
        intent=ResourceAnalysisIntent.COUNT,
        resource_type="work_items",
    )

    def fake_answer_sync(self, *, query, inventory, scope_hints):
        if "beta" in query:
            return ResourceAnalysisAnswer(
                content="You have 2 work items in this scope.",
                answer_type="work_items.count",
                query_plan=plan,
                structured_payload={
                    "card_kind": "resource_analysis",
                    "summary": "2 items",
                },
                source_rows=[{"item_id": "a"}, {"item_id": "b"}],
            )
        return None

    monkeypatch.setattr(ResourceAnalysisService, "answer_sync", fake_answer_sync)

    svc = ResourceAnalysisService()
    runner = ChatAnalysisRunner(resource_analysis_service=svc, feature_flags=ff)
    inventory = {
        "projects": [{"id": "proj-1", "name": "P"}],
        "work_items_by_project": {"proj-1": [{"id": "wi-1", "title": "T"}]},
    }
    ans = await runner.try_answer(
        user_message="median cycle time for bugs in backlog",
        user_id="user-1",
        conversation_id="conv-1",
        message_id="msg-1",
        inventory=inventory,
        scope_hints={"project_id": "proj-1"},
        chat_query_intent=ChatWorkspaceIntent.ANALYTICS_OR_RATE.value,
        route_requires_clarification=False,
        llm_client=_LLM(),
        metadata={"llm_model_id": "test-model"},
        audit=None,
        org_id=None,
        project_id="proj-1",
    )
    assert ans is not None
    run = ans.structured_payload.get("analysis_run")
    assert isinstance(run, dict)
    cells = run.get("cells")
    assert isinstance(cells, list) and len(cells) == 2
    assert cells[0]["status"] in {"miss", "ok"}
    assert cells[1]["status"] == "ok"


@pytest.mark.asyncio
async def test_analysis_runner_ambiguous_scope_uses_scope_planner_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ff = FeatureFlagService()
    ff.set_flag("feature.chat_analysis_runner", enabled=True)
    planner_system_chunks: list[str] = []

    class _Resp:
        content = '{"sub_queries":["which boards exist for guideai?"]}'

    class _LLM:
        def call(self, messages, **kwargs):  # noqa: ANN001, ANN003
            planner_system_chunks.append(messages[0]["content"])
            return _Resp()

    plan = ResourceQueryPlan(
        intent=ResourceAnalysisIntent.LIST,
        resource_type="boards",
    )
    answer = ResourceAnalysisAnswer(
        content="boards ok",
        answer_type="boards.list",
        query_plan=plan,
        structured_payload={"card_kind": "resource_analysis"},
        source_rows=[{"board_id": "b1"}],
    )

    def fake_answer_sync(self, *, query, inventory, scope_hints):  # noqa: ANN001
        if query and "boards" in query.lower():
            return answer
        return None

    monkeypatch.setattr(ResourceAnalysisService, "answer_sync", fake_answer_sync)

    runner = ChatAnalysisRunner(
        resource_analysis_service=ResourceAnalysisService(),
        feature_flags=ff,
    )
    inventory = {
        "projects": [{"project_id": "proj-1", "name": "GuideAI"}],
        "work_items_by_project": {"proj-1": [{"item_id": "wi-1", "title": "T"}]},
    }
    ans = await runner.try_answer(
        user_message="which board should I open for GuideAI?",
        user_id="user-1",
        conversation_id="conv-1",
        message_id="msg-1",
        inventory=inventory,
        scope_hints={"project_id": "proj-1"},
        chat_query_intent=ChatWorkspaceIntent.AMBIGUOUS_SCOPE.value,
        route_requires_clarification=False,
        llm_client=_LLM(),
        metadata={"llm_model_id": "test-model"},
        audit=None,
        org_id=None,
        project_id="proj-1",
    )
    assert ans is not None
    assert "workspace scope" in planner_system_chunks[0].lower()
    run = ans.structured_payload.get("analysis_run")
    assert isinstance(run, dict)


@pytest.mark.asyncio
async def test_analysis_runner_skips_without_org_or_inventory() -> None:
    ff = FeatureFlagService()
    ff.set_flag("feature.chat_analysis_runner", enabled=True)
    runner = ChatAnalysisRunner(
        resource_analysis_service=ResourceAnalysisService(),
        feature_flags=ff,
    )
    ans = await runner.try_answer(
        user_message="velocity",
        user_id="u",
        conversation_id="c",
        message_id="m",
        inventory={},
        scope_hints={},
        chat_query_intent=ChatWorkspaceIntent.ANALYTICS_OR_RATE.value,
        route_requires_clarification=False,
        llm_client=object(),
        metadata={},
        audit=None,
    )
    assert ans is None
