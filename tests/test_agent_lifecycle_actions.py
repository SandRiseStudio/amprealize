"""Tests for governed agent lifecycle chat actions."""

from __future__ import annotations

import pytest

from amprealize.agent_lifecycle_actions import (
    AgentLifecycleActionRequest,
    AgentLifecycleActionService,
    AgentLifecycleActionType,
)
from amprealize.session_audit import GovernedChatAuditLogger

pytestmark = pytest.mark.unit


class FakeAgentRegistry:
    def __init__(self) -> None:
        self.calls = []

    def search_agents(self, payload):
        self.calls.append(("search_agents", payload))
        return {"results": [{"agent_id": "agent-1"}], "total": 1}

    def create_agent(self, payload):
        self.calls.append(("create_agent", payload))
        return {"agent_id": "agent-new", "name": payload["name"]}

    def update_agent(self, agent_id, payload):
        self.calls.append(("update_agent", agent_id, payload))
        return {"agent_id": agent_id, "updated": True, "metadata": payload["metadata"]}

    def publish_agent(self, agent_id, payload):
        self.calls.append(("publish_agent", agent_id, payload))
        return {"agent_id": agent_id, "status": "ACTIVE"}

    def deprecate_agent(self, agent_id, payload):
        self.calls.append(("deprecate_agent", agent_id, payload))
        return {"agent_id": agent_id, "status": "DEPRECATED"}

    def assign_agent_to_project(self, agent_id, project_id, payload):
        self.calls.append(("assign_agent_to_project", agent_id, project_id, payload))
        return {"agent_id": agent_id, "project_id": project_id}


@pytest.mark.asyncio
async def test_discover_agents_runs_without_approval_and_audits():
    registry = FakeAgentRegistry()
    audit = GovernedChatAuditLogger()
    service = AgentLifecycleActionService(
        agent_registry=registry,
        audit_logger=audit,
    )

    result = await service.execute(
        AgentLifecycleActionRequest(
            action_type=AgentLifecycleActionType.DISCOVER,
            user_id="user-1",
            org_id="org-1",
            payload={"query": "planner"},
        )
    )

    assert result.success is True
    assert result.requires_approval is False
    assert registry.calls[0][0] == "search_agents"
    assert audit.records[0].action == "agent_lifecycle.discover"
    assert audit.records[0].decision == "allow"


@pytest.mark.asyncio
async def test_publish_requires_approval_before_registry_call():
    registry = FakeAgentRegistry()
    audit = GovernedChatAuditLogger()
    service = AgentLifecycleActionService(
        agent_registry=registry,
        audit_logger=audit,
    )

    result = await service.execute(
        AgentLifecycleActionRequest(
            action_type=AgentLifecycleActionType.PUBLISH,
            user_id="user-1",
            agent_id="agent-1",
            org_id="org-1",
            payload={"version": "1.0.0"},
        )
    )

    assert result.success is False
    assert result.requires_approval is True
    assert result.decision == "review"
    assert registry.calls == []
    assert audit.records[0].decision == "review_required"


@pytest.mark.asyncio
async def test_approved_publish_dispatches_and_marks_audit_approved():
    registry = FakeAgentRegistry()
    audit = GovernedChatAuditLogger()
    service = AgentLifecycleActionService(
        agent_registry=registry,
        audit_logger=audit,
    )

    result = await service.execute(
        AgentLifecycleActionRequest(
            action_type=AgentLifecycleActionType.PUBLISH,
            user_id="user-1",
            approved_by="owner-1",
            agent_id="agent-1",
            org_id="org-1",
            payload={"version": "1.0.0"},
        )
    )

    assert result.success is True
    assert result.requires_approval is True
    assert registry.calls[0][0] == "publish_agent"
    assert registry.calls[0][1] == "agent-1"
    assert audit.records[0].decision == "approved"


@pytest.mark.asyncio
async def test_tool_policy_change_requires_approval_and_adds_metadata():
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
            approved_by="owner-1",
            agent_id="agent-1",
            project_id="proj-1",
            payload={"metadata": {"tool_permissions": {"write_file": "deny"}}},
        )
    )

    _, agent_id, payload = registry.calls[0]
    assert result.success is True
    assert agent_id == "agent-1"
    assert payload["metadata"]["tool_permissions"]["write_file"] == "deny"
    assert payload["metadata"]["chat_lifecycle_action"] == "modify_tools"
    assert audit.records[0].target_resources[0]["type"] == "agent"


@pytest.mark.asyncio
async def test_project_assignment_requires_agent_and_project():
    registry = FakeAgentRegistry()
    service = AgentLifecycleActionService(agent_registry=registry)

    with pytest.raises(ValueError, match="agent_id and project_id"):
        await service.execute(
            AgentLifecycleActionRequest(
                action_type=AgentLifecycleActionType.ASSIGN_TO_PROJECT,
                user_id="user-1",
                agent_id="agent-1",
            )
        )
