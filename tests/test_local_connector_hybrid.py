"""Tests for local connector hybrid delegation (ToolExecutor + hub helpers)."""

from __future__ import annotations

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_tool_executor_read_file_delegates_to_connector():
    from amprealize.tool_executor import ToolExecutor
    from amprealize.work_item_execution_contracts import (
        ExecutionPolicy,
        InternetAccessPolicy,
        ToolCall,
        WriteScope,
    )

    policy = ExecutionPolicy(
        write_scope=WriteScope.LOCAL_ONLY,
        internet_access=InternetAccessPolicy.DISABLED,
    )
    delegate = MagicMock()
    delegate.invoke = AsyncMock(return_value="file-contents")
    ex = ToolExecutor(policy, connector_delegate=delegate)
    tc = ToolCall(tool_name="read_file", tool_args={"path": "src/a.py"})
    result = await ex.execute(tc)
    assert result.success is True
    assert result.output == "file-contents"
    delegate.invoke.assert_awaited_once_with(
        "read_file",
        {"path": "src/a.py", "start_line": None, "end_line": None},
    )


@pytest.mark.asyncio
async def test_local_connector_hybrid_provision_signals_lease_ack():
    from amprealize.execution_gateway_contracts import (
        ExecutionRequest,
        NewExecutionMode,
        OutputTarget,
        ResolvedExecution,
        SourceType,
    )
    from amprealize.local_execution_connector_hub import (
        get_local_execution_connector_hub,
        reset_local_execution_connector_hub_for_tests,
    )
    from amprealize.mode_executors import LocalConnectorHybridExecutor

    reset_local_execution_connector_hub_for_tests()
    req = ExecutionRequest(
        work_item_id="task-abc123def456",
        project_id="proj-1",
        surface="web",
        user_id="user-1",
    )
    resolved = ResolvedExecution(
        run_id="run-lease-1",
        cycle_id="cyc-1",
        request=req,
        mode=NewExecutionMode.LOCAL_CONNECTOR_HYBRID,
        output_target=OutputTarget.LOCAL_SYNC,
        source_type=SourceType.LOCAL_DIR,
        source_url=None,
        source_ref="main",
        model_id="m1",
        api_key="k",
        credential_source="platform",
        is_byok=False,
        agent_id="agent-1",
    )
    ex = LocalConnectorHybridExecutor()

    async def _ack_soon() -> None:
        await asyncio.sleep(0.02)
        get_local_execution_connector_hub().signal_lease_ack("run-lease-1")

    asyncio.create_task(_ack_soon())
    out = await ex.provision_workspace(resolved)
    assert out.workspace_path is None
    reset_local_execution_connector_hub_for_tests()
