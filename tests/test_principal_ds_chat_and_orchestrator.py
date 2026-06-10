"""Tests for principal data science chat injection and data_science orchestrator persona."""

from __future__ import annotations

import pytest

from amprealize.agent_orchestrator_service import AgentOrchestratorService
from amprealize.services.conversation_reply_service import (
    PRINCIPAL_DS_SYSTEM_SUFFIX,
    ConversationReplyService,
    ReplyRequest,
)

pytestmark = pytest.mark.unit


def test_list_personas_includes_data_science() -> None:
    svc = AgentOrchestratorService()
    ids = {p.agent_id for p in svc.list_personas()}
    assert "data_science" in ids
    ds = next(p for p in svc.list_personas() if p.agent_id == "data_science")
    assert "behavior_principal_data_science_workflow" in ds.default_behaviors
    assert any("AGENT_DATA_SCIENCE.md" in ref for ref in ds.playbook_refs)


def test_assign_agent_data_science_task_type() -> None:
    svc = AgentOrchestratorService()
    requested_by = {"actor_id": "u1", "actor_role": "STRATEGIST"}
    a = svc.assign_agent(
        run_id="run-ds-1",
        requested_agent_id=None,
        stage="planning",
        context={"task_type": "data_science"},
        requested_by=requested_by,
    )
    assert a.active_agent.agent_id == "data_science"


@pytest.mark.parametrize(
    ("content", "metadata", "expect"),
    [
        ("Show dashboard for velocity", {}, True),
        ("List open bugs", {}, False),
        ("What is p-value?", {}, True),
        ("Hello", {"principal_data_science": True}, True),
        ("Hello", {"function_key": "data_science"}, True),
        ("Hello", {}, False),
    ],
)
def test_should_inject_principal_ds_guidance(
    content: str,
    metadata: dict,
    expect: bool,
) -> None:
    req = ReplyRequest(
        conversation_id="c1",
        user_message_id="m1",
        user_message_content=content,
        user_id="u1",
        metadata=metadata,
    )
    assert ConversationReplyService._should_inject_principal_ds_guidance(req) is expect


def test_principal_ds_suffix_distinctive() -> None:
    assert "Principal data science operating mode" in PRINCIPAL_DS_SYSTEM_SUFFIX
    assert "behavior_principal_data_science_workflow" in PRINCIPAL_DS_SYSTEM_SUFFIX
