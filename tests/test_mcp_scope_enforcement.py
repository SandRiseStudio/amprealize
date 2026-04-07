#!/usr/bin/env python3
"""Test Phase 3: Scope enforcement infrastructure."""

from amprealize.mcp_server import MCPServer, MCPSessionContext, PUBLIC_TOOLS


def test_tool_scopes_loaded():
    """Test that tool scopes are loaded from manifests."""
    print("Creating MCPServer...")
    server = MCPServer()

    print(f"\n=== Tool Scopes Loaded ===")
    print(f"Total tools with scopes: {len(server._tool_scopes)}")
    for tool, scopes in sorted(server._tool_scopes.items())[:10]:
        print(f"  {tool}: {scopes}")

    # Verify some expected scopes
    assert "behaviors_list" in server._tool_scopes, "behaviors_list should have scopes"
    assert server._tool_scopes["behaviors_list"] == ["behaviors.read"]

    assert "runs_create" in server._tool_scopes, "runs_create should have scopes"
    assert server._tool_scopes["runs_create"] == ["runs.create"]

    print("✓ Tool scopes loaded correctly")


def test_session_scope_methods():
    """Test MCPSessionContext scope checking methods."""
    print(f"\n=== Session Scope Methods ===")
    ctx = MCPSessionContext()
    ctx.granted_scopes = {"behaviors.read", "runs.read", "runs.create"}

    print(f"Granted scopes: {ctx.granted_scopes}")

    # Test has_scope
    assert ctx.has_scope("behaviors.read") == True
    assert ctx.has_scope("admin.delete") == False
    print("✓ has_scope works")

    # Test has_all_scopes
    assert ctx.has_all_scopes(["behaviors.read", "runs.read"]) == True
    assert ctx.has_all_scopes(["behaviors.read", "admin.delete"]) == False
    assert ctx.has_all_scopes([]) == True  # Empty list = True
    print("✓ has_all_scopes works")

    # Test has_any_scope
    assert ctx.has_any_scope(["behaviors.read", "admin.delete"]) == True
    assert ctx.has_any_scope(["admin.delete", "admin.create"]) == False
    assert ctx.has_any_scope([]) == True  # Empty list = True
    print("✓ has_any_scope works")

    # Test missing_scopes
    missing = ctx.missing_scopes(["behaviors.read", "admin.delete"])
    assert missing == {"admin.delete"}
    print(f"✓ missing_scopes works: {missing}")


def test_auth_middleware_import():
    """Test that MCPAuthMiddleware can be imported."""
    print(f"\n=== Auth Middleware ===")
    from amprealize.mcp_auth_middleware import MCPAuthMiddleware, AuthDecision, AuthResult

    middleware = MCPAuthMiddleware(
        tool_scopes={"test_tool": ["test.scope"]},
    )

    assert middleware.get_tool_scopes("test_tool") == ["test.scope"]
    assert middleware.get_tool_scopes("unknown_tool") == []
    assert middleware.get_all_scopes() == {"test.scope"}
    print("✓ MCPAuthMiddleware works")


if __name__ == "__main__":
    test_tool_scopes_loaded()
    test_session_scope_methods()
    test_auth_middleware_import()
    print("\n" + "=" * 50)
    print("✅ All Phase 3 scope enforcement tests passed!")
