# Task Cycle Service Contract – Amprealize Execution Protocol (GEP)

## 1. Overview

The **Amprealize Execution Protocol (GEP)** defines a proprietary 8-phase task execution cycle that differentiates Amprealize from other agent orchestration platforms. GEP formalizes the complete lifecycle from task assignment through acceptance, with explicit phase gates, clarification loops, and Entity B (human or agent) verification checkpoints.

This protocol integrates seamlessly with existing Amprealize capabilities:
- **Student/Teacher/Strategist Roles**: Phases map to appropriate roles
- **Behavior Lifecycle**: Testing failures trigger behavior extraction
- **RunService/ActionService**: All phase transitions are tracked and auditable

## 2. Terminology

| Term | Definition |
|------|------------|
| **Agent A** | The executing agent assigned to complete the task |
| **Entity B** | The task requester (human user or another agent) who provides requirements and acceptance |
| **GEP** | Amprealize Execution Protocol – the 8-phase cycle defined herein |
| **Phase Gate** | A checkpoint requiring explicit approval before proceeding |
| **Soft Gate** | Auto-progression allowed with notification (e.g., Testing→Fixing loop) |
| **Strict Gate** | Requires Entity B approval before proceeding |

## 3. The 8 Phases

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                       Amprealize Execution Protocol (GEP)                           │
└─────────────────────────────────────────────────────────────────────────────────┘

   ┌──────────┐    ┌────────────┐    ┌─────────────┐    ┌───────────┐
   │ PLANNING │ →  │ CLARIFYING │ →  │ ARCHITECTING│ →  │ EXECUTING │
   │   (1)    │    │    (2)     │    │     (3)     │    │    (4)    │
   └──────────┘    └────────────┘    └─────────────┘    └───────────┘
        │               │                  │                  │
        │               │                  │                  │
   🧠 Strategist   🧠 Strategist      🧠 Strategist      📖 Student
        │               │                  │                  │
        │               ▼                  ▼                  │
        │         Entity B Q&A      ⛔ STRICT GATE           │
        │                                                     │
                                                             ▼
   ┌──────────┐    ┌────────────┐    ┌─────────────┐    ┌───────────┐
   │COMPLETING│ ←  │ VERIFYING  │ ←  │   FIXING    │ ←  │  TESTING  │
   │   (8)    │    │    (7)     │    │     (6)     │    │    (5)    │
   └──────────┘    └────────────┘    └─────────────┘    └───────────┘
        │               │                  │                  │
        │               │                  │                  │
   📖 Student      🎓 Teacher        📖 Student        📖 Student
        │               │                  │                  │
        ▼               ▼                  ▼                  │
   ⛔ STRICT GATE  ⛔ STRICT GATE    🔄 SOFT GATE ←──────────┘
                                    (auto-loop)
```

### Phase Details

| Phase | Name | Role | Gate Type | Description |
|-------|------|------|-----------|-------------|
| 1 | **PLANNING** | Strategist | None | Agent A analyzes task, identifies requirements, and formulates initial questions |
| 2 | **CLARIFYING** | Strategist | Soft | Agent A asks Entity B clarifying questions; Entity B responds |
| 3 | **ARCHITECTING** | Strategist | **Strict** | Agent A creates architecture/design document; Entity B must approve before execution |
| 4 | **EXECUTING** | Student | None | Agent A implements according to approved plan |
| 5 | **TESTING** | Student | Soft | Agent A runs tests on implementation |
| 6 | **FIXING** | Student | Soft | Agent A fixes issues found in testing; loops back to TESTING |
| 7 | **VERIFYING** | Teacher | **Strict** | Agent A requests Entity B verification; Entity B approves or requests adjustments |
| 8 | **COMPLETING** | Student | **Strict** | Final acceptance by Entity B; task marked complete |

## 4. State Machine

### 4.1 Phase Enum

```python
class CyclePhase(str, Enum):
    """GEP phase identifiers."""
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
```

### 4.2 Valid Transitions

| From | To | Trigger | Gate |
|------|-----|---------|------|
| PLANNING | CLARIFYING | Agent A submits questions | None |
| PLANNING | ARCHITECTING | No questions needed | None |
| CLARIFYING | CLARIFYING | Entity B answers, Agent A has follow-up | Soft |
| CLARIFYING | ARCHITECTING | All questions answered | None |
| ARCHITECTING | EXECUTING | Entity B approves architecture | **Strict** |
| ARCHITECTING | CLARIFYING | Entity B requests changes | None |
| EXECUTING | TESTING | Implementation complete | None |
| TESTING | FIXING | Tests fail | Soft (auto) |
| TESTING | VERIFYING | Tests pass | None |
| FIXING | TESTING | Fixes applied | Soft (auto) |
| VERIFYING | COMPLETING | Entity B approves | **Strict** |
| VERIFYING | FIXING | Entity B requests adjustments | None |
| COMPLETING | COMPLETED | Final acceptance | **Strict** |
| Any | CANCELLED | Entity B cancels | None |
| Any | FAILED | Unrecoverable error | None |

### 4.3 Gate Enforcement

```python
class GateType(str, Enum):
    """Phase gate enforcement types."""
    NONE = "none"           # Auto-progress
    SOFT = "soft"           # Auto-progress with notification
    STRICT = "strict"       # Requires explicit approval

