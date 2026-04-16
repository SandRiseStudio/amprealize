# MCP Server Design – Metacognitive Behavior Handbook Platform

## 1. Overview
The Metacognitive Control Plane (MCP) server provides a contract-first integration point that keeps the platform UI, public API, CLI, and agent tooling in lockstep. It exposes behavior-handbook operations, run orchestration, compliance auditing, and reflection workflows through a consistent schema so every surface delivers the same capabilities and guardrails.

**Status:** ✅ **220 MCP tools available** – Works natively in VS Code Copilot Chat and Claude Desktop.

## 2. Objectives
- **Parity:** Ensure any capability offered in the platform UI or CLI is available through MCP tools and the public API by default.
- **Observability:** Capture structured telemetry for every command (request metadata, behaviors used, checklist status).
- **Extensibility:** Support partner agents and IDE extensions through well-typed schemas (JSON Schema + OpenAPI) and capability negotiation.
- **Security & Compliance:** Enforce auth, RBAC, and audit logging aligned with compliance requirements.
- **IDE Compatibility:** All tool schemas use fully-inlined JSON (no `$ref` dependencies) for VS Code Copilot Chat and Claude Desktop compatibility.

## 3. Core Capabilities
| Domain | MCP Tool / Endpoint | Description |
| --- | --- | --- |
| Behavior Management | `behaviors.search`, `behaviors.get`, `behaviors.createDraft`, `behaviors.update`, `behaviors.approve` | Discover, retrieve, submit, and govern handbook entries. |
| **BCI Retrieval** | `bci.retrieve`, `bci.retrieveHybrid`, `bci.rebuildIndex` | Retrieve Top-K behaviors via embedding similarity (BGE-M3 + FAISS), keyword matching, or hybrid re-ranking for behavior-conditioned inference. |
| **BCI Prompting** | `bci.composePrompt`, `bci.parseCitations`, `bci.validateCitations` | Format behavior-conditioned prompts, extract cited behavior names from model output, and validate citation compliance. |
| Run Orchestration | `runs.create`, `runs.updateStatus`, `runs.list`, `runs.fetchLogs` | Manage Strategist/Student/Teacher runs, progress updates, and telemetry. |
| Compliance | `compliance.checklistStatus`, `compliance.recordStep`, `compliance.auditTrail` | Enforce checklist adherence and expose immutable evidence. |
| Reflection & Suggestions | `reflections.submitTrace`, `reflections.suggestBehaviors` | Upload traces, trigger summarization, and propose new behaviors. |
| **Trace Analysis** | `traces.segment`, `traces.detectPatterns`, `traces.scoreReusability` | Parse CoT reasoning steps, identify recurring sub-procedures, score candidate behaviors for clarity/generality/reusability. |
| Analytics | `analytics.metrics`, `analytics.tokenSavings`, `analytics.behaviorUsage` | Surface adoption and efficiency metrics (behavior reuse %, token reduction, task completion, compliance coverage) used by dashboards. |
| Configuration | `config.get`, `config.update`, `config.listLLMConnectors` | Manage model connectors, embedding indices, and token budgets (admin-scoped). |
| Action Registry | `actions.create`, `actions.list`, `actions.replay`, `actions.get` | Record, inspect, and replay build actions to ensure reproducibility and parity. |
| Agent Reviews | `reviews.run`, `reviews.list`, `reviews.get` | Trigger cross-functional agent reviewers (Engineering, DX, Compliance, Product) and retrieve synthesized feedback for artifacts. |
| Agent Orchestration | `agents.assign`, `agents.switch`, `agents.status` | Select domain agents for runs, switch personas mid-execution, and expose assignment history with audit metadata. |
| Agent Authentication | `auth.ensureGrant`, `auth.listGrants`, `auth.revoke`, `auth.status` | Broker OAuth/OIDC flows, enforce policy decisions, and expose grant state for agents and tools. |
| **Project Management** | `projects.list`, `projects.create`, `projects.get`, `projects.update` | Manage projects within organizations for workstream organization. |
| **Organization Management** | `orgs.list`, `orgs.create`, `orgs.get`, `orgs.update` | Manage organizations, members, and settings. |
| **Board Management** | `boards.list`, `boards.create`, `boards.get`, `boards.update` | Kanban-style boards for work item tracking. |
| **Whiteboard (Brainstorm)** | `brainstorm.openWhiteboard`, `brainstorm.addIdea`, `brainstorm.summarizeBoard`, `brainstorm.closeSession` | Ephemeral collaborative tldraw canvas for brainstorm sessions. Rooms created via brainstorm agent only; live canvas evaporates on close, snapshots persist with raw `canvas_elements` JSONB. |
| **Whiteboard (Canvas)** | `whiteboard.createRoom`, `whiteboard.addShape`, `whiteboard.readCanvas`, `whiteboard.annotate` | Lower-level canvas operations for direct shape manipulation, canvas inspection, and annotation. Gated: `createRoom` requires `metadata.source == "brainstorm_bridge"`. |

