"""
Test MCP workflow tools parity (workflow.template.*, workflow.run.*).

Following patterns from test_mcp_run_tools.py to ensure:
- JSON-RPC 2.0 protocol compliance
- MCP content format validation
- Full CRUD lifecycle coverage
- Error handling (missing params, not found)
"""

import json
import os
import pytest
from datetime import datetime, timedelta
from amprealize.mcp_server import MCPServer


@pytest.fixture(autouse=True)
def clean_workflow_db():
    """Clean workflow_templates and workflow_runs tables before each test."""
    dsn = os.environ.get("AMPREALIZE_WORKFLOW_PG_DSN")
    if not dsn:
        pytest.skip("AMPREALIZE_WORKFLOW_PG_DSN not set")

    from conftest import safe_truncate
    from amprealize.storage.redis_cache import get_cache

    safe_truncate(dsn, ["workflow_runs", "workflow_template_versions", "workflow_templates"])

    # Clear Redis cache for workflow service
    cache = get_cache()
    cache.invalidate_service("workflow")

    yield


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


@pytest.fixture
def actor():
    """Standard test actor payload."""
    return {
        "id": "test-user-123",
        "role": "DEVELOPER",
        "surface": "MCP_TEST"
    }


# ============================================================================
# Template Management Tests
# ============================================================================


@pytest.mark.asyncio
async def test_workflow_template_create_tool(clean_workflow_db, mcp_server, actor):
    """Test workflow.template.create tool creates template and returns valid structure."""
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "workflow.template.create",
            "arguments": {
                "name": "Behavior Review Workflow",
                "description": "Strategist reviews and approves behavior submissions",
                "role_focus": "STRATEGIST",
                "steps": [
                    {
                        "step_id": "review",
                        "name": "Review Submission",
                        "description": "Analyze behavior submission for quality",
                        "prompt_template": "Review this behavior:\n{{BEHAVIORS}}\n\nProvide feedback.",
                        "behavior_injection_point": "{{BEHAVIORS}}",
                        "required_behaviors": ["behavior_review_quality"],
                        "validation_rules": {"min_length": 50},
                        "metadata": {"priority": "P0"}
                    },
                    {
                        "step_id": "approve",
                        "name": "Approve or Reject",
                        "description": "Make final decision",
                        "prompt_template": "Decision: {{BEHAVIORS}}",
                        "required_behaviors": []
                    }
                ],
                "tags": ["review", "approval"],
                "metadata": {"sprint": "1"},
                "actor": actor
            }
        }
    }

    response = await mcp_server.handle_request(json.dumps(request))
    response_data = json.loads(response)

    # JSON-RPC validation
    assert response_data["jsonrpc"] == "2.0"
    assert response_data["id"] == 1
    assert "result" in response_data
    assert "error" not in response_data

    # MCP content format validation
    result = response_data["result"]
    assert "content" in result
    assert isinstance(result["content"], list)
    assert len(result["content"]) == 1
    assert result["content"][0]["type"] == "text"

    # Parse template data
    template_data = json.loads(result["content"][0]["text"])
    assert template_data["name"] == "Behavior Review Workflow"
    assert template_data["description"] == "Strategist reviews and approves behavior submissions"
    assert template_data["role_focus"] == "STRATEGIST"
    assert "template_id" in template_data
    assert "version" in template_data
    assert template_data["created_by"]["id"] == "test-user-123"
    assert len(template_data["steps"]) == 2
    assert template_data["steps"][0]["step_id"] == "review"
    assert template_data["steps"][0]["required_behaviors"] == ["behavior_review_quality"]
    assert template_data["tags"] == ["review", "approval"]
    assert template_data["metadata"]["sprint"] == "1"


@pytest.mark.asyncio
async def test_workflow_template_list_tool_empty(clean_workflow_db, mcp_server):
    """Test workflow.template.list returns empty list when no templates exist."""
    request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "workflow.template.list",
            "arguments": {}
        }
    }

    response = await mcp_server.handle_request(json.dumps(request))
    response_data = json.loads(response)

    assert response_data["jsonrpc"] == "2.0"
    assert "result" in response_data

    result = json.loads(response_data["result"]["content"][0]["text"])
    assert result["templates"] == []


