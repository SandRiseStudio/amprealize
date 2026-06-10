"""Governed agent lifecycle actions invoked from Amprealize Chat."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from .conversation_contracts import (
    ChatPermissionAction,
    ChatPermissionSurface,
)
from .policy_composition import (
    PolicyCompositionEngine,
    PolicyDecision,
    build_execution_policy_request,
)
from .session_audit import GovernedChatAuditEventType, GovernedChatAuditLogger


class AgentLifecycleActionType(str, Enum):
    """Agent lifecycle actions that chat can request."""

    DISCOVER = "discover"
    ASSIGN_TO_PROJECT = "assign_to_project"
    CREATE_CUSTOM = "create_custom"
    MODIFY_TOOLS = "modify_tools"
    MODIFY_POLICY = "modify_policy"
    PUBLISH = "publish"
    ARCHIVE_DELETE = "archive_delete"


@dataclass(frozen=True)
class AgentLifecycleActionRequest:
    """Input for a governed agent lifecycle action."""

    action_type: AgentLifecycleActionType
    user_id: str
    agent_id: Optional[str] = None
    org_id: Optional[str] = None
    project_id: Optional[str] = None
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    approved_by: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    policy_context: Dict[str, Any] = field(default_factory=dict)
    request_id: str = ""


@dataclass(frozen=True)
class AgentLifecycleActionResult:
    """Result of attempting an agent lifecycle action."""

    success: bool
    action_type: AgentLifecycleActionType
    decision: str
    requires_approval: bool = False
    message: str = ""
    result: Optional[Any] = None
    audit_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "action_type": self.action_type.value,
            "decision": self.decision,
            "requires_approval": self.requires_approval,
            "message": self.message,
            "result": self.result,
            "audit_id": self.audit_id,
        }


class AgentLifecycleActionService:
    """Execute chat-originated agent lifecycle actions through typed services."""

    _APPROVAL_REQUIRED = frozenset(
        {
            AgentLifecycleActionType.MODIFY_TOOLS,
            AgentLifecycleActionType.MODIFY_POLICY,
            AgentLifecycleActionType.PUBLISH,
            AgentLifecycleActionType.ARCHIVE_DELETE,
        }
    )

    def __init__(
        self,
        *,
        agent_registry: Any,
        project_agent_service: Any = None,
        policy_engine: Optional[PolicyCompositionEngine] = None,
        audit_logger: Optional[GovernedChatAuditLogger] = None,
    ) -> None:
        self._agent_registry = agent_registry
        self._project_agent_service = project_agent_service
        self._policy_engine = policy_engine or PolicyCompositionEngine()
        self._audit = audit_logger or GovernedChatAuditLogger()

    async def execute(
        self,
        request: AgentLifecycleActionRequest,
    ) -> AgentLifecycleActionResult:
        policy_result = self._evaluate_policy(request)
        if policy_result.denied:
            audit_id = self._audit_action(request, policy_result.decision.value)
            return AgentLifecycleActionResult(
                success=False,
                action_type=request.action_type,
                decision=policy_result.decision.value,
                message="Agent lifecycle action denied by policy.",
                audit_id=audit_id,
            )

        needs_approval = (
            policy_result.requires_review
            or request.action_type in self._APPROVAL_REQUIRED
        )
        if needs_approval and not request.approved_by:
            audit_id = self._audit_action(request, "review_required")
            return AgentLifecycleActionResult(
                success=False,
                action_type=request.action_type,
                decision=PolicyDecision.REVIEW.value,
                requires_approval=True,
                message="Agent lifecycle action requires approval.",
                audit_id=audit_id,
            )

        result = await self._dispatch(request)
        audit_id = self._audit_action(
            request,
            "approved" if request.approved_by else policy_result.decision.value,
            result=result,
        )
        return AgentLifecycleActionResult(
            success=True,
            action_type=request.action_type,
            decision="approved" if request.approved_by else policy_result.decision.value,
            requires_approval=needs_approval,
            message="Agent lifecycle action completed.",
            result=result,
            audit_id=audit_id,
        )

    def _evaluate_policy(self, request: AgentLifecycleActionRequest):
        policy_context = {
            **request.policy_context,
            "chat_surface": ChatPermissionSurface.AGENT_LIFECYCLE.value,
            "chat_action": self._permission_action(request.action_type).value,
            "sensitive_operation": (
                request.policy_context.get("sensitive_operation")
                or request.action_type in self._APPROVAL_REQUIRED
            ),
            "agent_lifecycle_action": {
                "action_type": request.action_type.value,
                "agent_id": request.agent_id,
                "project_id": request.project_id,
            },
        }
        return self._policy_engine.evaluate(
            build_execution_policy_request(
                request_id=request.request_id or f"agent-lifecycle-{request.action_type.value}",
                user_id=request.user_id,
                org_id=request.org_id,
                project_id=request.project_id,
                conversation_id=request.conversation_id,
                agent_id=request.agent_id,
                policy_context=policy_context,
                risk_classification=(
                    "high" if request.action_type in self._APPROVAL_REQUIRED else "medium"
                ),
            )
        )

    async def _dispatch(self, request: AgentLifecycleActionRequest) -> Any:
        payload = dict(request.payload)
        payload.setdefault("org_id", request.org_id)
        payload.setdefault("project_id", request.project_id)
        payload.setdefault(
            "actor",
            {"id": request.approved_by or request.user_id, "role": "user", "surface": "chat"},
        )
        if request.action_type == AgentLifecycleActionType.DISCOVER:
            if hasattr(self._agent_registry, "search_agents"):
                return await self._call(self._agent_registry.search_agents, payload)
            return await self._call(self._agent_registry.list_agents, payload)
        if request.action_type == AgentLifecycleActionType.CREATE_CUSTOM:
            return await self._call(self._agent_registry.create_agent, payload)
        if request.action_type in {
            AgentLifecycleActionType.MODIFY_TOOLS,
            AgentLifecycleActionType.MODIFY_POLICY,
        }:
            if not request.agent_id:
                raise ValueError("agent_id is required to modify agent tools or policy")
            payload["metadata"] = {
                **dict(payload.get("metadata") or {}),
                "chat_lifecycle_action": request.action_type.value,
            }
            return await self._call(self._agent_registry.update_agent, request.agent_id, payload)
        if request.action_type == AgentLifecycleActionType.PUBLISH:
            if not request.agent_id:
                raise ValueError("agent_id is required to publish an agent")
            return await self._call(self._agent_registry.publish_agent, request.agent_id, payload)
        if request.action_type == AgentLifecycleActionType.ARCHIVE_DELETE:
            if not request.agent_id:
                raise ValueError("agent_id is required to archive or delete an agent")
            if hasattr(self._agent_registry, "deprecate_agent"):
                return await self._call(self._agent_registry.deprecate_agent, request.agent_id, payload)
            return await self._call(self._agent_registry.delete_agent, request.agent_id)
        if request.action_type == AgentLifecycleActionType.ASSIGN_TO_PROJECT:
            if not request.agent_id or not request.project_id:
                raise ValueError("agent_id and project_id are required for project assignment")
            target = self._project_agent_service or self._agent_registry
            return await self._call(
                target.assign_agent_to_project,
                request.agent_id,
                request.project_id,
                payload,
            )
        raise ValueError(f"Unsupported agent lifecycle action: {request.action_type.value}")

    def _audit_action(
        self,
        request: AgentLifecycleActionRequest,
        decision: str,
        *,
        result: Optional[Any] = None,
    ) -> str:
        record = self._audit.log(
            event_type=GovernedChatAuditEventType.PLATFORM_ACTION,
            user_id=request.user_id,
            action=f"agent_lifecycle.{request.action_type.value}",
            decision=decision,
            chat_scope=request.policy_context.get("chat_scope"),
            target_resources=[
                resource
                for resource in (
                    {"type": "agent", "id": request.agent_id}
                    if request.agent_id
                    else None,
                    {"type": "project", "id": request.project_id}
                    if request.project_id
                    else None,
                    {"type": "org", "id": request.org_id}
                    if request.org_id
                    else None,
                )
                if resource is not None
            ],
            policy_ids=["CHAT_PERMISSION_MATRIX", "PolicyCompositionEngine"],
            conversation_id=request.conversation_id,
            message_id=request.message_id,
            request_id=request.request_id,
            metadata={
                "approved_by": request.approved_by,
                "payload_keys": sorted(request.payload),
                "result_present": result is not None,
            },
        )
        return record.audit_id

    @staticmethod
    def _permission_action(
        action_type: AgentLifecycleActionType,
    ) -> ChatPermissionAction:
        if action_type in {
            AgentLifecycleActionType.DISCOVER,
        }:
            return ChatPermissionAction.READ
        if action_type == AgentLifecycleActionType.CREATE_CUSTOM:
            return ChatPermissionAction.CREATE
        if action_type == AgentLifecycleActionType.PUBLISH:
            return ChatPermissionAction.PUBLISH
        if action_type == AgentLifecycleActionType.ARCHIVE_DELETE:
            return ChatPermissionAction.DELETE
        return ChatPermissionAction.UPDATE

    @staticmethod
    async def _call(method: Any, *args: Any, **kwargs: Any) -> Any:
        result = method(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result
