# Agent Handbook

> **TL;DR**: **Use the role that makes the most sense to begin with. Declare your role at task start.** Use Amprealize MCP tools directly (they work natively in VS Code Copilot Chat!).
> Log with Raze. Manage environments with BreakerAmp. Extract reusable code to `packages/`.
> Never hardcode secrets. Run `pre-commit` before pushing. **Cite both behavior AND role in your work.**
> Refer to WORK_MANAGEMENT_GUIDE.md for how to use the Amprealize platform for tracking work items, bugs, and project management.
> Use  ui-ux-pro-max skill for UI work.
---

## 🚨 Critical Rules (Always Follow)

| Rule | Behavior | Why |
|------|----------|-----|
| Use MCP tools over CLI/API when available | `behavior_prefer_mcp_tools` | Consistent schemas, automatic telemetry |
| Use Raze for all logging | `behavior_use_raze_for_logging` | Centralized, queryable, context-enriched |
| Use BreakerAmp for environments | `behavior_use_breakeramp_for_environments` | Blueprint-driven, compliance hooks |
| Never hardcode secrets | `behavior_prevent_secret_leaks` | Security, auditability |
| Run pre-commit before pushing | `behavior_prevent_secret_leaks` | Catches leaks before they reach git |
| Update docs after API/workflow changes | `behavior_update_docs_after_changes` | Keeps team aligned |
| Update the AI Learning Wiki when AI behavior or platform usage changes | `behavior_maintain_ai_learning_wiki` | Keeps the teaching layer current for future agents |

---

## 🎭 Agent Roles

> **Why Roles Matter**: The behavior handbook stores **procedural knowledge** (how-to strategies), distinct from
> declarative knowledge (facts). By operating in the correct role, you skip redundant re-derivation and
> reallocate compute to novel subproblems—achieving up to 46% fewer tokens while maintaining or improving quality.

Amprealize uses three roles inspired by [Meta's Metacognitive Reuse research](#-appendix-research-background):

| Role | Responsibility | Output Focus |
|------|----------------|-------------|
| **Student** 📖 | Consumes behaviors in-context or via fine-tuning (BC-SFT), executes with guidance | Efficient execution following established patterns |
| **Teacher** 🎓 | Generates behavior-conditioned responses for training data | Examples, documentation, behavior-conditioned training corpora |
| **Metacognitive Strategist** 🧠 | 1) Solves problems to produce traces, 2) Reflects on traces, 3) Emits behaviors | Pattern analysis, behavior curation, architectural decisions |

> **Note**: In the original research, Teacher generates training data and Student consumes/fine-tunes on it. Amprealize extends Teacher's role to include quality validation and behavior proposal approval for practical workflow integration.

### 🚦 Role Declaration Protocol (Required)

**At task start**, declare your role and rationale:

```
🎭 Role: Student
📋 Rationale: Following established patterns for [task description]
🔗 Behaviors: `behavior_use_raze_for_logging`, `behavior_prefer_mcp_tools`
```

**During execution**, if you need to escalate:

```
⬆️ Escalating: Student → Teacher
📋 Reason: Need to create reference examples for new API pattern
```

**In all work output**, cite both behavior AND role:

```
Following `behavior_use_raze_for_logging` (Student): Adding structured logging to endpoint...
```

### 📈 Role Escalation Triggers

| From | To | Trigger Conditions |
|------|-----|--------------------|
| **Student** | **Teacher** | Creating new examples or templates • Validating an unfamiliar approach • Writing documentation for others • Reviewing code quality • Explaining "how" or "why" to users |
| **Student** | **Metacognitive Strategist** | Same pattern observed 3+ times • Root cause analysis needed • No existing behavior fits • Architectural decision required • Post-mortem or retrospective |
| **Teacher** | **Metacognitive Strategist** | Gaps in behavior coverage discovered • Quality patterns need extraction • Cross-cutting concerns identified |

### 💡 Role Selection Decision Tree

```
START → Does an existing behavior cover this task?
  │
  ├─ YES → Is this routine execution?
  │         ├─ YES → Student 📖
  │         └─ NO (teaching/reviewing) → Teacher 🎓
  │
  └─ NO → Is this a novel problem requiring new patterns?
           ├─ YES → Metacognitive Strategist 🧠
           └─ NO (just needs examples) → Teacher 🎓
```

### 🎬 In Practice

```
User: "Add logging to the new endpoint"
🎭 Role: Student
📋 Rationale: Routine task with established behavior
Agent: Following `behavior_use_raze_for_logging` (Student), adding structured logging...

User: "Why do our tests keep failing on CI?"
🎭 Role: Metacognitive Strategist
📋 Rationale: Root cause analysis needed, may require new behavior
Agent: Analyzing patterns (Metacognitive Strategist). 1) Solving problem to produce trace, 2) Reflecting on trace, 3) Emitting behavior → proposing `behavior_fix_ci_flakiness`...

User: "Show me how to properly use BreakerAmp"
🎭 Role: Teacher
📋 Rationale: Creating reference examples for user learning
Agent: Demonstrating `behavior_use_breakeramp_for_environments` (Teacher) with annotated examples...

User: "We keep having to manually fix import ordering"
⬆️ Escalating: Student → Metacognitive Strategist
📋 Reason: Pattern observed 3+ times, no existing behavior
Agent: Extracting new behavior (Metacognitive Strategist): 1) Solving import problem, 2) Reflecting on trace, 3) Emitting `behavior_enforce_import_ordering`...
```

---

## 🔄 Behavior Lifecycle (Metacognitive Reuse)

> **Core Principle**: Behaviors are **procedural memory**—reusable how-to strategies extracted from successful traces.
> This lifecycle ensures behaviors are proposed, validated, and integrated systematically, achieving the 46% token
> reduction documented in Meta's research while maintaining quality.

### Lifecycle Phases

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  DISCOVER   │ →  │   PROPOSE   │ →  │   APPROVE   │ →  │  INTEGRATE  │
│  (Student)  │    │ (Strategist)│    │  (Teacher)  │    │    (All)    │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
      │                  │                  │                  │
  Observe 3+        Draft behavior     Validate quality   Add to handbook
  occurrences       with steps         & test on cases    & retrieval index
```

### Phase 1: DISCOVER (Student Role)

**Trigger**: While executing tasks, Students identify recurring patterns that lack existing behaviors.

**Student Discovery Protocol:**
```
🔍 Pattern Observed: [description of recurring situation]
📊 Occurrences: [count, ideally 3+]
📝 Current Workaround: [what steps are being repeated]
⬆️ Escalating: Student → Strategist for behavior extraction
```

**Example:**
```
🔍 Pattern Observed: Every time we add a new API endpoint, we manually add
   rate limiting, auth checks, and OpenAPI docs in the same order.
📊 Occurrences: 5 times in the last 2 weeks
📝 Current Workaround: Copy-paste from existing endpoint, modify fields
⬆️ Escalating: Student → Strategist for behavior extraction
```

### Phase 2: PROPOSE (Strategist Role)

**Trigger**: Strategist receives escalation OR discovers pattern during root cause analysis.

**Behavior Proposal Template:**
```markdown
## 📋 Behavior Proposal

**Name**: `behavior_<verb>_<noun>` (e.g., `behavior_scaffold_api_endpoint`)

**One-Line Summary**: [Single sentence describing the behavior]

**When (Triggers)**:
- [Condition 1]
- [Condition 2]

**Steps**:
1. [Step 1 with specific action]
2. [Step 2 with specific action]
3. [Validation step]

**Historical Validation**:
- [x] Would have helped in: [past case 1]
- [x] Would have helped in: [past case 2]
- [ ] Edge case to watch: [potential issue]

**Confidence Score**: [0.0-1.0, use 0.8+ for auto-approval]

**Proposed Role**: 📖 Student / 🎓 Teacher / 🧠 Strategist

