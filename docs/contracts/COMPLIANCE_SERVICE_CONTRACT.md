# ComplianceService Contract

## Purpose
Provide a standardized compliance checklist engine across Platform UI, REST API, CLI, and MCP tools. This service ensures every Strategist → Teacher → Student workflow captures required evidence steps, validates adherence, and surfaces compliance coverage metrics (targeting the PRD goal of 95% checklist coverage).

## Implementation Status
**Milestone 1 (Current):** In-memory stub implementation for contract validation and parity testing. Each CLI command/API request instantiates a fresh service instance with empty state—no cross-command persistence. Suitable for testing service logic, adapter consistency, and CLI/MCP tool wiring.

**Milestone 2+ (Planned):** Persistent backend (PostgreSQL/SQLite) with shared state across surfaces. Adapters remain unchanged; only the ComplianceService constructor will swap from in-memory storage to database connections.

## Services & Endpoints
- **gRPC Service:** `amprealize.compliance.v1.ComplianceService`
- **REST Base Path:** `/v1/compliance`
- **MCP Tools:** `compliance.recordStep`, `compliance.getChecklist`, `compliance.listChecklists`, `compliance.validateChecklist`

## Schemas (JSON / Proto)
### `ChecklistStep`
| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `step_id` | UUID | Yes | Primary identifier. |
| `checklist_id` | UUID | Yes | Parent checklist reference. |
| `timestamp` | RFC3339 | Yes | Time of step execution. |
| `actor` | Object | Yes | `{ id: UUID, role: enum, surface: enum }`. |
| `title` | string | Yes | ≤ 100 chars, actionable step description. |
| `status` | enum | Yes | `PENDING|IN_PROGRESS|COMPLETED|FAILED|SKIPPED`. |
| `evidence` | Object | No | `{ artifact_path, action_id, checksum, notes }`. |
| `behaviors_cited` | string[] | No | Behavior IDs referenced during step. |
| `related_run_id` | UUID | No | RunService association. |
| `audit_log_event_id` | UUID | No | Link to audit log entry (`AUDIT_LOG_STORAGE.md`). |
| `validation_result` | Object | No | `{ passed: bool, errors: string[], warnings: string[] }`. |

### `Checklist`
| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `checklist_id` | UUID | Yes | Primary identifier. |
| `title` | string | Yes | ≤ 160 chars, checklist name. |
| `description` | string | No | Markdown overview of scope/purpose. |
| `template_id` | UUID | No | Reference to workflow template. |
| `milestone` | string | No | E.g., "Milestone 1", "Milestone 2". |
| `compliance_category` | string[] | Yes | E.g., ["SOC2", "GDPR", "Internal"]. |
| `steps` | ChecklistStep[] | Yes | Ordered list of steps. |
| `created_at` | RFC3339 | Yes | Checklist creation time. |
| `completed_at` | RFC3339 | No | Set when all steps COMPLETED/SKIPPED. |
| `coverage_score` | float | Yes | 0-1 score indicating % completion. |

### `RecordStepRequest`
- `checklist_id` (UUID)
- `title` (string)
- `status` (enum)
- `evidence` (object optional)
- `behaviors_cited` (string[] optional)
- `related_run_id` (UUID optional)

### `GetChecklistRequest`
- `checklist_id` (UUID)

### `ListChecklistsRequest`
- `milestone` (string optional)
- `compliance_category` (string[] optional)
- `status_filter` (enum optional: `ACTIVE|COMPLETED|FAILED`)

### `ValidateChecklistRequest`
- `checklist_id` (UUID)

### `ValidateChecklistResponse`
- `checklist_id` (UUID)
- `valid` (bool)
- `coverage_score` (float)
- `missing_steps` (string[] titles)
- `failed_steps` (string[] titles)
- `warnings` (string[])

## RBAC Scopes
| Scope | Description | Default Roles |
| --- | --- | --- |
| `compliance.read` | List and fetch checklists created by same org/team. | Strategist, Teacher, Student, Admin |
| `compliance.write` | Record checklist steps and create new checklists. | Strategist, Teacher, Student |
| `compliance.validate` | Trigger validation and view coverage reports. | Strategist, Compliance, Admin |
| `compliance.admin` | Manage templates, purge failed steps, adjust retention. | Admin, Compliance |

