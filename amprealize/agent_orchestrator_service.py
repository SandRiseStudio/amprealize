from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

# Maximum recursion depth for consultations to prevent infinite loops
MAX_CONSULTATION_DEPTH = 3

_DEFAULT_PERSONA_DEFS = [
    {
        "agent_id": "engineering",
        "display_name": "Engineering Agent",
        "role_alignment": "MULTI_ROLE",
        "default_behaviors": [
            "behavior_unify_execution_records",
            "behavior_wire_cli_to_orchestrator",
        ],
        "playbook_refs": ["amprealize/agents/playbooks/AGENT_ENGINEERING.md"],
        "capabilities": ["runtime_orchestration", "telemetry"],
    },
    {
        "agent_id": "product",
        "display_name": "Product Agent",
        "role_alignment": "STRATEGIST",
        "default_behaviors": [
            "behavior_update_docs_after_changes",
            "behavior_instrument_metrics_pipeline",
        ],
        "playbook_refs": ["amprealize/agents/playbooks/AGENT_PRODUCT.md"],
        "capabilities": ["roadmap", "metrics"],
    },
    {
        "agent_id": "finance",
        "display_name": "Finance Agent",
        "role_alignment": "TEACHER",
        "default_behaviors": [
            "behavior_validate_financial_impact",
        ],
        "playbook_refs": ["amprealize/agents/playbooks/AGENT_FINANCE.md"],
        "capabilities": ["budget", "forecasting"],
    },
    {
        "agent_id": "compliance",
        "display_name": "Compliance Agent",
        "role_alignment": "TEACHER",
        "default_behaviors": [
            "behavior_handbook_compliance_prompt",
            "behavior_update_docs_after_changes",
        ],
        "playbook_refs": ["amprealize/agents/playbooks/AGENT_COMPLIANCE.md"],
        "capabilities": ["audit", "checklist"],
    },
    {
        "agent_id": "security",
        "display_name": "Security Agent",
        "role_alignment": "STRATEGIST",
        "default_behaviors": [
            "behavior_lock_down_security_surface",
            "behavior_prevent_secret_leaks",
        ],
        "playbook_refs": ["amprealize/agents/playbooks/AGENT_SECURITY.md"],
        "capabilities": ["auth", "threat_model"],
    },
]


@dataclass
class AgentPersona:
    agent_id: str
    display_name: str
    role_alignment: str
    default_behaviors: List[str] = field(default_factory=list)
    playbook_refs: List[str] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentSwitchEvent:
    event_id: str
    from_agent_id: str
    to_agent_id: str
    stage: str
    trigger: str
    trigger_details: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    issued_by: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# =============================================================================
# Agent Interaction Contracts (Delegation, Consultation, Handoff)
# =============================================================================


@dataclass
class DelegationRequest:
    """Request to delegate a subtask to another agent."""

    delegating_run_id: str  # Parent run requesting delegation
    target_agent_id: str  # Agent to delegate to
    subtask: str  # Description of the subtask
    context: Dict[str, Any] = field(default_factory=dict)  # Context to pass
    timeout_seconds: int = 300
    wait_for_completion: bool = True  # Block until subtask completes


@dataclass
class DelegationResponse:
    """Response from a delegation request."""

    delegation_id: str
    delegated_run_id: str  # Child run created for the subtask
    parent_run_id: str  # Original requesting run
    target_agent_id: str
    subtask: str
    status: str  # PENDING | RUNNING | COMPLETED | FAILED | CANCELLED
    result: Optional[Dict[str, Any]] = None  # Output from delegated run
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConsultationRequest:
    """Request for lightweight advisory input from another agent."""

    requesting_run_id: str  # Run requesting consultation
    target_agent_id: str  # Agent to consult
    question: str  # Question to ask
    context: Dict[str, Any] = field(default_factory=dict)  # Supporting context
    max_tokens: int = 2000
    depth: int = 0  # Recursion depth (for preventing infinite loops)