PHASE_GATES: Dict[CyclePhase, GateType] = {
    CyclePhase.PLANNING: GateType.NONE,
    CyclePhase.CLARIFYING: GateType.SOFT,
    CyclePhase.ARCHITECTING: GateType.STRICT,   # Entity B must approve
    CyclePhase.EXECUTING: GateType.NONE,
    CyclePhase.TESTING: GateType.SOFT,
    CyclePhase.FIXING: GateType.SOFT,           # Auto-loop with Testing
    CyclePhase.VERIFYING: GateType.STRICT,      # Entity B must verify
    CyclePhase.COMPLETING: GateType.STRICT,     # Entity B final acceptance
}
```

## 5. Entity B Timeout Handling

When Entity B doesn't respond to clarification questions or approval requests within the configured SLA, the system applies a configurable timeout policy.

### 5.1 Timeout Policy Enum

```python
class TimeoutPolicy(str, Enum):
    """Configurable timeout handling policies."""
    PAUSE_WITH_NOTIFICATION = "pause_with_notification"  # Default
    AUTO_ESCALATE = "auto_escalate"
    PROCEED_WITH_ASSUMPTIONS = "proceed_with_assumptions"
```

### 5.2 Policy Behaviors

| Policy | Behavior |
|--------|----------|
| `PAUSE_WITH_NOTIFICATION` | Pause the cycle, send notification to Entity B and configured escalation contacts. Task remains in current phase until Entity B responds. **(Default)** |
| `AUTO_ESCALATE` | Escalate to backup reviewer (configured per task or organization). If no backup, falls back to pause. |
| `PROCEED_WITH_ASSUMPTIONS` | Agent A documents assumptions and proceeds. Creates audit trail noting unconfirmed assumptions. |

### 5.3 Timeout Configuration

```python
@dataclass
class TimeoutConfig:
    """Timeout configuration for GEP cycles."""
    clarification_timeout_hours: int = 24
    architecture_approval_timeout_hours: int = 48
    verification_timeout_hours: int = 24
    policy: TimeoutPolicy = TimeoutPolicy.PAUSE_WITH_NOTIFICATION
    escalation_contact_ids: List[str] = field(default_factory=list)
    max_escalation_attempts: int = 3
```

## 6. Data Models

### 6.1 TaskCycle

```python
@dataclass
class TaskCycle:
    """Complete GEP task cycle state."""
    cycle_id: str                           # UUID for the cycle
    task_id: str                            # Related task from TaskService
    assigned_agent_id: str                  # Agent A
    requester_entity_id: str                # Entity B (user_id or agent_id)
    requester_entity_type: str              # "user" or "agent"

    # Phase tracking
    current_phase: CyclePhase
    phase_history: List[PhaseTransition]    # Full audit trail

    # Artifacts
    architecture_doc_id: Optional[str]      # ArchitectureDoc reference
    acceptance_criteria: List[str]          # From Entity B

    # Clarifications
    clarification_thread_id: Optional[str]  # ClarificationThread reference

    # Timeout handling
    timeout_config: TimeoutConfig
    last_entity_b_interaction: datetime
    timeout_warnings_sent: int

    # Testing integration
    test_iterations: int                    # Testing→Fixing loop count
    max_test_iterations: int                # Default 10

    # Reflection integration
    reflection_trigger_enabled: bool        # Trigger ReflectionService on test failures
    extracted_behavior_ids: List[str]       # Behaviors extracted during this cycle

    # Metadata
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]
    metadata: Dict[str, Any]
