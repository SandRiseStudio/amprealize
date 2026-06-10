"""Tests for the fast bounded chat query planner."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from amprealize.chat_query_planner import (
    ChatPlanLatencyTier,
    ChatPlanMode,
    ChatPlanOperation,
    ChatQueryPlan,
    ChatQueryPlanner,
    ChatQueryPlanValidator,
    ChatResourceType,
    chat_plan_to_resource_query_plan,
    render_chat_plan_resource_answer,
)
from amprealize.resource_analysis import (
    ResourceAnalysisAnswer,
    ResourceAnalysisIntent,
    ResourceAnalysisService,
)


class _Resp:
    def __init__(self, content: str) -> None:
        self.content = content


class _LLM:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[dict] = []

    def call(self, messages, **kwargs):  # noqa: ANN001, ANN003
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return _Resp(self.content)


def test_parse_strict_plan_for_guideai_board_progress() -> None:
    planner = ChatQueryPlanner()
    llm = _LLM(
        """
        {
          "mode": "answer",
          "operation": "summarize_resources",
          "resource_type": "work_items",
          "scope": {"project_name": "GuideAI"},
          "topic": "agent execution",
          "metrics": ["status_breakdown", "matching_items"],
          "latency_tier": "fast",
          "requires_approval": false,
          "confidence": 0.88
        }
        """
    )

    result = planner.plan_sync(
        user_message="from the guideai project, have we already implemented agent execution?",
        inventory_summary="Projects: GuideAI (proj-guideai)",
        scope_hints={},
        llm_client=llm,
        metadata={"llm_model_id": "test-model"},
        user_id="u1",
    )

    assert result.plan is not None
    assert result.plan.mode == ChatPlanMode.ANSWER
    assert result.plan.operation == ChatPlanOperation.SUMMARIZE_RESOURCES
    assert result.plan.resource_type == ChatResourceType.WORK_ITEMS
    assert result.plan.scope["project_name"] == "GuideAI"
    assert result.plan.topic == "agent execution"
    assert "status_breakdown" in result.plan.metrics
    assert result.plan.latency_tier == ChatPlanLatencyTier.FAST
    assert result.source == "llm"


def test_invalid_llm_operation_falls_back_to_clarification() -> None:
    planner = ChatQueryPlanner()
    llm = _LLM(
        """
        {
          "mode": "answer",
          "operation": "drop_database",
          "resource_type": "work_items",
          "confidence": 0.9
        }
        """
    )

    result = planner.plan_sync(
        user_message="summarize my work items",
        inventory_summary="Projects: GuideAI (proj-guideai)",
        scope_hints={},
        llm_client=llm,
        metadata={},
        user_id="u1",
    )

    assert result.plan is None
    assert result.validation.valid is False
    assert result.validation.requires_clarification is True
    assert "unsupported" in result.validation.reason.lower()


def test_no_llm_fallback_lists_projects_without_waiting_for_model() -> None:
    planner = ChatQueryPlanner()

    result = planner.plan_sync(
        user_message="list my projects",
        inventory_summary="Projects: GuideAI (proj-guideai)",
        scope_hints={},
        llm_client=None,
        metadata={},
        user_id="u1",
    )

    assert result.plan is not None
    assert result.source == "fallback"
    assert result.plan.operation == ChatPlanOperation.LIST_RESOURCES
    assert result.plan.resource_type == ChatResourceType.PROJECTS
    assert result.plan.latency_tier == ChatPlanLatencyTier.INSTANT


def test_no_llm_fallback_summarizes_implementation_status_by_topic() -> None:
    planner = ChatQueryPlanner()

    result = planner.plan_sync(
        user_message="from the guideai project, have we already implemented agent execution?",
        inventory_summary="Projects: GuideAI (proj-guideai)",
        scope_hints={"project_name": "GuideAI"},
        llm_client=None,
        metadata={},
        user_id="user-1",
    )

    assert result.plan is not None
    assert result.source == "fallback"
    assert result.plan.operation == ChatPlanOperation.SUMMARIZE_RESOURCES
    assert result.plan.resource_type == ChatResourceType.WORK_ITEMS
    assert result.plan.scope["project_name"] == "GuideAI"
    assert result.plan.topic == "agent execution"
    assert result.plan.latency_tier == ChatPlanLatencyTier.INSTANT
    assert "status_breakdown" in result.plan.metrics


def test_data_science_question_can_choose_analysis_tier() -> None:
    planner = ChatQueryPlanner()
    llm = _LLM(
        """
        {
          "mode": "deep_analysis",
          "operation": "compare_resources",
          "resource_type": "work_items",
          "scope": {"project_name": "GuideAI"},
          "topic": "cycle time and blockers",
          "metrics": ["velocity", "blockers"],
          "latency_tier": "analysis",
          "requires_approval": false,
          "confidence": 0.82
        }
        """
    )

    result = planner.plan_sync(
        user_message="Which GuideAI work items are slowing velocity and what blockers explain it?",
        inventory_summary="Projects: GuideAI (proj-guideai)",
        scope_hints={},
        llm_client=llm,
        metadata={"llm_model_id": "test-model"},
        user_id="u1",
    )

    assert result.plan is not None
    assert result.plan.mode == ChatPlanMode.DEEP_ANALYSIS
    assert result.plan.operation == ChatPlanOperation.COMPARE_RESOURCES
    assert result.plan.resource_type == ChatResourceType.WORK_ITEMS
    assert result.plan.latency_tier == ChatPlanLatencyTier.ANALYSIS
    assert result.plan.metrics == ["velocity", "blockers"]


def test_planner_call_matches_llm_client_signature_without_timeout_kwarg() -> None:
    planner = ChatQueryPlanner(planner_timeout_seconds=0.25)

    class _StrictLLM:
        def call(
            self,
            messages,  # noqa: ANN001
            *,
            model=None,  # noqa: ANN001
            temperature=None,  # noqa: ANN001
            max_tokens=None,  # noqa: ANN001
            config=None,  # noqa: ANN001
            project_id=None,  # noqa: ANN001
            org_id=None,  # noqa: ANN001
            user_id=None,  # noqa: ANN001
            prefer_user_credential=False,  # noqa: ANN001
            execution_observability=None,  # noqa: ANN001
            actor=None,  # noqa: ANN001
        ):
            assert config is not None
            assert config.timeout == 0.25
            return _Resp(
                '{"mode":"answer","operation":"summarize_resources",'
                '"resource_type":"work_items","topic":"agent execution",'
                '"metrics":["status_breakdown"],"confidence":0.9}'
            )

    result = planner.plan_sync(
        user_message="from guideai, have we implemented agent execution?",
        inventory_summary="Projects: GuideAI (proj-guideai)",
        scope_hints={},
        llm_client=_StrictLLM(),
        metadata={"llm_model_id": "test-model"},
        user_id="u1",
    )

    assert result.plan is not None
    assert result.source == "llm"
    telemetry = result.telemetry_payload()
    assert telemetry["requested_model_id"] == "test-model"
    assert telemetry["planner_timeout_seconds"] == 0.25


def test_planner_failure_telemetry_includes_resolved_model_and_error() -> None:
    planner = ChatQueryPlanner(planner_timeout_seconds=0.25)

    class _FailingLLM:
        def call(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise RuntimeError("planner timed out after 250ms")

    result = planner.plan_sync(
        user_message="from guideai, have we implemented agent execution?",
        inventory_summary="Projects: GuideAI (proj-guideai)",
        scope_hints={},
        llm_client=_FailingLLM(),
        metadata={"llm_model_id": "test-model"},
        user_id="u1",
    )

    telemetry = result.telemetry_payload()
    assert result.source == "fallback"
    assert telemetry["fallback_reason"] == "RuntimeError"
    assert telemetry["error_type"] == "RuntimeError"
    assert telemetry["error_message"] == "planner timed out after 250ms"
    assert telemetry["requested_model_id"] == "test-model"
    assert telemetry["planner_timeout_seconds"] == 0.25


def test_validator_requires_approval_for_action_plans() -> None:
    plan = ChatQueryPlan(
        mode=ChatPlanMode.ACTION,
        operation=ChatPlanOperation.START_ACTION,
        resource_type=ChatResourceType.WORK_ITEMS,
        requires_approval=False,
        confidence=0.91,
    )

    validation = ChatQueryPlanValidator().validate(plan, accessible_project_ids={"proj-guideai"})

    assert validation.valid is False
    assert validation.requires_approval is True
    assert "approval" in validation.reason.lower()


def test_validator_rejects_inaccessible_project_scope() -> None:
    plan = ChatQueryPlan(
        mode=ChatPlanMode.ANSWER,
        operation=ChatPlanOperation.SUMMARIZE_RESOURCES,
        resource_type=ChatResourceType.WORK_ITEMS,
        scope={"project_id": "proj-other"},
        confidence=0.91,
    )

    validation = ChatQueryPlanValidator().validate(plan, accessible_project_ids={"proj-guideai"})

    assert validation.valid is False
    assert "accessible" in validation.reason.lower()


def test_chat_plan_to_resource_plan_adds_topic_text_search() -> None:
    chat_plan = ChatQueryPlan(
        mode=ChatPlanMode.ANSWER,
        operation=ChatPlanOperation.SUMMARIZE_RESOURCES,
        resource_type=ChatResourceType.WORK_ITEMS,
        topic="agent execution",
        metrics=["status_breakdown", "matching_items"],
        confidence=0.9,
    )

    resource_plan = chat_plan_to_resource_query_plan(chat_plan)

    assert resource_plan.intent == ResourceAnalysisIntent.SUMMARIZE
    assert resource_plan.resource_type == "work_items"
    assert resource_plan.filters["text_search"] == "agent execution"


def test_render_chat_plan_resource_answer_prioritizes_board_progress() -> None:
    chat_plan = ChatQueryPlan(
        mode=ChatPlanMode.ANSWER,
        operation=ChatPlanOperation.SUMMARIZE_RESOURCES,
        resource_type=ChatResourceType.WORK_ITEMS,
        scope={"project_name": "GuideAI"},
        topic="agent execution",
        metrics=["status_breakdown", "matching_items"],
        confidence=0.9,
    )
    resource_plan = chat_plan_to_resource_query_plan(chat_plan)
    answer = ResourceAnalysisAnswer(
        content="fallback content",
        answer_type="work_items.summary",
        query_plan=resource_plan,
        structured_payload={"card_kind": "resource_analysis"},
        source_rows=[
            {"item_id": "wi-1", "title": "Agent execution phases", "status": "done"},
            {"item_id": "wi-2", "title": "Agent execution UI", "status": "in_progress"},
            {"item_id": "wi-3", "title": "Agent execution QA", "status": "backlog"},
        ],
    )

    rendered = render_chat_plan_resource_answer(chat_plan, answer)

    assert "For GuideAI, I found 3 work items related to agent execution." in rendered.content
    assert "Status breakdown:" in rendered.content
    assert "done: 1" in rendered.content
    assert "in_progress: 1" in rendered.content
    assert "backlog: 1" in rendered.content
    assert "Agent execution phases" in rendered.content
    assert rendered.structured_payload["chat_query_plan"]["operation"] == "summarize_resources"
    assert rendered.structured_payload["chat_query_result"]["status_counts"]["done"] == 1


def test_resource_executor_runs_chat_plan_with_topic_filter() -> None:
    chat_plan = ChatQueryPlan(
        mode=ChatPlanMode.ANSWER,
        operation=ChatPlanOperation.SUMMARIZE_RESOURCES,
        resource_type=ChatResourceType.WORK_ITEMS,
        scope={"project_id": "proj-guideai"},
        topic="agent execution",
        metrics=["status_breakdown", "matching_items"],
        confidence=0.9,
    )
    resource_plan = chat_plan_to_resource_query_plan(chat_plan)

    answer = ResourceAnalysisService().answer_plan_sync(
        query="from the guideai project, have we already implemented agent execution?",
        query_plan=resource_plan,
        inventory={
            "projects": [{"id": "proj-guideai", "name": "GuideAI"}],
            "work_items_by_project": {
                "proj-guideai": [
                    {"id": "wi-1", "title": "Agent execution phases", "status": "done"},
                    {"id": "wi-2", "title": "Agent execution UI", "status": "in_progress"},
                    {"id": "wi-3", "title": "Fix login page", "status": "done"},
                ]
            },
        },
        scope_hints={"project_id": "proj-guideai"},
    )

    assert answer is not None
    titles = {row["title"] for row in answer.source_rows}
    assert titles == {"Agent execution phases", "Agent execution UI"}
