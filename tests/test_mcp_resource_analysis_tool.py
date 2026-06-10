from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from amprealize.mcp_server import MCPServer

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_resources_analyze_dispatches_through_mcp_tool_call(monkeypatch: pytest.MonkeyPatch) -> None:
    server = MCPServer()
    server._session_context.user_id = "test-user"
    server._session_context.auth_method = "device_flow"
    server._session_context.is_admin = True
    server._session_context.granted_scopes = {"*"}
    server._session_context.expires_at = datetime.utcnow() + timedelta(hours=1)

    async def _fake_analyze(params):
        assert params["query"] == "how many work items are blocked?"
        return {
            "success": True,
            "content": "You have 1 work item in this workspace.",
            "answer_type": "work_items.count",
            "query_plan": {"intent": "count", "resource_type": "work_items"},
            "rows": [{"item_id": "wi-1", "title": "Blocked item"}],
            "metadata": {"analysis_mode": "deterministic", "row_count": 1},
        }

    monkeypatch.setattr(server, "_handle_resources_analyze_tool", _fake_analyze)

    response = json.loads(
        await server._dispatch_tool_call(
            "call-1",
            "resources_analyze",
            {"query": "how many work items are blocked?"},
        )
    )

    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["success"] is True
    assert payload["query_plan"]["resource_type"] == "work_items"
    assert payload["metadata"]["row_count"] == 1