## 4. Integration Surfaces
- **Platform UI (Web):** Uses REST/GraphQL façade deployed alongside MCP; feature flags ensure UI only exposes capabilities registered in MCP.
- **Public API:** Thin wrapper around MCP gRPC/HTTP endpoints with identical schemas; versioned routes (e.g., `/v1/behaviors`).
- **CLI:** Consumes the MCP SDK; commands (`amprealize plan`, `amprealize run`, `amprealize reflect`, `amprealize agents review`) call the same tools.
- **VS Code Copilot Chat:** ✅ **Works natively!** All 220 MCP tools can be invoked directly by name (e.g., `mcp_amprealize_projects_list`, `mcp_amprealize_behaviors_getfortask`).
- **Claude Desktop:** MCP tools available via Claude Desktop MCP integration.

## 5. Architecture
- **Transport:** Primary gRPC (for IDEs/CLI) with HTTP/JSON gateway; follows MCP capability negotiation (handshake with `listTools`).
- **Authentication & Authorization:** Central AgentAuthService handles OAuth/OIDC exchanges (auth code, device, OBO, client credentials), JIT consent, and RBAC/ABAC policy evaluation. Legacy PAT/device flows remain for backward compatibility.
- **Schema Management:** Source-of-truth OpenAPI + JSON Schema stored in `schema/` directory. MCP tool definitions generated from schemas; SDKs auto-generated (TypeScript, Python, Go).
- **Service Components:**
  - `BehaviorService` (Postgres + Vector index; performance targets and scaling plan in `RETRIEVAL_ENGINE_PERFORMANCE.md`).
  - `RunService` (Event-driven, persisting to unified run store).
  - `ComplianceService` (append-only audit log, WORM storage per `AUDIT_LOG_STORAGE.md`).
  - `ReflectionService` (queues traces to LLM reflection workers).
  - `MetricsService` (streams telemetry to warehouse and caches recent metrics).
  - `ActionService` (captures reproducible actions, links to artifacts, exposes replay state).
  - `AgentReviewService` (coordinates cross-functional agent runs, stores feedback summaries, records linked actions).
  - `AgentOrchestratorService` (maps domain agents to the Strategist → Teacher → Student pipeline, applies policy heuristics for switching, and emits telemetry about agent effectiveness).
  - `AgentAuthService` (token broker, policy engine, consent orchestration, telemetry + audit integration per `docs/AGENT_AUTH_ARCHITECTURE.md`).
  - **New Meta Algorithm Services (Milestone 2 Phase 1):**
    - `BehaviorRetriever` (hybrid retrieval: BGE-M3 embeddings + FAISS index + keyword matching; Top-K selection for BCI pipeline; latency <100ms P95).
    - `ReflectionService (Enhanced)` (trace reflection pipeline: CoT parsing, pattern detection, candidate behavior extraction; quality scoring rubric; approval workflow integration).
    - `TraceAnalysisService` (segments reasoning steps, detects recurring sub-procedures, scores reusability/clarity/generality; feeds ReflectionService).
    - `FineTuningService (Design Phase)` (BC-SFT pipeline: training corpus collection, LoRA/QLoRA configuration, Student model fine-tuning; benchmarking infrastructure).
- **Telemetry Pipeline:** Ingestion + warehouse path defined in `TELEMETRY_SCHEMA.md` (supports PRD metrics dashboards).
- **Secrets Management:** Client auth flows and SDK usage follow `SECRETS_MANAGEMENT_PLAN.md` (device flow, OS keychain storage, rotation).
- **Event Bus:** NATS or Kafka to emit `behavior.updated`, `run.statusChanged`, `compliance.stepRecorded`, enabling real-time UI updates and webhook integrations.

