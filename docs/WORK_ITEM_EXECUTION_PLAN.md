# Work Item Execution Plan (Agent-Executed Tasks via GEP)

## 0. Status

**Status:** ✅ Gateway-First Architecture Documented

This document defines how a Work Item assigned to an agent is explicitly started and executed end-to-end using the Amprealize Execution Protocol (GEP), with full step logging, concise outcome summaries, and configurable autonomy/gates per agent.

**Summary:**
- ✅ **Gateway Migration**: `ExecutionGateway` is the canonical start boundary for board UI, chat, REST API, MCP, and CLI-shaped requests. The contract models execute vs plan-only intent, surface/chat linkage, policy context, idempotency, output target, and normalized queue payload metadata.
- ✅ **Backend Services**: WorkItemExecutionService (1419 lines), AgentExecutionLoop (1603 lines), AgentLLMClient (704 lines) fully implemented
- ✅ **REST API**: 7 endpoints operational in `work_item_execution_api.py` (565 lines)
- ✅ **MCP Tools**: Handlers (451 lines) and manifests (5 tools) fully integrated in `mcp_server.py`
- ✅ **BYOK LLM Credentials**: Full DB persistence, encryption, CRUD endpoints
- ✅ **LLM Adapters**: Anthropic ✅, OpenAI ✅, OpenRouter ⏳, Local ⏳
- ✅ **Execution Surface Enforcement**: Actor surface detection → write mode (PR vs local)
- ✅ **BYOK GitHub Tokens**: Per-project GitHub credential storage (parallel to LLM creds)
- ✅ **PR Write Mode**: Branch naming, PR creation, file change accumulation
- 🔮 **Cloud IDE**: Codespaces, Gitpod, Fleet integration (design complete, implementation deferred)
- ✅ **UI**: Core components implemented in `@amprealize/collab-client` + `web-console` (status badges, timeline, execution controls)
- 🎨 **Chat UX North Star**: `guideai-1043` should implement the bottom-dock-to-draggable-glass-window chat experience with inline live work item/run cards, magic composer, adaptive agent presence, speed rituals, and tiered recovery.

### Implementation Status Summary

| Component | Status | Location |
|-----------|--------|----------|
| **WorkItemExecutionService** | ✅ Implemented | `amprealize/work_item_execution_service.py` (1419 lines) |
| **AgentExecutionLoop** | ✅ Implemented | `amprealize/agent_execution_loop.py` (1603 lines) |
| **AgentLLMClient** | ✅ Implemented | `amprealize/agent_llm_client.py` (704 lines) |
| **LLM Adapters** | ⚠️ Partial | Anthropic ✅, OpenAI ✅, OpenRouter ⏳ TODO, Local ⏳ TODO |
| **Contracts & Models** | ⚙️ Gateway migration in progress | `amprealize/work_item_execution_contracts.py`, `amprealize/execution_gateway_contracts.py` |
| **REST API Endpoints (7)** | ✅ Implemented | `amprealize/services/work_item_execution_api.py` (565 lines) |
| **MCP Tool Handlers (5)** | ✅ Implemented | `amprealize/mcp/handlers/work_item_execution_handlers.py` (451 lines) |
| **MCP Tool Manifests (5)** | ✅ Created | `mcp/tools/workItems.{execute,executionStatus,cancelExecution,provideClarification,listExecutions}.json` |
| **MCP Server Routing** | ✅ Wired | `amprealize/mcp_server.py` (lines 3158-3186) |
| **CredentialStore (LLM)** | ✅ Implemented | `amprealize/work_item_execution_service.py:109` |
| **InternetAccessResolver** | ✅ Implemented | `amprealize/work_item_execution_service.py:350` |
| **WriteTargetResolver** | ✅ Implemented | `amprealize/work_item_execution_service.py:388` (with SettingsService) |
| **ToolExecutor** | ✅ Implemented | `amprealize/tool_executor.py` (772 lines) |
| **MODEL_CATALOG** | ✅ Implemented | `amprealize/work_item_execution_contracts.py:107` (5 models) |
| **Execution Wiring** | ✅ Complete | `amprealize/execution_wiring.py` (248 lines) |
| **Execution Surface Detection** | ✅ Implemented | `WorkItemExecutionService.execute()` step 5.5 |
| **ExecutionMode Settings** | ✅ Implemented | `amprealize/multi_tenant/settings.py` (enum + ProjectSettings field) |
| **Surface Enforcement Error** | ✅ Implemented | `ExecutionSurfaceRestrictedError` with guidance |
| **BYOK GitHub Tokens** | ✅ Complete | `credentials.github_credentials` table + repository |
| **Branch Naming Convention** | ✅ Complete | `generate_pr_branch_name()` → `amprealize/work-item-{id}-{timestamp}` |
| **PR Creation in Loop** | ✅ Complete | `AgentExecutionLoop._create_pull_request_if_needed()` + `GitHubService` |
| **Cloud IDE Integration** | 🔮 Planned | Codespaces, Gitpod, Fleet |
| **Execution UI** | ✅ Implemented / 🎨 UX north star defined | `@amprealize/collab-client`, `web-console`, `docs/CONVERSATION_SYSTEM_PLAN.md` |

> **Cross-Reference**: UI implementation must follow `docs/COLLAB_SAAS_REQUIREMENTS.md` for performance targets, animation system, dual-user paradigm (agents + humans), and the Amprealize Chat UX north star. Detailed chat interaction guidance lives in `docs/CONVERSATION_SYSTEM_PLAN.md`.

_Last updated: 2026-04-25_

### ExecutionGateway Migration Contract

`ExecutionGateway` is the migration target for all run-start surfaces: board UI, chat, REST API, MCP, and CLI. During migration, existing `WorkItemExecutionService` response shapes remain the compatibility boundary for deployed clients, while new adapters should convert each surface request into `ExecutionRequest`.

The stale assumption to retire is that `WorkItemExecutionService` alone owns run starts. It remains the legacy compatibility service for non-start operations and as an incident fallback, but new start paths should enter through the gateway so policy, source resolution, idempotency, plan-only behavior, and queue payloads are composed once.

The canonical request/result contract is `amprealize/execution_gateway_contracts.py`:

