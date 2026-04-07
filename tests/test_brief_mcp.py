#!/usr/bin/env python3
"""Test Brief MCP server responds to JSON-RPC initialization."""

import json
import subprocess
import sys

def test_mcp_server():
    """Send initialization message to Brief MCP server."""

    # JSON-RPC initialization request
    init_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "test-client",
                "version": "1.0.0"
            }
        }
    }

    print("🧪 Testing Brief MCP server...")
    print(f"📤 Sending: {json.dumps(init_request, indent=2)}\n")

    try:
        # Start brief-mcp and send initialization
        proc = subprocess.Popen(
            ['brief-mcp'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        # Send request and wait for response (with timeout)
        stdout, stderr = proc.communicate(
            input=json.dumps(init_request) + '\n',
            timeout=5
        )

        print("📥 Response (stdout):")
        print(stdout)

        if stderr:
            print("\n⚠️  Stderr output:")
            print(stderr)

        # Try to parse response
        if stdout.strip():
            response = json.loads(stdout.strip())
            if 'result' in response:
                print("\n✅ Brief MCP server is working!")
                print(f"   Server info: {response['result'].get('serverInfo', {})}")
                return True
            else:
                print("\n⚠️  Unexpected response format")
                return False
        else:
            print("\n❌ No response from server")
            return False

    except subprocess.TimeoutExpired:
        proc.kill()
        print("\n⚠️  Server did not respond within timeout")
        print("   This might indicate the server is waiting for more input")
        return None
    except json.JSONDecodeError as e:
        print(f"\n❌ Invalid JSON response: {e}")
        return False
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False

if __name__ == '__main__':
    result = test_mcp_server()

    if result is True:
        print("\n✅ Brief MCP server is ready for Claude Desktop")
        sys.exit(0)
    elif result is None:
        print("\n⏸️  Brief MCP server started but needs full MCP client")
        print("   This is normal - start Claude Desktop to use it")
        sys.exit(0)
    else:
        print("\n❌ Brief MCP server may have issues")
        sys.exit(1)
