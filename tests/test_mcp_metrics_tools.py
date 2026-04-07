"""Test MCP server metrics tools integration.

Validates JSON-RPC 2.0 protocol compliance for all 3 MetricsService MCP tools:
- metrics.getSummary
- metrics.export
- metrics.subscribe

Each test follows the pattern:
1. Construct JSON-RPC request with tool name and arguments
2. Call mcp_server.handle_request()
3. Parse JSON-RPC response
4. Validate response structure (jsonrpc, id, result/error)
5. Validate nested content format (MCP content array with text)
6. Validate tool-specific result payload
"""

import json
import pytest
from datetime import datetime, timedelta
from amprealize.mcp_server import MCPServer


def _authenticated_server(server):
    """Authenticate an MCPServer session for testing."""
    server._session_context.user_id = "test-user"
    server._session_context.auth_method = "device_flow"
    server._session_context.is_admin = True
    server._session_context.granted_scopes = {"*"}
    server._session_context.expires_at = datetime.utcnow() + timedelta(hours=1)
    return server


@pytest.fixture
def mcp_server():
    """Create MCP server instance for testing."""
    return _authenticated_server(MCPServer())


@pytest.mark.asyncio
async def test_metrics_get_summary_tool(mcp_server):
    """Test metrics.getSummary tool retrieves metrics summary."""
    request = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/call",
        "params": {
            "name": "metrics.getSummary",
            "arguments": {
                "start_date": "2025-10-01",
                "end_date": "2025-10-31"
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(request))
    response = json.loads(response_str)

    # Validate JSON-RPC structure
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "1"
    assert "result" in response
    assert "content" in response["result"]

    # Parse nested MCP content
    content_text = response["result"]["content"][0]["text"]
    result = json.loads(content_text)

    # Validate result structure - MetricsSummary dataclass fields
    assert "snapshot_time" in result
    assert "behavior_reuse_pct" in result
    assert "average_token_savings_pct" in result
    assert isinstance(result["behavior_reuse_pct"], (int, float))


@pytest.mark.asyncio
async def test_metrics_export_tool(mcp_server):
    """Test metrics.export tool exports metrics data."""
    request = {
        "jsonrpc": "2.0",
        "id": "2",
        "method": "tools/call",
        "params": {
            "name": "metrics.export",
            "arguments": {
                "format": "json",
                "metrics": ["behavior_reuse", "token_savings"],
                "start_date": "2025-10-01",
                "end_date": "2025-10-31",
                "include_raw_events": False
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(request))
    response = json.loads(response_str)

    # Validate JSON-RPC structure
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "2"
    assert "result" in response
    assert "content" in response["result"]

    # Parse nested MCP content
    content_text = response["result"]["content"][0]["text"]
    result = json.loads(content_text)

    # Validate export structure - MetricsExportResult dataclass fields
    assert "export_id" in result
    assert "format" in result
    assert result["format"] == "json"
    assert "data" in result  # Changed from "metrics" to "data"
    assert isinstance(result["data"], list)


@pytest.mark.asyncio
async def test_metrics_subscribe_tool(mcp_server):
    """Test metrics.subscribe tool creates subscription."""
    request = {
        "jsonrpc": "2.0",
        "id": "3",
        "method": "tools/call",
        "params": {
            "name": "metrics.subscribe",
            "arguments": {
                "metrics": ["behavior_reuse", "token_savings", "completion_rate"],
                "refresh_interval_seconds": 60
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(request))
    response = json.loads(response_str)

    # Validate JSON-RPC structure
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "3"
    assert "result" in response
    assert "content" in response["result"]

    # Parse nested MCP content
    content_text = response["result"]["content"][0]["text"]
    result = json.loads(content_text)

    # Validate subscription structure
    assert "subscription_id" in result
    assert "metrics" in result
    assert result["metrics"] == ["behavior_reuse", "token_savings", "completion_rate"]
    assert "refresh_interval_seconds" in result
    assert result["refresh_interval_seconds"] == 60


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