```

### 6.2 PhaseTransition

```python
@dataclass
class PhaseTransition:
    """Record of a phase change."""
    transition_id: str
    from_phase: CyclePhase
    to_phase: CyclePhase
    triggered_by: str                       # agent_id or entity_id
    trigger_type: str                       # "auto", "approval", "timeout", "manual"
    gate_type: GateType
    timestamp: datetime
    notes: Optional[str]
    artifacts: Dict[str, Any]               # Phase-specific data
```

### 6.3 ClarificationThread

```python
@dataclass
class ClarificationMessage:
    """Single message in a clarification thread."""
    message_id: str
    sender_id: str
    sender_type: str                        # "agent" or "entity"
    content: str
    attachments: List[str]                  # Artifact IDs
    timestamp: datetime

@dataclass
class ClarificationThread:
    """Q&A thread between Agent A and Entity B."""
    thread_id: str
    cycle_id: str
    status: str                             # "pending_response", "answered", "timed_out"
    messages: List[ClarificationMessage]
    created_at: datetime
    last_response_at: Optional[datetime]
    waiting_for: str                        # "agent" or "entity"
```

### 6.4 ArchitectureDoc

```python
@dataclass
class ArchitectureDoc:
    """Architecture/design document created by Agent A."""
    doc_id: str
    cycle_id: str
    version: int                            # Incremented on updates

    # Content
    title: str
    summary: str
    design_sections: List[DesignSection]
    implementation_plan: List[PlanStep]
    acceptance_criteria: List[str]

    # Review state
    review_status: str                      # "draft", "pending_review", "approved", "revision_requested"
    reviewer_comments: List[ReviewComment]

    # Metadata
    created_at: datetime
    updated_at: datetime
    approved_at: Optional[datetime]
    approved_by: Optional[str]

@dataclass
class DesignSection:
    """Section of architecture document."""
    section_id: str
    title: str
    content: str                            # Markdown content
    diagrams: List[str]                     # Diagram artifact IDs
    order: int

@dataclass
class PlanStep:
    """Implementation plan step."""
    step_id: str
    title: str
    description: str
    estimated_duration: Optional[str]
    dependencies: List[str]                 # Other step IDs
    status: str                             # "pending", "in_progress", "completed", "skipped"
    order: int
```

## 7. Role Mapping

GEP phases integrate with the existing Student/Teacher/Strategist role system:

| Phase | Primary Role | Rationale |
|-------|--------------|-----------|
| PLANNING | 🧠 Strategist | Requires analysis, decomposition, and strategic thinking |
| CLARIFYING | 🧠 Strategist | Formulating effective questions requires domain expertise |
| ARCHITECTING | 🧠 Strategist | Design decisions require architectural thinking |
| EXECUTING | 📖 Student | Following established plan with known patterns |
| TESTING | 📖 Student | Running tests following established procedures |
| FIXING | 📖 Student | Applying fixes based on test results |
| VERIFYING | 🎓 Teacher | Validating work quality and completeness |
| COMPLETING | 📖 Student | Final administrative closure |

### Role Transitions During Cycle

```
🎭 PLANNING: Role: Strategist
📋 Rationale: Analyzing task requirements and formulating approach
🔗 Behaviors: behavior_validate_product_hypotheses, behavior_design_api_contract

⬆️ Transitioning: PLANNING → CLARIFYING
🎭 CLARIFYING: Role: Strategist
📋 Rationale: Formulating clarifying questions for Entity B

⬆️ Transitioning: CLARIFYING → ARCHITECTING
🎭 ARCHITECTING: Role: Strategist
📋 Rationale: Creating architecture document for approval

⛔ STRICT GATE: Awaiting Entity B approval...
✅ Architecture approved by Entity B

⬆️ Transitioning: ARCHITECTING → EXECUTING
🎭 EXECUTING: Role: Student
📋 Rationale: Implementing according to approved plan
🔗 Behaviors: [behaviors from BCI retrieval]

⬆️ Transitioning: EXECUTING → TESTING
🎭 TESTING: Role: Student
📋 Rationale: Running tests on implementation

🔄 Test failures detected → Triggering ReflectionService
⬆️ Transitioning: TESTING → FIXING (Soft Gate)

🎭 FIXING: Role: Student
📋 Rationale: Applying fixes based on test results

⬆️ Transitioning: FIXING → TESTING (Loop iteration 2)
...

✅ All tests passing
⬆️ Transitioning: TESTING → VERIFYING

🎭 VERIFYING: Role: Teacher
📋 Rationale: Validating work quality for Entity B review

