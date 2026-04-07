# Service Parity Audit - CLI/MCP/API Coverage

**Generated**: 2025-10-30
**Purpose**: Comprehensive inventory of all Amprealize services and their surface parity across CLI, MCP, and REST API.

## Executive Summary

This document maps every Amprealize service to its available interfaces (CLI commands, MCP tools, REST API endpoints). Gaps indicate missing integrations that break the parity contract outlined in `contracts/MCP_SERVER_DESIGN.md`.

**Status Legend:**
- ✅ **Complete** - Full implementation with tests
- 🟡 **Partial** - Implemented but missing some operations
- ❌ **Missing** - No implementation exists
- 📋 **Manifest Only** - MCP JSON exists but no server routing

---

## 1. ActionService (Reproducibility)

**Purpose**: Record, inspect, and replay build actions for reproducibility.

| Operation | CLI | MCP | REST API | Status |
|-----------|-----|-----|----------|--------|
| Create/Record Action | `amprealize record-action` | `actions.create` ✅ | `POST /v1/actions` | ✅ Complete |
| List Actions | `amprealize list-actions` | `actions.list` ✅ | `GET /v1/actions` | ✅ Complete |
| Get Action | `amprealize get-action` | `actions.get` ✅ | `GET /v1/actions/{id}` | ✅ Complete |
| Replay Actions | `amprealize replay-actions` | `actions.replay` ✅ | `POST /v1/actions:replay` | ✅ Complete |
| Replay Status | `amprealize replay-status` | `actions.replayStatus` ✅ | `GET /v1/actions/replays/{id}` | ✅ Complete |

**Backend**: PostgresActionService (~500 lines, production-ready, P95 74ms)
**Evidence**: `tests/test_mcp_action_tools.py` (6/6 passing), `tests/test_action_service_parity.py` (6/6 passing), `tests/test_cli_actions.py` (4/4 passing)
**Last Updated**: 2025-10-30 (MCP tools wired in commit 2768032)

---

## 2. BehaviorService (Behavior Handbook Management)

**Purpose**: Create, search, retrieve, and govern behavior handbook entries.

| Operation | CLI | MCP | REST API | Status |
|-----------|-----|-----|----------|--------|
| Create Behavior | `amprealize behaviors create` | `behaviors.create` 📋 | `POST /v1/behaviors` | 🟡 Partial (MCP not wired) |
| List Behaviors | `amprealize behaviors list` | `behaviors.list` 📋 | `GET /v1/behaviors` | 🟡 Partial (MCP not wired) |
| Search Behaviors | `amprealize behaviors search` | `behaviors.search` 📋 | `POST /v1/behaviors:search` | 🟡 Partial (MCP not wired) |
| Get Behavior | `amprealize behaviors get` | `behaviors.get` 📋 | `GET /v1/behaviors/{id}` | 🟡 Partial (MCP not wired) |
| Update Behavior | `amprealize behaviors update` | `behaviors.update` 📋 | `PATCH /v1/behaviors/{id}/versions/{v}` | 🟡 Partial (MCP not wired) |
| Submit Behavior | `amprealize behaviors submit` | `behaviors.submit` 📋 | `POST /v1/behaviors/{id}/versions/{v}:submit` | 🟡 Partial (MCP not wired) |
| Approve Behavior | `amprealize behaviors approve` | `behaviors.approve` 📋 | `POST /v1/behaviors/{id}:approve` | 🟡 Partial (MCP not wired) |
| Deprecate Behavior | `amprealize behaviors deprecate` | `behaviors.deprecate` 📋 | `POST /v1/behaviors/{id}:deprecate` | 🟡 Partial (MCP not wired) |
| Delete Draft | `amprealize behaviors delete-draft` | `behaviors.deleteDraft` 📋 | `DELETE /v1/behaviors/{id}/versions/{v}` | 🟡 Partial (MCP not wired) |

**Backend**: BehaviorService with PostgreSQL + vector indexing
**Adapters**: CLIBehaviorServiceAdapter, RestBehaviorServiceAdapter, MCPBehaviorServiceAdapter (exist)
**Gap**: MCP server routing NOT implemented in `mcp_server.py` (no `behaviors.*` handler block)
**Evidence**: CLI tests exist (`tests/test_cli_behaviors.py`), MCP manifests exist (`mcp/tools/behaviors.*.json`)

---

## 3. ComplianceService (Checklist Enforcement)

