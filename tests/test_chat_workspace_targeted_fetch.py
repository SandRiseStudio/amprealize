"""Tests for LLM-planned workspace targeted fetch (Phase B)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from amprealize.boards.contracts import WorkItemStatus
from amprealize.chat_workspace_targeted_fetch import (
    FetchQuerySpec,
    WorkspaceFetchPlan,
    build_fetch_plan_from_chat_query_plan,
    distinct_project_ids_in_plan,
    execute_fetch_plan,
    parse_workspace_fetch_plan,
    rows_per_project_counts,
    run_planner_llm,
)
from amprealize.chat_query_planner import (
    ChatPlanMode,
    ChatPlanOperation,
    ChatQueryPlan,
    ChatResourceType,
)

pytestmark = pytest.mark.unit


def test_planner_prompt_requires_multi_project_distribution() -> None:
    from amprealize.chat_workspace_targeted_fetch import PLANNER_SYSTEM_PROMPT

    assert "Multi-project breadth" in PLANNER_SYSTEM_PROMPT


def test_distinct_project_ids_in_plan_sorted_unique() -> None:
    plan = WorkspaceFetchPlan(
        queries=[
            FetchQuerySpec(project_id="b", limit=5),
            FetchQuerySpec(project_id="a", limit=5),
            FetchQuerySpec(project_id="a", limit=3),
        ],
        rationale="x",
    )

    assert distinct_project_ids_in_plan(plan) == ["a", "b"]


def test_rows_per_project_counts_groups_by_project_id() -> None:
    w1 = SimpleNamespace(item_id="1", project_id="p-a")
    w2 = SimpleNamespace(item_id="2", project_id="p-a")
    w3 = SimpleNamespace(item_id="3", project_id="p-b")
    assert rows_per_project_counts([w1, w2, w3]) == {"p-a": 2, "p-b": 1}


def test_build_fetch_plan_from_chat_query_plan_uses_topic_text_search() -> None:
    chat_plan = ChatQueryPlan(
        mode=ChatPlanMode.ANSWER,
        operation=ChatPlanOperation.SUMMARIZE_RESOURCES,
        resource_type=ChatResourceType.WORK_ITEMS,
        scope={"project_id": "proj-guideai"},
        topic="agent execution",
        confidence=0.9,
    )

    plan = build_fetch_plan_from_chat_query_plan(
        chat_plan,
        allowed_project_ids={"proj-guideai", "proj-other"},
    )

    assert plan is not None
    assert len(plan.queries) == 1
    assert plan.queries[0].project_id == "proj-guideai"
    assert plan.queries[0].text_search == "agent execution"


def test_parse_workspace_fetch_plan_accepts_json_queries() -> None:
    raw = """
    {
      "rationale": "recent open tasks",
      "queries": [
        {
          "project_id": "proj-a",
          "limit": 10,
          "sort_by": "updated_at",
          "order": "desc",
          "status": "in_progress"
        }
      ]
    }
    """
    plan = parse_workspace_fetch_plan(raw)
    assert plan is not None
    assert len(plan.queries) == 1
    q = plan.queries[0]
    assert q.project_id == "proj-a"
    assert q.limit == 10
    assert q.sort_by == "updated_at"
    assert q.status == WorkItemStatus.IN_PROGRESS


def test_execute_fetch_plan_skips_unauthorized_project_and_dedupes() -> None:
    wi1 = SimpleNamespace(item_id="w1")
    wi_dup = SimpleNamespace(item_id="w1")

    board_service = MagicMock()
    board_service.list_work_items.return_value = [wi1, wi_dup]

    plan = WorkspaceFetchPlan(
        queries=[
            FetchQuerySpec(project_id="evil", limit=5),
            FetchQuerySpec(project_id="p1", limit=10),
        ],
        rationale="test",
    )

    rows, nq = execute_fetch_plan(
        board_service=board_service,
        org_id="org-1",
        allowed_project_ids={"p1"},
        plan=plan,
    )

    assert nq == 1
    assert len(rows) == 1
    assert rows[0].item_id == "w1"
    board_service.list_work_items.assert_called_once()


def test_run_planner_llm_classifies_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMPREALIZE_TARGETED_FETCH_PLANNER_RETRY_COUNT", "0")
    client = MagicMock()
    client.call.side_effect = Exception("Request timed out.")
    result = run_planner_llm(
        llm_client=client,
        inventory_summary="projects:\n- x",
        user_question="what next?",
        metadata={"llm_model_id": "test-model"},
    )
    assert result.plan is None
    assert result.failure_reason == "planner_timeout"
    assert result.error_class == "Exception"
    assert client.call.call_count == 1


def test_run_planner_llm_invalid_json_from_model() -> None:
    client = MagicMock()
    client.call.return_value = SimpleNamespace(content="not-json-at-all")
    result = run_planner_llm(
        llm_client=client,
        inventory_summary="x",
        user_question="q",
        metadata={"llm_model_id": "m"},
    )
    assert result.plan is None
    assert result.failure_reason == "invalid_or_empty_plan"


def test_run_planner_llm_uses_dedicated_planner_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMPREALIZE_TARGETED_FETCH_PLANNER_TIMEOUT_SEC", "33")
    # Module reads env at call time via _planner_timeout_sec
    client = MagicMock()
    raw = (
        '{"rationale": "t", "queries": ['
        '{"project_id": "p", "limit": 2, "sort_by": "updated_at", "order": "desc"}'
        "]}"
    )
    client.call.return_value = SimpleNamespace(content=raw)
    run_planner_llm(
        llm_client=client,
        inventory_summary="x",
        user_question="q",
        metadata={"llm_model_id": "m"},
    )
    cfg = client.call.call_args.kwargs.get("config")
    assert cfg is not None
    assert cfg.timeout == 33.0


def test_run_planner_llm_retries_once_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMPREALIZE_TARGETED_FETCH_PLANNER_RETRY_COUNT", "1")
    client = MagicMock()
    raw = (
        '{"rationale": "x", "queries": ['
        '{"project_id": "p", "limit": 2, "sort_by": "updated_at", "order": "desc"}'
        "]}"
    )
    client.call.side_effect = [Exception("Request timed out."), SimpleNamespace(content=raw)]
    result = run_planner_llm(
        llm_client=client,
        inventory_summary="x",
        user_question="q",
        metadata={"llm_model_id": "m"},
    )
    assert result.plan is not None
    assert client.call.call_count == 2


def test_run_planner_llm_retry_exhausted_after_two_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMPREALIZE_TARGETED_FETCH_PLANNER_RETRY_COUNT", "1")
    client = MagicMock()
    client.call.side_effect = [
        Exception("Request timed out."),
        Exception("Request timed out."),
    ]
    result = run_planner_llm(
        llm_client=client,
        inventory_summary="x",
        user_question="q",
        metadata={"llm_model_id": "m"},
    )
    assert result.plan is None
    assert result.failure_reason == "planner_timeout"
    assert client.call.call_count == 2


def test_run_planner_llm_retry_attempt_uses_stretched_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMPREALIZE_TARGETED_FETCH_PLANNER_RETRY_COUNT", "1")
    monkeypatch.setenv("AMPREALIZE_TARGETED_FETCH_PLANNER_TIMEOUT_SEC", "80")
    client = MagicMock()
    raw = (
        '{"rationale": "x", "queries": ['
        '{"project_id": "p", "limit": 2, "sort_by": "updated_at", "order": "desc"}'
        "]}"
    )
    client.call.side_effect = [Exception("Request timed out."), SimpleNamespace(content=raw)]
    run_planner_llm(
        llm_client=client,
        inventory_summary="x",
        user_question="q",
        metadata={"llm_model_id": "m"},
    )
    first_t = client.call.call_args_list[0].kwargs["config"].timeout
    second_t = client.call.call_args_list[1].kwargs["config"].timeout
    assert first_t == 80.0
    assert second_t == 100.0


def test_run_planner_llm_success_returns_plan() -> None:
    client = MagicMock()
    raw = """
    {
      "rationale": "test",
      "queries": [
        {"project_id": "proj-a", "limit": 3, "sort_by": "updated_at", "order": "desc"}
      ]
    }
    """
    client.call.return_value = SimpleNamespace(content=raw)
    result = run_planner_llm(
        llm_client=client,
        inventory_summary="x",
        user_question="q",
        metadata={"llm_model_id": "m"},
    )
    assert result.failure_reason is None
    assert result.plan is not None
    assert len(result.plan.queries) == 1
    assert result.plan.queries[0].project_id == "proj-a"
    assert result.planner_latency_ms is not None
    assert result.planner_attempts == 1
    assert result.planner_model_id == "nvidia-llama-3-3-70b-instruct"


def test_run_planner_llm_uses_env_planner_model_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMPREALIZE_TARGETED_FETCH_PLANNER_MODEL_ID", "fast-planner")
    client = MagicMock()
    raw = """
    {
      "rationale": "test",
      "queries": [
        {"project_id": "proj-a", "limit": 3, "sort_by": "updated_at", "order": "desc"}
      ]
    }
    """
    client.call.return_value = SimpleNamespace(content=raw)
    result = run_planner_llm(
        llm_client=client,
        inventory_summary="x",
        user_question="q",
        metadata={"llm_model_id": "slow-chat-model"},
    )
    assert result.planner_model_id == "fast-planner"
    assert client.call.call_args.kwargs.get("model") == "fast-planner"


def test_execute_fetch_plan_respects_global_row_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "amprealize.chat_workspace_targeted_fetch._MAX_TOTAL_ROWS",
        4,
        raising=False,
    )

    def _items_for_project(pid: str) -> list:
        return [SimpleNamespace(item_id=f"{pid}-{i}") for i in range(3)]

    board_service = MagicMock()

    def list_work_items(**kwargs: object) -> list:
        return _items_for_project(str(kwargs["project_id"]))

    board_service.list_work_items.side_effect = list_work_items

    plan = WorkspaceFetchPlan(
        queries=[
            FetchQuerySpec(project_id="p1", limit=10),
            FetchQuerySpec(project_id="p2", limit=10),
            FetchQuerySpec(project_id="p3", limit=10),
        ],
        rationale="multi",
    )
    rows, nq = execute_fetch_plan(
        board_service=board_service,
        org_id="org-1",
        allowed_project_ids={"p1", "p2", "p3"},
        plan=plan,
    )
    # Merge stops at row cap; queries_run counts specs merged before early return.
    assert len(rows) == 4
    assert nq == 2
    assert board_service.list_work_items.call_count == 3
