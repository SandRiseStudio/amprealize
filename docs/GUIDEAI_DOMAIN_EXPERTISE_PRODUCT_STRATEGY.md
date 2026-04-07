# Amprealize Domain Expertise Product Strategy Memo

> **Status:** Proposed
>
> **Date:** 2026-03-16
>
> **Author:** GitHub Copilot (GPT-5.4) working session
>
> **Audience:** Product, Platform Engineering, DX, Extension, MCP, Behavior/BCI, Leadership
>
> **Related:** `AGENTS.md`, `.github/copilot-instructions.md`, `CLAUDE.md`, `docs/work_management_guide.md`, `docs/ONBOARDING_QUICKSTARTS.md`, `docs/INSTALLATION_AND_REPO_OPTIMIZATION_PLAN.md`, `docs/BCI_IMPLEMENTATION_SPEC.md`, `docs/PRD.md`

---

## 1. Executive Summary

Amprealize’s long-term advantage should come from making agents **Amprealize-native by default**: they should know how to use the platform, how to select the right role, how to retrieve the right behaviors, how to manage work inside Amprealize when appropriate, and how to improve over time from prior Amprealize executions.

The recommended strategy is **not** to begin by training a proprietary foundation model. Instead, Amprealize should build a **proprietary domain expertise layer** that sits above general-purpose models and is delivered consistently across every user surface:

1. **Canonical doctrine** — stable principles and behavior definitions.
2. **Scoped operational playbooks** — role-, repo-, and task-specific guidance.
3. **Adaptive bootstrap** — install/init/onboarding that provisions the right knowledge bundle.
4. **Runtime knowledge injection** — BCI, task-aware retrieval, workspace context, and role-aware prompting.
5. **Learning loop** — telemetry, traces, behavior extraction, recommendation tuning, and eventually model adaptation.

This lets Amprealize become better than generic LLM tooling at **Amprealize-specific work** while remaining portable across Copilot, Claude, MCP clients, the web console, the CLI, and the VS Code extension.

### Bottom-line recommendation

- **Keep `AGENTS.md` as the canonical source of truth.**
- **Bootstrap a scoped `work_management_guide.md` only where Amprealize self-tracking is expected.**
- **Create a new compact runtime artifact** (for example, a “Amprealize Operating Primer”) for high-frequency agent use.
- **Prioritize runtime infusion over static documentation alone.**
- **Treat BCI + Amprealize-specific telemetry + successful traces as the primary moat.**
- **Delay custom model work until Amprealize has enough proprietary high-quality traces to justify it.**

---

## 2. Problem Statement

Today, Amprealize partly solves the “how should agents use Amprealize?” problem through static repository instructions such as `AGENTS.md`, `.github/copilot-instructions.md`, and `CLAUDE.md`. That is a strong foundation, but it is not sufficient to make agents inherently effective at using the Amprealize platform.

### Current limitations

1. **Knowledge is document-heavy and unevenly injected**
   - Core rules exist, but they are not consistently surfaced at task start.
   - Agents may know the docs exist without being conditioned on the right subset at the right time.

2. **Too much knowledge is global when it should be scoped**
   - Some instruction is universal (`AGENTS.md`).
   - Some is operational and repo-specific (`work_management_guide.md`).
   - Some should be contextual and ephemeral (task-specific tool usage hints, runtime workarounds, surface-specific flows).

3. **Bootstrap alone does not create durable expertise**
   - Shipping a document into a repo helps, but it does not guarantee retrieval, prioritization, or adherence.
   - A bootstrapped file is only useful if the agent actually receives and uses it during execution.

4. **Amprealize-specific execution knowledge is not yet fully turned into product intelligence**
   - The platform already stores behaviors, runs, work items, audit signals, and telemetry.
   - That data should compound into better guidance, better retrieval, and better domain specialization.

### Strategic question

How do we make agents using Amprealize **inherently effective** at Amprealize, in a way that is portable, proprietary, measurable, and improves over time?

---

## 3. Strategic Thesis

Amprealize should build a **Amprealize Domain Expertise System** rather than relying on a single static handbook or jumping immediately to a proprietary model.

This system should:

- bootstrap the right knowledge,
- retrieve the right knowledge at runtime,
- validate whether the knowledge was actually used,
- learn from successful executions,
- and only later decide which parts should be baked into specialized models.

### Why this is the right strategy

1. **Faster to market** than full model training.
2. **Lower cost and lower risk** than creating a proprietary LLM early.
3. **Portable** across multiple agent hosts and model providers.
4. **Compounding** because each successful run can improve Amprealize-specific expertise.
5. **Proprietary** because the behavior graph, traces, rankings, and operational playbooks are unique to Amprealize.

---

## 4. Strategic Principles

### 4.1 Canonical-first, generated-second

`AGENTS.md` remains the canonical source of platform doctrine. Runtime artifacts, bootstrap packs, and surface-specific instructions should be generated from canonical sources wherever practical.

### 4.2 Scope knowledge to the job

Not every repo or user needs the same Amprealize operational instructions. Universal doctrine should be separated from work-management playbooks, extension workflows, or infrastructure usage patterns.

### 4.3 Runtime beats static

A knowledge file in a repo is helpful. A task-aware system that injects the right Amprealize principles, behaviors, and warnings into the active run is better.

### 4.4 Retrieval before training

Before baking Amprealize expertise into a specialized model, Amprealize should exhaust the gains available from:
- behavior retrieval,
- workspace-aware prompts,
- execution scoring,
- citation compliance,
- and post-run reflection.

### 4.5 Proprietary value comes from the loop

The moat is not just the text of the handbook. The moat is:
- which behavior was recommended,
- why it was recommended,
- which one was used,
- whether it worked,
- and how Amprealize updated itself afterward.

---

## 5. Knowledge Architecture Strategy

Amprealize expertise should be delivered through four layers.

### Layer A — Canonical Doctrine

Purpose: store durable Amprealize truths.

Examples:
- `AGENTS.md`
- behavior role model (Student / Teacher / Strategist)
- critical rules such as MCP-first, Raze logging, BreakerAmp usage, and behavior retrieval
- behavior lifecycle and handbook governance

This is the authoritative source for:
- roles,
- principles,
- required workflows,
- naming conventions,
- escalation rules,
- and cross-surface standards.

### Layer B — Operational Playbooks

Purpose: capture scoped, workflow-specific instructions.

Examples:
- `docs/work_management_guide.md`
- onboarding quickstarts
- future surface-specific playbooks (VS Code, CLI, Web)
- task-type guides (migration, extension work, work item execution, auth/device flow, analytics)

This layer is where Amprealize should answer questions like:
- How should an agent manage Amprealize work items?
- How should an agent operate in a specific repo type?
- What are the current platform workarounds and runtime checks?

### Layer C — Runtime Expertise Injection

Purpose: deliver the right subset of Amprealize knowledge at task time.

Examples:
- BCI behavior retrieval
- workspace-aware instruction injection
- role-aware plan templates
- chat welcome recommendations
- dynamic Copilot/Claude instruction overlays
- MCP tool responses that carry recommended context and next actions

This is the most important layer for product differentiation in the next two phases.

### Layer D — Learned Proprietary Memory

Purpose: improve Amprealize-native agent performance over time.

Examples:
- successful traces
- ranked behaviors by task type
- behavior citation compliance data
- task completion outcomes
- recommended prompt fragments by surface/profile
- extracted playbooks from successful Amprealize executions

This layer eventually feeds:
- better retrieval,
- better defaults,
- better onboarding,
- better routing,
- and possibly model adaptation.

---

## 6. Product Recommendations by Question

### 6.1 Should Amprealize bootstrap `work_management_guide.md`?

**Recommendation: Yes, selectively.**

`work_management_guide.md` is valuable when the repo or workspace is expected to track work in Amprealize itself or to follow Amprealize-native work management patterns. It should **not** be the default universal bootstrap artifact for every installation.

#### Recommended policy

Bootstrap `work_management_guide.md` when one or more of the following are true:
- the repo is a Amprealize-managed platform repo,
- the user chooses a “Amprealize-native work tracking” profile in `amprealize init`,
- the workspace enables work-item execution, boards, or compliance workflows,
- or the extension detects that the repo is intended to self-track inside Amprealize.