**Purpose**: Create, track, and validate compliance checklists with audit evidence.

| Operation | CLI | MCP | REST API | Status |
|-----------|-----|-----|----------|--------|
| Create Checklist | `amprealize compliance create-checklist` | `compliance.createChecklist` 📋 | `POST /v1/compliance/checklists` | 🟡 Partial (MCP not wired) |
| List Checklists | `amprealize compliance list` | `compliance.listChecklists` 📋 | `GET /v1/compliance/checklists` | 🟡 Partial (MCP not wired) |
| Get Checklist | `amprealize compliance get` | `compliance.getChecklist` 📋 | `GET /v1/compliance/checklists/{id}` | 🟡 Partial (MCP not wired) |
| Record Step | `amprealize compliance record-step` | `compliance.recordStep` 📋 | `POST /v1/compliance/checklists/{id}/steps` | 🟡 Partial (MCP not wired) |
| Validate Checklist | `amprealize compliance validate` | `compliance.validateChecklist` 📋 | `POST /v1/compliance/checklists/{id}:validate` | 🟡 Partial (MCP not wired) |

**Backend**: ComplianceService with append-only audit log (WORM per `contracts/AUDIT_LOG_STORAGE.md`)
**Adapters**: CLIComplianceServiceAdapter, RestComplianceServiceAdapter, MCPComplianceServiceAdapter (exist)
**Gap**: MCP server routing NOT implemented in `mcp_server.py`
**Evidence**: MCP manifests exist (`mcp/tools/compliance.*.json`)

---

## 4. WorkflowService (Workflow Templates & Execution)

**Purpose**: Define, execute, and monitor multi-step workflows.

| Operation | CLI | MCP | REST API | Status |
|-----------|-----|-----|----------|--------|
| Create Template | `amprealize workflow create-template` | `workflow.template.create` 📋 | `POST /v1/workflows/templates` | 🟡 Partial (MCP not wired) |
| List Templates | `amprealize workflow list-templates` | `workflow.template.list` 📋 | `GET /v1/workflows/templates` | 🟡 Partial (MCP not wired) |
| Get Template | `amprealize workflow get-template` | `workflow.template.get` 📋 | `GET /v1/workflows/templates/{id}` | 🟡 Partial (MCP not wired) |
| Start Run | `amprealize workflow run` | `workflow.run.start` 📋 | `POST /v1/workflows/runs` | 🟡 Partial (MCP not wired) |
| Get Run Status | `amprealize workflow status` | `workflow.run.status` 📋 | `GET /v1/workflows/runs/{id}` | 🟡 Partial (MCP not wired) |
| Update Run | ❌ Missing | ❌ Missing | `PATCH /v1/workflows/runs/{id}` | 🟡 Partial |

**Backend**: WorkflowService with behavior integration
**Adapters**: CLIWorkflowServiceAdapter, RestWorkflowServiceAdapter, MCPWorkflowServiceAdapter (exist)
**Gap**: MCP server routing NOT implemented in `mcp_server.py`
**Evidence**: MCP manifests exist (`mcp/tools/workflow.*.json`)

---

## 5. RunService (Strategist/Teacher/Student Execution)

**Purpose**: Manage agent run lifecycle, progress tracking, and telemetry.

| Operation | CLI | MCP | REST API | Status |
|-----------|-----|-----|----------|--------|
| Create Run | `amprealize run create` | `runs.create` 📋 | `POST /v1/runs` | 🟡 Partial (MCP not wired) |
| List Runs | `amprealize run list` | `runs.list` 📋 | `GET /v1/runs` | 🟡 Partial (MCP not wired) |
| Get Run | `amprealize run get` | `runs.get` 📋 | `GET /v1/runs/{id}` | 🟡 Partial (MCP not wired) |
| Update Progress | ❌ Missing | `runs.updateProgress` 📋 | `POST /v1/runs/{id}/progress` | 🟡 Partial (CLI missing) |
| Complete Run | `amprealize run complete` | `runs.complete` 📋 | `POST /v1/runs/{id}/complete` | 🟡 Partial (MCP not wired) |
| Cancel Run | `amprealize run cancel` | `runs.cancel` 📋 | `POST /v1/runs/{id}/cancel` | 🟡 Partial (MCP not wired) |
| Delete Run | ❌ Missing | ❌ Missing | `DELETE /v1/runs/{id}` | 🟡 Partial |