⛔ STRICT GATE: Awaiting Entity B verification...
✅ Entity B approves

⬆️ Transitioning: VERIFYING → COMPLETING
🎭 COMPLETING: Role: Student
📋 Rationale: Final administrative closure

⛔ STRICT GATE: Final acceptance...
✅ Task cycle completed
```

## 8. Integration with ReflectionService

When tests fail during the TESTING phase, GEP triggers the ReflectionService to extract potential behaviors:

### 8.1 Trigger Conditions

- Phase is TESTING
- Test execution produces failures
- `reflection_trigger_enabled` is True (default)
- Sufficient trace data available (≥3 steps)

### 8.2 Integration Flow

```
TESTING Phase
     │
     ├─ Tests Pass ──────────────────────────────► VERIFYING Phase
     │
     └─ Tests Fail
          │
          ├─ 1. Log test failure trace
          │
          ├─ 2. Call ReflectionService.reflect()
          │      - trace_text: test execution trace
          │      - run_id: cycle.task_id
          │      - min_quality_score: 0.6
          │
          ├─ 3. Store extracted behavior candidates
          │      - Link to cycle.extracted_behavior_ids
          │      - Tag with "gep_testing_extraction"
          │
          └─ 4. Transition to FIXING Phase
               - Include reflection results in fixing context
               - Agent A can apply extracted behaviors
```

### 8.3 Reflection Request Configuration

```python
def _trigger_reflection_on_test_failure(
    self,
    cycle: TaskCycle,
    test_trace: str,
) -> List[str]:
    """Trigger ReflectionService for test failures."""
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
    cycle.extracted_behavior_ids.extend(extracted_ids)

    return extracted_ids
