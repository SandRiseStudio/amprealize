"""End-to-end boundary tests for governed chat actions."""

from __future__ import annotations

import pytest

from amprealize.agent_lifecycle_actions import (
    AgentLifecycleActionRequest,
    AgentLifecycleActionService,
    AgentLifecycleActionType,
)
from amprealize.chat_action_router import ChatActionRouteRequest, ChatActionRouter
from amprealize.conversation_contracts import (
    ChatPermissionScope,
    ChatPermissionSurface,
    ConversationScope,
)
from amprealize.platform_management_actions import (
    PlatformManagementActionRequest,
    PlatformManagementActionService,
    PlatformManagementActionType,
    PlatformResourceType,
)
from amprealize.policy_composition import (
    PolicyCompositionEngine,
    PolicyDecision,
    PolicyEvaluationRequest,
)
from amprealize.session_audit import (
    GovernedChatAuditEventType,
    GovernedChatAuditLogger,
)
from amprealize.work_item_execution_contracts import (
    ExecutionPolicy,
    ToolPermissionLevel,
)

pytestmark = pytest.mark.unit


class FakeAgentRegistry:
    def __init__(self) -> None:
        self.calls = []

    def update_agent(self, agent_id, payload):
        self.calls.append(("update_agent", agent_id, payload))
        return {"agent_id": agent_id, "updated": True}


class FakePlatformService:
    def __init__(self) -> None:
        self.calls = []

    def create_work_item(self, payload):
        self.calls.append(("create_work_item", payload))
        return {"item_id": "task-1", "project_id": payload["project_id"]}

    def attach_file(self, payload):
        self.calls.append(("attach_file", payload))
        return {"file_id": "file-1", "conversation_id": payload["resource_id"]}

    def grant_tool_access(self, payload):
        self.calls.append(("grant_tool_access", payload))
        return {"tool": payload["tool_name"], "target": payload["target"]}


def test_global_chat_denies_inaccessible_resource_before_synthesis():
    router = ChatActionRouter()
    audit = GovernedChatAuditLogger()

    route = router.route(
        ChatActionRouteRequest(
            message="summarize the restricted project",
            conversation_scope=ConversationScope.GLOBAL_USER_HOME,
            user_id="user-1",
            resource_links=[
                {"resource_type": "project", "resource_id": "proj-secret"}
            ],
        )
    )
    candidate = route.primary
    assert candidate is not None
    policy = PolicyCompositionEngine().evaluate(
        PolicyEvaluationRequest(
            request_id="global-deny",
            user_id="user-1",
            chat_surface=candidate.permission_surface,
            chat_action=candidate.permission_action,
            policy_context={
                **candidate.to_policy_context(),
                "policy_decisions": {
                    "project": {
                        "decision": "deny",
                        "reason": "User cannot access proj-secret.",
                    }
                },
            },
        )
    )

    record = audit.log(
        event_type=GovernedChatAuditEventType.DENIAL,
        user_id="user-1",
        action=candidate.action_id,
        decision=policy.decision.value,
        chat_scope=ConversationScope.GLOBAL_USER_HOME.value,
        target_resources=[],
        request_id="global-deny",
        metadata={"withheld_resource_count": 1},
    )

    assert candidate.permission_surface == ChatPermissionSurface.GLOBAL_CHAT
    assert policy.decision == PolicyDecision.DENY
    assert record.target_resources == []
    assert record.metadata["withheld_resource_count"] == 1


def test_mixed_group_chat_execution_requires_conversation_project_and_agent_scopes():
    route = ChatActionRouter().route(
        ChatActionRouteRequest(
            message="execute this with the coding agent",
            conversation_scope=ConversationScope.GROUP_CHAT,
            project_id="proj-1",
            conversation_id="conv-group",
            resource_links=[
                {"resource_type": "work_item", "resource_id": "guideai-1037"}
            ],
        )
    )

    candidate = route.primary
    assert candidate is not None
    assert candidate.permission_surface == ChatPermissionSurface.GROUP_CHAT
    assert {
        ChatPermissionScope.CONVERSATION,
        ChatPermissionScope.PROJECT,
        ChatPermissionScope.AGENT,
    }.issubset(set(candidate.required_scopes))
    assert candidate.requires_approval is True


@pytest.mark.asyncio
async def test_project_space_work_item_mutation_dispatches_and_audits_scope():
    platform = FakePlatformService()
    audit = GovernedChatAuditLogger()
    service = PlatformManagementActionService(
        services={PlatformResourceType.WORK_ITEM: platform},
        audit_logger=audit,
    )

    result = await service.execute(
        PlatformManagementActionRequest(
            action_type=PlatformManagementActionType.CREATE,
            resource_type=PlatformResourceType.WORK_ITEM,
            user_id="user-1",
            project_id="proj-1",
            conversation_id="conv-project",
            policy_context={"chat_scope": ConversationScope.PROJECT_SPACE.value},
            payload={"title": "Follow up on governance boundary"},
        )
    )

    assert result.success is True
    assert platform.calls[0][0] == "create_work_item"
    assert audit.records[0].chat_scope == ConversationScope.PROJECT_SPACE.value
    assert audit.records[0].target_resources == [{"type": "project", "id": "proj-1"}]


