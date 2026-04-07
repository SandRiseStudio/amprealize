"""Test MCP server compliance tools integration.

Validates JSON-RPC 2.0 protocol compliance for all 5 ComplianceService MCP tools:
- compliance/create-checklist
- compliance/list-checklists
- compliance/get-checklist
- compliance/record-step
- compliance/validate-compliance

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
def clean_compliance_db():
    """Clean compliance database before each test."""
    dsn = os.getenv("AMPREALIZE_COMPLIANCE_PG_DSN")
    if not dsn:
        pytest.skip("AMPREALIZE_COMPLIANCE_PG_DSN not set")
    from conftest import safe_truncate
    safe_truncate(dsn, ["checklists"])


def _authenticated_server(server):
    """Authenticate an MCPServer session for testing."""
    server._session_context.user_id = "test-user"
    server._session_context.auth_method = "device_flow"
    server._session_context.is_admin = True
    server._session_context.granted_scopes = {"*"}
    server._session_context.expires_at = datetime.utcnow() + timedelta(hours=1)
    return server


@pytest.fixture
def mcp_server(clean_compliance_db):
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
async def test_compliance_create_checklist_tool(mcp_server, actor):
    """Test compliance/create-checklist tool creates a checklist."""
    request = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/call",
        "params": {
            "name": "compliance/create-checklist",
            "arguments": {
                "title": "Sprint 1 P0 Compliance",
                "description": "Validate all P0 services implement required compliance checks",
                "template_id": "sprint_p0_template",
                "milestone": "sprint_1_p0",
                "compliance_category": ["security", "audit", "parity"],
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
    checklist_data = json.loads(result["content"][0]["text"])

    # Validate checklist structure
    assert "checklist_id" in checklist_data
    assert checklist_data["title"] == "Sprint 1 P0 Compliance"
    assert checklist_data["description"] == "Validate all P0 services implement required compliance checks"
    assert checklist_data["template_id"] == "sprint_p0_template"
    assert checklist_data["milestone"] == "sprint_1_p0"
    assert checklist_data["compliance_category"] == ["security", "audit", "parity"]
    assert checklist_data["steps"] == []
    assert checklist_data["coverage_score"] == 0.0
    assert checklist_data["created_at"] is not None
    assert checklist_data["completed_at"] is None

    # Store checklist_id for subsequent tests
    return checklist_data["checklist_id"]


@pytest.mark.asyncio
async def test_compliance_list_checklists_tool(mcp_server, actor):
    """Test compliance/list-checklists tool returns empty list initially."""
    request = {
        "jsonrpc": "2.0",
        "id": "2",
        "method": "tools/call",
        "params": {
            "name": "compliance/list-checklists",
            "arguments": {}
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(request))
    response = json.loads(response_str)

    # Validate JSON-RPC structure
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "2"
    assert "result" in response
    assert "error" not in response

    # Validate MCP content format
    result = response["result"]
    assert "content" in result
    assert isinstance(result["content"], list)

    # Parse nested JSON payload
    list_data = json.loads(result["content"][0]["text"])

    # Validate list structure
    assert "checklists" in list_data
    assert isinstance(list_data["checklists"], list)


@pytest.mark.asyncio
async def test_compliance_get_checklist_tool(mcp_server, actor):
    """Test compliance/get-checklist tool retrieves a checklist."""
    # First create a checklist
    create_request = {
        "jsonrpc": "2.0",
        "id": "3a",
        "method": "tools/call",
        "params": {
            "name": "compliance/create-checklist",
            "arguments": {
                "title": "Get Test Checklist",
                "description": "Test get operation",
                "template_id": "test_template",
                "milestone": "test_milestone",
                "compliance_category": ["testing"],
            }
        }
    }

    create_response_str = await mcp_server.handle_request(json.dumps(create_request))
    create_response = json.loads(create_response_str)
    checklist_data = json.loads(create_response["result"]["content"][0]["text"])
    checklist_id = checklist_data["checklist_id"]

    # Now get the checklist
    get_request = {
        "jsonrpc": "2.0",
        "id": "3b",
        "method": "tools/call",
        "params": {
            "name": "compliance/get-checklist",
            "arguments": {
                "checklist_id": checklist_id
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(get_request))
    response = json.loads(response_str)

    # Validate JSON-RPC structure
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "3b"
    assert "result" in response
    assert "error" not in response

    # Parse nested JSON payload
    retrieved_data = json.loads(response["result"]["content"][0]["text"])

    # Validate retrieved checklist matches created one
    assert retrieved_data["checklist_id"] == checklist_id
    assert retrieved_data["title"] == "Get Test Checklist"
    assert retrieved_data["description"] == "Test get operation"
    assert retrieved_data["steps"] == []


@pytest.mark.asyncio
async def test_compliance_record_step_tool(mcp_server, actor):
    """Test compliance/record-step tool records a step and updates coverage."""
    # First create a checklist
    create_request = {
        "jsonrpc": "2.0",
        "id": "4a",
        "method": "tools/call",
        "params": {
            "name": "compliance/create-checklist",
            "arguments": {
                "title": "Step Test Checklist",
                "description": "Test step recording",
                "template_id": "test_template",
                "milestone": "test_milestone",
                "compliance_category": ["testing"],
            }
        }
    }

    create_response_str = await mcp_server.handle_request(json.dumps(create_request))
    create_response = json.loads(create_response_str)
    checklist_data = json.loads(create_response["result"]["content"][0]["text"])
    checklist_id = checklist_data["checklist_id"]

    # Record a step
    step_request = {
        "jsonrpc": "2.0",
        "id": "4b",
        "method": "tools/call",
        "params": {
            "name": "compliance/record-step",
            "arguments": {
                "checklist_id": checklist_id,
                "title": "PostgreSQL Migration Verified",
                "status": "COMPLETED",
                "evidence": {"migration_file": "006_create_compliance_service.sql", "test_result": "PASS"},
                "behaviors_cited": ["behavior_align_storage_layers"],
                "related_run_id": "test-run-001"
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(step_request))
    response = json.loads(response_str)

    # Validate JSON-RPC structure
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "4b"
    assert "result" in response
    assert "error" not in response

    # Parse nested JSON payload
    step_data = json.loads(response["result"]["content"][0]["text"])

    # Validate step structure
    assert "step_id" in step_data
    assert step_data["checklist_id"] == checklist_id
    assert step_data["title"] == "PostgreSQL Migration Verified"
    assert step_data["status"] == "COMPLETED"
    assert step_data["evidence"]["migration_file"] == "006_create_compliance_service.sql"
    assert "behavior_align_storage_layers" in step_data["behaviors_cited"]
    assert step_data["related_run_id"] == "test-run-001"


@pytest.mark.asyncio
async def test_compliance_validate_tool(mcp_server, actor):
    """Test compliance/validate-compliance tool validates a checklist."""
    # First create a checklist
    create_request = {
        "jsonrpc": "2.0",
        "id": "5a",
        "method": "tools/call",
        "params": {
            "name": "compliance/create-checklist",
            "arguments": {
                "title": "Validation Test Checklist",
                "description": "Test validation logic",
                "template_id": "test_template",
                "milestone": "test_milestone",
                "compliance_category": ["testing"],
            }
        }
    }

    create_response_str = await mcp_server.handle_request(json.dumps(create_request))
    create_response = json.loads(create_response_str)
    checklist_data = json.loads(create_response["result"]["content"][0]["text"])
    checklist_id = checklist_data["checklist_id"]

    # Validate the checklist (with no steps - should be invalid)
    validate_request = {
        "jsonrpc": "2.0",
        "id": "5b",
        "method": "tools/call",
        "params": {
            "name": "compliance/validate-compliance",
            "arguments": {
                "checklist_id": checklist_id
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(validate_request))
    response = json.loads(response_str)

    # Validate JSON-RPC structure
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "5b"
    assert "result" in response
    assert "error" not in response

    # Parse nested JSON payload
    validation_data = json.loads(response["result"]["content"][0]["text"])

    # Validate validation structure
    assert validation_data["checklist_id"] == checklist_id
    assert "valid" in validation_data
    assert validation_data["coverage_score"] == 0.0
    assert "missing_steps" in validation_data
    assert "failed_steps" in validation_data
    assert "warnings" in validation_data


@pytest.mark.asyncio
async def test_compliance_list_by_milestone(mcp_server, actor):
    """Test compliance/list-checklists filters by milestone."""
    # Create checklists with different milestones
    for i, milestone in enumerate(["sprint_1", "sprint_2", "sprint_1"]):
        create_request = {
            "jsonrpc": "2.0",
            "id": f"6a{i}",
            "method": "tools/call",
            "params": {
                "name": "compliance/create-checklist",
                "arguments": {
                    "title": f"Checklist {i}",
                    "description": f"Test {milestone}",
                    "milestone": milestone,
                    "compliance_category": ["testing"],
                }
            }
        }
        await mcp_server.handle_request(json.dumps(create_request))

    # List only sprint_1 checklists
    list_request = {
        "jsonrpc": "2.0",
        "id": "6b",
        "method": "tools/call",
        "params": {
            "name": "compliance/list-checklists",
            "arguments": {
                "milestone": "sprint_1"
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(list_request))
    response = json.loads(response_str)
    list_data = json.loads(response["result"]["content"][0]["text"])

    # Should have 2 sprint_1 checklists
    assert len(list_data["checklists"]) == 2
    for checklist in list_data["checklists"]:
        assert checklist["milestone"] == "sprint_1"


@pytest.mark.asyncio
async def test_compliance_list_by_category(mcp_server, actor):
    """Test compliance/list-checklists filters by category using JSONB overlap."""
    # Create checklists with different categories
    create_request_1 = {
        "jsonrpc": "2.0",
        "id": "7a",
        "method": "tools/call",
        "params": {
            "name": "compliance/create-checklist",
            "arguments": {
                "title": "Security Checklist",
                "description": "Security compliance",
                "compliance_category": ["security", "audit"],
            }
        }
    }
    await mcp_server.handle_request(json.dumps(create_request_1))

    create_request_2 = {
        "jsonrpc": "2.0",
        "id": "7b",
        "method": "tools/call",
        "params": {
            "name": "compliance/create-checklist",
            "arguments": {
                "title": "Parity Checklist",
                "description": "Parity compliance",
                "compliance_category": ["parity"],
            }
        }
    }
    await mcp_server.handle_request(json.dumps(create_request_2))

    # List security checklists
    list_request = {
        "jsonrpc": "2.0",
        "id": "7c",
        "method": "tools/call",
        "params": {
            "name": "compliance/list-checklists",
            "arguments": {
                "compliance_category": ["security"]
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(list_request))
    response = json.loads(response_str)
    list_data = json.loads(response["result"]["content"][0]["text"])

    # Should have 1 checklist with security category
    assert len(list_data["checklists"]) == 1
    assert "security" in list_data["checklists"][0]["compliance_category"]


@pytest.mark.asyncio
async def test_compliance_list_by_status(mcp_server, actor):
    """Test compliance/list-checklists filters by completion status."""
    # Create a checklist with 2 steps (one complete, one pending)
    create_request = {
        "jsonrpc": "2.0",
        "id": "8a",
        "method": "tools/call",
        "params": {
            "name": "compliance/create-checklist",
            "arguments": {
                "title": "Status Test Checklist",
                "description": "Test status filtering",
                "compliance_category": ["testing"],
            }
        }
    }

    create_response_str = await mcp_server.handle_request(json.dumps(create_request))
    create_response = json.loads(create_response_str)
    checklist_data = json.loads(create_response["result"]["content"][0]["text"])
    checklist_id = checklist_data["checklist_id"]

    # Record a PENDING step first
    step_request_0 = {
        "jsonrpc": "2.0",
        "id": "8b0",
        "method": "tools/call",
        "params": {
            "name": "compliance/record-step",
            "arguments": {
                "checklist_id": checklist_id,
                "title": "Step 0 - Pending",
                "status": "PENDING",
            }
        }
    }
    await mcp_server.handle_request(json.dumps(step_request_0))

    # Record a completed step
    step_request_1 = {
        "jsonrpc": "2.0",
        "id": "8b",
        "method": "tools/call",
        "params": {
            "name": "compliance/record-step",
            "arguments": {
                "checklist_id": checklist_id,
                "title": "Step 1",
                "status": "COMPLETED",
            }
        }
    }
    await mcp_server.handle_request(json.dumps(step_request_1))

    # List ACTIVE checklists (incomplete - has PENDING step)
    list_request = {
        "jsonrpc": "2.0",
        "id": "8c",
        "method": "tools/call",
        "params": {
            "name": "compliance/list-checklists",
            "arguments": {
                "status_filter": "ACTIVE"
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(list_request))
    response = json.loads(response_str)
    list_data = json.loads(response["result"]["content"][0]["text"])

    # Checklist should still be active (has PENDING step, not all terminal)
    checklist_ids = [c["checklist_id"] for c in list_data["checklists"]]
    assert checklist_id in checklist_ids


@pytest.mark.asyncio
async def test_compliance_coverage_calculation(mcp_server, actor):
    """Test coverage score updates correctly as steps are recorded."""
    # Create a checklist
    create_request = {
        "jsonrpc": "2.0",
        "id": "9a",
        "method": "tools/call",
        "params": {
            "name": "compliance/create-checklist",
            "arguments": {
                "title": "Coverage Test Checklist",
                "description": "Test coverage calculation",
                "compliance_category": ["testing"],
            }
        }
    }

    create_response_str = await mcp_server.handle_request(json.dumps(create_request))
    create_response = json.loads(create_response_str)
    checklist_data = json.loads(create_response["result"]["content"][0]["text"])
    checklist_id = checklist_data["checklist_id"]

    # Record 3 steps: 2 completed, 1 pending
    for i, status in enumerate(["COMPLETED", "COMPLETED", "PENDING"]):
        step_request = {
            "jsonrpc": "2.0",
            "id": f"9b{i}",
            "method": "tools/call",
            "params": {
                "name": "compliance/record-step",
                "arguments": {
                    "checklist_id": checklist_id,
                    "title": f"Step {i+1}",
                    "status": status,
                }
            }
        }
        await mcp_server.handle_request(json.dumps(step_request))

    # Get checklist and verify coverage = 2/3 ≈ 0.67
    get_request = {
        "jsonrpc": "2.0",
        "id": "9c",
        "method": "tools/call",
        "params": {
            "name": "compliance/get-checklist",
            "arguments": {
                "checklist_id": checklist_id
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(get_request))
    response = json.loads(response_str)
    checklist_data = json.loads(response["result"]["content"][0]["text"])

    # Coverage should be ~0.67 (2 of 3 steps terminal)
    assert abs(checklist_data["coverage_score"] - 0.67) < 0.01
    assert checklist_data["completed_at"] is None  # Not all terminal


@pytest.mark.asyncio
async def test_compliance_completion_detection(mcp_server, actor):
    """Test completed_at timestamp set when all steps terminal."""
    # Create a checklist
    create_request = {
        "jsonrpc": "2.0",
        "id": "10a",
        "method": "tools/call",
        "params": {
            "name": "compliance/create-checklist",
            "arguments": {
                "title": "Completion Test Checklist",
                "description": "Test completion detection",
                "compliance_category": ["testing"],
            }
        }
    }

    create_response_str = await mcp_server.handle_request(json.dumps(create_request))
    create_response = json.loads(create_response_str)
    checklist_data = json.loads(create_response["result"]["content"][0]["text"])
    checklist_id = checklist_data["checklist_id"]

    # Record 2 terminal steps (1 COMPLETED, 1 SKIPPED)
    for i, status in enumerate(["COMPLETED", "SKIPPED"]):
        step_request = {
            "jsonrpc": "2.0",
            "id": f"10b{i}",
            "method": "tools/call",
            "params": {
                "name": "compliance/record-step",
                "arguments": {
                    "checklist_id": checklist_id,
                    "title": f"Step {i+1}",
                    "status": status,
                }
            }
        }
        await mcp_server.handle_request(json.dumps(step_request))

    # Get checklist and verify completed_at is set
    get_request = {
        "jsonrpc": "2.0",
        "id": "10c",
        "method": "tools/call",
        "params": {
            "name": "compliance/get-checklist",
            "arguments": {
                "checklist_id": checklist_id
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(get_request))
    response = json.loads(response_str)
    checklist_data = json.loads(response["result"]["content"][0]["text"])

    # Checklist should be complete (all steps terminal)
    assert checklist_data["coverage_score"] == 1.0
    assert checklist_data["completed_at"] is not None


@pytest.mark.asyncio
async def test_compliance_missing_required_params(mcp_server, actor):
    """Test error handling for missing required parameters."""
    request = {
        "jsonrpc": "2.0",
        "id": "11",
        "method": "tools/call",
        "params": {
            "name": "compliance/create-checklist",
            "arguments": {
                # Missing required "title" field
                "description": "Missing title"
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(request))
    response = json.loads(response_str)

    # Should return error response
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "11"
    assert "error" in response
    assert "result" not in response


@pytest.mark.asyncio
async def test_compliance_unknown_tool(mcp_server, actor):
    """Test error handling for unknown tool name."""
    request = {
        "jsonrpc": "2.0",
        "id": "12",
        "method": "tools/call",
        "params": {
            "name": "compliance/unknown-tool",
            "arguments": {}
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(request))
    response = json.loads(response_str)

    # Should return error response
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "12"
    assert "error" in response
    assert "Unknown compliance tool" in response["error"]["message"]


@pytest.mark.asyncio
async def test_compliance_checklist_not_found(mcp_server, actor):
    """Test error handling for non-existent checklist."""
    request = {
        "jsonrpc": "2.0",
        "id": "13",
        "method": "tools/call",
        "params": {
            "name": "compliance/get-checklist",
            "arguments": {
                "checklist_id": "non-existent-id"
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(request))
    response = json.loads(response_str)

    # Should return error response
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "13"
    assert "error" in response
    assert "result" not in response
