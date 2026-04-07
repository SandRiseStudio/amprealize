# MCP Tool Schema Pattern for VS Code Copilot Chat

> **TL;DR**: To make Amprealize MCP tools work directly in VS Code Copilot Chat without requiring parameters, update the JSON schema's `required` array and rely on session context injection.

## Problem Statement

VS Code Copilot Chat validates MCP tool parameters **client-side** before sending requests to the server. If a tool schema declares parameters as `required`, Copilot will reject the call unless those parameters are explicitly provided.

This creates friction because:
1. Users must manually provide `user_id`, `org_id`, etc. for every tool call
2. Session context (authenticated user, accessible resources) is already known server-side
3. Admin users should be able to access all resources without specifying each one

## Solution Architecture

### 1. Session Context Injection

The MCP server maintains a session context (`MCPSessionContext`) that includes:

```python
@dataclass
class MCPSessionContext:
    user_id: Optional[str] = None
    scopes: Set[str] = field(default_factory=set)
    expires_at: Optional[datetime] = None

    # Authorization context (populated after auth)
    is_admin: bool = False
    accessible_org_ids: Set[str] = field(default_factory=set)
    accessible_project_ids: Set[str] = field(default_factory=set)
```

When a tool is called, the server injects session context into the tool arguments via `_inject_session_context()`:

```python
def _inject_session_context(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Inject session context into tool arguments."""
    arguments["_session"] = {
        "user_id": self._session_context.user_id,
        "scopes": list(self._session_context.scopes),
        "is_admin": self._session_context.is_admin,
        "accessible_org_ids": list(self._session_context.accessible_org_ids),
        "accessible_project_ids": list(self._session_context.accessible_project_ids),
    }
    return arguments
```

### 2. Schema Updates

Update tool JSON schemas to make context parameters optional:

**Before** (requires explicit parameters):
```json
{
  "name": "projects.list",
  "inputSchema": {
    "type": "object",
    "properties": {
      "user_id": { "type": "string" },
      "org_id": { "type": "string" }
    },
    "required": ["user_id", "org_id"]
  }
}
```

**After** (uses session context):
```json
{
  "name": "projects.list",
  "inputSchema": {
    "type": "object",
    "properties": {
      "user_id": { "type": "string", "description": "Override user (optional, uses session)" },
      "org_id": { "type": "string", "description": "Filter by org (optional)" }
    },
    "required": []
  }
}
```

### 3. Handler Updates

Update handlers to use session context when parameters are not provided:

```python
def handle_list_projects(project_service, org_service, arguments: Dict[str, Any]) -> Dict[str, Any]:
    # Get user from session if not provided
    session = arguments.get("_session", {})
    user_id = arguments.get("user_id") or session.get("user_id")
    org_id = arguments.get("org_id")  # Optional filter
    is_admin = session.get("is_admin", False)

    if is_admin and not org_id:
        # Admin sees all projects
        projects = list_all_projects()
    elif org_id:
        # Filter by specific org
        projects = list_org_projects(org_id)
    else:
        # User's accessible projects
        projects = list_user_projects(user_id)

    return {"success": True, "projects": projects}
```

### 4. Admin User Detection

Admin users are detected via environment variable:

```python
# In .vscode/mcp.json
{
  "env": {
    "AMPREALIZE_DEV_ADMIN_USERS": "dev-user,admin,dev-admin"
  }
}

# In mcp_server.py
def _populate_authorization_context(self):
    admin_users = os.environ.get("AMPREALIZE_DEV_ADMIN_USERS", "admin,dev-admin")
    admin_list = [u.strip() for u in admin_users.split(",")]

    if self._session_context.user_id in admin_list:
        self._session_context.is_admin = True
        self._logger.info(f"User {user_id} is an admin - full access granted")
```

## Implementation Checklist

When adding a new MCP tool or updating an existing one:

- [ ] **Schema**: Set `"required": []` or minimal required fields in `mcp/tools/<tool>.json`
- [ ] **Handler**: Check `arguments.get("_session", {})` for session context
- [ ] **Fallback**: Use session values when explicit parameters not provided
- [ ] **Admin Check**: Call `_is_admin_from_session(arguments)` for elevated access
- [ ] **Access Control**: Verify user can access requested resources
- [ ] **VS Code Restart**: Full restart (Cmd+Q) required for schema cache refresh

## Files Changed

| File | Purpose |
|------|---------|
| `mcp/tools/<tool>.json` | Tool schema with `required: []` |
| `amprealize/mcp_server.py` | Session context injection, admin detection |
| `amprealize/mcp/handlers/*.py` | Handler logic using session context |
| `.vscode/mcp.json` | Admin users env var |

## VS Code Copilot Integration

After implementing this pattern:

1. **No parameters needed**: `mcp_amprealize_projects_list` works with zero arguments
2. **Session-aware**: Tools automatically use the authenticated user's context
3. **Admin access**: Dev admin users can see all resources across all users/orgs
4. **Optional overrides**: Users can still provide explicit parameters to filter

### Example Usage

```
User: "List my projects"
Copilot: [calls mcp_amprealize_projects_list with no args]
Result: Returns all 5 projects (4 personal + 1 org)
```

## Troubleshooting

### "must have required property 'X'" Error

**Cause**: VS Code Copilot cached the old schema with required fields.

**Fix**: Fully quit VS Code (Cmd+Q on macOS) and restart. Window reload is insufficient.

### Tool Shows as "Disabled"

**Cause**: MCP server not connected or tool not loaded.

**Fix**: Check Output panel for "Amprealize MCP Server" logs. Verify server shows "Discovered N tools".

### Session Not Restored

**Cause**: PostgreSQL session store not configured or session expired.

**Fix**: Check logs for "Session restored from PostgreSQL" message. Run device auth flow if needed.

## Related Documentation

- [MCP_SERVER_DESIGN.md](contracts/MCP_SERVER_DESIGN.md) - Full MCP server architecture
- [AGENT_AUTH_ARCHITECTURE.md](AGENT_AUTH_ARCHITECTURE.md) - Authentication flow
- [ACTION_SERVICE_CONTRACT.md](contracts/ACTION_SERVICE_CONTRACT.md) - Service contracts
