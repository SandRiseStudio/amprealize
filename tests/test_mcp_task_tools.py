#!/usr/bin/env python3
"""
Test MCP Task Tools Integration

Tests all 4 task tools via MCP JSON-RPC protocol:
1. tasks.create - Create new task
2. tasks.listAssignments - List tasks
3. tasks.updateStatus - Update status
4. tasks.getStats - Get analytics
"""

import json
import subprocess
import sys
import time
from typing import Any, Dict, Optional


def send_mcp_request(method: str, params: Dict[str, Any], request_id: int = 1) -> Dict[str, Any]:
    """Send MCP request via subprocess stdin/stdout."""
    request = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    }

    # Start MCP server
    proc = subprocess.Popen(
        ["python", "-m", "amprealize.mcp_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Send request
    request_json = json.dumps(request) + "\n"
    stdout, stderr = proc.communicate(request_json, timeout=30)

    # Parse response
    try:
        response = json.loads(stdout.strip())
        return response
    except json.JSONDecodeError as e:
        print(f"Failed to parse response: {e}")
        print(f"stdout: {stdout}")
        print(f"stderr: {stderr}")
        raise


def test_task_tools():
    """Test all task tools end-to-end."""
    print("=" * 80)
    print("MCP Task Tools Integration Test")
    print("=" * 80)

    # Test 1: Initialize
    print("\n1. Testing initialize...")
    response = send_mcp_request("initialize", {"clientInfo": {"name": "test", "version": "1.0"}}, request_id=1)

    if response.get("error"):
        print(f"   ❌ Initialize failed: {response['error'].get('message')}")
        return False

    print(f"   ✅ Server: {response['result']['serverInfo']['name']} v{response['result']['serverInfo']['version']}")

    # Test 2: List tools (check task tools exist)
    print("\n2. Testing tools/list (verify task tools registered)...")
    response = send_mcp_request("tools/list", {}, request_id=2)

    if response.get("error"):
        print(f"   ❌ tools/list failed: {response['error'].get('message')}")
        return False

    tools = response["result"]["tools"]
    task_tools = [t for t in tools if t["name"].startswith("tasks.")]
    print(f"   ✅ Found {len(task_tools)} task tools:")
    for tool in task_tools:
        print(f"      - {tool['name']}: {tool['description'][:60]}...")

    # Test 3: Create task
    print("\n3. Testing tasks.create...")
    create_params = {
        "name": "tasks.create",
        "arguments": {
            "agent_id": "agent-test-mcp",
            "task_type": "code_review",
            "priority": 2,
            "title": "MCP Integration Test Task",
            "description": "Test task created via MCP protocol",
            "metadata": {"source": "mcp_test", "test_id": "integration-001"}
        }
    }
    response = send_mcp_request("tools/call", create_params, request_id=3)

    if response.get("error"):
        print(f"   ❌ tasks.create failed: {response['error'].get('message')}")
        return False

    # Parse task from MCP content format
    content = response["result"]["content"][0]["text"]
    task = json.loads(content)
    task_id = task["task_id"]
    print(f"   ✅ Created task {task_id}")
    print(f"      Status: {task['status']}, Priority: {task['priority']}, Title: {task['title']}")

    # Test 4: List tasks
    print("\n4. Testing tasks.listAssignments...")
    list_params = {
        "name": "tasks.listAssignments",
        "arguments": {
            "agent_id": "agent-test-mcp",
            "status": "pending",
            "limit": 10
        }
    }
    response = send_mcp_request("tools/call", list_params, request_id=4)

    if response.get("error"):
        print(f"   ❌ tasks.listAssignments failed: {response['error'].get('message')}")
        return False

    content = response["result"]["content"][0]["text"]
    result = json.loads(content)
    print(f"   ✅ Found {result['total']} pending tasks for agent-test-mcp")

    # Test 5: Update status
    print("\n5. Testing tasks.updateStatus...")
    update_params = {
        "name": "tasks.updateStatus",
        "arguments": {
            "task_id": task_id,
            "status": "completed",
            "metadata": {"completion_notes": "Test completed via MCP"}
        }
    }
    response = send_mcp_request("tools/call", update_params, request_id=5)

    if response.get("error"):
        print(f"   ❌ tasks.updateStatus failed: {response['error'].get('message')}")
        return False

    content = response["result"]["content"][0]["text"]
    updated_task = json.loads(content)
    print(f"   ✅ Updated task {task_id} to status: {updated_task['status']}")

    # Test 6: Get stats
    print("\n6. Testing tasks.getStats...")
    stats_params = {
        "name": "tasks.getStats",
        "arguments": {
            "agent_id": "agent-test-mcp"
        }
    }
    response = send_mcp_request("tools/call", stats_params, request_id=6)

    if response.get("error"):
        print(f"   ❌ tasks.getStats failed: {response['error'].get('message')}")
        return False

    content = response["result"]["content"][0]["text"]
    stats = json.loads(content)
    print(f"   ✅ Task stats for agent-test-mcp:")
    print(f"      Total: {stats['total']}, Pending: {stats['pending']}, In Progress: {stats['in_progress']}")
    print(f"      Completed: {stats['completed']}, Failed: {stats['failed']}, Blocked: {stats['blocked']}")

    print("\n" + "=" * 80)
    print("✅ All MCP task tools integration tests passed!")
    print("=" * 80)
    return True


if __name__ == "__main__":
    try:
        success = test_task_tools()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
