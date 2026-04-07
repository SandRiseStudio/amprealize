# Metacognitive Behavior Handbook Platform – Product Requirements Document

## Document Control
- **Status:** Milestone 1 In Progress – Parity audit completed; analytics CLI live, REST/MCP & IDE follow-ups pending
- **Date:** 2025-10-16
- **Last Updated:** 2025-10-24
- **Author(s):** Product & AI Enablement Team
- **Stakeholders:** Engineering, Developer Experience, Developer Productivity, Security & Compliance, Customer Success

## Background
The platform is inspired by Meta AI's "Metacognitive Reuse" work, which demonstrates how compressing repeated reasoning into reusable "behaviors" can cut reasoning token usage by up to 46% and raise accuracy in math benchmarks. Internally, we have begun dogfooding the approach through `AGENTS.md` and `agent-compliance-checklist.md`, but adoption remains inconsistent and manual. We need to productize the handbook concept so teams can reliably discover, apply, and evolve behaviors across tools (platform UI, CLI, VS Code) while preserving auditability.

## Current Status (2025-10-16)
**Milestone 0 – Foundations: COMPLETE** ✅
**Milestone 1 – Internal Alpha: PRIMARY DELIVERABLES COMPLETE** ✅

The platform has successfully completed Milestone 0 foundations and all four primary Milestone 1 deliverables:

### Parity Audit Summary (2025-10-16)
- Conducted cross-surface parity audit across 12 capabilities; evidence captured in `docs/SURFACE_PARITY_AUDIT_2025-10-16.md`.
- CLI now includes the analytics projector command (`amprealize analytics project-kpi`) with passing regression tests, while REST API and MCP surfaces remain unimplemented for analytics.
- REST adapters exist for behaviors, workflows, compliance, actions, and tasks, yet no HTTP endpoints are wired, leaving web console integration blocked.
- VS Code extension delivers behavior browsing and workflow execution but lacks compliance review, action replay, and analytics panels.
- Capability matrix refreshed on 2025-10-16 to capture status deltas and outstanding MCP manifest work (`docs/capability_matrix.md`).

### Milestone 1 Completed Deliverables

#### VS Code Extension MVP ✅ (DX + Engineering)
**Status:** Validated in runtime with live services, ready for user testing
- **Implementation:** 11 TypeScript source files (~1,100 lines), 2 tree views, 2 webview panels, 7 commands, 4 settings
- **Features:**
  - **Behavior Handbook Sidebar:** Role-based hierarchy (Strategist/Teacher/Student), search, one-click insertion into editor
  - **Workflow Templates Explorer:** Role-grouped template listing with automatic refresh
  - **Behavior Detail Panel:** Rich webview displaying instructions, examples, metadata, version history
  - **Plan Composer:** Template selection UI, behavior injection workflow, run execution with status notifications
  - **AmprealizeClient:** Subprocess bridge to amprealize CLI with JSON communication and telemetry emission
- **Validation:** Extension tested in Extension Development Host; all views functional with live BehaviorService/WorkflowService data
- **Build:** Webpack compilation successful (56 KiB bundle, 0 errors, 0 vulnerabilities), ESLint configured and passing
- **Telemetry:** Instrumented behavior retrieval, workflow template loading, plan composer lifecycle events
- **Evidence:** `extension/`, `extension/MVP_COMPLETE.md`, `BUILD_TIMELINE.md` #41-42

#### BehaviorService Runtime ✅ (Engineering + Platform)
**Status:** SQLite backend with full CLI/REST/MCP parity operational
- **Implementation:** 720-line service with complete lifecycle support, CLI adapters, 9 subcommands
- **Operations:** create, list, search, get, update, submit, approve, deprecate, delete-draft
- **Parity:** 25 passing tests validating CLI/REST/MCP consistency across all operations
- **Lifecycle:** Draft → In Review → Approved → Deprecated with version management
- **Telemetry:** Instrumented for behavior CRUD, approval workflow, usage tracking
- **MCP Tools:** 9 tool manifests published (`mcp/tools/behaviors.*.json`)
- **Evidence:** `amprealize/behavior_service.py`, `tests/test_behavior_parity.py`, `mcp/tools/`, `BUILD_TIMELINE.md` #39

#### WorkflowService Foundation ✅ (Engineering + DX)
**Status:** SQLite backend with behavior-conditioned inference (BCI) operational
- **Implementation:** 600-line service with template CRUD and behavior injection logic, CLI adapters, 5 subcommands
- **Operations:** create-template, list-templates, get-template, run workflow, check status
- **Parity:** 35 passing tests (18 integration + 17 parity) validating CLI/REST/MCP equivalence
- **BCI Algorithm:** Runtime behavior injection into prompt templates with token accounting
- **Role Support:** Strategist/Teacher/Student execution patterns with example workflow
- **Telemetry:** Instrumented for template creation, run submission, status updates, token tracking
- **MCP Tools:** 5 tool manifests published (`mcp/tools/workflow.*.json`)
- **Evidence:** `amprealize/workflow_service.py`, `WORKFLOW_SERVICE_CONTRACT.md`, `tests/test_workflow_*.py`, `BUILD_TIMELINE.md` #40

#### Checklist Automation Engine ✅ (Engineering + Compliance)
**Status:** In-memory service with full CLI/REST/MCP parity operational
- **Implementation:** 350-line service with validation logic, CLI adapters, 5 subcommands
- **Operations:** create-checklist, record-step, list, get, validate with coverage scoring
- **Parity:** 17 passing tests validating CLI/REST/MCP consistency
- **Validation:** Automated checklist coverage scoring and gap detection
- **Telemetry:** Instrumented for checklist lifecycle, step recording, validation outcomes
- **Evidence:** `amprealize/compliance_service.py`, `COMPLIANCE_SERVICE_CONTRACT.md`, `tests/test_compliance_service_parity.py`, `BUILD_TIMELINE.md` #38

### Core Infrastructure (Milestone 0 - Complete)
- ✅ **ActionService & Adapters:** Full contract implementation with CLI/REST/MCP parity (`amprealize/action_service.py`, `amprealize/adapters.py`, `tests/test_action_service_parity.py`)
- ✅ **Agent Auth Phase A:** Complete contract artifacts including proto definitions, JSON schemas, scope catalog, policy bundles, MCP tool definitions, SDK stubs, and comprehensive test coverage
- ✅ **Telemetry Pipeline:** Cross-surface instrumentation for dashboard, ActionService, and AgentAuth with automated integration tests
- ✅ **Secret Scanning:** Pre-commit hooks, CI/CD integration, CLI commands, and MCP tools operational across all surfaces

