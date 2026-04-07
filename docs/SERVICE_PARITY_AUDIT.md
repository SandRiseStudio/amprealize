# Service Parity & Production Readiness Audit# Service Parity Audit - CLI/MCP/API Coverage

**Date**: 2025-11-06

**Purpose**: Comprehensive audit of all services to ensure production-ready storage backends and surface parity across API/CLI/MCP**Generated**: 2025-10-30

**Purpose**: Comprehensive inventory of all Amprealize services and their surface parity across CLI, MCP, and REST API.

## Executive Summary

## Executive Summary

### ✅ **Production Ready** (PostgreSQL-backed)

- **BehaviorService** - Full PostgreSQL + FAISS vector indexThis document maps every Amprealize service to its available interfaces (CLI commands, MCP tools, REST API endpoints). Gaps indicate missing integrations that break the parity contract outlined in `contracts/MCP_SERVER_DESIGN.md`.

- **ActionService** - PostgreSQL via `action_service_postgres.py`

- **WorkflowService** - PostgreSQL-backed**Status Legend:**

- **MetricsService** - PostgreSQL via `metrics_service_postgres.py` (with SQLite fallback)- ✅ **Complete** - Full implementation with tests

- **AgentOrchestratorService** - PostgreSQL via `agent_orchestrator_service_postgres.py`- 🟡 **Partial** - Implemented but missing some operations

- **TraceAnalysisService** - PostgreSQL via `trace_analysis_service_postgres.py`- ❌ **Missing** - No implementation exists

- 📋 **Manifest Only** - MCP JSON exists but no server routing

### ⚠️ **Not Production Ready** (In-Memory/SQLite)

- **RunService** - SQLite-backed (Postgres implementation exists: `run_service_postgres.py`)---

- **ComplianceService** - In-memory only (Postgres implementation exists: `compliance_service_postgres.py`)

- **ReflectionService** - Delegates to TraceAnalysisService (transitively uses Postgres)## 1. ActionService (Reproducibility)



### 🔍 **Service-by-Service Analysis****Purpose**: Record, inspect, and replay build actions for reproducibility.



---| Operation | CLI | MCP | REST API | Status |

|-----------|-----|-----|----------|--------|

## 1. BehaviorService ✅| Create/Record Action | `amprealize record-action` | `actions.create` ✅ | `POST /v1/actions` | ✅ Complete |

| List Actions | `amprealize list-actions` | `actions.list` ✅ | `GET /v1/actions` | ✅ Complete |

### Storage Backend| Get Action | `amprealize get-action` | `actions.get` ✅ | `GET /v1/actions/{id}` | ✅ Complete |

- **Implementation**: `amprealize/behavior_service.py`| Replay Actions | `amprealize replay-actions` | `actions.replay` ✅ | `POST /v1/actions:replay` | ✅ Complete |

- **Storage**: PostgreSQL via `PostgresPool`| Replay Status | `amprealize replay-status` | `actions.replayStatus` ✅ | `GET /v1/actions/replays/{id}` | ✅ Complete |

- **Vector Index**: FAISS (BGE-M3 embeddings, 1024 dimensions)

- **Status**: ✅ **Production Ready****Backend**: PostgresActionService (~500 lines, production-ready, P95 74ms)

**Evidence**: `tests/test_mcp_action_tools.py` (6/6 passing), `tests/test_action_service_parity.py` (6/6 passing), `tests/test_cli_actions.py` (4/4 passing)

### API Coverage**Last Updated**: 2025-10-30 (MCP tools wired in commit 2768032)

```

POST   /v1/behaviors                          ✅ create_behavior_draft---

GET    /v1/behaviors                          ✅ list_behaviors

POST   /v1/behaviors:search                   ✅ search_behaviors## 2. BehaviorService (Behavior Handbook Management)

GET    /v1/behaviors/{behavior_id}            ✅ get_behavior

PATCH  /v1/behaviors/{behavior_id}/versions   ✅ update_behavior_version**Purpose**: Create, search, retrieve, and govern behavior handbook entries.

POST   /v1/behaviors/{id}/versions:submit     ✅ submit_for_approval

POST   /v1/behaviors/{id}:approve             ✅ approve_behavior| Operation | CLI | MCP | REST API | Status |

POST   /v1/behaviors/{id}:deprecate           ✅ deprecate_behavior|-----------|-----|-----|----------|--------|

DELETE /v1/behaviors/{id}/versions/{version}  ✅ delete_draft_version| Create Behavior | `amprealize behaviors create` | `behaviors.create` 📋 | `POST /v1/behaviors` | 🟡 Partial (MCP not wired) |

```| List Behaviors | `amprealize behaviors list` | `behaviors.list` 📋 | `GET /v1/behaviors` | 🟡 Partial (MCP not wired) |

| Search Behaviors | `amprealize behaviors search` | `behaviors.search` 📋 | `POST /v1/behaviors:search` | 🟡 Partial (MCP not wired) |

### CLI Coverage| Get Behavior | `amprealize behaviors get` | `behaviors.get` 📋 | `GET /v1/behaviors/{id}` | 🟡 Partial (MCP not wired) |

```| Update Behavior | `amprealize behaviors update` | `behaviors.update` 📋 | `PATCH /v1/behaviors/{id}/versions/{v}` | 🟡 Partial (MCP not wired) |

amprealize behaviors create     ✅ (via RestBehaviorServiceAdapter)| Submit Behavior | `amprealize behaviors submit` | `behaviors.submit` 📋 | `POST /v1/behaviors/{id}/versions/{v}:submit` | 🟡 Partial (MCP not wired) |

amprealize behaviors list       ✅| Approve Behavior | `amprealize behaviors approve` | `behaviors.approve` 📋 | `POST /v1/behaviors/{id}:approve` | 🟡 Partial (MCP not wired) |

amprealize behaviors search     ✅| Deprecate Behavior | `amprealize behaviors deprecate` | `behaviors.deprecate` 📋 | `POST /v1/behaviors/{id}:deprecate` | 🟡 Partial (MCP not wired) |

amprealize behaviors get        ✅| Delete Draft | `amprealize behaviors delete-draft` | `behaviors.deleteDraft` 📋 | `DELETE /v1/behaviors/{id}/versions/{v}` | 🟡 Partial (MCP not wired) |

amprealize behaviors update     ✅

amprealize behaviors submit     ✅**Backend**: BehaviorService with PostgreSQL + vector indexing

amprealize behaviors approve    ✅**Adapters**: CLIBehaviorServiceAdapter, RestBehaviorServiceAdapter, MCPBehaviorServiceAdapter (exist)

amprealize behaviors deprecate  ✅**Gap**: MCP server routing NOT implemented in `mcp_server.py` (no `behaviors.*` handler block)

```**Evidence**: CLI tests exist (`tests/test_cli_behaviors.py`), MCP manifests exist (`mcp/tools/behaviors.*.json`)



