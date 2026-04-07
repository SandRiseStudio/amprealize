"""Test MCP server behavior tools integration.

Validates JSON-RPC 2.0 protocol compliance for all 9 BehaviorService MCP tools:
- behaviors.create
- behaviors.list
- behaviors.search
- behaviors.get
- behaviors.update
- behaviors.submit
- behaviors.approve
- behaviors.deprecate
- behaviors.deleteDraft

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
from amprealize.action_contracts import utc_now_iso
from amprealize.mcp_server import MCPServer


@pytest.fixture
def clean_behavior_db():
    """Clean behavior database before each test."""
    dsn = os.getenv("AMPREALIZE_BEHAVIOR_PG_DSN")
    if not dsn:
        pytest.skip("AMPREALIZE_BEHAVIOR_PG_DSN not set")
    from conftest import safe_truncate
    safe_truncate(dsn, ["behaviors", "behavior_versions"])


def _authenticated_server(server):
    """Authenticate an MCPServer session for testing."""
    server._session_context.user_id = "test-user"
    server._session_context.auth_method = "device_flow"
    server._session_context.is_admin = True
    server._session_context.granted_scopes = {"*"}
    server._session_context.expires_at = datetime.utcnow() + timedelta(hours=1)
    return server


@pytest.fixture
def mcp_server(clean_behavior_db):
    """Create MCP server instance for testing."""
    return _authenticated_server(MCPServer())


@pytest.fixture
def actor():
    """Standard test actor payload."""
    return {
        "id": "test-strategist",
        "role": "STRATEGIST",
        "surface": "MCP"
    }


@pytest.mark.asyncio
async def test_behaviors_create_tool(mcp_server, actor):
    """Test behaviors.create tool creates a behavior draft."""
    request = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/call",
        "params": {
            "name": "behaviors.create",
            "arguments": {
                "name": "behavior_test_mcp_creation",
                "description": "Test behavior created via MCP",
                "instruction": "When testing MCP tools, create comprehensive test cases covering happy path, validation, and error handling.",
                "role_focus": "STRATEGIST",
                "trigger_keywords": ["test", "mcp", "validation"],
                "tags": ["testing", "mcp"],
                "examples": [
                    {
                        "scenario": "Testing new MCP tool",
                        "application": "Create test suite with fixtures, happy path, edge cases, error scenarios"
                    }
                ],
                "metadata": {"source": "mcp_test"},
                "actor": actor
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

    # Validate behavior draft result structure (returns {"behavior": {...}, "versions": [...]})
    assert "behavior" in result
    assert "versions" in result

    behavior = result["behavior"]
    assert behavior["name"] == "behavior_test_mcp_creation"
    assert behavior["description"] == "Test behavior created via MCP"
    assert behavior["status"] == "DRAFT"
    assert "behavior_id" in behavior

    # Validate version details
    assert len(result["versions"]) == 1
    version = result["versions"][0]
    assert version["instruction"] == "When testing MCP tools, create comprehensive test cases covering happy path, validation, and error handling."
    assert version["role_focus"] == "STRATEGIST"
    assert version["status"] == "DRAFT"
    assert version["version"] == "1.0.0"  # Default first version
    assert version["behavior_id"] == behavior["behavior_id"]


@pytest.mark.asyncio
async def test_behaviors_list_tool(mcp_server, actor):
    """Test behaviors.list tool returns behavior summaries."""
    # Create a behavior first
    create_request = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/call",
        "params": {
            "name": "behaviors.create",
            "arguments": {
                "name": "behavior_test_list",
                "description": "Test behavior for list operation",
                "instruction": "List all behaviors matching criteria.",
                "role_focus": "TEACHER",
                "trigger_keywords": ["list", "filter"],
                "tags": ["testing", "list"],
                "actor": actor
            }
        }
    }
    await mcp_server.handle_request(json.dumps(create_request))

    # List behaviors with filter
    list_request = {
        "jsonrpc": "2.0",
        "id": "2",
        "method": "tools/call",
        "params": {
            "name": "behaviors.list",
            "arguments": {
                "status": "DRAFT",
                "tags": ["testing"]
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(list_request))
    response = json.loads(response_str)

    # Validate JSON-RPC structure
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "2"
    assert "result" in response

    # Parse nested content
    content_text = response["result"]["content"][0]["text"]
    result = json.loads(content_text)

    # Validate list result
    assert isinstance(result, list)
    assert len(result) >= 1

    # Find our created behavior (list returns {"behavior": {..}, "active_version": {..}})
    test_behavior = next((b for b in result if b["behavior"]["name"] == "behavior_test_list"), None)
    assert test_behavior is not None
    assert test_behavior["behavior"]["status"] == "DRAFT"
    assert "testing" in test_behavior["behavior"]["tags"]
    assert test_behavior["active_version"] is not None


@pytest.mark.asyncio
async def test_behaviors_search_tool(mcp_server, actor):
    """Test behaviors.search tool performs semantic/keyword search."""
    # Create a searchable behavior
    create_request = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/call",
        "params": {
            "name": "behaviors.create",
            "arguments": {
                "name": "behavior_searchable_test",
                "description": "Searchable behavior for testing MCP search",
                "instruction": "When searching behaviors, use semantic or keyword matching.",
                "role_focus": "STUDENT",
                "trigger_keywords": ["search", "semantic", "keyword"],
                "tags": ["search", "retrieval"],
                "actor": actor
            }
        }
    }
    await mcp_server.handle_request(json.dumps(create_request))

    # Search for behaviors
    search_request = {
        "jsonrpc": "2.0",
        "id": "2",
        "method": "tools/call",
        "params": {
            "name": "behaviors.search",
            "arguments": {
                "query": "searching behaviors",
                "tags": ["search"],
                "status": "DRAFT",
                "limit": 10
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(search_request))
    response = json.loads(response_str)

    # Validate JSON-RPC structure
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "2"
    assert "result" in response

    # Parse nested content
    content_text = response["result"]["content"][0]["text"]
    result = json.loads(content_text)

    # Validate search results (returns [{"behavior": {...}, "active_version": {...}, "score": 0.x}])
    assert isinstance(result, list)
    assert len(result) >= 1

    # Should find our behavior
    test_behavior = next((b for b in result if b["behavior"]["name"] == "behavior_searchable_test"), None)
    assert test_behavior is not None
    assert "score" in test_behavior  # Search results include relevance score
    assert test_behavior["behavior"]["status"] == "DRAFT"
    assert test_behavior["active_version"] is not None


@pytest.mark.asyncio
async def test_behaviors_get_tool(mcp_server, actor):
    """Test behaviors.get tool retrieves behavior detail."""
    # Create a behavior
    create_request = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/call",
        "params": {
            "name": "behaviors.create",
            "arguments": {
                "name": "behavior_test_get",
                "description": "Test behavior for get operation",
                "instruction": "Get detailed behavior information.",
                "role_focus": "STRATEGIST",
                "trigger_keywords": ["get", "retrieve"],
                "tags": ["testing"],
                "actor": actor
            }
        }
    }

    create_response_str = await mcp_server.handle_request(json.dumps(create_request))
    create_response = json.loads(create_response_str)
    content_text = create_response["result"]["content"][0]["text"]
    created_behavior = json.loads(content_text)
    behavior_id = created_behavior["behavior"]["behavior_id"]

    # Get the behavior
    get_request = {
        "jsonrpc": "2.0",
        "id": "2",
        "method": "tools/call",
        "params": {
            "name": "behaviors.get",
            "arguments": {
                "behavior_id": behavior_id
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(get_request))
    response = json.loads(response_str)

    # Validate JSON-RPC structure
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "2"
    assert "result" in response

    # Parse nested content
    content_text = response["result"]["content"][0]["text"]
    result = json.loads(content_text)

    # Validate detailed result (nested structure)
    assert "behavior" in result
    assert "versions" in result
    behavior = result["behavior"]
    assert behavior["behavior_id"] == behavior_id
    assert behavior["name"] == "behavior_test_get"


@pytest.mark.asyncio
async def test_behaviors_update_tool(mcp_server, actor):
    """Test behaviors.update tool modifies behavior draft."""
    # Create a behavior draft
    create_request = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/call",
        "params": {
            "name": "behaviors.create",
            "arguments": {
                "name": "behavior_test_update",
                "description": "Original description",
                "instruction": "Original instruction.",
                "role_focus": "TEACHER",
                "trigger_keywords": ["original"],
                "tags": ["testing"],
                "actor": actor
            }
        }
    }

    create_response_str = await mcp_server.handle_request(json.dumps(create_request))
    create_response = json.loads(create_response_str)
    content_text = create_response["result"]["content"][0]["text"]
    created_behavior = json.loads(content_text)
    behavior_id = created_behavior["behavior"]["behavior_id"]
    version = created_behavior["versions"][0]["version"]

    # Update the draft
    update_request = {
        "jsonrpc": "2.0",
        "id": "2",
        "method": "tools/call",
        "params": {
            "name": "behaviors.update",
            "arguments": {
                "behavior_id": behavior_id,
                "version": version,
                "description": "Updated description via MCP",
                "instruction": "Updated instruction via MCP tool.",
                "trigger_keywords": ["updated", "mcp"],
                "tags": ["testing", "updated"],
                "actor": actor
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(update_request))
    response = json.loads(response_str)

    # Validate JSON-RPC structure
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "2"
    assert "result" in response

    # Parse nested content
    content_text = response["result"]["content"][0]["text"]
    result = json.loads(content_text)

    # Validate updated fields (nested structure)
    assert "behavior" in result
    assert "versions" in result
    behavior = result["behavior"]
    assert behavior["behavior_id"] == behavior_id
    assert behavior["description"] == "Updated description via MCP"
    assert "updated" in behavior["tags"]


@pytest.mark.asyncio
async def test_behaviors_submit_tool(mcp_server, actor):
    """Test behaviors.submit tool transitions draft to PENDING_REVIEW."""
    # Create a behavior draft
    create_request = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/call",
        "params": {
            "name": "behaviors.create",
            "arguments": {
                "name": "behavior_test_submit",
                "description": "Test behavior for submit operation",
                "instruction": "Submit behavior for review.",
                "role_focus": "STRATEGIST",
                "trigger_keywords": ["submit", "review"],
                "tags": ["testing"],
                "actor": actor
            }
        }
    }

    create_response_str = await mcp_server.handle_request(json.dumps(create_request))
    create_response = json.loads(create_response_str)
    content_text = create_response["result"]["content"][0]["text"]
    created_behavior = json.loads(content_text)
    behavior_id = created_behavior["behavior"]["behavior_id"]
    version = created_behavior["versions"][0]["version"]

    # Submit for review
    submit_request = {
        "jsonrpc": "2.0",
        "id": "2",
        "method": "tools/call",
        "params": {
            "name": "behaviors.submit",
            "arguments": {
                "behavior_id": behavior_id,
                "version": version,
                "actor": actor
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(submit_request))
    response = json.loads(response_str)

    # Validate JSON-RPC structure
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "2"
    assert "result" in response

    # Parse nested content
    content_text = response["result"]["content"][0]["text"]
    result = json.loads(content_text)

    # Validate status transition (nested structure)
    assert "behavior" in result
    assert "versions" in result
    version_obj = result["versions"][0]
    assert version_obj["status"] == "IN_REVIEW"  # Actual status from service


@pytest.mark.asyncio
async def test_behaviors_approve_tool(mcp_server, actor):
    """Test behaviors.approve tool transitions to APPROVED."""
    # Create and submit a behavior
    create_request = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/call",
        "params": {
            "name": "behaviors.create",
            "arguments": {
                "name": "behavior_test_approve",
                "description": "Test behavior for approve operation",
                "instruction": "Approve behavior for production use.",
                "role_focus": "TEACHER",
                "trigger_keywords": ["approve", "production"],
                "tags": ["testing"],
                "actor": actor
            }
        }
    }
    create_response_str = await mcp_server.handle_request(json.dumps(create_request))
    create_response = json.loads(create_response_str)
    content_text = create_response["result"]["content"][0]["text"]
    created_behavior = json.loads(content_text)
    behavior_id = created_behavior["behavior"]["behavior_id"]
    version = created_behavior["versions"][0]["version"]

    # Submit for review
    submit_request = {
        "jsonrpc": "2.0",
        "id": "2",
        "method": "tools/call",
        "params": {
            "name": "behaviors.submit",
            "arguments": {
                "behavior_id": behavior_id,
                "version": version,
                "actor": actor
            }
        }
    }
    await mcp_server.handle_request(json.dumps(submit_request))

    # Approve the behavior
    approve_request = {
        "jsonrpc": "2.0",
        "id": "3",
        "method": "tools/call",
        "params": {
            "name": "behaviors.approve",
            "arguments": {
                "behavior_id": behavior_id,
                "version": version,
                "effective_from": utc_now_iso(),
                "actor": actor
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(approve_request))
    response = json.loads(response_str)

    # Validate JSON-RPC structure
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "3"
    assert "result" in response

    # Parse nested content
    content_text = response["result"]["content"][0]["text"]
    result = json.loads(content_text)

    # Validate status transition (nested structure)
    assert "behavior" in result
    assert "versions" in result
    version_obj = result["versions"][0]
    assert version_obj["status"] == "APPROVED"
    assert version_obj["effective_from"] is not None


@pytest.mark.asyncio
async def test_behaviors_deprecate_tool(mcp_server, actor):
    """Test behaviors.deprecate tool transitions to DEPRECATED."""
    # Create, submit, and approve a behavior
    create_request = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/call",
        "params": {
            "name": "behaviors.create",
            "arguments": {
                "name": "behavior_test_deprecate",
                "description": "Test behavior for deprecate operation",
                "instruction": "Deprecate outdated behavior.",
                "role_focus": "STUDENT",
                "trigger_keywords": ["deprecate", "outdated"],
                "tags": ["testing"],
                "actor": actor
            }
        }
    }
    create_response_str = await mcp_server.handle_request(json.dumps(create_request))
    create_response = json.loads(create_response_str)
    content_text = create_response["result"]["content"][0]["text"]
    created_behavior = json.loads(content_text)
    behavior_id = created_behavior["behavior"]["behavior_id"]
    version = created_behavior["versions"][0]["version"]

    # Submit and approve
    submit_request = {
        "jsonrpc": "2.0",
        "id": "2",
        "method": "tools/call",
        "params": {
            "name": "behaviors.submit",
            "arguments": {
                "behavior_id": behavior_id,
                "version": version,
                "actor": actor
            }
        }
    }
    await mcp_server.handle_request(json.dumps(submit_request))

    approve_request = {
        "jsonrpc": "2.0",
        "id": "3",
        "method": "tools/call",
        "params": {
            "name": "behaviors.approve",
            "arguments": {
                "behavior_id": behavior_id,
                "version": version,
                "effective_from": utc_now_iso(),
                "actor": actor
            }
        }
    }
    await mcp_server.handle_request(json.dumps(approve_request))

    # Deprecate the behavior
    deprecate_request = {
        "jsonrpc": "2.0",
        "id": "4",
        "method": "tools/call",
        "params": {
            "name": "behaviors.deprecate",
            "arguments": {
                "behavior_id": behavior_id,
                "version": version,
                "effective_to": utc_now_iso(),
                "actor": actor
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(deprecate_request))
    response = json.loads(response_str)

    # Validate JSON-RPC structure
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "4"
    assert "result" in response

    # Parse nested content
    content_text = response["result"]["content"][0]["text"]
    result = json.loads(content_text)

    # Validate status transition (nested structure)
    assert "behavior" in result
    assert "versions" in result
    version_obj = result["versions"][0]
    assert version_obj["status"] == "DEPRECATED"
    assert version_obj["effective_to"] is not None


@pytest.mark.asyncio
async def test_behaviors_deleteDraft_tool(mcp_server, actor):
    """Test behaviors.deleteDraft tool removes draft."""
    # Create a behavior draft
    create_request = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/call",
        "params": {
            "name": "behaviors.create",
            "arguments": {
                "name": "behavior_test_delete",
                "description": "Test behavior for delete operation",
                "instruction": "Delete unused draft.",
                "role_focus": "STRATEGIST",
                "trigger_keywords": ["delete", "draft"],
                "tags": ["testing"],
                "actor": actor
            }
        }
    }

    create_response_str = await mcp_server.handle_request(json.dumps(create_request))
    create_response = json.loads(create_response_str)
    content_text = create_response["result"]["content"][0]["text"]
    created_behavior = json.loads(content_text)
    behavior_id = created_behavior["behavior"]["behavior_id"]
    version = created_behavior["versions"][0]["version"]

    # Delete the draft
    delete_request = {
        "jsonrpc": "2.0",
        "id": "2",
        "method": "tools/call",
        "params": {
            "name": "behaviors.deleteDraft",
            "arguments": {
                "behavior_id": behavior_id,
                "version": version,
                "actor": actor
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(delete_request))
    response = json.loads(response_str)

    # Validate JSON-RPC structure
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "2"
    assert "result" in response

    # Parse nested content
    content_text = response["result"]["content"][0]["text"]
    result = json.loads(content_text)

    # Validate deletion success
    assert result["success"] is True
    assert behavior_id in result["message"]

    # Verify behavior is deleted (get should fail)
    get_request = {
        "jsonrpc": "2.0",
        "id": "3",
        "method": "tools/call",
        "params": {
            "name": "behaviors.get",
            "arguments": {
                "behavior_id": behavior_id
            }
        }
    }

    get_response_str = await mcp_server.handle_request(json.dumps(get_request))
    get_response = json.loads(get_response_str)

    # Should return error or empty result (behavior deleted)
    # Implementation may vary - either error response or null result
    assert "error" in get_response or get_response.get("result") is None


@pytest.mark.asyncio
async def test_behaviors_missing_required_params(mcp_server):
    """Test behavior tools validate required parameters."""
    # Test behaviors.search without query
    search_request = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/call",
        "params": {
            "name": "behaviors.search",
            "arguments": {}
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(search_request))
    response = json.loads(response_str)

    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "1"
    assert "error" in response
    assert "query" in response["error"]["message"].lower()

    # Test behaviors.get without behavior_id
    get_request = {
        "jsonrpc": "2.0",
        "id": "2",
        "method": "tools/call",
        "params": {
            "name": "behaviors.get",
            "arguments": {}
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(get_request))
    response = json.loads(response_str)

    assert "error" in response
    assert "behavior_id" in response["error"]["message"].lower()


@pytest.mark.asyncio
async def test_behaviors_unknown_tool(mcp_server):
    """Test unknown behavior tool returns METHOD_NOT_FOUND error."""
    request = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/call",
        "params": {
            "name": "behaviors.unknownOperation",
            "arguments": {}
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(request))
    response = json.loads(response_str)

    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "1"
    assert "error" in response
    assert response["error"]["code"] == -32601  # METHOD_NOT_FOUND
    assert "unknown" in response["error"]["message"].lower()
