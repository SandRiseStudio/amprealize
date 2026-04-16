"""Test MCP server action tools integration."""

import json
import pytest
from datetime import datetime, timedelta
from amprealize.mcp_server import MCPServer


@pytest.fixture
def mcp_server():
    """Create MCP server instance for testing with authenticated session."""
    server = MCPServer()
    # Authenticate session to bypass auth checks for tool tests
    server._session_context.user_id = "test-user"
    server._session_context.auth_method = "device_flow"
    server._session_context.is_admin = True
    server._session_context.granted_scopes = {"*"}
    server._session_context.expires_at = datetime.utcnow() + timedelta(hours=1)
    # Reset distributed rate limiter so prior tests' Redis state doesn't bleed through
    drl = getattr(server, "_distributed_rate_limiter", None)
    if drl is not None:
        drl._memory_counters.clear()
        drl._redis_client = None
        drl._use_redis = False
    return server


@pytest.mark.asyncio
async def test_actions_create_tool(mcp_server):
    """Test actions.create tool call."""
    request = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/call",
        "params": {
            "name": "actions.create",
            "arguments": {
                "artifact_path": "test/file.py",
                "summary": "Test action",
                "behaviors_cited": ["behavior_test"],
                "metadata": {"test": "data"},
                "actor": {
                    "id": "test-actor",
                    "role": "STRATEGIST",
                    "surface": "MCP"
                }
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(request))
    response = json.loads(response_str)

    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "1"
    assert "result" in response
    assert "content" in response["result"]

    # Parse the nested result
    content_text = response["result"]["content"][0]["text"]
    result = json.loads(content_text)

    assert result["artifact_path"] == "test/file.py"
    assert result["summary"] == "Test action"
    assert result["behaviors_cited"] == ["behavior_test"]
    assert "action_id" in result


@pytest.mark.asyncio
async def test_actions_list_tool(mcp_server):
    """Test actions.list tool call."""
    # First create an action
    create_request = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/call",
        "params": {
            "name": "actions.create",
            "arguments": {
                "artifact_path": "test/file.py",
                "summary": "Test action",
                "behaviors_cited": ["behavior_test"],
                "actor": {
                    "id": "test-actor",
                    "role": "STRATEGIST",
                    "surface": "MCP"
                }
            }
        }
    }
    await mcp_server.handle_request(json.dumps(create_request))

    # Now list actions
    list_request = {
        "jsonrpc": "2.0",
        "id": "2",
        "method": "tools/call",
        "params": {
            "name": "actions.list",
            "arguments": {}
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(list_request))
    response = json.loads(response_str)

    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "2"
    assert "result" in response

    content_text = response["result"]["content"][0]["text"]
    result = json.loads(content_text)

    assert isinstance(result, list)
    assert len(result) >= 1

    # Find the action we just created
    created_action = next((a for a in result if a["artifact_path"] == "test/file.py"), None)
    assert created_action is not None, "Created action not found in list"
    assert created_action["summary"] == "Test action"


@pytest.mark.asyncio
async def test_actions_get_tool(mcp_server):
    """Test actions.get tool call."""
    # First create an action
    create_request = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/call",
        "params": {
            "name": "actions.create",
            "arguments": {
                "artifact_path": "test/file.py",
                "summary": "Test action",
                "behaviors_cited": ["behavior_test"],
                "actor": {
                    "id": "test-actor",
                    "role": "STRATEGIST",
                    "surface": "MCP"
                }
            }
        }
    }

    create_response_str = await mcp_server.handle_request(json.dumps(create_request))
    create_response = json.loads(create_response_str)
    content_text = create_response["result"]["content"][0]["text"]
    created_action = json.loads(content_text)
    action_id = created_action["action_id"]

    # Now get the action
    get_request = {
        "jsonrpc": "2.0",
        "id": "2",
        "method": "tools/call",
        "params": {
            "name": "actions.get",
            "arguments": {
                "action_id": action_id
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(get_request))
    response = json.loads(response_str)

    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "2"
    assert "result" in response

    content_text = response["result"]["content"][0]["text"]
    result = json.loads(content_text)

    assert result["action_id"] == action_id
    assert result["artifact_path"] == "test/file.py"


@pytest.mark.asyncio
async def test_actions_replay_tool(mcp_server):
    """Test actions.replay tool call."""
    # First create an action
    create_request = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/call",
        "params": {
            "name": "actions.create",
            "arguments": {
                "artifact_path": "test/file.py",
                "summary": "Test action",
                "behaviors_cited": ["behavior_test"],
                "actor": {
                    "id": "test-actor",
                    "role": "STRATEGIST",
                    "surface": "MCP"
                }
            }
        }
    }

    create_response_str = await mcp_server.handle_request(json.dumps(create_request))
    create_response = json.loads(create_response_str)
    content_text = create_response["result"]["content"][0]["text"]
    created_action = json.loads(content_text)
    action_id = created_action["action_id"]

    # Now replay the action
    replay_request = {
        "jsonrpc": "2.0",
        "id": "2",
        "method": "tools/call",
        "params": {
            "name": "actions.replay",
            "arguments": {
                "action_ids": [action_id],
                "strategy": "SEQUENTIAL",
                "options": {
                    "skip_existing": False,
                    "dry_run": True
                },
                "actor": {
                    "id": "test-actor",
                    "role": "STRATEGIST",
                    "surface": "MCP"
                }
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(replay_request))
    response = json.loads(response_str)

    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "2"
    assert "result" in response

    content_text = response["result"]["content"][0]["text"]
    result = json.loads(content_text)

    assert "replay_id" in result
    assert result["status"] in ["SUCCEEDED", "FAILED"]
    assert "logs" in result


@pytest.mark.asyncio
async def test_actions_replay_status_tool(mcp_server):
    """Test actions.replayStatus tool call."""
    # First create and replay an action
    create_request = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/call",
        "params": {
            "name": "actions.create",
            "arguments": {
                "artifact_path": "test/file.py",
                "summary": "Test action",
                "behaviors_cited": ["behavior_test"],
                "actor": {
                    "id": "test-actor",
                    "role": "STRATEGIST",
                    "surface": "MCP"
                }
            }
        }
    }

    create_response_str = await mcp_server.handle_request(json.dumps(create_request))
    create_response = json.loads(create_response_str)
    content_text = create_response["result"]["content"][0]["text"]
    created_action = json.loads(content_text)
    action_id = created_action["action_id"]

    # Replay the action
    replay_request = {
        "jsonrpc": "2.0",
        "id": "2",
        "method": "tools/call",
        "params": {
            "name": "actions.replay",
            "arguments": {
                "action_ids": [action_id],
                "actor": {
                    "id": "test-actor",
                    "role": "STRATEGIST",
                    "surface": "MCP"
                }
            }
        }
    }

    replay_response_str = await mcp_server.handle_request(json.dumps(replay_request))
    replay_response = json.loads(replay_response_str)
    content_text = replay_response["result"]["content"][0]["text"]
    replay_result = json.loads(content_text)
    replay_id = replay_result["replay_id"]

    # Now get replay status
    status_request = {
        "jsonrpc": "2.0",
        "id": "3",
        "method": "tools/call",
        "params": {
            "name": "actions.replayStatus",
            "arguments": {
                "replay_id": replay_id
            }
        }
    }

    response_str = await mcp_server.handle_request(json.dumps(status_request))
    response = json.loads(response_str)

    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "3"
    assert "result" in response

    content_text = response["result"]["content"][0]["text"]
    result = json.loads(content_text)

    assert result["replay_id"] == replay_id
    assert "status" in result
    assert "progress" in result


@pytest.mark.asyncio
async def test_tools_list_includes_action_tools(mcp_server):
    """Test that action tools are registered (may be lazy-loaded)."""
    # Activate execution tools group (which contains actions.*) first
    loader = mcp_server._lazy_loader
    if loader is not None:
        loader.activate_group("execution")

    request = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/list",
        "params": {}
    }

    response_str = await mcp_server.handle_request(json.dumps(request))
    response = json.loads(response_str)

    assert "result" in response
    assert "tools" in response["result"]

    tool_names = [tool["name"] for tool in response["result"]["tools"]]

    # Check that all action tools are present (tool names use underscores in active set)
    assert "actions_create" in tool_names
    assert "actions_list" in tool_names
    assert "actions_get" in tool_names
    assert "actions_replay" in tool_names
    assert "actions_replaystatus" in tool_names