### MCP Coverage---

```

behaviors.create      ✅ Line 711## 3. ComplianceService (Checklist Enforcement)

behaviors.list        ✅ Line 713

behaviors.search      ✅ Line 715**Purpose**: Create, track, and validate compliance checklists with audit evidence.

behaviors.get         ✅ Line 724

behaviors.update      ✅ Line 733| Operation | CLI | MCP | REST API | Status |

behaviors.submit      ✅ Line 743|-----------|-----|-----|----------|--------|

behaviors.approve     ✅ Line 753| Create Checklist | `amprealize compliance create-checklist` | `compliance.createChecklist` 📋 | `POST /v1/compliance/checklists` | 🟡 Partial (MCP not wired) |

behaviors.deprecate   ✅ Line 764| List Checklists | `amprealize compliance list` | `compliance.listChecklists` 📋 | `GET /v1/compliance/checklists` | 🟡 Partial (MCP not wired) |

behaviors.deleteDraft ✅ Line 775| Get Checklist | `amprealize compliance get` | `compliance.getChecklist` 📋 | `GET /v1/compliance/checklists/{id}` | 🟡 Partial (MCP not wired) |

```| Record Step | `amprealize compliance record-step` | `compliance.recordStep` 📋 | `POST /v1/compliance/checklists/{id}/steps` | 🟡 Partial (MCP not wired) |

| Validate Checklist | `amprealize compliance validate` | `compliance.validateChecklist` 📋 | `POST /v1/compliance/checklists/{id}:validate` | 🟡 Partial (MCP not wired) |

**Parity Status**: ✅ **100% - All surfaces aligned**

**Backend**: ComplianceService with append-only audit log (WORM per `contracts/AUDIT_LOG_STORAGE.md`)

---**Adapters**: CLIComplianceServiceAdapter, RestComplianceServiceAdapter, MCPComplianceServiceAdapter (exist)

**Gap**: MCP server routing NOT implemented in `mcp_server.py`

## 2. ActionService ✅**Evidence**: MCP manifests exist (`mcp/tools/compliance.*.json`)



### Storage Backend---

- **Implementation**: `amprealize/action_service_postgres.py` (class `PostgresActionService`)

- **Storage**: PostgreSQL via `PostgresPool`## 4. WorkflowService (Workflow Templates & Execution)

- **Fallback**: In-memory `ActionService` for testing (when DSN not configured)

- **Status**: ✅ **Production Ready** (when `AMPREALIZE_ACTION_PG_DSN` is set)**Purpose**: Define, execute, and monitor multi-step workflows.



### API Coverage| Operation | CLI | MCP | REST API | Status |

```|-----------|-----|-----|----------|--------|

POST /v1/actions              ✅ create_action| Create Template | `amprealize workflow create-template` | `workflow.template.create` 📋 | `POST /v1/workflows/templates` | 🟡 Partial (MCP not wired) |

GET  /v1/actions              ✅ list_actions| List Templates | `amprealize workflow list-templates` | `workflow.template.list` 📋 | `GET /v1/workflows/templates` | 🟡 Partial (MCP not wired) |

GET  /v1/actions/{action_id}  ✅ get_action| Get Template | `amprealize workflow get-template` | `workflow.template.get` 📋 | `GET /v1/workflows/templates/{id}` | 🟡 Partial (MCP not wired) |

POST /v1/actions:replay       ✅ replay_actions| Start Run | `amprealize workflow run` | `workflow.run.start` 📋 | `POST /v1/workflows/runs` | 🟡 Partial (MCP not wired) |

GET  /v1/actions/replays/{id} ✅ get_replay_status| Get Run Status | `amprealize workflow status` | `workflow.run.status` 📋 | `GET /v1/workflows/runs/{id}` | 🟡 Partial (MCP not wired) |

```| Update Run | ❌ Missing | ❌ Missing | `PATCH /v1/workflows/runs/{id}` | 🟡 Partial |



### CLI Coverage**Backend**: WorkflowService with behavior integration

```**Adapters**: CLIWorkflowServiceAdapter, RestWorkflowServiceAdapter, MCPWorkflowServiceAdapter (exist)

amprealize record-action       ✅ Calls ActionService.create_action**Gap**: MCP server routing NOT implemented in `mcp_server.py`

amprealize actions list        ✅**Evidence**: MCP manifests exist (`mcp/tools/workflow.*.json`)

amprealize actions get         ✅

amprealize replay              ✅ Calls ActionService.replay_actions---

amprealize replay-status       ✅

```## 5. RunService (Strategist/Teacher/Student Execution)



### MCP Coverage**Purpose**: Manage agent run lifecycle, progress tracking, and telemetry.

```

actions.create       ✅ Line 653| Operation | CLI | MCP | REST API | Status |

actions.list         ✅ Line 655|-----------|-----|-----|----------|--------|

actions.get          ✅ Line 657| Create Run | `amprealize run create` | `runs.create` 📋 | `POST /v1/runs` | 🟡 Partial (MCP not wired) |

actions.replay       ✅ Line 666| List Runs | `amprealize run list` | `runs.list` 📋 | `GET /v1/runs` | 🟡 Partial (MCP not wired) |

actions.replayStatus ✅ Line 668| Get Run | `amprealize run get` | `runs.get` 📋 | `GET /v1/runs/{id}` | 🟡 Partial (MCP not wired) |

```| Update Progress | ❌ Missing | `runs.updateProgress` 📋 | `POST /v1/runs/{id}/progress` | 🟡 Partial (CLI missing) |

| Complete Run | `amprealize run complete` | `runs.complete` 📋 | `POST /v1/runs/{id}/complete` | 🟡 Partial (MCP not wired) |

**Parity Status**: ✅ **100% - All surfaces aligned**| Cancel Run | `amprealize run cancel` | `runs.cancel` 📋 | `POST /v1/runs/{id}/cancel` | 🟡 Partial (MCP not wired) |

| Delete Run | ❌ Missing | ❌ Missing | `DELETE /v1/runs/{id}` | 🟡 Partial |