## 6. Parity Strategy
1. **Capability Matrix:** Maintain `docs/capability_matrix.md` mapping each feature to API route, MCP tool, CLI command, and UI surface. Update via PR for any new capability.
2. **Spec-First Development:** Define/modify schemas before implementation. Use contract tests across SDKs and UI clients.
3. **Shared SDKs:** Generate language SDKs from the same proto/OpenAPI definitions; CLI and web clients depend on these packages to prevent drift.
4. **Release Checklist:** New features require:
  - Capability matrix row in `docs/capability_matrix.md` updated with surfaces, parity status, and evidence links.
  - Schema update merged and versioned.
  - CLI command and UI components gated behind feature toggles until parity verified.
  - Automated parity test (CLI vs MCP vs REST) passing in CI.
5. **Observability Dashboards:** Monitor feature usage across surfaces; alert if any surface lags adoption (indicating parity issues).
6. **Versioning & Deprecation:** Semantic versioning for MCP APIs; backward-compatible changes only in minor versions. CLI and UI pinned to matching SDK versions.

## 7. Stdio Authentication Extension

### 7.1. Rationale

The [MCP Authorization specification (2025-11-25)](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization) defines an OAuth 2.1-based authorization flow for HTTP transports.  For **stdio transports** (the transport used by VS Code Copilot Chat, Claude Desktop, and the Amprealize CLI), the spec states:

> "Clients and servers using the Stdio transport **SHOULD NOT** follow this specification, and instead retrieve credentials from the environment."

Amprealize extends this guidance with two complementary mechanisms:

1. **Device-flow-as-tools** — interactive OAuth 2.0 Device Authorization Grant (RFC 8628) exposed as MCP tools for IDE contexts where a human is present.
2. **Environment-provided access token** — a pre-shared bearer token via `AMPREALIZE_ACCESS_TOKEN` for CI/CD, headless runners, and scripted automation.

### 7.2. Auth Tools (Device Flow)

For interactive stdio sessions (IDE, CLI), Amprealize exposes six `auth.*` MCP tools that drive a Device Authorization Grant without requiring the MCP server to embed an HTTP callback:

| Tool | Purpose |
|------|---------|
| `auth.deviceInit` | Start device code flow; returns `device_code`, `user_code`, `verification_uri`. |
| `auth.devicePoll` | Non-blocking poll for user approval; returns tokens on success. |
| `auth.deviceLogin` | Blocking convenience wrapper (init + poll loop). |
| `auth.authStatus` | Report current session state from stored tokens. |
| `auth.refreshToken` | Refresh an expired access token using a stored refresh token. |
| `auth.logout` | Clear stored tokens and optionally revoke on the server. |

These tools are in `PUBLIC_TOOLS` (no prior auth required) and `CORE_TOOLS` (always loaded regardless of tool-group activation).

**Session lifecycle:**

```
AMPREALIZE_ACCESS_TOKEN set?
  ├─ YES → _bootstrap_session_from_env_token() → session ready
  └─ NO
       ├─ auth.deviceInit → user approves → auth.devicePoll → session ready
       └─ MCP_RESTORE_SESSION_ON_STARTUP=true → restore from keychain/DB
```

After successful auth, an `MCPSessionContext` records `user_id`, `org_id`, `granted_scopes`, and `expires_at`.  Non-public tools check `session.is_authenticated` before executing.

### 7.3. Environment Token Bootstrap

For headless or CI/CD usage, set:

```bash
export AMPREALIZE_ACCESS_TOKEN="<bearer-token>"
# Optional:
export AMPREALIZE_USER_ID="ci-bot@example.com"             # skip token introspection
export AMPREALIZE_ACCESS_TOKEN_TTL_SECONDS="7200"           # override default 1h
```

On startup the MCP server checks `AMPREALIZE_ACCESS_TOKEN` **before** any device-flow or token-store restore.  If present, it:

1. Populates `MCPSessionContext` with `auth_method`, `expires_at`, and `user_id` (from `AMPREALIZE_USER_ID` or best-effort JWT `sub`/`email` decode).
2. Calls `_populate_authorization_context()` to resolve `is_admin`, `accessible_org_ids`, and `accessible_project_ids`.
3. Skips device-flow and token-store restore entirely.

> **Security note:** The token is never written to disk or echoed in tool results.  Rotate it by updating the environment variable and restarting the MCP server process.

### 7.4. Token Storage

