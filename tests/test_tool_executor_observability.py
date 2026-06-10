"""Tests for ToolExecutor execution observability events."""

from __future__ import annotations

from typing import Any

import pytest

from amprealize.execution_observability import ExecutionObservabilityContext
from amprealize.telemetry import InMemoryTelemetrySink, TelemetryClient
from amprealize.tool_executor import ToolCategory, ToolDefinition, ToolExecutor, ToolRegistry
from amprealize.work_item_execution_contracts import ExecutionPolicy, ToolCall, WriteScope

pytestmark = pytest.mark.unit


async def _echo_handler(**kwargs: Any) -> dict[str, Any]:
    return {"text": "token=abc123456789 should be hidden", "ok": True}  # gitleaks:allow


async def _create_resource_handler(**kwargs: Any) -> dict[str, Any]:
    return {"success": True, "resource_type": "work_item", "item_id": "wi-1"}


def _context() -> ExecutionObservabilityContext:
    return ExecutionObservabilityContext(
        run_id="run-1",
        cycle_id="cycle-1",
        work_item_id="task-1",
        project_id="proj-1",
        org_id="org-1",
        agent_id="agent-1",
        model_id="claude-sonnet-4-5",
        execution_mode="gep",
    )


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="echo_secret",
        description="Echo a sanitized secret",
        input_schema={"type": "object", "properties": {}},
        category=ToolCategory.READ,
        handler=_echo_handler,
    ))
    registry.register(ToolDefinition(
        name="write_denied",
        description="A write tool denied by read-only policy",
        input_schema={"type": "object", "properties": {}},
        category=ToolCategory.WRITE,
        is_write_operation=True,
        handler=_echo_handler,
    ))
    registry.register(ToolDefinition(
        name="create_resource",
        description="Create a resource outcome",
        input_schema={"type": "object", "properties": {}},
        category=ToolCategory.WRITE,
        is_write_operation=True,
        handler=_create_resource_handler,
    ))
    return registry


@pytest.mark.asyncio
async def test_tool_executor_emits_started_and_completed_with_context():
    sink = InMemoryTelemetrySink()
    executor = ToolExecutor(
        ExecutionPolicy(),
        registry=_registry(),
        telemetry=TelemetryClient(sink=sink),
        current_phase="planning",
        observability_context=_context(),
    )

    result = await executor.execute(
        ToolCall(
            tool_name="echo_secret",
            tool_args={"api_key": "secret-value", "path": "README.md"},  # pragma: allowlist secret
            call_id="call-1",
        )
    )

    assert result.success is True
    event_types = [event.event_type for event in sink.events]
    assert "execution.tool.started" in event_types
    assert "execution.tool.completed" in event_types
    assert "execution.tool.performance" in event_types
    started = next(event for event in sink.events if event.event_type == "execution.tool.started")
    completed = next(event for event in sink.events if event.event_type == "execution.tool.completed")
    performance = next(event for event in sink.events if event.event_type == "execution.tool.performance")
    assert started.payload["execution_observability"]["run_id"] == "run-1"
    assert started.payload["inputs"]["api_key"] == "***REDACTED***"
    assert completed.payload["phase"] == "planning"
    assert completed.payload["output_preview"] == '{"text": "token=***REDACTED*** should be hidden", "ok": true}'
    assert performance.payload["status"] == "completed"
    assert "output_preview" not in performance.payload


@pytest.mark.asyncio
async def test_tool_executor_emits_denied_with_sanitized_context():
    sink = InMemoryTelemetrySink()
    policy = ExecutionPolicy()
    policy.write_scope = WriteScope.READ_ONLY
    executor = ToolExecutor(
        policy,
        registry=_registry(),
        telemetry=TelemetryClient(sink=sink),
        current_phase="executing",
        observability_context=_context(),
    )

    result = await executor.execute(
        ToolCall(
            tool_name="write_denied",
            tool_args={"password": "secret-value"},  # pragma: allowlist secret
            call_id="call-2",
        )
    )

    assert result.success is False
    denied = next(event for event in sink.events if event.event_type == "execution.tool.denied")
    assert denied.payload["execution_observability"]["cycle_id"] == "cycle-1"
    assert denied.payload["reason"] == "Write operations not permitted"
    assert denied.payload["phase"] == "executing"
    performance = next(event for event in sink.events if event.event_type == "execution.tool.performance")
    assert performance.payload["status"] == "denied"
    assert performance.payload["error_class"] == "ToolPermissionError"


@pytest.mark.asyncio
async def test_tool_executor_emits_business_outcome_separate_from_performance():
    sink = InMemoryTelemetrySink()
    executor = ToolExecutor(
        ExecutionPolicy(),
        registry=_registry(),
        telemetry=TelemetryClient(sink=sink),
        current_phase="executing",
        observability_context=_context(),
    )

    result = await executor.execute(
        ToolCall(
            tool_name="create_resource",
            tool_args={"title": "Trace analytics"},
            call_id="call-3",
        )
    )

    assert result.success is True
    performance = next(event for event in sink.events if event.event_type == "execution.tool.performance")
    outcome = next(event for event in sink.events if event.event_type == "execution.tool.business_outcome")
    assert performance.payload["tool_name"] == "create_resource"
    assert performance.payload["status"] == "completed"
    assert outcome.payload["resource_type"] == "work_item"
    assert outcome.payload["resource_id"] == "wi-1"
    assert outcome.payload["outcome_ref"] == "work_item:wi-1"
