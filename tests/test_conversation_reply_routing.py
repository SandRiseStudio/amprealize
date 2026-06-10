from __future__ import annotations

from dataclasses import dataclass
import inspect

import pytest

from amprealize.chat_action_router import (
    ChatActionCandidate,
    ChatActionCategory,
    ChatActionRouteResult,
    ChatActionRisk,
    ChatPermissionAction,
    ChatPermissionScope,
    ChatPermissionSurface,
)
from amprealize.context_composer import ComposedContext, ContextFragment, DataSourceType
from amprealize.conversation_contracts import ActorType, Message, MessageType
from amprealize.conversation_event_hub import (
    EVENT_COMPLETE,
    EVENT_REPLY_COMPLETE,
    EVENT_REPLY_STARTED,
    EVENT_REPLY_STEP,
)
from amprealize.services.conversation_reply_service import (
    ConversationReplyService,
    ReplyRequest,
)
import amprealize.services.conversation_reply_service as reply_service_module
from amprealize.llm.types import LLMResponse, ProviderType, StreamChunk, StreamChunkType
from amprealize.observability_analytics import GovernedObservabilityQueryService
from amprealize.observability_chat import ObservabilityChatAnswerService
from amprealize.session_audit import GovernedChatAuditLogger
from amprealize.platform_management_actions import (
    PlatformManagementActionService,
    PlatformResourceType,
)
from amprealize.telemetry import InMemoryTelemetrySink, TelemetryClient, TelemetryEvent

pytestmark = pytest.mark.unit


class _FakeComposer:
    def __init__(self) -> None:
        self.calls = []

    async def compose(self, **kwargs):
        self.calls.append(kwargs)
        return ComposedContext(
            composed_text="Project context",
            total_tokens=12,
            fragments_included=[],
            fragments_excluded=[],
            sources_included=["work_item:guideai-1"],
            token_allocation={},
            budget_utilization=0.1,
            composition_time_ms=1.0,
        )


class _EmptyComposer:
    async def compose(self, **kwargs):
        return ComposedContext(
            composed_text="",
            total_tokens=0,
            fragments_included=[],
            fragments_excluded=[],
            sources_included=[],
            token_allocation={},
            budget_utilization=0.0,
            composition_time_ms=1.0,
        )


class _FallbackComposer:
    def __init__(self) -> None:
        self.calls = []

    async def compose(self, **kwargs):
        self.calls.append(kwargs)
        return ComposedContext(
            composed_text="## Accessible Workspace Inventory\nProjects:\n- GuideAI [proj-1]",
            total_tokens=15,
            fragments_included=[],
            fragments_excluded=[],
            sources_included=["workspace_inventory"],
            token_allocation={},
            budget_utilization=0.1,
            composition_time_ms=1.0,
        )


class _InventoryComposer:
    async def compose(self, **kwargs):
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


class _InventoryWithoutBoardsComposer:
    async def compose(self, **kwargs):
        inventory = {
            "projects": [
                {
                    "project_id": "proj-guideai",
                    "name": "GuideAI",
                    "slug": "guideai",
                }
            ],
            "boards_by_project": {"proj-guideai": []},
            "work_items_by_project": {"proj-guideai": []},
            "agent_assignments": [],
            "runs": [],
        }
        fragment = ContextFragment(
            source=DataSourceType.WORKSPACE_INVENTORY,
            content="GuideAI project",
            token_count=3,
            metadata={"inventory": inventory, "source_counts": {"projects": 1, "boards": 0}},
        )
        return ComposedContext(
            composed_text="## Accessible Workspace Inventory\nProjects:\n- GuideAI [proj-guideai]",
            total_tokens=12,
            fragments_included=[fragment],
            fragments_excluded=[],
            sources_included=["workspace_inventory"],
            token_allocation={},
            budget_utilization=0.1,
            composition_time_ms=1.0,
        )


