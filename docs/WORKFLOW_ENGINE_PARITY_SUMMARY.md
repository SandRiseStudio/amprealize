# Workflow Engine Cross-Surface Parity Summary

**Date:** 2025-10-16
**Status:** ✅ Complete
**Evidence:** BUILD_TIMELINE.md #40, 35 tests passing

---

## Overview

This document summarizes the cross-surface parity implementation for the Workflow Engine, demonstrating compliance with the parity contract outlined in `contracts/MCP_SERVER_DESIGN.md` and `contracts/ACTION_SERVICE_CONTRACT.md`.

**Alignment:**
- **PRD.md**: Milestone 1 – Workflow Engine Foundation
- **contracts/MCP_SERVER_DESIGN.md**: "Every control-plane capability must achieve parity across Web, API, CLI, and MCP surfaces"
- **contracts/ACTION_SERVICE_CONTRACT.md**: "All action contracts must be reproducible via CLI, REST API, and MCP tools"
- **contracts/REPRODUCIBILITY_STRATEGY.md**: Platform actions must be recordable and replayable across all surfaces

---

## Implementation Summary

### Core Service
- **File:** `amprealize/workflow_service.py` (~600 lines)
- **Capabilities:**
  - Template CRUD (create, list, get)
  - Behavior-conditioned inference (BCI)
  - Workflow execution with status tracking
  - Token accounting and behavior citation tracking
  - Telemetry integration
- **Storage:** SQLite (`~/.amprealize/workflows.db`)
- **Tests:** 18 integration tests (all passing)

### CLI Surface
- **Commands:** 5 subcommands under `amprealize workflow`
  - `create-template` - Create workflow template from JSON
  - `list-templates` - List templates with optional filters
  - `get-template` - Retrieve template by ID
  - `run` - Execute workflow with behavior injection
  - `status` - Check run progress and token usage
- **Adapter:** `CLIWorkflowServiceAdapter` in `amprealize/adapters.py`
- **Evidence:** `amprealize/cli.py` (workflow command group), 11 CLI-specific tests passing

### REST API Surface
- **Endpoints:** 6 REST-style operations
  - `POST /v1/workflows/templates` - Create template
  - `GET /v1/workflows/templates` - List templates
  - `GET /v1/workflows/templates/:id` - Get template
  - `POST /v1/workflows/runs` - Start workflow run
  - `GET /v1/workflows/runs/:id` - Get run status
  - `PATCH /v1/workflows/runs/:id` - Update run status
- **Adapter:** `RestWorkflowServiceAdapter` in `amprealize/adapters.py`
- **Evidence:** 17 parity tests validating REST/CLI/MCP equivalence

### MCP Surface
- **Tools:** 5 MCP tool manifests
  - `workflow.template.create` - `mcp/tools/workflow.template.create.json`
  - `workflow.template.list` - `mcp/tools/workflow.template.list.json`
  - `workflow.template.get` - `mcp/tools/workflow.template.get.json`
  - `workflow.run.start` - `mcp/tools/workflow.run.start.json`
  - `workflow.run.status` - `mcp/tools/workflow.run.status.json`
- **Adapter:** `MCPWorkflowServiceAdapter` in `amprealize/adapters.py`
- **Evidence:** JSON schemas with full input/output specs, 17 parity tests passing

### Web Surface
- **Status:** Planned for Milestone 2
- **Scope:** Template builder UI, visual workflow designer, run monitoring dashboard

---

## Test Coverage

### Integration Tests (`tests/test_workflow_service.py`)
18 tests covering:
- CRUD operations (4 tests)
- Behavior injection (2 tests)
- Workflow execution (4 tests)
- CLI adapter (3 tests)
- Telemetry integration (3 tests)
- Token accounting (2 tests)

### Parity Tests (`tests/test_workflow_parity.py`)
17 tests validating cross-surface equivalence:
- **Create Template Parity** (4 tests)
  - CLI create template
  - REST create template
  - MCP create template
  - Surface parity validation (all produce consistent structure)
- **List Templates Parity** (4 tests)
  - CLI list all
  - CLI filtered by role
  - REST list with filters
  - MCP list with filters
- **Run Workflow Parity** (3 tests)
  - CLI run workflow
  - REST run workflow
  - MCP run workflow
