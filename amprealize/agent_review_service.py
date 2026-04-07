"""AgentReviewService - multi-agent review and approval workflow service."""

from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import logging
import uuid

from .agent_review_contracts import (
    ReviewStatus, ReviewType, ReviewerRole, ReviewAssignment, ReviewWorkflow,
    Review, ReviewComment, ReviewDecision, CreateReviewRequest, CreateWorkflowRequest,
    ReviewAssignmentRequest, ReviewCommentRequest, ReviewDecisionRequest, ReviewMetrics
)
from .action_contracts import Actor
from .telemetry import TelemetryClient


class AgentReviewService:
    """Multi-agent review and approval workflow service."""

    def __init__(self, telemetry: Optional[TelemetryClient] = None) -> None:
        """Initialize AgentReviewService."""
        self._telemetry = telemetry or TelemetryClient.noop()
        self._reviews: Dict[str, Review] = {}
        self._workflows: Dict[str, ReviewWorkflow] = {}
        self._comments: Dict[str, ReviewComment] = {}
        self._decisions: Dict[str, ReviewDecision] = {}
        self._assignments: Dict[str, ReviewAssignment] = {}

        # Create default workflows
        self._create_default_workflows()

        self._logger = logging.getLogger(__name__)

    def create_workflow(self, request: CreateWorkflowRequest) -> ReviewWorkflow:
        """Create a new review workflow."""
        workflow_id = str(uuid.uuid4())

        workflow = ReviewWorkflow(
            workflow_id=workflow_id,
            name=request.name,
            review_type=request.review_type,
            required_roles=request.required_roles,
            approval_threshold=request.approval_threshold,
            escalation_rules=request.escalation_rules,
            created_at=datetime.utcnow()
        )

        self._workflows[workflow_id] = workflow

        self._emit_telemetry("workflow_created", {
            "workflow_id": workflow_id,
            "name": request.name,
            "review_type": request.review_type.value
        })

        return workflow

    def create_review(self, request: CreateReviewRequest, actor: Actor) -> Review:
        """Create a new review request."""
        # Validate workflow exists
        if request.workflow_id not in self._workflows:
            raise ValueError(f"Workflow {request.workflow_id} not found")

        workflow = self._workflows[request.workflow_id]

        # Create review
        review_id = str(uuid.uuid4())
        actor_id = actor.id if hasattr(actor, 'id') else getattr(actor, 'actor_id', 'unknown')

        review = Review(
            review_id=review_id,
            title=request.title,
            description=request.description,
            review_type=request.review_type,
            workflow_id=request.workflow_id,
            target_id=request.target_id,
            created_by=actor_id,
            created_at=datetime.utcnow(),
            status=ReviewStatus.PENDING,
            metadata=request.metadata or {},
            due_date=request.due_date,
            priority=request.priority,
            assignments=[]
        )

        self._reviews[review_id] = review

        # Auto-assign reviewers based on workflow
        if workflow.required_roles:
            self._auto_assign_reviewers(review_id, workflow)

        self._emit_telemetry("review_created", {
            "review_id": review_id,
            "title": request.title,
            "review_type": request.review_type.value,
            "created_by": actor_id
        })

        return review

    def assign_reviewers(self, request: ReviewAssignmentRequest) -> List[ReviewAssignment]:
        """Assign reviewers to a review."""
        if request.review_id not in self._reviews:
            raise ValueError(f"Review {request.review_id} not found")

        review = self._reviews[request.review_id]
        assignments = []

        for assignment_data in request.assignments:
            assignment_id = str(uuid.uuid4())
            assignment = ReviewAssignment(
                assignment_id=assignment_id,
                review_id=request.review_id,
                reviewer_agent_id=assignment_data["reviewer_agent_id"],
                reviewer_role=ReviewerRole(assignment_data["reviewer_role"]),
                assigned_at=datetime.utcnow(),
                due_date=assignment_data.get("due_date"),
                priority=assignment_data.get("priority", 1)
            )

            self._assignments[assignment_id] = assignment
            assignments.append(assignment)
            review.assignments.append(assignment)

        # Update review status
        if review.status == ReviewStatus.PENDING:
            review.status = ReviewStatus.IN_REVIEW

        self._emit_telemetry("reviewers_assigned", {
            "review_id": request.review_id,
            "assignment_count": len(assignments)
        })

        return assignments

    def add_comment(self, request: ReviewCommentRequest) -> ReviewComment:
        """Add a comment to a review."""
        if request.review_id not in self._reviews:
            raise ValueError(f"Review {request.review_id} not found")

        comment_id = str(uuid.uuid4())
        comment = ReviewComment(
            comment_id=comment_id,
            review_id=request.review_id,
            assignment_id=request.assignment_id,
            author_agent_id=request.author_agent_id,
            content=request.content,
            created_at=datetime.utcnow(),
            comment_type=request.comment_type,
            parent_comment_id=request.parent_comment_id
        )

        self._comments[comment_id] = comment

        self._emit_telemetry("comment_added", {
            "comment_id": comment_id,
            "review_id": request.review_id,
            "author_agent_id": request.author_agent_id
        })

        return comment

    def complete_assignment(self, assignment_id: str, comments: str, score: float) -> bool:
        """Mark a review assignment as completed."""
        if assignment_id not in self._assignments:
            return False

        assignment = self._assignments[assignment_id]
        assignment.status = ReviewStatus.APPROVED if score >= 0.7 else ReviewStatus.REJECTED
        assignment.completed_at = datetime.utcnow()
        assignment.comments = comments
        assignment.score = score

        # Check if all assignments are completed
        review = self._reviews[assignment.review_id]
        assignments_list = review.assignments or []
        if all(a.status in [ReviewStatus.APPROVED, ReviewStatus.REJECTED] for a in assignments_list):
            self._finalize_review(review.review_id)

        self._emit_telemetry("assignment_completed", {
            "assignment_id": assignment_id,
            "score": score,
            "status": assignment.status.value
        })

        return True

    def make_decision(self, request: ReviewDecisionRequest) -> ReviewDecision:
        """Make a final decision on a review."""
        if request.review_id not in self._reviews:
            raise ValueError(f"Review {request.review_id} not found")

        review = self._reviews[request.review_id]

        decision_id = str(uuid.uuid4())
        decision = ReviewDecision(
            decision_id=decision_id,
            review_id=request.review_id,
            final_status=request.final_status,
            decision_rationale=request.decision_rationale,
            decided_by=request.decided_by,
            decided_at=datetime.utcnow(),
            approval_score=request.approval_score,
            confidence_level=request.confidence_level,
            conditions=request.conditions or []
        )

        self._decisions[decision_id] = decision
        review.status = request.final_status

        self._emit_telemetry("review_decided", {
            "review_id": request.review_id,
            "decision_id": decision_id,
            "final_status": request.final_status.value,
            "approval_score": request.approval_score
        })

        return decision

    def get_review(self, review_id: str) -> Optional[Review]:
        """Get a specific review."""
        return self._reviews.get(review_id)

    def list_reviews(self, status: Optional[ReviewStatus] = None,
                    review_type: Optional[ReviewType] = None) -> List[Review]:
        """List reviews with optional filters."""
        reviews = list(self._reviews.values())

        if status:
            reviews = [r for r in reviews if r.status == status]

        if review_type:
            reviews = [r for r in reviews if r.review_type == review_type]

        return reviews

    def get_workflow(self, workflow_id: str) -> Optional[ReviewWorkflow]:
        """Get a specific workflow."""
        return self._workflows.get(workflow_id)

    def list_workflows(self, review_type: Optional[ReviewType] = None) -> List[ReviewWorkflow]:
        """List workflows with optional filter."""
        workflows = list(self._workflows.values())

        if review_type:
            workflows = [w for w in workflows if w.review_type == review_type]

        return workflows

    def get_review_comments(self, review_id: str) -> List[ReviewComment]:
        """Get all comments for a review."""
        return [c for c in self._comments.values() if c.review_id == review_id]

    def get_review_decision(self, review_id: str) -> Optional[ReviewDecision]:
        """Get the final decision for a review."""
        for decision in self._decisions.values():
            if decision.review_id == review_id:
                return decision
        return None

    def calculate_metrics(self, review_id: str) -> ReviewMetrics:
        """Calculate metrics for a review."""
        if review_id not in self._reviews:
            raise ValueError(f"Review {review_id} not found")

        review = self._reviews[review_id]
        assignments_list = review.assignments or []
        total_reviewers = len(assignments_list)
        completed_reviews = sum(1 for a in assignments_list
                              if a.status in [ReviewStatus.APPROVED, ReviewStatus.REJECTED])

        # Calculate average review time
        review_times = []
        for assignment in assignments_list:
            if assignment.completed_at:
                duration = (assignment.completed_at - assignment.assigned_at).total_seconds() / 3600
                review_times.append(duration)

        avg_time = sum(review_times) / len(review_times) if review_times else 0.0

        # Calculate approval rate
        approved = sum(1 for a in assignments_list if a.status == ReviewStatus.APPROVED)
        approval_rate = approved / total_reviewers if total_reviewers > 0 else 0.0

        # Calculate quality score
        scores = [a.score for a in assignments_list if a.score is not None]
        quality_score = sum(scores) / len(scores) if scores else 0.0

        # Check for escalations
        escalation_count = sum(1 for a in assignments_list if a.status == ReviewStatus.ESCALATED)

        # Final decision time
        decision = self.get_review_decision(review_id)
        final_decision_time = decision.decided_at if decision else None

        return ReviewMetrics(
            review_id=review_id,
            total_reviewers=total_reviewers,
            completed_reviews=completed_reviews,
            average_review_time_hours=avg_time,
            approval_rate=approval_rate,
            quality_score=quality_score,
            escalation_count=escalation_count,
            final_decision_time=final_decision_time
        )

    def _create_default_workflows(self) -> None:
        """Create default review workflows."""
        # Behavior approval workflow
        behavior_workflow = ReviewWorkflow(
            workflow_id=str(uuid.uuid4()),
            name="Standard Behavior Approval",
            review_type=ReviewType.BEHAVIOR_APPROVAL,
            required_roles=[ReviewerRole.REVIEWER, ReviewerRole.APPROVER],
            approval_threshold=0.8,
            escalation_rules={"timeout_hours": 48, "escalate_to": ReviewerRole.ADMIN},
            created_at=datetime.utcnow()
        )
        self._workflows[behavior_workflow.workflow_id] = behavior_workflow

        # Code review workflow
        code_workflow = ReviewWorkflow(
            workflow_id=str(uuid.uuid4()),
            name="Code Review Process",
            review_type=ReviewType.CODE_REVIEW,
            required_roles=[ReviewerRole.TEACHER, ReviewerRole.REVIEWER],
            approval_threshold=0.7,
            escalation_rules={"timeout_hours": 24, "escalate_to": ReviewerRole.ADMIN},
            created_at=datetime.utcnow()
        )
        self._workflows[code_workflow.workflow_id] = code_workflow

    def _auto_assign_reviewers(self, review_id: str, workflow: ReviewWorkflow) -> None:
        """Auto-assign reviewers based on workflow requirements."""
        review = self._reviews[review_id]

        for role in workflow.required_roles:
            # Simulate finding available agents for this role
            available_agents = self._find_available_agents(role)
            if available_agents:
                agent_id = available_agents[0]  # Pick first available

                assignment_id = str(uuid.uuid4())
                assignment = ReviewAssignment(
                    assignment_id=assignment_id,
                    review_id=review_id,
                    reviewer_agent_id=agent_id,
                    reviewer_role=role,
                    assigned_at=datetime.utcnow(),
                    due_date=datetime.utcnow() + timedelta(hours=24),
                    priority=1
                )

                self._assignments[assignment_id] = assignment
                review.assignments.append(assignment)

        if review.assignments:
            review.status = ReviewStatus.IN_REVIEW

    def _find_available_agents(self, role: ReviewerRole) -> List[str]:
        """Find available agents for a given role (simplified)."""
        # In a real implementation, this would query the agent registry
        agent_maps = {
            ReviewerRole.REVIEWER: ["agent_reviewer_1", "agent_reviewer_2"],
            ReviewerRole.APPROVER: ["agent_approver_1"],
            ReviewerRole.TEACHER: ["agent_teacher_1", "agent_teacher_2"],
            ReviewerRole.STRATEGIST: ["agent_strategist_1"],
            ReviewerRole.ADMIN: ["agent_admin_1"]
        }
        return agent_maps.get(role, ["agent_default"])

    def _finalize_review(self, review_id: str) -> None:
        """Finalize a review when all assignments are complete."""
        review = self._reviews[review_id]
        assignments_list = review.assignments or []

        # Calculate overall score
        scores = [a.score for a in assignments_list if a.score is not None]
        if scores:
            avg_score = sum(scores) / len(scores)

            if avg_score >= 0.8:
                review.status = ReviewStatus.APPROVED
            elif avg_score >= 0.5:
                review.status = ReviewStatus.CHANGES_REQUESTED
            else:
                review.status = ReviewStatus.REJECTED

        self._emit_telemetry("review_finalized", {
            "review_id": review_id,
            "final_status": review.status.value,
            "completion_rate": len([a for a in assignments_list if a.status != ReviewStatus.PENDING]) / len(assignments_list) if assignments_list else 0
        })

    def _emit_telemetry(self, event_type: str, data: Dict[str, Any]) -> None:
        """Emit telemetry event."""
        try:
            self._telemetry.emit_event(
                event_type=event_type,
                payload=data
            )
        except Exception as e:
            self._logger.warning(f"Failed to emit telemetry: {e}")

    def get_assignments_for_reviewer(self, reviewer_agent_id: str) -> List[ReviewAssignment]:
        """Get all assignments for a specific reviewer."""
        return [a for a in self._assignments.values() if a.reviewer_agent_id == reviewer_agent_id]