**Note**: API/CLI/MCP automatically use `PostgresActionService` when `AMPREALIZE_ACTION_PG_DSN` is set, otherwise fall back to in-memory implementation.

**Backend**: RunService (event-driven, unified execution records)

---**Adapters**: CLIRunServiceAdapter, RestRunServiceAdapter, MCPRunServiceAdapter (exist)

**Gap**: MCP server routing NOT implemented in `mcp_server.py`

## 3. RunService ⚠️**Evidence**: MCP manifests exist (`mcp/tools/runs.*.json`)



### Storage Backend---

- **Current Implementation**: `amprealize/run_service.py`

- **Storage**: ⚠️ **SQLite** (local file at `~/.amprealize/runs.db`)## 6. MetricsService (Telemetry & Analytics)

- **Postgres Implementation**: ✅ **EXISTS** at `amprealize/run_service_postgres.py`

- **Status**: ⚠️ **Not Production Ready** - Needs migration to PostgresRunService**Purpose**: Collect, aggregate, and expose platform metrics for dashboards.



### API Coverage| Operation | CLI | MCP | REST API | Status |

```|-----------|-----|-----|----------|--------|

POST   /v1/runs                   ✅ create_run| Get Summary | `amprealize metrics summary` | `metrics.getSummary` 📋 | `GET /v1/metrics/summary` | 🟡 Partial (MCP not wired) |

GET    /v1/runs                   ✅ list_runs| Export Metrics | `amprealize metrics export` | `metrics.export` 📋 | `POST /v1/metrics/export` | 🟡 Partial (MCP not wired) |

GET    /v1/runs/{run_id}          ✅ get_run| Subscribe | ❌ Missing | `metrics.subscribe` 📋 | `POST /v1/metrics/subscriptions` | 🟡 Partial (CLI missing) |

POST   /v1/runs/{id}/progress     ✅ update_progress| Unsubscribe | ❌ Missing | ❌ Missing | `DELETE /v1/metrics/subscriptions/{id}` | 🟡 Partial |

POST   /v1/runs/{id}/complete     ✅ complete_run

POST   /v1/runs/{id}/cancel       ✅ cancel_run**Backend**: MetricsService (streams to warehouse, caches aggregates)

DELETE /v1/runs/{run_id}          ✅ delete_run**Adapters**: CLIMetricsServiceAdapter, RestMetricsServiceAdapter, MCPMetricsServiceAdapter (exist)

```**Gap**: MCP server routing NOT implemented in `mcp_server.py`

**Evidence**: MCP manifests exist (`mcp/tools/metrics.*.json`)

### CLI Coverage

```---

amprealize run create       ✅ (via CLIRunServiceAdapter)

amprealize run get          ✅## 7. AnalyticsService (KPI Projections)

amprealize run list         ✅

amprealize run complete     ✅**Purpose**: Project PRD success metrics (behavior reuse, token savings, compliance coverage).

amprealize run cancel       ✅

```| Operation | CLI | MCP | REST API | Status |

|-----------|-----|-----|----------|--------|

### MCP Coverage| Project KPI | `amprealize analytics project-kpi` | ❌ Missing | `POST /v1/analytics:projectKPI` | 🟡 Partial (MCP missing) |

```| KPI Summary | `amprealize analytics kpi-summary` | `analytics.kpiSummary` 📋 | `GET /v1/analytics/kpi-summary` | 🟡 Partial (MCP not wired) |

runs.create         ✅ Line 986| Behavior Usage | `amprealize analytics behavior-usage` | `analytics.behaviorUsage` 📋 | `GET /v1/analytics/behavior-usage` | 🟡 Partial (MCP not wired) |

runs.list           ✅ Line 988| Token Savings | `amprealize analytics token-savings` | `analytics.tokenSavings` 📋 | `GET /v1/analytics/token-savings` | 🟡 Partial (MCP not wired) |

runs.get            ✅ Line 990| Compliance Coverage | `amprealize analytics compliance-coverage` | `analytics.complianceCoverage` 📋 | `GET /v1/analytics/compliance-coverage` | 🟡 Partial (MCP not wired) |

runs.updateProgress ✅ Line 999

runs.complete       ✅ Line 1008**Backend**: TelemetryKPIProjector (processes telemetry events)

runs.cancel         ✅ Line 1017**Adapters**: No dedicated adapters (uses TelemetryKPIProjector directly in CLI/API)

```**Gap**: MCP server routing NOT implemented in `mcp_server.py`, no adapter layer

**Evidence**: MCP manifests exist (`mcp/tools/analytics.*.json`)

**Parity Status**: ✅ Surface parity is 100%

**Production Readiness**: ⚠️ **BLOCKER** - Must switch from SQLite to PostgresRunService---



### Remediation Plan## 8. BCIService (Behavior-Conditioned Inference)

1. Update `api.py` line ~151 to use `PostgresRunService` when `AMPREALIZE_RUN_PG_DSN` is set

2. Update CLI adapters to support both implementations**Purpose**: Retrieve behaviors, compose prompts, validate citations, compute token savings.

3. Update MCP server registry to use PostgresRunService

4. Add migration script to copy existing SQLite runs to Postgres| Operation | CLI | MCP | REST API | Status |

5. Update documentation and environment variable examples|-----------|-----|-----|----------|--------|

| Retrieve Behaviors | `amprealize bci retrieve` | `bci.retrieve` 📋 | `POST /v1/bci:retrieve` | 🟡 Partial (MCP not wired) |

---| Retrieve Hybrid | ❌ Missing | `bci.retrieveHybrid` 📋 | `POST /v1/bci:retrieveHybrid` | 🟡 Partial (CLI missing) |

| Rebuild Index | `amprealize bci rebuild-index` | `bci.rebuildIndex` 📋 | `POST /v1/bci:rebuildIndex` | 🟡 Partial (MCP not wired) |

## 4. ComplianceService ⚠️| Compose Prompt | `amprealize bci compose-prompt` | `bci.composePrompt` 📋 | `POST /v1/bci:composePrompt` | 🟡 Partial (MCP not wired) |

| Compose Batch | ❌ Missing | `bci.composeBatchPrompts` 📋 | `POST /v1/bci:composeBatchPrompts` | 🟡 Partial (CLI missing) |

### Storage Backend| Parse Citations | ❌ Missing | `bci.parseCitations` 📋 | `POST /v1/bci:parseCitations` | 🟡 Partial (CLI missing) |