### Documentation & Governance
- ✅ **13 Governance Playbooks:** Including Agent Auth Architecture, DevOps practices, Git strategy, behavior versioning, SDK scope, policy deployment, onboarding quickstarts, compliance control matrix, and consent UX prototypes
- ✅ **Capability Matrix:** Parity tracking across Web/API/CLI/MCP surfaces with release checklist hooks
- ✅ **Build Timeline:** 35 auditable actions with reproducible build documentation

### Security & Compliance
- ✅ **MFA Enforcement:** Policy-driven re-prompts for high-risk scopes (`actions.replay`, `agentauth.manage`)
- ✅ **Audit Infrastructure:** Immutable logging with evidence pipeline and compliance control matrix
- ✅ **Secrets Management:** Device flow, rotation policies, and leak prevention guardrails

### Analytics & Monitoring
- ✅ **Milestone Zero Dashboard:** Responsive Preact/Vite UI visualizing progress, timeline, and alignment
- ✅ **Consent/MFA Telemetry:** Event capture with dashboard integration and usability validation plan
- ✅ **Onboarding Metrics:** Time-to-first-behavior, checklist completion, and adoption tracking instrumented

### Testing & Quality
- ✅ **5 Test Suites:** Action service parity, agent auth contracts, CLI actions, secret scanning, telemetry integration
- ✅ **CI/CD Guardrails:** Automated pre-commit checks, secret scanning, tests, and builds across all PRs

### Epic E4 — Learning Loop, Analytics, and Governance (AMPREALIZE-278) ✅ COMPLETE
Delivered the full learning-loop, analytics, and governance layer spanning telemetry, auto-reflection, quality gates, feature flags, and backward-compatible pack migration.

#### Story 4.1 — Telemetry & Analytics
- ✅ **T4.1.1 Telemetry Schema Definitions:** Typed event payloads (`amprealize/telemetry_events.py`), JSON Schemas under `schema/telemetry/v1/`, 8 E4 domain events (pack.activated, pack.deactivated, pack.overlay_applied, bci.retrieval_completed, bci.injection_completed, bci.citation_validated, reflection.candidate_extracted, reflection.candidate_approved).
- ✅ **T4.1.2 Wire Telemetry into Services:** RuntimeInjector, BCIService, and ReflectionService emit structured events through FileTelemetrySink.
- ✅ **T4.1.3 Telemetry Query API:** CLI `amprealize telemetry query/dashboard`, MCP tools `telemetry.query`/`telemetry.dashboard`, parity test suite.

#### Story 4.2 — Behavior Learning Loop
- ✅ **T4.2.1 Auto-Reflection Trigger:** Post-run reflection pipeline gated by `feature.auto_reflection` flag via FeatureFlagService. Candidate extraction from execution traces with confidence scoring.
- ✅ **T4.2.2 Review Queue & MCP Tools:** Human-in-the-loop review queue for reflection candidates. MCP tools for listing, approving, and rejecting candidates. 24 parity tests.
- ✅ **T4.2.3 Lifecycle Policies:** Behavior deprecation, promotion, and decay policies. Automatic staleness detection and archival. 18 policy tests.

#### Story 4.3 — Quality Gates & Benchmarking
- ✅ **T4.3.1 Benchmark Task Corpus:** Domain-specific benchmark tasks with expected outcomes for regression testing. 28 corpus tests.
- ✅ **T4.3.2 Comparison Harness:** A/B evaluation of BCI-enabled vs baseline runs with statistical significance testing. Token savings measurement (target ≥30%). 25 harness tests.
- ✅ **T4.3.3 CI Quality Gates:** `QualityGateService` enforcing minimum accuracy, max regression, and token budget thresholds per domain. 31 gate tests.

#### Story 4.4 — Operational Readiness
- ✅ **T4.4.1 Feature Flags:** `FeatureFlagService` supporting BOOLEAN, PERCENTAGE (SHA-256 consistent hashing), and USER_LIST flag types. 7 default flags. MCP tools `flags.list`/`flags.get`/`flags.set`. 46 flag tests + 8 auto-reflection test fixes.
- ✅ **T4.4.2 Backward-Compat Migration:** Alembic migration for `feature_flags` table, `StorageBackend` detector (Postgres/SQLite/JSON/Unknown), `PackMigrationService` with bootstrap/rollback, CLI `amprealize pack bootstrap|rollback|status`, MCP tools `pack.bootstrap`/`pack.rollback`/`pack.status`. 29 migration tests.
- ✅ **T4.4.3 PRD & Operational Guide Updates:** This section and corresponding updates to MIGRATION_GUIDE.md, TELEMETRY_SCHEMA.md, capability_matrix.md, AGENTS.md, BUILD_TIMELINE.md.

**E4 Test Coverage:** 209 tests across 12 tasks (all passing).

**Next Focus (Milestone 1 → Milestone 2):** Production Flink deployment for real-time analytics, deliver REST API endpoints + MCP manifests for all shipped capabilities, expand the VS Code extension with compliance/action analytics views, migrate to PostgreSQL + vector index for production scale, and begin external beta planning.

### Future Enhancements – Agentic Postgres Alignment
- **MCP-native database playbooks:** Bundle a Amprealize-run MCP toolkit for Postgres administration (schema design, query tuning, migrations) so agents inherit the “master prompt” guardrails highlighted in Agentic Postgres while staying on our self-managed stack.
- **Hybrid search inside PostgreSQL:** Enrich the telemetry migration with BM25 + semantic extensions (e.g., pg_textsearch-style ranking alongside vector indices) to keep retrieval local to the warehouse and mirror the native search ergonomics described in the launch.
- **Instant forkable sandboxes:** Design copy-on-write database snapshots for behavior experiments and telemetry replay so Strategist and Student agents can spin up safe sandboxes without duplicating storage, echoing the fast fork workflow Tiger surfaced.

### Future Enhancements – Runtime Agent Orchestration
- **Agent Orchestrator service:** Introduce a dedicated service that maps domain agents (Engineering, Product, Finance, Security, etc.) onto the Strategist → Teacher → Student pipeline at run creation time. The orchestrator will select the appropriate domain behaviors, inject playbook-specific prompts, and record which agent persona executed each step for auditability.
- **Dynamic agent switching heuristics:** Implement policy- and telemetry-driven rules (e.g., task taxonomy, compliance tags, incident severity) so runs can transition between agents mid-execution while preserving cited behaviors and checklist requirements.
- **Surface parity:** Extend CLI/REST/MCP/IDE surfaces with `agent` selectors (e.g., `--agent engineering`, “Run as Finance Agent”) so users can request or override agent assignments, with fallback to default Strategist/Teacher/Student flows.
- **Instrumentation + governance:** Capture agent selection metrics (reuse %, token savings, completion rate by agent) and update `PRD_ALIGNMENT_LOG.md` / `PROGRESS_TRACKER.md` playbooks to reflect runtime orchestration evidence and review cadences across functional leads.