- **Error Handling Consistency** (6 tests)
  - Get nonexistent template (CLI/REST/MCP)
  - Run nonexistent template (CLI/REST/MCP)

**Total:** 35 tests, 100% passing

---

## Parity Contract Validation

### ✅ Input Equivalence
All surfaces accept structurally equivalent inputs:
- Template creation: name, description, role_focus, steps, tags, metadata
- Template listing: role_focus filter, tags filter
- Template retrieval: template_id
- Run creation: template_id, behavior_ids, metadata, actor
- Run status: run_id

### ✅ Output Consistency
All surfaces return structurally consistent outputs:
- Template objects: template_id, name, role_focus, steps, created_at, created_by
- Run objects: run_id, template_id, status, steps, tokens_used, behaviors_cited
- List operations: arrays of template/run objects
- Error handling: consistent validation errors across surfaces

### ✅ Behavior Preservation
BCI algorithm executes identically regardless of surface:
1. Identify injection points (`{{BEHAVIORS}}`)
2. Retrieve behaviors from BehaviorService
3. Format behaviors (markdown bullet list)
4. Replace placeholder with formatted text
5. Track citations for metrics

### ✅ Telemetry Consistency
All surfaces emit identical telemetry events:
- `workflow.template.created` - Template creation
- `workflow.run.started` - Workflow execution start
- `plan_created` - Behavior citation + baseline tokens snapshot
- `execution_update` - Status + token accounting (output vs baseline)

### ✅ RBAC Scope Alignment
All surfaces enforce consistent authorization (future):
- `workflows:create_template`
- `workflows:read_template`
- `workflows:list_templates`
- `workflows:run_workflow`
- `workflows:read_run`

---

## Contract Evidence

### Service Contract
- **File:** `WORKFLOW_SERVICE_CONTRACT.md`
- **Status:** ✅ Implemented (updated from Draft)
- **Checklist:** 10/11 items complete (PostgreSQL migration pending Milestone 2)

### Capability Matrix
- **File:** `docs/capability_matrix.md`
- **Entry:** Workflow Engine (BCI) row added
- **Evidence Links:**
  - Service: `amprealize/workflow_service.py`
  - Adapters: `amprealize/adapters.py`
  - Tests: `tests/test_workflow_service.py`, `tests/test_workflow_parity.py`
  - MCP Tools: `mcp/tools/workflow.*.json`
  - Example: `examples/strategist_workflow_steps.json`
  - Timeline: `BUILD_TIMELINE.md` #40

### Progress Tracking
- **BUILD_TIMELINE.md:** Entry #40 documenting Workflow Engine delivery
- **PROGRESS_TRACKER.md:** Milestone 1 Workflow Engine marked complete
- **PRD_NEXT_STEPS.md:** Supporting Work § Workflow Engine marked ✅

---

## Adapter Patterns

All three adapters follow consistent patterns established by BehaviorService and ComplianceService:

### BaseWorkflowAdapter Pattern
```python
class BaseWorkflowAdapter:
    def __init__(self, service: WorkflowService):
        self._service = service

    def _build_actor(self, surface: str, **kwargs) -> Actor:
        """Build Actor from surface-specific inputs"""
        ...

    def create_template(self, ...):
        """Create template with surface-specific input transformation"""
        ...
```

### CLI Adapter (`CLIWorkflowServiceAdapter`)
- Takes positional/keyword arguments matching CLI flags
- Returns dict serializable to JSON/table formats
- Handles file I/O (e.g., `--steps-file`)

### REST Adapter (`RestWorkflowServiceAdapter`)
- Takes dict payloads matching REST request bodies
- Returns dict matching REST response schemas
- Includes `actor` in request payload

### MCP Adapter (`MCPWorkflowServiceAdapter`)
- Takes dict matching MCP tool inputSchema
- Returns dict matching MCP tool outputSchema
- Extracts `actor` from payload

---

## Example Workflow

### Template Creation (CLI)
```bash
amprealize workflow create-template \
  --name "Strategist Planning Flow" \
  --description "3-step workflow for request decomposition" \
  --role STRATEGIST \
  --steps-file examples/strategist_workflow_steps.json \
  --tag planning
```

### Workflow Execution (REST)
```json
POST /v1/workflows/runs
{
  "template_id": "wf-abc123",
  "behavior_ids": ["bhv-001", "bhv-002"],
  "metadata": {"request": "Build user auth system"},
  "actor": {
    "id": "strategist-agent",
    "role": "STRATEGIST",
    "surface": "REST_API"
  }
}
```

