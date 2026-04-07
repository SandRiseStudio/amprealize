"""Test MCP server analytics tools integration.

Validates JSON-RPC 2.0 protocol compliance for all 4 AnalyticsWarehouse MCP tools:
- analytics.kpiSummary
- analytics.behaviorUsage
- analytics.tokenSavings
- analytics.complianceCoverage

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
async def test_analytics_kpi_summary_tool(mcp_server):
    """Test analytics.kpiSummary tool retrieves KPI summary."""
    request = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/call",
        "params": {
            "name": "analytics.kpiSummary",
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

    # Validate result structure
    assert "records" in result
    assert "count" in result
    assert isinstance(result["records"], list)
    assert isinstance(result["count"], int)


@pytest.mark.asyncio
async def test_analytics_behavior_usage_tool(mcp_server):
    """Test analytics.behaviorUsage tool retrieves behavior usage facts."""
    request = {
        "jsonrpc": "2.0",
        "id": "2",
        "method": "tools/call",
        "params": {
            "name": "analytics.behaviorUsage",
            "arguments": {
                "start_date": "2025-10-01",
                "end_date": "2025-10-31",
                "limit": 50
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

    # Validate result structure
    assert "records" in result
    assert "count" in result
    assert isinstance(result["records"], list)
    assert isinstance(result["count"], int)


@pytest.mark.asyncio
async def test_analytics_token_savings_tool(mcp_server):
    """Test analytics.tokenSavings tool retrieves token savings facts."""
    request = {
        "jsonrpc": "2.0",
        "id": "3",
        "method": "tools/call",
        "params": {
            "name": "analytics.tokenSavings",
            "arguments": {
                "start_date": "2025-10-01",
                "end_date": "2025-10-31",
                "limit": 100
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

    # Validate result structure
    assert "records" in result
    assert "count" in result
    assert isinstance(result["records"], list)
    assert isinstance(result["count"], int)


@pytest.mark.asyncio
async def test_analytics_compliance_coverage_tool(mcp_server):
    """Test analytics.complianceCoverage tool retrieves compliance steps facts."""
    request = {
        "jsonrpc": "2.0",
        "id": "4",
        "method": "tools/call",
        "params": {
            "name": "analytics.complianceCoverage",
            "arguments": {
                "start_date": "2025-10-01",
                "end_date": "2025-10-31",
                "limit": 100
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(request))
    response = json.loads(response_str)

    # Validate JSON-RPC structure
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "4"
    assert "result" in response
    assert "content" in response["result"]

    # Parse nested MCP content
    content_text = response["result"]["content"][0]["text"]
    result = json.loads(content_text)

    # Validate result structure
    assert "records" in result
    assert "count" in result
    assert isinstance(result["records"], list)
    assert isinstance(result["count"], int)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
