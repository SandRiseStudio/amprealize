# AgentOrchestratorService Contract

## Purpose
Enable runtime assignment and switching of functional agents (Engineering, Product, Finance, Security, etc.) across the Strategist → Teacher → Student pipeline so every run inherits the correct playbooks, behaviors, and compliance guardrails. The service exposes a single orchestration contract that all surfaces (Web, REST API, CLI, MCP, VS Code) must use when selecting or overriding agents, keeping telemetry and audit evidence consistent with `PRD_NEXT_STEPS.md` and `AGENTS.md`.

## Services & Endpoints
- **gRPC Service:** `amprealize.agentorchestrator.v1.AgentOrchestratorService`
- **REST Base Path:** `/v1/agents`
- **MCP Tools:** `agents.assign`, `agents.switch`, `agents.status`
- **CLI Commands (planned):** `amprealize agents assign`, `amprealize agents switch`, `amprealize agents status`

## Schemas (JSON / Proto)
### `AgentPersona`
| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `agent_id` | string | Yes | Canonical agent slug (e.g., `engineering`, `product`, `finance`). |
| `display_name` | string | Yes | Human readable name. |
| `role_alignment` | enum | Yes | `STRATEGIST|TEACHER|STUDENT|MULTI_ROLE`. |
| `default_behaviors` | string[] | Yes | Behavior IDs automatically injected when the agent is selected. |
| `playbook_refs` | string[] | Yes | Links to playbooks (`AGENT_ENGINEERING.md`, etc.). |
| `capabilities` | string[] | No | Additional metadata (e.g., `"requires_compliance_review"`). |

### `AgentAssignment`
| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `assignment_id` | UUID | Yes | Primary identifier for the agent assignment session. |
| `run_id` | UUID | Yes | Associated run from RunService. |
| `active_agent` | `AgentPersona` | Yes | Currently active agent persona. |
| `stage` | enum | Yes | `PLAN|EXECUTE|REFLECT`. |
| `heuristics_applied` | object | Yes | Map of heuristic names to evaluation details (scores, triggers). |
| `requested_by` | object | Yes | `{ surface: enum, actor_id: UUID }`. |
| `timestamp` | RFC3339 | Yes | Time of assignment or switch. |
| `audit_log_event_id` | UUID | No | Link to immutable audit event (`AUDIT_LOG_STORAGE.md`). |
| `metadata` | object | No | Free-form context (task taxonomy, severity, compliance flags). |

### `AssignmentRequest`
- `run_id` (UUID)
- `requested_agent_id` (string optional)
- `context` (object: `task_type`, `severity`, `compliance_tags`, `behaviors_cited`, `surface`)
- `policy_overrides` (object optional)

### `SwitchRequest`
- `assignment_id` (UUID)
- `target_agent_id` (string)
- `reason` (string)
- `allow_downgrade` (bool, default false)

### `AgentStatus`
- `assignment_id` (UUID)
- `run_id` (UUID)
- `active_agent` (`AgentPersona`)
- `history` (`AgentSwitchEvent[]`)
- `next_recommended_agent` (`AgentPersona` optional)
- `metrics_snapshot` (object: `behavior_reuse_pct`, `token_savings_pct`, `completion_confidence`, `compliance_risk`)

### `AgentSwitchEvent`
| Field | Type | Description |
| --- | --- | --- |
| `event_id` | UUID | Unique switch event identifier. |
| `from_agent_id` | string | Previously active agent. |
| `to_agent_id` | string | Newly active agent. |
| `stage` | enum | Pipeline stage at switch. |
| `trigger` | enum | `HEURISTIC|MANUAL|ESCALATION|FALLBACK`. |
| `trigger_details` | object | Key/value explanation captured for audit. |
| `timestamp` | RFC3339 | Time of switch. |
| `issued_by` | object | `{ actor_id: UUID, surface: enum }`. |

## RBAC Scopes
| Scope | Description | Default Roles |
| --- | --- | --- |
| `agents.assign` | Request initial agent assignment for a run. | Strategist, Teacher, Admin |
| `agents.switch` | Trigger mid-run agent switches or escalations. | Strategist, Admin |
| `agents.override` | Override heuristic decisions or force downgrade. | Admin, Compliance |
| `agents.read` | Inspect assignment history and metrics. | Strategist, Teacher, Student, Admin |

Scopes are issued via AgentAuthService; CLI/IDE consumers must invoke `auth.ensureGrant` with the relevant scope bundle before calling orchestration endpoints. Device flow tokens persist in KeychainTokenStore per MCP device-flow guidance.