**Retrieval Keywords**: [comma-separated for embedding search]
```

**Auto-Approval Threshold**: Behaviors with confidence ≥ 0.8 AND validation on 3+ historical cases can be auto-approved.

### Phase 3: APPROVE (Teacher Role)

**Trigger**: Teacher reviews pending behavior proposals.

**Teacher Validation Checklist:**
| Check | Question | Pass Criteria |
|-------|----------|---------------|
| ✅ Uniqueness | Does this duplicate an existing behavior? | No overlap with existing |
| ✅ Clarity | Are triggers unambiguous? | Clear when-to-use conditions |
| ✅ Completeness | Are steps actionable and verifiable? | Each step has a concrete output |
| ✅ Quality | Does historical validation pass? | Prevents 3+ past issues |
| ✅ Naming | Does name follow `behavior_<verb>_<noun>` pattern? | Consistent naming |
| ✅ Role Fit | Is proposed role appropriate? | Matches complexity level |

**Teacher Approval Actions:**
```
✅ APPROVED: Behavior `behavior_xyz` validated. Proceeding to integration.
   Quality Score: [0.0-1.0]
   Notes: [any modifications made]

❌ REJECTED: Behavior `behavior_xyz` not approved.
   Reason: [specific rejection reason]
   Suggestion: [how to improve proposal]

🔄 REVISION REQUESTED: Behavior `behavior_xyz` needs changes.
   Required Changes: [list of changes]
```

### Phase 4: INTEGRATE (All Roles)

**Trigger**: Approved behavior ready for integration.

**Integration Steps:**
1. **Add to AGENTS.md**: Insert behavior definition in `## 📖 Behaviors` section
2. **Update Quick Triggers**: Add keywords to trigger table with appropriate role
3. **Seed to BehaviorService**: Run `python scripts/seed_behaviors_from_agents_md.py`
4. **Update Retrieval Index**: Ensure embeddings are generated for semantic search
5. **Add Test Cases**: Create regression tests in `tests/test_behavior_*.py`
6. **Log in BUILD_TIMELINE.md**: Document behavior addition with date

**Integration Verification:**
```bash
# Verify behavior is retrievable
amprealize bci generate --query "test query matching new behavior" --top-k 5

# Verify behavior appears in results
# Expected: New behavior in retrieved behaviors list
```

---

## 🎯 Role-Specific Behavior Responsibilities

### 📖 Student: Behavior Consumer & Pattern Scout

| Responsibility | Action | Output |
|---------------|--------|--------|
| **Consume** | Retrieve and apply existing behaviors | Cite behavior in work output |
| **Scout** | Notice when tasks lack behavior coverage | Document pattern observations |
| **Escalate** | Report patterns occurring 3+ times | Formal escalation to Strategist |
| **Feedback** | Report behavior gaps or unclear steps | Improvement suggestions |

**Student MUST NOT**: Create new behaviors directly (propose only via escalation)

### 🎓 Teacher: Behavior Validator & Quality Gate

| Responsibility | Action | Output |
|---------------|--------|--------|
| **Review** | Evaluate proposed behaviors for quality | Approval/rejection with rationale |
| **Validate** | Test behaviors against historical cases | Quality score (0.0-1.0) |
| **Improve** | Suggest refinements to proposals | Edited behavior definitions |
| **Document** | Create examples showing behavior usage | Reference implementations |
| **Mentor** | Help Students understand when to escalate | Guidance on pattern recognition |

**Teacher MUST NOT**: Propose behaviors (validation only, unless escalating to Strategist)

### 🧠 Metacognitive Strategist: Behavior Architect & Curator

> **Three-Step Process** (from research): 1) Solve a problem to produce a trace, 2) Reflect on the trace to identify generalizable steps, 3) Emit behaviors as entries.

| Responsibility | Action | Output |
|---------------|--------|--------|
| **Solve** | Execute tasks to produce reasoning traces | Trace data for reflection |
| **Reflect** | Analyze traces to identify generalizable patterns | Behavior proposals |
| **Emit** | Draft new behaviors with full specification | Complete proposal template |
| **Curate** | Maintain handbook coherence, merge/split behaviors | Handbook maintenance |
| **Deprecate** | Mark obsolete behaviors, plan migrations | Deprecation notices |
| **Architect** | Design behavior retrieval and integration systems | System improvements |

**Metacognitive Strategist CAN**: Bypass Teacher approval for urgent/critical behaviors with documented justification

---

## 📊 Behavior Metrics & Health

Track these metrics to ensure the behavior handbook remains effective:

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Coverage Rate** | >80% of tasks covered | Tasks with applicable behavior / Total tasks |
| **Retrieval Accuracy** | >90% relevant | Correct behavior in top-K / Total queries |
| **Token Efficiency** | ≥30% reduction | Tokens with BCI / Tokens without BCI |
| **Behavior Freshness** | <30 days since review | Days since last validation |
| **Proposal Approval Rate** | 70-90% | Approved proposals / Total proposals |
| **Escalation Rate** | 10-20% of tasks | Tasks escalated / Total tasks |

**Health Indicators:**
- 🟢 **Healthy**: High coverage, low escalation, good token efficiency
- 🟡 **Attention**: Rising escalation rate = missing behaviors
- 🔴 **Unhealthy**: Low retrieval accuracy = stale or poorly-named behaviors

---

## 🔧 Standalone Services

When adding significant functionality, create a standalone package under `packages/`:

| Service | Purpose | Package | Install |
|---------|---------|---------|---------|
| **Raze** | Structured logging, telemetry | `packages/raze/` | `pip install raze[cli,fastapi]` |
| **BreakerAmp** | Environment/container orchestration | `packages/breakeramp/` | `pip install breakeramp[cli,fastapi]` |

**Pattern**: Zero amprealize core deps → hooks for integration → optional extras `[cli,fastapi,dev]` → thin wrapper in `amprealize/<name>/`

---

## 🎯 Quick Triggers

Scan this table before starting any task. If keywords match, follow the linked behavior with the indicated role.

> **⚠️ Before ANY task**: Run `behaviors.getForTask` or `amprealize behaviors get-for-task` to retrieve relevant behaviors!

| Trigger Keywords | Behavior(s) | Role |
| --- | --- | --- |
| **start task, begin work, any new task** | `behaviors.getForTask` | 📖 Student |
| **MCP tool, MCP server, IDE extension** | `behavior_prefer_mcp_tools` | 📖 Student |
| **logging, structured logs, telemetry sink** | `behavior_use_raze_for_logging` | 📖 Student |
| **environment, blueprint, podman, container** | `behavior_use_breakeramp_for_environments` | 📖 Student |
| **standalone package, reusable service, extract module** | `behavior_extract_standalone_package` | 🎓 Teacher |
| **secret leak, token, credential, gitleaks** | `behavior_prevent_secret_leaks`, `behavior_rotate_leaked_credentials` | 📖 Student |
| execution record, SSE, progress, run status | `behavior_unify_execution_records` | 📖 Student |
| storage adapter, audit log, timeline, run history | `behavior_align_storage_layers` | 📖 Student |
| config path, env var, secrets manager, device flow | `behavior_externalize_configuration`, `behavior_rotate_leaked_credentials` | 📖 Student |
| BehaviorService, behavior index, reflection prompt | `behavior_curate_behavior_handbook` | 🧠 Metacognitive Strategist |
| action registry, parity, `amprealize record-action` | `behavior_sanitize_action_registry`, `behavior_wire_cli_to_orchestrator` | 📖 Student |
| telemetry event, Kafka, metrics dashboard | `behavior_instrument_metrics_pipeline` | 📖 Student |
| CORS, auth decorator, bearer token, cookie | `behavior_lock_down_security_surface` | 📖 Student |
| PRD sync, alignment log, checklist, progress tracker | `behavior_update_docs_after_changes`, `behavior_handbook_compliance_prompt` | 📖 Student |
| AI concept, retrieval strategy, prompt pattern, model behavior, embeddings, RAG, agent orchestration, AI learning wiki, in-practice page, new service, new module, architecture change, capability added | `behavior_maintain_ai_learning_wiki` | 📖 Student |
| consent, JIT auth, scope catalog, prototype | `behavior_prototype_consent_ux` | 🎓 Teacher |
| budget, ROI, forecast, payback | `behavior_validate_financial_impact` | 🎓 Teacher |
| launch plan, messaging, funnel, adoption | `behavior_plan_go_to_market` | 🎓 Teacher |
| threat model, vulnerability, pen test, SOC2 | `behavior_lock_down_security_surface`, `behavior_prevent_secret_leaks` | 📖 Student |
| accessibility, WCAG, screen reader, keyboard nav | `behavior_validate_accessibility` | 📖 Student |
| git workflow, branching, merge policy | `behavior_git_governance` | 📖 Student |
| ci pipeline, deployment, rollback | `behavior_orchestrate_cicd` | 📖 Student |
| API design, OpenAPI, contract, schema validation | `behavior_design_api_contract` | 🎓 Teacher |
| product validation, hypothesis, MVP scope, user research | `behavior_validate_product_hypotheses` | 🎓 Teacher |
| incident, outage, alert, on-call, severity | `behavior_triage_incident` | 📖 Student |
| postmortem, RCA, root cause, blameless, retrospective | `behavior_write_postmortem` | 🎓 Teacher |
| PostgreSQL migration, schema change, Alembic, SQL migration | `behavior_migrate_postgres_schema` | 📖 Student |
| cross-surface parity, CLI/API/MCP consistency, parity test | `behavior_validate_cross_surface_parity` | 📖 Student |
| VS Code extension, webview, TreeDataProvider, extension API | `behavior_integrate_vscode_extension` | 🎓 Teacher |
| MCP tool schema, required fields, session context, Copilot Chat | `behavior_design_mcp_tool_schema` | 📖 Student |
| code review, PR review, approval workflow, review checklist | `behavior_conduct_code_review` | 🎓 Teacher |
| copywriting, messaging, tone, voice, brand copy | `behavior_craft_messaging` | 🎓 Teacher |
| data pipeline, ETL, feature engineering, data quality | `behavior_create_data_pipeline` | 🎓 Teacher |
| test strategy, test plan, coverage analysis, test pyramid | `behavior_design_test_strategy` | 🎓 Teacher |
| feature flag, rollout, percentage flag, gradual release | `behavior_manage_feature_flags` | 📖 Student |
| quality gate, regression check, benchmark validation | `behavior_enforce_quality_gates` | 📖 Student |
| pack bootstrap, workspace migration, pack rollback | `behavior_bootstrap_pack_migration` | 📖 Student |
| auto-reflection, learning loop, reflection trigger | `behavior_run_auto_reflection` | 📖 Student |
| work item naming, GWS, title convention, item standard | `behavior_standardize_work_items` | 📖 Student |
| new feature, feature idea, feature proposal, feature scope, feature design | `behavior_define_feature_scope` | 🎓 Teacher |
| brainstorm, ideate, creative session, thinking session, explore ideas, deep dive, what if, whiteboard ideas, think through, pros and cons, weigh options, open-ended discussion | `behavior_facilitate_brainstorm` | 🎓 Teacher |
| whiteboard session, canvas room, tldraw, real-time drawing, collaborative canvas, brainstorm canvas, ephemeral session, whiteboard snapshot | `behavior_manage_whiteboard_sessions` | 📖 Student |
| **pattern observed 3+ times, need new behavior** | `behaviors.propose` → propose new behavior | 🧠 Metacognitive Strategist |
| **creating examples, documentation, tutorials** | Relevant domain behavior | 🎓 Teacher |
| **code review, quality validation** | Relevant domain behavior | 🎓 Teacher |

