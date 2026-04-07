#!/usr/bin/env python3
"""
Example: Testing Amprealize MCP Server Locally

Demonstrates MCP protocol communication by sending JSON-RPC requests
to the MCP server and parsing responses.

Usage:
    python examples/test_mcp_server.py
"""

import json
import subprocess
import sys
from typing import Any, Dict


def send_mcp_request(method: str, params: Dict[str, Any], request_id: int = 1) -> Dict[str, Any]:
    """
    Send JSON-RPC request to MCP server via stdin and parse response from stdout.

    Args:
        method: JSON-RPC method name
        params: Method parameters
        request_id: Request ID for correlation

    Returns:
        Parsed JSON-RPC response
    """
    request = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    }

    # Start MCP server process
    process = subprocess.Popen(
        [sys.executable, "-m", "amprealize.mcp_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Send request and get response
    request_line = json.dumps(request) + "\n"
    stdout, stderr = process.communicate(input=request_line, timeout=5)

    # Parse response (first line of stdout)
    response_line = stdout.strip().split("\n")[0] if stdout.strip() else "{}"
    response = json.loads(response_line)

    return response


def main() -> None:
    """Run MCP server tests."""
    print("Amprealize MCP Server Test\n" + "=" * 50 + "\n")

    # Test 1: Initialize
    print("1. Testing initialize...")
    response = send_mcp_request(
        "initialize",
        {"clientInfo": {"name": "test-client", "version": "1.0"}},
    )

    if "result" in response:
        print(f"   ✅ Server initialized: {response['result']['serverInfo']['name']} v{response['result']['serverInfo']['version']}")
        print(f"   Protocol: {response['result']['protocolVersion']}")
    else:
        print(f"   ❌ Initialize failed: {response.get('error', {}).get('message')}")
        return

    # Test 2: List tools
    print("\n2. Testing tools/list...")
    response = send_mcp_request("tools/list", {}, request_id=2)

    if "result" in response:
        tools = response["result"]["tools"]
        auth_tools = [t for t in tools if t["name"].startswith("auth.")]
        print(f"   ✅ Found {len(tools)} total tools")
        print(f"   ✅ Found {len(auth_tools)} auth tools:")
        for tool in auth_tools[:4]:  # Show first 4 auth tools
            print(f"      - {tool['name']}: {tool['description'][:60]}...")
    else:
        print(f"   ❌ tools/list failed: {response.get('error', {}).get('message')}")
        return

    # Test 3: Call auth.authStatus
    print("\n3. Testing tools/call (auth.authStatus)...")
    response = send_mcp_request(
        "tools/call",
        {
            "name": "auth.authStatus",
            "arguments": {"client_id": "test-client"},
        },
        request_id=3,
    )

    if "result" in response:
        content_text = response["result"]["content"][0]["text"]
        auth_status = json.loads(content_text)
        print(f"   ✅ Tool executed successfully")
        print(f"   Authenticated: {auth_status['is_authenticated']}")
        print(f"   Needs login: {auth_status['needs_login']}")
    else:
        print(f"   ❌ tools/call failed: {response.get('error', {}).get('message')}")
        return

    # Test 4: Ping
    print("\n4. Testing ping...")
    response = send_mcp_request("ping", {}, request_id=4)

    if "result" in response and response["result"].get("status") == "ok":
        print("   ✅ Server is responsive")
    else:
        print(f"   ❌ Ping failed: {response.get('error', {}).get('message')}")

    print("\n" + "=" * 50)
    print("✅ All MCP server tests passed!\n")
    print("Next steps:")
    print("  1. Configure Claude Desktop with MCP server")
    print("  2. Test device login flow end-to-end")
    print("  3. Verify token storage parity with CLI\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        sys.exit(1)
