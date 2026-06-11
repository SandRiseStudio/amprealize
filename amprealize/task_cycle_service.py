"""
TaskCycleService - Amprealize Execution Protocol (GEP) Orchestrator

PostgreSQL-backed service implementing the 8-phase GEP task execution cycle:
PLANNING → CLARIFYING → ARCHITECTING → EXECUTING → TESTING → FIXING → VERIFYING → COMPLETING

Features:
- Phase state machine with strict/soft gate enforcement
- Clarification thread management (Agent A ↔ Entity B)
- Architecture document creation and approval workflow
- Testing integration with ReflectionService for behavior extraction
- Configurable timeout policies (pause/escalate/proceed)
- Full audit trail via phase transitions

See TASK_CYCLE_SERVICE_CONTRACT.md for complete specification.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .reflection_contracts import ReflectRequest
from .reflection_service import ReflectionService
from .storage.postgres_pool import PostgresPool
from .task_cycle_contracts import (
    AcceptCompletionRequest,
    ApproveArchitectureRequest,
    ArchitectureDoc,
    ArchitectureResponse,
    ClarificationMessage,
    ClarificationResponse,
    ClarificationStatus,
    ClarificationThread,
    CreateArchitectureRequest,
    CreateCycleRequest,
    CyclePhase,
    CycleResponse,
    DesignSection,
    GateType,
    PHASE_GATES,
    PhaseTransition,
    PlanStep,
    RequestVerificationRequest,
    ReviewStatus,
    SubmitClarificationRequest,
    SubmitTestResultsRequest,
    TaskCycle,
    TestResultsResponse,
    TimeoutConfig,
    TimeoutPolicy,
    TransitionPhaseRequest,
    TriggerType,
    VALID_TRANSITIONS,
)
from .telemetry import TelemetryClient
from .utils.dsn import resolve_postgres_dsn


logger = logging.getLogger(__name__)

_TASK_CYCLE_PG_DSN_ENV = "AMPREALIZE_TASK_CYCLE_PG_DSN"
_DEFAULT_PG_DSN = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize"


class TaskCycleService:
    """
    PostgreSQL-backed GEP task cycle orchestrator.

    Manages the complete lifecycle of agent task execution through the 8-phase
    Amprealize Execution Protocol, enforcing gates, managing clarifications,
    and integrating with ReflectionService for behavior extraction.

    Uses the 'execution' schema in the consolidated database.
    """

    def __init__(
        self,
        dsn: Optional[str] = None,
        reflection_service: Optional[ReflectionService] = None,
        telemetry: Optional[TelemetryClient] = None,
        *,
        pool: Optional[PostgresPool] = None,
    ) -> None:
        """
        Initialize TaskCycleService.

        Args:
            dsn: PostgreSQL connection string. Falls back to DATABASE_URL.
            reflection_service: Optional ReflectionService for test failure analysis
            telemetry: Optional telemetry client for event emission
            pool: Optional pre-configured PostgresPool (takes precedence over dsn)
        """
        if pool is not None:
            self._pool = pool
        else:
            dsn_resolved = resolve_postgres_dsn(
                service="TASK_CYCLE",
                explicit_dsn=dsn,
                env_var=_TASK_CYCLE_PG_DSN_ENV,
                default_dsn=_DEFAULT_PG_DSN,
            )
            self._pool = PostgresPool(dsn=dsn_resolved)

        self._reflection_service = reflection_service
        self._telemetry = telemetry or TelemetryClient.noop()
        self._logger = logging.getLogger("amprealize.task_cycle_service")
        self._ensure_schema()
        self._logger.info("TaskCycleService initialized")

    def _ensure_schema(self) -> None:
        """Create all required tables and indexes."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                # task_cycles table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS task_cycles (
                        cycle_id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL,
                        assigned_agent_id TEXT NOT NULL,
                        requester_entity_id TEXT NOT NULL,
                        requester_entity_type TEXT NOT NULL DEFAULT 'user',
                        current_phase TEXT NOT NULL DEFAULT 'planning',
                        architecture_doc_id TEXT,
                        clarification_thread_id TEXT,
                        acceptance_criteria JSONB DEFAULT '[]',
                        timeout_config JSONB DEFAULT '{}',
                        last_entity_b_interaction TIMESTAMP,
                        timeout_warnings_sent INTEGER DEFAULT 0,
                        test_iterations INTEGER DEFAULT 0,
                        max_test_iterations INTEGER DEFAULT 10,
                        reflection_trigger_enabled BOOLEAN DEFAULT TRUE,
                        extracted_behavior_ids JSONB DEFAULT '[]',
                        metadata JSONB DEFAULT '{}',
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        completed_at TIMESTAMP
                    )
                """)

                # phase_transitions table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS phase_transitions (
                        transition_id TEXT PRIMARY KEY,
                        cycle_id TEXT NOT NULL,
                        from_phase TEXT NOT NULL,
                        to_phase TEXT NOT NULL,
                        triggered_by TEXT NOT NULL,
                        trigger_type TEXT NOT NULL,
                        gate_type TEXT NOT NULL,
                        notes TEXT,
                        artifacts JSONB DEFAULT '{}',
                        timestamp TIMESTAMP NOT NULL DEFAULT NOW()
                    )
                """)

                # clarification_threads table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS clarification_threads (
                        thread_id TEXT PRIMARY KEY,
                        cycle_id TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending_response',
                        waiting_for TEXT NOT NULL DEFAULT 'entity',
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        last_response_at TIMESTAMP
                    )
                """)

                # clarification_messages table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS clarification_messages (
                        message_id TEXT PRIMARY KEY,
                        thread_id TEXT NOT NULL,
                        sender_id TEXT NOT NULL,
                        sender_type TEXT NOT NULL,
                        content TEXT NOT NULL,
                        attachments JSONB DEFAULT '[]',
                        timestamp TIMESTAMP NOT NULL DEFAULT NOW()
                    )
                """)

                # architecture_docs table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS architecture_docs (
                        doc_id TEXT PRIMARY KEY,
                        cycle_id TEXT NOT NULL,
                        version INTEGER NOT NULL DEFAULT 1,
                        title TEXT NOT NULL,
                        summary TEXT,
                        design_sections JSONB DEFAULT '[]',
                        implementation_plan JSONB DEFAULT '[]',
                        acceptance_criteria JSONB DEFAULT '[]',
                        review_status TEXT NOT NULL DEFAULT 'draft',
                        reviewer_comments JSONB DEFAULT '[]',
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        approved_at TIMESTAMP,
                        approved_by TEXT
                    )
                """)

                # Create indexes
                cur.execute("CREATE INDEX IF NOT EXISTS idx_task_cycles_task_id ON task_cycles(task_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_task_cycles_agent ON task_cycles(assigned_agent_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_task_cycles_requester ON task_cycles(requester_entity_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_task_cycles_phase ON task_cycles(current_phase)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_task_cycles_created ON task_cycles(created_at DESC)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_phase_transitions_cycle ON phase_transitions(cycle_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_phase_transitions_timestamp ON phase_transitions(timestamp DESC)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_clarification_threads_cycle ON clarification_threads(cycle_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_clarification_messages_thread ON clarification_messages(thread_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_architecture_docs_cycle ON architecture_docs(cycle_id)")

                conn.commit()
                self._logger.info("TaskCycleService schema validated")

    # =========================================================================
    # Core Cycle Operations
    # =========================================================================

    def create_cycle(self, request: CreateCycleRequest) -> CycleResponse:
        """
        Create a new GEP task cycle.

        Args:
            request: Cycle creation parameters

        Returns:
            CycleResponse with created cycle
        """
        cycle = TaskCycle.create(
            task_id=request.task_id,
            assigned_agent_id=request.assigned_agent_id,
            requester_entity_id=request.requester_entity_id,
            requester_entity_type=request.requester_entity_type,
            acceptance_criteria=request.acceptance_criteria,
            timeout_policy=request.timeout_policy,
            max_test_iterations=request.max_test_iterations,
        )
        cycle.reflection_trigger_enabled = request.reflection_trigger_enabled
        cycle.metadata = request.metadata

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO task_cycles (
                        cycle_id, task_id, assigned_agent_id, requester_entity_id,
                        requester_entity_type, current_phase, acceptance_criteria,
                        timeout_config, max_test_iterations, reflection_trigger_enabled,
                        metadata, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        cycle.cycle_id,
                        cycle.task_id,
                        cycle.assigned_agent_id,
                        cycle.requester_entity_id,
                        cycle.requester_entity_type,
                        cycle.current_phase.value,
                        json.dumps(cycle.acceptance_criteria),
                        json.dumps(cycle.timeout_config.to_dict()),
                        cycle.max_test_iterations,
                        cycle.reflection_trigger_enabled,
                        json.dumps(cycle.metadata),
                        cycle.created_at,
                        cycle.updated_at,
                    ),
                )
                conn.commit()

        self._emit_telemetry("gep.cycle_created", {
            "cycle_id": cycle.cycle_id,
            "task_id": cycle.task_id,
            "agent_id": cycle.assigned_agent_id,
            "entity_id": cycle.requester_entity_id,
        })

        self._logger.info(f"Created GEP cycle {cycle.cycle_id} for task {cycle.task_id}")
        return CycleResponse(success=True, cycle=cycle, message="Cycle created successfully")

    def get_cycle(self, cycle_id: str) -> Optional[TaskCycle]:
        """Get cycle by ID."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM task_cycles WHERE cycle_id = %s", (cycle_id,))
                row = cur.fetchone()
                if not row:
                    return None
                return self._row_to_cycle(row)

    def get_cycle_by_task(self, task_id: str) -> Optional[TaskCycle]:
        """Get cycle by task ID."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM task_cycles WHERE task_id = %s ORDER BY created_at DESC LIMIT 1",
                    (task_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return self._row_to_cycle(row)

    def list_cycles(
        self,
        task_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        requester_id: Optional[str] = None,
        phase: Optional[CyclePhase] = None,
        limit: int = 50,
    ) -> List[TaskCycle]:
        """List cycles with optional filters."""
        conditions = []
        params = []

        if task_id:
            conditions.append("task_id = %s")
            params.append(task_id)
        if agent_id:
            conditions.append("assigned_agent_id = %s")
            params.append(agent_id)
        if requester_id:
            conditions.append("requester_entity_id = %s")
            params.append(requester_id)
        if phase:
            conditions.append("current_phase = %s")
            params.append(phase.value)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT * FROM task_cycles
                    {where_clause}
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    params,
                )
                return [self._row_to_cycle(row) for row in cur.fetchall()]

    # =========================================================================
    # Phase Transitions
    # =========================================================================

    def transition_phase(self, request: TransitionPhaseRequest) -> CycleResponse:
        """
        Transition cycle to a new phase.

        Enforces:
        - Valid transition (per state machine)
        - Gate requirements (strict gates require approval_granted=True)
        - Max test iterations

        Args:
            request: Transition request with target phase

        Returns:
            CycleResponse with updated cycle and transition record
        """
        cycle = self.get_cycle(request.cycle_id)
        if not cycle:
            return CycleResponse(success=False, error=f"Cycle not found: {request.cycle_id}")

        # Check if already terminal
        if cycle.is_terminal:
            return CycleResponse(
                success=False,
                cycle=cycle,
                error=f"Cycle is in terminal state: {cycle.current_phase.value}",
            )

        # Validate transition
        valid_targets = VALID_TRANSITIONS.get(cycle.current_phase, [])
        if request.target_phase not in valid_targets:
            return CycleResponse(
                success=False,
                cycle=cycle,
                error=f"Invalid transition from {cycle.current_phase.value} to {request.target_phase.value}. "
                      f"Valid targets: {[p.value for p in valid_targets]}",
            )

        # Check gate requirements
        gate_type = PHASE_GATES.get(cycle.current_phase, GateType.NONE)
        if gate_type == GateType.STRICT and not request.approval_granted:
            # Check if transitioning to non-terminal state requires approval
            if request.target_phase not in (CyclePhase.CANCELLED, CyclePhase.FAILED):
                return CycleResponse(
                    success=False,
                    cycle=cycle,
                    error=f"Strict gate at {cycle.current_phase.value} requires Entity B approval. "
                          f"Set approval_granted=True to proceed.",
                )

        # Check max test iterations
        if (
            cycle.current_phase == CyclePhase.TESTING
            and request.target_phase == CyclePhase.FIXING
        ):
            if cycle.test_iterations >= cycle.max_test_iterations:
                return CycleResponse(
                    success=False,
                    cycle=cycle,
                    error=f"Max test iterations ({cycle.max_test_iterations}) exceeded. "
                          f"Transition to VERIFYING instead.",
                )

        # Create transition record
        transition = PhaseTransition.create(
            cycle_id=cycle.cycle_id,
            from_phase=cycle.current_phase,
            to_phase=request.target_phase,
            triggered_by=request.triggered_by,
            trigger_type=request.trigger_type,
            notes=request.notes,
            artifacts=request.artifacts,
        )

        # Update cycle
        now = datetime.utcnow()
        completed_at = now if request.target_phase == CyclePhase.COMPLETED else None
        test_iterations = cycle.test_iterations
        if request.target_phase == CyclePhase.FIXING:
            test_iterations += 1

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                # Insert transition
                cur.execute(
                    """
                    INSERT INTO phase_transitions (
                        transition_id, cycle_id, from_phase, to_phase, triggered_by,
                        trigger_type, gate_type, notes, artifacts, timestamp
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        transition.transition_id,
                        transition.cycle_id,
                        transition.from_phase.value,
                        transition.to_phase.value,
                        transition.triggered_by,
                        transition.trigger_type.value,
                        transition.gate_type.value,
                        transition.notes,
                        json.dumps(transition.artifacts),
                        transition.timestamp,
                    ),
                )

                # Update cycle
                cur.execute(
                    """
                    UPDATE task_cycles
                    SET current_phase = %s, test_iterations = %s, updated_at = %s, completed_at = %s
                    WHERE cycle_id = %s
                    """,
                    (
                        request.target_phase.value,
                        test_iterations,
                        now,
                        completed_at,
                        cycle.cycle_id,
                    ),
                )
                conn.commit()

        # Reload cycle
        cycle = self.get_cycle(cycle.cycle_id)

        self._emit_telemetry("gep.phase_transition", {
            "cycle_id": cycle.cycle_id,
            "from_phase": transition.from_phase.value,
            "to_phase": transition.to_phase.value,
            "gate_type": transition.gate_type.value,
            "trigger_type": transition.trigger_type.value,
        })

        self._logger.info(
            f"Cycle {cycle.cycle_id}: {transition.from_phase.value} → {transition.to_phase.value} "
            f"(gate: {transition.gate_type.value}, trigger: {transition.trigger_type.value})"
        )

        return CycleResponse(
            success=True,
            cycle=cycle,
            phase_transition=transition,
            message=f"Transitioned to {request.target_phase.value}",
        )

    def get_phase_history(self, cycle_id: str) -> List[PhaseTransition]:
        """Get all phase transitions for a cycle."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM phase_transitions
                    WHERE cycle_id = %s
                    ORDER BY timestamp ASC
                    """,
                    (cycle_id,),
                )
                return [self._row_to_transition(row) for row in cur.fetchall()]

    # =========================================================================
    # Clarification Thread Management
    # =========================================================================

    def submit_clarification(self, request: SubmitClarificationRequest) -> ClarificationResponse:
        """
        Submit a clarification message.

        Creates thread if needed, adds message, and updates waiting_for.

        Args:
            request: Clarification submission request

        Returns:
            ClarificationResponse with thread and message
        """
        cycle = self.get_cycle(request.cycle_id)
        if not cycle:
            return ClarificationResponse(success=False, error=f"Cycle not found: {request.cycle_id}")

        # Get or create thread
        thread = self._get_or_create_thread(cycle)

        # Create message
        message = ClarificationMessage.create(
            thread_id=thread.thread_id,
            sender_id=request.sender_id,
            sender_type=request.sender_type,
            content=request.content,
            attachments=request.attachments,
        )

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                # Insert message
                cur.execute(
                    """
                    INSERT INTO clarification_messages (
                        message_id, thread_id, sender_id, sender_type, content, attachments, timestamp
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        message.message_id,
                        message.thread_id,
                        message.sender_id,
                        message.sender_type,
                        message.content,
                        json.dumps(message.attachments),
                        message.timestamp,
                    ),
                )

                # Update thread
                new_waiting_for = "agent" if request.sender_type == "entity" else "entity"
                new_status = "answered" if request.sender_type == "entity" else "pending_response"
                cur.execute(
                    """
                    UPDATE clarification_threads
                    SET waiting_for = %s, status = %s, last_response_at = %s
                    WHERE thread_id = %s
                    """,
                    (new_waiting_for, new_status, message.timestamp, thread.thread_id),
                )

                # Update cycle's last entity B interaction if from entity
                if request.sender_type == "entity":
                    cur.execute(
                        """
                        UPDATE task_cycles
                        SET last_entity_b_interaction = %s, updated_at = %s
                        WHERE cycle_id = %s
                        """,
                        (message.timestamp, message.timestamp, cycle.cycle_id),
                    )

                conn.commit()

        # Reload thread
        thread = self._get_thread(thread.thread_id)

        self._emit_telemetry("gep.clarification_submitted", {
            "cycle_id": cycle.cycle_id,
            "thread_id": thread.thread_id,
            "sender_type": request.sender_type,
            "message_length": len(request.content),
        })

        return ClarificationResponse(success=True, thread=thread, message=message)

    def get_clarification_thread(self, cycle_id: str) -> Optional[ClarificationThread]:
        """Get the clarification thread for a cycle."""
        cycle = self.get_cycle(cycle_id)
        if not cycle or not cycle.clarification_thread_id:
            return None
        return self._get_thread(cycle.clarification_thread_id)

    def _get_or_create_thread(self, cycle: TaskCycle) -> ClarificationThread:
        """Get existing thread or create new one."""
        if cycle.clarification_thread_id:
            thread = self._get_thread(cycle.clarification_thread_id)
            if thread:
                return thread

        # Create new thread
        thread = ClarificationThread.create(cycle.cycle_id)

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO clarification_threads (
                        thread_id, cycle_id, status, waiting_for, created_at
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        thread.thread_id,
                        thread.cycle_id,
                        thread.status.value,
                        thread.waiting_for,
                        thread.created_at,
                    ),
                )

                # Link to cycle
                cur.execute(
                    """
                    UPDATE task_cycles
                    SET clarification_thread_id = %s, updated_at = %s
                    WHERE cycle_id = %s
                    """,
                    (thread.thread_id, datetime.utcnow(), cycle.cycle_id),
                )
                conn.commit()

        return thread

    def _get_thread(self, thread_id: str) -> Optional[ClarificationThread]:
        """Get thread by ID with messages."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM clarification_threads WHERE thread_id = %s", (thread_id,))
                row = cur.fetchone()
                if not row:
                    return None

                thread = ClarificationThread(
                    thread_id=row[0],
                    cycle_id=row[1],
                    status=ClarificationStatus(row[2]),
                    waiting_for=row[3],
                    created_at=row[4],
                    last_response_at=row[5],
                )

                # Load messages
                cur.execute(
                    "SELECT * FROM clarification_messages WHERE thread_id = %s ORDER BY timestamp ASC",
                    (thread_id,),
                )
                for msg_row in cur.fetchall():
                    thread.messages.append(ClarificationMessage(
                        message_id=msg_row[0],
                        thread_id=msg_row[1],
                        sender_id=msg_row[2],
                        sender_type=msg_row[3],
                        content=msg_row[4],
                        attachments=json.loads(msg_row[5]) if msg_row[5] else [],
                        timestamp=msg_row[6],
                    ))

                return thread

    # =========================================================================
    # Architecture Document Management
    # =========================================================================

    def create_architecture(self, request: CreateArchitectureRequest) -> ArchitectureResponse:
        """
        Create or update architecture document.

        Args:
            request: Architecture creation request

        Returns:
            ArchitectureResponse with document
        """
        cycle = self.get_cycle(request.cycle_id)
        if not cycle:
            return ArchitectureResponse(success=False, error=f"Cycle not found: {request.cycle_id}")

        # Check if document exists
        existing_doc = self._get_architecture_doc(cycle.architecture_doc_id) if cycle.architecture_doc_id else None

        if existing_doc:
            # Update existing document
            doc = existing_doc
            doc.version += 1
            doc.title = request.title
            doc.summary = request.summary
            # Handle both dict and DesignSection objects
            sections = []
            for i, s in enumerate(request.design_sections):
                if isinstance(s, DesignSection):
                    sections.append(s)
                else:
                    sections.append(DesignSection(
                        section_id=s.get("section_id", str(uuid.uuid4())),
                        title=s["title"],
                        content=s["content"],
                        diagrams=s.get("diagrams", []),
                        order=s.get("order", i),
                    ))
            doc.design_sections = sections
            # Handle both dict and PlanStep objects
            plan_steps = []
            for i, p in enumerate(request.implementation_plan):
                if isinstance(p, PlanStep):
                    plan_steps.append(p)
                else:
                    plan_steps.append(PlanStep(
                        step_id=p.get("step_id", str(uuid.uuid4())),
                        title=p["title"],
                        description=p["description"],
                        estimated_duration=p.get("estimated_duration"),
                        dependencies=p.get("dependencies", []),
                        order=p.get("order", i),
                    ))
            doc.implementation_plan = plan_steps
            doc.acceptance_criteria = request.acceptance_criteria
            doc.review_status = ReviewStatus.PENDING_REVIEW
            doc.updated_at = datetime.utcnow()
        else:
            # Create new document
            doc = ArchitectureDoc.create(
                cycle_id=request.cycle_id,
                title=request.title,
                summary=request.summary,
            )
            # Handle both dict and DesignSection objects
            sections = []
            for i, s in enumerate(request.design_sections):
                if isinstance(s, DesignSection):
                    sections.append(s)
                else:
                    sections.append(DesignSection(
                        section_id=str(uuid.uuid4()),
                        title=s["title"],
                        content=s["content"],
                        diagrams=s.get("diagrams", []),
                        order=s.get("order", i),
                    ))
            doc.design_sections = sections

            # Handle both dict and PlanStep objects
            plan_steps = []
            for i, p in enumerate(request.implementation_plan):
                if isinstance(p, PlanStep):
                    plan_steps.append(p)
                else:
                    plan_steps.append(PlanStep(
                        step_id=str(uuid.uuid4()),
                        title=p["title"],
                        description=p["description"],
                        estimated_duration=p.get("estimated_duration"),
                        dependencies=p.get("dependencies", []),
                        order=p.get("order", i),
                    ))
            doc.implementation_plan = plan_steps
            doc.acceptance_criteria = request.acceptance_criteria
            doc.review_status = ReviewStatus.PENDING_REVIEW

        # Save document
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                if existing_doc:
                    cur.execute(
                        """
                        UPDATE architecture_docs
                        SET version = %s, title = %s, summary = %s, design_sections = %s,
                            implementation_plan = %s, acceptance_criteria = %s,
                            review_status = %s, updated_at = %s
                        WHERE doc_id = %s
                        """,
                        (
                            doc.version,
                            doc.title,
                            doc.summary,
                            json.dumps([self._section_to_dict(s) for s in doc.design_sections]),
                            json.dumps([self._step_to_dict(p) for p in doc.implementation_plan]),
                            json.dumps(doc.acceptance_criteria),
                            doc.review_status.value,
                            doc.updated_at,
                            doc.doc_id,
                        ),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO architecture_docs (
                            doc_id, cycle_id, version, title, summary, design_sections,
                            implementation_plan, acceptance_criteria, review_status,
                            created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            doc.doc_id,
                            doc.cycle_id,
                            doc.version,
                            doc.title,
                            doc.summary,
                            json.dumps([self._section_to_dict(s) for s in doc.design_sections]),
                            json.dumps([self._step_to_dict(p) for p in doc.implementation_plan]),
                            json.dumps(doc.acceptance_criteria),
                            doc.review_status.value,
                            doc.created_at,
                            doc.updated_at,
                        ),
                    )

                    # Link to cycle
                    cur.execute(
                        """
                        UPDATE task_cycles
                        SET architecture_doc_id = %s, updated_at = %s
                        WHERE cycle_id = %s
                        """,
                        (doc.doc_id, datetime.utcnow(), cycle.cycle_id),
                    )

                conn.commit()

        self._emit_telemetry("gep.architecture_created", {
            "cycle_id": cycle.cycle_id,
            "doc_id": doc.doc_id,
            "version": doc.version,
            "section_count": len(doc.design_sections),
        })

        return ArchitectureResponse(
            success=True,
            doc=doc,
            message=f"Architecture document {'updated' if existing_doc else 'created'} (v{doc.version})",
        )

    def approve_architecture(self, request: ApproveArchitectureRequest) -> CycleResponse:
        """
        Entity B approves architecture document.

        This satisfies the strict gate at ARCHITECTING phase.

        Args:
            request: Approval request

        Returns:
            CycleResponse with updated cycle (transitioned to EXECUTING)
        """
        cycle = self.get_cycle(request.cycle_id)
        if not cycle:
            return CycleResponse(success=False, error=f"Cycle not found: {request.cycle_id}")

        if cycle.current_phase != CyclePhase.ARCHITECTING:
            return CycleResponse(
                success=False,
                cycle=cycle,
                error=f"Cannot approve architecture in phase {cycle.current_phase.value}. "
                      f"Must be in ARCHITECTING phase.",
            )

        if not cycle.architecture_doc_id:
            return CycleResponse(
                success=False,
                cycle=cycle,
                error="No architecture document to approve",
            )

        # Update document
        now = datetime.utcnow()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE architecture_docs
                    SET review_status = %s, approved_at = %s, approved_by = %s, updated_at = %s
                    WHERE doc_id = %s
                    """,
                    (
                        ReviewStatus.APPROVED.value,
                        now,
                        request.approver_id,
                        now,
                        cycle.architecture_doc_id,
                    ),
                )

                # Update cycle's last entity B interaction
                cur.execute(
                    """
                    UPDATE task_cycles
                    SET last_entity_b_interaction = %s, updated_at = %s
                    WHERE cycle_id = %s
                    """,
                    (now, now, cycle.cycle_id),
                )
                conn.commit()

        self._emit_telemetry("gep.architecture_approved", {
            "cycle_id": cycle.cycle_id,
            "doc_id": cycle.architecture_doc_id,
            "approver_id": request.approver_id,
        })

        # Transition to EXECUTING (with approval granted)
        return self.transition_phase(TransitionPhaseRequest(
            cycle_id=cycle.cycle_id,
            target_phase=CyclePhase.EXECUTING,
            triggered_by=request.approver_id,
            trigger_type=TriggerType.APPROVAL,
            approval_granted=True,
            notes=request.approval_notes,
            artifacts={"approved_criteria": request.approved_criteria},
        ))

    def get_architecture_doc(self, cycle_id: str) -> Optional[ArchitectureDoc]:
        """Get architecture document for a cycle."""
        cycle = self.get_cycle(cycle_id)
        if not cycle or not cycle.architecture_doc_id:
            return None
        return self._get_architecture_doc(cycle.architecture_doc_id)

    def _get_architecture_doc(self, doc_id: str) -> Optional[ArchitectureDoc]:
        """Get document by ID."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM architecture_docs WHERE doc_id = %s", (doc_id,))
                row = cur.fetchone()
                if not row:
                    return None
                return self._row_to_architecture_doc(row)

    # =========================================================================
    # Testing Integration
    # =========================================================================

    def submit_test_results(self, request: SubmitTestResultsRequest) -> TestResultsResponse:
        """
        Submit test execution results.

        If tests fail and reflection_trigger_enabled, triggers ReflectionService
        to extract potential behaviors from the test trace.

        Args:
            request: Test results submission

        Returns:
            TestResultsResponse with reflection results
        """
        cycle = self.get_cycle(request.cycle_id)
        if not cycle:
            return TestResultsResponse(success=False, error=f"Cycle not found: {request.cycle_id}")

        if cycle.current_phase != CyclePhase.TESTING:
            return TestResultsResponse(
                success=False,
                cycle=cycle,
                error=f"Cannot submit test results in phase {cycle.current_phase.value}. "
                      f"Must be in TESTING phase.",
            )

        reflection_triggered = False
        extracted_ids: List[str] = []
        next_phase: CyclePhase

        if request.passed:
            # Tests passed - transition to VERIFYING
            next_phase = CyclePhase.VERIFYING
        else:
            # Tests failed
            if cycle.reflection_trigger_enabled and request.test_trace and self._reflection_service:
                # Trigger ReflectionService
                reflection_triggered = True
                extracted_ids = self._trigger_reflection_on_test_failure(cycle, request.test_trace)

            # Transition to FIXING
            next_phase = CyclePhase.FIXING

        self._emit_telemetry("gep.test_results_submitted", {
            "cycle_id": cycle.cycle_id,
            "passed": request.passed,
            "test_count": len(request.failed_tests) if not request.passed else 0,
            "failure_count": len(request.failed_tests),
        })

        if reflection_triggered:
            self._emit_telemetry("gep.reflection_triggered", {
                "cycle_id": cycle.cycle_id,
                "test_trace_length": len(request.test_trace or ""),
                "candidates_extracted": len(extracted_ids),
            })

        # Perform transition
        transition_result = self.transition_phase(TransitionPhaseRequest(
            cycle_id=cycle.cycle_id,
            target_phase=next_phase,
            triggered_by=cycle.assigned_agent_id,
            trigger_type=TriggerType.AUTO if request.passed else TriggerType.FAILURE,
            notes=request.test_summary,
            artifacts={
                "passed": request.passed,
                "failed_tests": request.failed_tests,
                "extracted_behavior_ids": extracted_ids,
            },
        ))

        return TestResultsResponse(
            success=transition_result.success,
            cycle=transition_result.cycle,
            reflection_triggered=reflection_triggered,
            extracted_behavior_ids=extracted_ids,
            next_phase=next_phase,
            message=f"{'Tests passed' if request.passed else 'Tests failed'}, transitioning to {next_phase.value}",
            error=transition_result.error,
        )

    def _trigger_reflection_on_test_failure(
        self,
        cycle: TaskCycle,
        test_trace: str,
    ) -> List[str]:
        """
        Trigger ReflectionService for test failures.

        Args:
            cycle: Current task cycle
            test_trace: Test execution trace

        Returns:
            List of extracted behavior slugs
        """
        if not self._reflection_service:
            self._logger.warning("ReflectionService not available for behavior extraction")
            return []

        try:
            request = ReflectRequest(
                run_id=cycle.task_id,
                trace_text=test_trace,
                trace_format="test_execution",
                min_quality_score=0.6,
                max_candidates=5,
                include_examples=True,
                tags=["gep_testing", f"cycle_{cycle.cycle_id}"],
            )
            response = self._reflection_service.reflect(request)

            # Store extracted behavior IDs
            extracted_ids = [c.slug for c in response.candidates]

            # Update cycle with extracted behavior IDs
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    # Merge with existing extracted IDs
                    cur.execute(
                        "SELECT extracted_behavior_ids FROM task_cycles WHERE cycle_id = %s",
                        (cycle.cycle_id,),
                    )
                    row = cur.fetchone()
                    existing_ids = json.loads(row[0]) if row and row[0] else []
                    all_ids = list(set(existing_ids + extracted_ids))

                    cur.execute(
                        """
                        UPDATE task_cycles
                        SET extracted_behavior_ids = %s, updated_at = %s
                        WHERE cycle_id = %s
                        """,
                        (json.dumps(all_ids), datetime.utcnow(), cycle.cycle_id),
                    )
                    conn.commit()

            self._logger.info(
                f"Cycle {cycle.cycle_id}: Extracted {len(extracted_ids)} behavior candidates from test failure"
            )
            return extracted_ids

        except Exception as exc:
            self._logger.warning(f"Failed to trigger ReflectionService: {exc}")
            return []

    # =========================================================================
    # Verification & Completion
    # =========================================================================

    def request_verification(self, request: RequestVerificationRequest) -> CycleResponse:
        """
        Request Entity B verification.

        Must be in VERIFYING phase. This prepares for the strict gate.

        Args:
            request: Verification request

        Returns:
            CycleResponse (cycle stays in VERIFYING awaiting approval)
        """
        cycle = self.get_cycle(request.cycle_id)
        if not cycle:
            return CycleResponse(success=False, error=f"Cycle not found: {request.cycle_id}")

        if cycle.current_phase != CyclePhase.VERIFYING:
            return CycleResponse(
                success=False,
                cycle=cycle,
                error=f"Cannot request verification in phase {cycle.current_phase.value}. "
                      f"Must be in VERIFYING phase.",
            )

        # Store verification request in metadata
        now = datetime.utcnow()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT metadata FROM task_cycles WHERE cycle_id = %s",
                    (cycle.cycle_id,),
                )
                row = cur.fetchone()
                metadata = json.loads(row[0]) if row and row[0] else {}
                metadata["verification_requested"] = {
                    "summary": request.summary,
                    "artifacts": request.artifacts,
                    "requested_at": now.isoformat(),
                }

                cur.execute(
                    """
                    UPDATE task_cycles
                    SET metadata = %s, updated_at = %s
                    WHERE cycle_id = %s
                    """,
                    (json.dumps(metadata), now, cycle.cycle_id),
                )
                conn.commit()

        self._emit_telemetry("gep.verification_requested", {
            "cycle_id": cycle.cycle_id,
            "summary_length": len(request.summary),
        })

        cycle = self.get_cycle(cycle.cycle_id)
        return CycleResponse(
            success=True,
            cycle=cycle,
            message="Verification requested. Awaiting Entity B approval.",
        )

    def accept_completion(self, request: AcceptCompletionRequest) -> CycleResponse:
        """
        Entity B provides final acceptance (or requests adjustments).

        If accepted, transitions to COMPLETED.
        If not accepted, transitions to FIXING with adjustment requests.

        Args:
            request: Acceptance request

        Returns:
            CycleResponse with updated cycle
        """
        cycle = self.get_cycle(request.cycle_id)
        if not cycle:
            return CycleResponse(success=False, error=f"Cycle not found: {request.cycle_id}")

        if cycle.current_phase not in (CyclePhase.VERIFYING, CyclePhase.COMPLETING):
            return CycleResponse(
                success=False,
                cycle=cycle,
                error=f"Cannot accept completion in phase {cycle.current_phase.value}. "
                      f"Must be in VERIFYING or COMPLETING phase.",
            )

        # Update last Entity B interaction
        now = datetime.utcnow()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE task_cycles
                    SET last_entity_b_interaction = %s, updated_at = %s
                    WHERE cycle_id = %s
                    """,
                    (now, now, cycle.cycle_id),
                )
                conn.commit()

        if request.accepted:
            # Final acceptance - transition to COMPLETED
            self._emit_telemetry("gep.completion_accepted", {
                "cycle_id": cycle.cycle_id,
                "total_duration_hours": (now - cycle.created_at).total_seconds() / 3600,
                "test_iterations": cycle.test_iterations,
            })

            # Two-step: VERIFYING → COMPLETING → COMPLETED
            if cycle.current_phase == CyclePhase.VERIFYING:
                result = self.transition_phase(TransitionPhaseRequest(
                    cycle_id=cycle.cycle_id,
                    target_phase=CyclePhase.COMPLETING,
                    triggered_by=request.accepter_id,
                    trigger_type=TriggerType.APPROVAL,
                    approval_granted=True,
                    notes=request.acceptance_notes,
                ))
                if not result.success:
                    return result
                cycle = result.cycle

            return self.transition_phase(TransitionPhaseRequest(
                cycle_id=cycle.cycle_id,
                target_phase=CyclePhase.COMPLETED,
                triggered_by=request.accepter_id,
                trigger_type=TriggerType.APPROVAL,
                approval_granted=True,
                notes=request.acceptance_notes,
            ))
        else:
            # Not accepted - transition to FIXING with adjustments
            # Needs approval_granted=True because VERIFYING has STRICT gate
            return self.transition_phase(TransitionPhaseRequest(
                cycle_id=cycle.cycle_id,
                target_phase=CyclePhase.FIXING,
                triggered_by=request.accepter_id,
                trigger_type=TriggerType.MANUAL,
                approval_granted=True,  # Entity B rejection IS the approval to proceed
                notes=request.acceptance_notes,
                artifacts={"adjustment_requests": request.adjustment_requests},
            ))

    # =========================================================================
    # Timeout Handling
    # =========================================================================

    def check_timeouts(self) -> List[Tuple[TaskCycle, str]]:
        """
        Check all active cycles for timeout conditions.

        Returns list of (cycle, warning_message) tuples for cycles approaching
        or exceeding timeouts.

        Returns:
            List of cycles with timeout warnings
        """
        warnings: List[Tuple[TaskCycle, str]] = []
        now = datetime.utcnow()

        # Get cycles in phases that can timeout
        timeout_phases = [CyclePhase.CLARIFYING, CyclePhase.ARCHITECTING, CyclePhase.VERIFYING]

        for phase in timeout_phases:
            cycles = self.list_cycles(phase=phase, limit=100)
            for cycle in cycles:
                timeout_hours = self._get_timeout_hours(cycle, phase)
                if not cycle.last_entity_b_interaction:
                    continue

                elapsed_hours = (now - cycle.last_entity_b_interaction).total_seconds() / 3600
                remaining_hours = timeout_hours - elapsed_hours

                if remaining_hours <= 0:
                    # Timeout reached - apply policy
                    self._apply_timeout_policy(cycle)
                    self._emit_telemetry("gep.timeout_triggered", {
                        "cycle_id": cycle.cycle_id,
                        "phase": phase.value,
                        "policy_applied": cycle.timeout_config.policy.value,
                    })
                    warnings.append((cycle, f"Timeout reached in {phase.value}. Policy applied: {cycle.timeout_config.policy.value}"))
                elif remaining_hours <= 4:
                    # Warning - approaching timeout
                    self._emit_telemetry("gep.timeout_warning", {
                        "cycle_id": cycle.cycle_id,
                        "phase": phase.value,
                        "hours_remaining": remaining_hours,
                        "policy": cycle.timeout_config.policy.value,
                    })
                    warnings.append((cycle, f"Approaching timeout in {phase.value}. {remaining_hours:.1f} hours remaining."))

        return warnings

    def _get_timeout_hours(self, cycle: TaskCycle, phase: CyclePhase) -> int:
        """Get timeout hours for a phase."""
        config = cycle.timeout_config
        if phase == CyclePhase.CLARIFYING:
            return config.clarification_timeout_hours
        elif phase == CyclePhase.ARCHITECTING:
            return config.architecture_approval_timeout_hours
        elif phase == CyclePhase.VERIFYING:
            return config.verification_timeout_hours
        return 24  # Default

    def _apply_timeout_policy(self, cycle: TaskCycle) -> None:
        """Apply configured timeout policy."""
        policy = cycle.timeout_config.policy

        if policy == TimeoutPolicy.PAUSE_WITH_NOTIFICATION:
            # Already paused - just increment warning count
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE task_cycles
                        SET timeout_warnings_sent = timeout_warnings_sent + 1, updated_at = %s
                        WHERE cycle_id = %s
                        """,
                        (datetime.utcnow(), cycle.cycle_id),
                    )
                    conn.commit()
            self._logger.info(f"Cycle {cycle.cycle_id}: Paused due to timeout (notification sent)")

        elif policy == TimeoutPolicy.AUTO_ESCALATE:
            # Escalate to backup contacts
            escalation_ids = cycle.timeout_config.escalation_contact_ids
            if escalation_ids and cycle.timeout_warnings_sent < cycle.timeout_config.max_escalation_attempts:
                # Would trigger notification to escalation contacts
                self._logger.info(f"Cycle {cycle.cycle_id}: Escalating to {escalation_ids}")
                with self._pool.connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE task_cycles
                            SET timeout_warnings_sent = timeout_warnings_sent + 1, updated_at = %s
                            WHERE cycle_id = %s
                            """,
                            (datetime.utcnow(), cycle.cycle_id),
                        )
                        conn.commit()
            else:
                # No escalation contacts or max attempts reached - fall back to pause
                self._logger.info(f"Cycle {cycle.cycle_id}: Auto-escalate fallback to pause")

        elif policy == TimeoutPolicy.PROCEED_WITH_ASSUMPTIONS:
            # Document assumptions and proceed
            self._logger.info(f"Cycle {cycle.cycle_id}: Proceeding with documented assumptions")
            # This would auto-transition with assumptions documented in artifacts

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def _row_to_cycle(self, row: tuple) -> TaskCycle:
        """Convert database row to TaskCycle.

        Note: JSON/JSONB columns may be auto-decoded by psycopg2, so we handle
        both string and already-decoded values.
        """
        # Helper to safely parse JSON that might already be decoded
        def safe_json_parse(val, default):
            if val is None:
                return default
            if isinstance(val, (list, dict)):
                return val  # Already decoded
            return json.loads(val)  # String needs parsing

        acceptance_criteria = safe_json_parse(row[8], [])
        timeout_config_raw = safe_json_parse(row[9], {})
        extracted_behavior_ids = safe_json_parse(row[15], [])
        metadata = safe_json_parse(row[16], {})

        return TaskCycle(
            cycle_id=row[0],
            task_id=row[1],
            assigned_agent_id=row[2],
            requester_entity_id=row[3],
            requester_entity_type=row[4],
            current_phase=CyclePhase(row[5]),
            architecture_doc_id=row[6],
            clarification_thread_id=row[7],
            acceptance_criteria=acceptance_criteria,
            timeout_config=TimeoutConfig.from_dict(timeout_config_raw) if timeout_config_raw else TimeoutConfig(),
            last_entity_b_interaction=row[10],
            timeout_warnings_sent=row[11] or 0,
            test_iterations=row[12] or 0,
            max_test_iterations=row[13] or 10,
            reflection_trigger_enabled=row[14] if row[14] is not None else True,
            extracted_behavior_ids=extracted_behavior_ids,
            metadata=metadata,
            created_at=row[17],
            updated_at=row[18],
            completed_at=row[19],
        )

    def _row_to_transition(self, row: tuple) -> PhaseTransition:
        """Convert database row to PhaseTransition."""
        # Helper to safely parse JSON that might already be decoded
        def safe_json_parse(val, default):
            if val is None:
                return default
            if isinstance(val, (list, dict)):
                return val
            return json.loads(val)

        return PhaseTransition(
            transition_id=row[0],
            cycle_id=row[1],
            from_phase=CyclePhase(row[2]),
            to_phase=CyclePhase(row[3]),
            triggered_by=row[4],
            trigger_type=TriggerType(row[5]),
            gate_type=GateType(row[6]),
            notes=row[7],
            artifacts=safe_json_parse(row[8], {}),
            timestamp=row[9],
        )

    def _row_to_architecture_doc(self, row: tuple) -> ArchitectureDoc:
        """Convert database row to ArchitectureDoc."""
        # Helper to safely parse JSON that might already be decoded
        def safe_json_parse(val, default):
            if val is None:
                return default
            if isinstance(val, (list, dict)):
                return val
            return json.loads(val)

        sections_data = safe_json_parse(row[5], [])
        plan_data = safe_json_parse(row[6], [])
        comments_data = safe_json_parse(row[9], [])
        acceptance_criteria = safe_json_parse(row[7], [])

        return ArchitectureDoc(
            doc_id=row[0],
            cycle_id=row[1],
            version=row[2],
            title=row[3],
            summary=row[4],
            design_sections=[
                DesignSection(
                    section_id=s.get("section_id", str(uuid.uuid4())),
                    title=s["title"],
                    content=s["content"],
                    diagrams=s.get("diagrams", []),
                    order=s.get("order", 0),
                )
                for s in sections_data
            ],
            implementation_plan=[
                PlanStep(
                    step_id=p.get("step_id", str(uuid.uuid4())),
                    title=p["title"],
                    description=p["description"],
                    estimated_duration=p.get("estimated_duration"),
                    dependencies=p.get("dependencies", []),
                    status=p.get("status", "pending"),
                    order=p.get("order", 0),
                )
                for p in plan_data
            ],
            acceptance_criteria=acceptance_criteria,
            review_status=ReviewStatus(row[8]),
            reviewer_comments=[],  # Would need to load from separate table if used
            created_at=row[10],
            updated_at=row[11],
            approved_at=row[12],
            approved_by=row[13],
        )

    def _section_to_dict(self, section: DesignSection) -> Dict[str, Any]:
        """Convert DesignSection to dict for JSON storage."""
        return {
            "section_id": section.section_id,
            "title": section.title,
            "content": section.content,
            "diagrams": section.diagrams,
            "order": section.order,
        }

    def _step_to_dict(self, step: PlanStep) -> Dict[str, Any]:
        """Convert PlanStep to dict for JSON storage."""
        return {
            "step_id": step.step_id,
            "title": step.title,
            "description": step.description,
            "estimated_duration": step.estimated_duration,
            "dependencies": step.dependencies,
            "status": step.status,
            "order": step.order,
        }

    def _emit_telemetry(self, event: str, data: Dict[str, Any]) -> None:
        """Emit telemetry event."""
        try:
            self._telemetry.record(event, data)
        except Exception as exc:
            self._logger.warning(f"Failed to emit telemetry: {exc}")