@pytest.mark.asyncio
async def test_attachment_requires_project_or_conversation_scope_and_audits_allowed_file():
    platform = FakePlatformService()
    audit = GovernedChatAuditLogger()
    service = PlatformManagementActionService(
        services={PlatformResourceType.FILE: platform},
        audit_logger=audit,
    )

    with pytest.raises(ValueError, match="project or conversation scope"):
        await service.execute(
            PlatformManagementActionRequest(
                action_type=PlatformManagementActionType.CREATE,
                resource_type=PlatformResourceType.FILE,
                user_id="user-1",
                payload={"filename": "private-plan.md"},
            )
        )

    result = await service.execute(
        PlatformManagementActionRequest(
            action_type=PlatformManagementActionType.CREATE,
            resource_type=PlatformResourceType.FILE,
            user_id="user-1",
            conversation_id="conv-1",
            resource_id="conv-1",
            payload={"filename": "private-plan.md"},
        )
    )

    assert result.success is True
    assert platform.calls[0][0] == "attach_file"
    assert audit.records[0].target_resources == [{"type": "file", "id": "conv-1"}]


@pytest.mark.asyncio
async def test_mcp_tool_access_requires_approval_then_records_approved_audit():
    platform = FakePlatformService()
    audit = GovernedChatAuditLogger()
    service = PlatformManagementActionService(
        services={PlatformResourceType.MCP_TOOL: platform},
        audit_logger=audit,
    )

    review_result = await service.execute(
        PlatformManagementActionRequest(
            action_type=PlatformManagementActionType.GRANT_TOOL_ACCESS,
            resource_type=PlatformResourceType.MCP_TOOL,
            user_id="user-1",
            project_id="proj-1",
            payload={"target": "agent-1", "tool_name": "write_file"},
        )
    )
    approved_result = await service.execute(
        PlatformManagementActionRequest(
            action_type=PlatformManagementActionType.GRANT_TOOL_ACCESS,
            resource_type=PlatformResourceType.MCP_TOOL,
            user_id="user-1",
            approved_by="owner-1",
            project_id="proj-1",
            payload={"target": "agent-1", "tool_name": "write_file"},
        )
    )

    assert review_result.requires_approval is True
    assert approved_result.success is True
    assert platform.calls[0][0] == "grant_tool_access"
    assert [record.decision for record in audit.records] == [
        "review_required",
        "approved",
    ]


@pytest.mark.asyncio
async def test_agent_lifecycle_policy_denial_blocks_registry_call_and_audits():
    registry = FakeAgentRegistry()
    audit = GovernedChatAuditLogger()
    service = AgentLifecycleActionService(
        agent_registry=registry,
        audit_logger=audit,
    )

    result = await service.execute(
        AgentLifecycleActionRequest(
            action_type=AgentLifecycleActionType.MODIFY_TOOLS,
            user_id="user-1",
            agent_id="agent-1",
            project_id="proj-1",
            policy_context={
                "policy_decisions": {
                    "agent": {
                        "decision": "deny",
                        "reason": "Agent policy is locked.",
                    }
                }
            },
            payload={"metadata": {"tool_permissions": {"write_file": "deny"}}},
        )
    )

    assert result.success is False
    assert result.decision == "deny"
    assert registry.calls == []
    assert audit.records[0].decision == "deny"
    assert audit.records[0].target_resources == [
        {"type": "agent", "id": "agent-1"},
        {"type": "project", "id": "proj-1"},
    ]


def test_execution_policy_blocks_denied_mcp_tool_before_chat_tool_call_audit():
    audit = GovernedChatAuditLogger()
    policy = PolicyCompositionEngine().evaluate(
        PolicyEvaluationRequest(
            request_id="tool-deny",
            user_id="user-1",
            project_id="proj-1",
            conversation_id="conv-1",
            agent_id="agent-1",
            chat_surface=ChatPermissionSurface.MCP_TOOL,
            policy_context={"mcp_tool_name": "delete_file"},
            execution_policy=ExecutionPolicy(
                tool_permissions={"delete_file": ToolPermissionLevel.DENY}
            ),
        )
    )

    record = audit.log_tool_call(
        user_id="user-1",
        action="delete_file",
        decision=policy.decision.value,
        conversation_id="conv-1",
        target_resources=[{"type": "mcp_tool", "id": "delete_file"}],
    )

    assert policy.decision == PolicyDecision.DENY
    assert record.decision == "deny"
    assert record.target_resources == [{"type": "mcp_tool", "id": "delete_file"}]
