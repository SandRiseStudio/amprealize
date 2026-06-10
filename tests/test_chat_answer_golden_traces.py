"""Golden trace regression tests for GUIDEAI-1121 chat answer paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

import pytest

from amprealize.context_composer import ComposedContext, ContextFragment, DataSourceType
from amprealize.conversation_contracts import ActorType
from amprealize.services.conversation_reply_service import (
    ConversationReplyService,
    ReplyRequest,
)
from amprealize.telemetry import InMemoryTelemetrySink, TelemetryClient
from tests.fixtures.chat_answer_golden_traces import (
    assert_chat_trace_fields,
    assert_event_types_subsequence,
    assert_no_llm_generation_events,
    get_chat_answer_scenario,
)

pytestmark = pytest.mark.unit


class _InventoryComposer:
    async def compose(self, **kwargs: Any) -> ComposedContext:
        inventory = {
            "projects": [
                {
                    "project_id": "proj-guideai",
                    "name": "GuideAI",
                    "slug": "guideai",
                }
            ],
            "boards_by_project": {
                "proj-guideai": [
                    {
                        "board_id": "board-guideai",
                        "project_id": "proj-guideai",
                        "name": "GuideAI project board",
                        "is_default": True,
                    }
                ]
            },
            "work_items_by_project": {
                "proj-guideai": [
                    {
                        "item_id": "wi-chat-handoff-1",
                        "title": "Implement execution handoff",
                        "status": "in_progress",
                        "board_id": "board-guideai",
                    }
                ]
            },
            "agent_assignments": [],
            "runs": [
                {
                    "run_id": "run-chat-handoff-1",
                    "work_item_id": "wi-chat-handoff-1",
                    "status": "running",
                }
            ],
        }
        fragment = ContextFragment(
            source=DataSourceType.WORKSPACE_INVENTORY,
            content="GuideAI project board",
            token_count=4,
            metadata={
                "inventory": inventory,
                "source_counts": {"projects": 1, "boards": 1, "work_items": 1, "runs": 1},
            },
        )
        return ComposedContext(
            composed_text="## Accessible Workspace Inventory\nProjects:\n- GuideAI [proj-guideai]",
            total_tokens=15,
            fragments_included=[fragment],
            fragments_excluded=[],
            sources_included=["workspace_inventory"],
            token_allocation={},
            budget_utilization=0.1,
            composition_time_ms=1.0,
        )


class _ExecutionHandoffComposer:
    async def compose(self, **kwargs: Any) -> ComposedContext:
        return ComposedContext(
            composed_text=(
                "Linked work item wi-chat-handoff-1 already has run "
                "run-chat-handoff-1."
            ),
            total_tokens=10,
            fragments_included=[],
            fragments_excluded=[],
            sources_included=["work_item:wi-chat-handoff-1", "run:run-chat-handoff-1"],
            token_allocation={},
            budget_utilization=0.1,
            composition_time_ms=1.0,
        )


@dataclass
class _FakeLLMResponse:
    content: str


class _FakeLLMClient:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def call(self, messages: List[Dict[str, str]], **kwargs: Any) -> _FakeLLMResponse:
        self.calls.append({"messages": messages, **kwargs})
        return _FakeLLMResponse("I linked this reply to the existing execution trace.")


class _FailingLLMClient:
    def call(self, messages: List[Dict[str, str]], **kwargs: Any) -> _FakeLLMResponse:
        raise AssertionError("LLM should not be called for deterministic answers")


class _FakeConversationService:
    def __init__(self) -> None:
        self.messages: List[Dict[str, Any]] = []
        self.participant_adds: List[Dict[str, Any]] = []

    def add_participant(self, conversation_id: str, **kwargs: Any) -> None:
        self.participant_adds.append({"conversation_id": conversation_id, **kwargs})

    def list_messages(
        self,
        conversation_id: str,
        *,
        user_id: str | None = None,
        org_id: str | None = None,
        include_thread_replies: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[List[Dict[str, Any]], int, bool]:
        """Match ConversationService.list_messages; golden tests use no persisted history."""
        return ([], 0, False)

    def send_message(self, conversation_id: str, **kwargs: Any) -> None:
        self.messages.append({"conversation_id": conversation_id, **kwargs})


@pytest.mark.asyncio
async def test_deterministic_answer_golden_trace_is_queryable_without_llm_generation():
    scenario = get_chat_answer_scenario("deterministic_workspace_inventory")
    sink = InMemoryTelemetrySink()
    conversation_service = _FakeConversationService()
    service = ConversationReplyService(
        context_composer=_InventoryComposer(),
        conversation_service=conversation_service,
        llm_client=_FailingLLMClient(),
        telemetry=TelemetryClient(sink=sink),
    )

    result = await service.generate_reply(
        ReplyRequest(
            conversation_id="conv-chat-golden",
            user_message_id="msg-user-deterministic",
            user_message_content=scenario.user_message_content,
            user_id="user-golden",
            metadata={
                "conversation_scope": "global_user_home",
                "llm_model_id": "nvidia-deepseek-v4-flash",
            },
        )
    )

    assert result.success is True
    assert_event_types_subsequence(sink.events, scenario.expected_event_types)
    assert_no_llm_generation_events(sink.events)
    message = conversation_service.messages[0]
    assert message["sender_type"] == ActorType.AGENT
    assert message["metadata"]["direct_answer"] is True
    trace = message["metadata"]["chat_trace"]
    assert_chat_trace_fields(trace)
    assert trace["route_action_id"] == scenario.expected_route_action_id
    assert trace["route_category"] == scenario.expected_route_category
    assert trace["answer_path"] == scenario.expected_answer_path
    assert trace["answer_type"] == scenario.expected_answer_type
    generated_event = next(
        event for event in sink.events if event.event_type == "conversation_reply.generated"
    )
    assert generated_event.payload["chat_trace"]["trace_id"] == trace["trace_id"]
    assert generated_event.payload["chat_trace"]["answer_path"] == "deterministic"


@pytest.mark.asyncio
async def test_execution_handoff_golden_trace_links_run_without_duplicate_execution_events():
    scenario = get_chat_answer_scenario("execution_handoff_reply")
    sink = InMemoryTelemetrySink()
    conversation_service = _FakeConversationService()
    llm_client = _FakeLLMClient()
    service = ConversationReplyService(
        context_composer=_ExecutionHandoffComposer(),
        conversation_service=conversation_service,
        llm_client=llm_client,
        telemetry=TelemetryClient(sink=sink),
    )

    result = await service.generate_reply(
        ReplyRequest(
            conversation_id="conv-chat-golden",
            user_message_id="msg-user-execution-handoff",
            user_message_content=scenario.user_message_content,
            user_id="user-golden",
            project_id="proj-guideai",
            work_item_id=scenario.work_item_id,
            run_id=scenario.run_id,
            metadata={
                "conversation_scope": "project_space",
                "llm_model_id": "nvidia-deepseek-v4-flash",
                "resource_links": [
                    {
                        "resource_type": "work_item",
                        "resource_id": scenario.work_item_id,
                    }
                ],
            },
        )
    )

    assert result.success is True
    assert len(llm_client.calls) == 1
    assert_event_types_subsequence(sink.events, scenario.expected_event_types)
    assert not any(event.event_type.startswith("execution.") for event in sink.events)
    message = conversation_service.messages[0]
    assert message["metadata"]["execution_observability"]["run_id"] == scenario.run_id
    assert message["metadata"]["execution_observability"]["work_item_id"] == scenario.work_item_id
    assert llm_client.calls[0]["execution_observability"]["run_id"] == scenario.run_id
    assert llm_client.calls[0]["execution_observability"]["surface"] == "chat"
    trace = message["metadata"]["chat_trace"]
    assert_chat_trace_fields(trace)
    assert trace["route_action_id"] == scenario.expected_route_action_id
    assert trace["route_category"] == scenario.expected_route_category
    assert trace["answer_path"] == scenario.expected_answer_path
    assert trace["run_id"] == scenario.run_id
    assert trace["work_item_id"] == scenario.work_item_id
    generated_event = next(
        event for event in sink.events if event.event_type == "conversation_reply.generated"
    )
    assert generated_event.payload["chat_trace"]["run_id"] == scenario.run_id
    assert generated_event.payload["chat_trace"]["work_item_id"] == scenario.work_item_id