```

## 9. MCP Tools

### 9.1 Tool Catalog

| Tool | Description | Required Params |
|------|-------------|-----------------|
| `cycle.create` | Create new GEP cycle for a task | task_id, assigned_agent_id, requester_entity_id |
| `cycle.getPhase` | Get current phase and cycle state | cycle_id |
| `cycle.transitionPhase` | Manually transition phase (respects gates) | cycle_id, target_phase |
| `cycle.submitClarification` | Submit clarification question or answer | cycle_id, message, sender_type |
| `cycle.createArchitecture` | Create/update architecture document | cycle_id, title, sections, plan |
| `cycle.approveArchitecture` | Entity B approves architecture (strict gate) | cycle_id, approval_notes |
| `cycle.submitTestResults` | Report test results (triggers reflection if failures) | cycle_id, passed, trace |
| `cycle.requestVerification` | Request Entity B verification | cycle_id, summary |
| `cycle.acceptCompletion` | Entity B final acceptance (strict gate) | cycle_id, acceptance_notes |
| `cycle.setTimeoutPolicy` | Configure timeout handling | cycle_id, policy, timeout_hours |
| `cycle.cancel` | Cancel cycle | cycle_id, reason |
| `cycle.getHistory` | Get phase transition history | cycle_id |

### 9.2 Tool Schemas

```json
{
  "cycle.create": {
    "description": "Create a new Amprealize Execution Protocol (GEP) cycle for a task",
    "inputSchema": {
      "type": "object",
      "required": ["task_id", "assigned_agent_id", "requester_entity_id"],
      "properties": {
        "task_id": {"type": "string", "description": "Task ID from TaskService"},
        "assigned_agent_id": {"type": "string", "description": "Agent A who will execute"},
        "requester_entity_id": {"type": "string", "description": "Entity B who requested the task"},
        "requester_entity_type": {"type": "string", "enum": ["user", "agent"], "default": "user"},
        "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
        "timeout_policy": {"type": "string", "enum": ["pause_with_notification", "auto_escalate", "proceed_with_assumptions"]},
        "max_test_iterations": {"type": "integer", "default": 10}
      }
    }
  },
  "cycle.approveArchitecture": {
    "description": "Entity B approves the architecture document (strict gate)",
    "inputSchema": {
      "type": "object",
      "required": ["cycle_id"],
      "properties": {
        "cycle_id": {"type": "string"},
        "approval_notes": {"type": "string"},
        "approved_criteria": {"type": "array", "items": {"type": "string"}}
      }
    }
  },
  "cycle.submitTestResults": {
    "description": "Submit test execution results. Triggers ReflectionService on failures.",
    "inputSchema": {
      "type": "object",
      "required": ["cycle_id", "passed"],
      "properties": {
        "cycle_id": {"type": "string"},
        "passed": {"type": "boolean"},
        "test_trace": {"type": "string", "description": "Test execution trace for reflection"},
        "test_summary": {"type": "string"},
        "failed_tests": {"type": "array", "items": {"type": "string"}}
      }
    }
  },
  "cycle.acceptCompletion": {
    "description": "Entity B provides final acceptance (strict gate)",
    "inputSchema": {
      "type": "object",
      "required": ["cycle_id", "accepted"],
      "properties": {
        "cycle_id": {"type": "string"},
        "accepted": {"type": "boolean"},
        "acceptance_notes": {"type": "string"},
        "adjustment_requests": {"type": "array", "items": {"type": "string"}}
      }
    }
  }
}
```

## 10. Database Schema

### 10.1 task_cycles Table

```sql
CREATE TABLE IF NOT EXISTS task_cycles (
    cycle_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    assigned_agent_id TEXT NOT NULL,
    requester_entity_id TEXT NOT NULL,
    requester_entity_type TEXT NOT NULL DEFAULT 'user',

    -- Phase tracking
    current_phase TEXT NOT NULL DEFAULT 'planning',

    -- Artifact references
    architecture_doc_id TEXT,
    clarification_thread_id TEXT,

    -- Acceptance criteria (JSONB array)
    acceptance_criteria JSONB DEFAULT '[]',

    -- Timeout configuration
    timeout_policy TEXT NOT NULL DEFAULT 'pause_with_notification',
    clarification_timeout_hours INTEGER DEFAULT 24,
    architecture_approval_timeout_hours INTEGER DEFAULT 48,
    verification_timeout_hours INTEGER DEFAULT 24,
    escalation_contact_ids JSONB DEFAULT '[]',
    last_entity_b_interaction TIMESTAMP,
    timeout_warnings_sent INTEGER DEFAULT 0,

    -- Testing integration
    test_iterations INTEGER DEFAULT 0,
    max_test_iterations INTEGER DEFAULT 10,

    -- Reflection integration
    reflection_trigger_enabled BOOLEAN DEFAULT TRUE,
    extracted_behavior_ids JSONB DEFAULT '[]',

    -- Metadata
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_task_cycles_task_id ON task_cycles(task_id);
CREATE INDEX IF NOT EXISTS idx_task_cycles_agent ON task_cycles(assigned_agent_id);
CREATE INDEX IF NOT EXISTS idx_task_cycles_requester ON task_cycles(requester_entity_id);
CREATE INDEX IF NOT EXISTS idx_task_cycles_phase ON task_cycles(current_phase);
CREATE INDEX IF NOT EXISTS idx_task_cycles_created ON task_cycles(created_at DESC);
```

### 10.2 phase_transitions Table

```sql
CREATE TABLE IF NOT EXISTS phase_transitions (
    transition_id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL REFERENCES task_cycles(cycle_id),
    from_phase TEXT NOT NULL,
    to_phase TEXT NOT NULL,
    triggered_by TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    gate_type TEXT NOT NULL,
    notes TEXT,
    artifacts JSONB DEFAULT '{}',
    timestamp TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_phase_transitions_cycle ON phase_transitions(cycle_id);
CREATE INDEX IF NOT EXISTS idx_phase_transitions_timestamp ON phase_transitions(timestamp DESC);
```

### 10.3 clarification_threads Table

```sql
CREATE TABLE IF NOT EXISTS clarification_threads (
    thread_id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL REFERENCES task_cycles(cycle_id),
    status TEXT NOT NULL DEFAULT 'pending_response',
    waiting_for TEXT NOT NULL DEFAULT 'entity',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_response_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS clarification_messages (
    message_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES clarification_threads(thread_id),
    sender_id TEXT NOT NULL,
    sender_type TEXT NOT NULL,
    content TEXT NOT NULL,
    attachments JSONB DEFAULT '[]',
    timestamp TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_clarification_threads_cycle ON clarification_threads(cycle_id);
CREATE INDEX IF NOT EXISTS idx_clarification_messages_thread ON clarification_messages(thread_id);
```

### 10.4 architecture_docs Table

```sql
CREATE TABLE IF NOT EXISTS architecture_docs (
    doc_id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL REFERENCES task_cycles(cycle_id),
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
);

CREATE INDEX IF NOT EXISTS idx_architecture_docs_cycle ON architecture_docs(cycle_id);
CREATE INDEX IF NOT EXISTS idx_architecture_docs_status ON architecture_docs(review_status);
```

## 11. Behavior Definition

Add to `AGENTS.md` Quick Triggers and Behaviors:

### Quick Trigger

```markdown
| task cycle, GEP, execution protocol, phase gate | `behavior_follow_gep_cycle` | 📖 Student |
```

### Behavior Definition

```markdown
### `behavior_follow_gep_cycle`
- **When**: Executing a task that requires the full Amprealize Execution Protocol lifecycle.
- **Role**: Varies by phase (see Role Mapping in TASK_CYCLE_SERVICE_CONTRACT.md)
- **Steps**:
  1. **PLANNING**: Analyze task requirements, identify unknowns, formulate initial approach
  2. **CLARIFYING**: Submit clarification questions to Entity B via `cycle.submitClarification`; await responses
  3. **ARCHITECTING**: Create architecture document via `cycle.createArchitecture`; await Entity B approval (strict gate)
  4. **EXECUTING**: Implement according to approved plan; cite behaviors via BCI
  5. **TESTING**: Run tests; if failures occur, ReflectionService extracts behaviors automatically
  6. **FIXING**: Apply fixes based on test results and extracted behaviors; loop to TESTING (soft gate)
  7. **VERIFYING**: Request Entity B verification via `cycle.requestVerification` (strict gate)
  8. **COMPLETING**: Obtain final acceptance via `cycle.acceptCompletion` (strict gate)
- **Integration Points**:
  - Use `behavior_design_api_contract` during ARCHITECTING for API designs
  - Use `behavior_design_test_strategy` during TESTING phase
  - Extracted behaviors from test failures feed into behavior lifecycle (DISCOVER→PROPOSE→APPROVE→INTEGRATE)
```

## 12. Telemetry Events

| Event | Trigger | Fields |
|-------|---------|--------|
| `gep.cycle_created` | New cycle created | cycle_id, task_id, agent_id, entity_id |
| `gep.phase_transition` | Phase changes | cycle_id, from_phase, to_phase, gate_type, trigger_type |
| `gep.clarification_submitted` | Q&A message | cycle_id, thread_id, sender_type, message_length |
| `gep.architecture_created` | Doc created/updated | cycle_id, doc_id, version, section_count |
| `gep.architecture_approved` | Entity B approves | cycle_id, doc_id, approver_id, approval_time_hours |
| `gep.test_results_submitted` | Test results | cycle_id, passed, test_count, failure_count |
| `gep.reflection_triggered` | ReflectionService called | cycle_id, test_trace_length, candidates_extracted |
| `gep.verification_requested` | Awaiting Entity B | cycle_id, summary_length |
| `gep.completion_accepted` | Final acceptance | cycle_id, total_duration_hours, test_iterations |
| `gep.timeout_warning` | Approaching timeout | cycle_id, phase, hours_remaining, policy |
| `gep.timeout_triggered` | Timeout reached | cycle_id, phase, policy_applied |

## 13. Error Handling

| Error | Handling |
|-------|----------|
| Invalid phase transition | Return error with valid transitions for current phase |
| Strict gate without approval | Block transition, return gate requirements |
| Max test iterations exceeded | Transition to VERIFYING with warning flag |
| Timeout reached | Apply configured policy (pause/escalate/proceed) |
| ReflectionService unavailable | Log warning, continue without behavior extraction |
| Entity B not found | Return error, require valid requester |

## 14. Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Cycle completion rate | >80% | completed / (completed + cancelled + failed) |
| Average cycle duration | <48h for small tasks | Hours from creation to completion |
| Clarification round-trips | <3 average | Messages before ARCHITECTING |
| Test iteration count | <5 average | Testing→Fixing loops |
| Entity B response time | <24h P50 | Time to respond to gates |
| Behavior extraction rate | >0.5/failure | Candidates extracted per test failure |

## 15. Implementation Phases

1. **Phase 1 - Core Models** (This PR)
   - TaskCycle, PhaseTransition data models
   - Database migrations
   - TaskCycleService with phase state machine

2. **Phase 2 - Clarification & Architecture**
   - ClarificationThread management
   - ArchitectureDoc creation and versioning
   - Entity B notification system

3. **Phase 3 - Testing Integration**
   - Test result submission
   - ReflectionService integration
   - Behavior extraction pipeline

4. **Phase 4 - MCP Tools & Parity**
   - All cycle.* MCP tools
   - CLI commands
   - VS Code extension integration