---

## 🛠️ Agent Etiquette

### Testing & Validation
- After every substantive change, run the smallest relevant check (`pytest`, `npm run build`, lint)
- Record command and outcome; if no automated check exists, perform smoke test and log result
- Use test runner run_tests.sh when running more the unit tests
-Use run_tests.sh with breakeramp mode for consistent environment setup/management

### Environment & Secrets
- Never hardcode paths or secrets—use environment variables or `.env` files
- When a secret leaks, cite `behavior_rotate_leaked_credentials` and rotate immediately

### Service Calls & Tooling
- **MCP-first**: When MCP tools are available, prefer them over CLI/API calls
- Avoid loopback HTTP unless architecture explicitly separates services
- Make base URLs and credentials configurable

### Code Quality
- Keep edits focused on active behaviors; note additional debt under "next steps"
- Preserve correctness, keep diffs minimal, guard edge cases
- Avoid blanket fixes—diagnose root cause so symptoms don't reappear
- Account for backwards/forwards compatibility

### Documentation
- Update `README.md`, `PRD.md`, `BUILD_TIMELINE.md` when APIs/workflows change
- For AI-related platform work, update `wiki/ai-learning/` pages or explicitly state why no wiki update was needed
- Cite `behavior_update_docs_after_changes` in summary

### Data Integrity
- Never discard, mask, or mutate user data silently
- When migrations are unavoidable, make them invertible or document recovery paths

---

## 📖 Behaviors

### `behavior_prefer_mcp_tools`
- **When**: Working in an IDE with MCP server extensions, or when Amprealize MCP tools could replace CLI/API interactions.
- **Steps**:
  1. **Check available tools**: Amprealize MCP server exposes **220 tools** including `behaviors.*`, `runs.*`, `compliance.*`, `actions.*`, `bci.*`, `raze.*`, `breakeramp.*`, `projects.*`, `orgs.*`, `boards.*`. See `docs/contracts/MCP_SERVER_DESIGN.md` for full catalog.
  2. **Use MCP directly in VS Code Copilot Chat**: Amprealize MCP tools work natively—just invoke them by name (e.g., `mcp_amprealize_projects_list`, `mcp_amprealize_behaviors_getfortask`). No CLI fallback needed.
  3. **Prefer MCP over CLI/API**: MCP provides consistent schemas, automatic telemetry, and cross-surface parity.
  4. **Leverage IDE extensions**: VS Code Copilot Chat can invoke Amprealize tools directly for real-time behavior retrieval, project management, run status, and compliance validation.
  5. **Record usage**: Cite MCP tools in action logs for reproducibility.
  6. **Fallback gracefully**: If MCP unavailable (e.g., outside VS Code), use CLI commands with same parameters.
  7. **Report gaps**: Document missing MCP equivalents in `docs/capability_matrix.md`.

### `behavior_use_raze_for_logging`
- **When**: Adding logging to any service, debugging production issues, implementing telemetry, or replacing ad-hoc print statements.
- **Steps**:
  1. Import: `from raze import RazeLogger` or `from raze import RazeService`.
  2. Configure sink: TimescaleDB (production), InMemory (tests), JSONL (local).
  3. Include context fields: `run_id`, `action_id`, `session_id`, `actor_surface`.
  4. Use structured fields: `logger.info("Request processed", endpoint="/v1/users", latency_ms=45)`.
  5. For VS Code/web, use the `RazeClient` TypeScript wrapper.
  6. Query via REST (`/v1/logs/query`) or MCP tools (`raze.query`).

### `behavior_use_breakeramp_for_environments`
- **When**: Provisioning development environments, managing containerized resources, setting up test infrastructure.
- **Steps**:
  1. Check if BreakerAmp is needed (container orchestration, compliance) or simpler Docker Compose suffices.
  2. Create/select blueprint from `packages/breakeramp/src/breakeramp/blueprints/`.
  3. Use plan/apply/destroy workflow: `breakeramp plan --blueprint <name>`, review, then `breakeramp apply`.
  4. Configure hooks for ActionService/ComplianceService when audit trails required.
  5. Monitor via `breakeramp status`, clean up with `breakeramp destroy`.
  6. Document new blueprints in `environments.yaml`.

### `behavior_extract_standalone_package`
- **When**: Adding functionality that could be reused across projects, or refactoring tightly-coupled code.
- **Steps**:
  1. **Evaluate reusability**: Is it generic enough to benefit other projects?
  2. **Follow Raze/BreakerAmp pattern**:
     - Create under `packages/<name>/` with `pyproject.toml`, `README.md`, `LICENSE`, `src/<name>/`
     - Zero amprealize core dependencies; use hooks/callbacks
     - Define optional extras: `[cli]`, `[fastapi]`, `[dev]`
  3. **Design hook architecture**: Use dataclasses/protocols for integration points.
  4. **Create amprealize wrapper**: Thin layer under `amprealize/<name>/` wiring to ActionService/ComplianceService.
  5. **Add integration points**: FastAPI router factory, MCP adapter, CLI commands.
  6. **Verify installation**: Test `pip install -e ./packages/<name>` works independently.
  7. **Document**: Add README, update `WORK_STRUCTURE.md`, log in `BUILD_TIMELINE.md`.

### `behavior_prevent_secret_leaks`
- **When**: Initializing repos, preparing commits/pushes, wiring CI pipelines.
- **Steps**:
  1. Confirm `.gitignore` excludes secrets directories/files.
  2. Ensure `pre-commit` is installed via `./scripts/install_hooks.sh`.
  3. Run `scripts/scan_secrets.sh` before PRs; remediate immediately.
  4. Record `amprealize scan-secrets` action with sanitized reports.
  5. Escalate recurring findings to Compliance; update `SECRETS_MANAGEMENT_PLAN.md`.

