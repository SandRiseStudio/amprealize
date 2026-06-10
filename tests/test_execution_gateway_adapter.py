"""Tests for gateway-backed legacy execution surface adapters."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from amprealize.execution_gateway_adapter import GatewayWorkItemExecutionAdapter
from amprealize.execution_gateway_contracts import (
    ExecutionGatewayResult,
    ExecutionIntent,
    NewExecutionMode,
    OutputTarget,
)
from amprealize.mcp.handlers.work_item_execution_handlers import (
    create_work_item_execution_handlers,
)
from amprealize.services.work_item_execution_api import create_work_item_execution_routes
from amprealize.work_item_execution_contracts import (
    AgentExecutionMode,
    ExecuteWorkItemRequest,
    ExecutionState,
)
from amprealize.work_item_execution_service import WorkItemExecutionError

pytestmark = pytest.mark.unit


class FakeGateway:
    def __init__(self) -> None:
        self.requests = []

    async def execute(self, request):
        self.requests.append(request)
        return ExecutionGatewayResult(
            success=True,
            run_id="run-1",
            cycle_id="cycle-1",
            mode=NewExecutionMode.CONTAINER_ISOLATED,
            output_target=OutputTarget.PULL_REQUEST,
            intent=request.intent,
            compatibility={
                "work_item_id": request.work_item_id,
                "agent_id": request.agent_id_override or "agent-1",
                "model_id": request.model_override or "claude-opus-4-6",
                "status": ExecutionState.PENDING.value,
                "phase": "planning",
                "created_at": "2026-04-24T22:00:00+00:00",
            },
            message="Execution started",
        )


class FakeLegacyService:
    async def execute(self, request):
        raise AssertionError("legacy execute should not be called when gateway is provided")

    def get_status(self, *args, **kwargs):
        return None


class FakeRestControlService:
    def __init__(self) -> None:
        self.cancel_calls = []
        self.clarification_calls = []

    def cancel(self, **kwargs):
        self.cancel_calls.append(kwargs)
        return True

    def provide_clarification(self, **kwargs):
        self.clarification_calls.append(kwargs)
        return True

    def get_status(self, *args, **kwargs):
        return None


class FakeMcpControlService:
    def __init__(self) -> None:
        self.cancel_calls = []
        self.clarification_calls = []

    async def cancel(self, **kwargs):
        self.cancel_calls.append(kwargs)
        return True

    async def provide_clarification(self, **kwargs):
        self.clarification_calls.append(kwargs)
        return True

    async def get_status(self, *args, **kwargs):
        return None


def _gateway_request_signature(request):
    return {
        "work_item_id": request.work_item_id,
        "project_id": request.project_id,
        "org_id": request.org_id,
        "agent_id_override": request.agent_id_override,
        "model_override": request.model_override,
        "agent_execution_mode": request.agent_execution_mode,
        "idempotency_key": request.idempotency_key,
        "intent": request.intent,
        "plan_artifact_id": request.plan_artifact_id,
    }


@pytest.mark.asyncio
async def test_adapter_maps_legacy_request_to_gateway_request():
    gateway = FakeGateway()
    adapter = GatewayWorkItemExecutionAdapter(gateway=gateway)

    response = await adapter.execute(
        ExecuteWorkItemRequest(
            work_item_id="guideai-1046",
            project_id="proj-1",
            user_id="user-1",
            org_id="org-1",
            actor_surface="mcp",
            model_id="claude-opus-4-6",
            agent_execution_mode=AgentExecutionMode.GEP,
            metadata={
                "idempotency_key": "idem-1",
                "agent_id_override": "agent-2",
                "intent": "plan_only",
                "conversation_id": "conv-1",
                "message_id": "msg-1",
                "policy_context": {"tool_profile": "read_only"},
            },
        )
    )

    gateway_request = gateway.requests[0]
    assert gateway_request.work_item_id == "guideai-1046"
    assert gateway_request.project_id == "proj-1"
    assert gateway_request.surface == "mcp"
    assert gateway_request.intent == ExecutionIntent.PLAN_ONLY
    assert gateway_request.idempotency_key == "idem-1"
    assert gateway_request.agent_id_override == "agent-2"
    assert gateway_request.conversation_id == "conv-1"
    assert gateway_request.policy_context == {"tool_profile": "read_only"}
    assert gateway_request.execution_workspace_kind == "cloud_git"
    assert gateway_request.metadata.get("execution_workspace_kind") == "cloud_git"

    assert response.run_id == "run-1"
    assert response.cycle_id == "cycle-1"
    assert response.agent_id == "agent-2"
    assert response.status == ExecutionState.PENDING
    assert response.phase == "planning"


@pytest.mark.asyncio
async def test_adapter_rejects_invalid_execution_workspace_kind():
    gateway = FakeGateway()
    adapter = GatewayWorkItemExecutionAdapter(gateway=gateway)
    with pytest.raises(WorkItemExecutionError, match="Invalid execution_workspace_kind"):
        await adapter.execute(
            ExecuteWorkItemRequest(
                work_item_id="guideai-1046",
                project_id="proj-1",
                user_id="user-1",
                org_id="org-1",
                actor_surface="mcp",
                metadata={"execution_workspace_kind": "unknown_workspace"},
            )
        )


@pytest.mark.asyncio
async def test_mcp_execute_handler_can_use_gateway_adapter():
    gateway = FakeGateway()
    handlers = create_work_item_execution_handlers(
        FakeLegacyService(),
        execution_gateway=gateway,
    )

    result = await handlers["workItems.execute"](
        {
            "work_item_id": "guideai-1046",
            "project_id": "proj-1",
            "user_id": "user-1",
            "actor_surface": "mcp",
            "agent_id": "agent-2",
            "idempotency_key": "idem-1",
            "model_override": "claude-opus-4-6",
            "execution_mode": "gep",
        }
    )

    assert result["success"] is True
    assert result["execution"]["run_id"] == "run-1"
    assert gateway.requests[0].agent_id_override == "agent-2"
    assert gateway.requests[0].idempotency_key == "idem-1"


@pytest.mark.asyncio
async def test_gateway_start_paths_share_equivalent_request_metadata():
    gateway = FakeGateway()
    app = FastAPI()
    app.include_router(
        create_work_item_execution_routes(
            FakeLegacyService(),
            execution_gateway=gateway,
        )
    )
    client = TestClient(app)

    rest_response = client.post(
        "/v1/work-items/guideai-1063:execute?project_id=proj-1&org_id=org-1",
        json={
            "agent_id": "agent-2",
            "idempotency_key": "idem-1",
            "model_override": "claude-opus-4-6",
            "execution_mode": "gep",
        },
    )
    assert rest_response.status_code == 202

    handlers = create_work_item_execution_handlers(
        FakeLegacyService(),
        execution_gateway=gateway,
    )
    mcp_response = await handlers["workItems.execute"](
        {
            "work_item_id": "guideai-1063",
            "project_id": "proj-1",
            "org_id": "org-1",
            "user_id": "user-1",
            "actor_surface": "mcp",
            "agent_id": "agent-2",
            "idempotency_key": "idem-1",
            "model_override": "claude-opus-4-6",
            "execution_mode": "gep",
        }
    )
    assert mcp_response["success"] is True

    adapter = GatewayWorkItemExecutionAdapter(gateway=gateway)
    for surface in ("cli", "chat"):
        response = await adapter.execute(
            ExecuteWorkItemRequest(
                work_item_id="guideai-1063",
                project_id="proj-1",
                org_id="org-1",
                user_id="user-1",
                actor_surface=surface,
                model_id="claude-opus-4-6",
                agent_execution_mode=AgentExecutionMode.GEP,
                metadata={
                    "agent_id_override": "agent-2",
                    "idempotency_key": "idem-1",
                },
            )
        )
        assert response.run_id == "run-1"

    signatures = [_gateway_request_signature(request) for request in gateway.requests]
    assert signatures[0] == signatures[1] == signatures[2] == signatures[3]
    assert [request.surface for request in gateway.requests] == ["api", "mcp", "cli", "chat"]


def test_rest_execute_route_can_use_gateway_adapter():
    gateway = FakeGateway()
    app = FastAPI()
    app.include_router(
        create_work_item_execution_routes(
            FakeLegacyService(),
            execution_gateway=gateway,
        )
    )
    client = TestClient(app)

    response = client.post(
        "/v1/work-items/guideai-1046:execute?project_id=proj-1",
        json={
            "agent_id": "agent-2",
            "idempotency_key": "idem-1",
            "model_override": "claude-opus-4-6",
            "execution_mode": "gep",
        },
    )

    assert response.status_code == 202
    assert response.json()["run_id"] == "run-1"
    assert gateway.requests[0].work_item_id == "guideai-1046"
    assert gateway.requests[0].surface == "api"
    assert gateway.requests[0].agent_id_override == "agent-2"
    assert gateway.requests[0].idempotency_key == "idem-1"


@pytest.mark.asyncio
async def test_cancel_and_clarification_controls_are_consistent_across_rest_and_mcp():
    rest_service = FakeRestControlService()
    app = FastAPI()
    app.include_router(create_work_item_execution_routes(rest_service))
    client = TestClient(app)

    cancel_response = client.post(
        "/v1/work-items/guideai-1063:cancel?org_id=org-1",
        json={"reason": "User requested cancellation"},
    )
    clarify_response = client.post(
        "/v1/work-items/guideai-1063:clarify?org_id=org-1",
        json={"clarification_id": "clarify-1", "response": "Use the gateway path."},
    )

    assert cancel_response.status_code == 200
    assert cancel_response.json()["success"] is True
    assert clarify_response.status_code == 200
    assert clarify_response.json()["success"] is True
    assert rest_service.cancel_calls[0]["work_item_id"] == "guideai-1063"
    assert rest_service.cancel_calls[0]["org_id"] == "org-1"
    assert rest_service.clarification_calls[0]["clarification_id"] == "clarify-1"

    mcp_service = FakeMcpControlService()
    handlers = create_work_item_execution_handlers(mcp_service)
    mcp_cancel = await handlers["workItems.cancelExecution"](
        {
            "work_item_id": "guideai-1063",
            "project_id": "proj-1",
            "org_id": "org-1",
            "user_id": "user-1",
            "reason": "User requested cancellation",
        }
    )
    mcp_clarify = await handlers["workItems.provideClarification"](
        {
            "work_item_id": "guideai-1063",
            "project_id": "proj-1",
            "org_id": "org-1",
            "user_id": "user-1",
            "clarification_id": "clarify-1",
            "response": "Use the gateway path.",
        }
    )

    assert mcp_cancel["success"] is True
    assert mcp_clarify["success"] is True
    assert mcp_service.cancel_calls[0]["work_item_id"] == rest_service.cancel_calls[0]["work_item_id"]
    assert mcp_service.cancel_calls[0]["org_id"] == rest_service.cancel_calls[0]["org_id"]
    assert mcp_service.clarification_calls[0]["clarification_id"] == rest_service.clarification_calls[0]["clarification_id"]
    assert mcp_service.clarification_calls[0]["response"] == rest_service.clarification_calls[0]["response"]