#### Why scoped bootstrap is better than universal bootstrap

- avoids overwhelming lightweight users,
- avoids irrelevant work-management instructions in simple repos,
- keeps global onboarding cleaner,
- and makes the guide more actionable because it is only present where it matters.

### 6.2 Should Amprealize train its own model?

**Recommendation: Not yet as the primary bet.**

Amprealize should not start by training a proprietary foundation model. That would be expensive, slow, operationally heavy, and premature relative to the amount of Amprealize-specific training data currently productized.

#### Better near-term path

First build the systems that create proprietary Amprealize intelligence without requiring a full custom model:
- knowledge packs,
- adaptive bootstrap,
- BCI retrieval,
- workspace-aware prompting,
- run scoring,
- trace extraction,
- and ranking/recommendation loops.

#### When model work becomes rational

A specialized model or adapter becomes attractive when Amprealize has:
- a large and clean corpus of Amprealize-native traces,
- high-confidence labeled successful executions,
- stable task taxonomies,
- robust offline evals,
- and clear evidence that retrieval/injection alone has plateaued.

### 6.3 Should Amprealize infuse domain expertise into existing LLMs and agents?

**Recommendation: Yes — this should be the main strategy.**

Amprealize should become a model-agnostic expertise layer that can condition existing LLMs and agent hosts more effectively than generic prompts can.

This includes:
- injected operating primers,
- behavior retrieval,
- task-scoped playbooks,
- role-aware instruction overlays,
- surface-specific recommendations,
- and telemetry-backed refinement.

This is the best mix of:
- leverage,
- distribution,
- speed,
- and proprietary value.

---

## 7. Proposed Product Capability: Amprealize Knowledge Packs

Amprealize should introduce a first-class product concept called a **Amprealize Knowledge Pack**.

A Knowledge Pack is a versioned, machine-readable, injectible package of Amprealize-native expertise.

### Proposed contents

1. **Doctrine**
   - core principles
   - required role declarations
   - critical tool usage patterns

2. **Behaviors**
   - selected behaviors
   - recommended retrieval tags
   - applicable surfaces

3. **Operational playbooks**
   - work management rules
   - onboarding steps
   - platform workarounds
   - environment rules

4. **Task overlays**
   - migration guidance
   - extension work guidance
   - MCP tool usage guidance
   - work item execution guidance

5. **Surface overlays**
   - VS Code guidance
   - CLI guidance
   - Web guidance
   - MCP guidance
   - non-Copilot agent guidance

6. **Examples and constraints**
   - high-signal examples
   - anti-patterns
   - policy constraints
   - citation expectations

### Why this matters

Knowledge Packs create a portable Amprealize-specific intelligence layer that can be:
- bootstrapped during `amprealize init`,
- attached to a workspace,
- loaded into an extension,
- injected into agent sessions,
- or reused across different model vendors.

---

## 8. Product Surface Strategy

### 8.1 CLI / `amprealize init`

Make `amprealize init` an adaptive setup wizard that asks what sort of user/workspace is being configured.

#### Proposed profiles

- Solo developer
- Amprealize platform repo
- Team workspace
- Extension-heavy repo
- API/backend repo
- Compliance-sensitive workspace

#### What `amprealize init` should provision

- baseline instruction pack,
- selected Knowledge Pack,
- optional `work_management_guide.md`,
- extension settings or `.vscode` integration,
- MCP config defaults,
- telemetry preferences,
- and role defaults.

### 8.2 VS Code Extension

Highest-leverage opportunity for runtime expertise injection.

#### Proposed enhancements

- **Activation welcome:** role-aware setup instead of generic success messaging.
- **Amprealize Chat welcome:** task suggestions derived from workspace type.
- **Behavior detail panel:** role-aware execution guidance.
- **Plan composer:** auto-suggested context variables and recommended behavior bundles.
- **Project settings:** selected knowledge profile and active pack visibility.

### 8.3 Copilot / Claude instruction surfaces

Current static instruction files are valuable but should evolve into generated overlays.

#### Strategy

- keep `.github/copilot-instructions.md` and `CLAUDE.md` as durable baseline instructions,
- inject workspace and task context dynamically at runtime,
- version and template the dynamic additions,
- and align them to the active Knowledge Pack.