### `behavior_rotate_leaked_credentials`
- **When**: Secrets, keys, or credentials appear in code, logs, or chat.
- **Steps**:
  1. Remove leaked artifact from repo; ensure `.gitignore` blocks future commits.
  2. Instruct user to rotate affected credentials per `SECRETS_MANAGEMENT_PLAN.md`.
  3. If secret reached git history, document scrub steps (`git filter-repo`).
  4. Replace production secrets with placeholders in `.env.example`.
  5. Note incident in summary with remediation status.

### `behavior_unify_execution_records`
- **When**: Work involves run persistence, SSE updates, CLI status, or execution records.
- **Steps**:
  1. Inventory all execution record definitions and storage adapters.
  2. Align fields with RunService contract (`docs/contracts/MCP_SERVER_DESIGN.md`), ActionService payloads (`docs/contracts/ACTION_SERVICE_CONTRACT.md`).
  3. Route mutations through canonical RunService/ActionService APIs.
  4. Validate state transitions across Web/CLI/API/MCP surfaces.
  5. Add regression tests covering create/progress/complete/failure paths.

### `behavior_align_storage_layers`
- **When**: Modifying UnifiedStorage, JSON/SQLite/Firestore adapters, PostgresPool.
- **Steps**:
  1. Check for duplicate methods or mismatched field names.
  2. Normalize signatures per `docs/contracts/AUDIT_LOG_STORAGE.md` and `docs/contracts/REPRODUCIBILITY_STRATEGY.md`.
  3. Verify PostgresPool commits before returning connections.
  4. Update schema docs and indexes.
  5. Test across at least two backends.
  6. Document migrations in `BUILD_TIMELINE.md`.

### `behavior_externalize_configuration`
- **When**: Encountering hardcoded file paths, ports, Firebase configs, API keys.
- **Steps**:
  1. Add typed config entries via `config/settings.py`.
  2. Load from env vars/`.env` with safe fallbacks per `SECRETS_MANAGEMENT_PLAN.md`.
  3. Update Docker Compose, manifests, `.env.example`.
  4. Remove hardcoded values; fail fast with descriptive errors if missing.
  5. Refresh setup docs.

### `behavior_harden_service_boundaries`
- **When**: Code makes loopback HTTP calls, uses inline API keys, or crosses service boundaries inconsistently.
- **Steps**:
  1. Determine if call should be in-process or external client.
  2. For in-process, use direct service calls honoring contracts.
  3. For cross-service, configure URLs/credentials, add auth guards, log failures.
  4. Add integration tests.
  5. Remove hardcoded secrets; rotate if exposed.

### `behavior_curate_behavior_handbook`
- **When**: Updating behavior definitions, prompts, retrieval metadata, OR processing behavior proposals.
- **Role**: 🧠 Metacognitive Strategist (propose/curate) or 🎓 Teacher (validate/approve)
- **Steps**:
  1. **Review existing entries** to avoid duplicates—search by name and keywords.
  2. **For new behaviors**: Follow the Behavior Proposal Template (see Behavior Lifecycle section).
  3. **Include clear triggers**: Specific conditions that activate this behavior.
  4. **Define validation steps**: How to verify the behavior was applied correctly.
  5. **Assign appropriate role**: Student (routine), Teacher (examples), Strategist (novel).
  6. **Calculate confidence score**: Based on historical validation (0.8+ for auto-approve).
  7. **Update BehaviorService index**: Run `python scripts/seed_behaviors_from_agents_md.py`.
  8. **Update retrieval metadata**: Ensure keywords enable semantic search discovery.
  9. **Add regression tests**: Create test cases in `tests/test_behavior_*.py`.
  10. **Log in BUILD_TIMELINE.md**: Document with date and brief rationale.

- **Auto-Approval Criteria** (confidence ≥ 0.8):
  - Validated against 3+ historical cases
  - Clear, unambiguous triggers
  - No overlap with existing behaviors
  - Follows `behavior_<verb>_<noun>` naming

- **Deprecation Protocol**:
  1. Mark behavior as `[DEPRECATED]` with migration path
  2. Update Quick Triggers table to remove keywords
  3. Keep in handbook for 30 days with warning
  4. Remove after migration period, log in BUILD_TIMELINE.md

### `behavior_sanitize_action_registry`
- **When**: Touching action registry schemas, defaults, or multi-tier storage.
- **Steps**:
  1. Keep registry modules inside package tree.
  2. Ensure default URLs match `docs/contracts/ACTION_REGISTRY_SPEC.md`.
  3. Provide graceful fallbacks per `docs/contracts/REPRODUCIBILITY_STRATEGY.md`.
  4. Add tests for resolution order and CLI/API parity.
  5. Update packaging and docs.

### `behavior_instrument_metrics_pipeline`
- **When**: Telemetry events, dashboards, or metrics contracts need updates.
- **Steps**:
  1. Map against `docs/contracts/TELEMETRY_SCHEMA.md`, `docs/contracts/MCP_SERVER_DESIGN.md` MetricsService.
  2. Ensure events carry run IDs, behavior refs, token accounting for PRD metrics.
  3. Update Kafka topics, warehouse schemas, retention notes.
  4. Add automated validation checks.
  5. Log dashboard updates in `BUILD_TIMELINE.md`.

### `behavior_wire_cli_to_orchestrator`
- **When**: Implementing or modifying CLI commands controlling runs.
- **Steps**:
  1. Map CLI to RunService/ActionService/BehaviorService per `docs/contracts/MCP_SERVER_DESIGN.md`.
  2. Support key ops with clear args per `docs/contracts/ACTION_REGISTRY_SPEC.md`.
  3. Add Click tests including CLI/API/MCP parity.
  4. Ensure output references unified run IDs.
  5. Update CLI docs.

### `behavior_lock_down_security_surface`
- **When**: Adjusting CORS, auth middleware, secrets/API keys.
- **Steps**:
  1. Restrict CORS via config with safe dev defaults.
  2. Audit endpoints for consistent auth.
  3. Remove inline secrets per `SECRETS_MANAGEMENT_PLAN.md`.
  4. Add security tests.
  5. Summarize posture changes.

### `behavior_update_docs_after_changes`
- **When**: Any behavior changes developer setup, API contracts, or UX flows.
- **Steps**:
  1. Update `README.md`, `PRD.md`, `WORK_STRUCTURE.md`, `BUILD_TIMELINE.md`.
  2. Regenerate API reference if schemas shift.
  3. Log in `BUILD_TIMELINE.md` and mention in summary.

### `behavior_maintain_ai_learning_wiki`
- **When**: AI-related platform work changes how Amprealize uses or explains concepts like embeddings, retrieval, prompting, agent orchestration, model behavior, or evaluation.
- **Steps**:
  1. Before coding or documenting, search the existing knowledge with `ai_learning_wiki.query` and `wiki.list_pages domain=ai-learning` to avoid duplicate pages.
  2. Decide whether the work changes a general explanation (`concept`, `technology`, `pattern`, `glossary`) or an Amprealize-specific walkthrough (`in-practice`).
  3. If the concept already exists, update the existing page with the new understanding, sources, prerequisites, and `amprealize_relevance`; otherwise create the missing page using the `wiki-contributor` skill and the wiki MCP tools.
  4. For any AI capability implemented in code, add or refresh the matching `in-practice` page with concrete file paths and a simplified explanation of how the concept shows up in Amprealize.
  5. Run `ai_learning_wiki.lint` after edits and fix broken links, stale references, or missing frontmatter before handoff.
  6. In the final summary, cite the wiki page(s) updated or explicitly state why no AI Learning Wiki update was required.

### `behavior_prototype_consent_ux`
- **When**: Designing or updating consent experiences across Web/CLI/IDE.
- **Steps**:
  1. Review `docs/AGENT_AUTH_ARCHITECTURE.md` and `docs/CONSENT_UX_PROTOTYPE.md`.
  2. Reference scope catalog entries with purpose/expiry/obligations.
  3. Define telemetry for prompt impressions, approvals, denials.
  4. Run WCAG AA accessibility checks.
  5. Log findings in `BUILD_TIMELINE.md`.