@pytest.mark.asyncio
async def test_workflow_template_list_tool_with_templates(clean_workflow_db, mcp_server, actor):
    """Test workflow.template.list returns multiple templates."""
    # Create 2 templates
    for idx in range(2):
        create_request = {
            "jsonrpc": "2.0",
            "id": idx + 10,
            "method": "tools/call",
            "params": {
                "name": "workflow.template.create",
                "arguments": {
                    "name": f"Template {idx + 1}",
                    "description": f"Description {idx + 1}",
                    "role_focus": "TEACHER" if idx == 0 else "STUDENT",
                    "steps": [
                        {
                            "name": f"Step {idx + 1}",
                            "description": f"Step description {idx + 1}",
                            "prompt_template": "Prompt template"
                        }
                    ],
                    "actor": actor
                }
            }
        }
        await mcp_server.handle_request(json.dumps(create_request))

    # List all templates
    list_request = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "workflow.template.list",
            "arguments": {}
        }
    }

    response = await mcp_server.handle_request(json.dumps(list_request))
    response_data = json.loads(response)

    result = json.loads(response_data["result"]["content"][0]["text"])
    assert len(result["templates"]) == 2
    assert result["templates"][0]["name"] in ["Template 1", "Template 2"]
    assert result["templates"][1]["name"] in ["Template 1", "Template 2"]


@pytest.mark.asyncio
async def test_workflow_template_list_tool_with_role_filter(clean_workflow_db, mcp_server, actor):
    """Test workflow.template.list filters by role_focus."""
    # Create templates with different roles
    for role in ["STRATEGIST", "TEACHER", "STUDENT"]:
        create_request = {
            "jsonrpc": "2.0",
            "id": 20 + ord(role[0]),
            "method": "tools/call",
            "params": {
                "name": "workflow.template.create",
                "arguments": {
                    "name": f"{role} Template",
                    "description": f"Template for {role}",
                    "role_focus": role,
                    "steps": [{"name": "Step", "description": "Desc", "prompt_template": "Prompt"}],
                    "actor": actor
                }
            }
        }
        await mcp_server.handle_request(json.dumps(create_request))

    # Filter by TEACHER
    filter_request = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "workflow.template.list",
            "arguments": {"role_focus": "TEACHER"}
        }
    }

    response = await mcp_server.handle_request(json.dumps(filter_request))
    response_data = json.loads(response)

    result = json.loads(response_data["result"]["content"][0]["text"])
    assert len(result["templates"]) == 1
    assert result["templates"][0]["role_focus"] == "TEACHER"


@pytest.mark.asyncio
async def test_workflow_template_get_tool(clean_workflow_db, mcp_server, actor):
    """Test workflow.template.get retrieves specific template by ID."""
    # Create template
    create_request = {
        "jsonrpc": "2.0",
        "id": 30,
        "method": "tools/call",
        "params": {
            "name": "workflow.template.create",
            "arguments": {
                "name": "Get Test Template",
                "description": "Template to retrieve",
                "role_focus": "STRATEGIST",
                "steps": [{"name": "Step", "description": "Desc", "prompt_template": "Prompt"}],
                "actor": actor
            }
        }
    }

    create_response = await mcp_server.handle_request(json.dumps(create_request))
    create_data = json.loads(create_response)
    template_id = json.loads(create_data["result"]["content"][0]["text"])["template_id"]

    # Get template
    get_request = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "workflow.template.get",
            "arguments": {"template_id": template_id}
        }
    }

    response = await mcp_server.handle_request(json.dumps(get_request))
    response_data = json.loads(response)

    assert response_data["jsonrpc"] == "2.0"
    assert "result" in response_data

    template_data = json.loads(response_data["result"]["content"][0]["text"])
    assert template_data["template_id"] == template_id
    assert template_data["name"] == "Get Test Template"
    assert template_data["description"] == "Template to retrieve"


@pytest.mark.asyncio
async def test_workflow_template_get_tool_not_found(clean_workflow_db, mcp_server):
    """Test workflow.template.get returns error for non-existent template."""
    request = {
        "jsonrpc": "2.0",
        "id": 6,
        "method": "tools/call",
        "params": {
            "name": "workflow.template.get",
            "arguments": {"template_id": "non-existent-template-id"}
        }
    }

    response = await mcp_server.handle_request(json.dumps(request))
    response_data = json.loads(response)

    assert response_data["jsonrpc"] == "2.0"
    assert "error" in response_data
    assert response_data["error"]["code"] == -32603  # INTERNAL_ERROR
    assert "not found" in response_data["error"]["message"].lower()