### 8.4 MCP surface

MCP tools should not only execute actions — they should also help agents understand what to do next.

Examples:
- `behaviors.getForTask` should return recommended usage notes and suggested next actions when appropriate.
- `context.getContext` should expose the active knowledge profile and active pack.
- task execution tools should log whether recommended Amprealize patterns were followed.

---

## 9. Proprietary Advantage Strategy

Amprealize’s moat should come from **Amprealize-native procedural intelligence**, not just documentation.

### Core proprietary assets

1. **Behavior graph**
   - which behaviors relate to which tasks, roles, and outcomes.

2. **Task-to-behavior ranking data**
   - which behaviors were recommended vs actually useful.

3. **Amprealize-native successful traces**
   - how high-quality Amprealize work is actually performed.

4. **Surface-specific effectiveness data**
   - which prompts and packs work best in CLI, extension, MCP, or web.

5. **Operational playbook corpus**
   - Amprealize-specific workflows, edge cases, and workarounds.

6. **Compliance and audit metadata**
   - whether the system followed its own standards and how often.

These are difficult for competitors to replicate because they emerge from Amprealize’s own platform usage and dogfooding.

---

## 10. Phased Roadmap

## Phase 1 — Canonical and Bootstrap Foundation (0–6 weeks)

### Objectives
- cleanly separate universal doctrine from scoped playbooks,
- create the first Knowledge Pack format,
- make bootstrap selective and profile-driven.

### Deliverables
- formal Knowledge Pack schema and versioning model,
- “Amprealize Operating Primer” generated from canonical sources,
- `amprealize init` profile selection and pack scaffolding,
- scoped bootstrap rules for `work_management_guide.md`,
- basic pack activation in extension/project settings.

### Success criteria
- fresh workspaces get the right guidance without manual doc hunting,
- first-run setup time decreases,
- support questions about “which docs do I use?” drop materially.

## Phase 2 — Runtime Knowledge Injection (6–12 weeks)

### Objectives
- make Amprealize guidance show up at task start across high-value surfaces.

### Deliverables
- extension role-aware welcome and task-start guidance,
- dynamic Copilot/Claude instruction overlays,
- workspace-aware recommendations in chat and plan composer,
- active-pack context visible in MCP and extension surfaces.

### Success criteria
- more sessions start with appropriate behavior retrieval,
- role declaration compliance improves,
- task-start friction decreases.

## Phase 3 — BCI and Recommendation Intelligence (12–20 weeks)

### Objectives
- turn behavior retrieval and usage validation into a durable product moat.

### Deliverables
- BCI retrieval/composition/citation pipeline in production workflows,
- task-to-behavior ranking tuned from Amprealize data,
- telemetry-backed recommendation dashboards,
- post-run feedback loops for retrieval quality.

### Success criteria
- behavior reuse increases toward PRD goals,
- output token efficiency improves,
- recommendation quality increases release over release.

## Phase 4 — Learned Specialization and Model Adaptation (20+ weeks)

### Objectives
- convert Amprealize-native trace quality into deeper specialization.

### Deliverables
- golden-trace curation pipeline,
- behavior/routing reranker experiments,
- planner/evaluator fine-tuning experiments,
- decision memo on whether Amprealize should train or adapt a specialist model.

### Success criteria
- measurable lift from specialized ranking/planning,
- evidence-backed go/no-go decision on model adaptation,
- clear ROI relative to retrieval-only strategy.

---

## 11. ROI Framing

## 11.1 Investment thesis

This strategy is attractive because most of the value can be created **before** expensive model-training work.

### Value drivers

1. **Higher task success**
   - agents follow Amprealize-native best practices more often.

2. **Lower prompt waste**
   - task-specific retrieval reduces repetitive guidance and re-derivation.

3. **Faster onboarding**
   - users and agents receive tailored setup rather than generic docs.

4. **Lower support burden**
   - the product can answer “what should I do next?” natively.

5. **Compounding product quality**
   - every run improves future guidance.

### Economic advantage vs custom model first