### Run Monitoring (MCP)
```json
{
  "name": "workflow.run.status",
  "arguments": {
    "run_id": "run-xyz789"
  }
}
```

All three produce structurally equivalent outputs with surface-specific metadata (e.g., `created_by.surface`).

---

## Metrics Integration

The Workflow Engine tracks metrics aligned with PRD success criteria:

### Behavior Reuse (70% target)
- `behaviors_cited` array in WorkflowRun tracks which behaviors were injected
- Aggregated via `BehaviorService.get_behavior_usage_stats()`
- Reported in dashboard analytics

### Token Savings (30% target)
- `tokens_used` field records total tokens consumed
- Compare with/without behavior injection to measure savings
- Formula: `savings = (baseline_tokens - with_behaviors_tokens) / baseline_tokens`

### Workflow Completion (80% target)
- `status` field tracks PENDING → RUNNING → COMPLETED/FAILED progression
- Success rate = completed runs / total runs
- Reported in workflow analytics

---

## Future Enhancements (Milestone 2)

### Planned Capabilities
1. **Web UI Template Builder** - Visual workflow designer with drag-drop steps
2. **PostgreSQL Migration** - Scale beyond single-user SQLite to multi-tenant PostgreSQL
3. **Conditional Steps** - Branching logic based on step outputs (if/else)
4. **Step Timeout** - Configurable timeout limits per step
5. **Retry Logic** - Automatic retry for failed steps with exponential backoff
6. **Workflow Versioning** - Track template evolution over time
7. **Step Dependencies** - Explicit dependencies between steps (DAG execution)

### Governance Requirements
- All enhancements must maintain parity across CLI/REST/MCP/Web
- Parity tests must expand to cover new capabilities
- Capability matrix must be updated with new evidence links

---

## Compliance

### Parity Contract ✅
- **Requirement:** "Every control-plane capability must achieve parity across Web, API, CLI, and MCP surfaces"
- **Evidence:** 17 parity tests passing, 3 adapters implemented, 5 MCP tool manifests, CLI command group
- **Status:** Phase 1 complete (Web UI pending Milestone 2)

### Reproducibility ✅
- **Requirement:** "Platform actions must be recordable and replayable"
- **Evidence:** All workflow operations emit telemetry, WorkflowRun stores full execution history
- **Status:** Complete

### Action Registry Integration 🚧
- **Requirement:** "Record workflow actions via `amprealize record-action`"
- **Evidence:** Telemetry events defined, action recording integration planned
- **Status:** Partial (telemetry complete, action registry linkage pending)

### Audit Trail ✅
- **Requirement:** "Immutable audit log for compliance evidence"
- **Evidence:** WorkflowRun stores actor, timestamps, behavior citations, token usage
- **Status:** Complete (WORM storage pending Milestone 2)

---

## References

- **Service Contract:** `WORKFLOW_SERVICE_CONTRACT.md`
- **Capability Matrix:** `docs/capability_matrix.md`
- **Parity Strategy:** `contracts/MCP_SERVER_DESIGN.md`
- **Action Contract:** `contracts/ACTION_SERVICE_CONTRACT.md`
- **PRD:** `PRD.md` Milestone 1 § Workflow Engine Foundation
- **Agent Workflows:** `AGENTS.md` (Strategist/Teacher/Student behaviors)
- **Timeline:** `BUILD_TIMELINE.md` #40
- **Progress:** `PROGRESS_TRACKER.md` Milestone 1
- **Tests:** `tests/test_workflow_service.py`, `tests/test_workflow_parity.py`
- **Adapters:** `amprealize/adapters.py`
- **MCP Tools:** `mcp/tools/workflow.*.json`
- **Example:** `examples/strategist_workflow_steps.json`

---

## Change Log

| Date | Change | Evidence |
|------|--------|----------|
| 2025-10-16 | Workflow Engine Phase 1 implementation | `amprealize/workflow_service.py`, 18 tests passing |
| 2025-10-16 | Cross-surface parity implementation | CLI/REST/MCP adapters, 5 MCP tools, 17 parity tests passing |
| 2025-10-16 | Governance documentation complete | Capability matrix updated, contract marked implemented |
