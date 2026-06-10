from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from amprealize.action_contracts import Actor
from amprealize.mcp.handlers.work_item_execution_handlers import create_work_item_execution_handlers
from amprealize.run_contracts import Run, RunStatus, RunStep
from amprealize.services.work_item_execution_api import create_work_item_execution_routes
from amprealize.work_item_execution_contracts import ExecutionState, ExecutionStatusResponse
from amprealize.work_item_execution_service import WorkItemExecutionService

pytestmark = pytest.mark.unit


def _run() -> Run:
    return Run(
        run_id="run-1",
        created_at="2026-04-28T20:00:00+00:00",
        updated_at="2026-04-28T20:00:04+00:00",
        actor=Actor(id="agent-1", role="agent", surface="worker"),
        status=RunStatus.RUNNING,
        workflow_id="work_item_execution",
        current_step="Executing tool",
        progress_pct=50.0,
        started_at="2026-04-28T20:00:00+00:00",
        metadata={
            "cycle_id": "cycle-1",
            "work_item_id": "wi-1",
            "project_id": "proj-1",
            "org_id": "org-1",
            "agent_id": "agent-1",
            "model_id": "claude-4.6",
            "execution_observability": {
                "surface": "chat",
                "conversation_id": "conv-1",
                "message_id": "msg-1",
                "request_id": "req-1",
                "execution_mode": "queue",
                "source_type": "work_item",
                "queue_job_id": "job-1",
            },
        },
        steps=[
            RunStep(
                step_id="step-1",
                name="Tool call",
                status="completed",
                started_at="2026-04-28T20:00:01+00:00",
                completed_at="2026-04-28T20:00:03+00:00",
                progress_pct=50,
                metadata={
                    "phase": "executing",
                    "step_type": "tool_call",
                    "input_tokens": 12,
                    "output_tokens": 8,
                    "cost_usd": 0.01,
                    "tool_calls": [{"tool_name": "resource_analyze"}],
                    "model_id": "claude-4.6",
                    "content_preview": "Analyzed resources",
                },
            )
        ],
    )


def test_execution_status_from_run_includes_trace_context_and_aggregates() -> None:
    service = WorkItemExecutionService.__new__(WorkItemExecutionService)

    status = service._execution_status_from_run(
        _run(),
        work_item_id="wi-1",
        cycle_id="cycle-1",
        phase="executing",
    )

    assert status.surface == "chat"
    assert status.conversation_id == "conv-1"
    assert status.queue_job_id == "job-1"
    assert status.trace_summary["origin"]["surface"] == "chat"
    assert status.trace_summary["execution"]["run_id"] == "run-1"
    assert status.trace_summary["metrics"]["total_tokens"] == 20
    assert status.total_tokens == 20
    assert status.total_cost_usd == 0.01
    assert status.tool_count == 1
    assert status.phase_timings["executing"]["duration_ms"] == 2000


