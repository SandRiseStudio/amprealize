from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

from amprealize.context_composer import ContextComposer
from amprealize.services.conversation_reply_service import ConversationReplyService, ReplyRequest
from amprealize.global_chat_context import (
    WorkspaceInventoryProvider,
    _resolved_chat_work_item_inventory_limit,
)


pytestmark = pytest.mark.unit


def test_resolved_chat_work_item_inventory_limit_env_and_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AMPREALIZE_CHAT_WORK_ITEM_INVENTORY_LIMIT", raising=False)
    assert _resolved_chat_work_item_inventory_limit(None) == 5000
    monkeypatch.setenv("AMPREALIZE_CHAT_WORK_ITEM_INVENTORY_LIMIT", "1200")
    assert _resolved_chat_work_item_inventory_limit(None) == 1200
    assert _resolved_chat_work_item_inventory_limit(7) == 7


@dataclass
class _Project:
    id: str
    name: str
    slug: str
    description: Optional[str] = None


@dataclass
class _Board:
    board_id: str
    project_id: str
    name: str


@dataclass
class _WorkItem:
    item_id: str
    project_id: str
    title: str
    status: str = "in_progress"
    item_type: str = "task"


@dataclass
class _Run:
    run_id: str
    created_at: str = "2026-04-27T00:00:00Z"
    updated_at: str = "2026-04-27T00:00:00Z"
    actor: Dict[str, Any] = field(default_factory=lambda: {"id": "user-1"})
    status: str = "RUNNING"
    metadata: Dict[str, Any] = field(default_factory=lambda: {"project_id": "proj-1"})


class _ProjectService:
    def list_projects(self, owner_id: str, org_id: Optional[str] = None) -> List[_Project]:
        assert owner_id == "user-1"
        assert org_id == "org-1"
        return [
            _Project(id="proj-1", name="Alpha", slug="alpha", description="Main project"),
            _Project(id="proj-2", name="Beta", slug="beta"),
        ]

    def list_user_project_agent_assignments(self, owner_id: str, org_id: Optional[str] = None) -> List[Dict[str, str]]:
        return [{"agent_id": "guideai", "agent_name": "GuideAI Agent", "project_id": "proj-1", "role": "builder"}]


class _OSSProjectServiceWithoutOrgParam:
    def list_projects(self, owner_id: str, org_id: Optional[str] = None) -> List[_Project]:
        return [_Project(id="proj-guideai", name="GuideAI", slug="guideai")]

    def list_user_project_agent_assignments(self, owner_id: str) -> List[Dict[str, str]]:
        return [
            {
                "agent_id": "agent-guide",
                "agent_name": "GuideAI Planner",
                "agent_slug": "guideai-planner",
                "project_id": "proj-guideai",
                "role": "primary",
            }
        ]


class _SlowBoardService:
    def list_boards(self, *, project_id: str, org_id: Optional[str], limit: int, offset: int) -> List[_Board]:
        time.sleep(0.05)
        return [_Board(board_id=f"board-{project_id}", project_id=project_id, name=f"{project_id} board")]

    def list_work_items(self, *, project_id: str, org_id: Optional[str], limit: int, offset: int, **kwargs: Any) -> List[_WorkItem]:
        time.sleep(0.05)
        return [_WorkItem(item_id=f"task-{project_id}", project_id=project_id, title=f"{project_id} task")]


class _RunService:
    def list_runs(self, *, limit: int) -> List[_Run]:
        return [_Run(run_id="run-1")]


class _BehaviorService:
    def get_relevant_behaviors_for_task(
        self,
        *,
        task_description: str,
        role: str,
        limit: int,
        telemetry_session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "recommended_behaviors": [
                {"name": "behavior_test", "instruction": "Use test behavior."}
            ]
        }


class _LLMClient:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def call(self, messages: List[Dict[str, str]], **kwargs: Any):
        self.calls.append({"messages": messages, **kwargs})
        return type("Response", (), {"content": "You have Alpha and Beta."})()


class _Telemetry:
    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []

    def emit_event(self, *, event_type: str, payload: Dict[str, Any], **kwargs: Any) -> None:
        self.events.append({"event_type": event_type, "payload": payload, **kwargs})


class _WikiService:
    def query(self, domain: str, query_text: str, max_results: int) -> Dict[str, Any]:
        return {
            "success": True,
            "results": [
                {
                    "page_path": "in-practice/global-chat-context.md",
                    "title": "Global Chat Context",
                    "type": "in-practice",
                    "score": 1,
                    "snippet": "How chat uses workspace context.",
                }
            ],
        }


