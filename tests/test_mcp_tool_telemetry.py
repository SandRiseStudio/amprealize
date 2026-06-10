"""MCP tools/call emits execution.tool.* telemetry with execution_observability."""

from __future__ import annotations

from amprealize.mcp_server import MCPServer
from amprealize.telemetry import InMemoryTelemetrySink, TelemetryClient


def test_mcp_tool_telemetry_emit_completed_and_performance() -> None:
    sink = InMemoryTelemetrySink()
    telemetry = TelemetryClient(
        sink=sink,
        default_actor={"id": "test", "role": "SYSTEM", "surface": "mcp"},
    )
    server = MCPServer(telemetry_client=telemetry)
    server._emit_mcp_tool_telemetry(
        event_type="execution.tool.completed",
        normalized_tool_name="behaviors_getForTask",
        tool_params={"project_id": "proj-test"},
        request_trace_id="abcd1234",
        call_id="call-1",
        elapsed_ms=12,
        extra={"success": True, "output_preview": "{}"},
    )
    server._emit_mcp_tool_telemetry(
        event_type="execution.tool.performance",
        normalized_tool_name="behaviors_getForTask",
        tool_params={"project_id": "proj-test"},
        request_trace_id="abcd1234",
        call_id="call-1",
        elapsed_ms=12,
        extra={"status": "completed"},
    )
    types = [e.event_type for e in sink.events]
    assert "execution.tool.completed" in types
    assert "execution.tool.performance" in types
    completed = next(e for e in sink.events if e.event_type == "execution.tool.completed")
    assert completed.payload.get("tool_name") == "behaviors.getForTask"
    assert completed.payload.get("execution_observability", {}).get("surface") == "mcp"
    assert completed.payload.get("execution_observability", {}).get("project_id") == "proj-test"
