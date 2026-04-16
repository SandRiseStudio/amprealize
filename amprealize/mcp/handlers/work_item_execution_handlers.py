"""MCP tool handlers for Work Item Execution.

Provides handlers for executing work items through the GEP (Amprealize execution protocol).
Following `behavior_prefer_mcp_tools` - MCP provides consistent schemas and automatic telemetry.

See WORK_ITEM_EXECUTION_PLAN.md for full specification.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from ...work_item_execution_service import (
    WorkItemExecutionService,
    WorkItemExecutionError,
    WorkItemNotAssignedError,
    AgentNotFoundError,
    ExecutionAlreadyActiveError,
    ModelNotAvailableError,
    InternetAccessDeniedError,
    ExecutionSurfaceRestrictedError,
)
from ...work_item_execution_contracts import (
    ExecuteWorkItemRequest,
    ExecuteWorkItemResponse,
    ExecutionStatusResponse,
    ExecutionState,
    GEPPhase,
)
from ...services.board_service import Actor, BoardService


# ==============================================================================
# Serialization Helpers
# ==============================================================================


def _serialize_value(value: Any) -> Any:
    """Recursively serialize values for JSON output."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, 'value'):  # Enum
        return value.value
    if hasattr(value, 'model_dump'):  # Pydantic model
        return {k: _serialize_value(v) for k, v in value.model_dump().items()}
    if hasattr(value, '__dataclass_fields__'):  # Dataclass
        import dataclasses
        return {k: _serialize_value(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_value(v) for v in value]
    return str(value)


def _response_to_dict(response: Any) -> Dict[str, Any]:
    """Convert response object to dict with serialized values."""
    if hasattr(response, 'model_dump'):
        result = response.model_dump()
    elif hasattr(response, '__dataclass_fields__'):
        import dataclasses
        result = dataclasses.asdict(response)
    else:
        result = response
    return {k: _serialize_value(v) for k, v in result.items()}


def _get_actor(arguments: Dict[str, Any]) -> Actor:
    """Extract actor from arguments or create default."""
    user_id = arguments.get("user_id", "mcp-user")
    role = arguments.get("actor_role", "user")
    surface = arguments.get("actor_surface", "mcp")
    return Actor(id=user_id, role=role, surface=surface)


# ==============================================================================
# Tool Definitions
# ==============================================================================


WORK_ITEM_EXECUTION_TOOLS = [
    {
        "name": "workItems.execute",
        "description": "Execute a work item using the assigned agent. Starts the GEP (Amprealize execution protocol) loop.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "work_item_id": {
                    "type": "string",
                    "description": "ID or display ID (e.g. 'myproject-42') of the work item to execute",
                },
                "org_id": {
                    "type": "string",
                    "description": "Organization ID (optional)",
                },
                "project_id": {
                    "type": "string",
                    "description": "Project ID",
                },
                "agent_id": {
                    "type": "string",
                    "description": "Optional agent ID override. If not provided, uses the assigned agent.",
                },
                "idempotency_key": {
                    "type": "string",
                    "description": "Optional idempotency key to prevent duplicate executions",
                },
                "model_override": {
                    "type": "string",
                    "description": "Optional model ID to override agent's default model",
                },
                "user_id": {
                    "type": "string",
                    "description": "User ID initiating the execution",
                },
                "actor_surface": {
                    "type": "string",
                    "description": "Surface initiating execution (cli, vscode, web, api, mcp). Defaults to 'mcp'. Local execution modes require local-capable surfaces.",
                    "enum": ["cli", "vscode", "web", "api", "mcp", "codespaces", "gitpod"],
                },
                "execution_mode": {
                    "type": "string",
                    "description": "Agent execution mode: 'gep' (full 8-phase protocol, default) or 'session' (lightweight 3-phase: plan → execute → complete).",
                    "enum": ["gep", "session"],
                },
            },
            "required": ["work_item_id", "project_id"],
        },
    },
    {
        "name": "workItems.executionStatus",
        "description": "Get the execution status of a work item",
        "inputSchema": {
            "type": "object",
            "properties": {
                "work_item_id": {
                    "type": "string",
                    "description": "ID or display ID (e.g. 'myproject-42') of the work item",
                },
                "org_id": {
                    "type": "string",
                    "description": "Organization ID (optional)",
                },
                "project_id": {
                    "type": "string",
                    "description": "Project ID",
                },
            },
            "required": ["work_item_id", "project_id"],
        },
    },
    {
        "name": "workItems.cancelExecution",
        "description": "Cancel an active work item execution",
        "inputSchema": {
            "type": "object",
            "properties": {
                "work_item_id": {
                    "type": "string",
                    "description": "ID or display ID (e.g. 'myproject-42') of the work item",
                },
                "org_id": {
                    "type": "string",
                    "description": "Organization ID (optional)",
                },
                "project_id": {
                    "type": "string",
                    "description": "Project ID",
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for cancellation",
                },
            },
            "required": ["work_item_id", "project_id"],
        },
    },
    {
        "name": "workItems.provideClarification",
        "description": "Provide a clarification response for a work item awaiting user input",
        "inputSchema": {
            "type": "object",
            "properties": {
                "work_item_id": {
                    "type": "string",
                    "description": "ID or display ID (e.g. 'myproject-42') of the work item",
                },
                "org_id": {
                    "type": "string",
                    "description": "Organization ID (optional)",
                },
                "project_id": {
                    "type": "string",
                    "description": "Project ID",
                },
                "clarification_id": {
                    "type": "string",
                    "description": "ID of the clarification being answered",
                },
                "response": {
                    "type": "string",
                    "description": "The clarification response",
                },
            },
            "required": ["work_item_id", "project_id", "clarification_id", "response"],
        },
    },
    {
        "name": "workItems.listExecutions",
        "description": "List recent executions for a project",
        "inputSchema": {
            "type": "object",
            "properties": {
                "org_id": {
                    "type": "string",
                    "description": "Organization ID (optional)",
                },
                "project_id": {
                    "type": "string",
                    "description": "Project ID",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status (PENDING, RUNNING, PAUSED, COMPLETED, FAILED, CANCELLED)",
                    "enum": ["PENDING", "RUNNING", "PAUSED", "COMPLETED", "FAILED", "CANCELLED"],
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of executions to return (default 20)",
                },
                "offset": {
                    "type": "integer",
                    "description": "Offset for pagination",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "workItems.approveGate",
        "description": (
            "Approve a strict gate on a paused execution and resume the agent. "
            "Required for ARCHITECTING, VERIFYING, and COMPLETING phase gates. "
            "After approval, the execution is re-enqueued and the agent resumes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "work_item_id": {
                    "type": "string",
                    "description": "ID or display ID (e.g. 'myproject-42') of the work item with a paused execution",
                },
                "org_id": {
                    "type": "string",
                    "description": "Organization ID (optional)",
                },
                "project_id": {
                    "type": "string",
                    "description": "Project ID",
                },
                "phase": {
                    "type": "string",
                    "description": "Phase gate to approve (e.g. 'architecting', 'verifying'). If omitted, approves current gate.",
                },
                "notes": {
                    "type": "string",
                    "description": "Approval notes or feedback for the agent",
                },
                "user_id": {
                    "type": "string",
                    "description": "User ID approving the gate",
                },
            },
            "required": ["work_item_id", "project_id"],
        },
    },
]