### `behavior_handbook_compliance_prompt`
- **When**: Starting a task, resuming after pause, or when user requests handbook adherence assurance.
- **Steps**:
  1. Walk through compliance checklist before executing.
  2. Reference behaviors in plan.
  3. Reconfirm after major milestones.
  4. Add new behaviors if patterns emerge.

### `behavior_git_governance`
- **When**: Creating branches, merging, coordinating reviews, mirroring repos.
- **Steps**:
  1. Review `docs/GIT_STRATEGY.md` for branching/messaging guardrails.
  2. Create branches as `role/short-slug`, run `pre-commit`.
  3. Include action IDs and behaviors in commit/PR descriptions.
  4. Require cross-role review before merge.
  5. Update trackers and tag releases.

### `behavior_orchestrate_cicd`
- **When**: Designing or updating CI/CD pipelines, deployment workflows.
- **Steps**:
  1. Reference `docs/AGENT_DEVOPS.md`, `docs/GIT_STRATEGY.md`.
  2. Configure pipelines to run pre-commit, pytest, npm build, secret scanning.
  3. Capture deployment telemetry linked to ActionService.
  4. Coordinate secrets via `SECRETS_MANAGEMENT_PLAN.md`.
  5. Validate via dry run, update incident playbooks.

### `behavior_validate_financial_impact`
- **When**: Evaluating budget requests, ROI analyses, pricing impacts.
- **Steps**:
  1. Collect cost forecasts and telemetry baselines.
  2. Model best/base/worst scenarios.
  3. Validate against Finance guardrails.
  4. Ensure financial telemetry is instrumented.
  5. Record outcomes in trackers.

### `behavior_plan_go_to_market`
- **When**: Crafting launch plans, messaging frameworks, enablement kits.
- **Steps**:
  1. Map segments and personas to value propositions.
  2. Align messaging across Web/API/CLI/MCP surfaces.
  3. Inventory launch assets with owners and dates.
  4. Define adoption KPIs and telemetry dashboards.
  5. Capture readiness status in `WORK_STRUCTURE.md`.

### `behavior_validate_accessibility`
- **When**: Designing or auditing user-facing workflows for accessibility.
- **Steps**:
  1. Run automated scans (axe, Lighthouse, PA11y).
  2. Perform keyboard and screen reader walkthroughs.
  3. Review copy for clarity and consistent tone.
  4. Verify semantic markup and ARIA metadata.
  5. Track remediation in dashboards.

### `behavior_design_api_contract`
- **When**: Creating new API endpoints, modifying existing contracts, designing service interfaces, or setting up contract testing.
- **Role**: 🎓 Teacher (design/document) or 📖 Student (follow established patterns)
- **Steps**:
  1. **Define schema first**: Draft OpenAPI 3.x spec before implementing; include request/response schemas, error codes, examples.
  2. **Follow naming conventions**: Use kebab-case paths, plural nouns for collections, consistent verb usage per `docs/contracts/ACTION_REGISTRY_SPEC.md`.
  3. **Version appropriately**: Include version in path (`/v1/`) or header; document breaking vs. non-breaking changes.
  4. **Add validation**: Use Pydantic models with strict typing; validate request bodies, query params, path params.
  5. **Document thoroughly**: Include descriptions, examples, and edge cases in OpenAPI spec; generate SDK types from spec.
  6. **Set up contract testing**: Add consumer-driven contract tests or schema validation tests in `tests/test_*_parity.py`.
  7. **Review for consistency**: Ensure pagination, filtering, sorting patterns match existing APIs.

### `behavior_validate_product_hypotheses`
- **When**: Starting new features, scoping MVP, conducting user research, or validating problem/solution fit.
- **Role**: 🎓 Teacher (facilitate validation) or 📖 Student (execute research plan)
- **Steps**:
  1. **State hypothesis clearly**: Format as "We believe [user segment] will [behavior] because [reason], which we'll measure by [metric]."
  2. **Define success criteria**: Quantitative thresholds (e.g., 30% adoption in 2 weeks) before building.
  3. **Choose validation method**: User interviews (qualitative), surveys (quantitative), prototype testing, or analytics.
  4. **Minimize build scope**: Create smallest artifact that tests hypothesis—mockup, landing page, or feature flag.
  5. **Collect structured feedback**: Use consistent interview scripts; log in `docs/user_research/` with date and participant ID.
  6. **Analyze and decide**: Document findings in PRD; explicitly state whether to proceed, pivot, or abandon.
  7. **Update roadmap**: Reflect validated learnings in `WORK_STRUCTURE.md` and product backlog.

### `behavior_triage_incident`
- **When**: Production incident occurs, alert fires, user reports critical issue, or system degradation detected.
- **Role**: 📖 Student (follow runbook) or 🧠 Strategist (novel incident requiring new patterns)
- **Steps**:
  1. **Acknowledge immediately**: Claim incident in alerting system; notify on-call channel within 5 minutes.
  2. **Assess severity**: P1 (service down), P2 (degraded), P3 (minor impact), P4 (cosmetic) per `docs/INCIDENT_SEVERITY.md`.
  3. **Establish communication**: Create incident channel; post initial status with known impact, start time, responders.
  4. **Gather diagnostics**: Check dashboards (Grafana), logs (Raze), recent deployments, external dependencies.
  5. **Mitigate first, debug second**: Roll back if recent deploy, scale if capacity, failover if single point of failure.
  6. **Update stakeholders**: Post status every 15 minutes for P1/P2; include ETA, workarounds, blast radius.
  7. **Declare resolution**: Confirm metrics normalized; post summary with duration, impact, immediate fix applied.
  8. **Schedule postmortem**: Create ticket within 24 hours citing `behavior_write_postmortem`.

### `behavior_write_postmortem`
- **When**: After incident resolution, significant outage, or near-miss that could have caused outage.
- **Role**: 🎓 Teacher (facilitate blameless retrospective) or 🧠 Strategist (extract systemic patterns)
- **Steps**:
  1. **Use template**: Copy `docs/templates/POSTMORTEM_TEMPLATE.md`; fill within 48 hours of incident.
  2. **Build timeline**: Chronological events from first signal to resolution; include timestamps, actors, actions.
  3. **Identify root causes**: Use 5 Whys or fishbone diagram; distinguish proximate cause from systemic issues.
  4. **Stay blameless**: Focus on systems and processes, not individuals; use "the system allowed" not "person X failed."
  5. **Define action items**: Each must have owner, due date, and success criteria; link to tracking tickets.
  6. **Quantify impact**: Users affected, revenue impact, SLA breach, reputation cost.
  7. **Review with team**: Hold postmortem meeting within 1 week; invite all responders and affected stakeholders.
  8. **Publish and track**: Store in `docs/postmortems/`; add action items to sprint; cite in `BUILD_TIMELINE.md`.
  9. **Extract behaviors**: If pattern observed 3+ times, escalate to Strategist for new behavior proposal.

### `behavior_migrate_postgres_schema`
- **When**: Adding/modifying database tables, changing column types, adding indexes, or managing schema versioning.
- **Role**: 📖 Student (routine migrations) or 🎓 Teacher (complex schema redesigns)
- **Reference**: See `docs/MIGRATION_GUIDE.md` for detailed examples and troubleshooting.
- **Steps**:
  1. **Check for single head**: Run `alembic heads` - must show exactly ONE head before creating migration.
  2. **Create migration**: Use `alembic revision -m "descriptive_name"` with clear action-oriented names.
  3. **Verify revision references**: Ensure `down_revision` uses the actual revision ID (not filename).
  4. **Include rollback**: Every migration must have corresponding `downgrade()` or be documented as irreversible.
  5. **Avoid unsupported params**: `create_index()` does NOT support `comment=` - use Python comments instead.
  6. **Test locally**: Run `alembic upgrade head`, verify, then test rollback with `alembic downgrade -1`.
  7. **Validate before commit**: Run `python scripts/validate_migrations.py` or let pre-commit check.
  8. **Handle data migrations**: For existing data, write idempotent transforms; never lose production data.
  9. **Update schema docs**: Reflect changes in `docs/contracts/AUDIT_LOG_STORAGE.md` and relevant service contracts.
  10. **Log in BUILD_TIMELINE.md**: Document migration number, purpose, and any breaking changes.

