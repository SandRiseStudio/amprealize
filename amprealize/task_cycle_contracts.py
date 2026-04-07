"""
Task Cycle Contracts - Amprealize Execution Protocol (GEP) Data Models

Defines all data models for the 8-phase GEP task execution cycle:
PLANNING → CLARIFYING → ARCHITECTING → EXECUTING → TESTING → FIXING → VERIFYING → COMPLETING

Integration points:
- TaskService: Task management and assignment
- ReflectionService: Behavior extraction on test failures
- ActionService: Audit trail
- RunService: Execution tracking
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class CyclePhase(str, Enum):
    """GEP phase identifiers following the 8-phase cycle."""
    PLANNING = "planning"
    CLARIFYING = "clarifying"
    ARCHITECTING = "architecting"
    EXECUTING = "executing"
    TESTING = "testing"
    FIXING = "fixing"
    VERIFYING = "verifying"
    COMPLETING = "completing"
    # Terminal states
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class GateType(str, Enum):
    """Phase gate enforcement types."""
    NONE = "none"           # Auto-progress without notification
    SOFT = "soft"           # Auto-progress with notification
    STRICT = "strict"       # Requires explicit Entity B approval


class TimeoutPolicy(str, Enum):
    """Configurable timeout handling policies for Entity B responses."""
    PAUSE_WITH_NOTIFICATION = "pause_with_notification"  # Default - pause and notify
    AUTO_ESCALATE = "auto_escalate"                      # Escalate to backup reviewer
    PROCEED_WITH_ASSUMPTIONS = "proceed_with_assumptions"  # Document assumptions and continue


class TriggerType(str, Enum):
    """Types of phase transition triggers."""
    AUTO = "auto"           # Automatic progression
    APPROVAL = "approval"   # Entity B approval
    TIMEOUT = "timeout"     # Timeout policy applied
    MANUAL = "manual"       # Manual override
    FAILURE = "failure"     # Test or execution failure
    LOOP = "loop"           # Testing→Fixing loop


class ClarificationStatus(str, Enum):
    """Status of a clarification thread."""
    PENDING_RESPONSE = "pending_response"
    ANSWERED = "answered"
    TIMED_OUT = "timed_out"
    CLOSED = "closed"


class ReviewStatus(str, Enum):
    """Architecture document review status."""
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REVISION_REQUESTED = "revision_requested"


# Phase gate configuration - defines which phases require strict approval
PHASE_GATES: Dict[CyclePhase, GateType] = {
    CyclePhase.PLANNING: GateType.NONE,
    CyclePhase.CLARIFYING: GateType.SOFT,
    CyclePhase.ARCHITECTING: GateType.STRICT,   # Entity B must approve architecture
    CyclePhase.EXECUTING: GateType.NONE,
    CyclePhase.TESTING: GateType.SOFT,
    CyclePhase.FIXING: GateType.SOFT,           # Auto-loop with Testing
    CyclePhase.VERIFYING: GateType.STRICT,      # Entity B must verify
    CyclePhase.COMPLETING: GateType.STRICT,     # Entity B final acceptance
}


# Valid phase transitions - defines the state machine
VALID_TRANSITIONS: Dict[CyclePhase, List[CyclePhase]] = {
    CyclePhase.PLANNING: [CyclePhase.CLARIFYING, CyclePhase.ARCHITECTING, CyclePhase.CANCELLED, CyclePhase.FAILED],
    CyclePhase.CLARIFYING: [CyclePhase.CLARIFYING, CyclePhase.ARCHITECTING, CyclePhase.CANCELLED, CyclePhase.FAILED],
    CyclePhase.ARCHITECTING: [CyclePhase.EXECUTING, CyclePhase.CLARIFYING, CyclePhase.CANCELLED, CyclePhase.FAILED],
    CyclePhase.EXECUTING: [CyclePhase.TESTING, CyclePhase.CANCELLED, CyclePhase.FAILED],
    CyclePhase.TESTING: [CyclePhase.FIXING, CyclePhase.VERIFYING, CyclePhase.CANCELLED, CyclePhase.FAILED],
    CyclePhase.FIXING: [CyclePhase.TESTING, CyclePhase.CANCELLED, CyclePhase.FAILED],
    CyclePhase.VERIFYING: [CyclePhase.COMPLETING, CyclePhase.FIXING, CyclePhase.CANCELLED, CyclePhase.FAILED],
    CyclePhase.COMPLETING: [CyclePhase.COMPLETED, CyclePhase.CANCELLED, CyclePhase.FAILED],
    # Terminal states have no outgoing transitions
    CyclePhase.COMPLETED: [],
    CyclePhase.CANCELLED: [],
    CyclePhase.FAILED: [],
}


# Role mapping for each phase
PHASE_ROLES: Dict[CyclePhase, str] = {
    CyclePhase.PLANNING: "strategist",
    CyclePhase.CLARIFYING: "strategist",
    CyclePhase.ARCHITECTING: "strategist",
    CyclePhase.EXECUTING: "student",
    CyclePhase.TESTING: "student",
    CyclePhase.FIXING: "student",
    CyclePhase.VERIFYING: "teacher",
    CyclePhase.COMPLETING: "student",
}


@dataclass
class TimeoutConfig:
    """Timeout configuration for GEP cycles."""
    clarification_timeout_hours: int = 24
    architecture_approval_timeout_hours: int = 48
    verification_timeout_hours: int = 24
    policy: TimeoutPolicy = TimeoutPolicy.PAUSE_WITH_NOTIFICATION
    escalation_contact_ids: List[str] = field(default_factory=list)
    max_escalation_attempts: int = 3

    def to_dict(self) -> Dict[str, Any]:
        return {
            "clarification_timeout_hours": self.clarification_timeout_hours,
            "architecture_approval_timeout_hours": self.architecture_approval_timeout_hours,
            "verification_timeout_hours": self.verification_timeout_hours,
            "policy": self.policy.value,
            "escalation_contact_ids": self.escalation_contact_ids,
            "max_escalation_attempts": self.max_escalation_attempts,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TimeoutConfig":
        return cls(
            clarification_timeout_hours=data.get("clarification_timeout_hours", 24),
            architecture_approval_timeout_hours=data.get("architecture_approval_timeout_hours", 48),
            verification_timeout_hours=data.get("verification_timeout_hours", 24),
            policy=TimeoutPolicy(data.get("policy", "pause_with_notification")),
            escalation_contact_ids=data.get("escalation_contact_ids", []),
            max_escalation_attempts=data.get("max_escalation_attempts", 3),
        )


@dataclass
class PhaseTransition:
    """Record of a phase change in the GEP cycle."""
    transition_id: str
    cycle_id: str
    from_phase: CyclePhase
    to_phase: CyclePhase
    triggered_by: str                       # agent_id or entity_id
    trigger_type: TriggerType
    gate_type: GateType
    timestamp: datetime
    notes: Optional[str] = None
    artifacts: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        cycle_id: str,
        from_phase: CyclePhase,
        to_phase: CyclePhase,
        triggered_by: str,
        trigger_type: TriggerType,
        notes: Optional[str] = None,
        artifacts: Optional[Dict[str, Any]] = None,
    ) -> "PhaseTransition":
        return cls(
            transition_id=str(uuid.uuid4()),
            cycle_id=cycle_id,
            from_phase=from_phase,
            to_phase=to_phase,
            triggered_by=triggered_by,
            trigger_type=trigger_type,
            gate_type=PHASE_GATES.get(from_phase, GateType.NONE),
            timestamp=datetime.utcnow(),
            notes=notes,
            artifacts=artifacts or {},
        )


@dataclass
class ClarificationMessage:
    """Single message in a clarification thread."""
    message_id: str
    thread_id: str
    sender_id: str
    sender_type: str                        # "agent" or "entity"
    content: str
    attachments: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @classmethod
    def create(
        cls,
        thread_id: str,
        sender_id: str,
        sender_type: str,
        content: str,
        attachments: Optional[List[str]] = None,
    ) -> "ClarificationMessage":
        return cls(
            message_id=str(uuid.uuid4()),
            thread_id=thread_id,
            sender_id=sender_id,
            sender_type=sender_type,
            content=content,
            attachments=attachments or [],
            timestamp=datetime.utcnow(),
        )


@dataclass
class ClarificationThread:
    """Q&A thread between Agent A and Entity B."""
    thread_id: str
    cycle_id: str
    status: ClarificationStatus
    messages: List[ClarificationMessage] = field(default_factory=list)
    waiting_for: str = "entity"             # "agent" or "entity"
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_response_at: Optional[datetime] = None

    @classmethod
    def create(cls, cycle_id: str) -> "ClarificationThread":
        return cls(
            thread_id=str(uuid.uuid4()),
            cycle_id=cycle_id,
            status=ClarificationStatus.PENDING_RESPONSE,
            waiting_for="entity",
            created_at=datetime.utcnow(),
        )

    def add_message(self, message: ClarificationMessage) -> None:
        self.messages.append(message)
        self.last_response_at = message.timestamp
        # Flip who we're waiting for
        self.waiting_for = "agent" if message.sender_type == "entity" else "entity"
        if message.sender_type == "entity":
            self.status = ClarificationStatus.ANSWERED


@dataclass
class DesignSection:
    """Section of architecture document."""
    section_id: str
    title: str
    content: str                            # Markdown content
    diagrams: List[str] = field(default_factory=list)
    order: int = 0

    @classmethod
    def create(cls, title: str, content: str, order: int = 0) -> "DesignSection":
        return cls(
            section_id=str(uuid.uuid4()),
            title=title,
            content=content,
            order=order,
        )


@dataclass
class PlanStep:
    """Implementation plan step."""
    step_id: str
    title: str
    description: str
    estimated_duration: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    status: str = "pending"                 # "pending", "in_progress", "completed", "skipped"
    order: int = 0

    @classmethod
    def create(
        cls,
        title: str,
        description: str,
        order: int = 0,
        estimated_duration: Optional[str] = None,
        dependencies: Optional[List[str]] = None,
    ) -> "PlanStep":
        return cls(
            step_id=str(uuid.uuid4()),
            title=title,
            description=description,
            estimated_duration=estimated_duration,
            dependencies=dependencies or [],
            order=order,
        )


@dataclass
class ReviewComment:
    """Comment from Entity B on architecture document."""
    comment_id: str
    reviewer_id: str
    section_id: Optional[str]               # None for general comments
    content: str
    resolved: bool = False
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ArchitectureDoc:
    """Architecture/design document created by Agent A."""
    doc_id: str
    cycle_id: str
    version: int = 1

    # Content
    title: str = ""
    summary: str = ""
    design_sections: List[DesignSection] = field(default_factory=list)
    implementation_plan: List[PlanStep] = field(default_factory=list)
    acceptance_criteria: List[str] = field(default_factory=list)

    # Review state
    review_status: ReviewStatus = ReviewStatus.DRAFT
    reviewer_comments: List[ReviewComment] = field(default_factory=list)

    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None

    @classmethod
    def create(cls, cycle_id: str, title: str, summary: str = "") -> "ArchitectureDoc":
        return cls(
            doc_id=str(uuid.uuid4()),
            cycle_id=cycle_id,
            title=title,
            summary=summary,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )


@dataclass
class TaskCycle:
    """Complete GEP task cycle state."""
    cycle_id: str
    task_id: str                            # Related task from TaskService
    assigned_agent_id: str                  # Agent A
    requester_entity_id: str                # Entity B (user_id or agent_id)
    requester_entity_type: str = "user"     # "user" or "agent"

    # Phase tracking
    current_phase: CyclePhase = CyclePhase.PLANNING
    phase_history: List[PhaseTransition] = field(default_factory=list)

    # Artifacts
    architecture_doc_id: Optional[str] = None
    acceptance_criteria: List[str] = field(default_factory=list)

    # Clarifications
    clarification_thread_id: Optional[str] = None

    # Timeout handling
    timeout_config: TimeoutConfig = field(default_factory=TimeoutConfig)
    last_entity_b_interaction: Optional[datetime] = None
    timeout_warnings_sent: int = 0

    # Testing integration
    test_iterations: int = 0
    max_test_iterations: int = 10

    # Reflection integration
    reflection_trigger_enabled: bool = True
    extracted_behavior_ids: List[str] = field(default_factory=list)

    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        task_id: str,
        assigned_agent_id: str,
        requester_entity_id: str,
        requester_entity_type: str = "user",
        acceptance_criteria: Optional[List[str]] = None,
        timeout_policy: TimeoutPolicy = TimeoutPolicy.PAUSE_WITH_NOTIFICATION,
        max_test_iterations: int = 10,
    ) -> "TaskCycle":
        return cls(
            cycle_id=str(uuid.uuid4()),
            task_id=task_id,
            assigned_agent_id=assigned_agent_id,
            requester_entity_id=requester_entity_id,
            requester_entity_type=requester_entity_type,
            acceptance_criteria=acceptance_criteria or [],
            timeout_config=TimeoutConfig(policy=timeout_policy),
            max_test_iterations=max_test_iterations,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

    @property
    def is_terminal(self) -> bool:
        """Check if cycle is in a terminal state."""
        return self.current_phase in (CyclePhase.COMPLETED, CyclePhase.CANCELLED, CyclePhase.FAILED)

    @property
    def current_role(self) -> str:
        """Get the role for the current phase."""
        return PHASE_ROLES.get(self.current_phase, "student")

    @property
    def current_gate_type(self) -> GateType:
        """Get the gate type for the current phase."""
        return PHASE_GATES.get(self.current_phase, GateType.NONE)


# Request/Response models for service methods

@dataclass
class CreateCycleRequest:
    """Request to create a new GEP cycle."""
    task_id: str
    assigned_agent_id: str
    requester_entity_id: str
    requester_entity_type: str = "user"
    acceptance_criteria: List[str] = field(default_factory=list)
    timeout_policy: TimeoutPolicy = TimeoutPolicy.PAUSE_WITH_NOTIFICATION
    max_test_iterations: int = 10
    reflection_trigger_enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TransitionPhaseRequest:
    """Request to transition to a new phase."""
    cycle_id: str
    target_phase: CyclePhase
    triggered_by: str
    trigger_type: TriggerType = TriggerType.MANUAL
    notes: Optional[str] = None
    artifacts: Dict[str, Any] = field(default_factory=dict)
    # For strict gates
    approval_granted: bool = False


@dataclass
class SubmitClarificationRequest:
    """Request to submit a clarification message."""
    cycle_id: str
    sender_id: str
    sender_type: str                        # "agent" or "entity"
    content: str
    attachments: List[str] = field(default_factory=list)


@dataclass
class CreateArchitectureRequest:
    """Request to create/update architecture document."""
    cycle_id: str
    title: str
    summary: str = ""
    design_sections: List[Dict[str, Any]] = field(default_factory=list)
    implementation_plan: List[Dict[str, Any]] = field(default_factory=list)
    acceptance_criteria: List[str] = field(default_factory=list)


@dataclass
class ApproveArchitectureRequest:
    """Request for Entity B to approve architecture."""
    cycle_id: str
    approver_id: str
    approval_notes: Optional[str] = None
    approved_criteria: List[str] = field(default_factory=list)


@dataclass
class SubmitTestResultsRequest:
    """Request to submit test execution results."""
    cycle_id: str
    passed: bool
    test_trace: Optional[str] = None        # For ReflectionService
    test_summary: Optional[str] = None
    failed_tests: List[str] = field(default_factory=list)


@dataclass
class RequestVerificationRequest:
    """Request Entity B verification."""
    cycle_id: str
    summary: str
    artifacts: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AcceptCompletionRequest:
    """Request for Entity B final acceptance."""
    cycle_id: str
    accepter_id: str
    accepted: bool
    acceptance_notes: Optional[str] = None
    adjustment_requests: List[str] = field(default_factory=list)


@dataclass
class CycleResponse:
    """Standard response containing cycle state."""
    success: bool
    cycle: Optional[TaskCycle] = None
    message: Optional[str] = None
    error: Optional[str] = None
    phase_transition: Optional[PhaseTransition] = None


@dataclass
class ClarificationResponse:
    """Response for clarification operations."""
    success: bool
    thread: Optional[ClarificationThread] = None
    message: Optional[ClarificationMessage] = None
    error: Optional[str] = None


@dataclass
class ArchitectureResponse:
    """Response for architecture operations."""
    success: bool
    doc: Optional[ArchitectureDoc] = None
    message: Optional[str] = None
    error: Optional[str] = None


@dataclass
class TestResultsResponse:
    """Response for test result submission."""
    success: bool
    cycle: Optional[TaskCycle] = None
    reflection_triggered: bool = False
    extracted_behavior_ids: List[str] = field(default_factory=list)
    next_phase: Optional[CyclePhase] = None
    message: Optional[str] = None
    error: Optional[str] = None