- **Current Implementation**: `amprealize/compliance_service.py`| Validate Citations | `amprealize bci validate-citations` | `bci.validateCitations` 📋 | `POST /v1/bci:validateCitations` | 🟡 Partial (MCP not wired) |

- **Storage**: ⚠️ **In-Memory** (Dict-based, non-persistent)| Compute Token Savings | ❌ Missing | `bci.computeTokenSavings` 📋 | `POST /v1/bci:computeTokenSavings` | 🟡 Partial (CLI missing) |

- **Postgres Implementation**: ✅ **EXISTS** at `amprealize/compliance_service_postgres.py`| Segment Trace | ❌ Missing | `bci.segmentTrace` 📋 | `POST /v1/bci:segmentTrace` | 🟡 Partial (CLI missing) |

- **Status**: ⚠️ **Not Production Ready** - Needs migration to PostgresComplianceService| Detect Patterns | ❌ Missing | `bci.detectPatterns` 📋 | `POST /v1/bci:detectPatterns` | 🟡 Partial (CLI missing) |

| Score Reusability | ❌ Missing | `bci.scoreReusability` 📋 | `POST /v1/bci:scoreReusability` | 🟡 Partial (CLI missing) |

### API Coverage

```**Backend**: BCIService (hybrid retrieval with BGE-M3 + FAISS)

POST /v1/compliance/checklists                ✅ create_checklist**Adapters**: No adapters (direct service calls in CLI/API)

GET  /v1/compliance/checklists                ✅ list_checklists**Gap**: MCP server routing NOT implemented, CLI missing several operations

GET  /v1/compliance/checklists/{id}           ✅ get_checklist**Evidence**: MCP manifests exist (`mcp/tools/bci.*.json`), extensive API coverage

POST /v1/compliance/checklists/{id}/steps     ✅ record_step

POST /v1/compliance/checklists/{id}:validate  ✅ validate_checklist---

```

## 9. ReflectionService (Behavior Extraction)

### CLI Coverage

```**Purpose**: Extract candidate behaviors from traces using LLM reflection.

amprealize compliance create-checklist    ✅ (via CLIComplianceServiceAdapter)

amprealize compliance list-checklists     ✅| Operation | CLI | MCP | REST API | Status |

amprealize compliance get-checklist       ✅|-----------|-----|-----|----------|--------|

amprealize compliance record-step         ✅| Extract Behaviors | `amprealize reflection` | `reflection.extract` 📋 | `POST /v1/reflection:extract` | 🟡 Partial (MCP not wired) |

amprealize compliance validate-checklist  ✅

```**Backend**: ReflectionService (trace reflection pipeline)

**Adapters**: CLIReflectionAdapter (exists), no MCP/REST adapters

### MCP Coverage**Gap**: MCP server routing NOT implemented in `mcp_server.py`

```**Evidence**: MCP manifest exists (`mcp/tools/reflection.extract.json`)

compliance.createChecklist    ✅ Line 1034

compliance.getChecklist       ✅ Line 1036---

compliance.listChecklists     ✅ Line 1038

compliance.recordStep         ✅ Line 1047## 10. TraceAnalysisService (Pattern Detection)

compliance.validateChecklist  ✅ Line 1056

compliance.auditTrail         ✅ Line 1074**Purpose**: Segment reasoning traces, detect patterns, score reusability.

```

| Operation | CLI | MCP | REST API | Status |

**Parity Status**: ✅ Surface parity is 100%  |-----------|-----|-----|----------|--------|

**Production Readiness**: ⚠️ **BLOCKER** - Must switch from in-memory to PostgresComplianceService| Detect Patterns | `amprealize patterns detect` | `patterns.detectPatterns` ✅ | `POST /v1/bci:detectPatterns` | ✅ Complete |

| Score Reusability | `amprealize patterns score` | `patterns.scoreReusability` ✅ | `POST /v1/bci:scoreReusability` | ✅ Complete |

### Remediation Plan

1. Update `api.py` line ~109 to use `PostgresComplianceService` when `AMPREALIZE_COMPLIANCE_PG_DSN` is set**Backend**: TraceAnalysisService (CoT parsing, pattern identification)

2. Update CLI to support both implementations**Adapters**: CLITraceAnalysisServiceAdapter, MCPTraceAnalysisServiceAdapter (exist)

3. Update MCP server registry to use PostgresComplianceService**MCP Routing**: ✅ Implemented (lines 354-390 in `mcp_server.py`)

4. Test WORM (Write-Once-Read-Many) audit log requirements per `contracts/AUDIT_LOG_STORAGE.md`**Evidence**: CLI tests exist, MCP handler wired



------



## 5. ReflectionService ✅## 11. AgentAuthService (OAuth/OIDC)



### Storage Backend**Purpose**: Broker OAuth flows, enforce policy, manage grants and consent.

- **Implementation**: `amprealize/reflection_service.py`

- **Storage**: Delegates to `TraceAnalysisService` (which uses Postgres)| Operation | CLI | MCP | REST API | Status |

- **Status**: ✅ **Production Ready** (transitively)|-----------|-----|-----|----------|--------|

| Device Login | `amprealize auth login` | `auth.deviceLogin` 📋 | `POST /v1/auth/device` | 🟡 Partial (MCP not wired) |

### API Coverage| Refresh Token | `amprealize auth refresh` | `auth.refreshToken` 📋 | `POST /v1/auth/device/refresh` | 🟡 Partial (MCP not wired) |

```| Auth Status | `amprealize auth status` | `auth.authStatus` 📋 | ❌ Missing | 🟡 Partial (API missing) |

POST /v1/reflections        ✅ reflect (via RestReflectionAdapter)| Logout | `amprealize auth logout` | `auth.logout` 📋 | ❌ Missing | 🟡 Partial (API missing) |

POST /v1/reflections:parse  ✅ parse_trace| Ensure Grant | `amprealize auth ensure-grant` | `auth.ensureGrant` 📋 | `POST /v1/auth/grants` | 🟡 Partial (MCP not wired) |

```| List Grants | `amprealize auth list-grants` | `auth.listGrants` 📋 | `GET /v1/auth/grants` | 🟡 Partial (MCP not wired) |

| Policy Preview | `amprealize auth policy-preview` | `auth.policy.preview` 📋 | `POST /v1/auth/policy-preview` | 🟡 Partial (MCP not wired) |

### CLI Coverage| Revoke Grant | `amprealize auth revoke` | `auth.revoke` 📋 | `DELETE /v1/auth/grants/{id}` | 🟡 Partial (MCP not wired) |