Tokens obtained via the device flow are persisted across restarts:

| Backend | Selection | Location |
|---------|-----------|----------|
| **macOS Keychain** (default) | `keyring` available | Service: `amprealize.auth` |
| **File store** | `AMPREALIZE_ALLOW_PLAINTEXT_TOKENS=1` | `~/.amprealize/auth_tokens.json` |
| **Custom path** | `AMPREALIZE_AUTH_TOKEN_PATH` | User-specified |

Multi-provider storage is supported via `auth_tokens_<provider>.json` files.

### 7.5. Spec Alignment

| MCP Spec Requirement | Amprealize Implementation |
|----------------------|---------------------------|
| Stdio: retrieve credentials from environment | `AMPREALIZE_ACCESS_TOKEN` env var bootstrap |
| OAuth 2.1 for HTTP transports | AgentAuthService (auth code, client credentials, OBO) |
| Dynamic Client Registration (MAY) | Supported via `auth.clientCredentials` |
| Token audience validation | Backend services validate audience claims |
| Short-lived tokens with refresh rotation | Default 1h access / 7d refresh; auto-rotation in `auth.refreshToken` |

## 8. Behavior-Conditioned Inference (BCI) Architecture

### 8.1. Overview
Per Meta's metacognitive reuse paper (see `Metacognitive_reuse.txt`), BCI reduces reasoning tokens by up to **46%** while maintaining or improving accuracy by retrieving relevant behaviors and prepending them to prompts. This section details the retrieval, prompting, and validation pipeline that delivers these token savings across the platform.

### 8.2. BCI Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│                         BCI Pipeline                             │
└─────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
    ┌──────────────────────────────────────────────────────────┐
    │  1. Query Analysis                                        │
    │     - Extract task keywords (topic, required reasoning)   │
    │     - Generate embedding for semantic search              │
    └──────────────────────────────────────────────────────────┘
                                   │
                                   ▼
    ┌──────────────────────────────────────────────────────────┐
    │  2. BehaviorRetriever                                     │
    │     - Hybrid retrieval: embedding similarity + keywords   │
    │     - Rank by relevance score                             │
    │     - Select Top-K behaviors (K=3-5 configurable)         │
    └──────────────────────────────────────────────────────────┘
                                   │
                                   ▼
    ┌──────────────────────────────────────────────────────────┐
    │  3. Prompt Composer                                       │
    │     - Format: "Relevant behaviors:\n- name: instruction"  │
    │     - Prepend to user query                               │
    │     - Add citation instruction                            │
    └──────────────────────────────────────────────────────────┘
                                   │
                                   ▼
    ┌──────────────────────────────────────────────────────────┐
    │  4. Model Inference                                       │
    │     - Pass conditioned prompt to LLM                      │
    │     - Model generates response with behavior citations    │
    └──────────────────────────────────────────────────────────┘
                                   │
                                   ▼
    ┌──────────────────────────────────────────────────────────┐
    │  5. Citation Parser & Validator                           │
    │     - Extract cited behavior names from output            │
    │     - Validate against prepended behaviors                │
    │     - Log to telemetry (fact_behavior_usage)              │
    └──────────────────────────────────────────────────────────┘
```

### 8.3. BehaviorRetriever Service

**Purpose:** Retrieve Top-K most relevant behaviors using hybrid retrieval (semantic embeddings + keyword matching).

**Technology Stack:**
- **Embedding Model:** BAAI/bge-m3 (BGE-M3) – 1024 dimensions, per Meta paper
- **Vector Index:** FAISS (IndexFlatIP for cosine similarity)
- **Library:** `sentence-transformers>=2.0`

**Performance Targets:**
- Retrieval latency: <100ms P95 (per `RETRIEVAL_ENGINE_PERFORMANCE.md`)
- Index rebuild: <5 seconds for 1000 behaviors
- Accuracy: Top-5 recall ≥85% on validation queries

**Retrieval Strategies:**

1. **Embedding Similarity** (primary):
   - Encode query with BGE-M3 model
   - FAISS nearest-neighbor search (cosine similarity)
   - Return Top-K by score

2. **Keyword Matching** (fallback):
   - Extract task keywords (topics, domains)
   - Match against behavior tags/categories
   - Used for MATH-500 topic-based retrieval

3. **Hybrid** (default):
   - Retrieve 2×K candidates via embedding
   - Re-rank using keyword overlap + recency
   - Select Top-K from re-ranked list

**MCP Tools:**
- `bci.retrieve(query, top_k=5, strategy="hybrid")` – Retrieve behaviors
- `bci.rebuildIndex()` – Rebuild FAISS index (admin-only)
- `bci.retrieveHybrid(query, embedding_weight=0.7, keyword_weight=0.3)` – Custom hybrid weighting

**Contracts:**
- `schema/bci/v1/retrieval.json` – Request/response schema for retrieval, hybrid weighting, and diagnostics payloads.
- `schema/bci/v1/prompt.json` – Prompt composition payloads including citation modes and batch formatting.
- `schema/bci/v1/citation.json` – Citation parsing, validation, and token savings calculations.
- `schema/bci/v1/trace.json` – Trace segmentation, pattern detection, and reusability scoring definitions.

### 8.4. Prompt Composer

**Purpose:** Format behavior-conditioned prompts that instruct the model to cite behaviors explicitly.

**Prompt Template:**
```
Relevant behaviors from the handbook:
- behavior_name_1: One-line instruction for behavior 1
- behavior_name_2: One-line instruction for behavior 2
- behavior_name_3: One-line instruction for behavior 3

