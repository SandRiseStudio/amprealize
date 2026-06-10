"""Integration tests for MCP traces.* tools (warehouse read parity with REST)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from amprealize.mcp_server import MCPServer
from amprealize.observability_trace_query import TraceSummaryFilters


@pytest.mark.asyncio
async def test_traces_runs_dispatch_uses_governed_service(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dispatch traces.runs with auth disabled; assert GovernedTraceReadService path and payload."""
    monkeypatch.setenv("MCP_REQUIRE_AUTH", "false")

    server = MCPServer()
    mock_svc = MagicMock()
    mock_svc.list_run_summaries.return_value = {
        "access_tier": "viewer",
        "records": [{"run_id": "run-1", "project_id": "proj-x"}],
        "count": 1,
        "truncated": False,
    }
    monkeypatch.setattr(
        server._services,
        "governed_trace_read_service",
        MagicMock(return_value=mock_svc),
    )

    raw = await server._dispatch_tool_call(
        "req-traces-runs",
        "traces_runs",
        {"project_id": "proj-x", "run_id": "run-1", "limit": 25, "offset": 0},
    )
    response = json.loads(raw)
    assert "error" not in response, response
    body = json.loads(response["result"]["content"][0]["text"])
    assert body["access_tier"] == "viewer"
    assert body["records"][0]["run_id"] == "run-1"
    assert body["query"]["project_id"] == "proj-x"
    assert body["query"]["run_id"] == "run-1"
    assert body["query"]["limit"] == 25

    mock_svc.list_run_summaries.assert_called_once()
    call_actor, call_filters = mock_svc.list_run_summaries.call_args[0]
    assert call_actor["id"] == ""
    assert isinstance(call_filters, TraceSummaryFilters)
    assert call_filters.project_id == "proj-x"
    assert call_filters.run_id == "run-1"
    assert call_filters.limit == 25
    assert call_filters.offset == 0


@pytest.mark.asyncio
async def test_traces_conversations_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_REQUIRE_AUTH", "false")
    server = MCPServer()
    mock_svc = MagicMock()
    mock_svc.list_conversation_summaries.return_value = {
        "access_tier": "viewer",
        "records": [],
        "count": 0,
        "truncated": False,
    }
    monkeypatch.setattr(
        server._services,
        "governed_trace_read_service",
        MagicMock(return_value=mock_svc),
    )

    raw = await server._dispatch_tool_call(
        "req-traces-conv",
        "traces_conversations",
        {"project_id": "proj-c", "conversation_id": "conv-1"},
    )
    response = json.loads(raw)
    assert "error" not in response, response
    _actor, call_filters = mock_svc.list_conversation_summaries.call_args[0]
    assert call_filters.project_id == "proj-c"
    assert call_filters.conversation_id == "conv-1"


@pytest.mark.asyncio
async def test_traces_spans_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_REQUIRE_AUTH", "false")
    server = MCPServer()
    mock_svc = MagicMock()
    mock_svc.get_span_tree.return_value = {
        "access_tier": "viewer",
        "trace_id": "tr-9",
        "records": [{"span_id": "s1"}],
        "count": 1,
        "truncated": False,
    }
    monkeypatch.setattr(
        server._services,
        "governed_trace_read_service",
        MagicMock(return_value=mock_svc),
    )

    raw = await server._dispatch_tool_call(
        "req-traces-spans",
        "traces_spans",
        {"project_id": "proj-s", "trace_id": "tr-9", "limit": 100},
    )
    response = json.loads(raw)
    assert "error" not in response, response
    body = json.loads(response["result"]["content"][0]["text"])
    assert body["trace_id"] == "tr-9"
    mock_svc.get_span_tree.assert_called_once()
    kall = mock_svc.get_span_tree.call_args
    assert kall[1]["project_id"] == "proj-s"
    assert kall[1]["trace_id"] == "tr-9"
    assert kall[1]["limit"] == 100


@pytest.mark.asyncio
async def test_traces_spans_rejects_missing_trace_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_REQUIRE_AUTH", "false")
    server = MCPServer()
    mock_svc = MagicMock()
    monkeypatch.setattr(
        server._services,
        "governed_trace_read_service",
        MagicMock(return_value=mock_svc),
    )

    raw = await server._dispatch_tool_call(
        "req-traces-spans-err",
        "traces_spans",
        {"project_id": "proj-s"},
    )
    response = json.loads(raw)
    assert "error" in response
    assert "trace_id" in response["error"]["message"]
    mock_svc.get_span_tree.assert_not_called()


@pytest.mark.asyncio
async def test_traces_runs_rejects_missing_project_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_REQUIRE_AUTH", "false")
    server = MCPServer()
    mock_svc = MagicMock()
    monkeypatch.setattr(
        server._services,
        "governed_trace_read_service",
        MagicMock(return_value=mock_svc),
    )

    raw = await server._dispatch_tool_call("req-traces-runs-err", "traces_runs", {})
    response = json.loads(raw)
    assert "error" in response
    assert "project_id" in response["error"]["message"]
    mock_svc.list_run_summaries.assert_not_called()