## Problem Statement
AI-assisted development teams repeatedly solve similar orchestration and remediation problems, causing long LLM traces, inconsistent outcomes, and weak institutional memory. Behavior handbooks exist but are siloed, hard to enforce, and unaudited. We need a product that operationalizes behavior discovery, retrieval, and compliance so that Strategist/Teacher/Student roles can collaborate efficiently and traceably.

## Vision
Deliver a connected platform that captures procedural knowledge, guides agents to reuse vetted behaviors, and makes compliance observable in every development surface (web, CLI, VS Code). The product should shorten reasoning traces, improve task success, and create a durable memory of high-quality workflows.

## Goals
1. **Increase behavior reuse:** 70% of assisted sessions reference at least one approved behavior by the end of public beta.
2. **Reduce token cost:** Average output tokens per complex remediation task drop by 30% compared to baseline traces.
3. **Improve success rate:** Completion rate for tracked engineering remediation tasks increases from 60% to 80%.
4. **Ensure auditability:** 95% of runs include compliance logs covering plan, execution, validation, and cited behaviors.

## Non-Goals
- Building proprietary LLMs; we rely on third-party APIs and prompt engineering.
- Replacing human review for production incidents; the platform augments but does not eliminate oversight.
- Managing declarative knowledge bases (classic RAG). Focus is procedural behaviors.

## Personas
1. **AI-Augmented Developer (Student role):** Executes tasks, needs actionable behavior prompts inside IDE/CLI.
2. **AI Strategist / Tech Lead:** Designs plans, curates behaviors, and monitors adoption.
3. **Teacher Agent / Prompt Author:** Crafts behavior-conditioned examples and ensures outputs cite behaviors.
4. **Compliance & Platform Admin:** Enforces standards, reviews new behaviors, audits logs.
5. **Knowledge Librarian (optional future role):** Manages large behavior corpora and taxonomy.

## User Stories
- As a developer, I retrieve relevant behaviors when drafting a remediation plan in VS Code and have the extension inject them into the prompt.
- As a strategist, I review traces post-task and convert novel steps into proposed behaviors through a reflection UI.
- As a compliance admin, I run a report showing which behaviors were cited over the last sprint and where the checklist was skipped.
- As a teacher agent, I author a prompt template that ensures every response references behavior IDs and validation steps.
- As a platform owner, I configure embeddings, storage backends, and token budgets for the behavior retriever.

## Scope
### In Scope (MVP + Beta)
- Unified behavior handbook service (CRUD, approval workflow, tagging, versioning).
- Retrieval service combining trigger keyword rules and embeddings (BGE-M3 + FAISS or equivalent).
- Strategist/Teacher/Student workflow tooling that references behaviors in plans, execution, and summaries.
- Compliance checklist enforcement and logging aligned with `agent-compliance-checklist.md`.
- Surfaced clients: minimal web console, CLI helper, VS Code extension.
- Analytics dashboards for adoption, token usage, and accuracy metrics.
- Behavior lifecycle management (draft → review → approved → deprecated).

### Out of Scope (for MVP)
- Native mobile apps.
- Automated fine-tuning pipeline (tracked as stretch goal).
- Marketplace for community behaviors (future consideration).

## Product Experience
### Core Platform (Web)
- **Behavior Library:** searchable list, filters (tags, roles, freshness), detail view with usage examples.
- **Reflection Inbox:** ingest traces, summarize, propose new behaviors with suggested names/instructions.
- **Compliance Dashboard:** displays checklist adherence, missing validations, and orphaned behaviors.
- **Run Explorer:** links strategist plans, student execution logs, and cited behaviors for each run.
- **Settings:** connectors for LLMs, embedding indices, storage backends, and auth.

### CLI Surface
- `amprealize plan`: prompts Strategist to cite behaviors; fails checklist if empty.
- `amprealize run`: executes tasks while logging validations and behavior usage.
- `amprealize reflect`: summarizes traces, proposes behaviors, and submits to review queue.
- Configurable hooks for CI/CD to ensure every PR references compliance logs.

### VS Code Extension
- **Behavior Sidebar:** search, pin, and inject behaviors into prompts or plans.
- **Plan Composer:** scaffolds Strategist/Teacher/Student sections referencing selected behaviors.
- **Execution Tracker:** displays commands run, validations, and outstanding checklist items.
- **Post-Task Review:** allows quick reflection to suggest new behaviors without leaving the IDE.

## Workflows
1. **Task Kickoff:** Strategist scans triggers, selects behaviors, drafts plan citing IDs. Checklist auto-logs step completion.
2. **Execution:** Student follows plan within CLI/IDE, logs commands and validation outcomes. Behaviors are referenced inline in responses.
3. **Reflection:** Teacher/Strategist reviews trace, uses reflection tooling to extract potential behaviors, submits for review.
4. **Compliance Review:** Admin verifies checklist completion, behavior usage, and approval status.

## Architecture Overview
- **Behavior Service:** stores metadata, instructions, embeddings, usage stats. Backed by Postgres + vector index (FAISS/Qdrant) with performance targets defined in `RETRIEVAL_ENGINE_PERFORMANCE.md`.
- **Retriever Engine:** hybrid search (keyword triggers + embeddings) with ranking heuristics.
- **Workflow Engine:** enforces Strategist/Teacher/Student templates and checklist requirements.
- **Telemetry Pipeline:** captures task logs, commands, token counts, validation results following the schema in `TELEMETRY_SCHEMA.md`.
- **Audit Log Storage:** immutable evidence pipeline outlined in `AUDIT_LOG_STORAGE.md`.
- **Secrets Management:** device login + rotation policies documented in `SECRETS_MANAGEMENT_PLAN.md`.
- **Agent Auth Service:** centralized OAuth/OIDC broker with just-in-time consent, policy enforcement, and audit integration per `docs/AGENT_AUTH_ARCHITECTURE.md`.
- **BreakerAmp Orchestrator:** single-front-door service that provisions, resumes, and retires all Amprealize test environments and data fixtures so clients never talk directly to pods, clusters, or queues.
- **Client Integrations:** web app (Next.js), CLI (Python Typer), VS Code extension (TypeScript). Shared SDK for authentication and API calls; see `docs/SDK_SCOPE.md` for supported languages, versioning, and distribution roadmap.
- **LLM Connectors:** plugable interface for OpenAI, Anthropic, local models; handles prompt templates for behavior-conditioned inference.

