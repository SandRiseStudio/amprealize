# Workflow Service Contract

**Version:** 1.0.0
**Status:** ✅ Implemented
**Last Updated:** 2025-10-16

## Overview

The **WorkflowService** manages Strategist/Teacher/Student workflow templates and enables behavior-conditioned inference (BCI) by injecting retrieved behaviors into runtime prompts. This service supports the PRD's goal of 70% behavior reuse and 30% token savings by providing reusable execution templates that leverage the procedural memory stored in the BehaviorService.

**Alignment:**
- **PRD.md**: Milestone 1 – Workflow Engine Foundation
- **AGENTS.md**: Strategist/Teacher/Student role definitions and handbook behaviors
- **MCP_SERVER_DESIGN.md**: Control-plane orchestration patterns
- **RETRIEVAL_ENGINE_PERFORMANCE.md**: Behavior retrieval integration requirements

---

## Service Capabilities

### Template Management
- **Create** workflow templates with role-specific step definitions (STRATEGIST/TEACHER/STUDENT/MULTI_ROLE)
- **Retrieve** templates by ID with full step details
- **List** templates with filters (role, tags)
- **Version** templates for evolution over time

### Behavior-Conditioned Inference (BCI)
- **Inject behaviors** into prompt templates at designated injection points (e.g., `{{BEHAVIORS}}`)
- **Auto-retrieve** behaviors based on template requirements or user-specified IDs
- **Format behaviors** for consistent presentation in prompts
- **Track behavior citations** for reuse metrics

### Workflow Execution
- **Run** templates with actor context and metadata
- **Track status** (PENDING → RUNNING → COMPLETED/FAILED/CANCELLED)
- **Account tokens** for behavior reuse analysis (compare with/without behaviors)
- **Emit telemetry** for all lifecycle events

---

## Data Models

### WorkflowRole Enum
```
STRATEGIST   - Decomposes requests, maps behaviors
TEACHER      - Explains plans, cites behaviors for educational context
STUDENT      - Executes plans, validates using behaviors
MULTI_ROLE   - Templates spanning multiple roles
```

### WorkflowTemplate
```json
{
  "template_id": "wf-<12-char-hex>",
  "name": "string",
  "description": "string",
  "role_focus": "STRATEGIST | TEACHER | STUDENT | MULTI_ROLE",
  "version": "semver",
  "created_at": "ISO8601",
  "created_by": {
    "id": "string",
    "role": "string",
    "surface": "CLI | API | MCP | WEB"
  },
  "steps": [
    {
      "step_id": "string",
      "name": "string",
      "description": "string",
      "prompt_template": "string with {{PLACEHOLDERS}}",
      "behavior_injection_point": "{{BEHAVIORS}}",
      "required_behaviors": ["behavior_id", ...],
      "validation_rules": {},
      "metadata": {}
    }
  ],
  "tags": ["string", ...],
  "metadata": {}
}
```

### WorkflowRun
```json
{
  "run_id": "run-<12-char-hex>",
  "template_id": "wf-<12-char-hex>",
  "template_name": "string",
  "role_focus": "STRATEGIST | TEACHER | STUDENT | MULTI_ROLE",
  "status": "PENDING | RUNNING | COMPLETED | FAILED | CANCELLED",
  "actor": {
    "id": "string",
    "role": "string",
    "surface": "string"
  },
  "steps": [
    {
      "step_id": "string",
      "status": "WorkflowStatus",
      "prompt_rendered": "string (with behaviors injected)",
      "behaviors_used": ["behavior_id", ...],
      "output": "string | null",
      "token_count": "integer | null",
      "started_at": "ISO8601 | null",
      "completed_at": "ISO8601 | null",
      "error": "string | null"
    }
  ],
  "started_at": "ISO8601",
  "completed_at": "ISO8601 | null",
  "total_tokens": "integer",
  "behaviors_cited": ["behavior_id", ...],
  "metadata": {}
}
```

---

## API Surface (Parity Contract)

### CLI Commands

```bash
# Template Management
amprealize workflow create-template \
  --name "Template Name" \
  --description "Description" \
  --role STRATEGIST \
  --steps-file steps.json \
  --tag <tag> \
  --metadata-file metadata.json \
  [--format json|table]

amprealize workflow list-templates \
  [--role STRATEGIST|TEACHER|STUDENT|MULTI_ROLE] \
  [--tag <tag>] \
  [--format json|table]

amprealize workflow get-template <template_id> \
  [--format json|table]

# Execution
amprealize workflow run <template_id> \
  [--behavior <behavior_id>] \
  [--metadata-file metadata.json] \
  [--actor-id <id>] \
  [--actor-role <role>] \
  [--format json|table]

amprealize workflow status <run_id> \
  [--format json|table]
```

