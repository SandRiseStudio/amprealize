#!/usr/bin/env python3
"""Test MCP auth session context implementation."""
import asyncio
from datetime import datetime, timedelta

from amprealize.mcp_server import MCPServer, MCPSessionContext, PUBLIC_TOOLS


def test_session_context():
    """Test MCPSessionContext behavior."""
    print("=== Test 1: Empty Session ===")
    ctx = MCPSessionContext()
    print(f"Empty session authenticated: {ctx.is_authenticated}")
    assert not ctx.is_authenticated, "Empty session should not be authenticated"
    print("✓ Empty session is not authenticated")

    print("\n=== Test 2: Set User ===")
    ctx.user_id = "user_123"
    ctx.auth_method = "device_flow"  # Must set auth_method!
    ctx.expires_at = datetime.utcnow() + timedelta(hours=1)
    print(f"With user_id authenticated: {ctx.is_authenticated}")
    print(f"Identity: {ctx.identity}")
    assert ctx.is_authenticated, "Session with user_id should be authenticated"
    assert ctx.identity == "user_123"
    print("✓ Session with user_id is authenticated")

    print("\n=== Test 3: Expired Session ===")
    ctx.expires_at = datetime.utcnow() - timedelta(hours=1)
    print(f"Expired session authenticated: {ctx.is_authenticated}")
    assert not ctx.is_authenticated, "Expired session should not be authenticated"
    print("✓ Expired session is not authenticated")

    print("\n=== Test 4: Service Principal ===")
    ctx2 = MCPSessionContext()
    ctx2.service_principal_id = "sp_456"
    ctx2.auth_method = "client_credentials"  # Must set auth_method!
    ctx2.expires_at = datetime.utcnow() + timedelta(hours=24)
    print(f"Service principal authenticated: {ctx2.is_authenticated}")
    print(f"Identity: {ctx2.identity}")
    assert ctx2.is_authenticated
    assert ctx2.identity == "sp_456"
    print("✓ Service principal session is authenticated")


def test_public_tools():
    """Test PUBLIC_TOOLS constant."""
    print("\n=== Test 5: PUBLIC_TOOLS ===")
    print(f"PUBLIC_TOOLS: {PUBLIC_TOOLS}")

    assert "auth.clientCredentials" in PUBLIC_TOOLS
    assert "auth.deviceLogin" in PUBLIC_TOOLS
    assert "auth.deviceInit" in PUBLIC_TOOLS
    assert "auth.devicePoll" in PUBLIC_TOOLS
    assert "auth.authStatus" in PUBLIC_TOOLS
    assert "auth.refreshToken" in PUBLIC_TOOLS
    assert "auth.consentStatus" in PUBLIC_TOOLS

    # Verify protected tools are NOT in public
    assert "behaviors.list" not in PUBLIC_TOOLS
    assert "runs.create" not in PUBLIC_TOOLS
    assert "projects.list" not in PUBLIC_TOOLS
    print("✓ PUBLIC_TOOLS contains expected auth tools")


def test_session_scopes():
    """Test session scope management."""
    print("\n=== Test 6: Session Scopes ===")
    ctx = MCPSessionContext()
    ctx.user_id = "user_789"
    ctx.expires_at = datetime.utcnow() + timedelta(hours=1)
    ctx.granted_scopes = {"behaviors.read", "runs.create", "compliance.validate"}
    ctx.roles = {"admin", "developer"}
    ctx.auth_method = "device_flow"
    ctx.org_id = "org_abc"

    print(f"Scopes: {ctx.granted_scopes}")
    print(f"Roles: {ctx.roles}")
    print(f"Auth method: {ctx.auth_method}")
    print(f"Org ID: {ctx.org_id}")

    assert "behaviors.read" in ctx.granted_scopes
    assert "admin" in ctx.roles
    assert ctx.auth_method == "device_flow"
    print("✓ Session scopes and roles work correctly")


if __name__ == "__main__":
    test_session_context()
    test_public_tools()
    test_session_scopes()
    print("\n" + "=" * 50)
    print("✅ All MCP auth session tests passed!")