**Backend**: RunService (event-driven, unified execution records)
**Adapters**: CLIRunServiceAdapter, RestRunServiceAdapter, MCPRunServiceAdapter (exist)
**Gap**: MCP server routing NOT implemented in `mcp_server.py`
**Evidence**: MCP manifests exist (`mcp/tools/runs.*.json`)

---

## 6. MetricsService (Telemetry & Analytics)

**Purpose**: Collect, aggregate, and expose platform metrics for dashboards.

| Operation | CLI | MCP | REST API | Status |
|-----------|-----|-----|----------|--------|
| Get Summary | `amprealize metrics summary` | `metrics.getSummary` 📋 | `GET /v1/metrics/summary` | 🟡 Partial (MCP not wired) |
| Export Metrics | `amprealize metrics export` | `metrics.export` 📋 | `POST /v1/metrics/export` | 🟡 Partial (MCP not wired) |
| Subscribe | ❌ Missing | `metrics.subscribe` 📋 | `POST /v1/metrics/subscriptions` | 🟡 Partial (CLI missing) |
| Unsubscribe | ❌ Missing | ❌ Missing | `DELETE /v1/metrics/subscriptions/{id}` | 🟡 Partial |

**Backend**: MetricsService (streams to warehouse, caches aggregates)
**Adapters**: CLIMetricsServiceAdapter, RestMetricsServiceAdapter, MCPMetricsServiceAdapter (exist)
**Gap**: MCP server routing NOT implemented in `mcp_server.py`
**Evidence**: MCP manifests exist (`mcp/tools/metrics.*.json`)

---

## 7. AnalyticsService (KPI Projections)

**Purpose**: Project PRD success metrics (behavior reuse, token savings, compliance coverage).

| Operation | CLI | MCP | REST API | Status |
|-----------|-----|-----|----------|--------|
| Project KPI | `amprealize analytics project-kpi` | ❌ Missing | `POST /v1/analytics:projectKPI` | 🟡 Partial (MCP missing) |
| KPI Summary | `amprealize analytics kpi-summary` | `analytics.kpiSummary` 📋 | `GET /v1/analytics/kpi-summary` | 🟡 Partial (MCP not wired) |
| Behavior Usage | `amprealize analytics behavior-usage` | `analytics.behaviorUsage` 📋 | `GET /v1/analytics/behavior-usage` | 🟡 Partial (MCP not wired) |
| Token Savings | `amprealize analytics token-savings` | `analytics.tokenSavings` 📋 | `GET /v1/analytics/token-savings` | 🟡 Partial (MCP not wired) |
| Compliance Coverage | `amprealize analytics compliance-coverage` | `analytics.complianceCoverage` 📋 | `GET /v1/analytics/compliance-coverage` | 🟡 Partial (MCP not wired) |

**Backend**: TelemetryKPIProjector (processes telemetry events)
**Adapters**: No dedicated adapters (uses TelemetryKPIProjector directly in CLI/API)
**Gap**: MCP server routing NOT implemented in `mcp_server.py`, no adapter layer
**Evidence**: MCP manifests exist (`mcp/tools/analytics.*.json`)

---

## 8. BCIService (Behavior-Conditioned Inference)

**Purpose**: Retrieve behaviors, compose prompts, validate citations, compute token savings.

| Operation | CLI | MCP | REST API | Status |
|-----------|-----|-----|----------|--------|
| Retrieve Behaviors | `amprealize bci retrieve` | `bci.retrieve` 📋 | `POST /v1/bci:retrieve` | 🟡 Partial (MCP not wired) |
| Retrieve Hybrid | ❌ Missing | `bci.retrieveHybrid` 📋 | `POST /v1/bci:retrieveHybrid` | 🟡 Partial (CLI missing) |
| Rebuild Index | `amprealize bci rebuild-index` | `bci.rebuildIndex` 📋 | `POST /v1/bci:rebuildIndex` | 🟡 Partial (MCP not wired) |
| Compose Prompt | `amprealize bci compose-prompt` | `bci.composePrompt` 📋 | `POST /v1/bci:composePrompt` | 🟡 Partial (MCP not wired) |
| Compose Batch | ❌ Missing | `bci.composeBatchPrompts` 📋 | `POST /v1/bci:composeBatchPrompts` | 🟡 Partial (CLI missing) |
| Parse Citations | ❌ Missing | `bci.parseCitations` 📋 | `POST /v1/bci:parseCitations` | 🟡 Partial (CLI missing) |
| Validate Citations | `amprealize bci validate-citations` | `bci.validateCitations` 📋 | `POST /v1/bci:validateCitations` | 🟡 Partial (MCP not wired) |
| Compute Token Savings | ❌ Missing | `bci.computeTokenSavings` 📋 | `POST /v1/bci:computeTokenSavings` | 🟡 Partial (CLI missing) |
| Segment Trace | ❌ Missing | `bci.segmentTrace` 📋 | `POST /v1/bci:segmentTrace` | 🟡 Partial (CLI missing) |
| Detect Patterns | ❌ Missing | `bci.detectPatterns` 📋 | `POST /v1/bci:detectPatterns` | 🟡 Partial (CLI missing) |
| Score Reusability | ❌ Missing | `bci.scoreReusability` 📋 | `POST /v1/bci:scoreReusability` | 🟡 Partial (CLI missing) |

