"""Test MCP server run tools integration.

Validates JSON-RPC 2.0 protocol compliance for all 6 RunService MCP tools:
- runs.create
- runs.list
- runs.get
- runs.updateProgress
- runs.complete
- runs.cancel

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
import os
import psycopg2
from datetime import datetime, timedelta
from amprealize.mcp_server import MCPServer


@pytest.fixture
def clean_run_db():
    """Clean run database before each test."""
    dsn = os.getenv("AMPREALIZE_RUN_PG_DSN")
    if not dsn:
        pytest.skip("AMPREALIZE_RUN_PG_DSN not set")
    from conftest import safe_truncate
    safe_truncate(dsn, ["run_steps", "runs"])
    # Seed test actors so FK constraint on runs.user_id passes
    import psycopg2
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO auth.users (id, email, display_name)
            VALUES (%s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            ("test-strategist", "test-strategist@example.com", "Test Strategist"),
        )
    conn.close()


def _authenticated_server(server):
    """Authenticate an MCPServer session for testing."""
    server._session_context.user_id = "test-user"
    server._session_context.auth_method = "device_flow"
    server._session_context.is_admin = True
    server._session_context.granted_scopes = {"*"}
    server._session_context.expires_at = datetime.utcnow() + timedelta(hours=1)
    return server


@pytest.fixture
def mcp_server(clean_run_db):
    """Create MCP server instance for testing."""
    return _authenticated_server(MCPServer())


@pytest.fixture
def actor():
    """Standard test actor payload."""
    return {
        "id": "test-strategist",
        "role": "STRATEGIST",
        "surface": "mcp"
    }


@pytest.mark.asyncio
async def test_runs_create_tool(mcp_server, actor):
    """Test runs.create tool creates a new run."""
    request = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/call",
        "params": {
            "name": "runs.create",
            "arguments": {
                "actor": actor,
                "workflow_id": "wf_001",
                "workflow_name": "Sprint 1 P0 Validation",
                "template_id": "tmpl_001",
                "template_name": "Service Parity Template",
                "behavior_ids": ["bhv_001", "bhv_002"],
                "metadata": {"priority": "P0", "sprint": "1"},
                "initial_message": "Starting Sprint 1 P0 validation",
                "total_steps": 4,
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(request))
    response = json.loads(response_str)

    # Validate JSON-RPC structure
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "1"
    assert "result" in response
    assert "error" not in response

    # Validate MCP content format
    result = response["result"]
    assert "content" in result
    assert isinstance(result["content"], list)
    assert len(result["content"]) > 0
    assert result["content"][0]["type"] == "text"

    # Parse nested JSON payload
    run_data = json.loads(result["content"][0]["text"])

    # Validate run structure
    assert "run_id" in run_data
    assert run_data["status"] == "PENDING"
    assert run_data["workflow_id"] == "wf_001"
    assert run_data["workflow_name"] == "Sprint 1 P0 Validation"
    assert run_data["template_id"] == "tmpl_001"
    assert run_data["template_name"] == "Service Parity Template"
    assert run_data["behavior_ids"] == ["bhv_001", "bhv_002"]
    # Metadata should include user-provided fields plus execution.total_steps
    assert run_data["metadata"]["priority"] == "P0"
    assert run_data["metadata"]["sprint"] == "1"
    assert run_data["metadata"]["execution"]["total_steps"] == 4
    assert run_data["current_step"] is None
    assert run_data["progress_pct"] == 0.0


@pytest.mark.asyncio
async def test_runs_list_tool_empty(mcp_server, actor):
    """Test runs.list tool returns empty list when no runs exist."""
    request = {
        "jsonrpc": "2.0",
        "id": "2",
        "method": "tools/call",
        "params": {
            "name": "runs.list",
            "arguments": {}
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(request))
    response = json.loads(response_str)

    # Validate JSON-RPC structure
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "2"
    assert "result" in response

    # Parse nested content
    result = response["result"]
    runs_data = json.loads(result["content"][0]["text"])

    assert "runs" in runs_data
    assert runs_data["runs"] == []


@pytest.mark.asyncio
async def test_runs_list_tool_with_runs(mcp_server, actor):
    """Test runs.list tool returns all runs."""
    # Create two runs
    create_request_1 = {
        "jsonrpc": "2.0",
        "id": "3a",
        "method": "tools/call",
        "params": {
            "name": "runs.create",
            "arguments": {
                "actor": actor,
                "workflow_id": "wf_001",
                "workflow_name": "Workflow A",
                "behavior_ids": [],
                "metadata": {},
            }
        }
    }
    await mcp_server.handle_request(json.dumps(create_request_1))

    create_request_2 = {
        "jsonrpc": "2.0",
        "id": "3b",
        "method": "tools/call",
        "params": {
            "name": "runs.create",
            "arguments": {
                "actor": actor,
                "workflow_id": "wf_002",
                "workflow_name": "Workflow B",
                "behavior_ids": [],
                "metadata": {},
            }
        }
    }
    await mcp_server.handle_request(json.dumps(create_request_2))

    # List all runs
    list_request = {
        "jsonrpc": "2.0",
        "id": "3",
        "method": "tools/call",
        "params": {
            "name": "runs.list",
            "arguments": {}
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(list_request))
    response = json.loads(response_str)

    result = response["result"]
    runs_data = json.loads(result["content"][0]["text"])

    assert "runs" in runs_data
    assert len(runs_data["runs"]) == 2
    assert runs_data["runs"][0]["workflow_name"] in ["Workflow A", "Workflow B"]


@pytest.mark.asyncio
async def test_runs_list_tool_with_status_filter(mcp_server, actor):
    """Test runs.list tool filters by status."""
    # Create run in PENDING status
    create_request = {
        "jsonrpc": "2.0",
        "id": "4a",
        "method": "tools/call",
        "params": {
            "name": "runs.create",
            "arguments": {
                "actor": actor,
                "workflow_id": "wf_001",
                "workflow_name": "Test Workflow",
                "behavior_ids": [],
                "metadata": {},
            }
        }
    }
    await mcp_server.handle_request(json.dumps(create_request))

    # List with PENDING filter
    list_request = {
        "jsonrpc": "2.0",
        "id": "4",
        "method": "tools/call",
        "params": {
            "name": "runs.list",
            "arguments": {"status": "PENDING"}
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(list_request))
    response = json.loads(response_str)

    result = response["result"]
    runs_data = json.loads(result["content"][0]["text"])

    assert len(runs_data["runs"]) >= 1
    assert all(r["status"] == "PENDING" for r in runs_data["runs"])


@pytest.mark.asyncio
async def test_runs_get_tool(mcp_server, actor):
    """Test runs.get tool retrieves specific run."""
    # Create a run
    create_request = {
        "jsonrpc": "2.0",
        "id": "5a",
        "method": "tools/call",
        "params": {
            "name": "runs.create",
            "arguments": {
                "actor": actor,
                "workflow_id": "wf_001",
                "workflow_name": "Test Workflow",
                "behavior_ids": ["bhv_001"],
                "metadata": {"test": "data"},
            }
        }
    }

    create_response_str = await mcp_server.handle_request(json.dumps(create_request))
    create_response = json.loads(create_response_str)
    create_result = json.loads(create_response["result"]["content"][0]["text"])
    run_id = create_result["run_id"]

    # Get the run
    get_request = {
        "jsonrpc": "2.0",
        "id": "5",
        "method": "tools/call",
        "params": {
            "name": "runs.get",
            "arguments": {"run_id": run_id}
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(get_request))
    response = json.loads(response_str)

    assert response["jsonrpc"] == "2.0"
    assert "result" in response

    result = response["result"]
    run_data = json.loads(result["content"][0]["text"])

    assert run_data["run_id"] == run_id
    assert run_data["workflow_id"] == "wf_001"
    assert run_data["workflow_name"] == "Test Workflow"
    assert run_data["behavior_ids"] == ["bhv_001"]
    assert run_data["metadata"] == {"test": "data"}


@pytest.mark.asyncio
async def test_runs_get_tool_not_found(mcp_server, actor):
    """Test runs.get tool returns error for non-existent run."""
    get_request = {
        "jsonrpc": "2.0",
        "id": "6",
        "method": "tools/call",
        "params": {
            "name": "runs.get",
            "arguments": {"run_id": "00000000-0000-0000-0000-000000000000"}
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(get_request))
    response = json.loads(response_str)

    assert response["jsonrpc"] == "2.0"
    assert "error" in response
    assert response["error"]["code"] == -32603  # INTERNAL_ERROR


@pytest.mark.asyncio
async def test_runs_update_progress_tool(mcp_server, actor):
    """Test runs.updateProgress tool updates run progress."""
    # Create a run
    create_request = {
        "jsonrpc": "2.0",
        "id": "7a",
        "method": "tools/call",
        "params": {
            "name": "runs.create",
            "arguments": {
                "actor": actor,
                "workflow_id": "wf_001",
                "workflow_name": "Test Workflow",
                "behavior_ids": [],
                "metadata": {},
            }
        }
    }

    create_response_str = await mcp_server.handle_request(json.dumps(create_request))
    create_response = json.loads(create_response_str)
    create_result = json.loads(create_response["result"]["content"][0]["text"])
    run_id = create_result["run_id"]

    # Update progress
    update_request = {
        "jsonrpc": "2.0",
        "id": "7",
        "method": "tools/call",
        "params": {
            "name": "runs.updateProgress",
            "arguments": {
                "run_id": run_id,
                "status": "RUNNING",
                "progress_pct": 50.0,
                "message": "Halfway through execution",
                "step_id": "step_2",
                "step_name": "Step 2 of 4",
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(update_request))
    response = json.loads(response_str)

    assert response["jsonrpc"] == "2.0"
    assert "result" in response

    result = response["result"]
    run_data = json.loads(result["content"][0]["text"])

    assert run_data["run_id"] == run_id
    assert run_data["status"] == "RUNNING"
    assert run_data["progress_pct"] == 50.0
    assert run_data["message"] == "Halfway through execution"
    assert run_data["current_step"] == "step_2"


@pytest.mark.asyncio
async def test_runs_update_progress_missing_run_id(mcp_server, actor):
    """Test runs.updateProgress tool returns error when run_id is missing."""
    update_request = {
        "jsonrpc": "2.0",
        "id": "8",
        "method": "tools/call",
        "params": {
            "name": "runs.updateProgress",
            "arguments": {
                "progress_pct": 25.0,
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(update_request))
    response = json.loads(response_str)

    assert response["jsonrpc"] == "2.0"
    assert "error" in response
    assert response["error"]["code"] == -32602  # INVALID_PARAMS
    assert "run_id" in response["error"]["message"]


@pytest.mark.asyncio
async def test_runs_complete_tool(mcp_server, actor):
    """Test runs.complete tool marks run as completed."""
    # Create a run
    create_request = {
        "jsonrpc": "2.0",
        "id": "9a",
        "method": "tools/call",
        "params": {
            "name": "runs.create",
            "arguments": {
                "actor": actor,
                "workflow_id": "wf_001",
                "workflow_name": "Test Workflow",
                "behavior_ids": [],
                "metadata": {},
            }
        }
    }

    create_response_str = await mcp_server.handle_request(json.dumps(create_request))
    create_response = json.loads(create_response_str)
    create_result = json.loads(create_response["result"]["content"][0]["text"])
    run_id = create_result["run_id"]

    # Complete the run
    complete_request = {
        "jsonrpc": "2.0",
        "id": "9",
        "method": "tools/call",
        "params": {
            "name": "runs.complete",
            "arguments": {
                "run_id": run_id,
                "status": "COMPLETED",
                "outputs": {"result": "success", "token_savings": 0.46},
                "message": "All steps completed successfully",
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(complete_request))
    response = json.loads(response_str)

    assert response["jsonrpc"] == "2.0"
    assert "result" in response

    result = response["result"]
    run_data = json.loads(result["content"][0]["text"])

    assert run_data["run_id"] == run_id
    assert run_data["status"] == "COMPLETED"
    assert run_data["outputs"] == {"result": "success", "token_savings": 0.46}
    assert run_data["message"] == "All steps completed successfully"
    assert run_data["progress_pct"] == 100.0


@pytest.mark.asyncio
async def test_runs_complete_tool_with_error(mcp_server, actor):
    """Test runs.complete tool marks run as failed with error."""
    # Create a run
    create_request = {
        "jsonrpc": "2.0",
        "id": "10a",
        "method": "tools/call",
        "params": {
            "name": "runs.create",
            "arguments": {
                "actor": actor,
                "workflow_id": "wf_001",
                "workflow_name": "Test Workflow",
                "behavior_ids": [],
                "metadata": {},
            }
        }
    }

    create_response_str = await mcp_server.handle_request(json.dumps(create_request))
    create_response = json.loads(create_response_str)
    create_result = json.loads(create_response["result"]["content"][0]["text"])
    run_id = create_result["run_id"]

    # Complete with failure
    complete_request = {
        "jsonrpc": "2.0",
        "id": "10",
        "method": "tools/call",
        "params": {
            "name": "runs.complete",
            "arguments": {
                "run_id": run_id,
                "status": "FAILED",
                "error": "Database connection timeout",
                "message": "Run failed during step 3",
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(complete_request))
    response = json.loads(response_str)

    assert response["jsonrpc"] == "2.0"
    assert "result" in response

    result = response["result"]
    run_data = json.loads(result["content"][0]["text"])

    assert run_data["run_id"] == run_id
    assert run_data["status"] == "FAILED"
    assert run_data["error"] == "Database connection timeout"
    assert run_data["message"] == "Run failed during step 3"


@pytest.mark.asyncio
async def test_runs_cancel_tool(mcp_server, actor):
    """Test runs.cancel tool cancels a running run."""
    # Create a run
    create_request = {
        "jsonrpc": "2.0",
        "id": "11a",
        "method": "tools/call",
        "params": {
            "name": "runs.create",
            "arguments": {
                "actor": actor,
                "workflow_id": "wf_001",
                "workflow_name": "Test Workflow",
                "behavior_ids": [],
                "metadata": {},
            }
        }
    }

    create_response_str = await mcp_server.handle_request(json.dumps(create_request))
    create_response = json.loads(create_response_str)
    create_result = json.loads(create_response["result"]["content"][0]["text"])
    run_id = create_result["run_id"]

    # Cancel the run
    cancel_request = {
        "jsonrpc": "2.0",
        "id": "11",
        "method": "tools/call",
        "params": {
            "name": "runs.cancel",
            "arguments": {
                "run_id": run_id,
                "reason": "User requested cancellation",
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(cancel_request))
    response = json.loads(response_str)

    assert response["jsonrpc"] == "2.0"
    assert "result" in response

    result = response["result"]
    run_data = json.loads(result["content"][0]["text"])

    assert run_data["run_id"] == run_id
    assert run_data["status"] == "CANCELLED"
    assert run_data["message"] == "User requested cancellation"


@pytest.mark.asyncio
async def test_runs_cancel_missing_run_id(mcp_server, actor):
    """Test runs.cancel tool returns error when run_id is missing."""
    cancel_request = {
        "jsonrpc": "2.0",
        "id": "12",
        "method": "tools/call",
        "params": {
            "name": "runs.cancel",
            "arguments": {
                "reason": "No run ID provided",
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(cancel_request))
    response = json.loads(response_str)

    assert response["jsonrpc"] == "2.0"
    assert "error" in response
    assert response["error"]["code"] == -32602  # INVALID_PARAMS
    assert "run_id" in response["error"]["message"]


@pytest.mark.asyncio
async def test_runs_workflow_lifecycle(mcp_server, actor):
    """Test complete run lifecycle: create → update → complete."""
    # 1. Create run
    create_request = {
        "jsonrpc": "2.0",
        "id": "13a",
        "method": "tools/call",
        "params": {
            "name": "runs.create",
            "arguments": {
                "actor": actor,
                "workflow_id": "wf_lifecycle",
                "workflow_name": "Lifecycle Test",
                "behavior_ids": ["bhv_001", "bhv_002"],
                "metadata": {"phase": "testing"},
                "total_steps": 3,
            }
        }
    }

    create_response_str = await mcp_server.handle_request(json.dumps(create_request))
    create_response = json.loads(create_response_str)
    create_result = json.loads(create_response["result"]["content"][0]["text"])
    run_id = create_result["run_id"]
    assert create_result["status"] == "PENDING"

    # 2. Update progress to 33%
    update1_request = {
        "jsonrpc": "2.0",
        "id": "13b",
        "method": "tools/call",
        "params": {
            "name": "runs.updateProgress",
            "arguments": {
                "run_id": run_id,
                "status": "RUNNING",
                "progress_pct": 33.0,
                "step_name": "Step 1 of 3",
            }
        }
    }
    await mcp_server.handle_request(json.dumps(update1_request))

    # 3. Update progress to 67%
    update2_request = {
        "jsonrpc": "2.0",
        "id": "13c",
        "method": "tools/call",
        "params": {
            "name": "runs.updateProgress",
            "arguments": {
                "run_id": run_id,
                "progress_pct": 67.0,
                "step_name": "Step 2 of 3",
            }
        }
    }
    await mcp_server.handle_request(json.dumps(update2_request))

    # 4. Complete run
    complete_request = {
        "jsonrpc": "2.0",
        "id": "13",
        "method": "tools/call",
        "params": {
            "name": "runs.complete",
            "arguments": {
                "run_id": run_id,
                "status": "COMPLETED",
                "outputs": {"behaviors_reused": 2, "token_savings_pct": 0.46},
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(complete_request))
    response = json.loads(response_str)
    result = json.loads(response["result"]["content"][0]["text"])

    assert result["run_id"] == run_id
    assert result["status"] == "COMPLETED"
    assert result["progress_pct"] == 100.0
    assert result["outputs"]["behaviors_reused"] == 2
    assert result["outputs"]["token_savings_pct"] == 0.46