### BreakerAmp Infrastructure Orchestration
- **Purpose:** BreakerAmp replaces ad-hoc pod and cluster access with a documented, replayable API for provisioning, pausing, and disposing of all ephemeral testing and remediation environments. Every client surface (CLI, VS Code, MCP, API) must route infrastructure operations through BreakerAmp to keep audit evidence, quota tracking, and teardown guarantees consistent.
- **Scope:** Manages sandbox lifecycles (create, hydrate data, attach secrets, run health checks, retire), coordinates long-running integration suites, and owns the catalog of reusable environment blueprints (PostgreSQL, TimescaleDB, Redis, Flink, vector stores, telemetry warehouse mirrors, etc.). BreakerAmp is also responsible for publishing cost, capacity, and utilization metrics back into MetricsService.
- **Interfaces:**
  - `breakeramp.plan` – declares desired environment topology, compliance tier, and lifespan; returns a signed manifest recorded in ActionService for reproducibility.
  - `breakeramp.apply` – executes the manifest by calling Terraform runners, Kubernetes operators, or cloud APIs behind the scenes while streaming RunService status updates.
  - `breakeramp.status` / `breakeramp.destroy` – report lifecycle events, issue teardown commands, and emit completion evidence to ComplianceService and PROGRESS_TRACKER.
  - Device-flow friendly authentication so IDE users can request environments without having direct kubeconfig/cluster creds.
- **Contract Requirements:** No caller is allowed to reach pods, nodes, or queues directly; BreakerAmp enforces configuration policy, injects secrets via `SECRETS_MANAGEMENT_PLAN.md`, and logs every infrastructure mutation to the audit pipeline. The service must expose parity across Web/API/CLI/MCP and honor the Strategist → Teacher → Student workflow (e.g., Strategist drafts an BreakerAmp plan, Student executes, Teacher reviews evidence).
- **Telemetry:** Emits structured events (`breakeramp.plan.created`, `breakeramp.apply.started`, `breakeramp.apply.duration_ms`, `breakeramp.destroy.completed`) feeding the 70% behavior reuse / 30% token savings / 80% completion / 95% compliance metrics as well as new infrastructure KPIs (environment reuse %, average lifespan, teardown success rate).
- **Documentation-First Directive:** All new capabilities must land in this PRD, `PRD_NEXT_STEPS.md`, and `PRD_ALIGNMENT_LOG.md` before code merges; BreakerAmp changes also require updates to `ACTION_REGISTRY_SPEC.md` and CLI/MCP help so Strategist agents can reference the behavior handbook entries that govern infrastructure operations.

#### `scripts/run_tests.sh` Integration Requirements
- The `scripts/run_tests.sh` harness must treat BreakerAmp as the authoritative provisioner whenever `AMPREALIZE_TEST_INFRA_MODE=breakeramp` (default once Phase 1 ships). In this mode the script:
  - Calls `amprealize breakeramp plan --blueprint local-test-suite --lifetime ${RUN_TESTS_TTL:-90m}` before any Podman/Compose commands run, passing the checklist ID for the current run so ComplianceService can track evidence.
  - Uses the signed manifest returned by `breakeramp.plan` to invoke `amprealize breakeramp apply --manifest - --watch` instead of local `podman-compose` calls. BreakerAmp then stands up the telemetry warehouse, metrics DB, Redis, API server, and nginx stack that `run_tests.sh` previously started directly.
  - Reads the emitted `environment_outputs` blob (JSON) to export DSNs and host/port pairs (`AMPREALIZE_PG_HOST_*`, `AMPREALIZE_REDIS_HOST`, `STAGING_API_URL`, etc.) so downstream pytest runs continue to work without modification.
  - Polls `amprealize breakeramp status --run-id <amp_run_id>` until every dependency is healthy, mirroring the existing port checks, and streams status events into RunService for IDE/CLI parity.
  - Calls `amprealize breakeramp destroy --run-id <amp_run_id>` in a `trap` if the script provisioned the environment, guaranteeing teardown of ephemeral resources even when pytest fails.
- Because BreakerAmp replaces Podman-managed compose stacks, `run_tests.sh` must enforce the Podman memory guidance captured in `deployment/PODMAN.md`: stop any running Podman machine (`podman machine stop`) before provisioning to release the 4–8 GB Apple Virtualization (AppleHV) VM footprint, warn when `AMPREALIZE_TEST_INFRA_MODE=breakeramp` but Podman is still running, and document that engineers need to manually start the Podman VM (`podman machine start --cpus 4 --memory 4096`) only when opting into the legacy mode. This prevents macOS hosts from keeping two full stacks in memory and makes the AppleHV VM life cycle an explicit operator step rather than an implicit background process.
- When `AMPREALIZE_TEST_INFRA_MODE=legacy` (opt-in until BreakerAmp reaches GA), the script retains the current Podman bootstrap path. This provides backwards compatibility for engineers who cannot reach the orchestrator yet and satisfies the “standalone” requirement.
- Integration must remain hermetic: `run_tests.sh` never talks to pods/clusters directly in BreakerAmp mode, and all side effects (plan/apply/destroy/status) are logged via ActionService entries so replay is possible.

#### Standalone BreakerAmp CLI / Service Usage
- `amprealize breakeramp plan|apply|status|destroy` must function without the rest of the Amprealize repo so external projects can reuse the orchestrator. Requirements:
  - CLI accepts either inline JSON manifests (`--manifest -`) or file paths (`--manifest ./breakeramp/local-dev.yaml`) describing blueprints, secrets, and compliance tiers. Manifests reference catalog items published from Phase 2 (e.g., `postgres.timescale.test`, `redis.cache.basic`).
  - Authentication relies on the existing device flow from AgentAuthService; no local kube credentials are required. Token cache defaults to `~/.amprealize/breakeramp/credentials.json` for reuse across repos.
  - Outputs are written to `~/.amprealize/breakeramp/environments/<run_id>.json` so other tools (including `scripts/run_tests.sh`) can source DSNs without the Amprealize codebase.
  - REST, CLI, MCP, and upcoming VS Code panels expose identical parameters and status objects to maintain parity. Standalone users can therefore provision environments programmatically (CI pipelines, other repos) using the same manifests.
  - Standalone docs must restate the Podman/AppleHV memory guidance so that engineers treating BreakerAmp as a portable orchestrator know to stop the Podman VM before provisioning, reclaim the 4–8 GB footprint after teardown, and only restart it for legacy Compose scenarios.