- `ExecutionRequest` carries `work_item_id`, `project_id`, `org_id`, `user_id`, invoking `surface`, source overrides, output target override, model/agent overrides, `idempotency_key`, and governance metadata.
- `ExecutionIntent` differentiates `execute` from `plan_only`; plan-only requests must use read-only/tool-limited policy and produce durable plan artifacts before any approval-triggered execution run.
- Chat-originated requests can link `conversation_id` and `message_id` so run cards and plan cards attach to the correct transcript.
- `GatewayQueuePayload` is the normalized payload that should be stored in `ExecutionJob.payload` once dispatch becomes queue-first. It preserves gateway intent, mode, source, output, surface, policy, approval, idempotency, and chat linkage for workers.
- `ExecutionGatewayResult` carries gateway fields plus compatibility metadata so REST/MCP/CLI adapters can preserve existing response shapes while sharing the same underlying contract.
- **`execution_workspace_kind`** (canonical: `cloud_git` | `local_connector`) selects the **workspace driver** inside the same gateway state machine: **`cloud_git`** uses mode executors with BreakerAmp/Podman provisioning (`CONTAINER_ISOLATED` / related modes)—the agent workspace is an **isolated clone** inside a container, not the developer laptop tree. **`local_connector`** uses the **hybrid model**: after pairing (`POST /api/v1/execution-connector/*`, flag `AMPREALIZE_ENABLE_LOCAL_EXECUTION_CONNECTOR`), the daemon receives **`run_lease`**, sends **`run.lease_ack`**, then executes **`tool.invoke`** round-trips (**`tool.result`**) for filesystem and bounded shell tools while **`AgentExecutionLoop` stays on the API process**. Protocol: **`docs/contracts/LOCAL_CONNECTOR_TOOL_PROTOCOL.md`**. **`dispatch_mode` must be `background`** for `local_connector` hybrid runs (queue workers do not await daemon RPC). REST **`POST /v1/work-items/{id}:execute`** and chat/composer payloads accept **`execution_workspace_kind`**; **`GET .../execution`** exposes **`execution_workspace_kind`** and **`connector_status`**. MCP **`executionConnector.*`** + **`workItems.execute`** parity preserved.
- `GatewayWorkItemExecutionAdapter` exposes the legacy `execute(ExecuteWorkItemRequest)` service shape for REST and MCP handlers. It maps old request fields into `ExecutionRequest` and returns `ExecuteWorkItemResponse`, while non-start operations can delegate to the legacy service until status/cancel/clarification routes are migrated.
- REST and MCP execution factories accept an optional gateway and wrap only the start path through `GatewayWorkItemExecutionAdapter`. API and MCP bootstraps now initialize that gateway by default, making the gateway the canonical start boundary while preserving `AMPREALIZE_EXECUTION_GATEWAY_ENABLED=false` as an explicit legacy fallback for incident response.
- `ExecutionGateway` now has an explicit dispatch mode. `background` keeps the current development behavior, while `queue` requires an `ExecutionQueuePublisher`, creates run/task-cycle metadata, enqueues an `ExecutionJob` with `GatewayQueuePayload`, and avoids API-process background execution. If queue dispatch is enabled without a publisher, the request fails before run/cycle records are created.
- `ExecutionGateway` handles `ExecutionIntent.PLAN_ONLY` as a non-dispatching gateway mode. It derives a read-only execution policy, denies write and platform-mutating tools, creates a `PlanArtifact`, returns a summary card in compatibility metadata, marks the plan run as completed, and distinguishes plan runs with `run_type=plan_only`.
- `PolicyCompositionEngine` evaluates the request's user, org, project, conversation, agent, MCP/tool, attachment, and action-risk policy signals before run/task-cycle creation. It returns `allow`, `deny`, or `review`; deny blocks immediately, review requires `approved_by`, and evaluation failures fail closed while emitting policy audit telemetry.
- `GovernedChatAuditLogger` records append-only, sanitized chat governance audit entries for intent classification, scope resolution, policy decisions, approvals/denials, tool calls, and execution starts. Records include user, chat scope, target resources, action, decision, policy IDs, execution observability context, and work item/run/chat links where available; `denied_or_review_required()` exposes review and denial queues without storing raw sensitive payloads.
- Execution status, execution detail, execution list, and MCP execution status/list payloads expose a normalized `trace_summary` plus flat compatibility fields for origin surface, chat links, queue metadata, phase timings, token/cost/tool totals, and last error. The work item drawer renders a unified trace panel from that normalized summary, falling back to flat fields for older responses, so chat-triggered and board-triggered executions share one visible trace surface.
- `GUIDEAI-1138` adds agent execution golden trace fixtures and regressions for chat-triggered, board-triggered, queued, direct/background, phase-failure, tool-denial, and successful-completion paths. These fixtures assert required correlation fields across RunService metadata, TaskCycle metadata, telemetry events, and RunStep trace output, including shared redaction for sensitive values.
- `GUIDEAI-1121` adds deterministic and execution-handoff chat answer golden traces. Reply metadata and `conversation_reply.generated` telemetry now include a bounded `chat_trace` object linking conversation, user message, reply message, route action/category, answer path, work item, and run IDs without creating duplicate execution telemetry for chat-triggered handoffs.
- `GUIDEAI-1122` adds LLM and MCP/platform-action golden traces. LLM replies and platform-action replies assert exporter parity between stored `chat_trace` metadata and telemetry payloads, platform-action traces include created-resource outcomes, and MCP resource-analysis responses remain JSON/exporter-safe.
- `GUIDEAI-1123` adds RBAC and load-style observability validation. `amprealize/observability_access.py` filters telemetry payloads by access tier, hides raw prompts/tool inputs/output previews from viewer and data-analyst access, preserves BreakerAmp execution context fields, and builds bounded dashboard summaries for high-cardinality event streams.
- `GUIDEAI-1113` adds `GovernedObservabilityQueryService` as the runtime access-control boundary for telemetry and trace analytics. It resolves actor roles to viewer, data-analyst, admin, or compliance tiers, applies the same restricted-field filtering to list queries, and returns bounded dashboard summaries with preserved correlation metadata.
- `GUIDEAI-1112` exposes the governed analytics boundary through typed REST query contracts at `POST /api/v1/observability/events` and `POST /api/v1/observability/dashboard`. The app route uses in-memory telemetry events in tests/dev and Postgres telemetry queries when `AMPREALIZE_TELEMETRY_PG_DSN` is configured.
- `GUIDEAI-1114` enables chat-powered observability questions. `ConversationReplyService` now has a deterministic observability fast path backed by `ObservabilityChatAnswerService` and `GovernedObservabilityQueryService`, so questions such as "which tools fail most?" or "why are replies slow?" return role-filtered answers without an LLM round trip or restricted payload leakage.
- `GUIDEAI-1111` defines the canonical trace envelope schema in `amprealize/observability_contracts.py`. The schema covers `trace`, `span`, `event`, `generation`, `tool_call`, `action`, `artifact`, `behavior_candidate`, and `outcome` records, shares one `ObservabilityCorrelation` shape, validates required correlation fields, and provides sanitized export payloads plus examples for storage/exporter alignment.
- `GUIDEAI-1190` publishes the consolidated contract and capture policy in `docs/contracts/CANONICAL_TRACE_CONTRACT.md`, including the telemetry → `observability_records` projection matrix and documented projection gaps for follow-up tasks.
- `GUIDEAI-1101` updates telemetry and trace-analysis contracts so the taxonomy from `GUIDEAI-1111` is explicit across OSS, self-hosted enterprise, and managed enterprise profiles. `observability_backend_targets()` now records the tested profile-to-backend matrix, and TraceAnalysisService documentation maps each canonical record kind to behavior-mining inputs.
- `GUIDEAI-1100` completes the `GUIDEAI-1092` contract slice by defining retention and sensitivity classes in `observability_retention_rules()`. The policy separates long-lived metadata, summaries, hashes, and behavior-mining features from short-lived raw prompts, raw responses, tool args, output previews, command output, and file diffs with explicit access tiers and purge/anonymization rules.
- `PlanArtifact` in `amprealize/plan_artifact_contracts.py` defines the durable plan-only output contract. Artifacts have stable `plan-*` IDs, immutable version history, links to work item/project/org/chat/message/agent/source run, and lifecycle states for draft, approved, discarded, and executed plans.

### Migration Path And Surface Matrix

| Surface | Start path | Status | Migration note |
| --- | --- | --- | --- |
| Board / Web UI | `ExecutionRequest(surface="web")` through board controls and drawer actions | ✅ Supported | Uses shared execution control model and gateway-compatible run states. |
| Amprealize Chat | `ExecutionRequest(surface="chat")` with `conversation_id`, `message_id`, `intent`, approval, and plan artifact linkage | ✅ Supported | Chat actions route through typed candidates, policy composition, and append-only audit records before dispatch. |
| REST API | `GatewayWorkItemExecutionAdapter` wrapping legacy execute response shape | ✅ Supported | Legacy response compatibility remains while start creation moves to the gateway. |
| MCP | Work item execution handlers using the same adapter path | ✅ Supported | Start parity is validated against REST, CLI-shaped, and chat-shaped gateway requests. |
| CLI | CLI-shaped request metadata and idempotency keys | ⚠️ Adapter-shaped validation | Canonical request parity is tested; dedicated user-facing CLI command wiring remains a follow-up where absent. |
| Queue workers | `GatewayQueuePayload` from resolved gateway request | ⚠️ Dispatch contract supported | Requires an `ExecutionQueuePublisher`; misconfiguration fails before orphan records are created. |

Parity evidence lives in `tests/test_execution_gateway_adapter.py`, which compares REST, MCP, CLI-shaped, and chat-shaped request signatures and verifies REST/MCP cancel and clarification controls remain consistent during migration.

### Plan Artifact Contract

`guideai-1054` defines the plan artifact shape used by plan-only gateway execution before storage and runtime wiring. A draft plan artifact is created from a plan-only run, can be revised while preserving previous versions, can be approved by a user, can be discarded while remaining auditable, and can be marked executed only after approval when a separate execution run starts.

The contract intentionally separates approval from execution: `PlanArtifact.can_start_execution` is true only for approved artifacts, and `mark_executed()` records the execution run ID without mutating the historical plan versions.

### Plan-Only Gateway Mode