### `behavior_design_mcp_tool_schema`
- **When**: Creating new MCP tools, updating tool schemas, or making tools work in VS Code Copilot Chat without required parameters.
- **Role**: 📖 Student (follow pattern) or 🎓 Teacher (establish new patterns)
- **Reference**: See `docs/MCP_TOOL_SCHEMA_PATTERN.md` for detailed implementation guide.
- **Steps**:
  1. **Set required to empty**: In `mcp/tools/<tool>.json`, use `"required": []` unless parameters are truly mandatory.
  2. **Use session context**: Handler should check `arguments.get("_session", {})` for user_id, is_admin, accessible resources.
  3. **Fallback to session**: When explicit parameters not provided, use session context values.
  4. **Check admin status**: Call `_is_admin_from_session(arguments)` for elevated access patterns.
  5. **Verify access control**: Ensure user can access requested resources via `_check_org_access()` or `_check_project_access()`.
  6. **Update description**: Schema property descriptions should indicate "(optional, uses session)" when applicable.
  7. **Test with Copilot**: After changes, fully restart VS Code (Cmd+Q) to clear schema cache, then test tool invocation.
  8. **Document changes**: Update `docs/MCP_TOOL_SCHEMA_PATTERN.md` if establishing new patterns.

### `behavior_validate_cross_surface_parity`
- **When**: Adding features that should work identically across CLI, API, MCP, and web surfaces.
- **Role**: 📖 Student (follow established patterns) or 🎓 Teacher (define new parity tests)
- **Steps**:
  1. **Identify affected surfaces**: List all surfaces where feature should be available (CLI, REST API, MCP tools, Web UI).
  2. **Map to existing parity tests**: Check `tests/test_*_parity.py` for relevant test patterns.
  3. **Write parity assertions**: Each surface should produce identical results for same inputs (modulo format).
  4. **Test error handling parity**: Verify error codes and messages are consistent across surfaces.
  5. **Check schema alignment**: Ensure request/response schemas match across surfaces; use shared Pydantic models.
  6. **Add regression tests**: Create `test_<feature>_parity.py` with parameterized tests for each surface.
  7. **Document surface matrix**: Update `docs/capability_matrix.md` with feature availability per surface.

### `behavior_integrate_vscode_extension`
- **When**: Adding new VS Code extension features, webview panels, tree data providers, or MCP client integrations.
- **Role**: 🎓 Teacher (design patterns) or 📖 Student (follow existing patterns)
- **Steps**:
  1. **Follow extension architecture**: New panels go in `extension/src/panels/`, providers in `providers/`, clients in `client/`.
  2. **Use TypeScript strictly**: Enable strict mode; define interfaces for all webview message types.
  3. **Handle activation correctly**: Register disposables in `activate()`; clean up in `deactivate()`.
  4. **Implement webview security**: Use CSP headers; sanitize all data from webviews; use nonces for scripts.
  5. **Connect to MCP**: Use `McpClient.ts` for backend communication; handle connection failures gracefully.
  6. **Add telemetry**: Use `RazeClient.ts` for structured logging; include `extensionId`, `command`, `duration`.
  7. **Test with Extension Test Runner**: Add tests in `extension/src/test/suite/`; mock VS Code APIs.
  8. **Update package.json**: Register commands, views, and activation events; bump version.
  9. **Document in README**: Add feature to `extension/README.md` with screenshots if visual.

### `behavior_conduct_code_review`
- **When**: Reviewing pull requests, providing feedback on code changes, or establishing review standards.
- **Role**: 🎓 Teacher (provide thorough feedback) or 📖 Student (follow checklist)
- **Steps**:
  1. **Read the PR description**: Understand intent before reviewing code; check linked issues/behaviors.
  2. **Check behavior compliance**: Verify PR cites relevant behaviors; check against `AGENTS.md` patterns.
  3. **Review for correctness**: Verify logic, edge cases, error handling, and test coverage.
  4. **Review for consistency**: Check naming conventions, code style, and patterns match existing code.
  5. **Review for security**: Check for hardcoded secrets, SQL injection, XSS, auth bypasses.
  6. **Review for performance**: Flag N+1 queries, missing indexes, unbounded loops, memory leaks.
  7. **Provide actionable feedback**: Use "Request changes" for blockers, "Comment" for suggestions.
  8. **Approve with confidence**: Only approve when you'd be comfortable deploying the change yourself.
  9. **Follow up on changes**: Re-review after requested changes are made; don't rubber-stamp.

### `behavior_craft_messaging`
- **When**: Writing user-facing copy, defining brand voice, creating marketing content, or standardizing terminology.
- **Role**: 🎓 Teacher (establish patterns) or 📖 Student (follow style guide)
- **Steps**:
  1. **Reference style guide**: Check `docs/STYLE_GUIDE.md` or `AGENT_COPYWRITING.md` for tone, voice, and terminology standards.
  2. **Understand audience**: Identify target persona (developer, manager, end-user) and tailor language complexity.
  3. **Be concise**: Prefer active voice, short sentences, and concrete examples over abstract descriptions.
  4. **Use consistent terminology**: Map product concepts to approved terms; avoid jargon unless audience expects it.
  5. **Include CTAs**: Every piece should have clear next action; avoid dead-ends in user journey.
  6. **Test readability**: Aim for Flesch-Kincaid grade 8-10 for general audiences; technical docs can be higher.
  7. **Localization-ready**: Avoid idioms, puns, or culturally-specific references that don't translate.
  8. **Review with stakeholders**: Get sign-off from Product/Marketing before shipping user-facing copy.

### `behavior_create_data_pipeline`
- **When**: Building ETL processes, feature engineering pipelines, data quality checks, or analytics workflows.
- **Role**: 🎓 Teacher (design patterns) or 📖 Student (implement standard pipelines)
- **Steps**:
  1. **Define schema first**: Document input/output schemas with data types, nullability, and valid ranges.
  2. **Implement idempotently**: Pipeline reruns should produce identical results; use upserts over inserts.
  3. **Add data validation**: Check for nulls, outliers, schema drift at ingestion; fail fast with clear errors.
  4. **Handle late arrivals**: Design for out-of-order data; use watermarks or grace periods where needed.
  5. **Instrument thoroughly**: Log row counts, processing times, data freshness per `behavior_use_raze_for_logging`.
  6. **Version transformations**: Track transformation logic in version control; document breaking changes.
  7. **Test with representative data**: Use production-like samples; test edge cases (empty, malformed, large).
  8. **Set up monitoring**: Alert on data quality degradation, pipeline failures, unusual patterns.
  9. **Document lineage**: Map data flow from source to destination; update `docs/DATA_LINEAGE.md`.

### `behavior_design_test_strategy`
- **When**: Planning test coverage for new features, establishing testing standards, or improving test quality.
- **Role**: 🎓 Teacher (define strategy) or 📖 Student (follow test patterns)
- **Steps**:
  1. **Follow test pyramid**: 70% unit, 20% integration, 10% E2E; adjust based on architecture.
  2. **Define coverage targets**: Set minimum coverage per component; critical paths need >90%.
  3. **Identify test boundaries**: What's mocked vs. real? Document external dependency handling.
  4. **Write tests first**: For new features, TDD ensures testability; for bugs, write regression test first.
  5. **Use fixtures effectively**: Share setup via `conftest.py`; avoid test interdependence.
  6. **Test error paths**: Happy path is necessary but insufficient; test failures, timeouts, edge cases.
  7. **Keep tests fast**: Unit tests <100ms each; slow tests should be marked and run separately.
  8. **Maintain test quality**: Tests are code—review, refactor, and deduplicate test logic.
  9. **Integrate with CI**: All tests run on PR; coverage gates prevent regression.

### `behavior_manage_feature_flags`
- **When**: Adding gradual rollout controls, toggling features per user/percentage, or managing flag lifecycle.
- **Role**: 📖 Student (follow established patterns)
- **Steps**:
  1. **Register flag**: Use `FeatureFlagService.register_flag()` with name, type (BOOLEAN/PERCENTAGE/USER_LIST), and default value.
  2. **Check flags at runtime**: Call `feature_flags.is_enabled(flag_name, context)` — never hard-code feature checks.
  3. **Use consistent hashing**: PERCENTAGE flags use SHA-256 on `user_id + flag_name` for deterministic rollout.
  4. **Expose via CLI/MCP**: Flags are manageable through `amprealize flags list|get|set` and MCP tools `flags.list`, `flags.get`, `flags.set`.
  5. **Migrate schema**: Use Alembic migration `20260319_add_feature_flags` for persistent storage; rollback supported.
  6. **Clean up stale flags**: Remove flags once fully rolled out; update MIGRATION_GUIDE.md if schema changes.
  7. **Test flag behavior**: Test both enabled/disabled paths; use `_build_loop_with_flag()` pattern in tests.