Requests must include AgentAuth-issued OAuth scopes; CLI obtains tokens via device flow and tool adapters call `auth.ensureGrant` prior to invoking ComplianceService endpoints per `SECRETS_MANAGEMENT_PLAN.md`.

## Audit & Compliance Integration
- Every `compliance.recordStep` call writes an audit event (link stored in `audit_log_event_id`).
- Checklist validation produces immutable evidence logs persisted per `AUDIT_LOG_STORAGE.md`.
- Schema version changes require update to `schema/compliance/v1/*.json` and an entry in `PRD_ALIGNMENT_LOG.md`.

## Parity Requirements
- CLI commands (`amprealize compliance record-step`, `amprealize compliance list`, `amprealize compliance validate`) call these endpoints directly via shared SDK.
- Platform UI uses the same REST endpoints; feature toggles gate UI until API parity tests pass.
- MCP tool definitions auto-generated from proto; IDE extension consumes `compliance.getChecklist` for dashboard view.
- Contract tests compare responses across surfaces (CLI vs REST vs MCP) using golden fixtures stored under `tests/contracts/compliance/`.

## Validation Engine Behavior
1. Fetch checklist by ID.
2. For each step:
   - Verify status is COMPLETED or SKIPPED.
   - Check evidence artifact exists (if required).
   - Validate behaviors_cited against behavior handbook (`AGENTS.md`).
3. Calculate `coverage_score` as (completed + skipped) / total steps.
4. Return validation result with missing/failed step details.
5. Emit telemetry events (`compliance_validation_start`, `compliance_validation_complete`).

## Workflow Templates
Checklists can be instantiated from templates that define:
- **Strategist template** – Plan approval, behavior retrieval, run scaffolding steps.
- **Teacher template** – Instruction synthesis, example generation, validation prep steps.
- **Student template** – Task execution, evidence capture, completion report steps.

Templates stored in `schema/compliance/templates/` as YAML and referenced by `template_id`. Future enhancements allow custom template creation (tracked in `PRD_NEXT_STEPS.md`).

## Error Handling
- Validation errors return HTTP 400 / gRPC INVALID_ARGUMENT with details.
- Step recording failures produce structured error log referencing failing checklist and remediation guidance.
- Idempotency keys supported on recordStep endpoint via `Idempotency-Key` header.

## Telemetry Events
- `compliance.step_recorded` – Emitted on successful step recording with checklist_id, step_id, status, coverage_score.
- `compliance.validation_triggered` – Emitted when validation starts with checklist_id, milestone.
- `compliance.validation_completed` – Emitted when validation finishes with valid, coverage_score, failed_count.
- `compliance.checklist_completed` – Emitted when all steps reach terminal status.

## Implementation Tasks (Milestone 1)
- Generate proto + JSON schemas and publish under `schema/compliance/v1/`.
- Scaffold service handlers (gRPC + REST gateway) returning stub responses (`amprealize/compliance_service.py`).
- Add CLI commands (`amprealize compliance record-step`, `list`, `validate`) with adapter parity (`amprealize/adapters.py`).
- Add contract tests ensuring CLI/REST/MCP parity (`tests/test_compliance_service_parity.py`).
- Integrate audit logging hooks and telemetry emission.
- Update capability matrix (`docs/capability_matrix.md`) and governance docs (`BUILD_TIMELINE.md`, `PRD_ALIGNMENT_LOG.md`).

Future enhancements tracked in `PRD_NEXT_STEPS.md` (template editing UI, approval workflows, multi-tenant checklists).

## Related Artifacts
- `docs/COMPLIANCE_CONTROL_MATRIX.md` – Maps checklist enforcement to SOC2/GDPR controls.
- `AGENTS.md` – Behavior handbook with compliance prompt (`behavior_handbook_compliance_prompt`).
- `ACTION_SERVICE_CONTRACT.md` – Action capture pattern serving as reference for this contract.
- `PROGRESS_TRACKER.md` – Milestone tracker leveraging checklist coverage scores.
- `TELEMETRY_SCHEMA.md` – Event definitions for compliance telemetry.