`guideai-1055` wires `ExecutionIntent.PLAN_ONLY` into `ExecutionGateway`. Plan-only requests still validate the work item, resolve the assigned agent, evaluate composed policy, resolve model/source/mode, and create Run + TaskCycle records. Before any executor or queue dispatch can happen, the gateway replaces the agent policy with a read-only/tool-limited policy, creates a draft `PlanArtifact`, updates the run as a completed `plan_only` run, and returns both `plan_artifact_id` and a `summary_card` in `ExecutionGatewayResult.compatibility`.

Plan-only mode is intentionally not an execution shortcut. It cannot enqueue workers, start background executors, or mutate files, boards, agents, projects, or orgs. Approval of the resulting artifact remains a separate lifecycle step; only an approved plan can seed a later execution run.

### Plan Approval Flow

`guideai-1056` adds `PlanApprovalService` in `amprealize/plan_approval_service.py` as the lifecycle bridge from draft plan artifacts to execution. The service uses a `PlanArtifactRepository` boundary so storage can be swapped from the in-memory implementation to a durable backend without changing callers.

The approval flow has three explicit non-execution actions:

- `revise_plan()` appends a new immutable plan version and resets approval back to draft.
- `discard_plan()` preserves the artifact and versions for audit while blocking later execution.
- `approve_plan()` records approver metadata without starting a run by itself.

To execute, callers use `approve_and_start_execution()`. It approves the artifact, builds a fresh `ExecutionRequest` with `intent=execute`, `plan_artifact_id`, approval context, agent/work item/chat links, and optional mode/output/model overrides, then calls `ExecutionGateway.execute()`. Only after the gateway returns a successful new `run_id` does the service mark the plan artifact as executed and link `execution_run_id`.

### Chat-Originated Permission Boundary

`guideai-1051` defines the chat permission matrix in `amprealize/conversation_contracts.py` and `docs/contracts/CHAT_PERMISSION_MATRIX.md`. `guideai-1052` consumes it through `PolicyCompositionEngine`, so execution requests that originate from global chat, project spaces, work item threads, run threads, agent lifecycle actions, MCP tools, attachments, or platform actions can compose chat requirements with the other policy layers. Chat linkage fields (`conversation_id`, `message_id`) provide audit context only; they do not grant project, agent, tool, attachment, or platform-action access.

`guideai-1064` validates the runtime boundary: inaccessible global-chat resource links are withheld before synthesis, group-chat execution requires conversation/project/agent scopes, MCP tool grants require approval, attachments require project or conversation scope, and agent lifecycle policy denial blocks registry dispatch. The regression coverage is in `tests/test_chat_governance_boundaries.py`.

## 1. Goals

1. **Explicit start**: Work items do not auto-run on assignment. Users explicitly start execution.
2. **All agent-executed tasks use GEP**: Every agent-run work item is executed as a GEP `TaskCycle`.
3. **Playbook-grounded execution**: The assigned agent must follow its playbook (mission, rubrics, templates, escalation rules) sourced from the agent registry/playbooks.
4. **Tool-driven agent**: The executing agent can plan, call Amprealize MCP tools, edit local files, open GitHub PRs, search the internet (if enabled), and iterate.
5. **Auditable traces**:
   - Verbose: structured `RunStep` log + Raze telemetry
   - Concise: outcome summary posted back to the Work Item card as a comment
6. **Board sync**: On success, move the work item to the Completed column.

## 2. Non-Goals (for initial implementation)

- Auto-merge PRs
- Multi-agent parallel execution on a single work item
- New UI beyond the implemented board controls, work item drawer, and chat artifact/control surfaces
- Persistent policy administration UI beyond the runtime composition hook

## 3. Core Concepts

### 3.1 Entities

- **Work Item**: the unit of work on a board.
- **Run**: the canonical execution record (RunService).
- **TaskCycle**: the canonical GEP execution state machine (TaskCycleService).
- **Agent Playbook**: agent mission/rubrics/templates (from `agents/AGENT_*.md`, synchronized into Agent Registry).

### 3.2 Roles and GEP Phases

All agent-executed work items run through the 8 GEP phases:

1. PLANNING
2. CLARIFYING
3. ARCHITECTING
4. EXECUTING
5. TESTING
6. FIXING
7. VERIFYING
8. COMPLETING

Default gate behavior is defined in `TASK_CYCLE_SERVICE_CONTRACT.md`, but **gate enforcement is configurable per agent**.

## 4. Execution Triggers

### 4.1 Explicit Start

Work items assigned to agents do not execute until a user triggers execution via:

- UI: “Start” button on the work item, board card, or work item drawer
- Chat: typed execution or plan-only action after governance and approval checks
- MCP: `workItems.execute`
- REST: `/api/v1/work-items/{id}/execute`
- CLI: gateway-compatible command/request path where enabled

### 4.2 Idempotency

Starting execution should be idempotent:

- If a work item already has an active `run_id` in a non-terminal state, return that run.
- If the last run is terminal, create a new run (keeping history).

## 5. Execution Architecture

### 5.1 Services

#### WorkItemExecutionService ✅ IMPLEMENTED
**Location:** `amprealize/work_item_execution_service.py`
**Responsibility:** Bridge Work Items ↔ RunService ↔ TaskCycleService and drive execution.

Key functions:
- ✅ Validate permissions + project/org tool/model gating
- ✅ Resolve assigned agent and load its playbook snapshot
- ✅ Create Run + TaskCycle
- ✅ Invoke AgentExecutionLoop until terminal
- ✅ Persist logs to RunService and update Work Item/Board state
- ✅ Persist shared `execution_observability` metadata so chat, board, REST API, MCP, CLI, queue workers, and direct execution can correlate the same `run_id`, `cycle_id`, work item, agent, model, surface, request, and chat-origin ids.

**Key Methods:**
- `execute(request, actor)` - Start work item execution
- `get_status(work_item_id, org_id?, project_id)` - Get execution status
- `cancel(work_item_id, org_id?, project_id, actor, reason)` - Cancel execution
- `provide_clarification(work_item_id, ..., response)` - Submit clarification
- `list_executions(org_id?, project_id, ...)` - List execution history
- `get_execution_by_run_id(run_id)` - Get execution details
- `get_execution_steps(run_id)` - Get step-by-step trace

#### AgentExecutionLoop ✅ IMPLEMENTED
**Location:** `amprealize/agent_execution_loop.py`
**Responsibility:** Phase-by-phase execution loop.

- ✅ Reads current phase from TaskCycle
- ✅ Calls `AgentLLMClient` to produce a phase output and/or tool calls
- ✅ Executes tool calls (via ToolExecutor with permission checks)
- ✅ Appends `RunStep` entries
- ✅ Advances the TaskCycle per valid transitions
- ✅ Emits per-phase and LLM-response telemetry using the shared execution observability context from `GUIDEAI-1091`.
- ✅ Mirrors phase completion/failure and LLM response milestones into RunStep metadata for UI trace rendering.

**Key Features:**
- Phase handlers for all 8 GEP phases (PLANNING → COMPLETING)
- `MAX_PHASE_ITERATIONS = 50` per-phase iteration limit
- `MAX_TOTAL_ITERATIONS = 200` total iteration limit
- `PhaseContext` and `PhaseResult` dataclasses

#### AgentLLMClient ✅ IMPLEMENTED
**Location:** `amprealize/agent_llm_client.py`
**Responsibility:** LLM/SLM abstraction for agent execution.

- ✅ Composes prompts from:
  - agent playbook
  - work item context
  - current phase + recent steps
  - allowed tools schema
- ✅ Supports model switching per agent policy and per run
- ✅ Provides a structured response format:
  - text output
  - optional tool calls
  - optional "needs clarification" questions
  - optional "stop" / "blocked" state

**Provider Adapters:**
- `AnthropicAdapter` - Claude models ✅ Implemented
- `OpenAIAdapter` - GPT models ✅ Implemented
- `OpenRouterAdapter` - Multi-provider routing ⏳ TODO
- `LocalAdapter` - Local model support ⏳ TODO

#### Supporting Classes ✅ IMPLEMENTED