### `behavior_enforce_quality_gates`
- **When**: Validating behavior adherence before pack promotion, checking for regressions in evaluation metrics.
- **Role**: 📖 Student (follow established patterns) or 🎓 Teacher (define new gate types)
- **Steps**:
  1. **Define gate checks**: Use `QualityGateService.run_all_gates()` with behavior approval, pack validation, and regression checks.
  2. **Set thresholds**: Configure `adherence_min`, `hallucination_max`, `citation_min` per gate; use defaults when not specified.
  3. **Check regressions**: Compare current vs. baseline metrics; flag regressions exceeding configurable thresholds.
  4. **Store gate results**: Attach `QualityGateReport` to behaviors via `BehaviorService` quality gate hook.
  5. **Emit telemetry**: Fire `quality_gate.evaluated` and `quality_gate.regression_detected` events per TELEMETRY_SCHEMA.
  6. **Block promotion on failure**: `PackBuilder.validate_build()` delegates to quality gates; failing gates prevent pack builds.
  7. **Review failures**: Use comparison harness (`EvaluationService.compare()`) for detailed metric breakdowns.

### `behavior_bootstrap_pack_migration`
- **When**: Bootstrapping knowledge packs into existing workspaces, rolling back failed migrations, or detecting storage backends.
- **Role**: 📖 Student (follow established patterns)
- **Steps**:
  1. **Detect storage**: Use `StorageDetector.detect()` to identify backend (Postgres, SQLite, JSON, Unknown).
  2. **Bootstrap pack**: Call `PackMigrationService.bootstrap()` — creates tables/directories, seeds default config, applies pending migrations.
  3. **Verify status**: Use `amprealize pack status` or MCP `pack.status` to confirm bootstrap success.
  4. **Rollback if needed**: Call `PackMigrationService.rollback()` to revert; idempotent and safe.
  5. **Handle backward compat**: `RuntimeInjector` gracefully handles missing ContextResolver, BehaviorRetriever, BCIService, or active pack.
  6. **Test all paths**: Test bootstrap + rollback for each storage backend; verify RuntimeInjector works with/without pack.

### `behavior_run_auto_reflection`
- **When**: Triggering automatic behavior reflection after execution runs, implementing learning loop feedback.
- **Role**: 📖 Student (follow established patterns)
- **Steps**:
  1. **Check feature flag**: Auto-reflection is gated by `ENABLE_AUTO_REFLECTION` feature flag; verify it is enabled.
  2. **Trigger after runs**: Reflection fires post-execution via `agent_execution_loop` integration.
  3. **Process through review queue**: Reflections route to review queue (`ReviewQueueService`) for approval/rejection.
  4. **Apply lifecycle policies**: Use `LifecyclePolicyService` to manage behavior promotion, deprecation, and archival.
  5. **Emit telemetry**: Fire events per TELEMETRY_SCHEMA for reflection triggers, queue operations, and policy applications.
  6. **Test with flag toggling**: Use `_build_loop_with_flag()` to test both enabled and disabled auto-reflection paths.

### `behavior_standardize_work_items`
- **When**: Creating work items via MCP, REST API, or agent planning prompts; reviewing work item titles for consistency.
- **Role**: 📖 Student (follow established patterns)
- **Reference**: `amprealize/agents/work_item_planner/prompts.py` (single source of truth), `skills/work-item-planner/SKILL.md`
- **Steps**:
  1. **Follow GWS v1.0 naming**: Titles start uppercase, use imperative verb phrases, 5-120 characters.
  2. **Use correct hierarchy**: goal → feature → task/bug. Set `parent_id` accordingly.
  3. **Avoid anti-patterns**: No Phase/Sprint/Track numbering (use labels), no type-number prefixes, no manual numbering, no status prefixes, no coded-section prefixes (`A1:`, `S1.1—`), no bracket prefixes (`[Bug]`, `[Feature]`).
  4. **Use labels for phasing**: Instead of "Phase 1: …" titles, add `labels: ["phase:1"]`.
  5. **Use points**: Not `story_points`. Depth levels: `goal_only`, `goal_and_features`, `full`.
  6. **Validate before creating**: MCP and REST API enforce GWS automatically; agent prompts include GWS summary.
  7. **Use WorkItemPlanner**: For bulk planning, use `WorkItemPlanner.plan()` or the `work-item-planner` skill.

### `behavior_define_feature_scope`
- **When**: Designing a new product feature, scoping a major enhancement, or planning cross-surface feature coverage before implementation.
- **Role**: 🎓 Teacher (facilitate structured design) or 📖 Student (follow established interview pattern)
- **Reference**: `amprealize/agents/playbooks/AGENT_NEW_FEATURE.md` (playbook), `skills/new-feature-designer/SKILL.md` (skill), `amprealize/agents/feature_designer/models.py` (models)
- **Steps**:
  1. **Auto-discover context**: Use `Explore` subagent and MCP tools (`behaviors.getForTask`, `context.getContext`) to gather related services, behaviors, and patterns.
  2. **Conduct 7-phase interview**: Identity & Distribution → Surface Coverage → Architecture & Integration → Behavioral Context → Feature Interactions → Security & Compliance → Success & Testing.
  3. **Determine edition**: Decide OSS / Enterprise Starter / Enterprise Premium; if enterprise-only, select an OSS stub pattern.
  4. **Map surface coverage**: For each surface (MCP, API, CLI, Web, VS Code), classify as day-one or follow-up.
  5. **Identify service impacts**: List all impacted services, data model changes, and config items.
  6. **Define acceptance criteria**: Every criterion must be testable with clear pass/fail — reject vague statements.
  7. **Produce Feature Definition**: Use `FEATURE_DEFINITION_TEMPLATE.md` template; save to session memory.
  8. **Hand off**: Route to Plan agent (implementation plan), WorkItemPlanner (work items), or save as file.

### `behavior_facilitate_brainstorm`
- **When**: User wants to brainstorm, ideate, explore ideas creatively, run a thinking session, conduct a deep dive, or think through any open-ended topic — whether product-related or not (e.g., process improvements, naming, strategy, architecture, research directions, team practices).
- **Role**: 🎓 Teacher (facilitate creative exploration)
- **Reference**: `amprealize/agents/playbooks/AGENT_BRAINSTORM.md` (playbook), `.agents/skills/brainstorm/SKILL.md` (skill), `amprealize/agents/templates/BRAINSTORM_SESSION_TEMPLATE.md` (output template)
- **Steps**:
  1. **Gather context**: Understand topic, background, constraints, and prior thinking. Auto-discover via Explore subagent and MCP tools if product-related; for non-product topics, gather context conversationally.
  2. **Diverge (OPEN)**: Generate volume of ideas using SCAMPER, inversion, random stimulus, question-storming, analogy transfer. Minimum 5-8 exchanges.
  3. **Deepen (EXPLORE)**: Drill into promising threads using 5 Whys, Six Thinking Hats, persona walks, constraint flips, second-order effects, future casting.
  4. **Converge (CLOSE)**: Only after 8+ substantive exchanges. Rank, synthesize themes, identify sleepers.
  5. **Checkpoint continuously**: Auto-save running idea board to `/memories/session/brainstorm-board.md` every 3-4 exchanges.
  6. **Produce summary**: Use `BRAINSTORM_SESSION_TEMPLATE.md`; save to `/memories/session/brainstorm-summary.md`.
  7. **Hand off**: Match output to session type. For product/feature ideas → NewFeature, Plan, or WorkItemPlanner. For non-product topics → save as decision doc, action items, memory note, or simply summarize conclusions. Offer "Continue brainstorming" for multi-day sessions.

