"""Golden trace fixtures for GUIDEAI-1138 agent execution observability tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from amprealize.execution_observability import (
    ExecutionObservabilityContext,
    sanitize_observability_payload,
)

CORE_CONTEXT_FIELDS: Tuple[str, ...] = (
    "run_id",
    "cycle_id",
    "work_item_id",
    "project_id",
    "agent_id",
    "model_id",
    "surface",
    "request_id",
    "execution_mode",
    "source_type",
)


@dataclass(frozen=True)
class AgentExecutionGoldenScenario:
    """Canonical execution scenario used by golden trace regression tests."""

    name: str
    surface: str
    source_type: str
    execution_mode: str
    expected_event_types: Tuple[str, ...]
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    queue_job_id: Optional[str] = None
    terminal_status: str = "completed"

    def context(self) -> ExecutionObservabilityContext:
        return ExecutionObservabilityContext(
            run_id=f"run-{self.name}",
            cycle_id=f"cycle-{self.name}",
            work_item_id="task-golden-1",
            project_id="proj-golden-1",
            org_id="org-golden-1",
            agent_id="agent-golden-1",
            model_id="claude-sonnet-4-5",
            surface=self.surface,
            conversation_id=self.conversation_id,
            message_id=self.message_id,
            request_id=f"req-{self.name}",
            execution_mode=self.execution_mode,
            source_type=self.source_type,
            queue_job_id=self.queue_job_id,
        )

    def run_metadata(self) -> Dict[str, Any]:
        context = self.context()
        return sanitize_observability_payload(
            {
                "cycle_id": context.cycle_id,
                "phase": "planning",
                "execution_intent": "execute",
                "run_type": "execution",
                "terminal_status": self.terminal_status,
                **context.to_metadata(),
            }
        )

    def task_cycle_metadata(self) -> Dict[str, Any]:
        context = self.context()
        return sanitize_observability_payload(
            {
                "work_item_id": context.work_item_id,
                "run_id": context.run_id,
                "agent_id": context.agent_id,
                "model_id": context.model_id,
                "execution_intent": "execute",
                "run_type": "execution",
                **context.to_metadata(),
            }
        )


AGENT_EXECUTION_GOLDEN_SCENARIOS: Tuple[AgentExecutionGoldenScenario, ...] = (
    AgentExecutionGoldenScenario(
        name="chat_triggered_execution",
        surface="chat",
        source_type="github",
        execution_mode="container_isolated",
        conversation_id="conv-golden-1",
        message_id="msg-golden-1",
        expected_event_types=(
            "execution.gateway.started",
            "execution.phase.started",
            "execution.llm.completed",
            "execution.tool.performance",
            "execution.phase.completed",
            "execution.gateway.completed",
        ),
    ),
    AgentExecutionGoldenScenario(
        name="board_triggered_execution",
        surface="web",
        source_type="local_dir",
        execution_mode="container_isolated",
        expected_event_types=(
            "execution.gateway.started",
            "execution.phase.started",
            "execution.phase.completed",
            "execution.gateway.completed",
        ),
    ),
    AgentExecutionGoldenScenario(
        name="queued_execution",
        surface="chat",
        source_type="github",
        execution_mode="container_isolated",
        conversation_id="conv-golden-queue",
        message_id="msg-golden-queue",
        queue_job_id="job-golden-queue",
        expected_event_types=(
            "execution.gateway.enqueued",
            "execution.worker.started",
            "execution.worker.completed",
        ),
    ),
    AgentExecutionGoldenScenario(
        name="direct_background_execution",
        surface="api",
        source_type="local_dir",
        execution_mode="background",
        expected_event_types=(
            "execution.gateway.started",
            "execution.phase.started",
            "execution.phase.completed",
            "execution.gateway.completed",
        ),
    ),
    AgentExecutionGoldenScenario(
        name="phase_failure",
        surface="web",
        source_type="github",
        execution_mode="container_isolated",
        terminal_status="failed",
        expected_event_types=(
            "execution.phase.started",
            "execution.phase.failed",
        ),
    ),
    AgentExecutionGoldenScenario(
        name="tool_denial",
        surface="chat",
        source_type="github",
        execution_mode="container_isolated",
        conversation_id="conv-golden-denial",
        message_id="msg-golden-denial",
        terminal_status="failed",
        expected_event_types=(
            "execution.tool.started",
            "tool.permission_denied",
            "execution.tool.denied",
            "execution.tool.performance",
        ),
    ),
    AgentExecutionGoldenScenario(
        name="successful_completion",
        surface="web",
        source_type="github",
        execution_mode="container_isolated",
        terminal_status="completed",
        expected_event_types=(
            "execution.phase.started",
            "execution.phase.completed",
        ),
    ),
)


def get_golden_scenario(name: str) -> AgentExecutionGoldenScenario:
    for scenario in AGENT_EXECUTION_GOLDEN_SCENARIOS:
        if scenario.name == name:
            return scenario
    raise KeyError(f"Unknown golden trace scenario: {name}")


def assert_core_context_fields(context: Mapping[str, Any]) -> None:
    missing = [field for field in CORE_CONTEXT_FIELDS if not context.get(field)]
    assert not missing, f"Missing golden trace context fields: {missing}"


def assert_no_secret_leak(payloads: Iterable[Any]) -> None:
    joined = repr(list(payloads))
    assert "abc123456789" not in joined  # pragma: allowlist secret
    assert "secret-value" not in joined
    assert "***REDACTED***" in joined