**Backend**: BCIService (hybrid retrieval with BGE-M3 + FAISS)
**Adapters**: No adapters (direct service calls in CLI/API)
**Gap**: MCP server routing NOT implemented, CLI missing several operations
**Evidence**: MCP manifests exist (`mcp/tools/bci.*.json`), extensive API coverage

---

## 9. ReflectionService (Behavior Extraction)

**Purpose**: Extract candidate behaviors from traces using LLM reflection.

| Operation | CLI | MCP | REST API | Status |
|-----------|-----|-----|----------|--------|
| Extract Behaviors | `amprealize reflection` | `reflection.extract` 📋 | `POST /v1/reflection:extract` | 🟡 Partial (MCP not wired) |

**Backend**: ReflectionService (trace reflection pipeline)
**Adapters**: CLIReflectionAdapter (exists), no MCP/REST adapters
**Gap**: MCP server routing NOT implemented in `mcp_server.py`
**Evidence**: MCP manifest exists (`mcp/tools/reflection.extract.json`)

---

## 10. TraceAnalysisService (Pattern Detection)

**Purpose**: Segment reasoning traces, detect patterns, score reusability.

| Operation | CLI | MCP | REST API | Status |
|-----------|-----|-----|----------|--------|
| Detect Patterns | `amprealize patterns detect` | `patterns.detectPatterns` ✅ | `POST /v1/bci:detectPatterns` | ✅ Complete |
| Score Reusability | `amprealize patterns score` | `patterns.scoreReusability` ✅ | `POST /v1/bci:scoreReusability` | ✅ Complete |

**Backend**: TraceAnalysisService (CoT parsing, pattern identification)
**Adapters**: CLITraceAnalysisServiceAdapter, MCPTraceAnalysisServiceAdapter (exist)
**MCP Routing**: ✅ Implemented (lines 354-390 in `mcp_server.py`)
**Evidence**: CLI tests exist, MCP handler wired

---

## 11. AgentAuthService (OAuth/OIDC)

**Purpose**: Broker OAuth flows, enforce policy, manage grants and consent.

| Operation | CLI | MCP | REST API | Status |
|-----------|-----|-----|----------|--------|
| Device Login | `amprealize auth login` | `auth.deviceLogin` 📋 | `POST /v1/auth/device` | 🟡 Partial (MCP not wired) |
| Refresh Token | `amprealize auth refresh` | `auth.refreshToken` 📋 | `POST /v1/auth/device/refresh` | 🟡 Partial (MCP not wired) |
| Auth Status | `amprealize auth status` | `auth.authStatus` 📋 | ❌ Missing | 🟡 Partial (API missing) |
| Logout | `amprealize auth logout` | `auth.logout` 📋 | ❌ Missing | 🟡 Partial (API missing) |
| Ensure Grant | `amprealize auth ensure-grant` | `auth.ensureGrant` 📋 | `POST /v1/auth/grants` | 🟡 Partial (MCP not wired) |
| List Grants | `amprealize auth list-grants` | `auth.listGrants` 📋 | `GET /v1/auth/grants` | 🟡 Partial (MCP not wired) |
| Policy Preview | `amprealize auth policy-preview` | `auth.policy.preview` 📋 | `POST /v1/auth/policy-preview` | 🟡 Partial (MCP not wired) |
| Revoke Grant | `amprealize auth revoke` | `auth.revoke` 📋 | `DELETE /v1/auth/grants/{id}` | 🟡 Partial (MCP not wired) |
| Consent Lookup | `amprealize auth consent lookup` | ❌ Missing | `POST /v1/auth/device/lookup` | 🟡 Partial (MCP missing) |
| Consent Approve | `amprealize auth consent approve` | ❌ Missing | `POST /v1/auth/device/approve` | 🟡 Partial (MCP missing) |
| Consent Deny | `amprealize auth consent deny` | ❌ Missing | `POST /v1/auth/device/deny` | 🟡 Partial (MCP missing) |

