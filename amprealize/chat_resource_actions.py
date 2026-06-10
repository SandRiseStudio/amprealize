"""Registry for chat-originated resource actions.

Chat uses this registry as the single dispatch point for first-party platform
mutations. REST and MCP remain external parity surfaces; chat should not call
those handlers or localhost APIs for internal actions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Optional

from amprealize.agent_lifecycle_actions import (
    AgentLifecycleActionRequest,
    AgentLifecycleActionService,
    AgentLifecycleActionType,
)
from amprealize.platform_management_actions import (
    PlatformManagementActionRequest,
    PlatformManagementActionService,
    PlatformManagementActionType,
    PlatformResourceType,
)


class ChatResourceActionId(str, Enum):
    """Stable chat action identifiers for governed resource mutations."""

    WORK_ITEM_CREATE = "work_item.create"
    WORK_ITEM_UPDATE = "work_item.update"
    WORK_ITEM_DISCOVER = "work_item.discover"
    BOARD_DISCOVER = "board.discover"
    BOARD_CREATE = "board.create"
    PROJECT_DISCOVER = "project.discover"
    PROJECT_CREATE = "project.create"
    ORG_DISCOVER = "org.discover"
    ORG_CREATE = "org.create"
    AGENT_DISCOVER = "agent.discover"
    AGENT_ASSIGN = "agent.assign"
    AGENT_CREATE = "agent.create"
    AGENT_PUBLISH = "agent.publish"
    AGENT_ARCHIVE = "agent.archive"
    WIKI_PAGE_DISCOVER = "wiki_page.discover"
    WIKI_PAGE_CREATE = "wiki_page.create"
    WIKI_PAGE_UPDATE = "wiki_page.update"
    WIKI_PAGE_DELETE = "wiki_page.delete"
    BEHAVIOR_DISCOVER = "behavior.discover"
    BEHAVIOR_PROPOSE = "behavior.propose"
    BEHAVIOR_UPDATE = "behavior.update"
    BEHAVIOR_APPROVE = "behavior.approve"
    BEHAVIOR_DEPRECATE = "behavior.deprecate"
    RUN_DISCOVER = "run.discover"
    RUN_START = "run.start"
    RUN_CANCEL = "run.cancel"
    ATTACHMENT_CREATE = "attachment.create"
    MCP_TOOL_INVOKE = "mcp_tool.invoke"


class ChatResourceActionBackend(str, Enum):
    """Which governed in-process service family executes the action."""

    PLATFORM = "platform"
    AGENT_LIFECYCLE = "agent_lifecycle"
    EXECUTION = "execution"
    WIKI = "wiki"
    BEHAVIOR = "behavior"
    MCP_GOVERNANCE = "mcp_governance"


@dataclass(frozen=True)
class ChatResourceActionSpec:
    """Registry metadata for one chat resource action."""

    action_id: ChatResourceActionId
    backend: ChatResourceActionBackend
    platform_resource: Optional[PlatformResourceType] = None
    platform_action: Optional[PlatformManagementActionType] = None
    agent_action: Optional[AgentLifecycleActionType] = None
    requires_approval: bool = False
    description: str = ""


@dataclass(frozen=True)
class ChatResourceActionRequest:
    """Input to the chat resource action registry."""

    action_id: ChatResourceActionId | str
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


class ChatResourceActionRegistry:
    """Dispatches chat actions to governed in-process resource services."""

    def __init__(
        self,
        *,
        platform_service: Optional[PlatformManagementActionService] = None,
        agent_lifecycle_service: Optional[AgentLifecycleActionService] = None,
        execution_bridge: Optional[Any] = None,
        extra_specs: Optional[Mapping[ChatResourceActionId | str, ChatResourceActionSpec]] = None,
    ) -> None:
        self._platform_service = platform_service
        self._agent_lifecycle_service = agent_lifecycle_service
        self._execution_bridge = execution_bridge
        self._specs: Dict[ChatResourceActionId, ChatResourceActionSpec] = dict(_DEFAULT_SPECS)
        for key, spec in (extra_specs or {}).items():
            action_id = self._resolve_action_id(key)
            self._specs[action_id] = spec

    def spec(self, action_id: ChatResourceActionId | str) -> ChatResourceActionSpec:
        resolved = self._resolve_action_id(action_id)
        try:
            return self._specs[resolved]
        except KeyError as exc:
            raise ValueError(f"Unsupported chat resource action: {resolved.value}") from exc

    def list_specs(self) -> list[ChatResourceActionSpec]:
        return [self._specs[key] for key in sorted(self._specs, key=lambda item: item.value)]

    async def execute(self, request: ChatResourceActionRequest) -> Any:
        spec = self.spec(request.action_id)
        if spec.backend == ChatResourceActionBackend.PLATFORM:
            return await self._execute_platform(spec, request)
        if spec.backend == ChatResourceActionBackend.AGENT_LIFECYCLE:
            return await self._execute_agent_lifecycle(spec, request)
        if spec.backend == ChatResourceActionBackend.EXECUTION:
            return await self._execute_execution(spec, request)
        raise ValueError(
            f"Chat resource action {spec.action_id.value} is registered "
            f"but no {spec.backend.value} executor is configured yet."
        )

    @staticmethod
    def _resolve_action_id(action_id: ChatResourceActionId | str) -> ChatResourceActionId:
        if isinstance(action_id, ChatResourceActionId):
            return action_id
        return ChatResourceActionId(str(action_id))

    async def _execute_platform(
        self,
        spec: ChatResourceActionSpec,
        request: ChatResourceActionRequest,
    ) -> Any:
        if self._platform_service is None:
            raise ValueError("PlatformManagementActionService is not configured")
        if spec.platform_resource is None or spec.platform_action is None:
            raise ValueError(f"Platform action {spec.action_id.value} is missing dispatch metadata")
        return await self._platform_service.execute(
            PlatformManagementActionRequest(
                action_type=spec.platform_action,
                resource_type=spec.platform_resource,
                user_id=request.user_id,
                resource_id=request.resource_id,
                org_id=request.org_id,
                project_id=request.project_id,
                conversation_id=request.conversation_id,
                message_id=request.message_id,
                approved_by=request.approved_by,
                payload=request.payload,
                policy_context=request.policy_context,
                request_id=request.request_id,
            )
        )

    async def _execute_agent_lifecycle(
        self,
        spec: ChatResourceActionSpec,
        request: ChatResourceActionRequest,
    ) -> Any:
        if self._agent_lifecycle_service is None:
            raise ValueError("AgentLifecycleActionService is not configured")
        if spec.agent_action is None:
            raise ValueError(f"Agent action {spec.action_id.value} is missing dispatch metadata")
        return await self._agent_lifecycle_service.execute(
            AgentLifecycleActionRequest(
                action_type=spec.agent_action,
                user_id=request.user_id,
                agent_id=request.resource_id,
                org_id=request.org_id,
                project_id=request.project_id,
                conversation_id=request.conversation_id,
                message_id=request.message_id,
                approved_by=request.approved_by,
                payload=request.payload,
                policy_context=request.policy_context,
                request_id=request.request_id,
            )
        )

    async def _execute_execution(
        self,
        spec: ChatResourceActionSpec,
        request: ChatResourceActionRequest,
    ) -> Any:
        if self._execution_bridge is None:
            raise ValueError(
                "Chat execution actions require ChatExecutionBridge "
                "(execution_start_service + gateway wiring)."
            )
        resolved = self._resolve_action_id(request.action_id)
        if resolved == ChatResourceActionId.RUN_START:
            return await self._execution_bridge.run_start(request)
        if resolved == ChatResourceActionId.RUN_CANCEL:
            return await self._execution_bridge.run_cancel(request)
        raise ValueError(f"Unsupported execution chat action: {resolved.value}")


_DEFAULT_SPECS: Dict[ChatResourceActionId, ChatResourceActionSpec] = {
    ChatResourceActionId.WORK_ITEM_CREATE: ChatResourceActionSpec(
        action_id=ChatResourceActionId.WORK_ITEM_CREATE,
        backend=ChatResourceActionBackend.PLATFORM,
        platform_resource=PlatformResourceType.WORK_ITEM,
        platform_action=PlatformManagementActionType.CREATE,
        description="Create a work item through BoardService.",
    ),
    ChatResourceActionId.WORK_ITEM_UPDATE: ChatResourceActionSpec(
        action_id=ChatResourceActionId.WORK_ITEM_UPDATE,
        backend=ChatResourceActionBackend.PLATFORM,
        platform_resource=PlatformResourceType.WORK_ITEM,
        platform_action=PlatformManagementActionType.UPDATE,
        description="Update a work item through BoardService.",
    ),
    ChatResourceActionId.WORK_ITEM_DISCOVER: ChatResourceActionSpec(
        action_id=ChatResourceActionId.WORK_ITEM_DISCOVER,
        backend=ChatResourceActionBackend.PLATFORM,
        platform_resource=PlatformResourceType.WORK_ITEM,
        platform_action=PlatformManagementActionType.DISCOVER,
        description="List work items through BoardService.",
    ),
    ChatResourceActionId.BOARD_DISCOVER: ChatResourceActionSpec(
        action_id=ChatResourceActionId.BOARD_DISCOVER,
        backend=ChatResourceActionBackend.PLATFORM,
        platform_resource=PlatformResourceType.BOARD,
        platform_action=PlatformManagementActionType.DISCOVER,
        description="List boards through BoardService.",
    ),
    ChatResourceActionId.BOARD_CREATE: ChatResourceActionSpec(
        action_id=ChatResourceActionId.BOARD_CREATE,
        backend=ChatResourceActionBackend.PLATFORM,
        platform_resource=PlatformResourceType.BOARD,
        platform_action=PlatformManagementActionType.CREATE,
        description="Create a board through BoardService.",
    ),
    ChatResourceActionId.PROJECT_DISCOVER: ChatResourceActionSpec(
        action_id=ChatResourceActionId.PROJECT_DISCOVER,
        backend=ChatResourceActionBackend.PLATFORM,
        platform_resource=PlatformResourceType.PROJECT,
        platform_action=PlatformManagementActionType.DISCOVER,
        description="List projects through project service.",
    ),
    ChatResourceActionId.PROJECT_CREATE: ChatResourceActionSpec(
        action_id=ChatResourceActionId.PROJECT_CREATE,
        backend=ChatResourceActionBackend.PLATFORM,
        platform_resource=PlatformResourceType.PROJECT,
        platform_action=PlatformManagementActionType.CREATE,
        description="Create a project through project service.",
    ),
    ChatResourceActionId.ORG_DISCOVER: ChatResourceActionSpec(
        action_id=ChatResourceActionId.ORG_DISCOVER,
        backend=ChatResourceActionBackend.PLATFORM,
        platform_resource=PlatformResourceType.ORG,
        platform_action=PlatformManagementActionType.DISCOVER,
        description="List organizations through org service.",
    ),
    ChatResourceActionId.ORG_CREATE: ChatResourceActionSpec(
        action_id=ChatResourceActionId.ORG_CREATE,
        backend=ChatResourceActionBackend.PLATFORM,
        platform_resource=PlatformResourceType.ORG,
        platform_action=PlatformManagementActionType.CREATE,
        description="Create an organization through org service.",
    ),
    ChatResourceActionId.ATTACHMENT_CREATE: ChatResourceActionSpec(
        action_id=ChatResourceActionId.ATTACHMENT_CREATE,
        backend=ChatResourceActionBackend.PLATFORM,
        platform_resource=PlatformResourceType.FILE,
        platform_action=PlatformManagementActionType.CREATE,
        description="Attach a file through attachment/file service.",
    ),
    ChatResourceActionId.MCP_TOOL_INVOKE: ChatResourceActionSpec(
        action_id=ChatResourceActionId.MCP_TOOL_INVOKE,
        backend=ChatResourceActionBackend.MCP_GOVERNANCE,
        requires_approval=True,
        description="Invoke external MCP tools only through MCP governance.",
    ),
    ChatResourceActionId.AGENT_DISCOVER: ChatResourceActionSpec(
        action_id=ChatResourceActionId.AGENT_DISCOVER,
        backend=ChatResourceActionBackend.AGENT_LIFECYCLE,
        agent_action=AgentLifecycleActionType.DISCOVER,
        description="Discover available agents through agent lifecycle service.",
    ),
    ChatResourceActionId.AGENT_ASSIGN: ChatResourceActionSpec(
        action_id=ChatResourceActionId.AGENT_ASSIGN,
        backend=ChatResourceActionBackend.AGENT_LIFECYCLE,
        agent_action=AgentLifecycleActionType.ASSIGN_TO_PROJECT,
        description="Assign an agent to a project through agent lifecycle service.",
    ),
    ChatResourceActionId.AGENT_CREATE: ChatResourceActionSpec(
        action_id=ChatResourceActionId.AGENT_CREATE,
        backend=ChatResourceActionBackend.AGENT_LIFECYCLE,
        agent_action=AgentLifecycleActionType.CREATE_CUSTOM,
        description="Create a custom agent through agent lifecycle service.",
    ),
    ChatResourceActionId.AGENT_PUBLISH: ChatResourceActionSpec(
        action_id=ChatResourceActionId.AGENT_PUBLISH,
        backend=ChatResourceActionBackend.AGENT_LIFECYCLE,
        agent_action=AgentLifecycleActionType.PUBLISH,
        requires_approval=True,
        description="Publish an agent through agent lifecycle service.",
    ),
    ChatResourceActionId.AGENT_ARCHIVE: ChatResourceActionSpec(
        action_id=ChatResourceActionId.AGENT_ARCHIVE,
        backend=ChatResourceActionBackend.AGENT_LIFECYCLE,
        agent_action=AgentLifecycleActionType.ARCHIVE_DELETE,
        requires_approval=True,
        description="Archive/delete an agent through agent lifecycle service.",
    ),
    ChatResourceActionId.WIKI_PAGE_DISCOVER: ChatResourceActionSpec(
        action_id=ChatResourceActionId.WIKI_PAGE_DISCOVER,
        backend=ChatResourceActionBackend.WIKI,
        description="Read/list wiki pages through wiki service.",
    ),
    ChatResourceActionId.WIKI_PAGE_CREATE: ChatResourceActionSpec(
        action_id=ChatResourceActionId.WIKI_PAGE_CREATE,
        backend=ChatResourceActionBackend.WIKI,
        description="Create wiki pages through wiki service.",
    ),
    ChatResourceActionId.WIKI_PAGE_UPDATE: ChatResourceActionSpec(
        action_id=ChatResourceActionId.WIKI_PAGE_UPDATE,
        backend=ChatResourceActionBackend.WIKI,
        description="Update wiki page content through wiki service.",
    ),
    ChatResourceActionId.WIKI_PAGE_DELETE: ChatResourceActionSpec(
        action_id=ChatResourceActionId.WIKI_PAGE_DELETE,
        backend=ChatResourceActionBackend.WIKI,
        requires_approval=True,
        description="Delete wiki pages through wiki service.",
    ),
    ChatResourceActionId.BEHAVIOR_DISCOVER: ChatResourceActionSpec(
        action_id=ChatResourceActionId.BEHAVIOR_DISCOVER,
        backend=ChatResourceActionBackend.BEHAVIOR,
        description="Search/list behaviors through BehaviorService.",
    ),
    ChatResourceActionId.BEHAVIOR_PROPOSE: ChatResourceActionSpec(
        action_id=ChatResourceActionId.BEHAVIOR_PROPOSE,
        backend=ChatResourceActionBackend.BEHAVIOR,
        description="Propose behavior changes through BehaviorService.",
    ),
    ChatResourceActionId.BEHAVIOR_UPDATE: ChatResourceActionSpec(
        action_id=ChatResourceActionId.BEHAVIOR_UPDATE,
        backend=ChatResourceActionBackend.BEHAVIOR,
        description="Update behaviors through BehaviorService.",
    ),
    ChatResourceActionId.BEHAVIOR_APPROVE: ChatResourceActionSpec(
        action_id=ChatResourceActionId.BEHAVIOR_APPROVE,
        backend=ChatResourceActionBackend.BEHAVIOR,
        requires_approval=True,
        description="Approve behaviors through BehaviorService.",
    ),
    ChatResourceActionId.BEHAVIOR_DEPRECATE: ChatResourceActionSpec(
        action_id=ChatResourceActionId.BEHAVIOR_DEPRECATE,
        backend=ChatResourceActionBackend.BEHAVIOR,
        requires_approval=True,
        description="Deprecate behaviors through BehaviorService.",
    ),
    ChatResourceActionId.RUN_DISCOVER: ChatResourceActionSpec(
        action_id=ChatResourceActionId.RUN_DISCOVER,
        backend=ChatResourceActionBackend.EXECUTION,
        description="Read run status through RunService/execution service.",
    ),
    ChatResourceActionId.RUN_START: ChatResourceActionSpec(
        action_id=ChatResourceActionId.RUN_START,
        backend=ChatResourceActionBackend.EXECUTION,
        requires_approval=True,
        description="Start execution through ExecutionGateway.",
    ),
    ChatResourceActionId.RUN_CANCEL: ChatResourceActionSpec(
        action_id=ChatResourceActionId.RUN_CANCEL,
        backend=ChatResourceActionBackend.EXECUTION,
        requires_approval=True,
        description="Cancel execution through execution control service.",
    ),
}


__all__ = [
    "ChatResourceActionBackend",
    "ChatResourceActionId",
    "ChatResourceActionRegistry",
    "ChatResourceActionRequest",
    "ChatResourceActionSpec",
]
