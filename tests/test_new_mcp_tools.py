#!/usr/bin/env python3
"""Test script for newly implemented MCP tools.

This is a manual test script, not a pytest module.
Run directly: python tests/test_new_mcp_tools.py
"""

import asyncio
import json

import pytest

# Skip entire module when collected by pytest — this is a manual script
pytestmark = pytest.mark.skip(reason="Manual test script, not pytest tests")

from amprealize.mcp_device_flow import MCPDeviceFlowHandler


async def test_auth_tools():
    """Test the 4 new auth.* tools."""
    print("\n=== Testing Auth Tools ===\n")

    handler = MCPDeviceFlowHandler()

    # Test auth.ensureGrant
    print("1. Testing auth.ensureGrant...")
    try:
        result = await handler.handle_tool_call(
            "auth.ensureGrant",
            {
                "agent_id": "test-agent",
                "surface": "MCP",
                "tool_name": "test.tool",
                "scopes": ["read", "write"],
            }
        )
        print(f"   ✅ Result: {json.dumps(result, indent=2)}\n")
    except Exception as e:
        print(f"   ❌ Error: {e}\n")

    # Test auth.listGrants
    print("2. Testing auth.listGrants...")
    try:
        result = await handler.handle_tool_call(
            "auth.listGrants",
            {"agent_id": "test-agent"}
        )
        print(f"   ✅ Result: {json.dumps(result, indent=2)}\n")
    except Exception as e:
        print(f"   ❌ Error: {e}\n")

    # Test auth.policy.preview
    print("3. Testing auth.policy.preview...")
    try:
        result = await handler.handle_tool_call(
            "auth.policy.preview",
            {
                "agent_id": "test-agent",
                "tool_name": "test.tool",
                "scopes": ["read"],
            }
        )
        print(f"   ✅ Result: {json.dumps(result, indent=2)}\n")
    except Exception as e:
        print(f"   ❌ Error: {e}\n")

    # Test auth.revoke
    print("4. Testing auth.revoke...")
    try:
        result = await handler.handle_tool_call(
            "auth.revoke",
            {
                "grant_id": "test-grant-123",
                "revoked_by": "test-admin",
            }
        )
        print(f"   ✅ Result: {json.dumps(result, indent=2)}\n")
    except Exception as e:
        print(f"   ❌ Error: {e}\n")


def test_reflection_adapter():
    """Test reflection.extract adapter."""
    print("\n=== Testing Reflection Tool ===\n")

    from amprealize.adapters import MCPReflectionServiceAdapter
    from amprealize.reflection_service import ReflectionService

    print("1. Testing reflection.extract...")
    try:
        service = ReflectionService()
        adapter = MCPReflectionServiceAdapter(service=service)

        result = adapter.extract({
            "trace_text": "Step 1: Initialize database\nStep 2: Load configuration\nStep 3: Start server",
            "max_candidates": 3,
        })
        print(f"   ✅ Result keys: {list(result.keys())}")
        print(f"   Candidates found: {len(result['candidates'])}\n")
    except Exception as e:
        print(f"   ❌ Error: {e}\n")


def test_manifest_loading():
    """Test that all 7 tool manifests can be loaded."""
    print("\n=== Testing Manifest Loading ===\n")

    import json
    from pathlib import Path

    tools = [
        "auth.ensureGrant",
        "auth.listGrants",
        "auth.policy.preview",
        "auth.revoke",
        "reflection.extract",
        "security.scanSecrets",
        "tasks.listAssignments",
    ]

    mcp_tools_dir = Path("mcp/tools")

    for tool in tools:
        manifest_path = mcp_tools_dir / f"{tool}.json"
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
            print(f"   ✅ {tool}: {manifest.get('description', 'No description')[:80]}")
        except Exception as e:
            print(f"   ❌ {tool}: {e}")

    print()


if __name__ == "__main__":
    print("=" * 70)
    print("Testing 7 Newly Implemented MCP Tools")
    print("=" * 70)

    # Test manifest loading
    test_manifest_loading()

    # Test auth tools (async)
    asyncio.run(test_auth_tools())

    # Test reflection adapter
    test_reflection_adapter()

    print("\n" + "=" * 70)
    print("Testing Complete!")
    print("=" * 70)
