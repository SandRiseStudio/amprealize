#!/usr/bin/env python3
"""
Helper script to call MCP server tools directly.

Usage:
    python scripts/mcp_call.py <tool_name> [--args '{"key": "value"}']

Examples:
    python scripts/mcp_call.py orgs_list
    python scripts/mcp_call.py orgs_create --args '{"name": "TestOrg"}'
    python scripts/mcp_call.py projects_create --args '{"user_id": "123", "org_id": "456", "name": "patio2"}'
"""
import json
import os
import subprocess
import sys
import argparse
from pathlib import Path

# Load .env file from amprealize root
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                # Remove quotes if present
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key.strip(), value)


def call_mcp_tool(tool_name: str, arguments: dict | None = None) -> dict:
    """Call an MCP tool and return the result."""

    # Build the JSON-RPC messages
    messages = [
        # Initialize
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mcp-call-script", "version": "1.0.0"}
            }
        },
        # Initialized notification (no id = no response expected per JSON-RPC 2.0)
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        },
        # Tool call
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments or {}
            }
        }
    ]

    # Send as newline-delimited JSON
    input_data = "\n".join(json.dumps(m) for m in messages) + "\n"

    # Run MCP server with current environment (including loaded .env vars)
    proc = subprocess.run(
        [sys.executable, "-m", "amprealize.mcp_server"],
        input=input_data,
        capture_output=True,
        text=True,
        timeout=30,
        env=os.environ.copy()  # Pass full environment including loaded .env
    )

    # Parse output - find JSON responses (not log lines)
    responses = []
    for line in proc.stdout.split("\n"):
        line = line.strip()
        if line and line.startswith("{"):
            try:
                obj = json.loads(line)
                if "jsonrpc" in obj:
                    responses.append(obj)
            except json.JSONDecodeError:
                pass

    # Find the tool call response (id=2)
    for resp in responses:
        if resp.get("id") == 2:
            return resp

    # Return last response if no id=2 found
    return responses[-1] if responses else {"error": "No response", "stderr": proc.stderr}


def main():
    parser = argparse.ArgumentParser(description="Call MCP server tools")
    parser.add_argument("tool", help="Tool name (e.g., orgs_list, projects_create)")
    parser.add_argument("--args", "-a", default="{}", help="JSON arguments")
    parser.add_argument("--pretty", "-p", action="store_true", help="Pretty print output")

    args = parser.parse_args()

    try:
        arguments = json.loads(args.args)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON arguments: {e}", file=sys.stderr)
        sys.exit(1)

    result = call_mcp_tool(args.tool, arguments)

    if args.pretty:
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps(result))


if __name__ == "__main__":
    main()