| Class | Location | Purpose |
|-------|----------|---------|
| `CredentialStore` | `work_item_execution_service.py:109` | LLM credential resolution (platform/org/project) |
| `InternetAccessResolver` | `work_item_execution_service.py:350` | Internet access permission checking |
| `WriteTargetResolver` | `work_item_execution_service.py:379` | Write scope resolution (local/PR/both) |
| `ToolExecutor` | `tool_executor.py` | Tool call execution with permissions, shared execution context, sanitized lifecycle events, separate `execution.tool.performance`, and separate `execution.tool.business_outcome` events |
| `LLMCallMetrics` | `agent_llm_client.py:45` | Token/cost tracking |
| `ExecutionObservabilityContext` | `execution_observability.py` | Shared run/cycle/work-item/agent/model/surface/chat/queue correlation metadata and redaction helpers |
| `SessionAuditLogger` / `GovernedChatAuditLogger` | `session_audit.py` | Sanitized session and governed-chat tool-call audit records with shared execution context, decisions, target resources, output previews, and error classes |
| Prompt composition | `agent_llm_client.py` (inline) | Context-aware prompt assembly |
  - text output
  - optional tool calls
  - optional “needs clarification” questions
  - optional “stop” / “blocked” state

### 5.2 High-Level Flow

1. User assigns agent to work item (no execution yet)
2. User starts execution (`workItems.execute`)
3. WorkItemExecutionService:
   - creates Run (execution tracking: status, progress, steps, telemetry)
   - creates TaskCycle (GEP phase state machine: gates, clarifications, architecture)
   - links: `WorkItem.run_id → Run.run_id`; `Run.metadata.cycle_id → TaskCycle.cycle_id`
   - snapshots agent playbook + execution policy into Run metadata
4. AgentExecutionLoop iterates phases until terminal
5. On completion:
   - post concise summary comment to work item
   - move work item to column with `status_mapping = 'completed'`
   - if no such column exists, update `WorkItem.status = 'completed'` only
   - update `WorkItem.completed_at` timestamp

**Entity Relationships:**
```
WorkItem (1) ──run_id──> Run (1) ──metadata.cycle_id──> TaskCycle (1)
     │                      │
     └── board_id ──>      └── steps[] (RunStep)
         column_id
```

- **Run**: Canonical execution record (status, progress, steps, outputs, telemetry)
- **TaskCycle**: GEP phase state machine (phase gates, clarifications, architecture docs)
- **Relationship**: 1 WorkItem → 1 Run → 1 TaskCycle (per execution attempt)

## 6. Agent Autonomy & Gates (Configurable) ✅ IMPLEMENTED

**Implementation:** `ExecutionPolicy` dataclass in `work_item_execution_contracts.py`, gate enforcement in `agent_execution_loop.py`

### 6.1 Execution Policy Schema (Agent Registry) ✅

`execution_policy` is implemented as a dataclass:

- `phase_gates`: map of GEP phase → `none|soft|strict`
- `internet_access`: `inherit|enabled|disabled`
- `write_scope`: `inherit|local_only|pr_only|local_and_pr`
- `model_policy`:
  - `preferred_model_id`
  - `fallback_model_ids[]`
  - `allow_mid_run_switching` (bool)

### 6.2 Default Policies ✅

- Default agents: keep standard GEP gate defaults unless overridden.
- AI Researcher agent: fully autonomous (`AUTONOMOUS_RESEARCHER` preset):
  - `ARCHITECTING=none`, `VERIFYING=none`, `COMPLETING=none`
  - Still runs the phases, but does not block for human approval.

### 6.3 Error Handling & Recovery ✅ IMPLEMENTED

**LLM API Failures:**
- Retry with exponential backoff: 1s, 2s, 4s (max 3 attempts)
- If all retries fail: pause execution, log error, notify user
- If `allow_mid_run_switching` is true, attempt fallback model

**Tool Call Failures:**
- Log error with full context to Raze
- Allow agent to recover (agent can retry or choose alternative approach)
- If tool is critical (e.g., file write), surface error in agent response

**Infinite Loop Prevention:**
- Enforce `max_test_iterations` (default: 10) for TESTING→FIXING cycle
- If exceeded: transition to FAILED with summary of attempts
- Emit `gep.max_iterations_exceeded` telemetry event

**Fatal Errors:**
- Transition TaskCycle to FAILED state
- Update Run status to FAILED with error details
- Post error summary as work item comment
- Do NOT move work item to Completed column

**Timeout Handling:**
- Per-phase timeouts configurable in `timeout_config`
- On timeout: apply `timeout_policy` (pause_with_notification | escalate | proceed)
- Emit `gep.timeout_triggered` telemetry event

## 7. Internet Access (Org/Project Gating) ✅ IMPLEMENTED

**Implementation:** `InternetAccessResolver` class in `work_item_execution_service.py:350`

Internet access is gated at org/project scope:

- Org setting: `org.internet_access_enabled`
- Project setting: `project.internet_access_enabled`

Resolution order:

- If project disables, internet is disabled.
- Else if org disables, internet is disabled.
- Else the agent’s execution policy decides.

When disabled:
- The agent must not use web tools; it should proceed using only provided inputs and repository context.

## 8. Write Targets: Local Files vs GitHub PRs ✅ COMPLETE

**Implementation:** `WriteTargetResolver` class in `work_item_execution_service.py:379`

Execution writes are controlled by **execution surface** and **project settings**:

### 8.1 Execution Surface Detection ✅ COMPLETE

The system automatically enforces write capabilities based on the execution surface:

| Surface | Execution Mode | File Access | GitHub PR | Notes |
|---------|---------------|-------------|-----------|-------|
| **VS Code Extension** | Full Local | ✅ Direct | ✅ Optional | MCP server runs as local subprocess |
| **Web UI** | PR-Only | ❌ None | ✅ Required | Containerized agent cannot access local FS |
| **CLI** | Full Local | ✅ Direct | ✅ Optional | CLI runs on same machine as codebase |
| **MCP (external)** | PR-Only | ❌ None | ✅ Required | External MCP clients use API container |
| **Cloud IDE** | Coming Soon | TBD | TBD | Codespaces, Gitpod, etc. |

**Architecture Rationale:**
- The API container runs in Podman/Docker and cannot access the user's local filesystem
- VS Code extension spawns a local MCP server subprocess that CAN access local files
- Web UI users MUST use GitHub PR mode since containerized agent has no local path access
- Clear UI messaging: "Local file operations require VS Code extension" when surface doesn't support local

### 8.2 Execution Mode Project Setting ✅ COMPLETE

New project setting `execution_mode` controls write behavior:

| Mode | Description | Surfaces Supported |
|------|-------------|--------------------|
| `local` | Direct filesystem writes | VS Code, CLI |
| `github_pr` | All changes via GitHub PRs | All surfaces |
| `local_and_pr` | Write locally AND create PR | VS Code, CLI |

**Resolution Logic:**
1. Check `actor.surface` from request context
2. If `surface=web` or `surface=api` → Force `github_pr` mode (local not available)
3. Else use project's `execution_mode` setting
4. If `execution_mode=local` but surface is web → Return error with guidance

### 8.3 Write Scope Values

- ✅ `READ_ONLY`: No writes allowed
- ✅ `LOCAL_ONLY`: Direct filesystem writes only (VS Code/CLI)
- ✅ `PR_ONLY`: All changes via GitHub PRs
- ✅ `LOCAL_AND_PR`: Write locally AND create PR

### 8.4 GitHub PR Mode ✅ COMPLETE

**Branch Naming Convention:**
- Format: `amprealize/work-item-{work_item_id}-{timestamp}`
- Example: `amprealize/work-item-a1b2c3d4-20260114T153045Z`
- Automatic branch creation on first file write in PR mode

**PR Creation Flow:**
1. Agent accumulates file changes during execution
2. On phase completion (EXECUTING → TESTING), create/update branch
3. On execution completion, create PR with summary
4. PR links posted back to work item comment

### 8.5 BYOK GitHub Tokens ✅ COMPLETE

GitHub credentials follow the same BYOK pattern as LLM credentials:

**Storage:**
- Table: `credentials.github_credentials` (parallel to `credentials.llm_credentials`)
- Fields: `org_id`, `project_id`, `token` (encrypted), `token_type` (classic/fine-grained)
- Encryption: Same `CredentialEncryptionService` (Fernet/KMS/Vault)

**Resolution Order (first match wins):**
1. Project-level BYOK token
2. Org-level BYOK token
3. Platform-level token (env var `GITHUB_TOKEN`)

**Token Types:**
- Classic PAT: `ghp_*` prefix
- Fine-grained PAT: `github_pat_*` prefix (recommended)
- GitHub App installation token: `ghs_*` prefix