class _SingleProjectService:
    def list_projects(self, owner_id: str, org_id: Optional[str] = None) -> List[_Project]:
        return [_Project(id="proj-1", name="Alpha", slug="alpha")]

    def list_user_project_agent_assignments(self, owner_id: str, org_id: Optional[str] = None) -> List[Dict[str, str]]:
        return []


class _LimitCaptureBoardService:
    """Records ``limit`` passed to ``list_work_items`` (one call per project)."""

    captured_limits: List[int] = []

    def list_boards(self, *, project_id: str, org_id: Optional[str], limit: int, offset: int) -> List[_Board]:
        return [_Board(board_id=f"board-{project_id}", project_id=project_id, name="Main")]

    def list_work_items(self, *, project_id: str, org_id: Optional[str], limit: int, offset: int, **kwargs: Any) -> List[Dict[str, Any]]:
        self.__class__.captured_limits.append(int(limit))
        return [
            {"item_id": f"wi-{project_id}-{i}", "title": "t", "project_id": project_id, "status": "open"}
            for i in range(min(int(limit), 3))
        ]


@pytest.mark.asyncio
async def test_workspace_inventory_requests_high_work_item_limit() -> None:
    _LimitCaptureBoardService.captured_limits.clear()
    provider = WorkspaceInventoryProvider(
        project_service=_SingleProjectService(),
        board_service=_LimitCaptureBoardService(),
        run_service=None,
        behavior_service=None,
        wiki_service=None,
        max_work_items_per_project=250,
    )
    inv = await provider._fetch_inventory(user_id="user-1", org_id="org-1", project_id=None)
    assert _LimitCaptureBoardService.captured_limits == [250]
    assert len(inv["work_items_by_project"]["proj-1"]) == 3


@pytest.mark.asyncio
async def test_workspace_inventory_lists_accessible_projects_and_related_context():
    provider = WorkspaceInventoryProvider(
        project_service=_ProjectService(),
        board_service=_SlowBoardService(),
        run_service=_RunService(),
        behavior_service=_BehaviorService(),
        wiki_service=_WikiService(),
        workspace_rules=["Prefer endorsed project facts before generation."],
        endorsed_project_ids=["proj-1"],
    )

    fragments = await provider.get_workspace_inventory(
        user_id="user-1",
        org_id="org-1",
        query="what projects do I have?",
        conversation_scope="global_user_home",
    )

    assert len(fragments) == 1
    content = fragments[0]["content"]
    assert "Alpha (alpha) [proj-1]" in content
    assert "Prefer endorsed project facts before generation." in content
    assert "Alpha (alpha) [proj-1] [endorsed]" in content
    assert "Beta (beta) [proj-2]" in content
    assert "GuideAI Agent [guideai] on Alpha [proj-1]" in content
    assert "task-proj-1" in content
    assert "run-1" in content
    assert "behavior_test" in content
    assert "Global Chat Context" in content
    assert fragments[0]["metadata"]["source_counts"]["projects"] == 2
    assert fragments[0]["metadata"]["source_counts"]["agent_assignments"] == 1
    assert fragments[0]["metadata"]["source_counts"]["workspace_rules"] == 1
    assert fragments[0]["metadata"]["context_sources"][0]["kind"] == "workspace_rules"


@pytest.mark.asyncio
async def test_workspace_inventory_lists_oss_agent_assignments_without_org_param():
    provider = WorkspaceInventoryProvider(
        project_service=_OSSProjectServiceWithoutOrgParam(),
        board_service=None,
        run_service=None,
        behavior_service=None,
        wiki_service=None,
    )

    fragments = await provider.get_workspace_inventory(
        user_id="user-1",
        org_id="org-1",
        query="what agents are assigned to the guideai project?",
        conversation_scope="global_user_home",
    )

    content = fragments[0]["content"]
    assert "GuideAI (guideai) [proj-guideai]" in content
    assert "GuideAI Planner (guideai-planner) [agent-guide] on GuideAI [proj-guideai] (primary)" in content
    assert fragments[0]["metadata"]["source_counts"]["agent_assignments"] == 1