- Action logging: every CLI invocation must emit `amprealize record-action --artifact ACTION_REGISTRY_SPEC.md --summary "breakeramp.{verb}" ...` entries referencing `behavior_wire_cli_to_orchestrator` and `behavior_update_docs_after_changes` so that infrastructure mutations remain auditable across standalone adopters.

## Data Model
- **Behavior:** id, name, trigger keywords, instruction, role focus, status, version, embedding vector, usage stats. `version` follows semantic versioning with lifecycle rules defined in `docs/BEHAVIOR_VERSIONING.md`; every run stores `(behavior_id, version)` for reproducibility.
- **Run:** id, task metadata, behaviors cited, plan, execution log, validation results, checklist flags.
- **Trace:** raw LLM output, associated run, tokens used, derived candidate behaviors.
- **Compliance Record:** checklist step, status, reviewer, timestamp, notes.

## Dependencies & Integrations
- Embedding model (BGE-M3 or alternative) with vector DB support.
- LLM APIs supporting long context (≥ 16k tokens) and tool-use metadata.
- Authentication (OAuth/SAML + AgentAuthService) for web; device/OBO/client-credential flows for CLI, IDE, and service agents.
- Telemetry sink (Snowflake/BigQuery) for analytics.

## Success Metrics

### Platform-Wide KPIs (aligned with PRD Goals)
1. **Behavior Reuse Rate:** 70% of assisted runs cite ≥1 approved behavior by end of public beta (Goal 1)
   - **Measurement:** `valid_citations_count > 0` / `total_runs` in `fact_behavior_usage` table
   - **Current Baseline:** ~10% manual citation (pre-BCI)
   - **Target Trajectory:** 30% by end of Milestone 2 Phase 1 (BCI deployed), 70% by GA

2. **Token Savings:** 30% average output token reduction vs. baseline unconditioned prompts (Goal 2)
   - **Measurement:** `(baseline_output_tokens - bci_output_tokens) / baseline_output_tokens × 100%`
   - **Research Validation:** Meta paper demonstrates 46% reduction on MATH-500; targeting 30% across diverse Amprealize workloads
   - **Target Trajectory:** 25% by end of Milestone 2 Phase 1 (initial BCI), 30% after prompt tuning, 35%+ stretch goal with BC-SFT

3. **Task Completion Rate:** 80% success rate for tracked remediation tasks (Goal 3)
   - **Measurement:** `completed_runs / total_runs` where `status=SUCCESS` in RunService
   - **Current Baseline:** ~60% (pre-BCI)
   - **Target Trajectory:** 70% by end of Milestone 2 Phase 1 (BCI + self-improvement), 80% by GA

4. **Compliance Coverage:** 95% of runs include audit logs with plan, execution, validation, and cited behaviors (Goal 4)
   - **Measurement:** `runs_with_complete_audit_trail / total_runs` in telemetry warehouse
   - **Current Baseline:** ~85% (checklist automation operational but not enforced in all surfaces)
   - **Target Trajectory:** 90% by end of Milestone 2 Phase 1, 95% by GA with VS Code Phase 2

### Meta Algorithm-Specific Metrics (Milestone 2 Phase 1)
5. **BCI Citation Compliance:** 95% of BCI-enabled runs emit parseable behavior citations
   - **Measurement:** `runs_with_valid_citations / bci_runs` where citations match prepended behaviors
   - **Validation:** Citation parser successfully extracts `behavior_*` references from model output

6. **Retrieval Latency:** P95 <100ms for Top-K behavior retrieval via BehaviorRetriever
   - **Measurement:** Telemetry event `bci.retrieval_complete.latency_ms` P95 percentile
   - **Tuning:** Optimize FAISS index (IVF + PQ) if latency exceeds target as handbook grows

7. **Behavior Extraction Rate:** ≥5 high-quality candidate behaviors extracted per 100 runs via ReflectionService
   - **Measurement:** `extracted_candidates / total_runs × 100`
   - **Quality Gate:** 80% approval rate for auto-extracted candidates (manual review)

8. **Self-Improvement Gain:** 10% accuracy improvement on revised runs vs. original failed attempts
   - **Measurement:** `(revised_success_rate - failed_task_baseline) / failed_task_baseline × 100%`
   - **Research Validation:** Meta paper shows 10% gains on AIME with behavior-guided self-correction

9. **BC-SFT Generalization (Milestone 3):** Student model accuracy ≥ baseline SFT on held-out behaviors
   - **Measurement:** Benchmark BC-SFT vs. baseline on MATH-500 + Amprealize validation set
   - **Target:** Match or exceed BCI accuracy while eliminating retrieval latency

### Operational Metrics (continuous monitoring)
10. **Handbook Growth:** Number of approved behaviors, submission rate, approval velocity
11. **Behavior Lifecycle:** Time in each state (draft → review → approved), deprecation rate
12. **User Adoption:** Active users per surface (Web/CLI/VS Code), session frequency, retention

## Release Plan
1. **Milestone 0 – Foundations (4 weeks):** ✅ **COMPLETE** – Stand up behavior service, manual retriever, basic CLI to log behaviors, publish Agent Auth architecture and scope catalog.
   - **Delivered:** ActionService contracts & stubs, Agent Auth Phase A (proto/schema/policy artifacts), secret scanning guardrails, CI/CD pipelines, telemetry instrumentation, compliance control matrix, SDK scope definition, behavior versioning strategy, Git/DevOps governance playbooks, policy deployment runbook, onboarding quickstarts, consent/MFA UX prototypes with validation plan, reproducible build documentation.
   - **Evidence:** 20+ completed work items tracked in `PROGRESS_TRACKER.md`, 35 timeline entries in `BUILD_TIMELINE.md`, full test coverage in `tests/`, contract artifacts in `proto/`, `schema/`, `policy/`, `mcp/tools/`.

