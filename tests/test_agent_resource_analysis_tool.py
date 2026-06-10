from __future__ import annotations

import json

import pytest

from amprealize.tool_executor import ToolExecutor
from amprealize.agent_execution_loop import AgentExecutionLoop
from amprealize.task_cycle_contracts import CyclePhase
from amprealize.work_item_execution_contracts import ExecutionPolicy, ToolCall

pytestmark = pytest.mark.unit


def _provider(**kwargs):
    assert kwargs["project_id"] == "proj-guideai"
    return {
        "projects": [{"project_id": "proj-guideai", "name": "GuideAI"}],
        "boards_by_project": {
            "proj-guideai": [{"board_id": "board-guideai", "name": "GuideAI board"}]
        },
        "work_items_by_project": {
            "proj-guideai": [
                {
                    "item_id": "wi-1",
                    "title": "Fix chat routing",
                    "status": "blocked",
                    "board_id": "board-guideai",
                }
            ]
        },
        "runs": [{"run_id": "run-1", "status": "failed", "project_id": "proj-guideai"}],
    }


@pytest.mark.asyncio
async def test_resource_analyze_tool_answers_during_agent_execution() -> None:
    executor = ToolExecutor(
        ExecutionPolicy(),
        github_context={
            "project_id": "proj-guideai",
            "org_id": "org-1",
            "user_id": "user-1",
        },
        resource_analysis_inventory_provider=_provider,
    )

    result = await executor.execute(
        ToolCall(
            tool_name="resource_analyze",
            tool_args={"query": "before executing, inspect related board items and recent failed runs"},
        )
    )

    assert result.success is True
    payload = json.loads(result.output)
    assert payload["success"] is True
    assert payload["query_plan"]["resource_type"] in {"work_items", "runs"}
    assert payload["rows"]
    assert payload["metadata"]["analysis_mode"] == "deterministic"
    assert payload["metadata"]["row_count"] == len(payload["rows"])


def test_resource_analyze_tool_schema_is_available() -> None:
    executor = ToolExecutor(ExecutionPolicy())

    schemas = executor.get_tool_schemas(["resource_analyze"])

    assert "resource_analyze" in schemas
    assert schemas["resource_analyze"]["input_schema"]["required"] == ["query"]


def test_resource_analyze_is_available_to_agent_phases() -> None:
    loop = AgentExecutionLoop(
        run_service=object(),
        task_cycle_service=object(),
        enable_early_retrieval=False,
    )

    assert "resource_analyze" in loop._get_available_tools(CyclePhase.PLANNING, ExecutionPolicy())
    assert "resource_analyze" in loop._get_available_tools(CyclePhase.ARCHITECTING, ExecutionPolicy())
    assert "resource_analyze" in loop._get_available_tools(CyclePhase.EXECUTING, ExecutionPolicy())