@pytest.mark.asyncio
async def test_global_reply_prompt_includes_workspace_inventory():
    provider = WorkspaceInventoryProvider(
        project_service=_ProjectService(),
        board_service=_SlowBoardService(),
        run_service=_RunService(),
        behavior_service=_BehaviorService(),
        wiki_service=_WikiService(),
    )
    composer = ContextComposer(workspace_provider=provider)
    llm_client = _LLMClient()
    service = ConversationReplyService(
        context_composer=composer,
        llm_client=llm_client,
    )

    result = await service.generate_reply(
        ReplyRequest(
            conversation_id="conv-1",
            user_message_id="msg-user-1",
            user_message_content="help me summarize what I should focus on next",
            user_id="user-1",
            org_id="org-1",
            metadata={"conversation_scope": "global_user_home", "llm_model_id": "test-model"},
        )
    )

    system_prompt = llm_client.calls[0]["messages"][0]["content"]
    assert result.success is True
    assert "Accessible Workspace Inventory" in system_prompt
    assert "Alpha (alpha) [proj-1]" in system_prompt
    assert "Beta (beta) [proj-2]" in system_prompt


@pytest.mark.asyncio
async def test_global_reply_answers_project_agent_assignment_without_llm_call():
    provider = WorkspaceInventoryProvider(
        project_service=_OSSProjectServiceWithoutOrgParam(),
        board_service=None,
        run_service=None,
        behavior_service=None,
        wiki_service=None,
    )
    composer = ContextComposer(workspace_provider=provider)
    llm_client = _LLMClient()
    service = ConversationReplyService(
        context_composer=composer,
        llm_client=llm_client,
    )

    result = await service.generate_reply(
        ReplyRequest(
            conversation_id="conv-1",
            user_message_id="msg-user-1",
            user_message_content="what agents are assigned to the guideai project?",
            user_id="user-1",
            org_id="org-1",
            metadata={"conversation_scope": "global_user_home", "llm_model_id": "test-model"},
        )
    )

    assert result.success is True
    assert "GuideAI Planner (guideai-planner) [agent-guide]" in result.content
    assert "primary" in result.content
    assert llm_client.calls == []


@pytest.mark.asyncio
async def test_global_reply_answers_project_list_without_llm_call():
    provider = WorkspaceInventoryProvider(
        project_service=_ProjectService(),
        board_service=None,
        run_service=None,
        behavior_service=None,
        wiki_service=None,
    )
    composer = ContextComposer(workspace_provider=provider)
    llm_client = _LLMClient()
    telemetry = _Telemetry()
    service = ConversationReplyService(
        context_composer=composer,
        llm_client=llm_client,
        telemetry=telemetry,
    )

    result = await service.generate_reply(
        ReplyRequest(
            conversation_id="conv-1",
            user_message_id="msg-user-1",
            user_message_content="what projects do I have?",
            user_id="user-1",
            org_id="org-1",
            metadata={"conversation_scope": "global_user_home"},
        )
    )

    assert result.success is True
    assert "Alpha (alpha) [proj-1]" in result.content
    assert "Beta (beta) [proj-2]" in result.content
    assert llm_client.calls == []
    assert any(event["event_type"] == "chat.fast_path.hit" for event in telemetry.events)


@pytest.mark.asyncio
async def test_global_reply_answers_runs_and_work_items_without_llm_call():
    provider = WorkspaceInventoryProvider(
        project_service=_ProjectService(),
        board_service=_SlowBoardService(),
        run_service=_RunService(),
        behavior_service=None,
        wiki_service=None,
    )
    composer = ContextComposer(workspace_provider=provider)
    llm_client = _LLMClient()
    service = ConversationReplyService(
        context_composer=composer,
        llm_client=llm_client,
    )

    runs_result = await service.generate_reply(
        ReplyRequest(
            conversation_id="conv-1",
            user_message_id="msg-user-runs",
            user_message_content="what active runs do I have?",
            user_id="user-1",
            org_id="org-1",
            metadata={"conversation_scope": "global_user_home"},
        )
    )
    work_items_result = await service.generate_reply(
        ReplyRequest(
            conversation_id="conv-1",
            user_message_id="msg-user-work",
            user_message_content="show recent work items for alpha",
            user_id="user-1",
            org_id="org-1",
            metadata={"conversation_scope": "global_user_home"},
        )
    )

    assert "run-1" in runs_result.content
    assert "task-proj-1" in work_items_result.content
    assert llm_client.calls == []


@pytest.mark.asyncio
async def test_workspace_inventory_fetches_project_boards_and_work_items_concurrently():
    provider = WorkspaceInventoryProvider(
        project_service=_ProjectService(),
        board_service=_SlowBoardService(),
        run_service=_RunService(),
        behavior_service=None,
        wiki_service=None,
    )

    started = time.perf_counter()
    await provider.get_workspace_inventory(
        user_id="user-1",
        org_id="org-1",
        query="inventory",
        conversation_scope="global_user_home",
    )
    elapsed = time.perf_counter() - started

    assert elapsed < 0.25
