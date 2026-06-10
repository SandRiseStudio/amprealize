"""Plan approval flow for plan-only execution artifacts.

This service owns the lifecycle bridge from a draft plan artifact to a separate
execution run. It keeps revision/discard auditable on the artifact and starts
execution only after a plan is approved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

from .execution_gateway_contracts import (
    ExecutionGatewayResult,
    ExecutionIntent,
    ExecutionRequest,
    NewExecutionMode,
    OutputTarget,
)
from .plan_artifact_contracts import PlanArtifact


class PlanArtifactRepository(Protocol):
    """Persistence boundary for plan artifacts."""

    def get(self, plan_artifact_id: str) -> Optional[PlanArtifact]:
        """Return a plan artifact by ID, or None when not found."""

    def save(self, plan_artifact: PlanArtifact) -> None:
        """Persist a plan artifact mutation."""


class InMemoryPlanArtifactRepository:
    """Simple repository for tests and local gateway wiring."""

    def __init__(self) -> None:
        self._artifacts: Dict[str, PlanArtifact] = {}

    def get(self, plan_artifact_id: str) -> Optional[PlanArtifact]:
        return self._artifacts.get(plan_artifact_id)

    def save(self, plan_artifact: PlanArtifact) -> None:
        self._artifacts[plan_artifact.plan_artifact_id] = plan_artifact


@dataclass
class PlanExecutionStartResult:
    """Result of approving a plan and starting a separate execution run."""

    plan_artifact: PlanArtifact
    execution_result: ExecutionGatewayResult

    @property
    def execution_run_id(self) -> Optional[str]:
        return self.execution_result.run_id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_artifact": self.plan_artifact.to_dict(),
            "execution": {
                "success": self.execution_result.success,
                "run_id": self.execution_result.run_id,
                "cycle_id": self.execution_result.cycle_id,
                "intent": self.execution_result.intent.value,
                "queue_job_id": self.execution_result.queue_job_id,
                "message": self.execution_result.message,
                "error": self.execution_result.error,
            },
        }


class PlanApprovalService:
    """Approve, revise, discard, and execute plan artifacts."""

    def __init__(
        self,
        *,
        repository: PlanArtifactRepository,
        execution_gateway: Any,
    ) -> None:
        self._repository = repository
        self._execution_gateway = execution_gateway

    def approve_plan(self, *, plan_artifact_id: str, approved_by: str) -> PlanArtifact:
        artifact = self._get_required(plan_artifact_id)
        artifact.approve(approved_by=approved_by)
        self._repository.save(artifact)
        return artifact

    def revise_plan(
        self,
        *,
        plan_artifact_id: str,
        content: str,
        revised_by: str,
        summary: str = "",
        source_run_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PlanArtifact:
        artifact = self._get_required(plan_artifact_id)
        artifact.revise(
            content=content,
            summary=summary,
            revised_by=revised_by,
            source_run_id=source_run_id,
            metadata=metadata,
        )
        self._repository.save(artifact)
        return artifact

    def discard_plan(self, *, plan_artifact_id: str, discarded_by: str) -> PlanArtifact:
        artifact = self._get_required(plan_artifact_id)
        artifact.discard(discarded_by=discarded_by)
        self._repository.save(artifact)
        return artifact

    async def approve_and_start_execution(
        self,
        *,
        plan_artifact_id: str,
        approved_by: str,
        surface: str = "api",
        message_id: Optional[str] = None,
        mode_override: Optional[NewExecutionMode] = None,
        output_target_override: Optional[OutputTarget] = None,
        model_override: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        policy_context: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PlanExecutionStartResult:
        artifact = self.approve_plan(
            plan_artifact_id=plan_artifact_id,
            approved_by=approved_by,
        )
        if not artifact.can_start_execution:
            raise ValueError("Only approved plan artifacts can start execution")

        execution_request = self._to_execution_request(
            artifact=artifact,
            approved_by=approved_by,
            surface=surface,
            message_id=message_id,
            mode_override=mode_override,
            output_target_override=output_target_override,
            model_override=model_override,
            idempotency_key=idempotency_key,
            policy_context=policy_context,
            metadata=metadata,
        )
        execution_result = await self._execution_gateway.execute(execution_request)
        if not execution_result.success:
            raise ValueError(
                execution_result.error
                or execution_result.message
                or "Plan execution start failed"
            )
        if not execution_result.run_id:
            raise ValueError("Plan execution start did not return a run_id")

        artifact.mark_executed(execution_run_id=execution_result.run_id)
        self._repository.save(artifact)
        return PlanExecutionStartResult(
            plan_artifact=artifact,
            execution_result=execution_result,
        )

    def _to_execution_request(
        self,
        *,
        artifact: PlanArtifact,
        approved_by: str,
        surface: str,
        message_id: Optional[str],
        mode_override: Optional[NewExecutionMode],
        output_target_override: Optional[OutputTarget],
        model_override: Optional[str],
        idempotency_key: Optional[str],
        policy_context: Optional[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]],
    ) -> ExecutionRequest:
        plan_context = {
            "plan_artifact_id": artifact.plan_artifact_id,
            "plan_version": artifact.current_version,
            "source_run_id": artifact.source_run_id,
            "approved_by": approved_by,
        }
        request_metadata = {
            "plan_artifact_id": artifact.plan_artifact_id,
            "plan_version": artifact.current_version,
            "source_plan_run_id": artifact.source_run_id,
            **dict(metadata or {}),
        }
        return ExecutionRequest(
            work_item_id=artifact.work_item_id,
            project_id=artifact.project_id,
            org_id=artifact.org_id,
            user_id=approved_by,
            surface=surface,
            conversation_id=artifact.conversation_id,
            message_id=message_id or artifact.message_id,
            mode_override=mode_override,
            output_target_override=output_target_override,
            model_override=model_override,
            agent_id_override=artifact.agent_id,
            intent=ExecutionIntent.EXECUTE,
            idempotency_key=idempotency_key,
            policy_context={
                **dict(policy_context or {}),
                "approved_plan": plan_context,
            },
            approved_by=approved_by,
            plan_artifact_id=artifact.plan_artifact_id,
            metadata=request_metadata,
        )

    def _get_required(self, plan_artifact_id: str) -> PlanArtifact:
        artifact = self._repository.get(plan_artifact_id)
        if artifact is None:
            raise ValueError(f"Plan artifact {plan_artifact_id} not found")
        return artifact