**Required Scopes:**
- `repo` (or `contents:write` for fine-grained)
- `pull_requests:write` (for fine-grained)

### 8.6 Cloud IDE Integration 🔮 PLANNED

**Target Platforms (cutting edge):**
- **GitHub Codespaces** — VS Code in browser with full FS access
- **Gitpod** — Cloud development environments
- **AWS Cloud9** — Amazon's cloud IDE
- **JetBrains Fleet** — Cloud-native IDE (remote dev)
- **Cursor** — AI-first IDE (potential integration)
- **Zed** — Next-gen collaborative editor

**Architecture:**
- Cloud IDEs run in containers with access to workspace
- Extension/plugin model similar to VS Code
- MCP server can run locally within cloud IDE container
- No PR-only restriction since agent shares filesystem with IDE

**Implementation Status:** Coming Soon (design complete, implementation deferred)

Notes:
- PR creation is never auto-merged in v1.
- Any destructive change (file delete, large refactor) can be made gateable later; for v1 we simply log and allow if write scope permits.

## 9. Model System (OOTB + BYOK) ✅ COMPLETE

**Implementation:** `MODEL_CATALOG` in `work_item_execution_contracts.py:107`, `CredentialStore` in `work_item_execution_service.py:109`, `LLMCredentialRepository` in `auth/llm_credential_repository.py` (622 lines)

### 9.1 Requirements ✅

- ✅ Out-of-the-box supported models:
  - `claude-opus-4-5` (Anthropic Claude Opus 4.5)
  - `claude-sonnet-4-5` (Anthropic Claude Sonnet 4.5)
  - `gpt-5-2` (OpenAI GPT-5.2)
  - `gpt-4o` (OpenAI GPT-4o) — added
  - `claude-3-5-sonnet` (Anthropic Claude 3.5 Sonnet) — added
- ✅ Platform-level credentials (admin-managed via environment variables)
- ✅ Bring-your-own-key (BYOK) at org/project scope (fully implemented with DB persistence)
- ✅ Model availability is resolved at org/project scope
- ✅ Agents can be configured to use any model that is available

**Model Catalog (implemented):**

| model_id | provider | display_name | supports_tool_calls | context_limit |
|----------|----------|--------------|---------------------|---------------|
| `claude-opus-4-5` | anthropic | Claude Opus 4.5 | ✅ | 200K |
| `claude-sonnet-4-5` | anthropic | Claude Sonnet 4.5 | ✅ | 200K |
| `gpt-5-2` | openai | GPT-5.2 | ✅ | 128K |
| `gpt-4o` | openai | GPT-4o | ✅ | 128K |
| `claude-3-5-sonnet` | anthropic | Claude 3.5 Sonnet | ✅ | 200K |

### 9.2 Architecture ✅ IMPLEMENTED

#### ModelCatalog ✅ (`MODEL_CATALOG` dict in contracts)
- `model_id`
- `provider` (anthropic/openai/openrouter/local)
- `display_name`
- `supports_tool_calls`
- `context_limit`, `max_output_tokens`, `input_price_per_m`, `output_price_per_m`

