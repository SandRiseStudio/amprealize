"""Data contracts for AgentReviewService - multi-agent review and approval workflows."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class ReviewStatus(str, Enum):
    """Review workflow status."""
    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"
    ESCALATED = "escalated"


class ReviewType(str, Enum):
    """Types of reviews that can be performed."""
    BEHAVIOR_APPROVAL = "behavior_approval"
    WORKFLOW_REVIEW = "workflow_review"
    CODE_REVIEW = "code_review"
    POLICY_REVIEW = "policy_review"
    QUALITY_ASSESSMENT = "quality_assessment"


class ReviewerRole(str, Enum):
    """Roles that reviewers can have in the workflow."""
    STRATEGIST = "strategist"
    TEACHER = "teacher"
    STUDENT = "student"
    REVIEWER = "reviewer"
    APPROVER = "approver"
    ADMIN = "admin"


@dataclass
class ReviewAssignment:
    """Assignment of a review to a specific agent/reviewer."""
    assignment_id: str
    review_id: str
    reviewer_agent_id: str
    reviewer_role: ReviewerRole
    assigned_at: datetime
    due_date: Optional[datetime]
    priority: int = 1
    completed_at: Optional[datetime] = None
    status: ReviewStatus = ReviewStatus.PENDING
    comments: Optional[str] = None
    score: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "assignment_id": self.assignment_id,
            "review_id": self.review_id,
            "reviewer_agent_id": self.reviewer_agent_id,
            "reviewer_role": self.reviewer_role.value,
            "assigned_at": self.assigned_at.isoformat(),
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "priority": self.priority,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status.value,
            "comments": self.comments,
            "score": self.score,
        }


@dataclass
class ReviewWorkflow:
    """Defines the workflow for a review process."""
    workflow_id: str
    name: str
    review_type: ReviewType
    required_roles: List[ReviewerRole]
    approval_threshold: float
    escalation_rules: Dict[str, Any]
    created_at: datetime
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "review_type": self.review_type.value,
            "required_roles": [role.value for role in self.required_roles],
            "approval_threshold": self.approval_threshold,
            "escalation_rules": self.escalation_rules,
            "created_at": self.created_at.isoformat(),
            "is_active": self.is_active,
        }


@dataclass
class Review:
    """Main review entity tracking the entire review process."""
    review_id: str
    title: str
    description: str
    review_type: ReviewType
    workflow_id: str
    target_id: str  # ID of the item being reviewed (behavior_id, workflow_id, etc.)
    created_by: str
    created_at: datetime
    status: ReviewStatus
    metadata: Dict[str, Any]
    due_date: Optional[datetime] = None
    priority: int = 1
    assignments: Optional[List[ReviewAssignment]] = None

    def __post_init__(self):
        if self.assignments is None:
            self.assignments = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "review_id": self.review_id,
            "title": self.title,
            "description": self.description,
            "review_type": self.review_type.value,
            "workflow_id": self.workflow_id,
            "target_id": self.target_id,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "status": self.status.value,
            "metadata": self.metadata,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "priority": self.priority,
            "assignments": [assignment.to_dict() for assignment in (self.assignments or [])],
        }


@dataclass
class ReviewComment:
    """Comment or feedback on a review."""
    comment_id: str
    review_id: str
    assignment_id: str
    author_agent_id: str
    content: str
    created_at: datetime
    comment_type: str = "general"  # general, approval, rejection, change_request
    is_resolution: bool = False
    parent_comment_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "comment_id": self.comment_id,
            "review_id": self.review_id,
            "assignment_id": self.assignment_id,
            "author_agent_id": self.author_agent_id,
            "content": self.content,
            "created_at": self.created_at.isoformat(),
            "comment_type": self.comment_type,
            "is_resolution": self.is_resolution,
            "parent_comment_id": self.parent_comment_id,
        }


@dataclass
class ReviewDecision:
    """Final decision on a review."""
    decision_id: str
    review_id: str
    final_status: ReviewStatus
    decision_rationale: str
    decided_by: str
    decided_at: datetime
    approval_score: float
    confidence_level: float
    conditions: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "review_id": self.review_id,
            "final_status": self.final_status.value,
            "decision_rationale": self.decision_rationale,
            "decided_by": self.decided_by,
            "decided_at": self.decided_at.isoformat(),
            "approval_score": self.approval_score,
            "confidence_level": self.confidence_level,
            "conditions": self.conditions,
        }


@dataclass
class CreateReviewRequest:
    """Request to create a new review."""
    title: str
    description: str
    review_type: ReviewType
    workflow_id: str
    target_id: str
    created_by: str
    due_date: Optional[datetime] = None
    priority: int = 1
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class CreateWorkflowRequest:
    """Request to create a new review workflow."""
    name: str
    review_type: ReviewType
    required_roles: List[ReviewerRole]
    approval_threshold: float
    escalation_rules: Dict[str, Any]


@dataclass
class ReviewAssignmentRequest:
    """Request to assign reviewers to a review."""
    review_id: str
    assignments: List[Dict[str, Any]]  # reviewer_agent_id, reviewer_role, due_date


@dataclass
class ReviewCommentRequest:
    """Request to add a comment to a review."""
    review_id: str
    assignment_id: str
    author_agent_id: str
    content: str
    comment_type: str = "general"
    parent_comment_id: Optional[str] = None


@dataclass
class ReviewDecisionRequest:
    """Request to make a final decision on a review."""
    review_id: str
    final_status: ReviewStatus
    decision_rationale: str
    decided_by: str
    approval_score: float
    confidence_level: float
    conditions: Optional[List[str]] = None


@dataclass
class ReviewMetrics:
    """Metrics and analytics for review performance."""
    review_id: str
    total_reviewers: int
    completed_reviews: int
    average_review_time_hours: float
    approval_rate: float
    quality_score: float
    escalation_count: int
    final_decision_time: Optional[datetime]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "review_id": self.review_id,
            "total_reviewers": self.total_reviewers,
            "completed_reviews": self.completed_reviews,
            "average_review_time_hours": self.average_review_time_hours,
            "approval_rate": self.approval_rate,
            "quality_score": self.quality_score,
            "escalation_count": self.escalation_count,
            "final_decision_time": self.final_decision_time.isoformat() if self.final_decision_time else None,
        }