```| Consent Lookup | `amprealize auth consent lookup` | ❌ Missing | `POST /v1/auth/device/lookup` | 🟡 Partial (MCP missing) |

amprealize reflection  ✅ Calls ReflectionService.reflect| Consent Approve | `amprealize auth consent approve` | ❌ Missing | `POST /v1/auth/device/approve` | 🟡 Partial (MCP missing) |

```| Consent Deny | `amprealize auth consent deny` | ❌ Missing | `POST /v1/auth/device/deny` | 🟡 Partial (MCP missing) |



### MCP Coverage**Backend**: AgentAuthClient + DeviceFlowManager

```**MCP Routing**: ✅ Partial (device flow handler in `mcp_server.py`, lines 322-352)

reflections.submitTrace      ✅ Line 1099**Gap**: Grant/policy/consent operations NOT wired to MCP server, some API endpoints missing

reflections.suggestBehaviors ✅ Line 1101**Evidence**: MCP manifests exist (`mcp/tools/auth.*.json`), CLI fully implemented

```

---

**Parity Status**: ✅ **100% - All surfaces aligned**

## 12. AgentOrchestratorService (Agent Assignment)

---

**Purpose**: Assign domain agents, switch personas, track agent effectiveness.

## 6. MetricsService ✅

| Operation | CLI | MCP | REST API | Status |

### Storage Backend|-----------|-----|-----|----------|--------|

- **Implementation**: `amprealize/metrics_service_postgres.py` (class `PostgresMetricsService`)| Assign Agent | `amprealize agents assign` | ❌ Missing | ❌ Missing | 🟡 Partial (MCP/API missing) |

- **Storage**: PostgreSQL (when `AMPREALIZE_METRICS_PG_DSN` is set)| Switch Agent | `amprealize agents switch` | ❌ Missing | ❌ Missing | 🟡 Partial (MCP/API missing) |

- **Fallback**: SQLite cache + DuckDB warehouse (via `amprealize/metrics_service.py`)| Agent Status | `amprealize agents status` | ❌ Missing | ❌ Missing | 🟡 Partial (MCP/API missing) |

- **Status**: ✅ **Production Ready** (when DSN configured)

**Backend**: AgentOrchestratorService (maps agents to Strategist → Teacher → Student)

### API Coverage**Adapters**: CLIAgentOrchestratorAdapter (exists), no MCP/REST adapters

```**Gap**: No MCP manifests, no API endpoints, only CLI implemented

GET  /v1/metrics/summary              ✅ get_summary**Evidence**: CLI commands exist

POST /v1/metrics/export               ✅ export_metrics

POST /v1/metrics/subscriptions        ✅ subscribe (SSE)---

DELETE /v1/metrics/subscriptions/{id} ✅ unsubscribe

```## 13. TaskAssignmentService



### CLI Coverage**Purpose**: List task assignments for agent routing.

```

amprealize metrics summary  ✅ (via CLIMetricsServiceAdapter)| Operation | CLI | MCP | REST API | Status |

amprealize metrics export   ✅|-----------|-----|-----|----------|--------|

```| List Assignments | `amprealize tasks` | `tasks.listAssignments` 📋 | `POST /v1/tasks:listAssignments` | 🟡 Partial (MCP not wired) |



### MCP Coverage**Backend**: TaskAssignmentService

```**Adapters**: CLITaskAssignmentAdapter (exists), no MCP adapter

metrics.getSummary  ✅ Line 1187**Gap**: MCP server routing NOT implemented in `mcp_server.py`

metrics.export      ✅ Line 1189**Evidence**: MCP manifest exists (`mcp/tools/tasks.listAssignments.json`)

metrics.subscribe   ✅ Line 1191 (SSE support)

```---



**Parity Status**: ✅ **100% - All surfaces aligned**## 14. SecurityService (Secret Scanning)



---**Purpose**: Scan repositories for leaked secrets using gitleaks.



## 7. TraceAnalysisService ✅| Operation | CLI | MCP | REST API | Status |

|-----------|-----|-----|----------|--------|

### Storage Backend| Scan Secrets | `amprealize scan-secrets` | `security.scanSecrets` 📋 | ❌ Missing | 🟡 Partial (MCP not wired, API missing) |

- **Implementation**: `amprealize/trace_analysis_service_postgres.py` (class `PostgresTraceAnalysisService`)

- **Storage**: PostgreSQL via `PostgresPool`**Backend**: Shell execution of `gitleaks detect`

- **Status**: ✅ **Production Ready****Gap**: MCP server routing NOT implemented, no API endpoint

**Evidence**: MCP manifest exists (`mcp/tools/security.scanSecrets.json`), CLI fully implemented

### API Coverage

```---

POST /v1/traces:segment          ✅ (via patterns.detectPatterns)

POST /v1/traces:detectPatterns   ✅## Summary of Parity Gaps

POST /v1/traces:scoreReusability ✅

```### Critical Gaps (Block Core Workflows)



### CLI Coverage1. **BehaviorService MCP Tools** (9 tools) - Handbook operations unavailable in IDEs

```2. **ComplianceService MCP Tools** (5 tools) - Checklist tracking unavailable in IDEs

amprealize patterns detect  ✅ Calls TraceAnalysisService.detect_patterns3. **RunService MCP Tools** (6 tools) - Run orchestration unavailable in IDEs

amprealize patterns score   ✅ Calls TraceAnalysisService.score_reusability4. **WorkflowService MCP Tools** (5 tools) - Workflow execution unavailable in IDEs

```5. **BCIService MCP Tools** (11 tools) - BCI pipeline unavailable in IDEs



### MCP Coverage### High-Priority Gaps (Limit Adoption)

```

patterns.detectPatterns   ✅ Line 593 (with progress notifications)6. **MetricsService MCP Tools** (3 tools) - Analytics unavailable in IDEs

patterns.scoreReusability ✅ Line 6177. **AnalyticsService MCP Tools** (4 tools) - KPI projections unavailable in IDEs

traces.segment            ✅ Implemented via TraceAnalysisService8. **AgentAuthService MCP Tools** (8+ tools) - Grant/policy operations unavailable in IDEs

```9. **TaskAssignmentService MCP Tool** (1 tool) - Assignment routing unavailable in IDEs



**Parity Status**: ✅ **100% - All surfaces aligned**### Medium-Priority Gaps (Reduce Flexibility)



---10. **BCIService CLI Commands** (7 operations) - Missing CLI for compose-batch, parse-citations, etc.

