"""Golden trace regression tests for GUIDEAI-1122 LLM and MCP paths."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List

import pytest

from amprealize.context_composer import ComposedContext, ContextFragment, DataSourceType
from amprealize.conversation_contracts import ActorType
from amprealize.mcp_server import MCPServer
from amprealize.platform_management_actions import (
    PlatformManagementActionService,
    PlatformResourceType,
)
from amprealize.services.conversation_reply_service import (
    ConversationReplyService,
    ReplyRequest,
)
from amprealize.telemetry import InMemoryTelemetrySink, TelemetryClient
from tests.fixtures.chat_answer_golden_traces import assert_chat_trace_fields, assert_event_types_subsequence
from tests.fixtures.llm_mcp_golden_traces import (
    assert_chat_trace_exporter_parity,
    last_telemetry_event_for_event_type,
    get_llm_mcp_scenario,
)

pytestmark = pytest.mark.unit


class _ArchitectureComposer:
    async def compose(self, **kwargs: Any) -> ComposedContext:
        return ComposedContext(
            composed_text="Amprealize uses chat, MCP, REST, and board surfaces.",
            total_tokens=9,
            fragments_included=[],
            fragments_excluded=[],
            sources_included=["docs:architecture"],
            token_allocation={},
            budget_utilization=0.1,
            composition_time_ms=1.0,
        )


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
            "work_items_by_project": {"proj-guideai": []},
            "agent_assignments": [],
            "runs": [],
        }
        fragment = ContextFragment(
            source=DataSourceType.WORKSPACE_INVENTORY,
            content="GuideAI project board",
            token_count=4,
            metadata={"inventory": inventory, "source_counts": {"projects": 1, "boards": 1}},
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


@dataclass
class _FakeLLMResponse:
    content: str


class _FakeLLMClient:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def call(self, messages: List[Dict[str, str]], **kwargs: Any) -> _FakeLLMResponse:
        self.calls.append({"messages": messages, **kwargs})
        return _FakeLLMResponse("Amprealize coordinates product work across chat and execution surfaces.")


class _FailingLLMClient:
    def call(self, messages: List[Dict[str, str]], **kwargs: Any) -> _FakeLLMResponse:
        raise AssertionError("LLM should not be called for platform-action golden trace")


class _FakePlatformWorkItemService:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def create_work_item(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append(payload)
        return {
            "item_id": "wi-golden-mcp",
            "title": payload["title"],
            "item_type": payload["item_type"],
            "project_id": payload["project_id"],
            "board_id": payload["board_id"],
        }


class _FakeConversationService:
    def __init__(self) -> None:
        self.messages: List[Dict[str, Any]] = []
        self.participant_adds: List[Dict[str, Any]] = []

    def add_participant(self, conversation_id: str, **kwargs: Any) -> None:
        self.participant_adds.append({"conversation_id": conversation_id, **kwargs})

    def send_message(self, conversation_id: str, **kwargs: Any) -> None:
        self.messages.append({"conversation_id": conversation_id, **kwargs})


@pytest.mark.asyncio
async def test_llm_answer_golden_trace_exports_same_chat_trace_as_stored_reply():
    scenario = get_llm_mcp_scenario("llm_read_synthesis")
    sink = InMemoryTelemetrySink()
    conversation_service = _FakeConversationService()
    llm_client = _FakeLLMClient()
    service = ConversationReplyService(
        context_composer=_ArchitectureComposer(),
        conversation_service=conversation_service,
        llm_client=llm_client,
        telemetry=TelemetryClient(sink=sink),
    )

    result = await service.generate_reply(
        ReplyRequest(
            conversation_id="conv-llm-golden",
            user_message_id="msg-user-llm",
            user_message_content=scenario.user_message_content,
            user_id="user-golden",
            metadata={
                "conversation_scope": "global_user_home",
                "llm_model_id": "nvidia-deepseek-v4-flash",
            },
        )
    )

    assert result.success is True
    assert len(llm_client.calls) == 1
    assert_event_types_subsequence(sink.events, scenario.expected_event_types)
    message = conversation_service.messages[0]
    assert message["sender_type"] == ActorType.AGENT
    assert "direct_answer" not in message["metadata"]
    trace = message["metadata"]["chat_trace"]
    assert_chat_trace_fields(trace)
    assert trace["route_action_id"] == scenario.expected_route_action_id
    assert trace["route_category"] == scenario.expected_route_category
    assert trace["answer_path"] == "llm"
    assert_chat_trace_exporter_parity(
        stored_trace=trace,
        telemetry_event=last_telemetry_event_for_event_type(sink.events, "conversation_reply.generated"),
    )


@pytest.mark.asyncio
async def test_platform_action_golden_trace_exports_same_chat_trace_and_outcome():
    scenario = get_llm_mcp_scenario("platform_action_work_item_create")
    sink = InMemoryTelemetrySink()
    conversation_service = _FakeConversationService()
    platform = _FakePlatformWorkItemService()
    service = ConversationReplyService(
        context_composer=_InventoryComposer(),
        conversation_service=conversation_service,
        llm_client=_FailingLLMClient(),
        telemetry=TelemetryClient(sink=sink),
        platform_management_service=PlatformManagementActionService(
            services={PlatformResourceType.WORK_ITEM: platform},
        ),
    )

    result = await service.generate_reply(
        ReplyRequest(
            conversation_id="conv-platform-golden",
            user_message_id="msg-user-platform",
            user_message_content=scenario.user_message_content,
            user_id="user-golden",
            metadata={
                "conversation_scope": "global_user_home",
                "llm_model_id": "nvidia-deepseek-v4-flash",
            },
        )
    )

    assert result.success is True
    assert platform.calls[0]["title"] == "Golden MCP trace"
    assert_event_types_subsequence(sink.events, scenario.expected_event_types)
    message = conversation_service.messages[0]
    assert message["metadata"]["direct_answer_type"] == "platform_action_result"
    assert message["structured_payload"]["type"] == "platform_action_result"
    assert message["structured_payload"]["data"]["result"]["item_id"] == "wi-golden-mcp"
    trace = message["metadata"]["chat_trace"]
    assert trace["route_action_id"] == scenario.expected_route_action_id
    assert trace["route_category"] == scenario.expected_route_category
    assert trace["answer_path"] == scenario.expected_answer_path
    assert trace["answer_type"] == scenario.expected_answer_type
    assert_chat_trace_exporter_parity(
        stored_trace=trace,
        telemetry_event=last_telemetry_event_for_event_type(sink.events, "conversation_reply.generated"),
    )


@pytest.mark.asyncio
async def test_mcp_resource_analysis_golden_trace_payload_is_exporter_safe(monkeypatch: pytest.MonkeyPatch):
    server = MCPServer()
    server._session_context.user_id = "test-user"
    server._session_context.auth_method = "device_flow"
    server._session_context.is_admin = True
    server._session_context.granted_scopes = {"*"}
    server._session_context.expires_at = datetime.utcnow() + timedelta(hours=1)

    async def _fake_analyze(params: Dict[str, Any]) -> Dict[str, Any]:
        assert params["query"] == "how many work items are blocked?"
        return {
            "success": True,
            "content": "You have 1 work item in this workspace.",
            "answer_type": "work_items.count",
            "query_plan": {"intent": "count", "resource_type": "work_items"},
            "rows": [{"item_id": "wi-1", "title": "Blocked item"}],
            "metadata": {
                "analysis_mode": "deterministic",
                "row_count": 1,
                "surface": "mcp",
            },
        }

    monkeypatch.setattr(server, "_handle_resources_analyze_tool", _fake_analyze)

    response = json.loads(
        await server._dispatch_tool_call(
            "call-golden-mcp",
            "resources_analyze",
            {"query": "how many work items are blocked?"},
        )
    )
    payload = json.loads(response["result"]["content"][0]["text"])

    assert payload["success"] is True
    assert payload["answer_type"] == "work_items.count"
    assert payload["query_plan"]["resource_type"] == "work_items"
    assert payload["metadata"]["surface"] == "mcp"
    json.dumps(response)
    json.dumps(payload)