2. **Milestone 1 – Internal Alpha (6 weeks):** ✅ **PRIMARY DELIVERABLES COMPLETE** – VS Code extension MVP validated in runtime, WorkflowService with BCI algorithm operational, BehaviorService with full lifecycle support deployed, checklist automation engine with parity testing complete, PRD KPI dashboards operational.
   - **Status:** All four primary deliverables shipped and validated. Analytics Phase 1-2-3 complete with operational dashboards visualizing PRD success metrics (behavior reuse, token savings, completion rate, compliance coverage). Metabase v0.48.0 deployed with DuckDB warehouse integration; all 4 dashboards created programmatically in ~10 seconds via REST API automation. Production Flink real-time pipeline remains as follow-up work.
   - **Delivered:**
     - **VS Code Extension MVP** – 11 TypeScript files, 2 tree views (Behavior Handbook + Workflow Explorer), 2 webview panels (Behavior Detail + Plan Composer), AmprealizeClient with telemetry, webpack build validated, runtime testing complete with live services. Features: role-based behavior browsing, search, one-click insertion, workflow template selection/execution, behavior injection UI. Evidence: `extension/`, `extension/MVP_COMPLETE.md`, `BUILD_TIMELINE.md` #41-42.
     - **BehaviorService Runtime** – SQLite-backed service with 720 lines, full lifecycle (create/list/search/get/update/submit/approve/deprecate/delete-draft), CLI/REST/MCP parity (25 passing tests), 9 MCP tool manifests, telemetry instrumentation. Evidence: `amprealize/behavior_service.py`, `tests/test_behavior_parity.py`, `mcp/tools/behaviors.*.json`, `BUILD_TIMELINE.md` #39.
     - **WorkflowService Foundation** – SQLite-backed service with 600 lines, template CRUD + BCI algorithm, CLI/REST/MCP parity (35 passing tests), 5 MCP tool manifests, role-specific execution patterns, token accounting, example Strategist workflow. Evidence: `amprealize/workflow_service.py`, `WORKFLOW_SERVICE_CONTRACT.md`, `tests/test_workflow_*.py`, `mcp/tools/workflow.*.json`, `BUILD_TIMELINE.md` #40.
     - **ComplianceService (Checklist Engine)** – In-memory service with 350 lines, create/record/list/get/validate operations, coverage scoring algorithm, CLI/REST/MCP parity (17 passing tests), telemetry integration. Evidence: `amprealize/compliance_service.py`, `COMPLIANCE_SERVICE_CONTRACT.md`, `tests/test_compliance_service_parity.py`, `BUILD_TIMELINE.md` #38.
     - **Telemetry Infrastructure** – FileTelemetrySink for JSONL persistence, CLI `telemetry emit` command, VS Code extension instrumentation (behavior retrieval, workflow loading, plan composer lifecycle), Python service event emission. Evidence: `amprealize/telemetry.py`, `amprealize/cli.py`, `extension/src/client/AmprealizeClient.ts`, `tests/test_telemetry_integration.py`, `BUILD_TIMELINE.md` #43.
     - **Analytics & Dashboards (Phase 1-2-3 Complete)** – DuckDB warehouse with 4 fact tables + 4 KPI views; Metabase v0.48.0 with SQLite export bridge; 4 operational dashboards with 18 cards created programmatically in ~10 seconds (75+ min time savings, 90% reduction vs manual); automation script (`scripts/create_metabase_dashboards.py` ~610 lines) and comprehensive guide (`docs/analytics/PROGRAMMATIC_DASHBOARD_CREATION.md`); REST API endpoints (`/v1/analytics/*`) with full parity; CLI analytics projector command. Dashboards: (1) PRD KPI Summary with 4 metric cards + KPI snapshot + run volume chart, (2) Behavior Usage Trends with usage summary + leaderboard + distribution, (3) Token Savings Analysis with savings summary + distribution + scatter + efficiency, (4) Compliance Coverage with coverage summary + checklist rankings + step completion + audit queue + distribution. All accessible at http://localhost:3000. Evidence: `BUILD_TIMELINE.md` #61-62-63-64, `PRD_ALIGNMENT_LOG.md` Phase 2-3 sections, `PROGRESS_TRACKER.md`, `docs/analytics/`, `scripts/create_metabase_dashboards.py`.
   - **Next:** Production Flink deployment for real-time analytics updates, PostgreSQL + vector index migration for BehaviorService, REST API endpoint exposure for remaining services, web console integration, VS Code analytics panel, external beta planning.