| Option | Time-to-value | Cost | Risk | Proprietary upside |
|---|---:|---:|---:|---:|
| Static docs only | Low | Low | Medium | Low |
| Custom model first | Slow | High | High | Potentially high, but delayed |
| Knowledge Pack + BCI + adaptive bootstrap | Fast | Moderate | Moderate | High and compounding |

### ROI expectation by phase

- **Phase 1:** primarily saves onboarding/support cost and reduces setup confusion.
- **Phase 2:** improves task-start success and agent consistency.
- **Phase 3:** improves productivity and creates measurable proprietary recommendation quality.
- **Phase 4:** may unlock further margin/performance gains if model adaptation is justified.

---

## 12. Risk Framing

## 12.1 Strategic risks

### Risk 1 — Knowledge sprawl

If Amprealize adds more docs without a governing structure, the system becomes harder to use rather than easier.

**Mitigation:**
- keep canonical doctrine limited,
- generate derived artifacts,
- use scoped packs instead of universal document proliferation.

### Risk 2 — Runtime over-complexity

If every surface gets a different behavior system, users and developers will face inconsistency.

**Mitigation:**
- one Knowledge Pack format,
- one behavior retrieval pipeline,
- one pack activation model,
- surface-specific renderers rather than surface-specific truth sources.

### Risk 3 — Premature model investment

Training or heavily fine-tuning too early could consume effort before Amprealize has stable data or evals.

**Mitigation:**
- retrieval first,
- telemetry and gold-trace pipeline first,
- model work only after clear plateau and evidence.

### Risk 4 — False confidence from injected guidance

Agents may appear more “Amprealize aware” while still missing crucial nuance.

**Mitigation:**
- citation compliance,
- validation checklists,
- post-run audits,
- recommendation quality measurement.

### Risk 5 — Drift between doctrine and implementation

Generated runtime guidance could go stale if canonical sources and system behavior diverge.

**Mitigation:**
- canonical-first generation,
- versioned packs,
- explicit validation pipeline for generated artifacts,
- docs/tests tied to behavior versioning.

---

## 13. Recommended Success Metrics

### Adoption metrics
- % of initialized workspaces with active Knowledge Pack
- % of sessions starting with role declaration and behavior retrieval
- % of eligible repos with scoped work management guidance enabled

### Guidance quality metrics
- behavior citation compliance
- recommended-behavior acceptance rate
- pack usage by task type and surface
- reduction in user confusion / setup retries

### Productivity metrics
- task completion rate
- time-to-first-successful-run
- token savings on BCI-assisted tasks
- reduction in repeated operator mistakes

### Moat metrics
- number of Amprealize-native traces captured
- number of reusable playbooks extracted from runs
- ranking lift from Amprealize-trained retrievers/rerankers over baseline retrieval

---

## 14. Key Decisions

1. **`AGENTS.md` stays canonical.**
2. **`work_management_guide.md` is bootstrapped selectively, not universally.**
3. **A compact runtime primer should be introduced.**
4. **Runtime infusion is a higher priority than adding more static docs alone.**
5. **BCI is the near-term moat.**
6. **Amprealize should become model-agnostic but Amprealize-native.**
7. **Custom model work is deferred until proprietary trace quality and eval coverage are strong enough.**

---

## 15. Immediate Next Steps

1. Define Knowledge Pack schema and storage model.
2. Define generation pipeline for the Amprealize Operating Primer.
3. Add profile selection to `amprealize init`.
4. Identify extension surfaces for first runtime knowledge injection.
5. Wire active-pack metadata into context and behavior retrieval surfaces.
6. Implement BCI usage telemetry that explicitly measures Amprealize-native guidance impact.
7. Create an eval set of representative Amprealize tasks to compare:
   - baseline prompting,
   - static handbook prompting,
   - Knowledge Pack + runtime retrieval,
   - and future model-adapted variants.

---

## 16. Conclusion

Amprealize does not need to choose between “ship docs” and “train a model.” The better strategy is to build a **proprietary expertise system** that uses canonical doctrine, scoped operational playbooks, adaptive bootstrap, runtime BCI-style retrieval, and compounding telemetry.

That approach gives Amprealize a credible near-term product advantage, a measurable path to ROI, and a strong long-term foundation for model specialization if and when the evidence supports it.
