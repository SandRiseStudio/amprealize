"""Tests for governed chat action routing."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from amprealize.chat_action_router import (
    ChatActionCategory,
    ChatActionRisk,
    ChatRouteGateway,
    ChatRouteMode,
    ChatActionRouteRequest,
    ChatActionRouter,
    ChatWorkspaceIntent,
    LLMChatActionRouter,
    detect_chat_workspace_intent,
    enrich_chat_routing_metadata,
)
from amprealize.conversation_contracts import (
    ChatPermissionAction,
    ChatPermissionScope,
    ChatPermissionSurface,
    ConversationScope,
)

pytestmark = pytest.mark.unit


@dataclass
class _FakeLLMResponse:
    content: str


class _FakeLLMClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = []

    def call(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        return _FakeLLMResponse(self.content)


def test_preset_plan_routes_to_execution_planning_candidate():
    router = ChatActionRouter()

    result = router.route(
        ChatActionRouteRequest(
            message="/plan guideai-1057",
            conversation_scope=ConversationScope.WORK_ITEM_THREAD,
            project_id="proj-1",
            resource_links=[
                {"resource_type": "work_item", "resource_id": "guideai-1057"}
            ],
        )
    )

    candidate = result.primary
    assert candidate is not None
    assert candidate.category == ChatActionCategory.EXECUTION_PLANNING
    assert candidate.action_id == "execution.plan"
    assert candidate.preset == "/plan"
    assert candidate.confidence == 0.98
    assert candidate.permission_surface == ChatPermissionSurface.WORK_ITEM_THREAD
    assert candidate.permission_action == ChatPermissionAction.EXECUTE
    assert candidate.requires_approval is True
    assert candidate.requires_clarification is False
    assert ChatPermissionScope.PROJECT in candidate.required_scopes


def test_high_risk_execute_requires_approval_and_policy_context():
    router = ChatActionRouter()

    result = router.route(
        ChatActionRouteRequest(
            message="execute this work item",
            project_id="proj-1",
            resource_links=[
                {"resource_type": "work_item", "resource_id": "guideai-1057"}
            ],
        )
    )

    candidate = result.primary
    assert candidate is not None
    policy_context = candidate.to_policy_context()
    assert candidate.category == ChatActionCategory.EXECUTION_START
    assert candidate.risk == ChatActionRisk.HIGH
    assert candidate.requires_approval is True
    assert policy_context["chat_surface"] == "work_item_thread"
    assert policy_context["chat_action"] == "execute"
    assert policy_context["sensitive_operation"] is True


def test_group_chat_execution_uses_group_chat_permission_surface():
    router = ChatActionRouter()

    result = router.route(
        ChatActionRouteRequest(
            message="execute this with the coding agent",
            conversation_scope=ConversationScope.GROUP_CHAT,
            project_id="proj-1",
            conversation_id="conv-group",
            resource_links=[
                {"resource_type": "work_item", "resource_id": "guideai-1057"}
            ],
        )
    )

    candidate = result.primary
    assert candidate is not None
    assert candidate.category == ChatActionCategory.EXECUTION_START
    assert candidate.permission_surface == ChatPermissionSurface.GROUP_CHAT
    assert {
        ChatPermissionScope.CONVERSATION,
        ChatPermissionScope.PROJECT,
        ChatPermissionScope.AGENT,
    }.issubset(set(candidate.required_scopes))
    assert candidate.requires_approval is True
    assert candidate.metadata["conversation_scope"] == "group_chat"


def test_ambiguous_plan_and_execute_asks_for_clarification():
    router = ChatActionRouter()

    result = router.route(
        ChatActionRouteRequest(
            message="plan and execute guideai-1057",
            project_id="proj-1",
        )
    )

    assert result.requires_clarification is True
    assert result.clarification_prompt is not None
    assert len(result.candidates) >= 2
    assert {candidate.category for candidate in result.candidates} >= {
        ChatActionCategory.EXECUTION_PLANNING,
        ChatActionCategory.EXECUTION_START,
    }
    assert all(candidate.requires_clarification for candidate in result.candidates)


def test_work_management_routes_to_platform_action_scope():
    router = ChatActionRouter()

    result = router.route(
        ChatActionRouteRequest(
            message="create a bug for the broken gateway card",
            conversation_scope=ConversationScope.PROJECT_SPACE,
            project_id="proj-1",
        )
    )

    candidate = result.primary
    assert candidate is not None
    assert candidate.category == ChatActionCategory.WORK_MANAGEMENT
    assert candidate.permission_surface == ChatPermissionSurface.PLATFORM_ACTION
    assert candidate.permission_action == ChatPermissionAction.CREATE
    assert candidate.target_resource_type == "work_item"
    assert candidate.requires_clarification is False


def test_work_item_slot_followup_routes_work_management_without_mutation_keywords():
    router = ChatActionRouter()

    result = router.route(
        ChatActionRouteRequest(
            message="SmokeTestTitle",
            conversation_scope=ConversationScope.PROJECT_SPACE,
            project_id="proj-1",
            metadata={
                "work_item_slot_followup": True,
                "routing_prior_user_message": "Create a new task on the GuideAI project board",
            },
        )
    )

    candidate = result.primary
    assert candidate is not None
    assert candidate.category == ChatActionCategory.WORK_MANAGEMENT
    assert candidate.requires_clarification is False
    assert result.requires_clarification is False


def test_resource_count_question_routes_to_analysis_not_work_creation():
    router = ChatActionRouter()

    result = router.route(
        ChatActionRouteRequest(
            message="how many work items do i have on the guideai board?",
            conversation_scope=ConversationScope.PROJECT_SPACE,
            project_id="proj-1",
        )
    )

    candidate = result.primary
    assert candidate is not None
    assert candidate.category == ChatActionCategory.RESOURCE_ANALYSIS
    assert candidate.action_id == "resource.analyze"
    assert candidate.permission_action == ChatPermissionAction.READ
    assert candidate.requires_approval is False
    assert candidate.requires_clarification is False
    assert candidate.metadata["intent_class"] == "read_query"


def test_changed_behavior_question_routes_to_analysis_not_update():
    router = ChatActionRouter()

    result = router.route(ChatActionRouteRequest(message="what behaviors changed recently?"))

    candidate = result.primary
    assert candidate is not None
    assert candidate.category == ChatActionCategory.RESOURCE_ANALYSIS
    assert candidate.permission_action == ChatPermissionAction.READ


def test_observability_question_routes_to_read_analysis():
    router = ChatActionRouter()

    result = router.route(ChatActionRouteRequest(message="which tools fail most in observability traces?"))

    candidate = result.primary
    assert candidate is not None
    assert candidate.category == ChatActionCategory.RESOURCE_ANALYSIS
    assert candidate.action_id == "resource.analyze"
    assert candidate.permission_action == ChatPermissionAction.READ
    assert candidate.requires_approval is False


def test_unknown_message_defaults_to_read_synthesis_with_clarification():
    router = ChatActionRouter()

    result = router.route(ChatActionRouteRequest(message="maybe later"))

    candidate = result.primary
    assert candidate is not None
    assert result.requires_clarification is True
    assert candidate.category == ChatActionCategory.READ_SYNTHESIS
    assert candidate.requires_clarification is True


def test_cancel_run_routes_to_execution_cancel_not_start():
    router = ChatActionRouter()

    result = router.route(
        ChatActionRouteRequest(
            message="please cancel run for the coding agent",
            project_id="proj-1",
            resource_links=[
                {"resource_type": "work_item", "resource_id": "wi-42"}
            ],
        )
    )

    candidate = result.primary
    assert candidate is not None
    assert candidate.category == ChatActionCategory.EXECUTION_CANCEL
    assert candidate.action_id == "execution.cancel"


def test_slash_cancel_preset_routes_to_execution_cancel():
    router = ChatActionRouter()

    result = router.route(
        ChatActionRouteRequest(
            message="/cancel execution",
            project_id="proj-9",
            resource_links=[{"resource_type": "work_item", "resource_id": "wi-1"}],
        )
    )

    candidate = result.primary
    assert candidate is not None
    assert candidate.category == ChatActionCategory.EXECUTION_CANCEL
    assert candidate.preset == "/cancel"
    assert candidate.confidence == 0.98


    llm_client = _FakeLLMClient(
        """
        {
          "candidates": [
            {
              "action_id": "execution.start",
              "category": "execution_start",
              "permission_surface": "work_item_thread",
              "permission_action": "execute",
              "confidence": 1.4,
              "risk": "high",
              "target_resource_type": "run",
              "rationale": "User asked to start implementation."
            }
          ],
          "requires_clarification": false,
          "clarification_prompt": null
        }
        """
    )
    router = LLMChatActionRouter(llm_client=llm_client)

    result = router.route(
        ChatActionRouteRequest(
            message="please implement this",
            user_id="user-1",
            project_id="proj-1",
            resource_links=[
                {"resource_type": "work_item", "resource_id": "guideai-1057"}
            ],
        )
    )

    candidate = result.primary
    assert candidate is not None
    assert candidate.action_id == "execution.start"
    assert candidate.confidence == 1.0
    assert candidate.permission_surface == ChatPermissionSurface.WORK_ITEM_THREAD
    assert candidate.permission_action == ChatPermissionAction.EXECUTE
    assert ChatPermissionScope.PROJECT in candidate.required_scopes
    assert candidate.requires_approval is True
    assert candidate.metadata["route_mode"] == "llm"


def test_llm_router_falls_back_on_unknown_action_id():
    llm_client = _FakeLLMClient(
        """
        {
          "candidates": [
            {
              "action_id": "dangerous.unknown",
              "category": "execution_start",
              "permission_surface": "work_item_thread",
              "permission_action": "execute",
              "confidence": 0.99,
              "risk": "high"
            }
          ]
        }
        """
    )
    router = LLMChatActionRouter(llm_client=llm_client)

    result = router.route(
        ChatActionRouteRequest(
            message="execute this work item",
            project_id="proj-1",
            resource_links=[
                {"resource_type": "work_item", "resource_id": "guideai-1057"}
            ],
        )
    )

    candidate = result.primary
    assert candidate is not None
    assert candidate.action_id == "execution.start"
    assert candidate.metadata["route_mode"] == "deterministic"
    assert candidate.metadata["fallback_reason"] == "llm_route_failed"


def test_chat_route_gateway_uses_llm_mode_when_enabled():
    llm_client = _FakeLLMClient(
        """
        {
          "candidates": [
            {
              "action_id": "chat.read_synthesis",
              "category": "read_synthesis",
              "permission_surface": "global_chat",
              "permission_action": "read",
              "confidence": 0.92,
              "risk": "low",
              "rationale": "User is asking for information."
            }
          ]
        }
        """
    )
    llm_router = LLMChatActionRouter(llm_client=llm_client)
    gateway = ChatRouteGateway(llm_router=llm_router, mode=ChatRouteMode.LLM)

    result = gateway.route(ChatActionRouteRequest(message="what happened yesterday?"))

    candidate = result.primary
    assert candidate is not None
    assert candidate.metadata["route_mode"] == "llm"


def test_enrich_chat_routing_metadata_sets_hybrid_for_analytics_intent():
    meta = enrich_chat_routing_metadata({}, "How quickly do items move from backlog to in progress?")
    assert meta["chat_query_intent"] == ChatWorkspaceIntent.ANALYTICS_OR_RATE.value
    assert meta["chat_route_mode"] == ChatRouteMode.HYBRID.value


def test_enrich_chat_routing_metadata_respects_explicit_route_mode():
    meta = enrich_chat_routing_metadata(
        {"chat_route_mode": ChatRouteMode.DETERMINISTIC.value},
        "How quickly do items move from backlog to in progress?",
    )
    assert meta["chat_query_intent"] == ChatWorkspaceIntent.ANALYTICS_OR_RATE.value
    assert meta["chat_route_mode"] == ChatRouteMode.DETERMINISTIC.value


def test_detect_chat_workspace_intent_mutate_vs_list():
    assert detect_chat_workspace_intent("create a new work item") == ChatWorkspaceIntent.MUTATE.value
    assert detect_chat_workspace_intent("list my projects") == ChatWorkspaceIntent.LIST_INVENTORY.value


def test_detect_chat_workspace_intent_prioritize_today():
    assert detect_chat_workspace_intent("what should I work on today?") == ChatWorkspaceIntent.WORKSPACE_PRIORITIZE.value
    assert detect_chat_workspace_intent("Help me prioritize my backlog") == ChatWorkspaceIntent.WORKSPACE_PRIORITIZE.value


def test_detect_chat_workspace_intent_conversational_access():
    assert (
        detect_chat_workspace_intent("do you have access to my local project path files?")
        == ChatWorkspaceIntent.CONVERSATIONAL_NON_INVENTORY.value
    )
    assert detect_chat_workspace_intent("who are you?") == ChatWorkspaceIntent.CONVERSATIONAL_NON_INVENTORY.value


def test_enrich_chat_routing_metadata_sets_intent_for_conversational_without_forcing_hybrid_route():
    """Conversational intent skips inventory fast path; action routing stays deterministic by default."""
    meta = enrich_chat_routing_metadata({}, "what model are you?")
    assert meta["chat_query_intent"] == ChatWorkspaceIntent.CONVERSATIONAL_NON_INVENTORY.value
    assert "chat_route_mode" not in meta or meta.get("chat_route_mode") is None


# ---------------------------------------------------------------------------
# Transcript regression tests — these lock in the correct routing for the
# bad conversation that motivated the reliability plan.
# ---------------------------------------------------------------------------


def test_have_we_implemented_agent_execution_routes_to_read_not_execution_start():
    """'have we implemented agent execution?' is a polar question, not an execution command."""
    router = ChatActionRouter()
    result = router.route(
        ChatActionRouteRequest(
            message="From the GuideAI project, have we already implemented agent execution?",
            conversation_scope=ConversationScope.PROJECT_SPACE,
            project_id="proj-guideai",
        )
    )
    primary = result.primary
    assert primary is not None
    # Must NOT be EXECUTION_START for this phrasing.
    assert primary.category != ChatActionCategory.EXECUTION_START, (
        "Polar questions about capability must not trigger EXECUTION_START"
    )
    assert primary.requires_approval is False


def test_look_at_project_board_routes_to_read_not_execution_start():
    """'Look at the GuideAI project board...' is an inventory read, not an execution request."""
    router = ChatActionRouter()
    result = router.route(
        ChatActionRouteRequest(
            message="Look at the GuideAI project board and tell me about any work items that mention agent execution.",
            conversation_scope=ConversationScope.PROJECT_SPACE,
            project_id="proj-guideai",
        )
    )
    primary = result.primary
    assert primary is not None
    assert primary.category != ChatActionCategory.EXECUTION_START, (
        "Board read requests must not trigger execution"
    )
    assert primary.requires_approval is False


def test_polar_question_does_not_carry_requires_clarification_for_read_routes():
    """Read routes that can answer should not set requires_clarification=True."""
    router = ChatActionRouter()
    result = router.route(
        ChatActionRouteRequest(
            message="how many work items are in the GuideAI project?",
            conversation_scope=ConversationScope.PROJECT_SPACE,
            project_id="proj-guideai",
        )
    )
    primary = result.primary
    assert primary is not None
    assert primary.category == ChatActionCategory.RESOURCE_ANALYSIS
    assert primary.requires_clarification is False, (
        "Answerable read queries should not require clarification"
    )


def test_i_am_asking_you_a_question_routes_as_read_not_action():
    """Meta correction phrases should not re-trigger execution or action routing."""
    router = ChatActionRouter()
    result = router.route(
        ChatActionRouteRequest(
            message="I'm asking you a question, not asking you to execute anything.",
            conversation_scope=ConversationScope.PROJECT_SPACE,
        )
    )
    primary = result.primary
    if primary is not None:
        assert primary.category != ChatActionCategory.EXECUTION_START


def test_are_any_of_these_completed_routes_as_read():
    """Follow-up 'are any of these completed?' should route to read analysis, not execution."""
    router = ChatActionRouter()
    result = router.route(
        ChatActionRouteRequest(
            message="Are any of these completed?",
            conversation_scope=ConversationScope.PROJECT_SPACE,
            project_id="proj-guideai",
        )
    )
    if result.primary is not None:
        assert result.primary.category != ChatActionCategory.EXECUTION_START
