"""Tests for plan-only execution artifact contracts."""

from __future__ import annotations

import pytest

from amprealize.plan_artifact_contracts import PlanArtifact, PlanArtifactStatus

pytestmark = pytest.mark.unit


def test_plan_artifact_create_links_work_item_chat_agent_and_source_run():
    artifact = PlanArtifact.create(
        work_item_id="guideai-1054",
        project_id="proj-1",
        org_id="org-1",
        created_by="user-1",
        agent_id="agent-1",
        conversation_id="conv-1",
        message_id="msg-1",
        source_run_id="run-plan",
        content="1. Inspect gateway.\n2. Add tests.",
        summary="Gateway plan",
    )

    payload = artifact.to_dict()

    assert artifact.plan_artifact_id.startswith("plan-")
    assert artifact.status == PlanArtifactStatus.DRAFT
    assert artifact.can_start_execution is False
    assert payload["work_item_id"] == "guideai-1054"
    assert payload["conversation_id"] == "conv-1"
    assert payload["message_id"] == "msg-1"
    assert payload["agent_id"] == "agent-1"
    assert payload["source_run_id"] == "run-plan"
    assert payload["current_version"] == 1
    assert payload["versions"][0]["content"].startswith("1. Inspect")


def test_plan_artifact_revision_preserves_version_history_and_resets_approval():
    artifact = PlanArtifact.create(
        work_item_id="guideai-1054",
        project_id="proj-1",
        created_by="user-1",
        content="Initial plan",
    )
    artifact.approve(approved_by="approver-1")

    version = artifact.revise(
        content="Revised plan",
        summary="Updated",
        revised_by="user-2",
    )

    assert version.version == 2
    assert artifact.current_version == 2
    assert len(artifact.versions) == 2
    assert artifact.status == PlanArtifactStatus.DRAFT
    assert artifact.approved_by is None
    assert artifact.current.content == "Revised plan"


def test_plan_artifact_approval_and_execution_transition():
    artifact = PlanArtifact.create(
        work_item_id="guideai-1054",
        project_id="proj-1",
        created_by="user-1",
        content="Plan",
    )

    artifact.approve(approved_by="approver-1")
    assert artifact.status == PlanArtifactStatus.APPROVED
    assert artifact.can_start_execution is True

    artifact.mark_executed(execution_run_id="run-exec")
    assert artifact.status == PlanArtifactStatus.EXECUTED
    assert artifact.execution_run_id == "run-exec"
    assert artifact.can_start_execution is False


def test_discarded_plan_remains_auditable_but_cannot_execute_or_revise():
    artifact = PlanArtifact.create(
        work_item_id="guideai-1054",
        project_id="proj-1",
        created_by="user-1",
        content="Plan",
    )

    artifact.discard(discarded_by="user-1")

    assert artifact.status == PlanArtifactStatus.DISCARDED
    assert artifact.discarded_by == "user-1"
    assert artifact.to_dict()["versions"][0]["content"] == "Plan"
    with pytest.raises(ValueError, match="Only approved"):
        artifact.mark_executed(execution_run_id="run-exec")
    with pytest.raises(ValueError, match="Cannot revise"):
        artifact.revise(content="New plan", revised_by="user-1")
