#!/usr/bin/env python3
"""Simple demonstration of MCP progress notifications."""
import json
import subprocess
import sys

def demo_notifications():
    """Demonstrate JSON-RPC notifications during tool execution."""

    print("=" * 60)
    print("MCP Progress Notifications Demo")
    print("=" * 60)
    print()
    print("This demonstrates how MCP tools can send progress notifications")
    print("during long-running operations using JSON-RPC notifications.")
    print()
    print("Notifications have NO 'id' field, so no response is expected.")
    print("They provide real-time updates without blocking the request/response.")
    print()
    print("-" * 60)
    print()

    # Send pattern detection request (will trigger notifications)
    request = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "patterns.detectPatterns",
            "arguments": {
                "run_ids": ["demo_run_1", "demo_run_2"],
                "min_frequency": 1
            }
        }
    })

    proc = subprocess.Popen(
        [sys.executable, "-m", "amprealize.mcp_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Send request
    stdout, stderr = proc.communicate(input=request + "\n", timeout=5)

    print("📤 Sent JSON-RPC request:")
    print(f"   Method: tools/call")
    print(f"   Tool: patterns.detectPatterns")
    print()
    print("📨 Received messages (in order):")
    print()

    # Parse all stdout lines
    messages = []
    for line in stdout.strip().split("\n"):
        if line:
            try:
                msg = json.loads(line)
                messages.append(msg)
            except json.JSONDecodeError:
                pass

    for i, msg in enumerate(messages, 1):
        if "id" in msg:
            # This is a response
            result = msg.get("result", msg.get("error"))
            print(f"{i}. ✅ RESPONSE (id={msg['id']})")
            if "error" in msg:
                print(f"   Error: {msg['error'].get('message', 'Unknown error')}")
            else:
                print(f"   Type: JSON-RPC Response (has 'id' field)")
                print(f"   Status: Success")
        elif "method" in msg:
            # This is a notification
            params = msg.get("params", {})
            print(f"{i}. 📢 NOTIFICATION (method={msg['method']})")
            print(f"   No 'id' field = no response expected")
            print(f"   Status: {params.get('status', 'unknown')}")
            print(f"   Message: {params.get('message', 'N/A')}")
        print()

    print("-" * 60)
    print()
    print("✅ Demonstration complete!")
    print()
    print("Key takeaways:")
    print("• Notifications arrive BEFORE the final response")
    print("• They provide progress updates for long operations")
    print("• Client can display them to users in real-time")
    print("• This pattern works over stdio without HTTP/SSE")
    print()

if __name__ == "__main__":
    try:
        demo_notifications()
    except Exception as e:
        print(f"❌ Demo failed: {e}")
        sys.exit(1)