3. **Milestone 2 – External Beta (8 weeks):**

   ### Phase 1: Meta Algorithm Implementation (Weeks 1-8, **P0 Priority**)

   **Critical Discovery (2025-10-16):** Progress audit and Meta paper validation revealed Amprealize has excellent infrastructure (storage, orchestration, telemetry, 30 MCP manifests, 110 tests) but lacks the core Meta "Metacognitive Reuse" algorithm that delivers the PRD's value proposition. Current implementation provides handbook storage but not the retrieval, conditioning, and self-improvement mechanisms that achieve **46% token reduction** and **10% accuracy gains** demonstrated in the research. This phase implements the missing algorithm components before scaling infrastructure.

   **Success Criteria (aligned with PRD Goals):**
   - **Goal 1 (Behavior Reuse):** 70% of runs cite ≥1 behavior via BCI pipeline (up from current ~10% manual citation)
   - **Goal 2 (Token Savings):** 30% average output token reduction across assisted tasks (BCI delivers 46% on math benchmarks per Meta paper, target 30% across diverse workloads)
   - **Goal 3 (Completion Rate):** 80% task success rate maintained or improved with BCI (Meta paper shows BCI matches/exceeds baseline accuracy)
   - **Goal 4 (Auditability):** 95% citation compliance (parseable behavior references in BCI outputs)

   #### Component A: Behavior-Conditioned Inference (BCI) Pipeline (Weeks 1-2, P0)

   **Purpose:** Implement core BCI algorithm from Meta paper that retrieves Top-K relevant behaviors and prepends them to prompts, enabling 46% token reduction while maintaining accuracy.

   **Implementation:**
   - **BehaviorRetriever Class:**
     - Embedding-based retrieval using BGE-M3 model (1024-dim vectors, same as Meta paper AIME experiments)
     - FAISS IndexFlatIP for exact cosine similarity search (IndexIVFPQ when handbook exceeds 10K behaviors)
     - Hybrid retrieval strategy: embedding similarity (primary) + keyword matching (fallback) + re-ranking
     - Top-K selection algorithm (K=3-5 configurable, default 5)
     - Retrieval latency target: <100ms P95 for Top-5 queries
   - **Prompt Composer:**
     - Format: "Relevant behaviors:\n- behavior_name: instruction\n...\nPlease reference these behaviors explicitly when applicable.\n\nNow solve: {query}"
     - Token budget: ~150 input tokens for Top-5 behaviors (pre-computable, often billed cheaper than output tokens)
     - Ordering: Present in relevance rank order (highest score first)
   - **Citation Parser & Validator:**
     - Regex extraction of `behavior_*` references from model output
     - Validation: match cited behaviors against prepended behaviors
     - Compliance scoring: valid_citations / prepended_behaviors per run
     - Telemetry logging to `fact_behavior_usage` table for 70% reuse rate KPI
   - **Integration:**
     - Update `WorkflowService.run_with_bci()` to inject pipeline before LLM inference
     - CLI flag: `amprealize run --bci` with behavior citation output
     - MCP tool: `bci.retrieve` for programmatic access
     - VS Code: Auto-enable BCI for all plan executions via `amprealize:enableBCI` setting

   **Dependencies:**
   - Python packages: `sentence-transformers>=2.0` (BGE-M3), `faiss-cpu>=1.7` (FAISS index), `torch>=2.0` (PyTorch backend)
   - BGE-M3 model download: ~2GB (auto-downloads to `~/.cache/torch/sentence_transformers/`)
   - FAISS index storage: ~4MB per 1000 behaviors (400KB for current 100 behaviors)

   **Validation:**
   - A/B testing framework: BCI vs baseline prompts on 100+ validation tasks
   - Measure: token reduction (target ≥40%, aiming for 46%), accuracy preservation (BCI/baseline ≥1.0), reuse rate (≥70%)
   - Tune Top-K parameter (test K=3, 5, 7, 10) for optimal token/accuracy tradeoff

   **Evidence:**
   - Technical spec: `docs/BCI_IMPLEMENTATION_SPEC.md` (complete)
   - Code: `amprealize/behavior_retriever.py`, updated `amprealize/workflow_service.py`
   - Tests: `tests/test_bci_pipeline.py`, `tests/test_bci_parity.py`
   - MCP manifest: `mcp/tools/bci.retrieve.json`
   - Dashboard: Token savings chart, behavior reuse heatmap (wire to DuckDB warehouse)

   #### Component B: Automated Behavior Extraction (Weeks 3-4, P0)

   **Purpose:** Implement reflection pipeline that automatically extracts reusable behaviors from completed traces, eliminating manual curation bottleneck and enabling handbook growth at scale.

   **Implementation:**
   - **ReflectionService:**
     - `reflect(trace, run_id)`: Analyze CoT trace with reflection prompt (based on Meta paper Strategist role)
     - Identify recurring patterns, sub-procedures, and generalizable steps
     - Generate candidate behaviors with: `name` (verb_noun format), `instruction` (one-line how-to), `examples` (extracted from trace), `quality_scores` (reusability 0-1, clarity 0-1, generality 0-1)
     - Validation rules: Check duplicates in handbook, require quality_scores > 0.7 threshold
     - Approval workflow: Human-in-loop for candidate review before adding to handbook
   - **TraceAnalysisService:**
     - `parse_cot_trace(output)`: Segment reasoning into discrete steps
     - `detect_patterns(steps)`: Identify repeated sub-procedures across multiple traces
     - `score_reusability(pattern)`: Calculate frequency, token savings potential, cross-task applicability
   - **Integration:**
     - CLI: `amprealize reflect <run_id>` extracts behaviors from completed run
     - MCP tool: `reflection.extract` for automated post-run reflection
     - VS Code: "Extract Behaviors" button in Plan Composer after run completion
     - Scheduled job: Nightly reflection on previous day's runs (batch mode)

   **Dependencies:**
   - Reflection prompt template: Adaptation of Meta paper Strategist prompts for extraction
   - LLM API: Same model used for BCI inference (consistency)
   - BehaviorService: Draft submission API for candidate behaviors

   **Validation:**
   - Target: Extract ≥5 high-quality behaviors per 100 runs (0.05 extraction rate)
   - Quality: 80% approval rate for auto-extracted candidates (manual review)
   - Coverage: Reduce duplicate manual submissions by 50% (measure via tagging)

   **Evidence:**
   - Contract: `REFLECTION_SERVICE_CONTRACT.md` (defines API, quality rubric, approval workflow)
   - Code: `amprealize/reflection_service.py`, `amprealize/trace_analysis_service.py`
   - Tests: `tests/test_reflection_extraction.py`, sample traces with expected behaviors
   - Dashboard: Extraction rate chart, approval funnel, behavior growth over time

   #### Component C: Self-Improvement Loop (Weeks 5-6, P1)

   **Purpose:** Implement revision workflow from Meta paper that feeds extracted behaviors back as hints when runs fail, achieving 10% accuracy improvement on corrected attempts.

   **Implementation:**
   - **Revision Workflow:**
     - On run failure (task incomplete, validation failed, user dissatisfaction), trigger revision
     - Extract behaviors from failed trace using ReflectionService
     - Format as revision hints: "Previously attempted strategies:\n- behavior_X: reason for failure\nAlternative behaviors to try:\n- behavior_Y: suggested approach"
     - Re-run task with hint-augmented BCI prompt (original K behaviors + extracted hints)
   - **Improvement Tracking:**
     - Compare outcomes: failed_run vs revised_run (completion, accuracy, token usage)
     - Calculate improvement delta: (revised_success - failed_success) / failed_success
     - Target: 10% average improvement on revised runs (per Meta paper AIME results)
   - **Integration:**
     - CLI: `amprealize retry <run_id> --with-reflection` triggers revision workflow
     - MCP tool: `workflow.revise` with auto-reflection option
     - VS Code: "Retry with Hints" action in execution tracker for failed runs

   **Dependencies:**
   - ReflectionService (Component B) for behavior extraction
   - BehaviorRetriever (Component A) for hint-augmented BCI
   - RunService: Store revision relationships (original_run_id → revised_run_id)

   **Validation:**
   - A/B test: Revision with hints vs. simple retry (no hints) on 50+ failed tasks
   - Measure: improvement rate (target ≥10%), token usage delta, time to success
   - Iterate on hint format and K parameter for optimal results

   **Evidence:**
   - Design doc: Section in `docs/BCI_IMPLEMENTATION_SPEC.md` (self-improvement workflow)
   - Code: Update `amprealize/workflow_service.py` with retry + reflection logic
   - Tests: `tests/test_self_improvement.py`, synthetic failure scenarios
   - Dashboard: Revision success rate chart, improvement delta histogram

   #### Component D: BC-SFT Fine-Tuning Infrastructure (Weeks 7-8, P2)

   **Purpose:** Design behavior-conditioned supervised fine-tuning (BC-SFT) pipeline to distill BCI patterns into Student model weights, per Meta paper's approach for parametric behavior usage (no retrieval at inference).

   **Implementation (Design Phase):**
   - **Training Corpus Collection:**
     - Export behavior-conditioned prompts + responses from BCI runs (successful tasks only)
     - Format: `{"instruction": "Relevant behaviors:\n...\n\nNow solve: {query}", "input": "", "output": "{response with citations}"}`
     - Target corpus size: 10K+ instruction pairs for initial fine-tune
   - **Fine-Tuning Pipeline:**
     - LoRA (Low-Rank Adaptation) configuration: rank 16-32, alpha 16-32, dropout 0.05
     - QLoRA option: 4-bit quantization for memory efficiency (larger models)
     - Training: 3-5 epochs, learning rate 1e-4, batch size 4-8 (A100 GPU)
   - **Benchmarking:**
     - Compare BC-SFT Student vs. baseline SFT (no behaviors) vs. BCI (retrieval)
     - Datasets: MATH-500 (math reasoning), custom Amprealize validation set (dev tasks)
     - Metrics: accuracy, token efficiency, generalization to unseen behaviors
   - **Integration (Future):**
     - CLI: `amprealize train --corpus <path> --model <base_model>` initiates fine-tune
     - Model registry: Store trained Student models with version, corpus metadata
     - Inference: `amprealize run --model student-v1` uses BC-SFT model (no retrieval overhead)

   **Dependencies:**
   - GPU infrastructure: A100 40GB for 7B-13B models, multi-GPU for 30B+ models
   - Training libraries: `transformers`, `peft` (LoRA), `bitsandbytes` (QLoRA)
   - Baseline models: Llama-3.1-8B-Instruct, Qwen2.5-14B-Base (per Meta paper experiments)

   **Validation (Deferred to Milestone 3):**
   - Target: BC-SFT Student matches BCI accuracy while reducing retrieval latency to zero
   - Token efficiency: Retain 80%+ of BCI token savings (some compression loss expected)
   - Deployment: Serve BC-SFT models as Amprealize inference backend option

   **Evidence:**
   - Contract: `BC_SFT_CONTRACT.md` (training corpus format, LoRA config, benchmarking methodology)
   - Design: `docs/BCI_IMPLEMENTATION_SPEC.md` §§ Phase 4 (BC-SFT infrastructure)
   - Prototype: Training script skeleton in `scripts/train_bc_sft.py` (runnable with sample corpus)
   - Note: Full implementation (training execution, model serving) moved to Milestone 3 (requires GPU cluster provisioning and corpus scale)

   ### Phase 2: Infrastructure Scaling (Weeks 9-16, P1 Priority - **Deprioritized**)

   **Justification for Re-Sequencing:** Meta algorithm (BCI, extraction, self-improvement) delivers immediate value (46% token savings, 70% reuse rate, 10% accuracy gains) and validates handbook usefulness before investing in production infrastructure. PostgreSQL migration, REST API deployment, and web console can scale existing functionality but don't unlock new capabilities. By proving BCI works first, we derisk infrastructure investment and gather requirements from real usage patterns.

   **Original Milestone 2 Scope (Now Weeks 9-16):**
   - PostgreSQL + vector index migration for BehaviorService (replace SQLite, support production scale)
   - REST API endpoint exposure for all services (enable web console integration)
   - Web console v1 (behavior library, compliance dashboard, run explorer)
   - Production analytics deployment (Snowflake/BigQuery warehouse, KPI dashboards live)
   - VS Code extension Phase 2 (compliance review panels, action replay UI, analytics views)
   - AgentAuthService production deployment with just-in-time consent for all MCP tools

   **Updated Sequencing:**
   - Week 9-10: PostgreSQL migration + vector index (pgvector) for BehaviorRetriever FAISS index persistence
   - Week 11-12: REST API endpoints (FastAPI) for all services + OpenAPI spec generation
   - Week 13-14: VS Code extension Phase 2 (compliance panels, BCI toggle, analytics integration)
   - Week 15-16: Web console v1 MVP (behavior search, BCI monitoring dashboard, run explorer)
   - Deferred to Milestone 3: Production analytics warehouse (DuckDB sufficient for beta), AgentAuth production rollout (Phase 1 covers development/testing)

  ### BreakerAmp Rollout Plan (Documentation-First)
  - **Phase 0 – Documentation & Contracts (current):** Capture BreakerAmp vision, API shape, and audit requirements in PRD.md, `PRD_NEXT_STEPS.md`, and `PRD_ALIGNMENT_LOG.md` before writing code. Update `ACTION_REGISTRY_SPEC.md` and CLI/MCP help with placeholder commands (`amprealize breakeramp plan|apply|status|destroy`).
  - **Phase 1 – Control Plane Implementation (Weeks 5-6 overlap):** Build the BreakerAmp service backing the `plan/apply/status/destroy` lifecycle. Integrate with RunService for status propagation, ComplianceService for evidence, and MetricsService for utilization KPIs. All infrastructure requests from Strategist/Student agents must traverse BreakerAmp.
  - **Phase 2 – Environment Catalog (Weeks 7-8):** Ship blueprint library (PostgreSQL+Timescale bundle, Redis cache tier, telemetry stack, behavior retriever bench) with policy metadata (cost ceiling, lease duration, compliance tags). Surface catalog via CLI/VS Code pickers and expose API filters for automation.
  - **Phase 3 – Observability & Quotas (Weeks 9-10):** Add telemetry streams for resource usage, enforce per-tenant quotas, and wire dashboards highlighting environment reuse %, teardown success rate, and token savings tied to infrastructure automation.
  - **Exit Criteria:** No user or agent touches pods/infra directly; every environment is provisioned, audited, and destroyed through BreakerAmp with evidence recorded in ActionService and PROGRESS_TRACKER.