#### CredentialStore ✅ (class at `work_item_execution_service.py:109`)
- ✅ Platform credentials (from env vars: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`)
- ✅ Org credentials (DB persistence via `credentials.llm_credentials` table)
- ✅ Project credentials (DB persistence via `credentials.llm_credentials` table)

#### ModelAvailabilityResolver ✅ (via `CredentialStore.get_credential_for_model`)
Returns: tuple of `(api_key, source, is_byok)` or `None` if not available.

Resolution order (first match wins):
1. Project credential (if present) — BYOK takes priority
2. Org credential (if present) — BYOK at org level
3. Platform credential (if present) — admin-managed defaults

**Conflict resolution:**
- First matching credential wins (project > org > platform)
- BYOK credentials always override platform credentials at same scope
- If no credential exists for a model, that model is unavailable in the project
- Agents cannot use models that are unavailable in their assigned project

### 9.3 Agent Model Policy
Each agent has:
- `preferred_model_id`
- `fallback_model_ids`
- `allow_mid_run_switching`

Every Run logs:
- chosen `model_id`
- any switches (as RunSteps)

## 10. Logging, Tracing, and Summaries ✅ IMPLEMENTED

**Implementation:** `RunStep` logging in `agent_execution_loop.py`, Raze structured logging throughout

### 10.1 Verbose Execution Log ✅
Every meaningful event becomes a `RunStep`:

- phase
- timestamp
- model_id
- tool name + args (redacted)
- tool outputs (truncated)
- file changes summary
- links to created PRs/artifacts

In addition, emit Raze structured logs keyed by `run_id`, `work_item_id`, `project_id`, `agent_id`.

**Real-Time Delivery (per COLLAB_SAAS_REQUIREMENTS.md):**
- RunSteps are pushed via WebSocket with < 100ms latency
- UI receives live updates without polling
- Reconnection is transparent (< 500ms recovery)

### 10.2 Concise Work Item Comment ⏳ PARTIAL
At completion (or failure), the agent posts:

- What was done
- What changed (files/PR)
- Verification/testing results
- Any blockers or follow-ups

## 11. MCP Tools (Planned Additions)

### 11.1 Work Items ✅ IMPLEMENTED

**Status**: **Fully implemented** - handlers, manifests, and MCP routing complete

**Implementation Details:**
- ✅ Handler implementations in `amprealize/mcp/handlers/work_item_execution_handlers.py` (452 lines)
  - `handle_execute()` - Start work item execution
  - `handle_execution_status()` - Get execution status
  - `handle_cancel_execution()` - Cancel active execution
  - `handle_provide_clarification()` - Provide clarification response
  - `handle_list_executions()` - List recent executions
- ✅ Tool definitions array `WORK_ITEM_EXECUTION_TOOLS` with JSON schemas
- ✅ Factory function `create_work_item_execution_handlers(service)`
- ✅ JSON tool manifests created in `mcp/tools/` directory:
  - `workItems.execute.json` ✅ Created (2175 bytes)
  - `workItems.executionStatus.json` ✅ Created (1868 bytes)
  - `workItems.cancelExecution.json` ✅ Created (1160 bytes)
  - `workItems.provideClarification.json` ✅ Created (1425 bytes)
  - `workItems.listExecutions.json` ✅ Created (2160 bytes)
- ✅ MCP server routing added to `amprealize/mcp_server.py` (lines 3105-3161)
  - Intelligent namespace split: execution tools vs board CRUD tools
  - Service factory method `work_item_execution_service()` (lines 693-722)
  - Async handler invocation with error handling

**Available via MCP Protocol:**
- `workItems.execute(work_item_id, org_id?, project_id, ...)` → Start GEP execution
- `workItems.executionStatus(work_item_id, org_id?, project_id)` → Get status with metrics
- `workItems.cancelExecution(work_item_id, org_id?, project_id, reason?)` → Cancel execution
- `workItems.provideClarification(work_item_id, org_id?, project_id, clarification_id, response)` → Provide clarification
- `workItems.listExecutions(org_id?, project_id, status?, limit?, offset?)` → List/filter executions

**REST API Parity** (also available):
- `POST /v1/work-items/{item_id}:execute` → `workItems.execute`
- `GET /v1/work-items/{item_id}/execution` → `workItems.executionStatus`
- `POST /v1/work-items/{item_id}:cancel` → `workItems.cancelExecution`
- `POST /v1/work-items/{item_id}:clarify` → `workItems.provideClarification`
- `GET /v1/executions` → `workItems.listExecutions`

**Board Management Tools** (separate from execution tools):
- ✅ `workItems.postComment(work_item_id, body)` — Posts comment to work item with author validation
- ✅ `workItems.moveToColumn(work_item_id, column_id | status_mapping)` — Moves item by column_id or status_mapping
- ✅ `workItems.listComments(work_item_id)` — Lists comments on a work item
- ✅ `workItems.create`, `workItems.get`, `workItems.list`, `workItems.update`, `workItems.delete`, `workItems.move` *(deprecated — use `workItems.moveToColumn`)*

> **Note**: Board management tools (create/get/list/update/delete/move/postComment/listComments) handle **kanban board CRUD operations** via BoardService. Execution tools (execute/executionStatus/cancelExecution/provideClarification/listExecutions) handle **GEP execution flows** via WorkItemExecutionService. MCP routing at lines 3158-3186 intelligently splits these namespaces.

### 11.2 Runs ✅ COMPLETE
Ensure RunService MCP manifests are fully wired:
- ✅ `runs.create`, `runs.get`, `runs.list` (via RunService)
- ✅ `runs.updateStatus` — Update only status of a run (convenience wrapper) (`mcp/tools/runs.updateStatus.json`)
- ✅ `runs.updateProgress` — Update run progress with steps (`mcp/tools/runs.updateProgress.json`)
- ✅ `runs.fetchLogs` — Fetch execution logs from Raze with cursor pagination (`mcp/tools/runs.fetchLogs.json`)
- ✅ `runs.cancel` — Cancel a run (`mcp/tools/runs.cancel.json`)
- ✅ `runs.complete` — Complete a run (`mcp/tools/runs.complete.json`)

**Implementation Notes (2026-01-12):**
- `runs.updateStatus` and `runs.fetchLogs` added to `amprealize/mcp_server.py` routing
- `RunLogsRequest`, `RunLogsResponse`, `RunLogEntry` contracts in `amprealize/run_contracts.py`
- `fetch_logs()` async method in `RunService` queries Raze with run_id filter
- REST parity: `PATCH /api/v1/runs/{id}/status` and `GET /api/v1/runs/{id}/logs`
- Both `MCPRunServiceAdapter` and `RestRunServiceAdapter` support new methods

### 11.3 Agent Interaction ✅ COMPLETE
Tools for agents to collaborate with other agents:
- ✅ `agents.delegate(agent_id, subtask, context) -> { delegated_run_id }` — Delegate a subtask to another agent and await result
- ✅ `agents.consult(agent_id, question, context) -> { response }` — Ask another agent for input without creating a full run
- ✅ `agents.handoff(agent_id, reason) -> { new_run_id }` — Transfer execution to another agent

**Implementation Notes (2025-01-15):**
- **Contracts**: `DelegationRequest/Response`, `ConsultationRequest/Response`, `HandoffRequest/Response` in `amprealize/agent_orchestrator_service.py`
- **Run linking**: Added `origin_run_id`, `delegation_id`, `handoff_from_run_id` fields to Run contracts in `amprealize/run_contracts.py`
- **Service methods**: `delegate_subtask()`, `consult_agent()`, `handoff_execution()` in `AgentOrchestratorService`
- **MCP tools**: `mcp/tools/agents.delegate.json`, `agents.consult.json`, `agents.handoff.json`
- **MCP adapters**: Extended `MCPAgentOrchestratorAdapter` with `delegate()`, `consult()`, `handoff()` methods
- **MCP routing**: Added routing in `amprealize/mcp_server.py` for `agents.delegate`, `agents.consult`, `agents.handoff`
- **REST endpoints**: `POST /api/v1/agents/{agent_id}:delegate`, `:consult`, `:handoff` in `amprealize/api.py`
- **REST adapter**: Created `RestAgentOrchestratorAdapter` in `amprealize/adapters.py`

**Design Decisions:**
- `wait_for_completion=true` default for delegate - simpler UX, blocks until subtask completes
- `MAX_CONSULTATION_DEPTH = 3` constant prevents infinite consultation recursion
- Handoff creates new run and terminates source run, transferring context/outputs optionally

### 11.4 Human Escalation ✅ COMPLETE
Tools for agents to request human involvement mid-execution:
- ✅ Clarification support via `workItems.provideClarification`
- ✅ `escalation.requestHelp(reason, context) -> { escalation_id, status, guidance? }` — Request human guidance (non-blocking, continues execution)
- ✅ `escalation.requestApproval(decision, options) -> { escalation_id, approved: bool, selected_option? }` — Block execution until human approves/rejects (1hr default timeout, configurable)
- ✅ `escalation.notifyBlocked(reason, blocker_details) -> { escalation_id, status }` — Notify human that execution is blocked

**Implementation Details (2025-01-17):**
- **Contracts** in `amprealize/agent_orchestrator_service.py`:
  - `EscalationType` enum: HELP, APPROVAL, BLOCKED
  - `EscalationStatus` enum: PENDING, RESOLVED, APPROVED, REJECTED, ACKNOWLEDGED, CANCELLED, EXPIRED
  - Dataclasses: `EscalationRequest`, `HelpRequest`, `HelpResponse`, `ApprovalOption`, `ApprovalRequest`, `ApprovalResponse`, `BlockedNotification`, `BlockedResponse`
- **Service Methods**: `request_help()`, `request_approval()`, `notify_blocked()`, `resolve_help()`, `resolve_approval()`, `acknowledge_blocked()`, `get_escalation()`, `list_pending_escalations()`
- **MCP Tool Manifests**: `mcp/tools/escalation.requestHelp.json`, `mcp/tools/escalation.requestApproval.json`, `mcp/tools/escalation.notifyBlocked.json`
- **MCP Routing**: Added `escalation.*` block in `amprealize/mcp_server.py`
- **Adapters**: `MCPEscalationAdapter` and `RestEscalationAdapter` in `amprealize/adapters.py`
- **REST Endpoints**: `/api/v1/escalations:help`, `:approval`, `:blocked`, `/{id}`, `/{id}:resolve`, `/{id}:approve`, `/{id}:reject`, `/{id}:acknowledge`
- **Notification Hooks**: Uses `packages/notify` via `set_notification_hook()` for delivery (hook interface ready, actual delivery TBD)
- **Timeout**: `DEFAULT_APPROVAL_TIMEOUT_SECONDS = 3600` (1 hour), configurable 60s-7days per request


### 11.5 File Operations ✅ COMPLETE
Tools for reading/writing project files:
- ✅ `ToolExecutor` with file operation support
- ✅ Write scope enforcement (`WriteTargetResolver`)
- ✅ `files.read(path, options?) -> { content }` — Read file from local path (`mcp/tools/files.read.json`, `amprealize/mcp/handlers/file_handlers.py`)
- ✅ `files.write(path, content, options?) -> { result }` — Write file per write_scope policy (`mcp/tools/files.write.json`)
- ✅ `files.delete(path, options?) -> { result }` — Delete file per write_scope policy (`mcp/tools/files.delete.json`)
- ✅ `files.diff(path, new_content) -> { diff }` — Preview changes before writing (`mcp/tools/files.diff.json`)
- ✅ `github.createPR(branch, title, body, files[]) -> { pr_url }` — Create PR with changes (`mcp/tools/github.createPR.json`, `amprealize/mcp/handlers/github_handlers.py`)
- ✅ `github.commitToBranch(branch, message, files[]) -> { commit_sha }` — Commit changes to branch (`mcp/tools/github.commitToBranch.json`)

**Implementation Notes (2025-01-15):**
- File handlers in `amprealize/mcp/handlers/file_handlers.py` (569 lines) - supports path security validation, line ranges, encoding
- GitHub service in `amprealize/services/github_service.py` (599 lines) - uses httpx for REST API, project-level tokens via `GitHubCredentialStore`
- GitHub handlers in `amprealize/mcp/handlers/github_handlers.py` (234 lines) - creates PRs and commits via GitHub's Git Data API
- MCP routing added to `amprealize/mcp_server.py` for `files.*` and `github.*` prefixes

**Test Coverage (2025-01-12):**
- Comprehensive test suite added: 32 tests total (18 file operations + 14 GitHub operations)
- File operations: `tests/test_file_operations_mcp.py` - covers read, write, delete, diff with security validation, line ranges, scope resolution
- GitHub operations: `tests/test_github_operations_mcp.py` - covers PR creation, branch commits, file change parsing, error handling
- All tests passing (100% pass rate) with proper mocking for external dependencies
- Tests marked with `@pytest.mark.unit` for fast execution without database/network dependencies

### 11.6 Config ✅ COMPLETE
- ✅ `MODEL_CATALOG` with model definitions (`amprealize/work_item_execution_contracts.py:107`)
- ✅ `CredentialStore.get_available_models()` in `work_item_execution_service.py`
- ✅ `config.getModelAvailability(project_id)` MCP tool:
  - Manifest: `mcp/tools/config.getModelAvailability.json`
  - Handler: `amprealize/mcp/handlers/config_handlers.py`
  - MCP routing: `config.*` block in `mcp_server.py`
- ✅ REST API endpoints:
  - `GET /api/v1/projects/{project_id}/models` — Project-specific model availability (supports both personal and org projects)
  - `GET /api/v1/config/models` — Platform-level model availability
- ✅ Features implemented:
  - Credential resolution order: project BYOK → org BYOK → platform
  - Optional pricing info (`include_pricing` param)
  - Provider filtering (`provider_filter` param)
  - BYOK indicator in response
- ✅ `config.listLLMConnectors`: Handler and JSON manifest complete

## 12. UI Expectations ✅ COMPLETE

> **Reference**: Must align with `COLLAB_SAAS_REQUIREMENTS.md` — the canonical UX requirements document.

**Implementation Status (2026-01-14):** Core execution UI is fully implemented:

| Component | Status | Location |
|-----------|--------|----------|
| **ExecutionStatusBadge** | ✅ Done | `packages/collab-client/src/components/execution/ExecutionStatusBadge.tsx` |
| **ExecutionStatusCard** | ✅ Done | `packages/collab-client/src/components/execution/ExecutionStatusCard.tsx` |
| **ExecutionTimeline** | ✅ Done | `packages/collab-client/src/components/execution/ExecutionTimeline.tsx` |
| **Work Item Card** | ✅ Done | `web-console/src/components/boards/BoardPage.tsx` |
| **Work Item Drawer** | ✅ Done | `web-console/src/components/boards/WorkItemDrawer.tsx` |
| **SSE Streaming** | ✅ Done | `web-console/src/api/executions.ts` (`useExecutionStream` hook) |
| **Start/Cancel Controls** | ✅ Done | Integrated in BoardPage + WorkItemDrawer |
| **Clarification UI** | ✅ Done | WorkItemDrawer with inline response input |

**Shared Components** (`@amprealize/collab-client`):
- `ExecutionStatusBadge` — State dot + label + phase pill + animated progress bar
- `ExecutionStatusCard` — Full status card with configurable actions
- `ExecutionTimeline` — Phase-grouped step list with filtering + collapse
- GPU-accelerated animations via `transform`/`opacity` (60fps compliant)

### 12.1 Performance Targets

| Metric | Target | Notes |
|--------|--------|-------|
| **Time to Interactive (TTI)** | < 1.5s | Faster than Figma (~2.5s) |
| **First Input Delay (FID)** | < 50ms | Better than Linear (~80ms) |
| **Animation Frame Rate** | 60fps constant | Non-negotiable |
| **Execution Status Latency** | < 100ms perceived | WebSocket push updates |
| **WebSocket Reconnection** | < 500ms | Transparent to user |

### 12.2 UX Qualities

All execution UI must embody these qualities:

1. **Extremely Fast** — Optimistic updates everywhere. Start button responds before server confirms.
2. **Floaty** — Smooth spring animations on state transitions (phase changes, status updates).
3. **Smooth** — 60fps animations, no jank, no layout shifts. GPU-accelerated transforms only.
4. **Responsive** — Instant feedback on every interaction (hover, press, focus states).
5. **Animated** — State changes are animated (150-300ms max), not instant. Use spring physics.
6. **Delightful** — Success states that celebrate. Error states that guide, not blame.

### 12.3 Animation System

```css
/* Core timing functions - Spring physics via cubic-bezier */
--ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);        /* Overshoot bounce */
--ease-spring-gentle: cubic-bezier(0.34, 1.2, 0.64, 1);  /* Subtle bounce */
--ease-out-expo: cubic-bezier(0.16, 1, 0.3, 1);          /* Fast out, smooth stop */