@dataclass
class ConsultationResponse:
    """Response from a consultation."""

    consultation_id: str
    requesting_run_id: str
    target_agent_id: str
    question: str
    response: str  # The agent's answer
    confidence: float = 1.0  # 0.0-1.0 confidence score
    depth: int = 0  # Recursion depth at which this occurred
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HandoffRequest:
    """Request to transfer execution to another agent."""

    source_run_id: str  # Current run to hand off from
    target_agent_id: str  # Agent to hand off to
    reason: str  # Reason for handoff
    transfer_context: bool = True  # Copy context to new run
    transfer_outputs: bool = True  # Copy outputs so far


@dataclass
class HandoffResponse:
    """Response from a handoff operation."""

    handoff_id: str
    new_run_id: str  # New run created for target agent
    previous_run_id: str  # Source run that was handed off
    new_agent_id: str
    previous_agent_id: str
    reason: str
    status: str  # COMPLETED (handoff done) | FAILED
    context_transferred: bool
    outputs_transferred: bool
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# =============================================================================
# Escalation Contracts (Section 11.4 - Human Escalation)
# =============================================================================

# Default timeout for approval requests (1 hour)
DEFAULT_APPROVAL_TIMEOUT_SECONDS = 3600


class EscalationType(str, Enum):
    """Type of escalation request."""

    HELP = "help"  # Non-blocking guidance request
    APPROVAL = "approval"  # Blocking approval request
    BLOCKED = "blocked"  # Notification that execution is blocked


class EscalationStatus(str, Enum):
    """Status of an escalation."""

    PENDING = "pending"  # Awaiting human response
    RESOLVED = "resolved"  # Help request resolved
    APPROVED = "approved"  # Approval granted
    REJECTED = "rejected"  # Approval denied
    ACKNOWLEDGED = "acknowledged"  # Blocked notification acknowledged
    CANCELLED = "cancelled"  # Escalation cancelled
    EXPIRED = "expired"  # Timed out without response


@dataclass
class EscalationRequest:
    """Base escalation request."""

    escalation_id: str
    escalation_type: EscalationType
    run_id: str
    work_item_id: Optional[str]
    reason: str
    context: Dict[str, Any] = field(default_factory=dict)
    blocking: bool = False  # If True, execution pauses until resolved
    requested_by: Dict[str, Any] = field(default_factory=dict)  # Agent/surface info
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    timeout_seconds: Optional[int] = None  # For approval requests
    expires_at: Optional[str] = None  # Computed from timeout

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HelpRequest:
    """Request for non-blocking human guidance."""

    run_id: str
    reason: str
    context: Dict[str, Any] = field(default_factory=dict)
    work_item_id: Optional[str] = None
    urgency: str = "normal"  # low | normal | high | urgent


@dataclass
class HelpResponse:
    """Response to a help request."""

    escalation_id: str
    run_id: str
    status: EscalationStatus
    reason: str
    guidance: Optional[str] = None  # Human's response/guidance
    resolved_by: Optional[str] = None  # User who responded
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved_at: Optional[str] = None
    notification_sent: bool = False  # Whether notification was dispatched

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ApprovalOption:
    """An option for approval decision."""

    value: str
    label: str
    description: Optional[str] = None


@dataclass
class ApprovalRequest:
    """Request for blocking human approval."""

    run_id: str
    decision: str  # What decision is being requested
    options: List[str]  # Available choices (e.g., ["approve", "reject", "defer"])
    context: Dict[str, Any] = field(default_factory=dict)
    work_item_id: Optional[str] = None
    timeout_seconds: int = DEFAULT_APPROVAL_TIMEOUT_SECONDS


@dataclass
class ApprovalResponse:
    """Response to an approval request."""

    escalation_id: str
    run_id: str
    decision: str
    status: EscalationStatus  # PENDING | APPROVED | REJECTED | EXPIRED | CANCELLED
    approved: bool = False
    selected_option: Optional[str] = None  # Which option was chosen
    reason: Optional[str] = None  # Human's explanation
    approved_by: Optional[str] = None  # User who approved/rejected
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved_at: Optional[str] = None
    expires_at: Optional[str] = None
    notification_sent: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BlockedNotification:
    """Notification that execution is blocked."""

    run_id: str
    reason: str
    blocker_details: Dict[str, Any] = field(default_factory=dict)
    work_item_id: Optional[str] = None
    suggested_actions: List[str] = field(default_factory=list)


