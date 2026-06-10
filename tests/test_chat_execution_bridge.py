"""Tests for chat-originated execution (Option B server-side agent bridge)."""

from __future__ import annotations

from typing import Any, Dict

import pytest

from amprealize.chat_execution_bridge import CHAT_AGENT_EXECUTION_FLAG, ChatExecutionBridge
from amprealize.chat_resource_actions import (
    ChatResourceActionId,
    ChatResourceActionRegistry,
    ChatResourceActionRequest,
)
from amprealize.feature_flags import FeatureFlag, FeatureFlagService, FlagType
from amprealize.work_item_execution_contracts import ExecuteWorkItemResponse, ExecutionState

pytestmark = pytest.mark.unit


class _FakeExecutionStartService:
    def __init__(self) -> None:
        self.calls: list[Dict[str, Any]] = []
        self.cancel_calls: list[Dict[str, Any]] = []
        self.cancel_result = True

    async def execute(self, request: Any) -> ExecuteWorkItemResponse:
        self.calls.append(
            {
                "work_item_id": request.work_item_id,
                "project_id": request.project_id,
                "metadata": dict(request.metadata or {}),
            }
        )
        return ExecuteWorkItemResponse(
            run_id="run-xyz",
            cycle_id="cycle-xyz",
            work_item_id=request.work_item_id,
            agent_id="builtin",
            model_id=request.model_id or "gpt-4o",
            status=ExecutionState.PENDING,
            phase="planning",
            created_at="2026-04-30T00:00:00Z",
        )

    def cancel(self, work_item_id: str, user_id: str, org_id: Any = None, reason: Any = None) -> bool:
        self.cancel_calls.append(
            {
                "work_item_id": work_item_id,
                "user_id": user_id,
                "org_id": org_id,
                "reason": reason,
            }
        )
        return self.cancel_result


@pytest.mark.asyncio
async def test_bridge_refuses_when_feature_disabled() -> None:
    flags = FeatureFlagService(
        flags=[
            FeatureFlag(
                name=CHAT_AGENT_EXECUTION_FLAG,
                flag_type=FlagType.BOOLEAN,
                enabled=False,
            )
        ]
    )
    bridge = ChatExecutionBridge(
        execution_start_service=_FakeExecutionStartService(),
        feature_flags=flags,
    )
    out = await bridge.run_start(
        ChatResourceActionRequest(
            action_id=ChatResourceActionId.RUN_START,
            user_id="u1",
            project_id="p1",
            resource_id="w1",
            payload={"confirm_chat_execution": True, "work_item_id": "w1", "project_id": "p1"},
        )
    )
    assert out["success"] is False
    assert "disabled" in out["message"].lower()


@pytest.mark.asyncio
async def test_bridge_requires_confirm_payload() -> None:
    flags = FeatureFlagService(
        flags=[
            FeatureFlag(
                name=CHAT_AGENT_EXECUTION_FLAG,
                flag_type=FlagType.BOOLEAN,
                enabled=True,
            )
        ]
    )
    bridge = ChatExecutionBridge(
        execution_start_service=_FakeExecutionStartService(),
        feature_flags=flags,
    )
    out = await bridge.run_start(
        ChatResourceActionRequest(
            action_id=ChatResourceActionId.RUN_START,
            user_id="u1",
            project_id="p1",
            resource_id="w1",
            payload={"work_item_id": "w1", "project_id": "p1"},
        )
    )
    assert out["success"] is False
    assert out.get("requires_approval") is True


@pytest.mark.asyncio
async def test_registry_dispatches_run_start_through_bridge() -> None:
    fake = _FakeExecutionStartService()
    flags = FeatureFlagService(
        flags=[
            FeatureFlag(
                name=CHAT_AGENT_EXECUTION_FLAG,
                flag_type=FlagType.BOOLEAN,
                enabled=True,
            )
        ]
    )
    bridge = ChatExecutionBridge(execution_start_service=fake, feature_flags=flags)
    registry = ChatResourceActionRegistry(execution_bridge=bridge)

    raw = await registry.execute(
        ChatResourceActionRequest(
            action_id=ChatResourceActionId.RUN_START,
            user_id="u1",
            org_id="o1",
            project_id="p1",
            conversation_id="c1",
            message_id="m1",
            resource_id="wi-99",
            payload={
                "work_item_id": "wi-99",
                "project_id": "p1",
                "confirm_chat_execution": True,
                "source_type": "github",
            },
            request_id="req-1",
        )
    )
    assert isinstance(raw, dict)
    assert raw["success"] is True
    assert raw["result"]["run_id"] == "run-xyz"
    assert fake.calls[0]["work_item_id"] == "wi-99"
    assert fake.calls[0]["metadata"]["conversation_id"] == "c1"
    assert fake.calls[0]["metadata"]["source_type"] == "github"


@pytest.mark.asyncio
async def test_bridge_cancel_requires_confirm_flag() -> None:
    flags = FeatureFlagService(
        flags=[
            FeatureFlag(
                name=CHAT_AGENT_EXECUTION_FLAG,
                flag_type=FlagType.BOOLEAN,
                enabled=True,
            )
        ]
    )
    fake = _FakeExecutionStartService()
    bridge = ChatExecutionBridge(execution_start_service=fake, feature_flags=flags)
    out = await bridge.run_cancel(
        ChatResourceActionRequest(
            action_id=ChatResourceActionId.RUN_CANCEL,
            user_id="u1",
            resource_id="wi-1",
            payload={"work_item_id": "wi-1"},
        )
    )
    assert out["success"] is False
    assert out.get("requires_approval") is True
    assert fake.cancel_calls == []


@pytest.mark.asyncio
async def test_registry_dispatches_run_cancel_through_bridge() -> None:
    fake = _FakeExecutionStartService()
    fake.cancel_result = True
    flags = FeatureFlagService(
        flags=[
            FeatureFlag(
                name=CHAT_AGENT_EXECUTION_FLAG,
                flag_type=FlagType.BOOLEAN,
                enabled=True,
            )
        ]
    )
    bridge = ChatExecutionBridge(execution_start_service=fake, feature_flags=flags)
    registry = ChatResourceActionRegistry(execution_bridge=bridge)

    raw = await registry.execute(
        ChatResourceActionRequest(
            action_id=ChatResourceActionId.RUN_CANCEL,
            user_id="u1",
            org_id="o1",
            project_id="p1",
            conversation_id="c1",
            message_id="m1",
            resource_id="wi-88",
            payload={
                "work_item_id": "wi-88",
                "confirm_chat_execution_cancel": True,
                "reason": "user asked in chat",
            },
            request_id="req-cancel-1",
        )
    )
    assert isinstance(raw, dict)
    assert raw["success"] is True
    assert fake.cancel_calls[0]["work_item_id"] == "wi-88"
    assert fake.cancel_calls[0]["user_id"] == "u1"
    assert fake.cancel_calls[0]["reason"] == "user asked in chat"