class _InventoryWithWorkItemsComposer:
    async def compose(self, **kwargs):
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
                        "name": "GuideAI board",
                        "is_default": True,
                    }
                ]
            },
            "work_items_by_project": {
                "proj-guideai": [
                    {
                        "item_id": "wi-1",
                        "title": "Fix chat routing",
                        "status": "todo",
                        "board_id": "board-guideai",
                    },
                    {
                        "item_id": "wi-2",
                        "title": "Add analyst tool",
                        "status": "blocked",
                        "board_id": "board-guideai",
                    },
                ]
            },
            "agent_assignments": [],
            "runs": [],
        }
        fragment = ContextFragment(
            source=DataSourceType.WORKSPACE_INVENTORY,
            content="GuideAI board work items",
            token_count=5,
            metadata={"inventory": inventory, "source_counts": {"projects": 1, "boards": 1, "work_items": 2}},
        )
        return ComposedContext(
            composed_text="## Accessible Workspace Inventory\nGuideAI board has work items",
            total_tokens=20,
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
        self.calls = []

    def call(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        return _FakeLLMResponse("Done.")


class _FailingLLMClient:
    def call(self, messages, **kwargs):
        raise AssertionError("LLM should not be called for governed direct action")


class _FakePlatformWorkItemService:
    def __init__(self) -> None:
        self.calls = []

    def list_boards(self, payload):
        self.calls.append({"operation": "list_boards", **payload})
        return [
            {
                "board_id": "board-guideai-discovered",
                "project_id": payload["project_id"],
                "name": "GuideAI project board",
                "is_default": True,
            }
        ]

    def create_work_item(self, payload):
        self.calls.append(payload)
        return {
            "item_id": "goal-1",
            "title": payload["title"],
            "item_type": payload["item_type"],
            "project_id": payload["project_id"],
            "board_id": payload["board_id"],
        }


class _FakeConversationService:
    def __init__(self, transcript_messages=None) -> None:
        self.messages = []
        self.participant_adds: list = []
        self.list_messages_calls: list = []
        self._transcript_messages = transcript_messages

    def get_conversation(self, conversation_id, *, user_id=None, org_id=None):
        from types import SimpleNamespace

        return SimpleNamespace(id=conversation_id, metadata={})

    def list_messages(
        self,
        conversation_id,
        *,
        user_id,
        org_id=None,
        parent_id=None,
        include_thread_replies=False,
        **kwargs,
    ):
        self.list_messages_calls.append(
            {
                "conversation_id": conversation_id,
                "include_thread_replies": include_thread_replies,
            }
        )
        if self._transcript_messages is not None:
            return (self._transcript_messages, len(self._transcript_messages), False)
        return ([], 0, False)

    def add_participant(self, conversation_id, **kwargs):
        self.participant_adds.append({"conversation_id": conversation_id, **kwargs})

    def send_message(self, conversation_id, **kwargs):
        self.messages.append({"conversation_id": conversation_id, **kwargs})


class _FakeEventHub:
    def __init__(self) -> None:
        self.events = []

    def publish_token(self, conversation_id, message_id, payload, event_type):
        self.events.append(
            {
                "conversation_id": conversation_id,
                "message_id": message_id,
                "payload": payload,
                "event_type": event_type,
            }
        )


def _telemetry_event(
    event_type: str,
    *,
    run_id: str = "run-chat-obs",
    payload: dict | None = None,
) -> TelemetryEvent:
    return TelemetryEvent(
        event_id=f"evt-{event_type}",
        timestamp="2026-04-28T00:00:00Z",
        event_type=event_type,
        actor={"id": "agent", "role": "SYSTEM", "surface": "agent"},
        run_id=run_id,
        action_id=None,
        session_id=None,
        payload=payload or {},
    )


@dataclass
class _StubProject:
    id: str
    name: str
    slug: str
    settings: dict


class _FakeReplyProjectService:
    def __init__(self, project: _StubProject | None) -> None:
        self._project = project

    def get_project(self, project_id: str, org_id: str | None = None):
        if self._project is None:
            return None
        return self._project if project_id == self._project.id else None


class _FakeConnectorHub:
    def __init__(self, live: bool) -> None:
        self._live = live

    def user_has_live_connector_socket(self, user_id: str) -> bool:
        return self._live and bool(user_id)


@pytest.mark.asyncio
async def test_compose_context_includes_local_execution_snapshot():
    composer = _FakeComposer()
    proj = _StubProject(
        id="proj-1",
        name="Demo",
        slug="demo",
        settings={"local_project_path": "/tmp/demo-workspace"},
    )
    hub = _FakeConnectorHub(live=True)
    service = ConversationReplyService(
        context_composer=composer,
        reply_project_service=_FakeReplyProjectService(proj),
        local_execution_connector_hub=hub,
    )
    req = ReplyRequest(
        conversation_id="conv-1",
        user_message_id="msg-1",
        user_message_content="status?",
        user_id="user-42",
        project_id="proj-1",
        org_id="org-9",
        metadata={"execution_workspace_kind": "local"},
    )
    await service._compose_context(req, include_conversation_history=True)
    assert composer.calls, "composer should be invoked"
    extra = composer.calls[0].get("extra_context") or {}
    snap = extra.get("Local execution (live)", "")
    assert "local_project_path: /tmp/demo-workspace" in snap
    assert "execution_workspace_kind=" in snap
    assert "WebSocket connected" in snap


@pytest.mark.asyncio
async def test_generate_reply_records_route_metadata_and_selected_model():
    llm_client = _FakeLLMClient()
    conversation_service = _FakeConversationService()
    composer = _FakeComposer()
    audit = GovernedChatAuditLogger()
    service = ConversationReplyService(
        context_composer=composer,
        conversation_service=conversation_service,
        llm_client=llm_client,
        governed_chat_audit=audit,
    )

    result = await service.generate_reply(
        ReplyRequest(
            conversation_id="conv-1",
            user_message_id="msg-user-1",
            user_message_content="execute this work item",
            user_id="user-1",
            project_id="proj-1",
            org_id="org-1",
            metadata={
                "llm_model_id": "nvidia-deepseek-v4-flash",
                "credential_scope": "project",
                "resource_links": [
                    {"resource_type": "work_item", "resource_id": "guideai-1"}
                ],
            },
        )
    )

    assert result.success is True
    assert len(conversation_service.participant_adds) == 1
    assert conversation_service.participant_adds[0]["actor_id"] == "amprealize-agent"
    assert conversation_service.messages[0]["sender_type"] == ActorType.AGENT
    assert "actor_type" not in conversation_service.messages[0]
    assert llm_client.calls[0]["model"] == "nvidia-deepseek-v4-flash"
    assert llm_client.calls[0]["project_id"] == "proj-1"
    assert composer.calls[0]["org_id"] == "org-1"
    assert composer.calls[0]["project_id"] == "proj-1"
    assert composer.calls[0]["include_conversation_history"] is False
    assert conversation_service.list_messages_calls
    stored_metadata = conversation_service.messages[0]["metadata"]
    assert stored_metadata["chat_route"]["candidates"][0]["action_id"] == "execution.start"
    assert stored_metadata["chat_route_mode"] == "deterministic"
    assert stored_metadata["chat_route_requires_approval"] is True
    assert stored_metadata["chat_route_policy_context"]["chat_action"] == "execute"
    assert audit.records[0].event_type == "intent_classification"
    assert audit.records[0].metadata["selected_model"] == "nvidia-deepseek-v4-flash"


@pytest.mark.asyncio
async def test_generate_reply_emits_chat_trace_spans_and_handoff_correlation():
    llm_client = _FakeLLMClient()
    conversation_service = _FakeConversationService()
    telemetry_sink = InMemoryTelemetrySink()
    service = ConversationReplyService(
        context_composer=_FakeComposer(),
        conversation_service=conversation_service,
        llm_client=llm_client,
        telemetry=TelemetryClient(sink=telemetry_sink),
    )

    result = await service.generate_reply(
        ReplyRequest(
            conversation_id="conv-1",
            user_message_id="msg-user-1",
            user_message_content="execute this work item",
            user_id="user-1",
            work_item_id="guideai-1102",
            run_id="run-chat-1",
            project_id="proj-1",
            org_id="org-1",
            metadata={
                "llm_model_id": "nvidia-deepseek-v4-flash",
                "credential_scope": "project",
                "request_id": "req-chat-1",
            },
        )
    )

    assert result.success is True
    event_types = [event.event_type for event in telemetry_sink.events]
    assert "chat.trace.started" in event_types
    assert "chat.trace.completed" in event_types
    assert event_types.count("chat.span.completed") >= 6

    spans = [
        event.payload
        for event in telemetry_sink.events
        if event.event_type == "chat.span.completed"
    ]
    span_names = {span["span_name"] for span in spans}
    assert {
        "routing",
        "context",
        "fast_path",
        "generation",
        "persistence",
        "sse_streaming",
        "completion",
        "execution_handoff",
    }.issubset(span_names)

    execution_handoff = next(
        span for span in spans if span["span_name"] == "execution_handoff"
    )
    assert execution_handoff["attributes"]["run_id"] == "run-chat-1"
    assert execution_handoff["attributes"]["work_item_id"] == "guideai-1102"
    assert execution_handoff["attributes"]["execution_observability"]["surface"] == "chat"

    llm_call = llm_client.calls[0]
    assert llm_call["execution_observability"]["run_id"] == "run-chat-1"
    assert llm_call["execution_observability"]["work_item_id"] == "guideai-1102"
    assert llm_call["execution_observability"]["conversation_id"] == "conv-1"
    assert llm_call["execution_observability"]["message_id"] == "msg-user-1"
    assert llm_call["actor"] == {"id": "user-1", "role": "user", "surface": "chat"}

    stored_metadata = conversation_service.messages[0]["metadata"]
    assert stored_metadata["execution_observability"]["run_id"] == "run-chat-1"
    assert stored_metadata["chat_trace"]["trace_id"] == "chat:conv-1:msg-user-1"


@pytest.mark.asyncio
async def test_generate_reply_emits_chat_trace_failure_event():
    telemetry_sink = InMemoryTelemetrySink()
    service = ConversationReplyService(
        context_composer=_FakeComposer(),
        conversation_service=_FakeConversationService(),
        llm_client=_FailingLLMClient(),
        telemetry=TelemetryClient(sink=telemetry_sink),
    )

    result = await service.generate_reply(
        ReplyRequest(
            conversation_id="conv-fail",
            user_message_id="msg-user-fail",
            # Mutate-scoped message: router does not require clarification, so the LLM path runs.
            user_message_content="what is a run",
            user_id="user-1",
            project_id="proj-1",
            org_id="org-1",
            metadata={"llm_model_id": "nvidia-deepseek-v4-flash"},
        )
    )

    assert result.success is False
    failed_trace = next(
        event for event in telemetry_sink.events if event.event_type == "chat.trace.failed"
    )
    assert failed_trace.payload["trace_id"] == "chat:conv-fail:msg-user-fail"
    assert failed_trace.payload["error_class"] == "AssertionError"
    failed_span = next(
        event for event in telemetry_sink.events if event.event_type == "chat.span.failed"
    )
    assert failed_span.payload["span_name"] == "reply"


@pytest.mark.asyncio
async def test_generate_reply_answers_observability_questions_with_governed_redaction():
    conversation_service = _FakeConversationService()
    observability_answer_service = ObservabilityChatAnswerService(
        GovernedObservabilityQueryService(
            event_provider=lambda: [
                _telemetry_event(
                    "execution.tool.performance",
                    payload={
                        "tool_name": "workitems_update",
                        "status": "failed",
                        "inputs": {"api_key": "sk-live-secret"},  # pragma: allowlist secret
                    },
                ),
                _telemetry_event(
                    "execution.tool.performance",
                    payload={
                        "tool_name": "workitems_update",
                        "status": "failed",
                    },
                ),
                _telemetry_event(
                    "execution.tool.performance",
                    payload={
                        "tool_name": "behaviors_getfortask",
                        "status": "ok",
                    },
                ),
            ]
        )
    )
    service = ConversationReplyService(
        context_composer=_EmptyComposer(),
        conversation_service=conversation_service,
        llm_client=_FailingLLMClient(),
        observability_answer_service=observability_answer_service,
    )

    result = await service.generate_reply(
        ReplyRequest(
            conversation_id="conv-obs",
            user_message_id="msg-user-obs",
            user_message_content="Which tools fail most in the observability traces?",
            user_id="user-1",
            metadata={"role": "viewer"},
        )
    )

    assert result.success is True
    assert "workitems_update: 2 failure(s)" in result.content
    sent = conversation_service.messages[0]
    assert sent["metadata"]["direct_answer_type"] == "observability.tool_failures"
    assert sent["metadata"]["chat_trace"]["answer_path"] == "deterministic"
    assert sent["structured_payload"]["access_tier"] == "viewer"
    first_record = sent["structured_payload"]["query_result"]["records"][0]
    assert first_record["payload"]["inputs"] == "***REDACTED***"
    assert "sk-live-secret" not in str(sent["structured_payload"])


@pytest.mark.asyncio
async def test_generate_reply_emits_stable_reply_lifecycle_events():
    event_hub = _FakeEventHub()
    conversation_service = _FakeConversationService()
    service = ConversationReplyService(
        context_composer=_FakeComposer(),
        conversation_service=conversation_service,
        llm_client=_FakeLLMClient(),
        event_hub=event_hub,
    )

    result = await service.generate_reply(
        ReplyRequest(
            conversation_id="conv-1",
            user_message_id="msg-user-1",
            user_message_content="what projects do I have?",
            user_id="user-1",
            org_id="org-1",
            metadata={
                "llm_model_id": "nvidia-deepseek-v4-flash",
                "stream_message_id": "msg-stream-stable",
                "conversation_scope": "global_user_home",
            },
            stream_message_id="msg-stream-stable",
        )
    )

    assert result.message_id == "msg-stream-stable"
    event_types = [event["event_type"] for event in event_hub.events]
    assert EVENT_REPLY_STARTED in event_types
    assert EVENT_REPLY_STEP in event_types
    assert EVENT_REPLY_COMPLETE in event_types
    assert EVENT_COMPLETE in event_types
    assert all(event["message_id"] == "msg-stream-stable" for event in event_hub.events)
    complete_payload = next(
        event["payload"]
        for event in event_hub.events
        if event["event_type"] == EVENT_REPLY_COMPLETE
    )
    assert complete_payload["user_message_id"] == "msg-user-1"
    assert complete_payload["phase"] == "complete"
    assert conversation_service.messages[0]["metadata"]["stream_message_id"] == "msg-stream-stable"


@pytest.mark.asyncio
async def test_global_reply_uses_dsn_context_fallback_when_primary_composer_is_empty(monkeypatch):
    fallback_composer = _FallbackComposer()
    monkeypatch.setenv("DATABASE_URL", "postgres://example")
    monkeypatch.setattr(
        reply_service_module,
        "OSSProjectService",
        lambda dsn: object(),
    )
    monkeypatch.setattr(
        reply_service_module,
        "build_chat_context_composer",
        lambda **kwargs: fallback_composer,
    )

    service = ConversationReplyService(
        context_composer=_EmptyComposer(),
        conversation_service=_FakeConversationService(),
        llm_client=_FakeLLMClient(),
    )

    result = await service.generate_reply(
        ReplyRequest(
            conversation_id="conv-1",
            user_message_id="msg-user-1",
            user_message_content="what projects do I have?",
            user_id="user-1",
            metadata={
                "llm_model_id": "nvidia-deepseek-v4-flash",
                "conversation_scope": "global_user_home",
            },
        )
    )

    assert result.success is True
    assert result.composed_context.sources_included == ["workspace_inventory"]
    assert "GuideAI" in result.composed_context.composed_text
    assert fallback_composer.calls[0]["conversation_scope"] == "global_user_home"


@pytest.mark.asyncio
async def test_generate_reply_creates_goal_work_item_from_chat_without_llm():
    platform = _FakePlatformWorkItemService()
    conversation_service = _FakeConversationService()
    service = ConversationReplyService(
        context_composer=_InventoryComposer(),
        conversation_service=conversation_service,
        llm_client=_FailingLLMClient(),
        platform_management_service=PlatformManagementActionService(
            services={PlatformResourceType.WORK_ITEM: platform},
        ),
    )

    result = await service.generate_reply(
        ReplyRequest(
            conversation_id="conv-1",
            user_message_id="msg-user-1",
            user_message_content='can you create a new work item called "ephemeral agents\' (work type goal) on the guideai project board',
            user_id="user-1",
            metadata={
                "llm_model_id": "nvidia-deepseek-v4-flash",
                "conversation_scope": "global_user_home",
            },
        )
    )

    assert result.success is True
    assert platform.calls == [
        {
            "title": "Ephemeral agents",
            "item_type": "goal",
            "project_id": "proj-guideai",
            "board_id": "board-guideai",
            "metadata": {
                "created_from": "chat",
                "conversation_id": "conv-1",
                "user_message_id": "msg-user-1",
            },
            "resource_id": None,
            "org_id": None,
            "actor": {"id": "user-1", "role": "user", "surface": "chat"},
        }
    ]
    assert "Created goal work item: Ephemeral agents." in conversation_service.messages[0]["content"]
    stored_metadata = conversation_service.messages[0]["metadata"]
    assert stored_metadata["direct_answer_type"] == "platform_action_result"
    assert conversation_service.messages[0]["structured_payload"]["type"] == "platform_action_result"


@pytest.mark.asyncio
async def test_generate_reply_creates_task_unquoted_called_title_without_llm():
    platform = _FakePlatformWorkItemService()
    conversation_service = _FakeConversationService()
    service = ConversationReplyService(
        context_composer=_InventoryComposer(),
        conversation_service=conversation_service,
        llm_client=_FailingLLMClient(),
        platform_management_service=PlatformManagementActionService(
            services={PlatformResourceType.WORK_ITEM: platform},
        ),
    )

    result = await service.generate_reply(
        ReplyRequest(
            conversation_id="conv-1",
            user_message_id="msg-user-unquoted",
            user_message_content=(
                "create a task called board smoke on the guideai project board"
            ),
            user_id="user-1",
            metadata={
                "llm_model_id": "nvidia-deepseek-v4-flash",
                "conversation_scope": "global_user_home",
            },
        )
    )

    assert result.success is True
    assert platform.calls and platform.calls[0]["title"] == "Board smoke"


@pytest.mark.asyncio
async def test_generate_reply_work_item_title_slot_followup_merges_prior_message():
    platform = _FakePlatformWorkItemService()
    transcript = [
        Message(
            id="msg-follow-user",
            conversation_id="conv-1",
            sender_id="user-1",
            sender_type=ActorType.USER,
            content="SmokeTestTitle",
            message_type=MessageType.TEXT,
        ),
        Message(
            id="msg-follow-assistant",
            conversation_id="conv-1",
            sender_id="agent",
            sender_type=ActorType.AGENT,
            content="What should we call this work item?",
            message_type=MessageType.TEXT,
        ),
        Message(
            id="msg-follow-create",
            conversation_id="conv-1",
            sender_id="user-1",
            sender_type=ActorType.USER,
            content="Create a new task on the GuideAI project board",
            message_type=MessageType.TEXT,
        ),
    ]
    conversation_service = _FakeConversationService(transcript_messages=transcript)
    service = ConversationReplyService(
        context_composer=_InventoryComposer(),
        conversation_service=conversation_service,
        llm_client=_FailingLLMClient(),
        platform_management_service=PlatformManagementActionService(
            services={PlatformResourceType.WORK_ITEM: platform},
        ),
    )

    result = await service.generate_reply(
        ReplyRequest(
            conversation_id="conv-1",
            user_message_id="msg-follow-user",
            user_message_content="SmokeTestTitle",
            user_id="user-1",
            metadata={
                "llm_model_id": "nvidia-deepseek-v4-flash",
                "conversation_scope": "global_user_home",
            },
        )
    )

    assert result.success is True
    assert platform.calls and platform.calls[0]["title"] == "SmokeTestTitle"


@pytest.mark.asyncio
async def test_generate_reply_answers_board_inventory_before_project_list():
    conversation_service = _FakeConversationService()
    service = ConversationReplyService(
        context_composer=_InventoryComposer(),
        conversation_service=conversation_service,
        llm_client=_FailingLLMClient(),
    )

    result = await service.generate_reply(
        ReplyRequest(
            conversation_id="conv-1",
            user_message_id="msg-user-boards",
            user_message_content="what boards exist on the guideai project?",
            user_id="user-1",
            metadata={
                "llm_model_id": "nvidia-deepseek-v4-flash",
                "conversation_scope": "global_user_home",
            },
        )
    )

    assert result.success is True
    message = conversation_service.messages[0]
    assert "GuideAI project board" in message["content"]
    assert message["metadata"]["direct_answer_type"] == "boards.list"
    assert message["structured_payload"]["card_kind"] == "resource_analysis"
    assert message["structured_payload"]["rows"][0]["id"] == "board-guideai"


@pytest.mark.asyncio
async def test_generate_reply_counts_existing_work_items_without_creating():
    conversation_service = _FakeConversationService()
    service = ConversationReplyService(
        context_composer=_InventoryWithWorkItemsComposer(),
        conversation_service=conversation_service,
        llm_client=_FailingLLMClient(),
    )

    result = await service.generate_reply(
        ReplyRequest(
            conversation_id="conv-1",
            user_message_id="msg-user-count-work-items",
            user_message_content="how many work items do i have on the guideai board?",
            user_id="user-1",
            metadata={
                "llm_model_id": "nvidia-deepseek-v4-flash",
                "conversation_scope": "global_user_home",
            },
        )
    )

    assert result.success is True
    message = conversation_service.messages[0]
    assert "2 work items" in message["content"].lower()
    assert message["metadata"]["direct_answer_type"] == "work_items.count"
    assert message["metadata"]["resource_analysis"]["analysis_mode"] == "deterministic"
    assert message["metadata"]["resource_analysis"]["row_count"] == 2
    assert message["structured_payload"]["card_kind"] == "resource_analysis"
    assert message["structured_payload"]["analysis_mode"] == "deterministic"
    assert message["structured_payload"]["query_plan"]["intent"] == "count"


@pytest.mark.asyncio
async def test_generate_reply_discovers_boards_before_create_when_inventory_is_empty():
    platform = _FakePlatformWorkItemService()
    conversation_service = _FakeConversationService()
    service = ConversationReplyService(
        context_composer=_InventoryWithoutBoardsComposer(),
        conversation_service=conversation_service,
        llm_client=_FailingLLMClient(),
        platform_management_service=PlatformManagementActionService(
            services={
                PlatformResourceType.BOARD: platform,
                PlatformResourceType.WORK_ITEM: platform,
            },
        ),
    )

    result = await service.generate_reply(
        ReplyRequest(
            conversation_id="conv-1",
            user_message_id="msg-user-create-discover",
            user_message_content='can you create a new work item called "ephemeral agents\' (work type goal) on the guideai project board',
            user_id="user-1",
            metadata={
                "llm_model_id": "nvidia-deepseek-v4-flash",
                "conversation_scope": "global_user_home",
            },
        )
    )

    assert result.success is True
    assert platform.calls[0]["operation"] == "list_boards"
    assert platform.calls[0]["project_id"] == "proj-guideai"
    create_payload = platform.calls[1]
    assert create_payload["title"] == "Ephemeral agents"
    assert create_payload["item_type"] == "goal"
    assert create_payload["board_id"] == "board-guideai-discovered"
    assert create_payload["metadata"]["board_resolved_via"] == "platform_discover"


def test_chat_platform_action_path_does_not_dispatch_via_rest_or_mcp():
    source = inspect.getsource(ConversationReplyService._try_platform_management_answer)
    init_source = inspect.getsource(ConversationReplyService.__init__)
    forbidden_fragments = [
        "httpx.",
        "aiohttp.",
        "urllib.request",
        "localhost",
        "127.0.0.1",
        "CallMcp",
        "MCPServer",
        "handle_create_work_item",
        "/api/",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in source
    assert "ChatResourceActionRegistry" in init_source
    assert "registry.execute(" in source


class _FakeLLMClientAstreamMessageCompleteOnly:
    """Mimics providers that only attach text on the final MESSAGE_COMPLETE chunk."""

    async def astream(self, messages, **kwargs):
        yield StreamChunk(
            type=StreamChunkType.MESSAGE_COMPLETE,
            response=LLMResponse(
                content="Hello from final chunk only.",
                model="test-model",
                provider=ProviderType.OPENAI,
            ),
        )


class _FakeLLMClientAstreamReasoningOnlyOnFinalResponse:
    """NIM-style: no deltas; final LLMResponse has empty content but reasoning_content."""

    async def astream(self, messages, **kwargs):
        yield StreamChunk(
            type=StreamChunkType.MESSAGE_COMPLETE,
            response=LLMResponse(
                content="",
                model="nvidia-deepseek-v4-flash",
                provider=ProviderType.NVIDIA,
                reasoning_content="Visible answer assembled from reasoning channel.",
            ),
        )


class _FakeLLMClientAstreamErrorChunk:
    """Yields an ERROR chunk with provider exception class (OpenAI-compatible stream)."""

    async def astream(self, messages, **kwargs):
        yield StreamChunk(
            type=StreamChunkType.ERROR,
            error="Request timed out.",
            error_class="APITimeoutError",
        )


class _FakeLLMClientAstreamFullyEmpty:
    """Final MESSAGE_COMPLETE with no text (no deltas, empty content and reasoning)."""

    async def astream(self, messages, **kwargs):
        yield StreamChunk(
            type=StreamChunkType.MESSAGE_COMPLETE,
            response=LLMResponse(
                content="",
                model="test-model",
                provider=ProviderType.OPENAI,
                reasoning_content="",
            ),
        )


class _ClarifyingRouteGateway:
    """Deterministic router: clarification required before any LLM work."""

    def route(self, route_request):
        return ChatActionRouteResult(
            candidates=[
                ChatActionCandidate(
                    action_id="chat.read_synthesis",
                    category=ChatActionCategory.READ_SYNTHESIS,
                    permission_surface=ChatPermissionSurface.GLOBAL_CHAT,
                    permission_action=ChatPermissionAction.READ,
                    confidence=0.55,
                    risk=ChatActionRisk.LOW,
                    required_scopes=(ChatPermissionScope.USER,),
                    requires_approval=False,
                    requires_clarification=True,
                    rationale="ambiguous target",
                )
            ],
            requires_clarification=True,
            clarification_prompt="Please name the project or board first.",
        )


class _ClarifyingRouteGatewayNoPrompt(_ClarifyingRouteGateway):
    """Like _ClarifyingRouteGateway but omits clarification text (exercises body fallback)."""

    def route(self, route_request):
        base = super().route(route_request)
        return ChatActionRouteResult(
            candidates=base.candidates,
            requires_clarification=True,
            clarification_prompt=None,
        )


class _ForbiddenLLMClient:
    """LLM surface must not be invoked when routing short-circuits clarification."""

    async def astream(self, *args, **kwargs):
        raise AssertionError("astream should not be called when clarification short-circuits")

    def call(self, *args, **kwargs):
        raise AssertionError("call should not be called when clarification short-circuits")


@pytest.mark.asyncio
async def test_generate_with_streaming_uses_response_when_no_text_deltas():
    service = ConversationReplyService(
        context_composer=_FakeComposer(),
        conversation_service=_FakeConversationService(),
        llm_client=_FakeLLMClientAstreamMessageCompleteOnly(),
    )
    out = await service._generate_with_streaming(
        [{"role": "user", "content": "hi"}],
        conversation_id="conv-1",
        message_id="msg-stream-1",
        metadata={"llm_model_id": "nvidia-deepseek-v4-flash"},
        project_id="p1",
        org_id="o1",
        user_id="u1",
    )
    assert out == "Hello from final chunk only."


@pytest.mark.asyncio
async def test_generate_with_streaming_replaces_fully_empty_completion():
    service = ConversationReplyService(
        context_composer=_FakeComposer(),
        conversation_service=_FakeConversationService(),
        llm_client=_FakeLLMClientAstreamFullyEmpty(),
    )
    out = await service._generate_with_streaming(
        [{"role": "user", "content": "hi"}],
        conversation_id="conv-1",
        message_id="msg-stream-empty",
        metadata={"llm_model_id": "gpt-4o-mini"},
        project_id="p1",
        org_id="o1",
        user_id="u1",
    )
    assert out == reply_service_module._EMPTY_LLM_REPLY_PLACEHOLDER


@pytest.mark.asyncio
async def test_generate_with_streaming_uses_reasoning_content_when_content_empty():
    service = ConversationReplyService(
        context_composer=_FakeComposer(),
        conversation_service=_FakeConversationService(),
        llm_client=_FakeLLMClientAstreamReasoningOnlyOnFinalResponse(),
    )
    out = await service._generate_with_streaming(
        [{"role": "user", "content": "hi"}],
        conversation_id="conv-1",
        message_id="msg-stream-reason",
        metadata={"llm_model_id": "nvidia-deepseek-v4-flash"},
        project_id="p1",
        org_id="o1",
        user_id="u1",
    )
    assert out == "Visible answer assembled from reasoning channel."


@pytest.mark.asyncio
async def test_generate_reply_emits_provider_error_class_from_stream_error_chunk():
    """chat.trace.failed includes provider_error_class when the LLM stream ERROR chunk sets error_class."""
    telemetry_sink = InMemoryTelemetrySink()
    service = ConversationReplyService(
        context_composer=_FakeComposer(),
        conversation_service=_FakeConversationService(),
        llm_client=_FakeLLMClientAstreamErrorChunk(),
        telemetry=TelemetryClient(sink=telemetry_sink),
    )

    result = await service.generate_reply(
        ReplyRequest(
            conversation_id="conv-stream-err",
            user_message_id="msg-stream-err",
            # Mutate-scoped message: router does not require clarification, so streaming runs.
            user_message_content="what is a run",
            user_id="user-1",
            project_id="proj-1",
            org_id="org-1",
            metadata={"llm_model_id": "nvidia-deepseek-v4-flash"},
        )
    )

    assert result.success is False
    failed_trace = next(
        event for event in telemetry_sink.events if event.event_type == "chat.trace.failed"
    )
    assert failed_trace.payload["error_class"] == "RuntimeError"
    assert failed_trace.payload["provider_error_class"] == "APITimeoutError"
    failed_span = next(
        event for event in telemetry_sink.events if event.event_type == "chat.span.failed"
    )
    assert failed_span.payload["provider_error_class"] == "APITimeoutError"


@pytest.mark.asyncio
async def test_generate_reply_uses_llm_for_conversational_access_question():
    """Capability / local-access questions skip inventory fast path (natural assistant reply)."""
    conversation_service = _FakeConversationService()
    fake_llm = _FakeLLMClient()
    service = ConversationReplyService(
        context_composer=_InventoryComposer(),
        conversation_service=conversation_service,
        llm_client=fake_llm,
    )

    result = await service.generate_reply(
        ReplyRequest(
            conversation_id="conv-conv-access",
            user_message_id="msg-conv-access",
            user_message_content="do you have access to files on my laptop?",
            user_id="user-1",
            metadata={
                "llm_model_id": "nvidia-deepseek-v4-flash",
                "conversation_scope": "global_user_home",
            },
        )
    )

    assert result.success is True
    assert len(fake_llm.calls) >= 1
    message = conversation_service.messages[0]
    assert message["metadata"].get("direct_answer") is not True
    assert "Done." in message["content"]


@pytest.mark.asyncio
async def test_generate_reply_skips_llm_when_route_requires_clarification():
    telemetry_sink = InMemoryTelemetrySink()
    conversation_service = _FakeConversationService()
    service = ConversationReplyService(
        context_composer=_FakeComposer(),
        conversation_service=conversation_service,
        llm_client=_ForbiddenLLMClient(),
        route_gateway=_ClarifyingRouteGateway(),
        telemetry=TelemetryClient(sink=telemetry_sink),
    )

    result = await service.generate_reply(
        ReplyRequest(
            conversation_id="conv-clarify-skip",
            user_message_id="msg-clarify-skip",
            user_message_content="do something with that thing",
            user_id="user-1",
            metadata={
                "llm_model_id": "nvidia-deepseek-v4-flash",
                "conversation_scope": "global_user_home",
            },
        )
    )

    assert result.success is True
    assert conversation_service.messages[0]["content"] == "Please name the project or board first."
    gen_events = [
        e for e in telemetry_sink.events if e.event_type == "conversation_reply.generated"
    ]
    assert gen_events
    assert gen_events[-1].payload["answer_path"] == "routing_clarification"


@pytest.mark.asyncio
async def test_generate_reply_clarification_short_circuit_uses_body_fallback_when_no_prompt():
    conversation_service = _FakeConversationService()
    service = ConversationReplyService(
        context_composer=_FakeComposer(),
        conversation_service=conversation_service,
        llm_client=_ForbiddenLLMClient(),
        route_gateway=_ClarifyingRouteGatewayNoPrompt(),
    )

    result = await service.generate_reply(
        ReplyRequest(
            conversation_id="conv-clarify-fallback",
            user_message_id="msg-clarify-fallback",
            user_message_content="ambiguous",
            user_id="user-1",
            metadata={"conversation_scope": "global_user_home"},
        )
    )

    assert result.success is True
    assert conversation_service.messages[0]["content"] == reply_service_module._CLARIFICATION_BODY_FALLBACK