@dataclass
class BlockedResponse:
    """Response to a blocked notification."""

    escalation_id: str
    run_id: str
    status: EscalationStatus  # PENDING | ACKNOWLEDGED | RESOLVED
    reason: str
    blocker_details: Dict[str, Any] = field(default_factory=dict)
    acknowledged_by: Optional[str] = None
    resolution: Optional[str] = None  # How the blocker was resolved
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    acknowledged_at: Optional[str] = None
    notification_sent: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentAssignment:
    assignment_id: str
    run_id: str
    active_agent: AgentPersona
    stage: str
    heuristics_applied: Dict[str, Any]
    requested_by: Dict[str, Any]
    timestamp: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    history: List[AgentSwitchEvent] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["active_agent"] = self.active_agent.to_dict()
        payload["history"] = [event.to_dict() for event in self.history]
        return payload


class AgentOrchestratorService:
    """In-memory coordinator for runtime agent assignments."""

    def __init__(self, personas: Optional[List[AgentPersona]] = None) -> None:
        if personas is None:
            personas = [AgentPersona(**definition) for definition in _DEFAULT_PERSONA_DEFS]
        self._personas: Dict[str, AgentPersona] = {persona.agent_id: persona for persona in personas}
        self._assignments: Dict[str, AgentAssignment] = {}
        self._assignments_by_run: Dict[str, str] = {}

    def list_personas(self) -> List[AgentPersona]:
        return list(self._personas.values())

    def assign_agent(
        self,
        *,
        run_id: Optional[str],
        requested_agent_id: Optional[str],
        stage: str,
        context: Optional[Dict[str, Any]],
        requested_by: Dict[str, Any],
    ) -> AgentAssignment:
        run_identifier = run_id or str(uuid4())
        existing_id = self._assignments_by_run.get(run_identifier)
        if existing_id:
            existing = self._assignments[existing_id]
            if requested_agent_id is None or existing.active_agent.agent_id == requested_agent_id:
                return existing
        persona = self._select_persona(requested_agent_id, context)
        heuristics = self._build_heuristics(persona.agent_id, requested_agent_id, context)
        assignment_id = str(uuid4())
        assignment = AgentAssignment(
            assignment_id=assignment_id,
            run_id=run_identifier,
            active_agent=persona,
            stage=stage,
            heuristics_applied=heuristics,
            requested_by=requested_by,
            timestamp=datetime.now(timezone.utc).isoformat(),
            metadata=context or {},
            history=[],
        )
        self._assignments[assignment_id] = assignment
        self._assignments_by_run[run_identifier] = assignment_id
        return assignment

    def switch_agent(
        self,
        *,
        assignment_id: str,
        target_agent_id: str,
        reason: Optional[str],
        allow_downgrade: bool,
        stage: Optional[str],
        issued_by: Optional[Dict[str, Any]],
    ) -> AgentAssignment:
        assignment = self._get_assignment(assignment_id)
        persona = self._select_persona(target_agent_id, assignment.metadata)
        trigger_details = {
            "reason": reason or "manual_override",
            "allow_downgrade": allow_downgrade,
        }
        event = AgentSwitchEvent(
            event_id=str(uuid4()),
            from_agent_id=assignment.active_agent.agent_id,
            to_agent_id=persona.agent_id,
            stage=stage or assignment.stage,
            trigger="MANUAL" if reason else "HEURISTIC",
            trigger_details=trigger_details,
            issued_by=issued_by or {},
        )
        assignment.history.append(event)
        assignment.active_agent = persona
        if stage:
            assignment.stage = stage
        assignment.heuristics_applied = self._build_heuristics(persona.agent_id, target_agent_id, assignment.metadata)
        assignment.timestamp = datetime.now(timezone.utc).isoformat()
        return assignment

    def get_status(
        self,
        *,
        run_id: Optional[str],
        assignment_id: Optional[str],
    ) -> Optional[AgentAssignment]:
        if assignment_id:
            return self._assignments.get(assignment_id)
        if run_id:
            found = self._assignments_by_run.get(run_id)
            return self._assignments.get(found) if found else None
        return None

    def _select_persona(
        self,
        requested_agent_id: Optional[str],
        context: Optional[Dict[str, Any]],
    ) -> AgentPersona:
        if requested_agent_id and requested_agent_id in self._personas:
            return self._personas[requested_agent_id]
        if context:
            task_type = context.get("task_type")
            if task_type == "compliance" and "compliance" in self._personas:
                return self._personas["compliance"]
            if task_type == "security" and "security" in self._personas:
                return self._personas["security"]
            if task_type == "finance" and "finance" in self._personas:
                return self._personas["finance"]
        return self._personas.get("engineering") or next(iter(self._personas.values()))

    def _build_heuristics(
        self,
        selected_agent_id: str,
        requested_agent_id: Optional[str],
        context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "selected_agent_id": selected_agent_id,
            "requested_agent_id": requested_agent_id,
            "task_type": context.get("task_type") if context else None,
            "compliance_tags": context.get("compliance_tags") if context else None,
            "severity": context.get("severity") if context else None,
        }

    def _get_assignment(self, assignment_id: str) -> AgentAssignment:
        if assignment_id not in self._assignments:
            raise KeyError(f"Unknown assignment_id: {assignment_id}")
        return self._assignments[assignment_id]

    # =========================================================================
    # Agent Interaction Methods (Delegation, Consultation, Handoff)
    # =========================================================================

    def delegate_subtask(
        self,
        *,
        delegating_run_id: str,
        target_agent_id: str,
        subtask: str,
        context: Optional[Dict[str, Any]] = None,
        timeout_seconds: int = 300,
        wait_for_completion: bool = True,
        requested_by: Optional[Dict[str, Any]] = None,
    ) -> DelegationResponse:
        """
        Delegate a subtask to another agent.

        Creates a child run assigned to the target agent and optionally waits
        for completion. The parent run can continue or block based on
        wait_for_completion flag.
        """
        # Validate target agent exists
        if target_agent_id not in self._personas:
            raise KeyError(f"Unknown target_agent_id: {target_agent_id}")

        delegation_id = str(uuid4())
        delegated_run_id = f"run-{uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        # Create delegation response
        response = DelegationResponse(
            delegation_id=delegation_id,
            delegated_run_id=delegated_run_id,
            parent_run_id=delegating_run_id,
            target_agent_id=target_agent_id,
            subtask=subtask,
            status="PENDING" if not wait_for_completion else "RUNNING",
            result=None,
            error=None,
            created_at=now,
        )

        # Store delegation for tracking
        if not hasattr(self, "_delegations"):
            self._delegations: Dict[str, DelegationResponse] = {}
        self._delegations[delegation_id] = response

        # If wait_for_completion, simulate synchronous completion
        # In a real implementation, this would create a RunService run and poll/await
        if wait_for_completion:
            # For now, mark as completed with placeholder result
            response.status = "COMPLETED"
            response.completed_at = datetime.now(timezone.utc).isoformat()
            response.result = {
                "subtask": subtask,
                "agent_id": target_agent_id,
                "message": f"Subtask delegated to {target_agent_id}",
            }

        return response

    def consult_agent(
        self,
        *,
        requesting_run_id: str,
        target_agent_id: str,
        question: str,
        context: Optional[Dict[str, Any]] = None,
        max_tokens: int = 2000,
        depth: int = 0,
    ) -> ConsultationResponse:
        """
        Get lightweight advisory input from another agent.

        Does not create a full run - just queries the agent for a response.
        Enforces maximum consultation depth to prevent infinite recursion.
        """
        # Check recursion depth
        if depth >= MAX_CONSULTATION_DEPTH:
            return ConsultationResponse(
                consultation_id=str(uuid4()),
                requesting_run_id=requesting_run_id,
                target_agent_id=target_agent_id,
                question=question,
                response=f"Maximum consultation depth ({MAX_CONSULTATION_DEPTH}) exceeded. Cannot consult further.",
                confidence=0.0,
                depth=depth,
                metadata={"error": "max_depth_exceeded"},
            )

        # Validate target agent exists
        if target_agent_id not in self._personas:
            raise KeyError(f"Unknown target_agent_id: {target_agent_id}")

        persona = self._personas[target_agent_id]
        consultation_id = str(uuid4())

        # Generate advisory response based on agent persona
        # In a real implementation, this would invoke the agent's LLM
        advisory_response = (
            f"[{persona.display_name}] Advisory response to: {question}\n"
            f"Based on role alignment: {persona.role_alignment}\n"
            f"Relevant behaviors: {', '.join(persona.default_behaviors[:3])}"
        )

        response = ConsultationResponse(
            consultation_id=consultation_id,
            requesting_run_id=requesting_run_id,
            target_agent_id=target_agent_id,
            question=question,
            response=advisory_response,
            confidence=0.85,
            depth=depth,
            metadata={
                "agent_capabilities": persona.capabilities,
                "max_tokens": max_tokens,
                "context_keys": list((context or {}).keys()),
            },
        )

        # Store consultation for audit
        if not hasattr(self, "_consultations"):
            self._consultations: Dict[str, ConsultationResponse] = {}
        self._consultations[consultation_id] = response

        return response

    def handoff_execution(
        self,
        *,
        source_run_id: str,
        target_agent_id: str,
        reason: str,
        transfer_context: bool = True,
        transfer_outputs: bool = True,
        issued_by: Optional[Dict[str, Any]] = None,
    ) -> HandoffResponse:
        """
        Transfer execution to another agent.

        Marks the source run as handed-off and creates a new run for the
        target agent. Context and outputs can optionally be transferred.
        """
        # Validate target agent exists
        if target_agent_id not in self._personas:
            raise KeyError(f"Unknown target_agent_id: {target_agent_id}")

        # Get source assignment to find previous agent
        source_assignment = self._assignments_by_run.get(source_run_id)
        previous_agent_id = "unknown"
        if source_assignment:
            assignment = self._assignments.get(source_assignment)
            if assignment:
                previous_agent_id = assignment.active_agent.agent_id

        handoff_id = str(uuid4())
        new_run_id = f"run-{uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        response = HandoffResponse(
            handoff_id=handoff_id,
            new_run_id=new_run_id,
            previous_run_id=source_run_id,
            new_agent_id=target_agent_id,
            previous_agent_id=previous_agent_id,
            reason=reason,
            status="COMPLETED",
            context_transferred=transfer_context,
            outputs_transferred=transfer_outputs,
            created_at=now,
        )

        # Store handoff for audit
        if not hasattr(self, "_handoffs"):
            self._handoffs: Dict[str, HandoffResponse] = {}
        self._handoffs[handoff_id] = response

        # Create assignment for new run
        self.assign_agent(
            run_id=new_run_id,
            requested_agent_id=target_agent_id,
            stage="EXECUTION",
            context={
                "handoff_from": source_run_id,
                "handoff_reason": reason,
                "previous_agent": previous_agent_id,
            },
            requested_by=issued_by or {"surface": "handoff"},
        )

        return response

    def get_delegation(self, delegation_id: str) -> Optional[DelegationResponse]:
        """Retrieve a delegation by ID."""
        if not hasattr(self, "_delegations"):
            return None
        return self._delegations.get(delegation_id)

    def get_consultation(self, consultation_id: str) -> Optional[ConsultationResponse]:
        """Retrieve a consultation by ID."""
        if not hasattr(self, "_consultations"):
            return None
        return self._consultations.get(consultation_id)

    def get_handoff(self, handoff_id: str) -> Optional[HandoffResponse]:
        """Retrieve a handoff by ID."""
        if not hasattr(self, "_handoffs"):
            return None
        return self._handoffs.get(handoff_id)

    # =========================================================================
    # Escalation Methods (Section 11.4 - Human Escalation)
    # =========================================================================

    def _ensure_escalation_storage(self) -> None:
        """Lazily initialize escalation storage."""
        if not hasattr(self, "_escalations"):
            self._escalations: Dict[str, EscalationRequest] = {}
        if not hasattr(self, "_help_responses"):
            self._help_responses: Dict[str, HelpResponse] = {}
        if not hasattr(self, "_approval_responses"):
            self._approval_responses: Dict[str, ApprovalResponse] = {}
        if not hasattr(self, "_blocked_responses"):
            self._blocked_responses: Dict[str, BlockedResponse] = {}

    def _get_notification_hook(self) -> Optional[Any]:
        """Get the notification hook if configured.

        Returns the notify.NotifyService instance if available.
        Override this method to inject a custom notification service.
        """
        # Lazy import to avoid hard dependency on notify package
        if not hasattr(self, "_notify_service"):
            self._notify_service = None
            try:
                # Check if notify package is available
                from notify import NotifyService  # type: ignore

                # Service would be injected via set_notification_hook()
            except ImportError:
                pass
        return self._notify_service

    def set_notification_hook(self, notify_service: Any) -> None:
        """Set the notification service for escalation notifications.

        Args:
            notify_service: A notify.NotifyService instance
        """
        self._notify_service = notify_service

    async def _send_escalation_notification(
        self,
        escalation_type: EscalationType,
        escalation_id: str,
        run_id: str,
        reason: str,
        context: Dict[str, Any],
        urgency: str = "normal",
    ) -> bool:
        """Send notification for an escalation via the notify package.

        This is a hook for the notification system. If no notification
        service is configured, this is a no-op.

        Args:
            escalation_type: Type of escalation
            escalation_id: ID of the escalation
            run_id: Associated run ID
            reason: Reason for escalation
            context: Additional context
            urgency: Priority level

        Returns:
            True if notification was sent, False otherwise
        """
        notify_service = self._get_notification_hook()
        if notify_service is None:
            return False

        try:
            from notify import NotificationRequest, Channel, Recipient, Priority

            # Map urgency to priority
            priority_map = {
                "low": Priority.LOW,
                "normal": Priority.NORMAL,
                "high": Priority.HIGH,
                "urgent": Priority.URGENT,
            }
            priority = priority_map.get(urgency, Priority.NORMAL)

            # Template name based on escalation type
            template_name = f"escalation_{escalation_type.value}"

            # For now, use console channel for development
            # In production, this would be configured per-user preferences
            request = NotificationRequest(
                notification_type=template_name,
                channel=Channel.CONSOLE,
                recipient=Recipient(email="escalation@amprealize.local"),  # Placeholder
                context={
                    "escalation_id": escalation_id,
                    "escalation_type": escalation_type.value,
                    "run_id": run_id,
                    "reason": reason,
                    **context,
                },
                priority=priority,
            )
            await notify_service.send(request)
            return True
        except Exception:
            # Log but don't fail the escalation
            return False

    def request_help(
        self,
        *,
        run_id: str,
        reason: str,
        context: Optional[Dict[str, Any]] = None,
        work_item_id: Optional[str] = None,
        urgency: str = "normal",
        requested_by: Optional[Dict[str, Any]] = None,
    ) -> HelpResponse:
        """Request non-blocking human guidance.

        This creates an escalation that allows execution to continue
        while awaiting human input. The agent can proceed with its
        work and incorporate guidance when it arrives.

        Args:
            run_id: ID of the run requesting help
            reason: Why help is needed
            context: Additional context for the human
            work_item_id: Optional associated work item
            urgency: low | normal | high | urgent
            requested_by: Info about the requesting agent/surface

        Returns:
            HelpResponse with escalation_id and initial status
        """
        self._ensure_escalation_storage()

        escalation_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # Create the escalation request record
        escalation = EscalationRequest(
            escalation_id=escalation_id,
            escalation_type=EscalationType.HELP,
            run_id=run_id,
            work_item_id=work_item_id,
            reason=reason,
            context=context or {},
            blocking=False,  # Non-blocking
            requested_by=requested_by or {},
            created_at=now,
        )
        self._escalations[escalation_id] = escalation

        # Create the response object
        response = HelpResponse(
            escalation_id=escalation_id,
            run_id=run_id,
            status=EscalationStatus.PENDING,
            reason=reason,
            created_at=now,
            notification_sent=False,
        )
        self._help_responses[escalation_id] = response

        # Attempt to send notification (non-blocking, fire-and-forget)
        # In async context, this would be awaited
        # For sync compatibility, we mark notification_sent based on hook presence
        if self._get_notification_hook() is not None:
            response.notification_sent = True

        return response

    def request_approval(
        self,
        *,
        run_id: str,
        decision: str,
        options: List[str],
        context: Optional[Dict[str, Any]] = None,
        work_item_id: Optional[str] = None,
        timeout_seconds: int = DEFAULT_APPROVAL_TIMEOUT_SECONDS,
        requested_by: Optional[Dict[str, Any]] = None,
    ) -> ApprovalResponse:
        """Request blocking human approval.

        This creates an escalation that pauses execution until a human
        approves or rejects the decision. The run should transition to
        PAUSED_PENDING_CLARIFICATION state.

        Args:
            run_id: ID of the run requesting approval
            decision: What decision is being requested
            options: List of available choices (e.g., ["approve", "reject"])
            context: Additional context for the human
            work_item_id: Optional associated work item
            timeout_seconds: How long to wait (default 1 hour)
            requested_by: Info about the requesting agent/surface

        Returns:
            ApprovalResponse with escalation_id, status=PENDING, expires_at
        """
        self._ensure_escalation_storage()

        escalation_id = str(uuid4())
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        expires_at = (now + timedelta(seconds=timeout_seconds)).isoformat()

        # Validate options
        if not options or len(options) < 2:
            raise ValueError("Approval request must have at least 2 options")

        # Create the escalation request record
        escalation = EscalationRequest(
            escalation_id=escalation_id,
            escalation_type=EscalationType.APPROVAL,
            run_id=run_id,
            work_item_id=work_item_id,
            reason=decision,
            context=context or {},
            blocking=True,  # Blocking
            requested_by=requested_by or {},
            created_at=now_iso,
            timeout_seconds=timeout_seconds,
            expires_at=expires_at,
        )
        self._escalations[escalation_id] = escalation

        # Create the response object
        response = ApprovalResponse(
            escalation_id=escalation_id,
            run_id=run_id,
            decision=decision,
            status=EscalationStatus.PENDING,
            approved=False,
            created_at=now_iso,
            expires_at=expires_at,
            notification_sent=self._get_notification_hook() is not None,
        )
        self._approval_responses[escalation_id] = response

        return response

    def notify_blocked(
        self,
        *,
        run_id: str,
        reason: str,
        blocker_details: Optional[Dict[str, Any]] = None,
        work_item_id: Optional[str] = None,
        suggested_actions: Optional[List[str]] = None,
        requested_by: Optional[Dict[str, Any]] = None,
    ) -> BlockedResponse:
        """Notify that execution is blocked.

        This creates an escalation to inform humans that the agent
        cannot proceed. Execution remains paused until the blocker
        is resolved externally.

        Args:
            run_id: ID of the blocked run
            reason: Why execution is blocked
            blocker_details: Details about what's blocking (error, dependency, etc.)
            work_item_id: Optional associated work item
            suggested_actions: What humans might do to unblock
            requested_by: Info about the requesting agent/surface

        Returns:
            BlockedResponse with escalation_id and status
        """
        self._ensure_escalation_storage()

        escalation_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # Create the escalation request record
        escalation = EscalationRequest(
            escalation_id=escalation_id,
            escalation_type=EscalationType.BLOCKED,
            run_id=run_id,
            work_item_id=work_item_id,
            reason=reason,
            context=blocker_details or {},
            blocking=True,  # Blocking (already blocked)
            requested_by=requested_by or {},
            created_at=now,
        )
        self._escalations[escalation_id] = escalation

        # Create the response object
        response = BlockedResponse(
            escalation_id=escalation_id,
            run_id=run_id,
            status=EscalationStatus.PENDING,
            reason=reason,
            blocker_details=blocker_details or {},
            created_at=now,
            notification_sent=self._get_notification_hook() is not None,
        )
        self._blocked_responses[escalation_id] = response

        return response

    def resolve_help(
        self,
        escalation_id: str,
        *,
        guidance: str,
        resolved_by: Optional[str] = None,
    ) -> HelpResponse:
        """Resolve a help request with guidance.

        Args:
            escalation_id: ID of the help escalation
            guidance: The human's response/guidance
            resolved_by: User who provided the guidance

        Returns:
            Updated HelpResponse
        """
        self._ensure_escalation_storage()

        response = self._help_responses.get(escalation_id)
        if response is None:
            raise ValueError(f"Help escalation not found: {escalation_id}")
        if response.status != EscalationStatus.PENDING:
            raise ValueError(f"Help escalation already resolved: {escalation_id}")

        response.guidance = guidance
        response.resolved_by = resolved_by
        response.resolved_at = datetime.now(timezone.utc).isoformat()
        response.status = EscalationStatus.RESOLVED

        return response

    def resolve_approval(
        self,
        escalation_id: str,
        *,
        approved: bool,
        selected_option: Optional[str] = None,
        reason: Optional[str] = None,
        resolved_by: Optional[str] = None,
    ) -> ApprovalResponse:
        """Resolve an approval request.

        Args:
            escalation_id: ID of the approval escalation
            approved: Whether the request was approved
            selected_option: Which option was chosen
            reason: Explanation for the decision
            resolved_by: User who made the decision

        Returns:
            Updated ApprovalResponse
        """
        self._ensure_escalation_storage()

        response = self._approval_responses.get(escalation_id)
        if response is None:
            raise ValueError(f"Approval escalation not found: {escalation_id}")
        if response.status != EscalationStatus.PENDING:
            raise ValueError(f"Approval escalation already resolved: {escalation_id}")

        response.approved = approved
        response.selected_option = selected_option
        response.reason = reason
        response.approved_by = resolved_by
        response.resolved_at = datetime.now(timezone.utc).isoformat()
        response.status = EscalationStatus.APPROVED if approved else EscalationStatus.REJECTED

        return response

    def acknowledge_blocked(
        self,
        escalation_id: str,
        *,
        acknowledged_by: Optional[str] = None,
        resolution: Optional[str] = None,
    ) -> BlockedResponse:
        """Acknowledge a blocked notification.

        Args:
            escalation_id: ID of the blocked escalation
            acknowledged_by: User who acknowledged
            resolution: How the blocker was/will be resolved

        Returns:
            Updated BlockedResponse
        """
        self._ensure_escalation_storage()

        response = self._blocked_responses.get(escalation_id)
        if response is None:
            raise ValueError(f"Blocked escalation not found: {escalation_id}")
        if response.status not in (EscalationStatus.PENDING, EscalationStatus.ACKNOWLEDGED):
            raise ValueError(f"Blocked escalation already resolved: {escalation_id}")

        response.acknowledged_by = acknowledged_by
        response.acknowledged_at = datetime.now(timezone.utc).isoformat()

        if resolution:
            response.resolution = resolution
            response.status = EscalationStatus.RESOLVED
        else:
            response.status = EscalationStatus.ACKNOWLEDGED

        return response

    def get_escalation(self, escalation_id: str) -> Optional[EscalationRequest]:
        """Retrieve an escalation by ID."""
        self._ensure_escalation_storage()
        return self._escalations.get(escalation_id)

    def get_help_response(self, escalation_id: str) -> Optional[HelpResponse]:
        """Retrieve a help response by ID."""
        self._ensure_escalation_storage()
        return self._help_responses.get(escalation_id)

    def get_approval_response(self, escalation_id: str) -> Optional[ApprovalResponse]:
        """Retrieve an approval response by ID."""
        self._ensure_escalation_storage()
        return self._approval_responses.get(escalation_id)

    def get_blocked_response(self, escalation_id: str) -> Optional[BlockedResponse]:
        """Retrieve a blocked response by ID."""
        self._ensure_escalation_storage()
        return self._blocked_responses.get(escalation_id)

    def list_pending_escalations(
        self,
        run_id: Optional[str] = None,
        escalation_type: Optional[EscalationType] = None,
    ) -> List[EscalationRequest]:
        """List pending escalations, optionally filtered.

        Args:
            run_id: Filter by run ID
            escalation_type: Filter by type

        Returns:
            List of pending escalation requests
        """
        self._ensure_escalation_storage()

        results = []
        for esc in self._escalations.values():
            # Check if still pending by looking up the response
            if esc.escalation_type == EscalationType.HELP:
                resp = self._help_responses.get(esc.escalation_id)
                if resp and resp.status != EscalationStatus.PENDING:
                    continue
            elif esc.escalation_type == EscalationType.APPROVAL:
                resp = self._approval_responses.get(esc.escalation_id)
                if resp and resp.status != EscalationStatus.PENDING:
                    continue
            elif esc.escalation_type == EscalationType.BLOCKED:
                resp = self._blocked_responses.get(esc.escalation_id)
                if resp and resp.status not in (
                    EscalationStatus.PENDING,
                    EscalationStatus.ACKNOWLEDGED,
                ):
                    continue

            # Apply filters
            if run_id and esc.run_id != run_id:
                continue
            if escalation_type and esc.escalation_type != escalation_type:
                continue

            results.append(esc)

        return results
