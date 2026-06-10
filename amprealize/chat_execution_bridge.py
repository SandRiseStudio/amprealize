"""Chat-originated work item execution (Option B — server-side coding agent).

Bridges governed chat actions (``run.start``) to the same execution entry point
used by REST/MCP: :class:`~amprealize.execution_gateway_adapter.GatewayWorkItemExecutionAdapter`
when the ExecutionGateway is enabled, otherwise :class:`~amprealize.work_item_execution_service.WorkItemExecutionService`.

Gated by ``feature.chat_agent_work_item_execution`` (default **off**). Starts require
``confirm_chat_execution``; cancels require ``confirm_chat_execution_cancel`` so clients
cannot accidentally mutate runs from ambient NL alone.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Dict, Optional

from amprealize.chat_resource_actions import ChatResourceActionRequest
from amprealize.feature_flags import FeatureFlagService
from amprealize.work_item_execution_contracts import (
    AgentExecutionMode,
    ExecuteWorkItemRequest,
)

logger = logging.getLogger(__name__)

CHAT_AGENT_EXECUTION_FLAG = "feature.chat_agent_work_item_execution"


class ChatExecutionBridge:
    """Execute ``run.start`` chat resource actions via WorkItemExecutionService / Gateway."""

    def __init__(
        self,
        *,
        execution_start_service: Any,
        feature_flags: Optional[FeatureFlagService] = None,
    ) -> None:
        self._execution = execution_start_service
        self._flags = feature_flags or FeatureFlagService()

    async def run_start(self, request: ChatResourceActionRequest) -> Dict[str, Any]:
        """Start a governed execution run for a work item from chat context."""
        ctx = {
            "user_id": request.user_id,
            "org_id": request.org_id,
            "project_id": request.project_id,
        }
        if not self._flags.is_enabled(CHAT_AGENT_EXECUTION_FLAG, ctx):
            return {
                "success": False,
                "message": (
                    "Chat-triggered work item execution is disabled "
                    f"(enable {CHAT_AGENT_EXECUTION_FLAG})."
                ),
                "requires_approval": False,
            }

        payload = dict(request.payload or {})
        if not payload.get("confirm_chat_execution"):
            return {
                "success": False,
                "message": (
                    "Starting a run from chat requires confirm_chat_execution=true "
                    "in the client payload."
                ),
                "requires_approval": True,
            }

        work_item_id = payload.get("work_item_id") or request.resource_id
        project_id = payload.get("project_id") or request.project_id
        if not work_item_id or not project_id:
            return {
                "success": False,
                "message": "work_item_id and project_id are required to start execution.",
                "requires_approval": False,
            }

        mode_raw = payload.get("agent_execution_mode") or payload.get("execution_mode")
        agent_mode: Optional[AgentExecutionMode] = None
        if mode_raw:
            try:
                agent_mode = AgentExecutionMode(str(mode_raw).lower())
            except ValueError:
                return {
                    "success": False,
                    "message": f"Invalid agent_execution_mode: {mode_raw!r}.",
                    "requires_approval": False,
                }

        metadata: Dict[str, Any] = {
            "conversation_id": request.conversation_id,
            "message_id": request.message_id,
            "created_from": "chat",
            "chat_request_id": request.request_id,
            "execution_workspace_kind": payload.get("execution_workspace_kind", "cloud_git"),
        }
        for key in (
            "source_type",
            "source_url",
            "source_ref",
            "mode_override",
            "output_target",
            "idempotency_key",
            "agent_id_override",
            "intent",
        ):
            if key in payload and payload[key] is not None:
                metadata[key] = payload[key]

        exec_req = ExecuteWorkItemRequest(
            work_item_id=str(work_item_id),
            user_id=request.user_id,
            org_id=request.org_id,
            project_id=str(project_id),
            actor_surface="web",
            model_id=payload.get("model_id") or payload.get("model_override"),
            agent_execution_mode=agent_mode,
            metadata=metadata,
        )

        try:
            response = await self._execution.execute(exec_req)
        except Exception as exc:
            logger.warning(
                "chat_execution.run_start_failed work_item_id=%s err=%s",
                work_item_id,
                exc,
            )
            return {
                "success": False,
                "message": str(exc),
                "requires_approval": False,
            }

        return {
            "success": True,
            "message": "Execution started.",
            "requires_approval": False,
            "result": response.to_dict() if hasattr(response, "to_dict") else {},
        }

    async def run_cancel(self, request: ChatResourceActionRequest) -> Dict[str, Any]:
        """Cancel active execution for a work item from chat (same RBAC path as REST cancel)."""
        ctx = {
            "user_id": request.user_id,
            "org_id": request.org_id,
            "project_id": request.project_id,
        }
        if not self._flags.is_enabled(CHAT_AGENT_EXECUTION_FLAG, ctx):
            return {
                "success": False,
                "message": (
                    "Chat-triggered work item execution is disabled "
                    f"(enable {CHAT_AGENT_EXECUTION_FLAG})."
                ),
                "requires_approval": False,
            }

        payload = dict(request.payload or {})
        if not payload.get("confirm_chat_execution_cancel"):
            return {
                "success": False,
                "message": (
                    "Canceling a run from chat requires confirm_chat_execution_cancel=true "
                    "in the client payload."
                ),
                "requires_approval": True,
            }

        work_item_id = payload.get("work_item_id") or request.resource_id
        if not work_item_id:
            return {
                "success": False,
                "message": "work_item_id is required to cancel execution.",
                "requires_approval": False,
            }

        org_id = payload.get("org_id") if payload.get("org_id") is not None else request.org_id
        reason = payload.get("reason") or payload.get("cancellation_reason")

        cancel_fn = getattr(self._execution, "cancel", None)
        if cancel_fn is None:
            return {
                "success": False,
                "message": "Execution service does not support cancel.",
                "requires_approval": False,
            }

        try:
            raw = cancel_fn(str(work_item_id), request.user_id, org_id=org_id, reason=reason)
            if inspect.isawaitable(raw):
                raw = await raw
            success = bool(raw)
        except Exception as exc:
            logger.warning(
                "chat_execution.run_cancel_failed work_item_id=%s err=%s",
                work_item_id,
                exc,
            )
            return {
                "success": False,
                "message": str(exc),
                "requires_approval": False,
            }

        return {
            "success": success,
            "message": (
                "Execution cancelled." if success else "No active execution found for this work item."
            ),
            "requires_approval": False,
            "result": {"work_item_id": str(work_item_id), "cancelled": success},
        }


__all__ = ["CHAT_AGENT_EXECUTION_FLAG", "ChatExecutionBridge"]