When solving the task below, reference these behaviors by name when you apply them (e.g., "Following behavior_name_1, I will...").

Task:
{user_query}
```

**Configuration:**
- `max_behaviors`: Default 5, configurable per run
- `citation_instruction`: Customizable instruction text
- `format`: "list" (default) | "prose" | "structured"

**MCP Tools:**
- `bci.composePrompt(query, behaviors, citation_mode="explicit")` – Format conditioned prompt
- `bci.composeBatchPrompts(queries, behaviors_per_query)` – Batch formatting

### 8.5. Citation Parser & Validator

**Purpose:** Extract and validate behavior citations from model output to measure compliance and behavior usage.

**Citation Patterns:**
- Explicit: `"Following behavior_unify_execution_records, I will..."`
- Implicit: `"Using the execution record unification pattern..."`
- Inline: `"(behavior_externalize_configuration)"`

**Validation Rules:**
- Citation must reference a behavior that was prepended to the prompt
- At least one citation required for BCI compliance (95% target)
- Invalid citations logged as warnings, not errors

**Telemetry Integration:**
- Emit `fact_behavior_usage` events with:
  - `run_id`, `behavior_id`, `citation_type` (explicit/implicit/inline)
  - `token_savings` (estimated vs baseline)
  - `timestamp`, `agent_role` (Strategist/Teacher/Student)

**MCP Tools:**
- `bci.parseCitations(output_text)` – Extract cited behavior names
- `bci.validateCitations(output_text, prepended_behaviors)` – Check compliance
- `bci.computeTokenSavings(baseline_tokens, bci_tokens)` – Calculate savings

### 8.6. Trace Analysis Service

**Purpose:** Segment reasoning traces, detect recurring patterns, and score candidate behaviors for reflection pipeline.

**Capabilities:**
- **Step Segmentation:** Parse CoT traces into discrete reasoning steps
- **Pattern Detection:** Identify sub-procedures used ≥2 times across traces
- **Reusability Scoring:** Rate candidates on clarity, generality, applicability

**Scoring Rubric:**
| Dimension | Weight | Criteria |
|-----------|--------|----------|
| Clarity | 0.3 | Single-sentence instruction, no ambiguity |
| Generality | 0.3 | Applies across ≥3 domains or task types |
| Reusability | 0.25 | Observed in ≥2 traces or cited by Strategist |
| Correctness | 0.15 | Steps led to correct solution in original trace |

**MCP Tools:**
- `traces.segment(trace_text)` – Parse into steps
- `traces.detectPatterns(traces)` – Find recurring sub-procedures
- `traces.scoreReusability(candidate_behavior)` – Return 0-100 score

### 8.7. Integration with Existing Services

**BehaviorService:**
- BehaviorRetriever reads from `behaviors` table via BehaviorService API
- Index rebuild triggered on `behavior.approved` events
- Versioning ensures retrieval uses latest approved behaviors

**RunService:**
- BCI toggle per run: `use_bci=True/False`
- Retrieved behaviors stored in run metadata
- Token counts tracked separately for baseline vs BCI

**MetricsService:**
- Aggregates behavior usage across runs
- Computes reuse rate: `(runs with ≥1 citation) / total runs`
- Token savings dashboard: `(baseline_tokens - bci_tokens) / baseline_tokens`

**ComplianceService:**
- Citation compliance tracked per run
- Audit trail includes prepended behaviors and parsed citations
- Alerts when compliance drops below 95% threshold

### 8.8. Parity Across Surfaces

**Web UI:**
- Behavior retrieval preview in Plan Composer
- Citation highlights in execution logs
- Token savings chart on run detail page

**CLI:**
- `amprealize run --bci --top-k=5` – Enable BCI with custom K
- `amprealize bci rebuild-index` – Force index rebuild
- `amprealize bci test-retrieval "query"` – Test retrieval locally

**API:**
- `POST /v1/bci/retrieve` – Retrieve behaviors
- `POST /v1/runs` with `bci_config` – Create BCI-enabled run
- `GET /v1/analytics/token-savings` – Aggregate savings

**MCP Tools:**
- All `bci.*` tools available to IDEs and agents
- Parity validated via contract tests in Phase 1

### 8.9. Performance & Scalability

**Latency Budget:**
- Query embedding: <50ms
- FAISS search: <30ms
- Re-ranking: <20ms
- **Total retrieval: <100ms P95**

**Index Scaling:**
- 1000 behaviors: In-memory FAISS (≈100MB)
- 10,000 behaviors: Quantized FAISS (IVF index)
- 100,000+ behaviors: Distributed vector DB (Milvus/Weaviate)

**Caching Strategy:**
- Cache Top-K for frequent queries (TTL 1 hour)
- Invalidate on behavior updates
- LRU eviction for memory management

### 8.10. Metrics & Success Targets

Per `PRD.md` and `BCI_IMPLEMENTATION_SPEC.md`:

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| Token reduction | 46% | TBD | Milestone 2 Phase 1 |
| Behavior reuse rate | 70% | TBD | Milestone 2 Phase 1 |
| Accuracy preservation | ≥100% | TBD | Validation required |
| Retrieval latency | <100ms P95 | TBD | Infrastructure ready |
| Citation compliance | 95% | TBD | Parser implemented |

**Measurement Plan:**
- Baseline runs: Execute tasks without BCI (current behavior)
- BCI runs: Same tasks with Top-K behaviors prepended
- Compare: Output tokens, accuracy, latency, citation rate
- Dashboard: Real-time metrics in `analytics.tokenSavings` endpoint

## 9. Security & Compliance Considerations
- Enforce least-privilege scopes (e.g., `behavior.write`, `run.execute`, `compliance.review`).
- Tokenized audit entries with cryptographic signatures to ensure tamper evidence.
- Secrets never transmitted in clear text; configuration updates require dual control for production environments.
- Require every tool execution to pass through `auth.ensureGrant` decisioning, emitting telemetry for grants, denials, and JIT consent prompts.
- Rate limiting and anomaly detection to prevent abuse by automated agents.

## 10. Implementation Phases
1. **Phase 0 – Contracts (2 weeks):** Draft schemas, capability matrix, scaffold gRPC/HTTP services, generate SDKs.
2. **Phase 1 – Behavior, Run & Action Tools (4 weeks):** Implement behavior/run domains, stand up `ActionService`, and integrate CLI + UI read/write parity for action capture.
3. **Phase 2 – Compliance & Reflection (4 weeks):** Add checklist enforcement, trace submission, and ensure actions reference compliance evidence.
4. **Phase 3 – Analytics & Admin (3 weeks):** Deliver metrics endpoints, configuration management, parity tests, and action replay reporting.
5. **Phase 4 – Harden & Scale (3 weeks):** Load testing, security review, release workflow, documentation.

## 11. Open Questions
- Do we provide tenant-level isolation per MCP server instance or enforce isolation within a multi-tenant deployment?
- Should reflection suggestions trigger automatic behavior drafts, or stay manual for initial release?
- What is the minimum offline support required for CLI usage (queued operations when disconnected)?
- How do we expose parity compliance reports to customers (self-serve vs internal only)?

## 12. Next Steps
- Create capability matrix doc and integrate into `PRD_NEXT_STEPS.md` tracking.
- Align with infrastructure team on event bus selection and audit log storage.
- Kick off Phase 0 contract work, ensuring agent playbooks reference MCP parity requirements when reviewing future changes.
- Define `ActionService` schemas (action record, replay job) and publish draft CLI/API specs for review.
