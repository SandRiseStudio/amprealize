from __future__ import annotations

import inspect

import pytest

from amprealize.chat_resource_actions import (
    ChatResourceActionBackend,
    ChatResourceActionId,
    ChatResourceActionRegistry,
    ChatResourceActionRequest,
)
from amprealize.platform_management_actions import (
    PlatformManagementActionService,
    PlatformResourceType,
)

pytestmark = pytest.mark.unit


class _FakePlatformService:
    def __init__(self) -> None:
        self.calls = []

    def create_work_item(self, payload):
        self.calls.append(("create_work_item", payload))
        return {"item_id": "goal-1", "title": payload["title"]}

    def list_boards(self, payload):
        self.calls.append(("list_boards", payload))
        return [{"board_id": "board-1", "project_id": payload["project_id"]}]


def test_registry_declares_core_chat_resource_actions():
    registry = ChatResourceActionRegistry()
    specs = {spec.action_id: spec for spec in registry.list_specs()}

    expected = {
        ChatResourceActionId.WORK_ITEM_CREATE,
        ChatResourceActionId.BOARD_DISCOVER,
        ChatResourceActionId.PROJECT_CREATE,
        ChatResourceActionId.ORG_CREATE,
        ChatResourceActionId.AGENT_ASSIGN,
        ChatResourceActionId.AGENT_PUBLISH,
        ChatResourceActionId.WIKI_PAGE_DISCOVER,
        ChatResourceActionId.WIKI_PAGE_UPDATE,
        ChatResourceActionId.BEHAVIOR_PROPOSE,
        ChatResourceActionId.BEHAVIOR_APPROVE,
        ChatResourceActionId.RUN_START,
        ChatResourceActionId.RUN_CANCEL,
        ChatResourceActionId.ATTACHMENT_CREATE,
        ChatResourceActionId.MCP_TOOL_INVOKE,
    }
    assert expected.issubset(specs)
    assert specs[ChatResourceActionId.WORK_ITEM_CREATE].backend == ChatResourceActionBackend.PLATFORM
    assert specs[ChatResourceActionId.AGENT_ASSIGN].backend == ChatResourceActionBackend.AGENT_LIFECYCLE
    assert specs[ChatResourceActionId.WIKI_PAGE_UPDATE].backend == ChatResourceActionBackend.WIKI
    assert specs[ChatResourceActionId.BEHAVIOR_PROPOSE].backend == ChatResourceActionBackend.BEHAVIOR
    assert specs[ChatResourceActionId.RUN_START].backend == ChatResourceActionBackend.EXECUTION
    assert specs[ChatResourceActionId.MCP_TOOL_INVOKE].backend == ChatResourceActionBackend.MCP_GOVERNANCE


@pytest.mark.asyncio
async def test_registry_dispatches_work_item_create_through_platform_service():
    platform = _FakePlatformService()
    platform_service = PlatformManagementActionService(
        services={PlatformResourceType.WORK_ITEM: platform},
    )
    registry = ChatResourceActionRegistry(platform_service=platform_service)

    result = await registry.execute(
        ChatResourceActionRequest(
            action_id=ChatResourceActionId.WORK_ITEM_CREATE,
            user_id="user-1",
            project_id="proj-1",
            conversation_id="conv-1",
            message_id="msg-1",
            payload={"title": "Ephemeral agents", "item_type": "goal", "board_id": "board-1"},
            policy_context={"chat_scope": "global_user_home"},
        )
    )

    assert result.success is True
    assert result.result == {"item_id": "goal-1", "title": "Ephemeral agents"}
    assert platform.calls[0][0] == "create_work_item"
    assert platform.calls[0][1]["actor"] == {"id": "user-1", "role": "user", "surface": "chat"}


@pytest.mark.asyncio
async def test_registry_dispatches_board_discover_through_platform_service():
    platform = _FakePlatformService()
    platform_service = PlatformManagementActionService(
        services={PlatformResourceType.BOARD: platform},
    )
    registry = ChatResourceActionRegistry(platform_service=platform_service)

    result = await registry.execute(
        ChatResourceActionRequest(
            action_id=ChatResourceActionId.BOARD_DISCOVER,
            user_id="user-1",
            project_id="proj-1",
            payload={"project_id": "proj-1"},
        )
    )

    assert result.success is True
    assert result.result == [{"board_id": "board-1", "project_id": "proj-1"}]
    assert platform.calls == [
        (
            "list_boards",
            {
                "project_id": "proj-1",
                "resource_id": None,
                "org_id": None,
                "actor": {"id": "user-1", "role": "user", "surface": "chat"},
            },
        )
    ]


@pytest.mark.asyncio
async def test_registered_non_platform_actions_fail_closed_without_executor():
    registry = ChatResourceActionRegistry()

    with pytest.raises(ValueError, match="no wiki executor"):
        await registry.execute(
            ChatResourceActionRequest(
                action_id=ChatResourceActionId.WIKI_PAGE_UPDATE,
                user_id="user-1",
            )
        )


def test_registry_does_not_dispatch_via_rest_or_mcp_loopback():
    source = inspect.getsource(ChatResourceActionRegistry)
    forbidden_fragments = [
        "httpx.",
        "aiohttp.",
        "urllib.request",
        "localhost",
        "127.0.0.1",
        "MCPServer",
        "handle_create_work_item",
        "/api/",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in source