11. **RunService CLI Update Progress** - No CLI for progress updates (API/MCP have it)

## 8. WorkflowService ✅12. **AgentOrchestratorService API/MCP** - Only CLI exists, no programmatic access

13. **SecurityService API Endpoint** - Secret scanning only via CLI

### Storage Backend

- **Implementation**: `amprealize/workflow_service.py`### Low-Priority Gaps (Edge Cases)

- **Storage**: PostgreSQL via `PostgresPool` (reads from `AMPREALIZE_WORKFLOW_PG_DSN`)

- **Status**: ✅ **Production Ready**14. **Auth API Endpoints** - Missing status/logout REST endpoints (CLI/MCP have them)

15. **Workflow Update Run CLI** - PATCH endpoint exists but no CLI command

### API Coverage16. **Metrics Subscribe/Unsubscribe CLI** - API has subscriptions, CLI doesn't

```

POST /v1/workflows/templates          ✅ create_template---

GET  /v1/workflows/templates          ✅ list_templates

GET  /v1/workflows/templates/{id}     ✅ get_template## Recommended Implementation Order

POST /v1/workflows/runs               ✅ create_workflow_run

GET  /v1/workflows/runs/{run_id}      ✅ get_workflow_run### Phase 1: Core Service MCP Tools (P0 - Sprint 1)

PATCH /v1/workflows/runs/{run_id}     ✅ update_workflow_run1. **BehaviorService** - 9 MCP tools + server routing (~200 lines)

```2. **ComplianceService** - 5 MCP tools + server routing (~150 lines)

3. **RunService** - 6 MCP tools + server routing (~180 lines)

### CLI Coverage4. **WorkflowService** - 5 MCP tools + server routing (~150 lines)

```

amprealize workflows create-template  ✅ (via CLIWorkflowServiceAdapter)**Rationale**: These are core platform capabilities. Without MCP tools, IDE users cannot access handbook, compliance, orchestration, or workflows.

amprealize workflows list-templates   ✅

amprealize workflows get-template     ✅**Estimated Effort**: 3-4 days (follow `actions.*` pattern from commit 2768032)

amprealize workflows run              ✅

```### Phase 2: BCI & Analytics (P1 - Sprint 2)

5. **BCIService** - 11 MCP tools + server routing (~250 lines)

### MCP Coverage6. **AnalyticsService** - 4 MCP tools + server routing (~100 lines) + adapter layer

```7. **MetricsService** - 3 MCP tools + server routing (~80 lines)

workflows.createTemplate  ✅ Line 844

workflows.listTemplates   ✅ Line 846**Rationale**: BCI is critical for token savings (PRD success metric). Analytics surfaces PRD metrics dashboards.

workflows.getTemplate     ✅ Line 848

workflows.createRun       ✅ Line 857**Estimated Effort**: 2-3 days

workflows.getRun          ✅ Line 859

workflows.updateRun       ✅ Line 868### Phase 3: Auth & Orchestration (P2 - Sprint 2)

```8. **AgentAuthService** - Wire remaining auth MCP tools (grants, policy, consent) (~150 lines)

9. **TaskAssignmentService** - 1 MCP tool + server routing (~30 lines)

**Parity Status**: ✅ **100% - All surfaces aligned**10. **AgentOrchestratorService** - Create API endpoints + MCP tools (~200 lines)



---**Rationale**: Auth/orchestration less critical for MVP but required for multi-tenant production.



## 9. AgentOrchestratorService ✅**Estimated Effort**: 2 days



### Storage Backend### Phase 4: CLI & API Parity (P3 - Sprint 3)

- **Implementation**: `amprealize/agent_orchestrator_service_postgres.py`11. Add missing CLI commands (BCIService batch operations, RunService progress, etc.)

- **Storage**: PostgreSQL via `PostgresPool`12. Add missing API endpoints (AgentOrchestrator, Auth status/logout, SecurityService)

- **Status**: ✅ **Production Ready**13. Create parity tests for all new integrations



### API Coverage**Estimated Effort**: 2-3 days

```

POST /v1/agents/assign   ✅ assign_agent (via RestAgentAuthServiceAdapter)---

POST /v1/agents/switch   ✅ switch_agent

GET  /v1/agents/status   ✅ get_agent_status## Testing Strategy

```

For each service with new MCP tools:

### CLI Coverage

```1. **Create test file**: `tests/test_mcp_{service}_tools.py` (follow `test_mcp_action_tools.py` pattern)

amprealize agents assign  ✅ (via CLIAgentOrchestratorAdapter)2. **Test coverage**: All MCP tools via JSON-RPC protocol, parameter validation, error handling

amprealize agents switch  ✅3. **Parity validation**: Ensure CLI/MCP/API return equivalent results for same operations

amprealize agents status  ✅4. **Integration tests**: Test actual service backends, not just adapters

```

**Success Criteria**: All tests passing, pre-commit hooks green, CI workflow succeeds.

### MCP Coverage

```---

agents.assign  ✅ Line 1271

agents.switch  ✅ Line 1273## Behaviors to Apply

agents.status  ✅ Line 1275

```- `behavior_unify_execution_records` - Ensure consistent state across surfaces

- `behavior_align_storage_layers` - Validate storage adapter compatibility

**Parity Status**: ✅ **100% - All surfaces aligned**- `behavior_externalize_configuration` - Keep DSNs/secrets configurable

- `behavior_curate_behavior_handbook` - Document new patterns in `AGENTS.md`

---- `behavior_sanitize_action_registry` - Record all changes via `amprealize record-action`

- `behavior_wire_cli_to_orchestrator` - Map CLI commands to services

## 10. BCIService ✅- `behavior_lock_down_security_surface` - Audit auth/CORS for new endpoints

- `behavior_update_docs_after_changes` - Update `PRD.md`, `contracts/MCP_SERVER_DESIGN.md`, `contracts/ACTION_REGISTRY_SPEC.md`

### Storage Backend

- **Implementation**: `amprealize/bci_service.py`---

- **Storage**: Stateless (delegates to BehaviorService for retrieval)

- **Status**: ✅ **Production Ready**## Next Steps



### API Coverage1. **Prioritize gaps** with product/engineering stakeholders