# ==============================================================================
# Handler Factory
# ==============================================================================


def create_work_item_execution_handlers(
    service: WorkItemExecutionService,
    board_service: Optional[BoardService] = None,
) -> Dict[str, callable]:
    """Create handler functions for work item execution tools.

    Args:
        service: The WorkItemExecutionService instance
        board_service: Optional BoardService for resolving display IDs

    Returns:
        Dict mapping tool names to handler functions
    """

    def _resolve_id(identifier: str, arguments: Dict[str, Any]) -> str:
        """Resolve display ID to internal ID if board_service available."""
        if board_service is None:
            return identifier
        return board_service.resolve_work_item_id(
            identifier,
            org_id=arguments.get("org_id"),
            project_id=arguments.get("project_id"),
        )

    async def handle_execute(arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle workItems.execute tool call."""
        actor = _get_actor(arguments)

        try:
            work_item_id = _resolve_id(arguments["work_item_id"], arguments)

            # Resolve agent execution mode
            agent_exec_mode = None
            exec_mode_str = arguments.get("execution_mode")
            if exec_mode_str:
                from ...work_item_execution_contracts import AgentExecutionMode
                try:
                    agent_exec_mode = AgentExecutionMode(exec_mode_str)
                except ValueError:
                    return {
                        "success": False,
                        "error": "invalid_execution_mode",
                        "message": f"Invalid execution_mode '{exec_mode_str}'. Must be 'gep' or 'session'.",
                    }

            request = ExecuteWorkItemRequest(
                work_item_id=work_item_id,
                user_id=actor.id,
                org_id=arguments.get("org_id"),
                project_id=arguments["project_id"],
                actor_surface=arguments.get("actor_surface", "mcp"),
                model_id=arguments.get("model_override"),
                agent_execution_mode=agent_exec_mode,
                metadata={
                    "idempotency_key": arguments.get("idempotency_key"),
                    "agent_id_override": arguments.get("agent_id"),
                },
            )

            response = await service.execute(request)

            return {
                "success": True,
                "execution": _response_to_dict(response),
            }

        except WorkItemNotAssignedError as e:
            return {
                "success": False,
                "error": "work_item_not_assigned",
                "message": str(e),
            }
        except AgentNotFoundError as e:
            return {
                "success": False,
                "error": "agent_not_found",
                "message": str(e),
            }
        except ExecutionAlreadyActiveError as e:
            return {
                "success": False,
                "error": "execution_already_active",
                "message": str(e),
                "run_id": getattr(e, 'run_id', None),
            }
        except ModelNotAvailableError as e:
            return {
                "success": False,
                "error": "model_not_available",
                "message": str(e),
            }
        except ExecutionSurfaceRestrictedError as e:
            return {
                "success": False,
                "error": "execution_surface_restricted",
                "message": str(e),
                "guidance": e.guidance,
            }
        except InternetAccessDeniedError as e:
            return {
                "success": False,
                "error": "internet_access_denied",
                "message": str(e),
            }
        except WorkItemExecutionError as e:
            return {
                "success": False,
                "error": "execution_error",
                "message": str(e),
            }
        except Exception as e:
            return {
                "success": False,
                "error": "unexpected_error",
                "message": str(e),
            }

    async def handle_execution_status(arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle workItems.executionStatus tool call."""
        try:
            work_item_id = _resolve_id(arguments["work_item_id"], arguments)
            response = await service.get_status(
                work_item_id=work_item_id,
                org_id=arguments.get("org_id"),
                project_id=arguments["project_id"],
            )

            if response is None:
                return {
                    "success": True,
                    "has_execution": False,
                    "status": None,
                }

            return {
                "success": True,
                "has_execution": True,
                "status": _response_to_dict(response),
            }

        except Exception as e:
            return {
                "success": False,
                "error": "unexpected_error",
                "message": str(e),
            }

    async def handle_cancel_execution(arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle workItems.cancelExecution tool call."""
        actor = _get_actor(arguments)

        try:
            work_item_id = _resolve_id(arguments["work_item_id"], arguments)
            success = await service.cancel(
                work_item_id=work_item_id,
                org_id=arguments.get("org_id"),
                project_id=arguments["project_id"],
                reason=arguments.get("reason", "User requested cancellation"),
                actor=actor,
            )

            return {
                "success": success,
                "message": "Execution cancelled" if success else "No active execution found",
            }

        except Exception as e:
            return {
                "success": False,
                "error": "unexpected_error",
                "message": str(e),
            }

    async def handle_provide_clarification(arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle workItems.provideClarification tool call."""
        actor = _get_actor(arguments)

        try:
            work_item_id = _resolve_id(arguments["work_item_id"], arguments)
            # This will be implemented in the service
            # For now, return a placeholder
            success = await service.provide_clarification(
                work_item_id=work_item_id,
                org_id=arguments.get("org_id"),
                project_id=arguments["project_id"],
                clarification_id=arguments["clarification_id"],
                response=arguments["response"],
                actor=actor,
            )

            return {
                "success": success,
                "message": "Clarification provided" if success else "Failed to provide clarification",
            }

        except Exception as e:
            return {
                "success": False,
                "error": "unexpected_error",
                "message": str(e),
            }

    async def handle_list_executions(arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle workItems.listExecutions tool call."""
        try:
            status_filter = None
            if "status" in arguments:
                try:
                    status_filter = ExecutionState(arguments["status"])
                except ValueError:
                    pass

            executions = await service.list_executions(
                org_id=arguments.get("org_id"),
                project_id=arguments["project_id"],
                status=status_filter,
                limit=arguments.get("limit", 20),
                offset=arguments.get("offset", 0),
            )

            return {
                "success": True,
                "executions": [_response_to_dict(e) for e in executions],
                "count": len(executions),
            }

        except Exception as e:
            return {
                "success": False,
                "error": "unexpected_error",
                "message": str(e),
            }

    async def handle_approve_gate(arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle workItems.approveGate tool call."""
        actor = _get_actor(arguments)

        try:
            work_item_id = _resolve_id(arguments["work_item_id"], arguments)
            result = await service.approve_gate(
                work_item_id=work_item_id,
                user_id=actor.id,
                org_id=arguments.get("org_id"),
                project_id=arguments["project_id"],
                phase=arguments.get("phase"),
                notes=arguments.get("notes"),
            )

            return result

        except Exception as e:
            return {
                "success": False,
                "error": "unexpected_error",
                "message": str(e),
            }

    return {
        "workItems.execute": handle_execute,
        "workItems.executionStatus": handle_execution_status,
        "workItems.cancelExecution": handle_cancel_execution,
        "workItems.provideClarification": handle_provide_clarification,
        "workItems.listExecutions": handle_list_executions,
        "workItems.approveGate": handle_approve_gate,
    }


# ==============================================================================
# Tool Registration Helper
# ==============================================================================


def get_work_item_execution_tools() -> List[Dict[str, Any]]:
    """Get the tool definitions for work item execution.

    Returns:
        List of tool definition dicts in MCP format
    """
    return WORK_ITEM_EXECUTION_TOOLS
