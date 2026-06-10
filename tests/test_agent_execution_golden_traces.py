"""Golden trace regression tests for GUIDEAI-1138."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest

from amprealize.agent_execution_loop import AgentExecutionLoop, PhaseResult
from amprealize.execution_observability import ExecutionObservabilityContext
from amprealize.execution_worker import ExecutionWorker, WorkerConfig
from amprealize.task_cycle_contracts import CyclePhase
from amprealize.telemetry import InMemoryTelemetrySink, TelemetryClient
from amprealize.tool_executor import ToolCategory, ToolDefinition, ToolExecutor, ToolRegistry
from amprealize.work_item_execution_contracts import ExecutionPolicy, ToolCall, WriteScope
from execution_queue import ExecutionJob, ExecutionStatus, Priority
from tests.fixtures.agent_execution_golden_traces import (
    AGENT_EXECUTION_GOLDEN_SCENARIOS,
    assert_core_context_fields,
    assert_no_secret_leak,
    get_golden_scenario,
)

pytestmark = pytest.mark.unit


class _RunService:
    def __init__(self) -> None:
        self.steps: List[Dict[str, Any]] = []

    def add_step(self, **kwargs: Any) -> None:
        self.steps.append(kwargs)


class _TaskCycleService:
    pass


def _work_item() -> SimpleNamespace:
    return SimpleNamespace(
        item_id="task-golden-1",
        project_id="proj-golden-1",
        title="Create golden traces",
    )


def _agent() -> SimpleNamespace:
    return SimpleNamespace(agent_id="agent-golden-1", name="Golden Agent")


def _make_loop(context: ExecutionObservabilityContext | None = None) -> tuple[AgentExecutionLoop, InMemoryTelemetrySink, _RunService]:
    sink = InMemoryTelemetrySink()
    run_service = _RunService()
    loop = AgentExecutionLoop(
        run_service=run_service,
        task_cycle_service=_TaskCycleService(),
        telemetry=TelemetryClient(sink=sink),
        enable_early_retrieval=False,
    )
    loop._current_observability_context = context  # noqa: SLF001
    return loop, sink, run_service


async def _denied_handler(**kwargs: Any) -> Dict[str, Any]:
    return {"success": True}


def _denied_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="write_denied",
            description="A write tool denied by read-only policy",
            input_schema={"type": "object", "properties": {}},
            category=ToolCategory.WRITE,
            is_write_operation=True,
            handler=_denied_handler,
        )
    )
    return registry


def _job_from_context(context: ExecutionObservabilityContext) -> ExecutionJob:
    return ExecutionJob(
        job_id=context.queue_job_id or "job-golden-queue",
        run_id=context.run_id or "run-golden-queue",
        work_item_id=context.work_item_id,
        agent_id=context.agent_id or "agent-golden-1",
        priority=Priority.NORMAL,
        user_id="user-golden-1",
        project_id=context.project_id,
        org_id=context.org_id,
        model_override=context.model_id,
        cycle_id=context.cycle_id,
        payload={
            "gateway_request_id": context.request_id,
            "surface": context.surface,
            "conversation_id": context.conversation_id,
            "message_id": context.message_id,
            "mode": context.execution_mode,
            "source_type": context.source_type,
            **context.to_metadata(),
        },
    )


def test_golden_trace_fixtures_cover_agent_execution_scenarios_and_core_fields():
    names = {scenario.name for scenario in AGENT_EXECUTION_GOLDEN_SCENARIOS}
    assert {
        "chat_triggered_execution",
        "board_triggered_execution",
        "queued_execution",
        "direct_background_execution",
        "phase_failure",
        "tool_denial",
        "successful_completion",
    }.issubset(names)

    for scenario in AGENT_EXECUTION_GOLDEN_SCENARIOS:
        run_context = scenario.run_metadata()["execution_observability"]
        cycle_context = scenario.task_cycle_metadata()["execution_observability"]
        assert_core_context_fields(run_context)
        assert_core_context_fields(cycle_context)
        assert run_context["surface"] == scenario.surface
        assert cycle_context["source_type"] == scenario.source_type


@pytest.mark.asyncio
async def test_successful_completion_golden_trace_matches_phase_events_and_run_steps():
    scenario = get_golden_scenario("successful_completion")
    loop, sink, run_service = _make_loop(scenario.context())

    async def handler(**kwargs: Any) -> PhaseResult:
        return PhaseResult(
            success=True,
            phase=CyclePhase.COMPLETING,
            outputs={"summary": "completed"},
            should_advance=False,
        )

    loop._phase_handlers[CyclePhase.COMPLETING] = handler  # noqa: SLF001

    result = await loop._execute_phase(  # noqa: SLF001
        phase=CyclePhase.COMPLETING,
        run_id=scenario.context().run_id or "run-success",
        cycle_id=scenario.context().cycle_id or "cycle-success",
        work_item=_work_item(),
        agent=_agent(),
        agent_version=None,
        exec_policy=ExecutionPolicy(),
        model_id="claude-sonnet-4-5",
        playbook={},
        previous_outputs={},
        project_id="proj-golden-1",
        org_id="org-golden-1",
    )

    assert result.success is True
    assert [event.event_type for event in sink.events] == list(scenario.expected_event_types)
    completed_context = sink.events[-1].payload["execution_observability"]
    assert completed_context["surface"] == "web"
    assert completed_context["request_id"] == scenario.context().request_id
    phase_end_step = run_service.steps[-1]
    assert phase_end_step["metadata"]["phase_success"] is True
    assert phase_end_step["metadata"]["execution_observability"]["surface"] == "web"


@pytest.mark.asyncio
async def test_phase_failure_golden_trace_redacts_errors_in_events_and_run_steps():
    scenario = get_golden_scenario("phase_failure")
    loop, sink, run_service = _make_loop(scenario.context())

    async def handler(**kwargs: Any) -> PhaseResult:
        raise RuntimeError("token=abc123456789 leaked")  # gitleaks:allow

    loop._phase_handlers[CyclePhase.EXECUTING] = handler  # noqa: SLF001

    result = await loop._execute_phase(  # noqa: SLF001
        phase=CyclePhase.EXECUTING,
        run_id=scenario.context().run_id or "run-failure",
        cycle_id=scenario.context().cycle_id or "cycle-failure",
        work_item=_work_item(),
        agent=_agent(),
        agent_version=None,
        exec_policy=ExecutionPolicy(),
        model_id="claude-sonnet-4-5",
        playbook={},
        previous_outputs={},
        project_id="proj-golden-1",
        org_id="org-golden-1",
    )

    assert result.success is False
    assert [event.event_type for event in sink.events] == list(scenario.expected_event_types)
    failed = sink.events[-1]
    assert failed.payload["error"] == "token=***REDACTED*** leaked"
    failure_step = run_service.steps[-1]
    assert failure_step["metadata"]["phase_success"] is False
    assert_no_secret_leak([failed.payload, failure_step["metadata"], failure_step["outcome"]])


@pytest.mark.asyncio
async def test_tool_denial_golden_trace_preserves_context_and_redaction():
    scenario = get_golden_scenario("tool_denial")
    context = scenario.context()
    sink = InMemoryTelemetrySink()
    policy = ExecutionPolicy()
    policy.write_scope = WriteScope.READ_ONLY
    executor = ToolExecutor(
        policy,
        registry=_denied_registry(),
        telemetry=TelemetryClient(sink=sink),
        current_phase="executing",
        observability_context=context,
    )

    result = await executor.execute(
        ToolCall(
            tool_name="write_denied",
            tool_args={"password": "secret-value"},  # pragma: allowlist secret
            call_id="call-denied",
        )
    )

    assert result.success is False
    assert [event.event_type for event in sink.events] == list(scenario.expected_event_types)
    denied = next(event for event in sink.events if event.event_type == "execution.tool.denied")
    started = next(event for event in sink.events if event.event_type == "execution.tool.started")
    assert denied.payload["execution_observability"]["conversation_id"] == "conv-golden-denial"
    assert started.payload["inputs"]["password"] == "***REDACTED***"
    assert_no_secret_leak([event.payload for event in sink.events])


@pytest.mark.asyncio
async def test_queued_execution_golden_trace_matches_worker_events():
    scenario = get_golden_scenario("queued_execution")
    context = scenario.context()
    sink = InMemoryTelemetrySink()
    worker = ExecutionWorker(
        config=WorkerConfig(provision_workspace=False, consumer_name="golden-worker"),
        telemetry=TelemetryClient(sink=sink),
    )
    worker._load_execution_context = AsyncMock(  # noqa: SLF001
        return_value={"exec_policy": SimpleNamespace(require_workspace=False)}
    )
    worker._run_execution_loop = AsyncMock(return_value={})  # noqa: SLF001

    result = await worker._handle_job(_job_from_context(context))  # noqa: SLF001

    assert result.status == ExecutionStatus.SUCCESS
    assert [event.event_type for event in sink.events] == ["execution.worker.started", "execution.worker.completed"]
    started_context = sink.events[0].payload["execution_observability"]
    completed_context = sink.events[1].payload["execution_observability"]
    assert started_context["queue_job_id"] == "job-golden-queue"
    assert started_context["conversation_id"] == "conv-golden-queue"
    assert completed_context["request_id"] == scenario.context().request_id
