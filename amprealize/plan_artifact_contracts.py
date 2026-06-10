"""Plan artifact contracts for plan-only governed execution.

Plan artifacts are durable drafts produced by plan-only gateway requests. They
link the user-visible plan to its work item, chat message, agent, source run,
and eventual execution run without granting execution permission by themselves.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_plan_artifact_id() -> str:
    return f"plan-{uuid.uuid4().hex[:12]}"


class PlanArtifactStatus(str, Enum):
    """Lifecycle status for a durable plan artifact."""

    DRAFT = "draft"
    APPROVED = "approved"
    DISCARDED = "discarded"
    EXECUTED = "executed"


@dataclass
class PlanArtifactVersion:
    """One immutable version of a generated or revised execution plan."""

    version: int
    content: str
    summary: str = ""
    created_by: str = ""
    created_at: str = field(default_factory=_now_iso)
    source_run_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "content": self.content,
            "summary": self.summary,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "source_run_id": self.source_run_id,
            "metadata": dict(self.metadata),
        }


@dataclass
class PlanArtifact:
    """Durable plan linked to chat, work item, agent, and execution records."""

    plan_artifact_id: str
    work_item_id: str
    project_id: str
    created_by: str
    agent_id: Optional[str] = None
    org_id: Optional[str] = None
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    source_run_id: Optional[str] = None
    execution_run_id: Optional[str] = None
    status: PlanArtifactStatus = PlanArtifactStatus.DRAFT
    current_version: int = 1
    versions: List[PlanArtifactVersion] = field(default_factory=list)
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    discarded_by: Optional[str] = None
    discarded_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    @classmethod
    def create(
        cls,
        *,
        work_item_id: str,
        project_id: str,
        created_by: str,
        content: str,
        summary: str = "",
        agent_id: Optional[str] = None,
        org_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        message_id: Optional[str] = None,
        source_run_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "PlanArtifact":
        version = PlanArtifactVersion(
            version=1,
            content=content,
            summary=summary,
            created_by=created_by,
            source_run_id=source_run_id,
        )
        return cls(
            plan_artifact_id=_new_plan_artifact_id(),
            work_item_id=work_item_id,
            project_id=project_id,
            org_id=org_id,
            created_by=created_by,
            agent_id=agent_id,
            conversation_id=conversation_id,
            message_id=message_id,
            source_run_id=source_run_id,
            versions=[version],
            metadata=dict(metadata or {}),
        )

    @property
    def current(self) -> PlanArtifactVersion:
        if not self.versions:
            raise ValueError("Plan artifact has no versions")
        return self.versions[-1]

    @property
    def can_start_execution(self) -> bool:
        return self.status == PlanArtifactStatus.APPROVED

    def revise(
        self,
        *,
        content: str,
        summary: str = "",
        revised_by: str,
        source_run_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PlanArtifactVersion:
        if self.status in {PlanArtifactStatus.DISCARDED, PlanArtifactStatus.EXECUTED}:
            raise ValueError(f"Cannot revise a {self.status.value} plan artifact")

        next_version = self.current_version + 1
        version = PlanArtifactVersion(
            version=next_version,
            content=content,
            summary=summary,
            created_by=revised_by,
            source_run_id=source_run_id or self.source_run_id,
            metadata=dict(metadata or {}),
        )
        self.versions.append(version)
        self.current_version = next_version
        self.status = PlanArtifactStatus.DRAFT
        self.approved_by = None
        self.approved_at = None
        self.updated_at = _now_iso()
        return version

    def approve(self, *, approved_by: str) -> None:
        if self.status == PlanArtifactStatus.DISCARDED:
            raise ValueError("Cannot approve a discarded plan artifact")
        if self.status == PlanArtifactStatus.EXECUTED:
            raise ValueError("Cannot approve an executed plan artifact")

        self.status = PlanArtifactStatus.APPROVED
        self.approved_by = approved_by
        self.approved_at = _now_iso()
        self.updated_at = self.approved_at

    def discard(self, *, discarded_by: str) -> None:
        if self.status == PlanArtifactStatus.EXECUTED:
            raise ValueError("Cannot discard an executed plan artifact")

        self.status = PlanArtifactStatus.DISCARDED
        self.discarded_by = discarded_by
        self.discarded_at = _now_iso()
        self.updated_at = self.discarded_at

    def mark_executed(self, *, execution_run_id: str) -> None:
        if not self.can_start_execution:
            raise ValueError("Only approved plan artifacts can start execution")

        self.status = PlanArtifactStatus.EXECUTED
        self.execution_run_id = execution_run_id
        self.updated_at = _now_iso()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_artifact_id": self.plan_artifact_id,
            "work_item_id": self.work_item_id,
            "project_id": self.project_id,
            "org_id": self.org_id,
            "created_by": self.created_by,
            "agent_id": self.agent_id,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "source_run_id": self.source_run_id,
            "execution_run_id": self.execution_run_id,
            "status": self.status.value,
            "current_version": self.current_version,
            "versions": [version.to_dict() for version in self.versions],
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "discarded_by": self.discarded_by,
            "discarded_at": self.discarded_at,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