@pytest.mark.asyncio
async def test_workflow_template_get_missing_template_id(mcp_server):
    """Test workflow.template.get validates required template_id parameter."""
    request = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {
            "name": "workflow.template.get",
            "arguments": {}
        }
    }

    response = await mcp_server.handle_request(json.dumps(request))
    response_data = json.loads(response)

    assert "error" in response_data
    assert response_data["error"]["code"] == -32602  # INVALID_PARAMS
    assert "template_id" in response_data["error"]["message"]


# ============================================================================
# Workflow Run Tests
# ============================================================================


@pytest.mark.asyncio
async def test_workflow_run_start_tool(clean_workflow_db, mcp_server, actor):
    """Test workflow.run.start creates workflow run and returns run details."""
    # Create template first
    create_template = {
        "jsonrpc": "2.0",
        "id": 40,
        "method": "tools/call",
        "params": {
            "name": "workflow.template.create",
            "arguments": {
                "name": "Execution Template",
                "description": "Template to execute",
                "role_focus": "STUDENT",
                "steps": [
                    {"name": "Execute", "description": "Execute step", "prompt_template": "{{BEHAVIORS}} Execute"}
                ],
                "actor": actor
            }
        }
    }

    create_response = await mcp_server.handle_request(json.dumps(create_template))
    template_id = json.loads(json.loads(create_response)["result"]["content"][0]["text"])["template_id"]

    # Start workflow run
    run_request = {
        "jsonrpc": "2.0",
        "id": 8,
        "method": "tools/call",
        "params": {
            "name": "workflow.run.start",
            "arguments": {
                "template_id": template_id,
                "actor": actor,
                "behavior_ids": ["behavior_1", "behavior_2"],
                "metadata": {"test_run": True}
            }
        }
    }

    response = await mcp_server.handle_request(json.dumps(run_request))
    response_data = json.loads(response)

    assert response_data["jsonrpc"] == "2.0"
    assert "result" in response_data

    run_data = json.loads(response_data["result"]["content"][0]["text"])
    assert "run_id" in run_data
    assert run_data["template_id"] == template_id
    assert run_data["template_name"] == "Execution Template"
    assert run_data["role_focus"] == "STUDENT"
    assert run_data["status"] == "PENDING"  # Workflow runs start as PENDING
    assert run_data["actor"]["id"] == "test-user-123"
    assert run_data["metadata"]["test_run"] is True


@pytest.mark.asyncio
async def test_workflow_run_status_tool(clean_workflow_db, mcp_server, actor):
    """Test workflow.run.status retrieves workflow run details."""
    # Create template and start run
    create_template = {
        "jsonrpc": "2.0",
        "id": 50,
        "method": "tools/call",
        "params": {
            "name": "workflow.template.create",
            "arguments": {
                "name": "Status Check Template",
                "description": "Template for status check",
                "role_focus": "TEACHER",
                "steps": [{"name": "Check", "description": "Check status", "prompt_template": "Status"}],
                "actor": actor
            }
        }
    }

    create_response = await mcp_server.handle_request(json.dumps(create_template))
    template_id = json.loads(json.loads(create_response)["result"]["content"][0]["text"])["template_id"]

    start_run = {
        "jsonrpc": "2.0",
        "id": 51,
        "method": "tools/call",
        "params": {
            "name": "workflow.run.start",
            "arguments": {"template_id": template_id, "actor": actor}
        }
    }

    start_response = await mcp_server.handle_request(json.dumps(start_run))
    run_id = json.loads(json.loads(start_response)["result"]["content"][0]["text"])["run_id"]

    # Get run status
    status_request = {
        "jsonrpc": "2.0",
        "id": 9,
        "method": "tools/call",
        "params": {
            "name": "workflow.run.status",
            "arguments": {"run_id": run_id}
        }
    }

    response = await mcp_server.handle_request(json.dumps(status_request))
    response_data = json.loads(response)

    assert response_data["jsonrpc"] == "2.0"
    assert "result" in response_data

    run_data = json.loads(response_data["result"]["content"][0]["text"])
    assert run_data["run_id"] == run_id
    assert run_data["template_name"] == "Status Check Template"
    assert run_data["status"] == "PENDING"  # Workflow runs start as PENDING