### REST API Endpoints ✅

**Status:** Implemented via `RestWorkflowServiceAdapter` in `amprealize/adapters.py`

```
POST   /v1/workflows/templates           - Create template
GET    /v1/workflows/templates           - List templates
GET    /v1/workflows/templates/:id       - Get template
POST   /v1/workflows/runs                - Start run
GET    /v1/workflows/runs/:id            - Get run status
PATCH  /v1/workflows/runs/:id            - Update run status
```

**Evidence:**
- Implementation: `amprealize/adapters.py` (RestWorkflowServiceAdapter)
- Tests: `tests/test_workflow_parity.py` (17 parity tests covering REST/CLI/MCP)

### MCP Tools ✅

**Status:** Implemented via `MCPWorkflowServiceAdapter` + JSON manifests

```
workflow.template.create     - mcp/tools/workflow.template.create.json
workflow.template.list       - mcp/tools/workflow.template.list.json
workflow.template.get        - mcp/tools/workflow.template.get.json
workflow.run.start          - mcp/tools/workflow.run.start.json
workflow.run.status         - mcp/tools/workflow.run.status.json
```

**Evidence:**
- MCP Adapter: `amprealize/adapters.py` (MCPWorkflowServiceAdapter)
- Tool Manifests: `mcp/tools/workflow.*.json` (5 files)
- Tests: `tests/test_workflow_parity.py` (17 parity tests covering REST/CLI/MCP)

---

## Behavior Injection Algorithm

1. **Identify Injection Points**: Parse `prompt_template` for `behavior_injection_point` placeholders (default: `{{BEHAVIORS}}`)
2. **Retrieve Behaviors**:
   - If `behavior_ids` specified: fetch from BehaviorService by ID
   - If `required_behaviors` in step: auto-retrieve those IDs
   - If neither: skip injection (empty string replacement)
3. **Format Behaviors**:
   ```
   ## Available Behaviors

   - **behavior_name_1**: Description of behavior 1
   - **behavior_name_2**: Description of behavior 2

   Reference these behaviors by name when applicable.
   ```
4. **Replace Placeholder**: Substitute `{{BEHAVIORS}}` with formatted text
5. **Track Citations**: Record `behaviors_used` in run step metadata

---

## Telemetry Events

### workflow.template.created
```json
{
  "template_id": "wf-...",
  "name": "string",
  "role_focus": "STRATEGIST",
  "step_count": 3,
  "actor": { "id": "...", "role": "...", "surface": "..." }
}
```

### workflow.run.started
```json
{
  "run_id": "run-...",
  "template_id": "wf-...",
  "role_focus": "TEACHER",
  "actor": { "id": "...", "role": "...", "surface": "..." }
}
```

### plan_created
```json
{
  "run_id": "run-...",
  "template_id": "wf-...",
  "behavior_ids": ["bhv-..."],
  "behavior_count": 3,
  "baseline_tokens": 1800,
  "checklist_snapshot": { "checklist_id": "chk-...", "status": "DRAFT" },
  "metadata_keys": ["baseline_tokens", "checklist_snapshot"]
}
```

### execution_update
```json
{
  "run_id": "run-...",
  "template_id": "wf-...",
  "status": "COMPLETED",
  "output_tokens": 2500,
  "baseline_tokens": 3200,
  "token_savings_pct": 0.22,
  "behaviors_cited": ["bhv-..."],
  "step": "SUMMARY",
  "context_keys": ["project_id", "behaviors"],
  "completed_at": "2025-10-16T12:34:56Z"
}
```

### workflow.behavior.injected (Future)
```json
{
  "run_id": "run-...",
  "step_id": "step-1",
  "behaviors_injected": ["bhv-...", "bhv-..."],
  "prompt_length": 1200
}
```

---

## Storage Backend

**Phase 1 (Current):** SQLite database (`~/.amprealize/workflows.db`)
- Tables: `workflow_templates`, `workflow_runs`
- Schema enforces template/run relationships via foreign keys
- JSON serialization for complex nested structures (steps, metadata)

**Phase 2 (Planned):** PostgreSQL migration
- Enhanced indexing for search/filter performance
- JSON column types for flexible querying
- Replication support for production deployments

---

## Integration Points