**Backend**: AgentAuthClient + DeviceFlowManager
**MCP Routing**: ✅ Partial (device flow handler in `mcp_server.py`, lines 322-352)
**Gap**: Grant/policy/consent operations NOT wired to MCP server, some API endpoints missing
**Evidence**: MCP manifests exist (`mcp/tools/auth.*.json`), CLI fully implemented

---

## 12. AgentOrchestratorService (Agent Assignment)

**Purpose**: Assign domain agents, switch personas, track agent effectiveness.

| Operation | CLI | MCP | REST API | Status |
|-----------|-----|-----|----------|--------|
| Assign Agent | `amprealize agents assign` | ❌ Missing | ❌ Missing | 🟡 Partial (MCP/API missing) |
| Switch Agent | `amprealize agents switch` | ❌ Missing | ❌ Missing | 🟡 Partial (MCP/API missing) |
| Agent Status | `amprealize agents status` | ❌ Missing | ❌ Missing | 🟡 Partial (MCP/API missing) |

**Backend**: AgentOrchestratorService (maps agents to Strategist → Teacher → Student)
**Adapters**: CLIAgentOrchestratorAdapter (exists), no MCP/REST adapters
**Gap**: No MCP manifests, no API endpoints, only CLI implemented
**Evidence**: CLI commands exist

---

## 13. TaskAssignmentService

**Purpose**: List task assignments for agent routing.

| Operation | CLI | MCP | REST API | Status |
|-----------|-----|-----|----------|--------|
| List Assignments | `amprealize tasks` | `tasks.listAssignments` 📋 | `POST /v1/tasks:listAssignments` | 🟡 Partial (MCP not wired) |

**Backend**: TaskAssignmentService
**Adapters**: CLITaskAssignmentAdapter (exists), no MCP adapter
**Gap**: MCP server routing NOT implemented in `mcp_server.py`
**Evidence**: MCP manifest exists (`mcp/tools/tasks.listAssignments.json`)

---

## 14. SecurityService (Secret Scanning)

**Purpose**: Scan repositories for leaked secrets using gitleaks.

| Operation | CLI | MCP | REST API | Status |
|-----------|-----|-----|----------|--------|
| Scan Secrets | `amprealize scan-secrets` | `security.scanSecrets` 📋 | ❌ Missing | 🟡 Partial (MCP not wired, API missing) |

**Backend**: Shell execution of `gitleaks detect`
**Gap**: MCP server routing NOT implemented, no API endpoint
**Evidence**: MCP manifest exists (`mcp/tools/security.scanSecrets.json`), CLI fully implemented

---

## Summary of Parity Gaps

### Critical Gaps (Block Core Workflows)

1. **BehaviorService MCP Tools** (9 tools) - Handbook operations unavailable in IDEs
2. **ComplianceService MCP Tools** (5 tools) - Checklist tracking unavailable in IDEs
3. **RunService MCP Tools** (6 tools) - Run orchestration unavailable in IDEs
4. **WorkflowService MCP Tools** (5 tools) - Workflow execution unavailable in IDEs
5. **BCIService MCP Tools** (11 tools) - BCI pipeline unavailable in IDEs

### High-Priority Gaps (Limit Adoption)

6. **MetricsService MCP Tools** (3 tools) - Analytics unavailable in IDEs
7. **AnalyticsService MCP Tools** (4 tools) - KPI projections unavailable in IDEs
8. **AgentAuthService MCP Tools** (8+ tools) - Grant/policy operations unavailable in IDEs
9. **TaskAssignmentService MCP Tool** (1 tool) - Assignment routing unavailable in IDEs

### Medium-Priority Gaps (Reduce Flexibility)

10. **BCIService CLI Commands** (7 operations) - Missing CLI for compose-batch, parse-citations, etc.
11. **RunService CLI Update Progress** - No CLI for progress updates (API/MCP have it)
12. **AgentOrchestratorService API/MCP** - Only CLI exists, no programmatic access
13. **SecurityService API Endpoint** - Secret scanning only via CLI