/* Duration scale */
--duration-instant: 100ms;   /* Micro-interactions (button press) */
--duration-fast: 150ms;      /* State changes (phase transition badge) */
--duration-normal: 250ms;    /* Transitions (card expand/collapse) */

/* GPU-accelerated properties ONLY */
/* ✅ Use: transform, opacity, filter */
/* ❌ Avoid: width, height, top, left, margin, padding */
```

### 12.4 Dual-User Paradigm (Agents + Humans)

The execution UI must support both AI agents and human users:

**Agent-Specific:**
- Batch operations — Agents may trigger many executions rapidly; UI must handle coalescing
- Presence at scale — With many concurrent agents, need aggregated/hierarchical views
- Audit trail — Every agent action visible in execution log

**Human-Specific:**
- Visual presence — Humans see who (agent or human) started/owns each execution
- Override controls — Humans can pause/cancel agent-initiated executions
- Activity awareness — Agent activity visible without overwhelming the UI

### 12.5 Work Item Card Components

- **Assigned Agent Badge** — Shows agent name, avatar, model being used
- **Start Button** — Only visible if:
  - Assigned agent exists
  - No active run in progress
  - User has execute permission
- **Execution Status Indicator** — Real-time phase + status with animated transitions:
  - Phase pill (PLANNING → EXECUTING → VERIFYING, etc.)
  - Status badge (running/paused/blocked/completed/failed)
  - Progress indicator (animated spinner or determinate progress)
- **Execution Log Link** — Opens detailed step-by-step trace panel
- **PR Link** — If write target includes PR, link to GitHub PR
- **Cancel Button** — Visible during active execution (with confirmation)
- **Clarification UI** — Inline prompt when agent needs human input

### 12.6 Execution Log Panel

The execution log panel shows verbose step-by-step trace:

- **Timeline View** — Vertical timeline of RunSteps with timestamps
- **Phase Grouping** — Steps grouped by GEP phase with collapsible sections
- **Step Details** — Each step shows:
  - Tool name + truncated args
  - Output preview (expandable)
  - Duration + token count
  - Model used (if LLM call)
- **Live Updates** — New steps animate in via WebSocket push
- **WebSocket Stream** — `/api/v1/executions/ws` with `execution.status` + `execution.step` events (run or project scoped)
- **Filtering** — Filter by phase, tool type, status

### 12.7 Cross-Surface Parity

Per `COLLAB_SAAS_REQUIREMENTS.md`, execution UI must work identically on:

| Surface | Implementation | Notes |
|---------|----------------|-------|
| **Web Console** | React components using `@amprealize/collab-client` | Full feature set |
| **VS Code Webview** | Same React components | Identical to web |
| **VS Code Extension** | Tree providers + status bar | Simplified view |

Shared components (work item card, execution log, status indicators) MUST live in `@amprealize/collab-client` package.

## 13. Implementation Milestones

### Milestone 1: Execute Work Item (Local-only) ✅ COMPLETE

**Status**: Fully implemented including MCP integration

**✅ Completed Components:**
- ✅ Implement WorkItemExecutionService + AgentExecutionLoop + AgentLLMClient (1358 lines total)
- ✅ Persist verbose logs and post concise summary comment
- ✅ Move to Completed column on success
- ✅ REST API endpoints (7 endpoints, 566 lines)
  - `POST /v1/work-items/{item_id}:execute` - Start execution
  - `GET /v1/work-items/{item_id}/execution` - Get execution status
  - `POST /v1/work-items/{item_id}:cancel` - Cancel execution
  - `POST /v1/work-items/{item_id}:clarify` - Provide clarification
  - `GET /v1/executions` - List executions
  - `GET /v1/executions/{execution_id}` - Get execution details
  - `GET /v1/executions/{execution_id}/steps` - Get execution steps
- ✅ Service methods with error handling
  - `WorkItemExecutionService.execute()` - Orchestrates work item execution
  - `WorkItemExecutionService.get_status()` - Returns execution status
  - `WorkItemExecutionService.cancel()` - Cancels active execution
  - `WorkItemExecutionService.provide_clarification()` - Handles user clarification flow
  - `WorkItemExecutionService.list_executions()` - Lists execution history
  - `WorkItemExecutionService.get_execution_by_run_id()` - Gets execution details
  - `WorkItemExecutionService.get_execution_steps()` - Gets step-by-step trace
- ✅ `AgentExecutionLoop.run()` - Drives phase-by-phase execution
- ✅ Phase handlers for all 8 GEP phases (PLANNING through COMPLETING)
- ✅ `AgentLLMClient` with multi-provider support (Anthropic, OpenAI, OpenRouter, Local)
- ✅ Comprehensive exception types
  - `WorkItemNotAssignedError`, `AgentNotFoundError`, `ExecutionAlreadyActiveError`
  - `ModelNotAvailableError`, `InternetAccessDeniedError`, `WorkItemExecutionError`
- ✅ MCP tool handlers wired to `mcp_server.py` (lines 3158-3186)
- ✅ 5 JSON tool manifests created in `mcp/tools/`:
  - `workItems.execute.json`
  - `workItems.executionStatus.json`
  - `workItems.cancelExecution.json`
  - `workItems.provideClarification.json`
  - `workItems.listExecutions.json`

### Milestone 2: PR write target ✅ COMPLETE

#### 2.1 Execution Surface Enforcement ✅ COMPLETE
- ✅ Add `execution_mode` to project settings schema (`local` | `github_pr` | `local_and_pr`)
  - Added `ExecutionMode` enum in `amprealize/multi_tenant/settings.py`
  - Added `execution_mode` field to `ProjectSettings` model with `github_pr` default
  - Added `LOCAL_CAPABLE_SURFACES` and `REMOTE_ONLY_SURFACES` constants
- ✅ Update `WriteTargetResolver` to query project settings from DB
  - Injected `SettingsService` dependency
  - Maps `ExecutionMode` → `WriteScope`
  - Added `validate_surface_for_mode()` method
- ✅ Add surface detection in `WorkItemExecutionService.execute()`
  - Added `actor_surface` field to `ExecuteWorkItemRequest` dataclass
  - Added Step 5.5 surface enforcement check before model resolution
  - Creates `ExecutionSurfaceRestrictedError` with actionable guidance
- ✅ Return error with guidance when web UI tries to use local mode
  - New `ExecutionSurfaceRestrictedError` exception with `message` + `guidance`
  - MCP handler returns `error: "execution_surface_restricted"` with guidance
- ✅ Add UI messaging: "Local operations require VS Code extension"
  - Added `execution_mode` dropdown to VS Code `ProjectSettingsPanel`
  - Shows contextual warning cards for local modes
- ✅ Alembic migration for existing projects: `20260114_add_execution_mode_to_projects.py`

#### 2.2 BYOK GitHub Tokens ✅ COMPLETE
- ✅ Create `credentials.github_credentials` table (`migrations/versions/20260114_add_github_credentials.py`)
- ✅ Implement `GitHubCredentialRepository` (`amprealize/auth/github_credential_repository.py`)
- ✅ Create `GitHubCredentialStore` with resolution order: project → org → platform (`amprealize/services/github_service.py:102`)
- ✅ REST endpoints for GitHub credential CRUD (10 endpoints in `amprealize/api.py`):
  - `POST /api/v1/projects/{id}/github-credential`
  - `GET /api/v1/projects/{id}/github-credential`
  - `DELETE /api/v1/projects/{id}/github-credential`
  - `POST /api/v1/projects/{id}/github-credential:re-enable`
  - `GET /api/v1/projects/{id}/github-credential/audit`
  - `POST /api/v1/orgs/{id}/github-credential`
  - `GET /api/v1/orgs/{id}/github-credential`
  - `DELETE /api/v1/orgs/{id}/github-credential`
  - `POST /api/v1/orgs/{id}/github-credential:re-enable`
  - `GET /api/v1/orgs/{id}/github-credential/audit`
- ✅ Token validation (test GitHub API on save)
- ✅ Audit logging via `auth.github_credential_audit_log` table

#### 2.3 Branch Naming & PR Creation ✅ COMPLETE
- ✅ Implement branch naming: `amprealize/work-item-{id}-{timestamp}` in `generate_pr_branch_name()`
- ✅ Auto-create branch on first write in PR mode via `GitHubService.commit_to_branch(create_branch=True)`
- ✅ Accumulate file changes during execution phases via `PRExecutionContext.pending_changes`
- ✅ Create/update PR on execution completion via `AgentExecutionLoop._create_pull_request_if_needed()`
- ✅ Post PR link to work item comment via `WorkItemExecutionService._on_execution_complete(pr_url)`

**Implementation Files (2026-01-14):**
- `amprealize/work_item_execution_contracts.py`: `PRExecutionContext`, `PendingFileChange`, `PRCommitStrategy`, `generate_pr_branch_name()`
- `amprealize/services/github_service.py`: `get_default_branch()`, `get_repo_info()`
- `amprealize/agent_execution_loop.py`: PR context integration, `_create_pull_request_if_needed()`, `_build_pr_body()`
- `amprealize/tool_executor.py`: File write interception in PR mode (`_is_pr_mode()`, `_should_write_locally()`)
- `amprealize/work_item_execution_service.py`: `_setup_pr_context()`, `_resolve_project_repo()`
- `tests/test_pr_creation_flow.py`: 23 unit tests covering branch naming, context, file changes, tool executor modes

#### 2.4 GitHub Integration in AgentExecutionLoop ✅ COMPLETE
- ✅ Add `PendingFileChanges` accumulator to execution context (`PRExecutionContext.pending_changes`)
- ✅ Hook into `ToolExecutor` file write operations (`_execute_locally()` interception)
- ✅ Batch commits at phase boundaries (configurable via `PRCommitStrategy`)
- ✅ Create PR with execution summary as body (`_build_pr_body()`)
- ✅ Handle PR update if execution runs multiple times (via `pr_number` tracking)

> **Note**: PR write mode now prioritized. Implementation started 2026-01-14.

### Milestone 2.5: Cloud IDE Integration 🔮 PLANNED
- 🔮 GitHub Codespaces extension/integration
- 🔮 Gitpod workspace integration
- 🔮 JetBrains Fleet plugin
- 🔮 Detection of cloud IDE environment
- 🔮 MCP server deployment in cloud IDE context

> **Status**: Design complete. Implementation deferred until core PR mode is working.

### Milestone 3: Model system + BYOK ✅ COMPLETE
- ✅ Implement `MODEL_CATALOG` with supported models (Claude Opus 4.5, Sonnet 4.5, GPT-5.2, GPT-4o, Claude 3.5 Sonnet)
- ✅ Implement `CredentialStore` with platform/org/project credential resolution
- ✅ `ModelAvailabilityResolver` logic (in `CredentialStore.get_credential_for_model`)
- ✅ Agent model policy support (`ModelPolicy` dataclass)
- ✅ DB persistence for BYOK credentials (`credentials.llm_credentials` table)
- ✅ Encryption via `CredentialEncryptionService` (Fernet, AWS KMS, Vault support)
- ✅ CRUD endpoints: 10 REST endpoints for org/project credential management
- ✅ Audit logging with `credentials.llm_credential_audit_log` table
- ✅ Failure tracking with auto-disable after consecutive 401/403 errors

### Milestone 4: Internet gating ✅ COMPLETE
- ✅ `InternetAccessPolicy` enum defined
- ✅ `InternetAccessResolver` class implemented
- ✅ Org/project internet toggle logic
- ✅ Enforcement at runtime in `AgentExecutionLoop`

## 14. Example: AI Researcher Work Item

Work Item:
- Title: “Create Process for AI Researcher Agent”
- Description: Given an article/research input, deeply summarize, assess benefit to Amprealize, and propose implementation details with honest critique.

Execution highlights:
- PLANNING: interpret request, define output structure, identify needed inputs (article link/file)
- CLARIFYING: ask for missing input only if required
- ARCHITECTING: internal plan (non-blocking for this agent)
- EXECUTING: retrieve article (if internet allowed), extract sections, produce objective summary + implementation mapping
- VERIFYING/COMPLETING: non-blocking; post summary comment and mark done

---

## 15. Codebase Audit Log

This section tracks discrepancies found between the plan and actual implementation.

### Audit: 2026-01-14

| Finding | Severity | Resolution |
|---------|----------|------------|
| **OpenRouterAdapter not implemented** | ⚠️ Medium | Marked as TODO in plan |
| **LocalAdapter not implemented** | ⚠️ Medium | Marked as TODO in plan |
| **PromptComposer not a separate class** | 🔵 Low | Updated plan - logic is inline |
| **Line numbers outdated** | 🔵 Low | Updated all line references |
| **credentials.github_credentials missing** | ✅ Done | Implemented in Milestone 2.2 |
| **File line counts updated** | 🔵 Low | Refreshed all file statistics |

**MCP Tool Manifest Count (217 total in `mcp/tools/`):**
- workItems.*.json: 14 tools (5 execution + 9 board management)
- runs.*.json: 8 tools
- agents.*.json: 11 tools
- escalation.*.json: 3 tools
- files.*.json: 4 tools
- github.*.json: 2 tools
- config.*.json: 1 tool
- Plus 174+ other domain tools