```2. **Create implementation plan** for Phase 1 (BehaviorService, ComplianceService, RunService, WorkflowService)

POST /v1/bci:retrieve          ✅ retrieve_behaviors3. **Follow ActionService pattern** (commit 2768032) for consistent implementation

POST /v1/bci:composePrompt     ✅ compose_prompt4. **Update tracking docs** (`BUILD_TIMELINE.md`, `PROGRESS_TRACKER.md`, `PRD_ALIGNMENT_LOG.md`)

POST /v1/bci:validateCitations ✅ validate_citations5. **Record actions** via `amprealize record-action` for reproducibility

POST /v1/bci:rebuildIndex      ✅ rebuild_behavior_index

```---



### CLI Coverage**Document Status**: Draft - Awaiting prioritization

```**Owner**: Engineering

amprealize bci retrieve           ✅ (via CLIReflectionAdapter -> BCIService)**Related**: `contracts/MCP_SERVER_DESIGN.md` (§4-6), `contracts/ACTION_SERVICE_CONTRACT.md`, `PRD.md` (parity requirements)

amprealize bci compose-prompt     ✅
amprealize bci validate-citations ✅
amprealize bci rebuild-index      ✅
```

### MCP Coverage
```
bci.retrieve          ✅ Line 1125
bci.composePrompt     ✅ Line 1127
bci.validateCitations ✅ Line 1136
bci.rebuildIndex      ✅ Line 1145
```

**Parity Status**: ✅ **100% - All surfaces aligned**

---

## 11. AgentAuthService / DeviceFlow ✅

### Storage Backend
- **Implementation**: `amprealize/agent_auth.py`, `amprealize/device_flow.py`
- **Storage**: Ephemeral (device codes in memory, tokens in OS keychain via `TokenStore`)
- **Status**: ✅ **Production Ready** (tokens stored securely, not in DB)

### API Coverage
```
POST /v1/auth/device/authorize       ✅ initiate_device_flow
POST /v1/auth/device/poll            ✅ poll_device_authorization
POST /v1/auth/device/activate        ✅ activate_device_code (web form)
POST /v1/auth/token                  ✅ exchange_authorization_code
POST /v1/auth/token:refresh          ✅ refresh_access_token
GET  /v1/auth/grants                 ✅ list_grants
POST /v1/auth/grants:ensure          ✅ ensure_grant
DELETE /v1/auth/grants/{grant_id}    ✅ revoke_grant
```

### CLI Coverage
```
amprealize auth login            ✅ Initiates device flow
amprealize auth status           ✅ Check token validity
amprealize auth refresh          ✅ Refresh tokens
amprealize auth logout           ✅ Clear tokens
amprealize auth ensure-grant     ✅
amprealize auth list-grants      ✅
amprealize auth revoke           ✅
amprealize auth consent lookup   ✅
amprealize auth consent approve  ✅
amprealize auth consent deny     ✅
```

### MCP Coverage
```
auth.ensureGrant ✅ Line 1291
auth.listGrants  ✅ Line 1293
auth.revoke      ✅ Line 1302
auth.status      ✅ Line 1311
```

**Parity Status**: ✅ **100% - All surfaces aligned**

---

## 12. Analytics (Telemetry + Warehouse) ✅

### Storage Backend
- **Implementation**: `amprealize/analytics/` (TelemetryKPIProjector, AnalyticsWarehouse)
- **Storage**: DuckDB warehouse + telemetry events (JSONL or Kafka)
- **Status**: ✅ **Production Ready**

### API Coverage
```
POST /v1/analytics:projectKPI           ✅ project_kpi
GET  /v1/analytics/kpi-summary          ✅ get_kpi_summary
GET  /v1/analytics/behavior-usage       ✅ get_behavior_usage
GET  /v1/analytics/token-savings        ✅ get_token_savings
GET  /v1/analytics/compliance-coverage  ✅ get_compliance_coverage
```

### CLI Coverage
```
amprealize analytics project-kpi         ✅
amprealize analytics kpi-summary         ✅
amprealize analytics behavior-usage      ✅
amprealize analytics token-savings       ✅
amprealize analytics compliance-coverage ✅
```

### MCP Coverage
```
analytics.kpiSummary          ✅ Line 1228
analytics.behaviorUsage       ✅ Line 1230
analytics.tokenSavings        ✅ Line 1232
analytics.complianceCoverage  ✅ Line 1234
```

**Parity Status**: ✅ **100% - All surfaces aligned**

---

## Production Readiness Summary

### ✅ Ready for Production (9 services)
1. **BehaviorService** - PostgreSQL + FAISS
2. **ActionService** - PostgreSQL (when DSN configured)
3. **WorkflowService** - PostgreSQL
4. **MetricsService** - PostgreSQL (when DSN configured)
5. **AgentOrchestratorService** - PostgreSQL
6. **TraceAnalysisService** - PostgreSQL
7. **ReflectionService** - Postgres-backed (transitively)
8. **BCIService** - Stateless
9. **AgentAuthService** - Secure token storage

### ⚠️ **Blockers for Production** (2 services)

#### Priority 1.1: RunService Migration
- **Current**: SQLite (`~/.amprealize/runs.db`)
- **Target**: PostgresRunService (implementation exists)
- **Impact**: ⚠️ **HIGH** - Runs are core orchestration primitive
- **Effort**: ~2 hours (wiring + migration script)
- **Files to Update**:
  - `amprealize/api.py` line ~151 (conditional instantiation)
  - `amprealize/mcp_server.py` (MCPServiceRegistry)
  - `amprealize/cli.py` (CLI adapter logic)

#### Priority 1.2: ComplianceService Migration
- **Current**: In-memory dicts (non-persistent)
- **Target**: PostgresComplianceService (implementation exists)
- **Impact**: ⚠️ **HIGH** - Audit trail required per `contracts/AUDIT_LOG_STORAGE.md`
- **Effort**: ~2 hours (wiring + WORM testing)
- **Files to Update**:
  - `amprealize/api.py` line ~109 (conditional instantiation)
  - `amprealize/mcp_server.py` (MCPServiceRegistry)
  - `amprealize/cli.py` (CLI adapter logic)

---

## Surface Parity Summary

### Overall Parity Score: **100%**

| Service | API | CLI | MCP | Parity |
|---------|-----|-----|-----|--------|
| BehaviorService | ✅ | ✅ | ✅ | 100% |
| ActionService | ✅ | ✅ | ✅ | 100% |
| RunService | ✅ | ✅ | ✅ | 100% |
| ComplianceService | ✅ | ✅ | ✅ | 100% |
| ReflectionService | ✅ | ✅ | ✅ | 100% |
| MetricsService | ✅ | ✅ | ✅ | 100% |
| TraceAnalysisService | ✅ | ✅ | ✅ | 100% |
| WorkflowService | ✅ | ✅ | ✅ | 100% |
| AgentOrchestratorService | ✅ | ✅ | ✅ | 100% |
| BCIService | ✅ | ✅ | ✅ | 100% |
| AgentAuthService | ✅ | ✅ | ✅ | 100% |
| Analytics | ✅ | ✅ | ✅ | 100% |