### Low-Priority Gaps (Edge Cases)

14. **Auth API Endpoints** - Missing status/logout REST endpoints (CLI/MCP have them)
15. **Workflow Update Run CLI** - PATCH endpoint exists but no CLI command
16. **Metrics Subscribe/Unsubscribe CLI** - API has subscriptions, CLI doesn't

---

## Recommended Implementation Order

### Phase 1: Core Service MCP Tools (P0 - Sprint 1)
1. **BehaviorService** - 9 MCP tools + server routing (~200 lines)
2. **ComplianceService** - 5 MCP tools + server routing (~150 lines)
3. **RunService** - 6 MCP tools + server routing (~180 lines)
4. **WorkflowService** - 5 MCP tools + server routing (~150 lines)

**Rationale**: These are core platform capabilities. Without MCP tools, IDE users cannot access handbook, compliance, orchestration, or workflows.

**Estimated Effort**: 3-4 days (follow `actions.*` pattern from commit 2768032)

### Phase 2: BCI & Analytics (P1 - Sprint 2)
5. **BCIService** - 11 MCP tools + server routing (~250 lines)
6. **AnalyticsService** - 4 MCP tools + server routing (~100 lines) + adapter layer
7. **MetricsService** - 3 MCP tools + server routing (~80 lines)

**Rationale**: BCI is critical for token savings (PRD success metric). Analytics surfaces PRD metrics dashboards.

**Estimated Effort**: 2-3 days

### Phase 3: Auth & Orchestration (P2 - Sprint 2)
8. **AgentAuthService** - Wire remaining auth MCP tools (grants, policy, consent) (~150 lines)
9. **TaskAssignmentService** - 1 MCP tool + server routing (~30 lines)
10. **AgentOrchestratorService** - Create API endpoints + MCP tools (~200 lines)

**Rationale**: Auth/orchestration less critical for MVP but required for multi-tenant production.

**Estimated Effort**: 2 days

### Phase 4: CLI & API Parity (P3 - Sprint 3)
11. Add missing CLI commands (BCIService batch operations, RunService progress, etc.)
12. Add missing API endpoints (AgentOrchestrator, Auth status/logout, SecurityService)
13. Create parity tests for all new integrations

**Estimated Effort**: 2-3 days

---

## Testing Strategy

For each service with new MCP tools:

1. **Create test file**: `tests/test_mcp_{service}_tools.py` (follow `test_mcp_action_tools.py` pattern)
2. **Test coverage**: All MCP tools via JSON-RPC protocol, parameter validation, error handling
3. **Parity validation**: Ensure CLI/MCP/API return equivalent results for same operations
4. **Integration tests**: Test actual service backends, not just adapters

**Success Criteria**: All tests passing, pre-commit hooks green, CI workflow succeeds.

---

## Behaviors to Apply

- `behavior_unify_execution_records` - Ensure consistent state across surfaces
- `behavior_align_storage_layers` - Validate storage adapter compatibility
- `behavior_externalize_configuration` - Keep DSNs/secrets configurable
- `behavior_curate_behavior_handbook` - Document new patterns in `AGENTS.md`
- `behavior_sanitize_action_registry` - Record all changes via `amprealize record-action`
- `behavior_wire_cli_to_orchestrator` - Map CLI commands to services
- `behavior_lock_down_security_surface` - Audit auth/CORS for new endpoints
- `behavior_update_docs_after_changes` - Update `PRD.md`, `contracts/MCP_SERVER_DESIGN.md`, `contracts/ACTION_REGISTRY_SPEC.md`

---

## Next Steps

1. **Prioritize gaps** with product/engineering stakeholders
2. **Create implementation plan** for Phase 1 (BehaviorService, ComplianceService, RunService, WorkflowService)
3. **Follow ActionService pattern** (commit 2768032) for consistent implementation
4. **Update tracking docs** (`BUILD_TIMELINE.md`, `PROGRESS_TRACKER.md`, `PRD_ALIGNMENT_LOG.md`)
5. **Record actions** via `amprealize record-action` for reproducibility

---

**Document Status**: Draft - Awaiting prioritization
**Owner**: Engineering
**Related**: `contracts/MCP_SERVER_DESIGN.md` (§4-6), `contracts/ACTION_SERVICE_CONTRACT.md`, `PRD.md` (parity requirements)
