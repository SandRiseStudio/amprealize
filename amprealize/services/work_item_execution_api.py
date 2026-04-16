"""FastAPI router for Work Item Execution.

Provides REST endpoints for executing work items through the GEP
(Amprealize execution protocol).

Endpoints:
    # Execution
    POST   /v1/work-items/{item_id}:execute     - Start execution
    GET    /v1/work-items/{item_id}/execution   - Get execution status
    POST   /v1/work-items/{item_id}:cancel      - Cancel execution
    POST   /v1/work-items/{item_id}:clarify     - Provide clarification

    # Execution History
    GET    /v1/executions                       - List executions
    GET    /v1/executions/{execution_id}        - Get execution details
    GET    /v1/executions/{execution_id}/steps  - Get execution steps

See WORK_ITEM_EXECUTION_PLAN.md for full specification.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from ..work_item_execution_service import (
    WorkItemExecutionService,
    WorkItemExecutionError,
    WorkItemNotAssignedError,
    AgentNotFoundError,
    ExecutionAlreadyActiveError,
    ModelNotAvailableError,
    InternetAccessDeniedError,
)
from ..work_item_execution_contracts import (
    ExecuteWorkItemRequest,
    ExecutionState,
)
from ..services.board_service import Actor


logger = logging.getLogger(__name__)


# ==============================================================================
# Request/Response Models
# ==============================================================================


class ExecuteRequest(BaseModel):
    """Request to execute a work item."""
    agent_id: Optional[str] = Field(
        None,
        description="Optional agent ID override. If not provided, uses the assigned agent.",
    )
    idempotency_key: Optional[str] = Field(
        None,
        description="Optional idempotency key to prevent duplicate executions",
    )
    model_override: Optional[str] = Field(
        None,
        description="Optional model ID to override agent's default model",
    )
    execution_mode: Optional[str] = Field(
        None,
        description=(
            "Agent execution mode: 'gep' (full 8-phase protocol, default) "
            "or 'session' (lightweight 3-phase: plan → execute → complete)."
        ),
    )
    callback_url: Optional[str] = Field(
        None,
        description=(
            "Webhook URL to receive gate events (gate.waiting, "
            "gate.clarification_needed, run.completed, run.failed). "
            "The URL will receive POST requests with HMAC-signed payloads."
        ),
    )


class ExecuteResponse(BaseModel):
    """Response from starting execution."""
    success: bool
    run_id: Optional[str] = None
    task_cycle_id: Optional[str] = None
    status: Optional[str] = None
    message: Optional[str] = None


class ExecutionStatusResponse(BaseModel):
    """Current execution status."""
    has_execution: bool
    run_id: Optional[str] = None
    task_cycle_id: Optional[str] = None
    state: Optional[str] = None
    phase: Optional[str] = None
    started_at: Optional[str] = None
    progress_pct: Optional[float] = None
    current_step: Optional[str] = None
    total_tokens: Optional[int] = None
    total_cost_usd: Optional[float] = None
    pending_clarifications: Optional[List[Dict[str, Any]]] = None


class CancelRequest(BaseModel):
    """Request to cancel execution."""
    reason: Optional[str] = Field(
        "User requested cancellation",
        description="Reason for cancellation",
    )


class CancelResponse(BaseModel):
    """Response from cancelling execution."""
    success: bool
    message: str


class ClarifyRequest(BaseModel):
    """Request to provide clarification."""
    clarification_id: str = Field(..., description="ID of the clarification being answered")
    response: str = Field(..., description="The clarification response")


class ClarifyResponse(BaseModel):
    """Response from providing clarification."""
    success: bool
    message: str


class ApproveGateRequest(BaseModel):
    """Request to approve a strict gate and resume execution."""
    phase: Optional[str] = Field(
        None,
        description="Phase gate to approve (e.g. 'architecting', 'verifying'). If omitted, approves current gate.",
    )
    notes: Optional[str] = Field(
        None,
        description="Approval notes or feedback for the agent.",
    )


class ApproveGateResponse(BaseModel):
    """Response from approving a gate."""
    success: bool
    message: str
    run_id: Optional[str] = None
    resumed: bool = False


class ExecutionListItem(BaseModel):
    """Summary of an execution for list responses."""
    run_id: str
    work_item_id: str
    work_item_title: Optional[str] = None
    agent_id: str
    state: str
    phase: Optional[str] = None
    started_at: str
    completed_at: Optional[str] = None
    progress_pct: float


class ExecutionListResponse(BaseModel):
    """Response containing list of executions."""
    executions: List[ExecutionListItem]
    total: int
    offset: int
    limit: int


class ExecutionStepResponse(BaseModel):
    """An execution step."""
    step_id: str
    phase: str
    step_type: str
    started_at: str
    completed_at: Optional[str] = None
    input_tokens: int
    output_tokens: int
    tool_calls: int
    content_preview: Optional[str] = None
    content_full: Optional[str] = None  # Full content for detailed view
    tool_names: Optional[List[str]] = None  # Names of tools called
    model_id: Optional[str] = None  # Model used for LLM calls


class ExecutionStepsResponse(BaseModel):
    """Response containing execution steps."""
    steps: List[ExecutionStepResponse]
    total: int


# ==============================================================================
# Router Factory
# ==============================================================================


def create_work_item_execution_routes(
    service: WorkItemExecutionService,
) -> APIRouter:
    """Create FastAPI router for work item execution.

    Args:
        service: The WorkItemExecutionService instance

    Returns:
        APIRouter with all execution endpoints
    """

    router = APIRouter(tags=["work-item-execution"])

    def _get_actor(request: Request) -> Actor:
        """Extract actor from request context."""
        user_id = getattr(request.state, "user_id", None) or "api-user"
        role = getattr(request.state, "role", "user")
        return Actor(id=user_id, role=role, surface="api")

    # ==========================================================================
    # Work Item Execution Endpoints
    # ==========================================================================

    @router.post(
        "/v1/work-items/{item_id}:execute",
        response_model=ExecuteResponse,
        status_code=status.HTTP_202_ACCEPTED,
        summary="Execute a work item",
        description="Start execution of a work item using its assigned agent.",
    )
    async def execute_work_item(
        item_id: str,
        request: Request,
        body: ExecuteRequest,
        org_id: Optional[str] = Query(None, description="Organization ID"),
        project_id: str = Query(..., description="Project ID"),
    ) -> ExecuteResponse:
        """Start execution of a work item."""
        actor = _get_actor(request)

        try:
            # Resolve execution mode
            agent_exec_mode = None
            if body.execution_mode:
                from ..work_item_execution_contracts import AgentExecutionMode
                try:
                    agent_exec_mode = AgentExecutionMode(body.execution_mode)
                except ValueError:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={
                            "error": "invalid_execution_mode",
                            "message": f"Invalid execution_mode '{body.execution_mode}'. Must be 'gep' or 'session'.",
                        },
                    )

            exec_request = ExecuteWorkItemRequest(
                work_item_id=item_id,
                user_id=actor.id,
                org_id=org_id,
                project_id=project_id,
                model_id=body.model_override,
                agent_execution_mode=agent_exec_mode,
                metadata={
                    "callback_url": body.callback_url,
                } if body.callback_url else {},
            )

            response = await service.execute(exec_request)

            return ExecuteResponse(
                success=True,
                run_id=response.run_id,
                task_cycle_id=response.cycle_id,
                status=response.status.value if response.status else None,
            )

        except WorkItemNotAssignedError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "work_item_not_assigned",
                    "message": str(e),
                },
            )
        except AgentNotFoundError as e:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "agent_not_found",
                    "message": str(e),
                },
            )
        except ExecutionAlreadyActiveError as e:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "execution_already_active",
                    "message": str(e),
                },
            )
        except ModelNotAvailableError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "model_not_available",
                    "message": str(e),
                },
            )
        except InternetAccessDeniedError as e:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "internet_access_denied",
                    "message": str(e),
                },
            )
        except WorkItemExecutionError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": "execution_error",
                    "message": str(e),
                },
            )

    @router.get(
        "/v1/work-items/{item_id}/execution",
        response_model=ExecutionStatusResponse,
        summary="Get execution status",
        description="Get the current execution status of a work item.",
    )
    async def get_execution_status(
        item_id: str,
        org_id: Optional[str] = Query(None, description="Organization ID"),
        project_id: str = Query(..., description="Project ID"),
    ) -> ExecutionStatusResponse:
        """Get execution status of a work item."""
        try:
            # get_status is synchronous
            response = service.get_status(
                work_item_id=item_id,
                org_id=org_id,
            )

            if response is None:
                return ExecutionStatusResponse(has_execution=False)

            return ExecutionStatusResponse(
                has_execution=True,
                run_id=response.run_id,
                task_cycle_id=response.cycle_id,
                state=response.status.value if response.status else None,
                phase=response.phase if response.phase else None,
                started_at=response.started_at,
                progress_pct=response.progress_pct,
                current_step=response.current_step,
                total_tokens=None,  # Not in current contract
                total_cost_usd=None,  # Not in current contract
                pending_clarifications=response.pending_clarifications,
            )

        except Exception as e:
            logger.exception(f"Error getting execution status: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": "unexpected_error", "message": str(e)},
            )

    @router.post(
        "/v1/work-items/{item_id}:cancel",
        response_model=CancelResponse,
        summary="Cancel execution",
        description="Cancel an active work item execution.",
    )
    def cancel_execution(
        item_id: str,
        request: Request,
        body: CancelRequest,
        org_id: Optional[str] = Query(None, description="Organization ID"),
    ) -> CancelResponse:
        """Cancel execution of a work item."""
        actor = _get_actor(request)
        user_id = actor.id

        try:
            success = service.cancel(
                work_item_id=item_id,
                user_id=user_id,
                org_id=org_id,
                reason=body.reason or "User requested cancellation",
            )

            return CancelResponse(
                success=success,
                message="Execution cancelled" if success else "No active execution found",
            )

        except Exception as e:
            logger.exception(f"Error cancelling execution: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": "unexpected_error", "message": str(e)},
            )

    @router.post(
        "/v1/work-items/{item_id}:clarify",
        response_model=ClarifyResponse,
        summary="Provide clarification",
        description="Provide a clarification response for a work item awaiting user input.",
    )
    async def provide_clarification(
        item_id: str,
        request: Request,
        body: ClarifyRequest,
        org_id: Optional[str] = Query(None, description="Organization ID"),
    ) -> ClarifyResponse:
        """Provide clarification for a work item."""
        actor = _get_actor(request)

        try:
            success = service.provide_clarification(
                work_item_id=item_id,
                clarification_id=body.clarification_id,
                response=body.response,
                user_id=actor.id,
                org_id=org_id,
            )

            if success:
                return ClarifyResponse(
                    success=True,
                    message="Clarification provided successfully",
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": "clarification_failed",
                        "message": "Could not provide clarification. Execution may not be waiting for input.",
                    },
                )
        except Exception as e:
            logger.exception(f"Error providing clarification for {item_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": "internal_error", "message": str(e)},
            )

    # ==========================================================================
    # Gate Approval Endpoint
    # ==========================================================================

    @router.post(
        "/v1/work-items/{item_id}:approve-gate",
        response_model=ApproveGateResponse,
        summary="Approve a strict gate",
        description=(
            "Approve a strict gate on a paused execution and resume the agent. "
            "Required for ARCHITECTING, VERIFYING, and COMPLETING phases."
        ),
    )
    async def approve_gate(
        item_id: str,
        request: Request,
        body: ApproveGateRequest,
        org_id: Optional[str] = Query(None, description="Organization ID"),
        project_id: str = Query(..., description="Project ID"),
    ) -> ApproveGateResponse:
        """Approve a strict gate and resume execution."""
        actor = _get_actor(request)

        try:
            result = await service.approve_gate(
                work_item_id=item_id,
                user_id=actor.id,
                org_id=org_id,
                project_id=project_id,
                phase=body.phase,
                notes=body.notes,
            )

            return ApproveGateResponse(
                success=result.get("success", False),
                message=result.get("message", "Gate approved"),
                run_id=result.get("run_id"),
                resumed=result.get("resumed", False),
            )

        except WorkItemExecutionError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "gate_approval_failed",
                    "message": str(e),
                },
            )
        except Exception as e:
            logger.exception(f"Error approving gate for {item_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": "internal_error", "message": str(e)},
            )

    # ==========================================================================
    # Execution List/History Endpoints
    # ==========================================================================

    @router.get(
        "/v1/executions",
        response_model=ExecutionListResponse,
        summary="List executions",
        description="List recent executions for a project.",
    )
    async def list_executions(
        org_id: Optional[str] = Query(None, description="Organization ID"),
        project_id: str = Query(..., description="Project ID"),
        status_filter: Optional[str] = Query(
            None,
            alias="status",
            description="Filter by status",
        ),
        limit: int = Query(20, ge=1, le=200, description="Maximum results"),
        offset: int = Query(0, ge=0, description="Offset for pagination"),
    ) -> ExecutionListResponse:
        """List executions for a project."""
        try:
            # Convert status string to ExecutionState if provided
            status_enum = None
            if status_filter:
                try:
                    status_enum = ExecutionState(status_filter)
                except ValueError:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={
                            "error": "invalid_status",
                            "message": f"Invalid status '{status_filter}'. Valid values: {[s.value for s in ExecutionState]}",
                        },
                    )

            executions = service.list_executions(
                org_id=org_id,
                project_id=project_id,
                status=status_enum,
                limit=limit,
                offset=offset,
            )

            # Convert to API response format
            items = []
            for ex in executions:
                items.append(ExecutionListItem(
                    run_id=ex.run_id,
                    work_item_id=ex.work_item_id,
                    work_item_title=None,  # TODO: fetch from board service
                    agent_id=ex.model_id or "",
                    state=ex.status.value if ex.status else "unknown",
                    phase=ex.phase,
                    started_at=ex.started_at or "",
                    completed_at=ex.completed_at,
                    progress_pct=ex.progress_pct or 0.0,
                ))

            return ExecutionListResponse(
                executions=items,
                total=len(items),  # TODO: get actual total from service
                offset=offset,
                limit=limit,
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"Error listing executions: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": "internal_error", "message": str(e)},
            )

    @router.get(
        "/v1/executions/{execution_id}",
        response_model=ExecutionStatusResponse,
        summary="Get execution details",
        description="Get detailed information about a specific execution.",
    )
    async def get_execution_details(
        execution_id: str,
        org_id: Optional[str] = Query(None, description="Organization ID"),
    ) -> ExecutionStatusResponse:
        """Get execution details by run ID."""
        try:
            execution = service.get_execution_by_run_id(
                run_id=execution_id,
                org_id=org_id,
            )

            if not execution:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "error": "not_found",
                        "message": f"Execution {execution_id} not found",
                    },
                )

            return ExecutionStatusResponse(
                has_execution=True,
                run_id=execution.run_id,
                task_cycle_id=execution.cycle_id,
                state=execution.status.value if execution.status else None,
                phase=execution.phase,
                started_at=execution.started_at,
                progress_pct=execution.progress_pct,
                current_step=execution.current_step,
                total_tokens=None,  # TODO: calculate from steps
                total_cost_usd=None,  # TODO: calculate from steps
                pending_clarifications=None,
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"Error getting execution {execution_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": "internal_error", "message": str(e)},
            )

    @router.get(
        "/v1/executions/{execution_id}/steps",
        response_model=ExecutionStepsResponse,
        summary="Get execution steps",
        description="Get the execution steps for a specific run.",
    )
    async def get_execution_steps(
        execution_id: str,
        org_id: Optional[str] = Query(None, description="Organization ID"),
        limit: int = Query(50, ge=1, le=200, description="Maximum results"),
        offset: int = Query(0, ge=0, description="Offset for pagination"),
    ) -> ExecutionStepsResponse:
        """Get execution steps for a run."""
        try:
            steps_data = service.get_execution_steps(
                run_id=execution_id,
                org_id=org_id,
                limit=limit,
                offset=offset,
            )

            # Convert to API response format
            steps = []
            for step in steps_data:
                steps.append(ExecutionStepResponse(
                    step_id=step["step_id"],
                    phase=step.get("phase", "unknown"),
                    step_type=step.get("step_type", "unknown"),
                    started_at=step.get("started_at", ""),
                    completed_at=step.get("completed_at"),
                    input_tokens=step.get("input_tokens", 0),
                    output_tokens=step.get("output_tokens", 0),
                    tool_calls=step.get("tool_calls", 0),
                    content_preview=step.get("content_preview"),
                    content_full=step.get("content_full"),
                    tool_names=step.get("tool_names"),
                    model_id=step.get("model_id"),
                ))

            return ExecutionStepsResponse(
                steps=steps,
                total=len(steps),  # TODO: get actual total from service
            )
        except Exception as e:
            logger.exception(f"Error getting steps for {execution_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": "internal_error", "message": str(e)},
            )

    return router