4. **Milestone 3 – GA (6 weeks):** Scaling improvements, behavior lifecycle automation, SDK release, documentation, expanded provider connectors and advanced policy tooling.

## Risks & Mitigations
- **Behavior sprawl:** implement review workflow, tagging, and decay policies.
- **Compliance fatigue:** automate checklists, provide quick inline actions.
- **LLM hallucination:** enforce behavior citation format, add evaluation harness.
- **Security:** ensure secrets never logged; integrate with secret scanners.
- **Vendor lock-in:** design abstraction layer for embeddings/LLMs.

## Open Questions
- Should we support multi-tenant behavior handbooks with shared/global behaviors?
- ~~How to price token savings; do we surface cost analytics to customers?~~ **RESOLVED** - Yes, cost analytics are customer-facing via VS Code extension Cost Tracker tree view. See [COST_MODEL.md](docs/COST_MODEL.md).
- What is the minimum viable reflection quality to auto-suggest behaviors?
- Do we offer on-prem deployments for regulated environments?

## Appendix
- **Reference Docs:** `AGENTS.md`, `agent-compliance-checklist.md`, `Metacognitive_reuse.txt`, `RETRIEVAL_ENGINE_PERFORMANCE.md`, `TELEMETRY_SCHEMA.md`, `AUDIT_LOG_STORAGE.md`, `SECRETS_MANAGEMENT_PLAN.md`, `ACTION_SERVICE_CONTRACT.md`
- **Terminology:** Strategist = plan author, Teacher = reflection coach, Student = executor.
- **Future Enhancements:** Behavior-conditioned fine-tuning service, marketplace, incident retrospectives integration.
