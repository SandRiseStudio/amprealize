"""Tests for AgentExecutionLoop observability events."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from amprealize.agent_execution_loop import AgentExecutionLoop, PhaseResult
from amprealize.execution_observability import ExecutionObservabilityContext
from amprealize.task_cycle_contracts import CyclePhase
from amprealize.telemetry import InMemoryTelemetrySink, TelemetryClient
from amprealize.work_item_execution_contracts import (
    AgentResponse,
    ExecutionPolicy,
    ToolCall,
)

pytestmark = pytest.mark.unit


class _RunService:
    def __init__(self) -> None:
        self.steps: List[Dict[str, Any]] = []

    def add_step(self, **kwargs: Any) -> None:
        self.steps.append(kwargs)


class _TaskCycleService:
    pass


def _make_loop() -> tuple[AgentExecutionLoop, InMemoryTelemetrySink, _RunService]:
    sink = InMemoryTelemetrySink()
    run_service = _RunService()
    loop = AgentExecutionLoop(
        run_service=run_service,
        task_cycle_service=_TaskCycleService(),
        telemetry=TelemetryClient(sink=sink),
        enable_early_retrieval=False,
    )
    return loop, sink, run_service


def _work_item() -> SimpleNamespace:
    return SimpleNamespace(
        item_id="task-1",
        project_id="proj-1",
        title="Implement observability",
    )


def _agent() -> SimpleNamespace:
    return SimpleNamespace(agent_id="agent-1", name="Agent One")


@pytest.mark.asyncio
async def test_execute_phase_emits_started_completed_and_run_step_context():
    loop, sink, run_service = _make_loop()

    async def handler(**kwargs: Any) -> PhaseResult:
        return PhaseResult(
            success=True,
            phase=CyclePhase.PLANNING,
            outputs={"plan": "do it"},
            tool_calls=[ToolCall(tool_name="read_file", tool_args={"path": "README.md"})],
            should_advance=True,
            next_phase=CyclePhase.ARCHITECTING,
        )

    loop._phase_handlers[CyclePhase.PLANNING] = handler  # noqa: SLF001

    result = await loop._execute_phase(  # noqa: SLF001
        phase=CyclePhase.PLANNING,
        run_id="run-1",
        cycle_id="cycle-1",
        work_item=_work_item(),
        agent=_agent(),
        agent_version=None,
        exec_policy=ExecutionPolicy(),
        model_id="claude-sonnet-4-5",
        playbook={},
        previous_outputs={},
        project_id="proj-1",
        org_id="org-1",
    )

    assert result.success is True
    assert [event.event_type for event in sink.events] == [
        "execution.phase.started",
        "execution.phase.completed",
    ]
    started_context = sink.events[0].payload["execution_observability"]
    completed = sink.events[1].payload
    assert started_context["run_id"] == "run-1"
    assert started_context["cycle_id"] == "cycle-1"
    assert started_context["work_item_id"] == "task-1"
    assert started_context["agent_id"] == "agent-1"
    assert completed["phase"] == "planning"
    assert completed["tool_call_count"] == 1
    phase_end_step = run_service.steps[-1]
    assert phase_end_step["metadata"]["execution_observability"]["run_id"] == "run-1"
    assert phase_end_step["metadata"]["phase_success"] is True


def test_record_llm_response_emits_metrics_and_sanitized_preview():
    loop, sink, run_service = _make_loop()
    loop._current_observability_context = ExecutionObservabilityContext(  # noqa: SLF001
        run_id="run-1",
        cycle_id="cycle-1",
        work_item_id="task-1",
        project_id="proj-1",
        org_id="org-1",
        agent_id="agent-1",
        model_id="claude-sonnet-4-5",
        execution_mode="gep",
    )
    response = AgentResponse(
        text_output="token=abc123456789 should be redacted",  # gitleaks:allow
        input_tokens=10,
        output_tokens=20,
        cost_usd=0.03,
        phase_complete=True,
    )

    loop._record_llm_response(  # noqa: SLF001
        run_id="run-1",
        phase="planning",
        model_id="claude-sonnet-4-5",
        response=response,
    )

    assert run_service.steps[0]["metadata"]["execution_observability"]["cycle_id"] == "cycle-1"
    event = sink.events[0]
    assert event.event_type == "execution.llm.completed"
    assert event.payload["input_tokens"] == 10
    assert event.payload["output_tokens"] == 20
    assert event.payload["cost_usd"] == 0.03
    assert event.payload["output_preview"] == "token=***REDACTED*** should be redacted"
