"""MCP tool handlers for Agent Registry and Agent Runtime management.

Provides handlers for:
- agentRegistry.*: Agent CRUD operations (create, get, list, update, deprecate)
- agents.*: Runtime operations (activate, pause, disable, status, assign)

Following `behavior_prefer_mcp_tools` - MCP provides consistent schemas and automatic telemetry.
Migrated from orgAgents.* namespace (archived 2026-01-07).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
# NOTE: Agent is a Pydantic model - use .model_dump() not asdict()

from amprealize.multi_tenant.contracts import (
    Agent,
    AgentStatus,
    AgentType,
)


# Marker for handler discovery
_handler_module_stub = True


# ==============================================================================
# Serialization Helpers
# ==============================================================================


def _serialize_value(value: Any) -> Any:
    """Recursively serialize values for JSON output."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, 'value'):  # Enum
        return value.value
    if hasattr(value, 'model_dump'):  # Pydantic model
        return {k: _serialize_value(v) for k, v in value.model_dump().items()}
    if isinstance(value, list):
        return [_serialize_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    return value


def _agent_to_dict(agent: Agent) -> Dict[str, Any]:
    """Convert Agent Pydantic model to serializable dict."""
    return _serialize_value(agent.model_dump())


# ==============================================================================
# Organization Agent Handlers
# ==============================================================================


async def handle_create_agent(
    service: Any,  # OrganizationService or AgentService
    arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Create a new agent in an organization."""
    user_id = arguments["user_id"]
    org_id = arguments["org_id"]
    name = arguments["name"]
    agent_type = AgentType(arguments.get("type", "orchestrator"))
    description = arguments.get("description")
    config = arguments.get("config", {})

    agent = await service.create_agent(
        user_id=user_id,
        org_id=org_id,
        name=name,
        agent_type=agent_type,
        description=description,
        config=config,
    )

    return {
        "success": True,
        "agent": _agent_to_dict(agent),
        "message": f"Agent '{name}' created successfully",
    }


async def handle_get_agent(
    service: Any,
    arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Get agent details by ID."""
    user_id = arguments["user_id"]
    agent_id = arguments["agent_id"]

    agent = await service.get_agent(user_id=user_id, agent_id=agent_id)

    if not agent:
        return {
            "success": False,
            "error": "Agent not found",
            "agent": None,
        }

    return {
        "success": True,
        "agent": _agent_to_dict(agent),
    }


async def handle_list_agents(
    service: Any,
    arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """List agents in an organization or project."""
    user_id = arguments["user_id"]
    org_id = arguments.get("org_id")
    project_id = arguments.get("project_id")
    status = arguments.get("status")
    agent_type = arguments.get("type")
    limit = arguments.get("limit", 50)
    offset = arguments.get("offset", 0)

    if status:
        status = AgentStatus(status)
    if agent_type:
        agent_type = AgentType(agent_type)

    agents = await service.list_agents(
        user_id=user_id,
        org_id=org_id,
        project_id=project_id,
        status=status,
        agent_type=agent_type,
        limit=limit,
        offset=offset,
    )

    return {
        "success": True,
        "agents": [_agent_to_dict(a) for a in agents],
        "count": len(agents),
    }


async def handle_update_agent(
    service: Any,
    arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Update an existing agent."""
    user_id = arguments["user_id"]
    agent_id = arguments["agent_id"]
    name = arguments.get("name")
    description = arguments.get("description")
    config = arguments.get("config")

    agent = await service.update_agent(
        user_id=user_id,
        agent_id=agent_id,
        name=name,
        description=description,
        config=config,
    )

    if not agent:
        return {
            "success": False,
            "error": "Agent not found or access denied",
            "agent": None,
        }

    return {
        "success": True,
        "agent": _agent_to_dict(agent),
        "message": "Agent updated successfully",
    }


async def handle_delete_agent(
    service: Any,
    arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Delete an agent."""
    user_id = arguments["user_id"]
    agent_id = arguments["agent_id"]

    success = await service.delete_agent(user_id=user_id, agent_id=agent_id)

    if not success:
        return {
            "success": False,
            "error": "Agent not found or access denied",
        }

    return {
        "success": True,
        "message": "Agent deleted successfully",
    }


async def handle_pause_agent(
    service: Any,
    arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Pause a running agent."""
    user_id = arguments["user_id"]
    agent_id = arguments["agent_id"]
    reason = arguments.get("reason")

    agent = await service.update_agent_status(
        user_id=user_id,
        agent_id=agent_id,
        status=AgentStatus.PAUSED,
        reason=reason,
    )

    if not agent:
        return {
            "success": False,
            "error": "Agent not found or cannot be paused",
        }

    return {
        "success": True,
        "agent": _agent_to_dict(agent),
        "message": "Agent paused",
    }


async def handle_resume_agent(
    service: Any,
    arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Resume a paused agent."""
    user_id = arguments["user_id"]
    agent_id = arguments["agent_id"]

    agent = await service.update_agent_status(
        user_id=user_id,
        agent_id=agent_id,
        status=AgentStatus.ACTIVE,  # Resume to ACTIVE state (RUNNING doesn't exist)
    )

    if not agent:
        return {
            "success": False,
            "error": "Agent not found or cannot be resumed",
        }

    return {
        "success": True,
        "agent": _agent_to_dict(agent),
        "message": "Agent resumed",
    }


async def handle_stop_agent(
    service: Any,
    arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Stop a running or paused agent."""
    user_id = arguments["user_id"]
    agent_id = arguments["agent_id"]
    reason = arguments.get("reason")

    agent = await service.update_agent_status(
        user_id=user_id,
        agent_id=agent_id,
        status=AgentStatus.DISABLED,  # Use DISABLED (STOPPED doesn't exist)
        reason=reason,
    )

    if not agent:
        return {
            "success": False,
            "error": "Agent not found or cannot be stopped",
        }

    return {
        "success": True,
        "agent": _agent_to_dict(agent),
        "message": "Agent stopped",
    }


async def handle_get_status(
    service: Any,
    arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Get detailed status of an agent including metrics."""
    user_id = arguments["user_id"]
    agent_id = arguments["agent_id"]

    status = await service.get_agent_status(
        user_id=user_id,
        agent_id=agent_id,
    )

    if not status:
        return {
            "success": False,
            "error": "Agent not found",
        }

    return {
        "success": True,
        "status": _serialize_value(status),
    }


async def handle_assign_to_project(
    service: Any,
    arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Assign an agent to a project."""
    user_id = arguments["user_id"]
    agent_id = arguments["agent_id"]
    project_id = arguments["project_id"]

    success = await service.assign_agent_to_project(
        user_id=user_id,
        agent_id=agent_id,
        project_id=project_id,
    )

    if not success:
        return {
            "success": False,
            "error": "Failed to assign agent to project",
        }

    return {
        "success": True,
        "message": f"Agent assigned to project {project_id}",
    }


async def handle_remove_from_project(
    service: Any,
    arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Remove an agent from a project."""
    user_id = arguments["user_id"]
    agent_id = arguments["agent_id"]
    project_id = arguments["project_id"]

    success = await service.remove_agent_from_project(
        user_id=user_id,
        agent_id=agent_id,
        project_id=project_id,
    )

    if not success:
        return {
            "success": False,
            "error": "Failed to remove agent from project",
        }

    return {
        "success": True,
        "message": f"Agent removed from project {project_id}",
    }


# ==============================================================================
# Handler Registry
# ==============================================================================


# Agent Registry handlers (CRUD operations)
AGENT_REGISTRY_HANDLERS: Dict[str, Any] = {
    "agentRegistry.create": handle_create_agent,
    "agentRegistry.get": handle_get_agent,
    "agentRegistry.list": handle_list_agents,
    "agentRegistry.update": handle_update_agent,
    "agentRegistry.deprecate": handle_delete_agent,  # Semantic match: delete → deprecate
}

# Agent Runtime handlers (orchestration operations)
AGENT_RUNTIME_HANDLERS: Dict[str, Any] = {
    "agents.pause": handle_pause_agent,
    "agents.activate": handle_resume_agent,  # Resume → activate
    "agents.disable": handle_stop_agent,     # Stop → disable
    "agents.status": handle_get_status,      # getStatus → status
    "agents.assign": handle_assign_to_project,  # Project assignment
}

# Legacy handlers (DEPRECATED - archived 2026-01-07)
# Kept for backwards compatibility during migration period
ORG_AGENT_HANDLERS: Dict[str, Any] = {
    "orgAgents.create": handle_create_agent,
    "orgAgents.get": handle_get_agent,
    "orgAgents.list": handle_list_agents,
    "orgAgents.update": handle_update_agent,
    "orgAgents.delete": handle_delete_agent,
    "orgAgents.pause": handle_pause_agent,
    "orgAgents.resume": handle_resume_agent,
    "orgAgents.stop": handle_stop_agent,
    "orgAgents.getStatus": handle_get_status,
    "orgAgents.assignToProject": handle_assign_to_project,
    "orgAgents.removeFromProject": handle_remove_from_project,
}
