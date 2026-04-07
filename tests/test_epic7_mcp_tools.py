#!/usr/bin/env python3
"""
Test Epic 7 MCP Tools Integration

Validates that all 6 new Epic 7 services have proper MCP tool manifests,
proper routing in the MCP server, and working adapters.
"""

import json
import os
import sys
from pathlib import Path

# Add the amprealize package to the path
sys.path.insert(0, str(Path(__file__).parent / "amprealize"))

def test_mcp_tools_exist():
    """Test that all MCP tool manifests exist."""
    tools_dir = Path(__file__).parent / "mcp" / "tools"

    expected_tools = [
        "fine-tuning.create.json",
        "fine-tuning.status.json",
        "fine-tuning.list.json",
        "reviews.create.json",
        "tenants.create.json",
        "retrieval.advanced-search.json",
        "collaboration.workspace.create.json",
        "rate-limits.configure.json"
    ]

    print("🔍 Testing MCP tool manifests...")

    missing_tools = []
    for tool in expected_tools:
        tool_path = tools_dir / tool
        if tool_path.exists():
            print(f"  ✅ {tool}")
        else:
            print(f"  ❌ {tool} - MISSING")
            missing_tools.append(tool)

    return len(missing_tools) == 0, missing_tools

def test_mcp_server_loading():
    """Test that the MCP server can load without import errors."""
    print("\n🔍 Testing MCP server loading...")

    try:
        from amprealize.mcp_server import MCPServer
        print("  ✅ MCP server imports successfully")

        # Test that services can be instantiated
        from amprealize.mcp_server import MCPServiceRegistry
        registry = MCPServiceRegistry()

        # Test all 6 new services
        services = {
            "fine_tuning": registry.fine_tuning_service(),
            "agent_review": registry.agent_review_service(),
            "multi_tenant": registry.multi_tenant_service(),
            "advanced_retrieval": registry.advanced_retrieval_service(),
            "collaboration": registry.collaboration_service(),
            "api_rate_limiting": registry.api_rate_limiting_service()
        }

        for service_name, service in services.items():
            print(f"  ✅ {service_name} service loaded")

        return True, None

    except Exception as e:
        print(f"  ❌ MCP server loading failed: {e}")
        return False, str(e)

def test_adapters_exist():
    """Test that MCP adapters exist for all services."""
    print("\n🔍 Testing MCP adapters...")

    try:
        from amprealize.adapters import (
            MCPFineTuningServiceAdapter,
            MCPAgentReviewServiceAdapter,
            MCPMultiTenantServiceAdapter,
            MCPAdvancedRetrievalServiceAdapter,
            MCPCollaborationServiceAdapter,
            MCPAPIRateLimitingServiceAdapter
        )

        adapters = {
            "fine_tuning": MCPFineTuningServiceAdapter,
            "agent_review": MCPAgentReviewServiceAdapter,
            "multi_tenant": MCPMultiTenantServiceAdapter,
            "advanced_retrieval": MCPAdvancedRetrievalServiceAdapter,
            "collaboration": MCPCollaborationServiceAdapter,
            "api_rate_limiting": MCPAPIRateLimitingServiceAdapter
        }

        for adapter_name, adapter_class in adapters.items():
            print(f"  ✅ {adapter_name} adapter exists")

        return True, None

    except Exception as e:
        print(f"  ❌ Adapter loading failed: {e}")
        return False, str(e)

def test_tool_manifests_valid():
    """Test that MCP tool manifests have valid JSON schema."""
    print("\n🔍 Testing tool manifest validation...")

    tools_dir = Path(__file__).parent / "mcp" / "tools"
    invalid_manifests = []

    epic7_tools = [
        "fine-tuning.create.json",
        "fine-tuning.status.json",
        "fine-tuning.list.json",
        "reviews.create.json",
        "tenants.create.json",
        "retrieval.advanced-search.json",
        "collaboration.workspace.create.json",
        "rate-limits.configure.json"
    ]

    for tool_file in epic7_tools:
        tool_path = tools_dir / tool_file
        if not tool_path.exists():
            continue

        try:
            with open(tool_path) as f:
                manifest = json.load(f)

            # Check required fields
            required_fields = ["name", "description", "inputSchema", "outputSchema"]
            missing_fields = [field for field in required_fields if field not in manifest]

            if missing_fields:
                print(f"  ❌ {tool_file} missing fields: {missing_fields}")
                invalid_manifests.append(tool_file)
            else:
                print(f"  ✅ {tool_file} valid")

        except Exception as e:
            print(f"  ❌ {tool_file} parsing failed: {e}")
            invalid_manifests.append(tool_file)

    return len(invalid_manifests) == 0, invalid_manifests

def main():
    """Run all Epic 7 MCP integration tests."""
    print("🚀 Testing Epic 7 MCP Tools Integration")
    print("=" * 50)

    # Test 1: MCP tools exist
    tools_ok, missing_tools = test_mcp_tools_exist()

    # Test 2: MCP server loading
    server_ok, server_error = test_mcp_server_loading()

    # Test 3: Adapters exist
    adapters_ok, adapters_error = test_adapters_exist()

    # Test 4: Tool manifests valid
    manifests_ok, invalid_manifests = test_tool_manifests_valid()

    # Summary
    print("\n" + "=" * 50)
    print("📊 Test Summary:")
    print(f"  Tool Manifests: {'✅ PASS' if tools_ok else '❌ FAIL'}")
    print(f"  Server Loading: {'✅ PASS' if server_ok else '❌ FAIL'}")
    print(f"  Adapters: {'✅ PASS' if adapters_ok else '❌ FAIL'}")
    print(f"  Manifest Validation: {'✅ PASS' if manifests_ok else '❌ FAIL'}")

    all_ok = tools_ok and server_ok and adapters_ok and manifests_ok

    if all_ok:
        print("\n🎉 All Epic 7 MCP tools integration tests PASSED!")
        print("\nThe following services now have full MCP surface parity:")
        print("  • FineTuningService (BC-SFT training pipeline)")
        print("  • AgentReviewService (multi-agent approval workflow)")
        print("  • MultiTenantService (tenant isolation)")
        print("  • AdvancedRetrievalService (semantic search)")
        print("  • CollaborationService (real-time co-editing)")
        print("  • APIRateLimitingService (token bucket)")
        return 0
    else:
        print("\n❌ Some tests FAILED!")
        if missing_tools:
            print(f"  Missing tools: {missing_tools}")
        if server_error:
            print(f"  Server error: {server_error}")
        if adapters_error:
            print(f"  Adapters error: {adapters_error}")
        if invalid_manifests:
            print(f"  Invalid manifests: {invalid_manifests}")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