class _FakeExecutionService:
    def get_execution_by_run_id(self, run_id: str, org_id: Optional[str] = None) -> ExecutionStatusResponse:
        assert run_id == "run-1"
        assert org_id == "org-1"
        return ExecutionStatusResponse(
            run_id="run-1",
            cycle_id="cycle-1",
            work_item_id="wi-1",
            status=ExecutionState.RUNNING,
            phase="executing",
            progress_pct=50,
            current_step="Executing tool",
            started_at="2026-04-28T20:00:00+00:00",
            model_id="claude-4.6",
            agent_id="agent-1",
            project_id="proj-1",
            org_id="org-1",
            surface="chat",
            source_type="work_item",
            conversation_id="conv-1",
            message_id="msg-1",
            request_id="req-1",
            execution_mode="queue",
            queue_job_id="job-1",
            queue_metadata={"queue_job_id": "job-1"},
            phase_timings={"executing": {"duration_ms": 2000}},
            trace_summary={
                "origin": {"surface": "chat", "conversation_id": "conv-1"},
                "execution": {"run_id": "run-1", "work_item_id": "wi-1"},
                "metrics": {"total_tokens": 20, "tool_count": 1},
            },
            total_tokens=20,
            total_cost_usd=0.01,
            tool_count=1,
            step_count=1,
        )

    def get_execution_steps(
        self,
        run_id: str,
        org_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        assert run_id == "run-1"
        assert org_id == "org-1"
        return [
            {
                "step_id": "step-1",
                "name": "Tool call",
                "status": "completed",
                "phase": "executing",
                "step_type": "tool_call",
                "started_at": "2026-04-28T20:00:01+00:00",
                "completed_at": "2026-04-28T20:00:03+00:00",
                "duration_ms": 2000,
                "input_tokens": 12,
                "output_tokens": 8,
                "cost_usd": 0.01,
                "tool_calls": 1,
                "tool_names": ["resource_analyze"],
                "model_id": "claude-4.6",
                "metadata": {"phase": "executing"},
            }
        ]


def test_execution_trace_routes_return_rich_status_and_steps() -> None:
    app = FastAPI()
    app.include_router(create_work_item_execution_routes(service=_FakeExecutionService()))  # type: ignore[arg-type]
    client = TestClient(app)

    status_response = client.get("/v1/executions/run-1?org_id=org-1")
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["surface"] == "chat"
    assert status_payload["conversation_id"] == "conv-1"
    assert status_payload["queue_metadata"] == {"queue_job_id": "job-1"}
    assert status_payload["trace_summary"]["origin"]["surface"] == "chat"
    assert status_payload["trace_summary"]["metrics"]["total_tokens"] == 20
    assert status_payload["total_tokens"] == 20
    assert status_payload["tool_count"] == 1

    steps_response = client.get("/v1/executions/run-1/steps?org_id=org-1")
    assert steps_response.status_code == 200
    step = steps_response.json()["steps"][0]
    assert step["duration_ms"] == 2000
    assert step["cost_usd"] == 0.01
    assert step["tool_names"] == ["resource_analyze"]
    assert step["metadata"] == {"phase": "executing"}


class _FakeListExecutionService(_FakeExecutionService):
    def list_executions(
        self,
        org_id: Optional[str] = None,
        project_id: Optional[str] = None,
        status: Optional[ExecutionState] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[ExecutionStatusResponse]:
        assert org_id == "org-1"
        assert project_id == "proj-1"
        assert status is None
        assert limit == 20
        assert offset == 0
        return [self.get_execution_by_run_id("run-1", org_id=org_id)]


def test_execution_list_route_returns_trace_summary_fields() -> None:
    app = FastAPI()
    app.include_router(create_work_item_execution_routes(service=_FakeListExecutionService()))  # type: ignore[arg-type]
    client = TestClient(app)

    response = client.get("/v1/executions?org_id=org-1&project_id=proj-1")

    assert response.status_code == 200
    item = response.json()["executions"][0]
    assert item["run_id"] == "run-1"
    assert item["surface"] == "chat"
    assert item["conversation_id"] == "conv-1"
    assert item["queue_metadata"] == {"queue_job_id": "job-1"}
    assert item["phase_timings"] == {"executing": {"duration_ms": 2000}}
    assert item["trace_summary"]["execution"]["work_item_id"] == "wi-1"
    assert item["total_tokens"] == 20
    assert item["tool_count"] == 1


class _FakeMCPExecutionService:
    async def get_status(
        self,
        work_item_id: str,
        org_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> ExecutionStatusResponse:
        assert work_item_id == "wi-1"
        assert org_id == "org-1"
        assert project_id == "proj-1"
        return _FakeExecutionService().get_execution_by_run_id("run-1", org_id=org_id)

    async def list_executions(
        self,
        org_id: Optional[str] = None,
        project_id: Optional[str] = None,
        status: Optional[ExecutionState] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[ExecutionStatusResponse]:
        assert org_id == "org-1"
        assert project_id == "proj-1"
        assert status is None
        assert limit == 20
        assert offset == 0
        return [_FakeExecutionService().get_execution_by_run_id("run-1", org_id=org_id)]


@pytest.mark.asyncio
async def test_mcp_execution_status_and_list_include_trace_summary_fields() -> None:
    handlers = create_work_item_execution_handlers(service=_FakeMCPExecutionService())  # type: ignore[arg-type]

    status_response = await handlers["workItems.executionStatus"](
        {"work_item_id": "wi-1", "project_id": "proj-1", "org_id": "org-1"}
    )
    list_response = await handlers["workItems.listExecutions"](
        {"project_id": "proj-1", "org_id": "org-1"}
    )

    assert status_response["success"] is True
    assert status_response["status"]["trace_summary"]["origin"]["surface"] == "chat"
    assert status_response["status"]["total_tokens"] == 20
    assert list_response["success"] is True
    assert list_response["executions"][0]["trace_summary"]["metrics"]["tool_count"] == 1
    assert list_response["executions"][0]["conversation_id"] == "conv-1"