### `behavior_manage_whiteboard_sessions`
- **When**: Creating, joining, or closing whiteboard sessions; managing canvas state; exporting snapshots; troubleshooting tldraw sync issues.
- **Role**: 📖 Student (follow established patterns)
- **Reference**: `amprealize/agents/playbooks/AGENT_BRAINSTORM.md` (whiteboard integration section), `docs/features/BRAINSTORM_WHITEBOARD_FEATURE_DEFINITION.md`
- **Steps**:
  1. **Check feature flag**: Whiteboard is gated by `ENABLE_WHITEBOARD`; verify it is enabled before proceeding.
  2. **Create via brainstorm only**: Rooms are created exclusively through `brainstorm.openWhiteboard`. Direct creation via REST or MCP `whiteboard.createRoom` requires `metadata.source == "brainstorm_bridge"`.
  3. **Use environment-aware URLs**: Room URLs use `AMPREALIZE_CONSOLE_URL` (defaults to `http://localhost:5173` for dev). Never hardcode hostnames.
  4. **Manage ephemeral lifecycle**: Live canvas data evaporates on close. Call `brainstorm.closeSession` to persist a snapshot (rendered export + raw `canvas_elements` JSONB) before closing.
  5. **Respect canvas size limits**: Canvas state is capped at 5MB (both sidecar and REST API enforce this). Warn users if approaching limit.
  6. **Monitor via hooks**: Room create/close/archive events emit Raze telemetry and audit log entries via `AmprealizeWhiteboardHooks`.
  7. **Troubleshoot sync**: If WebSocket issues occur, check nginx config (`/ws/whiteboard/` proxy), `whiteboard-sync` sidecar health (`/healthz`), and `VITE_WHITEBOARD_SYNC_URL` env var.

---

## ✅ Role-Specific Checklists

Use the checklist matching your declared role. Complete at task start and after major milestones.

### 📖 Student Checklist (Default Role)

Use for routine execution following established patterns.

| Step | Action | Example |
|------|--------|---------|
| 1. **Declare** | State role with rationale | `🎭 Role: Student` `📋 Rationale: Adding logging per established pattern` |
| 2. **Scan** | Review Quick Triggers, list applicable behaviors | `🔗 Behaviors: behavior_use_raze_for_logging` |
| 3. **Execute** | Follow behavior steps, cite behavior+role in output | `Following behavior_use_raze_for_logging (Student)...` |
| 4. **Validate** | Run smallest relevant automated check | `pytest tests/test_logging.py` |
| 5. **Summarize** | List completed work with behavior+role citations | `Completed: Added Raze logging (Student, behavior_use_raze_for_logging)` |
| 5a. **Wiki Check** | If AI-related work, update wiki or state why not | `Wiki: Updated wiki/ai-learning/concepts/embeddings.md` or `Wiki: No AI concept changes` |
| 6. **Scout Patterns** | Note if same workaround was used before | `🔍 Pattern: Third time adding rate limiting manually` |
| 7. **Escalate?** | If pattern occurs 3+ times, escalate to Strategist | `⬆️ Escalating: Student → Strategist (pattern observed 3+ times)` |

### 🎓 Teacher Checklist

Use when creating examples, documentation, reviews, or validating behavior proposals.

| Step | Action | Example |
|------|--------|---------|
| 1. **Declare** | State role with teaching objective | `🎭 Role: Teacher` `📋 Rationale: Creating reference examples for BreakerAmp` |
| 2. **Identify scope** | What needs to be taught/validated/documented? | `Scope: Blueprint creation workflow with compliance hooks` |
| 3. **Check coverage** | Do existing behaviors cover this? If gaps, note for Strategist | `Gap: No behavior for blueprint versioning` |
| 4. **Create artifacts** | Generate behavior-conditioned examples with clear annotations | `# Example: behavior_use_breakeramp_for_environments (Teacher)` |
| 5. **Validate quality** | Ensure examples are correct, idiomatic, complete | Code review, test execution |
| 6. **Review proposals** | If behavior proposals pending, validate per Teacher Checklist | `✅ APPROVED: behavior_scaffold_api_endpoint` |
| 7. **Document** | Update relevant docs citing behavior+role | `Updated README.md (Teacher, behavior_update_docs_after_changes)` |
| 8. **Escalate?** | If gaps discovered, escalate to Strategist | `⬆️ Escalating: Teacher → Strategist (behavior gap identified)` |

### 🧠 Metacognitive Strategist Checklist

Use for novel problems, pattern extraction, post-mortems, and behavior curation.

| Step | Action | Example |
|------|--------|--------|
| 1. **Declare** | State role with strategic objective | `🎭 Role: Metacognitive Strategist` `📋 Rationale: Root cause analysis of CI failures` |
| 2. **Solve** | Execute task to produce reasoning trace | `Trace: Debugging CI failure → found flaky test timing` |
| 3. **Reflect** | Analyze trace for generalizable steps | `Generalizable: Pre-commit hook + isort config` |
| 4. **Propose behavior** | Draft new behavior using Proposal Template | `Proposing: behavior_enforce_import_ordering` (see template) |
| 5. **Calculate confidence** | Score based on historical validation | `Confidence: 0.85 (validated against 4 past cases)` |
| 6. **Submit for approval** | Route to Teacher for validation (or auto-approve if ≥0.8) | `→ Teacher review` OR `Auto-approved (confidence 0.85)` |
| 7. **Integrate** | Add to handbook, update retrieval metadata | `Added to AGENTS.md, seeded to BehaviorService` |
| 8. **Delegate** | Hand off routine execution to Student/Teacher | `Routine enforcement now follows behavior_enforce_import_ordering (Student)` |

> **Note**: Steps 2-4 map to the research's three-step process: Solve → Reflect → Emit.

---

## 📋 Additional Instructions

- Prioritize updating existing docs instead of creating new summary files
- Always run pre-commit hooks before pushing code
- Use descriptive variable names that explain purpose and intent
- Document all public API endpoints with OpenAPI specs
- Follow `TESTING_GUIDE.md` using pytest
- Use Brief CLI or MCP tools to sync instruction files (AGENTS.md, CLAUDE.md, .github/copilot-instructions.md)
- **Branding:** Use **Amprealize** for the product name (capital **A** only; not “AmpRealize”). Use **`amprealize`** for the CLI, Python package, and PyPI distribution name (all lowercase).

---

## 📚 Appendix: Research Background

<details>
<summary>Meta AI's "Metacognitive Reuse" Paper (click to expand)</summary>

### Article that inspired Amprealize

**Meta AI Proposes 'Metacognitive Reuse': Turning LLM Chains-of-Thought into a Procedural Handbook that Cuts Tokens by 46%**

*By Asif Razzaq – September 21, 2025*
*Source: https://arxiv.org/pdf/2509.13237*

Meta researchers introduced a method that compresses repeated reasoning patterns into short, named procedures—"behaviors"—and then conditions models to use them at inference or distills them via fine-tuning.

**Results:**
- Up to **46% fewer reasoning tokens** on MATH while matching or improving accuracy
- Up to **10% accuracy gains** in self-improvement settings on AIME
- No model weight changes required

**The Problem:**
Long chain-of-thought traces repeatedly re-derive common sub-procedures (inclusion–exclusion, base conversions, geometric angle sums). This redundancy burns tokens, adds latency, and crowds out exploration.

**The Solution:**
Abstract recurring steps into concise, named behaviors (name + one-line instruction) recovered from prior traces via LLM-driven reflection, then reuse them during future reasoning.

**Three Roles, One Handbook:**
- **Metacognitive Strategist** (R1-Llama-70B in research): 1) Solves a problem to produce a trace, 2) Reflects on the trace to identify generalizable steps, 3) Emits behaviors as entries
- **Teacher** (LLM B): Generates behavior-conditioned responses used to build training corpora
- **Student** (LLM C): Consumes behaviors in-context (inference) or is fine-tuned on behavior-conditioned data (BC-SFT)

**Evaluation Modes:**
1. **Behavior-Conditioned Inference (BCI)**: Retrieve K relevant behaviors and prepend to prompt
2. **Behavior-Guided Self-Improvement**: Extract behaviors from earlier attempts as hints for revision
3. **Behavior-Conditioned SFT (BC-SFT)**: Fine-tune on teacher outputs that already follow behavior-guided reasoning

**Retrieval Mechanism:**
- Topic-based retrieval on MATH benchmarks
- Embedding-based retrieval (BGE-M3 + FAISS) on AIME benchmarks

**Why It Works:**
The handbook stores procedural knowledge (how-to strategies), distinct from classic RAG's declarative knowledge (facts). By converting verbose derivations into short, reusable steps, the model skips re-derivation and reallocates compute to novel subproblems.

**Full Citation:**
*"Metacognitive Reuse: Turning LLM Chains-of-Thought into a Procedural Handbook"*
Meta AI Research, September 2025
https://arxiv.org/pdf/2509.13237

</details>

---

_Last updated: 2026-04-03_
