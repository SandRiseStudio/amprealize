"""Tests for execution worker observability events."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from amprealize.execution_worker import ExecutionWorker, WorkerConfig
from amprealize.telemetry import InMemoryTelemetrySink, TelemetryClient
from execution_queue import ExecutionJob, ExecutionStatus, Priority

pytestmark = pytest.mark.unit


def _make_job() -> ExecutionJob:
    return ExecutionJob(
        job_id="job-1",
        run_id="run-1",
        work_item_id="task-1",
        agent_id="agent-1",
        priority=Priority.NORMAL,
        user_id="user-1",
        project_id="proj-1",
        org_id="org-1",
        model_override="claude-sonnet-4-5",
        cycle_id="cycle-1",
        payload={
            "gateway_request_id": "req-1",
            "surface": "chat",
            "conversation_id": "conv-1",
            "message_id": "msg-1",
            "mode": "container_isolated",
            "source_type": "github",
            "execution_observability": {
                "run_id": "run-1",
                "cycle_id": "cycle-1",
                "work_item_id": "task-1",
                "project_id": "proj-1",
                "org_id": "org-1",
                "agent_id": "agent-1",
                "model_id": "claude-sonnet-4-5",
                "surface": "chat",
                "conversation_id": "conv-1",
                "message_id": "msg-1",
                "request_id": "req-1",
                "execution_mode": "container_isolated",
                "source_type": "github",
                "queue_job_id": "job-1",
            },
        },
    )


@pytest.mark.asyncio
async def test_handle_job_emits_worker_started_and_completed_events():
    sink = InMemoryTelemetrySink()
    worker = ExecutionWorker(
        config=WorkerConfig(provision_workspace=False, consumer_name="worker-test"),
        telemetry=TelemetryClient(sink=sink),
    )
    worker._load_execution_context = AsyncMock(  # noqa: SLF001
        return_value={"exec_policy": SimpleNamespace(require_workspace=False)}
    )
    worker._run_execution_loop = AsyncMock(return_value={})  # noqa: SLF001

    result = await worker._handle_job(_make_job())  # noqa: SLF001

    assert result.status == ExecutionStatus.SUCCESS
    event_types = [event.event_type for event in sink.events]
    assert event_types == ["execution.worker.started", "execution.worker.completed"]
    started_context = sink.events[0].payload["execution_observability"]
    completed_context = sink.events[1].payload["execution_observability"]
    assert started_context["request_id"] == "req-1"
    assert started_context["conversation_id"] == "conv-1"
    assert completed_context["queue_job_id"] == "job-1"
    assert sink.events[1].payload["status"] == "success"


@pytest.mark.asyncio
async def test_handle_job_emits_sanitized_worker_failure_event():
    sink = InMemoryTelemetrySink()
    worker = ExecutionWorker(
        config=WorkerConfig(provision_workspace=False, consumer_name="worker-test"),
        telemetry=TelemetryClient(sink=sink),
    )
    worker._load_execution_context = AsyncMock(  # noqa: SLF001
        return_value={"exec_policy": SimpleNamespace(require_workspace=False)}
    )
    worker._run_execution_loop = AsyncMock(  # noqa: SLF001
        return_value={"error": "token=abc123456789 leaked"}  # gitleaks:allow
    )

    result = await worker._handle_job(_make_job())  # noqa: SLF001

    assert result.status == ExecutionStatus.FAILURE
    failed_event = sink.events[-1]
    assert failed_event.event_type == "execution.worker.failed"
    assert failed_event.payload["error"] == "token=***REDACTED*** leaked"
    assert failed_event.payload["execution_observability"]["run_id"] == "run-1"


@pytest.mark.asyncio
async def test_handle_job_skips_loop_for_local_connector_stage_only():
    sink = InMemoryTelemetrySink()
    worker = ExecutionWorker(
        config=WorkerConfig(provision_workspace=False, consumer_name="worker-test"),
        telemetry=TelemetryClient(sink=sink),
    )
    job = _make_job()
    job.payload["gateway_local_connector_stage_only"] = True
    worker._load_execution_context = AsyncMock()  # noqa: SLF001
    worker._run_execution_loop = AsyncMock()  # noqa: SLF001

    result = await worker._handle_job(job)  # noqa: SLF001

    assert result.status == ExecutionStatus.SUCCESS
    worker._load_execution_context.assert_not_called()  # noqa: SLF001
    worker._run_execution_loop.assert_not_called()  # noqa: SLF001
    assert [e.event_type for e in sink.events] == ["execution.worker.started", "execution.worker.completed"]