## Orchestration Flow
1. **Assignment:** Client submits `AssignmentRequest`; service evaluates policy heuristics (task taxonomy, compliance tags, telemetry trends) and returns `AgentAssignment` with the chosen persona.
2. **Run Integration:** Assignment is persisted alongside RunService records; `agent_assignment` metadata is embedded in the run payload so every progress update carries agent context.
3. **Monitoring:** MetricsService subscription includes agent dimensions (reuse %, token savings %, completion, compliance) allowing dashboards to compare agent effectiveness.
4. **Switching:** When heuristics or users detect drift, `SwitchRequest` triggers an agent change. The service logs `AgentSwitchEvent`, updates RunService metadata, and emits telemetry (`agent_switch` events).
5. **Audit & Telemetry:** Each assignment and switch emits telemetry adhering to `TELEMETRY_SCHEMA.md` (fields: `run_id`, `agent_id`, `stage`, `trigger`, `scores`) and writes an immutable audit entry.
6. **Status Retrieval:** Clients call `agents.status` to fetch current assignment, history, and recommended next agent based on heuristics.

## Policy Heuristics
- **Task Taxonomy Mapping:** Use task classification (e.g., remediation vs. analytics) to select default agent. Dictionary maintained in `schema/agents/task_taxonomy.yaml`.
- **Compliance Risk Score:** If compliance tags include high-risk scopes, escalate to Compliance agent for Teacher/Student stages.
- **Token Budget Monitoring:** If token usage exceeds thresholds, recommend switching to Efficiency-focused agents.
- **Incident Severity Escalation:** Severity levels trigger Security or Product agents when policy dictates.
- **Manual Overrides:** Users can force an assignment; overrides are logged with justification and surfaced in compliance dashboards.

Heuristic configurations are stored in the shared configuration service and should be versioned with change history in `PRD_ALIGNMENT_LOG.md`.

## Telemetry & Metrics
- **Events:** `agent_assigned`, `agent_switch`, `agent_override`, `agent_recommendation_issued`.
- **Metrics Dimensions:** `agent_id`, `run_stage`, `surface`, `task_type`, `compliance_risk_level`.
- **Success Criteria:** Track PRD KPIs (behavior reuse %, token savings %, completion rate %, compliance coverage %) per agent persona.
- **Dashboards:** Extend Metabase dashboards and VS Code analytics panel to visualize agent effectiveness and switching frequency.

## Parity Requirements
- **CLI:** `amprealize agents assign/switch/status` must call the same endpoints via shared SDK. Output includes current agent, heuristics, and next recommendation.
- **REST:** Publish OpenAPI schemas under `schema/agents/v1/*.json`; enforce versioning and backward-compatible changes.
- **MCP:** Tool manifests generated from schemas to guarantee IDE and partner integration parity.
- **VS Code:** Execution Tracker view should surface agent badges and allow allowed overrides per CAP matrix row.
- **Contract Tests:** Add parity tests under `tests/test_agent_orchestrator_parity.py` comparing CLI vs REST vs MCP responses using golden fixtures.

## Dependencies
- **RunService:** Persists `agent_assignment` metadata and exposes agent context through `/v1/runs` endpoints.
- **MetricsService:** Aggregates KPIs by agent persona for dashboards and recommendations.
- **BehaviorService / WorkflowService:** Supplies default behaviors/playbooks for each agent persona.
- **AgentAuthService:** Issues scopes and enforces policy decisions; integrates with consent flows when agent switching touches sensitive scopes.
- **Telemetry Pipeline:** Ensures agent events are stored in the warehouse and dashboards.
- **Audit Log Storage:** Captures immutable evidence of assignments and switches in alignment with `AUDIT_LOG_STORAGE.md`.

## Implementation Tasks (Milestone 3 – Production Infrastructure)
1. **Contract Finalization:** Publish proto + JSON schemas (`proto/agentorchestrator/v1/*.proto`, `schema/agents/v1/*.json`) and update `docs/capability_matrix.md` row.
2. **Service Scaffold:** Implement gRPC/REST handlers in `amprealize/agent_orchestrator_service.py`, add adapters in `amprealize/adapters.py`.
3. **RunService Integration:** Extend run creation/completion payloads with agent metadata and parity tests.
4. **CLI & MCP Updates:** Ship new commands and tool manifests; add integration tests ensuring `--agent` flag works across surfaces.
5. **Telemetry Hooks:** Emit agent events; update warehouse schema and Metabase dashboards to include agent dimensions.
6. **Governance:** Refresh `AGENTS.md`, `agent-compliance-checklist.md`, `PRD_ALIGNMENT_LOG.md`, and `BUILD_TIMELINE.md` with orchestration evidence.
7. **Policy Engine:** Implement heuristic engine with feature-flagged configuration, unit tests, and documentation in `docs/AGENT_ORCHESTRATOR_POLICIES.md` (future).

## Change Management
- Any schema change requires synchronized updates to proto, JSON schema, SDKs, and capability matrix.
- Agent persona additions must include updated playbooks in `AGENT_*.md` and taxonomy mappings.
- Release PRs must record action logs referencing this contract and demonstrate parity tests.
