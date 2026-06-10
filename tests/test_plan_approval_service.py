"""Tests for plan artifact approval and execution start flow."""

from __future__ import annotations

import pytest

from amprealize.execution_gateway_contracts import (
    ExecutionGatewayResult,
    ExecutionIntent,
    NewExecutionMode,
    OutputTarget,
)
from amprealize.plan_approval_service import (
    InMemoryPlanArtifactRepository,
    PlanApprovalService,
)
from amprealize.plan_artifact_contracts import PlanArtifact, PlanArtifactStatus

pytestmark = pytest.mark.unit


class FakeGateway:
    def __init__(self, *, success: bool = True) -> None:
        self.requests = []
        self.success = success

    async def execute(self, request):
        self.requests.append(request)
        return ExecutionGatewayResult(
            success=self.success,
            run_id="run-exec-1" if self.success else None,
            cycle_id="cycle-exec-1" if self.success else None,
            intent=request.intent,
            message="Execution queued" if self.success else "Execution failed",
            error=None if self.success else "blocked",
        )


def _make_repository_with_plan() -> tuple[InMemoryPlanArtifactRepository, PlanArtifact]:
    repository = InMemoryPlanArtifactRepository()
    artifact = PlanArtifact.create(
        work_item_id="guideai-1056",
        project_id="proj-1",
        org_id="org-1",
        created_by="user-1",
        agent_id="agent-1",
        conversation_id="conv-1",
        message_id="msg-plan",
        source_run_id="run-plan-1",
        content="Plan content",
        summary="Plan summary",
    )
    repository.save(artifact)
    return repository, artifact


def test_revise_plan_preserves_history_and_resets_approval():
    repository, artifact = _make_repository_with_plan()
    service = PlanApprovalService(
        repository=repository,
        execution_gateway=FakeGateway(),
    )
    service.approve_plan(
        plan_artifact_id=artifact.plan_artifact_id,
        approved_by="approver-1",
    )

    revised = service.revise_plan(
        plan_artifact_id=artifact.plan_artifact_id,
        content="Revised plan",
        summary="Updated",
        revised_by="user-2",
        metadata={"reason": "scope changed"},
    )

    assert revised.status == PlanArtifactStatus.DRAFT
    assert revised.current_version == 2
    assert len(revised.versions) == 2
    assert revised.approved_by is None
    assert revised.current.content == "Revised plan"
    assert revised.current.metadata["reason"] == "scope changed"


def test_discard_plan_blocks_execution_but_preserves_artifact():
    repository, artifact = _make_repository_with_plan()
    service = PlanApprovalService(
        repository=repository,
        execution_gateway=FakeGateway(),
    )

    discarded = service.discard_plan(
        plan_artifact_id=artifact.plan_artifact_id,
        discarded_by="user-1",
    )

    assert discarded.status == PlanArtifactStatus.DISCARDED
    assert discarded.discarded_by == "user-1"
    assert discarded.current.content == "Plan content"
    with pytest.raises(ValueError, match="Cannot approve a discarded"):
        service.approve_plan(
            plan_artifact_id=artifact.plan_artifact_id,
            approved_by="approver-1",
        )


@pytest.mark.asyncio
async def test_approve_and_start_execution_links_new_run_to_plan_artifact():
    repository, artifact = _make_repository_with_plan()
    gateway = FakeGateway()
    service = PlanApprovalService(
        repository=repository,
        execution_gateway=gateway,
    )

    result = await service.approve_and_start_execution(
        plan_artifact_id=artifact.plan_artifact_id,
        approved_by="approver-1",
        surface="mcp",
        message_id="msg-approval",
        mode_override=NewExecutionMode.CONTAINER_ISOLATED,
        output_target_override=OutputTarget.PULL_REQUEST,
        model_override="claude-opus-4-6",
        idempotency_key="idem-plan-1",
        policy_context={"approval_path": "chat"},
        metadata={"request_source": "plan_card"},
    )

    execution_request = gateway.requests[0]

    assert result.execution_run_id == "run-exec-1"
    assert result.plan_artifact.status == PlanArtifactStatus.EXECUTED
    assert result.plan_artifact.execution_run_id == "run-exec-1"
    assert execution_request.intent == ExecutionIntent.EXECUTE
    assert execution_request.plan_artifact_id == artifact.plan_artifact_id
    assert execution_request.work_item_id == "guideai-1056"
    assert execution_request.project_id == "proj-1"
    assert execution_request.org_id == "org-1"
    assert execution_request.user_id == "approver-1"
    assert execution_request.surface == "mcp"
    assert execution_request.conversation_id == "conv-1"
    assert execution_request.message_id == "msg-approval"
    assert execution_request.agent_id_override == "agent-1"
    assert execution_request.mode_override == NewExecutionMode.CONTAINER_ISOLATED
    assert execution_request.output_target_override == OutputTarget.PULL_REQUEST
    assert execution_request.model_override == "claude-opus-4-6"
    assert execution_request.idempotency_key == "idem-plan-1"
    assert execution_request.policy_context["approval_path"] == "chat"
    assert (
        execution_request.policy_context["approved_plan"]["plan_artifact_id"]
        == artifact.plan_artifact_id
    )
    assert execution_request.metadata["request_source"] == "plan_card"


@pytest.mark.asyncio
async def test_failed_execution_start_leaves_plan_approved_not_executed():
    repository, artifact = _make_repository_with_plan()
    service = PlanApprovalService(
        repository=repository,
        execution_gateway=FakeGateway(success=False),
    )

    with pytest.raises(ValueError, match="blocked"):
        await service.approve_and_start_execution(
            plan_artifact_id=artifact.plan_artifact_id,
            approved_by="approver-1",
        )

    saved = repository.get(artifact.plan_artifact_id)
    assert saved is not None
    assert saved.status == PlanArtifactStatus.APPROVED
    assert saved.execution_run_id is None
