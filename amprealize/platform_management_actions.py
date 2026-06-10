"""Governed platform management actions invoked from Amprealize Chat."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Optional

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
from .boards.contracts import CreateWorkItemRequest
from .services.board_service import Actor


class PlatformResourceType(str, Enum):
    """Platform resource families managed through chat actions."""

    ORG = "org"
    PROJECT = "project"
    BOARD = "board"
    WORK_ITEM = "work_item"
    INVITE_SHARE = "invite_share"
    FILE = "file"
    UPLOAD = "upload"
    IMAGE = "image"
    MCP_TOOL = "mcp_tool"


class PlatformManagementActionType(str, Enum):
    """Generic management verbs shared by platform resource families."""

    DISCOVER = "discover"
    CREATE = "create"
    UPDATE = "update"
    DELETE_ARCHIVE = "delete_archive"
    INVITE_SHARE = "invite_share"
    GRANT_TOOL_ACCESS = "grant_tool_access"
    REVOKE_TOOL_ACCESS = "revoke_tool_access"


@dataclass(frozen=True)
class PlatformManagementActionRequest:
    """Input for a governed platform management action."""

    action_type: PlatformManagementActionType
    resource_type: PlatformResourceType
    user_id: str
    resource_id: Optional[str] = None
    org_id: Optional[str] = None
    project_id: Optional[str] = None
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    approved_by: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    policy_context: Dict[str, Any] = field(default_factory=dict)
    request_id: str = ""


@dataclass(frozen=True)
class PlatformManagementActionResult:
    """Result of attempting a governed platform management action."""

    success: bool
    action_type: PlatformManagementActionType
    resource_type: PlatformResourceType
    decision: str
    requires_approval: bool = False
    message: str = ""
    result: Optional[Any] = None
    audit_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "action_type": self.action_type.value,
            "resource_type": self.resource_type.value,
            "decision": self.decision,
            "requires_approval": self.requires_approval,
            "message": self.message,
            "result": self.result,
            "audit_id": self.audit_id,
        }


class PlatformManagementActionService:
    """Execute chat-originated platform actions through typed services."""

    _APPROVAL_REQUIRED = frozenset(
        {
            PlatformManagementActionType.DELETE_ARCHIVE,
            PlatformManagementActionType.INVITE_SHARE,
            PlatformManagementActionType.GRANT_TOOL_ACCESS,
            PlatformManagementActionType.REVOKE_TOOL_ACCESS,
        }
    )

    _RESOURCE_SURFACE = {
        PlatformResourceType.FILE: ChatPermissionSurface.ATTACHMENT,
        PlatformResourceType.UPLOAD: ChatPermissionSurface.ATTACHMENT,
        PlatformResourceType.IMAGE: ChatPermissionSurface.ATTACHMENT,
        PlatformResourceType.MCP_TOOL: ChatPermissionSurface.MCP_TOOL,
    }

    _METHODS: Mapping[
        tuple[PlatformResourceType, PlatformManagementActionType],
        str,
    ] = {
        (PlatformResourceType.ORG, PlatformManagementActionType.DISCOVER): "list_orgs",
        (PlatformResourceType.ORG, PlatformManagementActionType.CREATE): "create_org",
        (PlatformResourceType.ORG, PlatformManagementActionType.UPDATE): "update_org",
        (PlatformResourceType.PROJECT, PlatformManagementActionType.DISCOVER): "list_projects",
        (PlatformResourceType.PROJECT, PlatformManagementActionType.CREATE): "create_project",
        (PlatformResourceType.PROJECT, PlatformManagementActionType.UPDATE): "update_project",
        (PlatformResourceType.PROJECT, PlatformManagementActionType.DELETE_ARCHIVE): "archive_project",
        (PlatformResourceType.BOARD, PlatformManagementActionType.DISCOVER): "list_boards",
        (PlatformResourceType.BOARD, PlatformManagementActionType.CREATE): "create_board",
        (PlatformResourceType.BOARD, PlatformManagementActionType.UPDATE): "update_board",
        (PlatformResourceType.WORK_ITEM, PlatformManagementActionType.DISCOVER): "list_work_items",
        (PlatformResourceType.WORK_ITEM, PlatformManagementActionType.CREATE): "create_work_item",
        (PlatformResourceType.WORK_ITEM, PlatformManagementActionType.UPDATE): "update_work_item",
        (PlatformResourceType.INVITE_SHARE, PlatformManagementActionType.INVITE_SHARE): "invite_or_share",
        (PlatformResourceType.FILE, PlatformManagementActionType.CREATE): "attach_file",
        (PlatformResourceType.FILE, PlatformManagementActionType.DISCOVER): "list_files",
        (PlatformResourceType.UPLOAD, PlatformManagementActionType.CREATE): "create_upload",
        (PlatformResourceType.IMAGE, PlatformManagementActionType.CREATE): "attach_image",
        (PlatformResourceType.MCP_TOOL, PlatformManagementActionType.GRANT_TOOL_ACCESS): "grant_tool_access",
        (PlatformResourceType.MCP_TOOL, PlatformManagementActionType.REVOKE_TOOL_ACCESS): "revoke_tool_access",
    }

    def __init__(
        self,
        *,
        services: Mapping[PlatformResourceType | str, Any],
        policy_engine: Optional[PolicyCompositionEngine] = None,
        audit_logger: Optional[GovernedChatAuditLogger] = None,
    ) -> None:
        self._services = services
        self._policy_engine = policy_engine or PolicyCompositionEngine()
        self._audit = audit_logger or GovernedChatAuditLogger()

    async def execute(
        self,
        request: PlatformManagementActionRequest,
    ) -> PlatformManagementActionResult:
        self._validate_target(request)
        policy_result = self._evaluate_policy(request)
        if policy_result.denied:
            audit_id = self._audit_action(request, policy_result.decision.value)
            return PlatformManagementActionResult(
                success=False,
                action_type=request.action_type,
                resource_type=request.resource_type,
                decision=policy_result.decision.value,
                message="Platform management action denied by policy.",
                audit_id=audit_id,
            )

        needs_approval = (
            policy_result.requires_review
            or request.action_type in self._APPROVAL_REQUIRED
        )
        if needs_approval and not request.approved_by:
            audit_id = self._audit_action(request, "review_required")
            return PlatformManagementActionResult(
                success=False,
                action_type=request.action_type,
                resource_type=request.resource_type,
                decision=PolicyDecision.REVIEW.value,
                requires_approval=True,
                message="Platform management action requires approval.",
                audit_id=audit_id,
            )

        result = await self._dispatch(request)
        audit_id = self._audit_action(
            request,
            "approved" if request.approved_by else policy_result.decision.value,
            result=result,
        )
        return PlatformManagementActionResult(
            success=True,
            action_type=request.action_type,
            resource_type=request.resource_type,
            decision="approved" if request.approved_by else policy_result.decision.value,
            requires_approval=needs_approval,
            message="Platform management action completed.",
            result=result,
            audit_id=audit_id,
        )

    def _evaluate_policy(self, request: PlatformManagementActionRequest):
        policy_context = {
            **request.policy_context,
            "chat_surface": self._permission_surface(request.resource_type).value,
            "chat_action": self._permission_action(request.action_type).value,
            "sensitive_operation": (
                request.policy_context.get("sensitive_operation")
                or request.action_type in self._APPROVAL_REQUIRED
            ),
            "platform_management_action": {
                "action_type": request.action_type.value,
                "resource_type": request.resource_type.value,
                "resource_id": request.resource_id,
                "project_id": request.project_id,
            },
        }
        return self._policy_engine.evaluate(
            build_execution_policy_request(
                request_id=request.request_id
                or f"platform-management-{request.resource_type.value}-{request.action_type.value}",
                user_id=request.user_id,
                org_id=request.org_id,
                project_id=request.project_id,
                conversation_id=request.conversation_id,
                policy_context=policy_context,
                risk_classification=(
                    "high" if request.action_type in self._APPROVAL_REQUIRED else "medium"
                ),
            )
        )

    async def _dispatch(self, request: PlatformManagementActionRequest) -> Any:
        service = self._service_for(request.resource_type)
        method_name = self._METHODS.get((request.resource_type, request.action_type))
        if not method_name:
            raise ValueError(
                f"Unsupported platform action {request.resource_type.value}.{request.action_type.value}"
            )
        method = getattr(service, method_name)
        payload = {
            **request.payload,
            "resource_id": request.resource_id,
            "org_id": request.org_id,
            "project_id": request.project_id,
            "actor": {
                "id": request.approved_by or request.user_id,
                "role": "user",
                "surface": "chat",
            },
        }
        return await self._call(method, payload)

    def _service_for(self, resource_type: PlatformResourceType) -> Any:
        return self._services.get(resource_type) or self._services.get(resource_type.value)

    def _validate_target(self, request: PlatformManagementActionRequest) -> None:
        if self._service_for(request.resource_type) is None:
            raise ValueError(f"No service configured for {request.resource_type.value}")
        if request.action_type in self._APPROVAL_REQUIRED and not request.payload.get("target"):
            raise ValueError("invite/share and tool access actions require an explicit target")
        if request.resource_type in {
            PlatformResourceType.FILE,
            PlatformResourceType.UPLOAD,
            PlatformResourceType.IMAGE,
        } and not (request.project_id or request.conversation_id):
            raise ValueError("file, upload, and image actions require project or conversation scope")

    def _audit_action(
        self,
        request: PlatformManagementActionRequest,
        decision: str,
        *,
        result: Optional[Any] = None,
    ) -> str:
        record = self._audit.log(
            event_type=GovernedChatAuditEventType.PLATFORM_ACTION,
            user_id=request.user_id,
            action=f"platform.{request.resource_type.value}.{request.action_type.value}",
            decision=decision,
            chat_scope=request.policy_context.get("chat_scope"),
            target_resources=[
                resource
                for resource in (
                    {"type": request.resource_type.value, "id": request.resource_id}
                    if request.resource_id
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
                "business_outcome": self._business_outcome_metadata(request, result),
            },
        )
        return record.audit_id

    @staticmethod
    def _business_outcome_metadata(
        request: PlatformManagementActionRequest,
        result: Optional[Any],
    ) -> Dict[str, Any]:
        result_payload = result if isinstance(result, dict) else {}
        resource_id = (
            result_payload.get("item_id")
            or result_payload.get("work_item_id")
            or result_payload.get("project_id")
            or result_payload.get("board_id")
            or result_payload.get("invite_id")
            or result_payload.get("file_id")
            or result_payload.get("id")
            or request.resource_id
        )
        resource_type = request.resource_type.value
        return {
            "outcome_type": f"platform.{resource_type}.{request.action_type.value}",
            "resource_type": resource_type,
            "resource_id": resource_id,
            "outcome_ref": (
                f"{resource_type}:{resource_id}"
                if resource_id
                else None
            ),
        }

    @classmethod
    def _permission_surface(
        cls,
        resource_type: PlatformResourceType,
    ) -> ChatPermissionSurface:
        return cls._RESOURCE_SURFACE.get(
            resource_type,
            ChatPermissionSurface.PLATFORM_ACTION,
        )

    @staticmethod
    def _permission_action(
        action_type: PlatformManagementActionType,
    ) -> ChatPermissionAction:
        if action_type == PlatformManagementActionType.DISCOVER:
            return ChatPermissionAction.READ
        if action_type == PlatformManagementActionType.CREATE:
            return ChatPermissionAction.CREATE
        if action_type == PlatformManagementActionType.UPDATE:
            return ChatPermissionAction.UPDATE
        if action_type == PlatformManagementActionType.DELETE_ARCHIVE:
            return ChatPermissionAction.DELETE
        if action_type == PlatformManagementActionType.INVITE_SHARE:
            return ChatPermissionAction.INVITE_SHARE
        return ChatPermissionAction.ADMINISTER

    @staticmethod
    async def _call(method: Any, *args: Any, **kwargs: Any) -> Any:
        result = method(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result


class BoardPlatformManagementAdapter:
    """Adapter that exposes BoardService through PlatformManagementActionService."""

    def __init__(self, board_service: Any) -> None:
        self._board_service = board_service

    def list_boards(self, payload: Dict[str, Any]) -> Any:
        boards = self._board_service.list_boards(
            project_id=payload.get("project_id"),
            org_id=payload.get("org_id"),
            limit=int(payload.get("limit") or 100),
            offset=int(payload.get("offset") or 0),
        )
        return [
            board.model_dump(mode="json") if hasattr(board, "model_dump") else board
            for board in boards
        ]

    def list_work_items(self, payload: Dict[str, Any]) -> Any:
        """Discover work items scoped to a project/board.

        Accepts text_search for topic-based lookups (e.g. "agent execution").
        """
        items, total = self._board_service.list_work_items(
            project_id=payload.get("project_id"),
            board_id=payload.get("board_id"),
            org_id=payload.get("org_id"),
            status=None,  # let callers pass via payload if needed
            title_search=payload.get("title_search") or None,
            text_search=payload.get("text_search") or None,
            limit=int(payload.get("limit") or 50),
            offset=int(payload.get("offset") or 0),
            include_total=True,
        )
        return {
            "items": [
                item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                for item in items
            ],
            "total": total,
        }

    def update_work_item(self, payload: Dict[str, Any]) -> Any:
        """Update a work item field."""
        from amprealize.boards.contracts import UpdateWorkItemRequest

        actor_payload = payload.get("actor") if isinstance(payload.get("actor"), dict) else {}
        actor = Actor(
            id=str(actor_payload.get("id") or payload.get("user_id") or "chat"),
            role=str(actor_payload.get("role") or "user"),
            surface=str(actor_payload.get("surface") or "chat"),
        )
        item_id = str(payload.get("item_id") or payload.get("work_item_id") or "")
        request = UpdateWorkItemRequest(
            title=payload.get("title"),
            description=payload.get("description"),
            status=payload.get("status"),
            priority=payload.get("priority"),
            parent_id=payload.get("parent_id"),
            assignee_id=payload.get("assignee_id"),
            labels=list(payload["labels"]) if payload.get("labels") else None,
            points=payload.get("points"),
        )
        item = self._board_service.update_work_item(
            item_id,
            request,
            actor,
            org_id=payload.get("org_id"),
        )
        return item.model_dump(mode="json") if hasattr(item, "model_dump") else item

    def create_work_item(self, payload: Dict[str, Any]) -> Any:
        actor_payload = payload.get("actor") if isinstance(payload.get("actor"), dict) else {}
        actor = Actor(
            id=str(actor_payload.get("id") or payload.get("user_id") or "chat"),
            role=str(actor_payload.get("role") or "user"),
            surface=str(actor_payload.get("surface") or "chat"),
        )
        request = CreateWorkItemRequest(
            item_type=str(payload.get("item_type") or "task"),
            project_id=payload.get("project_id"),
            board_id=payload.get("board_id"),
            column_id=payload.get("column_id"),
            parent_id=payload.get("parent_id"),
            title=str(payload.get("title") or ""),
            description=payload.get("description"),
            priority=payload.get("priority") or "medium",
            points=payload.get("points"),
            labels=list(payload.get("labels") or []),
            acceptance_criteria=list(payload.get("acceptance_criteria") or []),
            checklist=list(payload.get("checklist") or []),
            metadata=dict(payload.get("metadata") or {}),
        )
        item = self._board_service.create_work_item(
            request,
            actor,
            org_id=payload.get("org_id"),
        )
        return item.model_dump(mode="json") if hasattr(item, "model_dump") else item