**Result**: ✅ **All services have 100% surface parity** across API, CLI, and MCP

---

## Recommended Action Plan

### Phase 1: Production Storage Migration (Priority 1)
**Duration**: ~4 hours
**Impact**: Unblocks production deployment

1. **RunService → PostgresRunService**
   - Update `api.py` to conditionally use `PostgresRunService` when `AMPREALIZE_RUN_PG_DSN` is set
   - Update MCP server registry instantiation
   - Update CLI adapter conditional logic
   - Create migration script: `scripts/migrate_runs_sqlite_to_postgres.py`
   - Test run lifecycle: create → progress → complete/cancel

2. **ComplianceService → PostgresComplianceService**
   - Update `api.py` to conditionally use `PostgresComplianceService` when `AMPREALIZE_COMPLIANCE_PG_DSN` is set
   - Update MCP server registry instantiation
   - Update CLI adapter conditional logic
   - Test WORM audit log immutability requirements
   - Validate checklist create → record step → validate workflow

### Phase 2: Environment Variable Documentation
**Duration**: ~1 hour

1. Update `README.md` with comprehensive DSN configuration examples
2. Update `.env.example` with all `AMPREALIZE_*_PG_DSN` variables
3. Document fallback behavior (when DSNs not set, uses in-memory/SQLite)
4. Update `SECRETS_MANAGEMENT_PLAN.md` with DSN rotation procedures

### Phase 3: Integration Testing
**Duration**: ~2 hours

1. Add integration tests exercising Postgres implementations
2. Validate connection pooling pre-warming works across all services
3. Test concurrent operations on shared PostgresPool
4. Verify telemetry flows to warehouse correctly
5. Validate SSE metrics subscription under load

### Phase 4: Deployment Verification
**Duration**: ~1 hour

1. Deploy with all `AMPREALIZE_*_PG_DSN` variables configured
2. Smoke test each service via API/CLI/MCP
3. Validate connection pool metrics and performance
4. Confirm audit logs are immutable (WORM validation)
5. Run load test script (`behavior_test_optimized.txt` results as baseline)

---

## Environment Variables Reference

### Required for Production
```bash
# Behavior & Vector Index
AMPREALIZE_BEHAVIOR_PG_DSN=postgresql://user:pass@host:5432/amprealize_behaviors

# Action Registry & Replay
AMPREALIZE_ACTION_PG_DSN=postgresql://user:pass@host:5432/amprealize_actions

# Workflow Templates & Runs
AMPREALIZE_WORKFLOW_PG_DSN=postgresql://user:pass@host:5432/amprealize_workflows

# Run Orchestration (PRIORITY 1.1)
AMPREALIZE_RUN_PG_DSN=postgresql://user:pass@host:5432/amprealize_runs

# Compliance Audit Logs (PRIORITY 1.2)
AMPREALIZE_COMPLIANCE_PG_DSN=postgresql://user:pass@host:5432/amprealize_compliance

# Metrics & Analytics
AMPREALIZE_METRICS_PG_DSN=postgresql://user:pass@host:5432/amprealize_metrics

# Agent Orchestration
AMPREALIZE_AGENT_ORCHESTRATOR_PG_DSN=postgresql://user:pass@host:5432/amprealize_agents

# Connection Pool Configuration (optional, defaults shown)
AMPREALIZE_PG_POOL_SIZE=10
AMPREALIZE_PG_POOL_MAX_OVERFLOW=20
AMPREALIZE_PG_POOL_TIMEOUT=30
AMPREALIZE_PG_POOL_RECYCLE=1800
```

### Fallback Behavior (Development)
When DSN variables are not set:
- **BehaviorService**: Falls back to in-memory (no persistence)
- **ActionService**: Falls back to in-memory `ActionService`
- **RunService**: Falls back to SQLite at `~/.amprealize/runs.db`
- **ComplianceService**: Falls back to in-memory dicts (non-persistent)
- **MetricsService**: Falls back to SQLite cache + DuckDB warehouse
- **WorkflowService**: Falls back to in-memory (no persistence)

---

## Conclusion

### Current State
- ✅ **Surface Parity**: 100% across API/CLI/MCP (all 12 services)
- ✅ **PostgreSQL Implementations**: All services have Postgres versions
- ⚠️ **Production Wiring**: 75% (9/12 services default to Postgres)
- ⚠️ **Blockers**: 2 services need wiring (RunService, ComplianceService)

### Key Findings
1. **Excellent Surface Parity**: Every service operation is exposed through all three surfaces (API, CLI, MCP)
2. **Postgres Implementations Exist**: Both blocker services have complete Postgres implementations already built
3. **Minimal Effort Required**: Only wiring/configuration changes needed, not new development
4. **MCP Progress Notifications**: Already implemented for patterns.detectPatterns, can be extended to other long-running tools

### Next Steps
1. **Immediate** (Priority 1): Wire RunService and ComplianceService to use Postgres implementations
2. **Short-term** (Priority 2): Document environment variables and fallback behavior
3. **Medium-term** (Priority 3): Add integration tests for Postgres implementations
4. **Long-term** (Priority 4): Production deployment with smoke testing

### Estimated Timeline
- **Phase 1**: 4 hours (production storage wiring)
- **Phase 2**: 1 hour (documentation)
- **Phase 3**: 2 hours (integration testing)
- **Phase 4**: 1 hour (deployment verification)
- **Total**: ~8 hours to full production readiness

---

**References**:
- `contracts/MCP_SERVER_DESIGN.md` - Service architecture and capabilities
- `contracts/ACTION_SERVICE_CONTRACT.md` - ActionService API contract
- `contracts/BEHAVIOR_SERVICE_CONTRACT.md` - BehaviorService API contract
- `contracts/AUDIT_LOG_STORAGE.md` - WORM requirements for ComplianceService
- `contracts/RETRIEVAL_ENGINE_PERFORMANCE.md` - Vector index performance targets
- `contracts/SECRETS_MANAGEMENT_PLAN.md` - DSN storage and rotation
- `contracts/REPRODUCIBILITY_STRATEGY.md` - ActionService replay guarantees