@pytest.mark.asyncio
async def test_workflow_run_status_not_found(clean_workflow_db, mcp_server):
    """Test workflow.run.status returns error for non-existent run."""
    request = {
        "jsonrpc": "2.0",
        "id": 10,
        "method": "tools/call",
        "params": {
            "name": "workflow.run.status",
            "arguments": {"run_id": "non-existent-run-id"}
        }
    }

    response = await mcp_server.handle_request(json.dumps(request))
    response_data = json.loads(response)

    assert "error" in response_data
    assert response_data["error"]["code"] == -32603  # INTERNAL_ERROR
    assert "not found" in response_data["error"]["message"].lower()


@pytest.mark.asyncio
async def test_workflow_run_status_missing_run_id(mcp_server):
    """Test workflow.run.status validates required run_id parameter."""
    request = {
        "jsonrpc": "2.0",
        "id": 11,
        "method": "tools/call",
        "params": {
            "name": "workflow.run.status",
            "arguments": {}
        }
    }

    response = await mcp_server.handle_request(json.dumps(request))
    response_data = json.loads(response)

    assert "error" in response_data
    assert response_data["error"]["code"] == -32602  # INVALID_PARAMS
    assert "run_id" in response_data["error"]["message"]


# ============================================================================
# Workflow Lifecycle Test
# ============================================================================


@pytest.mark.asyncio
async def test_workflow_full_lifecycle(clean_workflow_db, mcp_server, actor):
    """Test complete workflow lifecycle: create template → list → get → start run → check status."""
    # 1. Create template
    create_request = {
        "jsonrpc": "2.0",
        "id": 60,
        "method": "tools/call",
        "params": {
            "name": "workflow.template.create",
            "arguments": {
                "name": "Lifecycle Test Workflow",
                "description": "End-to-end workflow test",
                "role_focus": "MULTI_ROLE",
                "steps": [
                    {"name": "Plan", "description": "Planning step", "prompt_template": "Plan: {{BEHAVIORS}}"},
                    {"name": "Execute", "description": "Execution step", "prompt_template": "Execute: {{BEHAVIORS}}"},
                    {"name": "Review", "description": "Review step", "prompt_template": "Review: {{BEHAVIORS}}"}
                ],
                "tags": ["test", "lifecycle"],
                "actor": actor
            }
        }
    }

    create_response = await mcp_server.handle_request(json.dumps(create_request))
    template_id = json.loads(json.loads(create_response)["result"]["content"][0]["text"])["template_id"]

    # 2. List templates (should find our template)
    list_request = {
        "jsonrpc": "2.0",
        "id": 61,
        "method": "tools/call",
        "params": {"name": "workflow.template.list", "arguments": {}}
    }

    list_response = await mcp_server.handle_request(json.dumps(list_request))
    templates = json.loads(json.loads(list_response)["result"]["content"][0]["text"])["templates"]
    assert len(templates) >= 1
    assert any(t["template_id"] == template_id for t in templates)

    # 3. Get specific template
    get_request = {
        "jsonrpc": "2.0",
        "id": 62,
        "method": "tools/call",
        "params": {"name": "workflow.template.get", "arguments": {"template_id": template_id}}
    }

    get_response = await mcp_server.handle_request(json.dumps(get_request))
    template_data = json.loads(json.loads(get_response)["result"]["content"][0]["text"])
    assert template_data["name"] == "Lifecycle Test Workflow"
    assert len(template_data["steps"]) == 3

    # 4. Start workflow run
    start_request = {
        "jsonrpc": "2.0",
        "id": 63,
        "method": "tools/call",
        "params": {
            "name": "workflow.run.start",
            "arguments": {
                "template_id": template_id,
                "actor": actor,
                "behavior_ids": ["behavior_lifecycle_test"],
                "metadata": {"lifecycle_test": True}
            }
        }
    }

    start_response = await mcp_server.handle_request(json.dumps(start_request))
    run_id = json.loads(json.loads(start_response)["result"]["content"][0]["text"])["run_id"]

    # 5. Check run status
    status_request = {
        "jsonrpc": "2.0",
        "id": 64,
        "method": "tools/call",
        "params": {"name": "workflow.run.status", "arguments": {"run_id": run_id}}
    }

    status_response = await mcp_server.handle_request(json.dumps(status_request))
    run_data = json.loads(json.loads(status_response)["result"]["content"][0]["text"])

    assert run_data["run_id"] == run_id
    assert run_data["template_id"] == template_id
    assert run_data["template_name"] == "Lifecycle Test Workflow"
    assert run_data["status"] == "PENDING"  # Workflow runs start as PENDING
    assert run_data["metadata"]["lifecycle_test"] is True