### BehaviorService
- **Retrieval**: `BehaviorService.get_behavior(behavior_id)` fetches behavior details for injection
- **Search**: Future enhancement to auto-retrieve behaviors via semantic search based on step descriptions
- **Metrics**: Track behavior reuse rates to validate PRD's 70% reuse target

### ComplianceService
- **Evidence**: Workflow runs can be cited as evidence in compliance checklists
- **Audit**: All template creation/execution events logged for compliance review

### ActionService
- **Recording**: Workflow execution can trigger action recordings for reproducibility
- **Replay**: Future support for replaying workflow runs via ActionService

### TelemetryService
- **Event Emission**: All lifecycle events flow through TelemetryClient
- **Metrics**: Token counts feed into analytics dashboards tracking 30% token savings goal

---

## Validation Rules

### Template Creation
- `name`: Required, max 200 characters
- `description`: Required, max 1000 characters
- `role_focus`: Must be valid WorkflowRole enum value
- `steps`: Required, array of 1-50 steps
- Each step must have `step_id`, `name`, `description`, `prompt_template`
- `behavior_injection_point` defaults to `{{BEHAVIORS}}` if omitted

### Run Execution
- `template_id`: Must reference existing template
- `actor`: Required with `id`, `role`, `surface`
- `behavior_ids`: Optional, must reference valid behaviors if specified
- Run status transitions: PENDING → RUNNING → (COMPLETED | FAILED | CANCELLED)

---

## Performance Targets

**Aligned with RETRIEVAL_ENGINE_PERFORMANCE.md:**

| Metric | Target | Current |
|--------|--------|---------|
| Template Creation | < 100ms | ~50ms (SQLite) |
| Template Retrieval | < 50ms | ~20ms (SQLite) |
| Behavior Injection | < 100ms per step | ~30ms (3 behaviors) |
| Run Initialization | < 200ms | ~80ms |
| List Templates (100 items) | < 500ms | ~150ms |

**Token Savings (BCI vs. Baseline):**
- Target: 30% reduction in output tokens (per PRD)
- Measured via: `output_tokens` vs. `baseline_tokens` in `execution_update` telemetry
- Validation: Compare `execution_update` events with/without behaviors

---

## Security & Access Control

### RBAC Scopes (Future)
```
workflows.template.create   - Create new templates (STRATEGIST, ADMIN)
workflows.template.read     - View templates (ALL roles)
workflows.template.update   - Modify templates (STRATEGIST, ADMIN)
workflows.template.delete   - Delete templates (ADMIN only)
workflows.run.execute       - Start workflow runs (STRATEGIST, TEACHER, STUDENT)
workflows.run.read          - View run status (ALL roles)
```

### Audit Requirements
- All template mutations logged with actor context
- Run initiation/completion events captured
- Behavior injection tracked for compliance review
- Integration with `AUDIT_LOG_STORAGE.md` standards

---

## Open Questions

1. **Template Versioning**: Should we support multiple versions of the same template (e.g., v1.0, v1.1) with migration paths?
2. **Parallel Execution**: Should WorkflowService support concurrent step execution for MULTI_ROLE workflows?
3. **Conditional Steps**: Do we need branching logic (if/else) based on step outputs?
4. **Step Timeout**: Should individual steps have configurable timeout limits?
5. **Retry Logic**: Automatic retry for failed steps with exponential backoff?

---

## Change Log

| Date | Version | Changes | Author |
|------|---------|---------|--------|
| 2025-10-16 | 1.0.0 | Initial contract with Phase 1 SQLite implementation | Agent Engineering |
| 2025-10-16 | 1.0.0 | ✅ REST/MCP parity implementation complete: adapters, MCP tools, 17 parity tests passing | Agent Engineering |

---

## Compliance Checklist

- [x] Aligned with PRD Milestone 1 requirements
- [x] Integration with BehaviorService documented
- [x] Telemetry events defined per TELEMETRY_SCHEMA.md
- [x] CLI commands match ACTION_SERVICE_CONTRACT.md patterns
- [x] Storage approach documented (SQLite → PostgreSQL path)
- [x] Performance targets referenced from RETRIEVAL_ENGINE_PERFORMANCE.md
- [x] RBAC scope placeholders defined for future auth integration
- [x] REST API endpoints implemented (RestWorkflowServiceAdapter in amprealize/adapters.py)
- [x] MCP tools implemented (5 manifests in mcp/tools/workflow.*.json + MCPWorkflowServiceAdapter)
- [x] Parity tests passing (17 tests in tests/test_workflow_parity.py validating CLI/REST/MCP equivalence)
- [ ] PostgreSQL migration executed (Milestone 2)
- [ ] Web UI template builder (Milestone 2)
