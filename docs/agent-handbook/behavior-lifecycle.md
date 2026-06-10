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
1. **Add to [behavior-catalog.md](behavior-catalog.md) and update compact `AGENTS.md` quick triggers if needed**: Insert behavior definition in [behavior-catalog.md](behavior-catalog.md)
2. **Update Quick Triggers**: Add keywords to trigger table with appropriate role
3. **Seed to BehaviorService**: Run `python scripts/seed_behaviors_from_agents_md.py` (add `--apply-context` after `amprealize context use neon` so Neon DSNs override localhost `.env` entries)
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
| 1a. **Subsystem quotient** | Before a new major subsystem or duplicate orchestration path, apply `behavior_justify_platform_subsystem` | One-sentence distinction vs YAML + one workflow engine + one agent runtime (see `docs/SUBSYSTEM_BASELINE.md`) |
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
- After handbook or MCP tool changes, run `python scripts/sync_agent_instruction_files.py` (handbook → enterprise, MCP manifests, workspace `.cursor/rules/Agent-rules.mdc`). Do not use `brief update` to duplicate content across `AGENTS.md` / `CLAUDE.md` / copilot files — they are layered adapters; optional: `brief list` / `brief validate`.
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

_Last updated: 2026-05-26_
