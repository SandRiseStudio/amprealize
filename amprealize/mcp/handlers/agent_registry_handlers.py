"""MCP tool handlers for AgentRegistryService operations.

Provides handlers for agentRegistry.* tools:
- agentRegistry.create: Create new agent
- agentRegistry.get: Get agent by ID
- agentRegistry.list: List agents with filters
- agentRegistry.update: Update agent metadata
- agentRegistry.deprecate: Deprecate an agent
- agentRegistry.publish: Publish an agent version
- agentRegistry.search: Search agents by query
- agentRegistry.bootstrap: Bootstrap from playbooks

Following `behavior_prefer_mcp_tools` - MCP provides consistent schemas and automatic telemetry.
"""

from __future__ import annotations

from typing import Any, Dict

from amprealize.agent_registry_contracts import (
    CreateAgentRequest,
    DeprecateAgentRequest,
    ListAgentsRequest,
    PublishAgentRequest,
    SearchAgentsRequest,
    UpdateAgentRequest,
)
from amprealize.agent_registry_service import (
    Actor,
    AgentRegistryService,
)


# ==============================================================================
# Handler Functions
# ==============================================================================


async def handle_create_agent(
    service: AgentRegistryService,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Create a new agent.

    Required params:
        - name: Agent display name
        - description: Brief description
        - mission: Mission statement
        - role_alignment: STRATEGIST | TEACHER | STUDENT | MULTI_ROLE
        - user_id: User creating the agent (becomes actor)

    Optional params:
        - slug: URL-safe identifier (auto-generated if not provided)
        - capabilities: List of capability tags
        - default_behaviors: List of behavior IDs
        - playbook_content: Full playbook markdown
        - tags: Searchable tags
        - visibility: PRIVATE | ORGANIZATION | PUBLIC (default: PRIVATE)
        - org_id: Organization ID for multi-tenant
    """
    # Build actor from user_id
    actor = Actor(
        id=params.get("user_id", "anonymous"),
        role=params.get("role", "user"),
        surface=params.get("surface", "mcp"),
    )

    # Build request from params
    request = CreateAgentRequest(
        name=params["name"],
        slug=params.get("slug", ""),  # Will be auto-generated if empty
        description=params.get("description", ""),
        mission=params.get("mission", ""),
        role_alignment=params.get("role_alignment", "STUDENT"),
        capabilities=params.get("capabilities", []),
        default_behaviors=params.get("default_behaviors", []),
        playbook_content=params.get("playbook_content", ""),
        tags=params.get("tags", []),
        visibility=params.get("visibility", "PRIVATE"),
        metadata=params.get("metadata", {}),
    )

    org_id = params.get("org_id")

    try:
        agent = service.create_agent(request, actor, org_id=org_id)
        return {
            "success": True,
            "agent": agent.to_dict(),
            "message": f"Agent '{params['name']}' created successfully",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "agent": None,
        }


async def handle_get_agent(
    service: AgentRegistryService,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Get agent details by ID.

    Required params:
        - agent_id: Agent ID to retrieve

    Optional params:
        - version: Specific version to return
    """
    agent_id = params["agent_id"]
    version = params.get("version")

    try:
        result = service.get_agent(agent_id=agent_id, version=version)
        return {
            "success": True,
            "agent": result.get("agent"),
            "versions": result.get("versions", []),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "agent": None,
            "versions": [],
        }


async def handle_list_agents(
    service: AgentRegistryService,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """List agents with optional filters.

    Optional params:
        - status: DRAFT | ACTIVE | DEPRECATED
        - visibility: PRIVATE | ORGANIZATION | PUBLIC
        - role_alignment: STRATEGIST | TEACHER | STUDENT | MULTI_ROLE
        - owner_id: Filter by owner
        - include_builtin: Include system agents (default: True)
        - limit: Max results (default: 50)
        - org_id: Organization ID for multi-tenant
    """
    request = ListAgentsRequest(
        status=params.get("status"),
        visibility=params.get("visibility"),
        role_alignment=params.get("role_alignment"),
        owner_id=params.get("owner_id"),
        include_builtin=params.get("include_builtin", True),
        limit=params.get("limit", 50),
        org_id=params.get("org_id"),
    )

    org_id = params.get("org_id")

    try:
        agents = service.list_agents(request, org_id=org_id)
        return {
            "success": True,
            "agents": agents,
            "count": len(agents),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "agents": [],
            "count": 0,
        }


async def handle_update_agent(
    service: AgentRegistryService,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Update an existing agent's metadata.

    Required params:
        - agent_id: Agent to update
        - user_id: User performing update (becomes actor)

    Optional params:
        - name: New name
        - description: New description
        - tags: New tags
        - visibility: New visibility level
    """
    actor = Actor(
        id=params.get("user_id", "anonymous"),
        role=params.get("role", "user"),
        surface=params.get("surface", "mcp"),
    )

    request = UpdateAgentRequest(
        agent_id=params["agent_id"],
        version=params.get("version", "1.0.0"),
        name=params.get("name"),
        description=params.get("description"),
        tags=params.get("tags"),
        visibility=params.get("visibility"),
    )

    try:
        agent = service.update_agent(request, actor)
        return {
            "success": True,
            "agent": agent.to_dict(),
            "message": "Agent updated successfully",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "agent": None,
        }


async def handle_deprecate_agent(
    service: AgentRegistryService,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Deprecate an agent version.

    Required params:
        - agent_id: Agent to deprecate
        - version: Version to deprecate
        - effective_to: ISO timestamp when deprecation takes effect
        - user_id: User performing deprecation (becomes actor)

    Optional params:
        - successor_agent_id: Agent that replaces this one
    """
    actor = Actor(
        id=params.get("user_id", "anonymous"),
        role=params.get("role", "user"),
        surface=params.get("surface", "mcp"),
    )

    # For simple deprecate, we use the current timestamp
    from amprealize.agent_registry_service import utc_now_iso

    request = DeprecateAgentRequest(
        agent_id=params["agent_id"],
        version=params.get("version", "1.0.0"),
        effective_to=params.get("effective_to", utc_now_iso()),
        successor_agent_id=params.get("successor_agent_id"),
    )

    try:
        result = service.deprecate_agent(request, actor)
        return {
            "success": True,
            "agent": result.to_dict(),
            "message": f"Agent {params['agent_id']} deprecated",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


async def handle_publish_agent(
    service: AgentRegistryService,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Publish an agent version.

    Required params:
        - agent_id: Agent to publish
        - user_id: User publishing (becomes actor)

    Optional params:
        - version: Version to publish (default: 1.0.0)
        - visibility: Target visibility (default: PUBLIC)
        - effective_from: When publication takes effect
    """
    actor = Actor(
        id=params.get("user_id", "anonymous"),
        role=params.get("role", "user"),
        surface=params.get("surface", "mcp"),
    )

    request = PublishAgentRequest(
        agent_id=params["agent_id"],
        version=params.get("version", "1.0.0"),
        visibility=params.get("visibility", "PUBLIC"),
        effective_from=params.get("effective_from"),
    )

    try:
        result = service.publish_agent(request, actor)
        # publish_agent returns an Agent object, not a dict
        return {
            "success": True,
            "agent": result.to_dict(),
            "version": request.version,
            "message": f"Agent {params['agent_id']} published",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


async def handle_search_agents(
    service: AgentRegistryService,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Search agents by query and filters.

    Optional params:
        - query: Text search in name/description/mission
        - tags: Filter by tags
        - role_alignment: Filter by role
        - visibility: Filter by visibility
        - status: Filter by status
        - owner_id: Filter by owner
        - include_builtin: Include system agents (default: True)
        - limit: Max results (default: 25)
        - org_id: Organization ID for multi-tenant
    """
    actor = None
    if params.get("user_id"):
        actor = Actor(
            id=params["user_id"],
            role=params.get("role", "user"),
            surface=params.get("surface", "mcp"),
        )

    request = SearchAgentsRequest(
        query=params.get("query"),
        tags=params.get("tags"),
        role_alignment=params.get("role_alignment"),
        visibility=params.get("visibility"),
        status=params.get("status"),
        owner_id=params.get("owner_id"),
        include_builtin=params.get("include_builtin", True),
        limit=params.get("limit", 25),
        org_id=params.get("org_id"),
    )

    try:
        results = service.search_agents(request, actor)
        return {
            "success": True,
            "results": [r.to_dict() for r in results],
            "count": len(results),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "results": [],
            "count": 0,
        }


async def handle_bootstrap_agents(
    service: AgentRegistryService,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Bootstrap agents from playbook files.

    Optional params:
        - user_id: User performing bootstrap (becomes actor)
        - force: If True, updates existing builtin agents
    """
    actor = Actor(
        id=params.get("user_id", "system"),
        role=params.get("role", "admin"),
        surface=params.get("surface", "mcp"),
    )

    force = params.get("force", False)

    try:
        results = service.bootstrap_from_playbooks(
            actor=actor,
            force=force,
        )
        return {
            "success": True,
            "bootstrapped": results.get("created", []),
            "updated": results.get("updated", []),
            "skipped": results.get("skipped", []),
            "message": f"Bootstrap complete: {len(results.get('created', []))} created, {len(results.get('updated', []))} updated",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "bootstrapped": [],
            "updated": [],
            "skipped": [],
        }


# ==============================================================================
# Handler Registry
# ==============================================================================


AGENT_REGISTRY_HANDLERS: Dict[str, Any] = {
    "agentRegistry.create": handle_create_agent,
    "agentRegistry.get": handle_get_agent,
    "agentRegistry.list": handle_list_agents,
    "agentRegistry.update": handle_update_agent,
    "agentRegistry.deprecate": handle_deprecate_agent,
    "agentRegistry.publish": handle_publish_agent,
    "agentRegistry.search": handle_search_agents,
    "agentRegistry.bootstrap": handle_bootstrap_agents,
}
