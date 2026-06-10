"""Compatibility adapter from legacy work item execution APIs to ExecutionGateway.

The REST and MCP execution surfaces currently depend on the
WorkItemExecutionService shape. This adapter lets those surfaces call the
gateway-backed start path while preserving response objects and delegating
non-start operations during migration.
"""

from __future__ import annotations

from typing import Any, Optional

from .execution_gateway_contracts import (
    ExecutionIntent,
    ExecutionRequest,
    NewExecutionMode,
    OutputTarget,
    SourceType,
)
from .execution_workspace_contracts import InvalidExecutionWorkspaceKindError, parse_execution_workspace_kind
from .work_item_execution_contracts import (
    ExecuteWorkItemRequest,
    ExecuteWorkItemResponse,
    ExecutionState,
)
from .work_item_execution_service import WorkItemExecutionError


def _enum_from_metadata(enum_type: Any, value: Optional[str]) -> Any:
    if value is None:
        return None
    return enum_type(value)


class GatewayWorkItemExecutionAdapter:
    """Expose a WorkItemExecutionService-compatible start method backed by the gateway."""

    def __init__(
        self,
        *,
        gateway: Any,
        legacy_service: Optional[Any] = None,
    ) -> None:
        self._gateway = gateway
        self._legacy = legacy_service

    async def execute(self, request: ExecuteWorkItemRequest) -> ExecuteWorkItemResponse:
        gateway_request = self.to_gateway_request(request)
        result = await self._gateway.execute(gateway_request)

        if not result.success:
            raise WorkItemExecutionError(result.error or result.message or "Gateway execution failed")

        compatibility = result.compatibility
        return ExecuteWorkItemResponse(
            run_id=result.run_id or "",
            cycle_id=result.cycle_id or "",
            work_item_id=compatibility.get("work_item_id", request.work_item_id),
            agent_id=compatibility.get("agent_id", request.metadata.get("agent_id_override", "")),
            model_id=compatibility.get("model_id", request.model_id or ""),
            status=ExecutionState(compatibility.get("status", ExecutionState.PENDING.value)),
            phase=compatibility.get("phase", "planning"),
            created_at=compatibility.get("created_at", gateway_request.created_at),
            message=result.message,
        )

    def to_gateway_request(self, request: ExecuteWorkItemRequest) -> ExecutionRequest:
        metadata = dict(request.metadata)
        intent = _enum_from_metadata(ExecutionIntent, metadata.get("intent")) or ExecutionIntent.EXECUTE

        try:
            workspace_kind = parse_execution_workspace_kind(
                metadata.get("execution_workspace_kind")
            ).value
        except InvalidExecutionWorkspaceKindError as e:
            raise WorkItemExecutionError(str(e)) from e
        metadata["execution_workspace_kind"] = workspace_kind

        return ExecutionRequest(
            work_item_id=request.work_item_id,
            project_id=request.project_id or "",
            org_id=request.org_id,
            user_id=request.user_id,
            surface=request.actor_surface,
            conversation_id=metadata.get("conversation_id"),
            message_id=metadata.get("message_id"),
            source_type=_enum_from_metadata(SourceType, metadata.get("source_type")),
            source_url=metadata.get("source_url"),
            source_ref=metadata.get("source_ref"),
            mode_override=_enum_from_metadata(NewExecutionMode, metadata.get("mode_override")),
            output_target_override=_enum_from_metadata(OutputTarget, metadata.get("output_target")),
            model_override=request.model_id,
            agent_id_override=metadata.get("agent_id_override"),
            agent_execution_mode=request.agent_execution_mode,
            intent=intent,
            idempotency_key=metadata.get("idempotency_key"),
            policy_context=metadata.get("policy_context") or {},
            risk_classification=metadata.get("risk_classification"),
            requires_approval=bool(metadata.get("requires_approval", False)),
            approved_by=metadata.get("approved_by"),
            plan_artifact_id=metadata.get("plan_artifact_id"),
            callback_url=metadata.get("callback_url"),
            metadata=metadata,
            execution_workspace_kind=workspace_kind,
        )

    def _require_legacy(self) -> Any:
        if self._legacy is None:
            raise WorkItemExecutionError("Operation is not available without a legacy execution service")
        return self._legacy

    def get_status(self, *args: Any, **kwargs: Any) -> Any:
        return self._require_legacy().get_status(*args, **kwargs)

    async def cancel(self, *args: Any, **kwargs: Any) -> Any:
        # Legacy WorkItemExecutionService.cancel is synchronous; do not await its return value.
        return self._require_legacy().cancel(*args, **kwargs)

    async def provide_clarification(self, *args: Any, **kwargs: Any) -> Any:
        return await self._require_legacy().provide_clarification(*args, **kwargs)

    async def list_executions(self, *args: Any, **kwargs: Any) -> Any:
        return await self._require_legacy().list_executions(*args, **kwargs)

    async def approve_gate(self, *args: Any, **kwargs: Any) -> Any:
        return await self._require_legacy().approve_gate(*args, **kwargs)
