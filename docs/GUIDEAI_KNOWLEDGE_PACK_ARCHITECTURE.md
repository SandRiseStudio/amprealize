# Amprealize Knowledge Pack + BCI + Adaptive Bootstrap Architecture Plan

> **Status:** Proposed
>
> **Date:** 2026-03-16
>
> **Author:** GitHub Copilot (GPT-5.4) working session
>
> **Audience:** Platform Engineering, DX, Extension, MCP, CLI, Behavior/BCI, Analytics
>
> **Related:** `AGENTS.md`, `.github/copilot-instructions.md`, `CLAUDE.md`, `docs/work_management_guide.md`, `docs/BCI_IMPLEMENTATION_SPEC.md`, `docs/INSTALLATION_AND_REPO_OPTIMIZATION_PLAN.md`, `docs/PRD.md`

---

## 1. Purpose

This document defines the target technical architecture for a **Amprealize Knowledge Pack + BCI + adaptive bootstrap** system that makes agents inherently better at using the Amprealize platform.

The architecture is designed to:
- preserve `AGENTS.md` as the canonical doctrine,
- bootstrap the right operational guidance for the right workspace,
- inject Amprealize-specific expertise at runtime,
- and learn from Amprealize-native executions over time.

The system should work across:
- CLI,
- MCP,
- VS Code extension,
- static repo instruction surfaces,
- and future web-console task execution paths.

---

## 2. Architectural Goals

1. **Model-agnostic expertise delivery**
   - Amprealize knowledge should be portable across third-party LLMs and agent hosts.

2. **Canonical source discipline**
   - Doctrine and behaviors should have one source of truth.

3. **Task-scoped runtime retrieval**
   - Agents should receive only the Amprealize knowledge relevant to the active task, role, workspace, and surface.

4. **Composable bootstrap**
   - `amprealize init` and other onboarding flows should assemble a workspace-appropriate knowledge bundle.

5. **Telemetry-backed improvement**
   - Retrieval quality, adherence, and outcome quality should be measurable and improvable.

6. **Future-ready for specialization**
   - The architecture should support later retriever/reranker/planner fine-tuning without requiring redesign.

---

## 3. Non-Goals

- Training a proprietary foundation model in the initial phases.
- Replacing canonical markdown with a hidden internal-only representation.
- Hardcoding Amprealize guidance independently into each surface.
- Building a classic RAG system centered on arbitrary factual documents rather than procedural Amprealize expertise.

---

## 4. High-Level Architecture

```text
┌──────────────────────────────────────────────────────────────────────┐
│                        Canonical Knowledge Sources                   │
├──────────────────────────────────────────────────────────────────────┤
│ AGENTS.md │ Behavior Service │ Work Mgmt Guide │ Surface Playbooks   │
└──────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    Knowledge Pack Build / Sync Layer                │
├──────────────────────────────────────────────────────────────────────┤
│ Canonical parser │ Derived artifact generator │ Pack versioner       │
└──────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      Adaptive Bootstrap Layer                       │
├──────────────────────────────────────────────────────────────────────┤
│ amprealize init │ workspace detection │ profile selection │ pack attach │
└──────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│                 Runtime Context & Knowledge Injection               │
├──────────────────────────────────────────────────────────────────────┤
│ Context resolver │ Behavior retrieval │ BCI composer │ overlay rules │
└──────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│                           Client Surfaces                           │
├──────────────────────────────────────────────────────────────────────┤
│ VS Code │ Copilot/Claude docs │ CLI │ MCP │ Web Console (future)    │
└──────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     Telemetry, Reflection, Learning                 │
├──────────────────────────────────────────────────────────────────────┤
│ Citation validation │ Run outcomes │ Trace extraction │ ranking loop │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 5. Core Concepts

## 5.1 Canonical Doctrine

Stable platform doctrine that applies broadly across Amprealize.

Primary source:
- `AGENTS.md`

Examples:
- roles,
- behavior lifecycle,
- critical rules,
- tool usage preferences,
- escalation logic,
- doc update expectations.

## 5.2 Operational Playbooks

Scoped guidance used for specific kinds of work.

Examples:
- `docs/work_management_guide.md`
- onboarding quickstarts
- future migration or extension playbooks
- infra, auth, or analytics task guides

These are not universally injected; they are attached when relevant.

## 5.3 Knowledge Pack

A versioned, machine-readable bundle of Amprealize-native expertise assembled from canonical and scoped sources.

A Knowledge Pack can be:
- attached to a workspace,
- activated by a user profile,
- injected into a task run,
- or referenced by a specific surface.

## 5.4 Runtime Overlay

A just-in-time prompt or context augmentation derived from:
- active pack,
- current task,
- active role,
- workspace profile,
- active surface,
- and current platform state/workarounds.

## 5.5 BCI Context Block

The BCI-generated, run-scoped behavior and guidance block prepended or attached to the active prompt/request.

---

## 6. Proposed System Components

## 6.1 Knowledge Source Registry

### Purpose
Track what sources are canonical, what sources are derived, and how they map into packs.

### Responsibilities
- register source files,
- classify sources by scope,
- track generation dependencies,
- expose current source versions.

### Suggested sources
- `AGENTS.md`
- `.github/copilot-instructions.md`
- `CLAUDE.md`
- `docs/work_management_guide.md`
- `docs/ONBOARDING_QUICKSTARTS.md`
- behavior records from `BehaviorService`
- future surface playbooks

### Suggested metadata
- source id
- file path or service reference
- scope (`canonical`, `operational`, `surface`, `runtime`)
- owner
- version hash
- generation eligibility

---

## 6.2 Knowledge Pack Builder

### Purpose
Build portable pack artifacts from canonical and operational sources.

### Responsibilities
- parse source content,
- normalize and segment guidance,
- classify by role/task/surface,
- create compact runtime artifacts,
- emit pack manifests.

### Outputs
1. **Pack manifest**
2. **Runtime primer**
3. **Surface overlays**
4. **Task overlays**
5. **Retrieval metadata**

### Build triggers
- source doc updates,
- behavior creation/approval/deprecation,
- profile changes,
- explicit pack rebuild command.

### Candidate command surface
- `amprealize knowledge-pack build`
- `amprealize knowledge-pack validate`
- `amprealize knowledge-pack attach`
- `amprealize knowledge-pack inspect`

---

## 6.3 Adaptive Bootstrap Service

### Purpose
Configure a workspace with the right knowledge bundle during setup.

### Responsibilities
- detect workspace signals,
- ask profile questions when detection is ambiguous,
- choose an appropriate pack,
- scaffold pack-linked files and config,
- record the active knowledge profile.

### Inputs
- workspace path
- selected storage / IDE mode
- repo type hints
- user role or persona
- explicit flags (for example, self-tracking enabled)

### Outputs
- active pack assignment
- optional generated runtime primer file
- optional `work_management_guide.md` bootstrap or link
- profile metadata in config
- extension / MCP settings hints

### Candidate workspace profiles
- `solo-dev`
- `amprealize-platform`
- `team-collab`
- `extension-dev`
- `api-backend`
- `compliance-sensitive`

### Suggested config storage
- `~/.amprealize/config.yaml`
- workspace `.amprealize/knowledge-pack.json`
- optional `.vscode/amprealize.json`

---

## 6.4 Context Resolver

### Purpose
Construct the runtime context envelope used by client surfaces and BCI.

### Responsibilities
- identify active workspace profile,
- resolve active knowledge pack,
- resolve active role,
- inspect task description and workspace type,
- surface known relevant platform workarounds,
- output a normalized context object.

### Inputs
- user/session identity
- active workspace metadata
- pack manifest
- current task description
- optional open file / active editor context
- current surface (`cli`, `vscode`, `mcp`, `copilot`, `claude`, `web`)

### Output schema (illustrative)

```json
{
  "workspace_profile": "amprealize-platform",
  "active_pack": "amprealize-platform-core@0.3.0",
  "role": "Student",
  "surface": "vscode",
  "task_type": "platform-strategy-docs",
  "recommended_behaviors": ["behavior_prefer_mcp_tools"],
  "recommended_playbooks": ["work_management_guide"],
  "runtime_constraints": [
    "Use MCP-first when available",
    "Cite behavior and role in work output"
  ],
  "known_workarounds": [
    "Prefer device flow over service principal auth for local dev"
  ]
}
```

---

## 6.5 Behavior Retrieval Service (BCI-aligned)

### Purpose
Retrieve the most relevant Amprealize behaviors and overlays for a task.

### Responsibilities
- hybrid retrieval over behavior corpus,
- rank by task, role, surface, workspace profile, and historical effectiveness,
- return top-K behaviors,
- return pack-aware and playbook-aware overlays,
- support runtime usage measurement.

### Base design
Build on the direction already described in `docs/BCI_IMPLEMENTATION_SPEC.md`.

### Retrieval inputs
- task description
- role
- workspace profile
- surface
- active knowledge pack
- file/context snippets
- prior run outcome data (optional)

### Retrieval outputs
- `recommended_behaviors`
- `recommended_overlays`
- `recommended_playbooks`
- `explanations`
- retrieval scores

### Strategy
- semantic retrieval over behavior and overlay fragments,
- keyword or rule constraints for mandatory patterns,
- reranking from Amprealize-native outcome data,
- optional task-family priors.

---

## 6.6 BCI Prompt Composer

### Purpose
Compose the runtime knowledge block injected into prompts or tool workflows.

### Responsibilities
- format relevant behaviors,
- include pack-derived runtime guidance,
- include scoped playbook notes when relevant,
- respect token budgets,
- add citation/usage expectations.

### Candidate structure

```text
Amprealize runtime context:
- Workspace profile: amprealize-platform
- Active role: Student
- Active pack: amprealize-platform-core@0.3.0

Relevant behaviors:
- behavior_prefer_mcp_tools: Use Amprealize MCP tools directly when available.
- behavior_handbook_compliance_prompt: Reconfirm applicable behaviors before major milestones.

Relevant operational guidance:
- Use work item tracking for non-trivial implementation work.
- Cite behavior and role in outputs.

Please apply the relevant Amprealize guidance explicitly when it matters.
```

### Design rules
- keep output compact,
- prefer highest-signal fragments,
- allow per-surface formatting,
- support “strict mode” for regulated or Amprealize-native repos.

---

## 6.7 Surface Adapters

### Purpose
Render the same underlying knowledge system appropriately across surfaces.

### Surfaces and examples

#### VS Code extension
- activation-time role/profile guidance,
- chat welcome suggestions,
- plan composer context hints,
- behavior detail role overlays.

#### CLI
- `amprealize init` pack selection,
- `amprealize plan` task-aware knowledge injection,
- `amprealize run` BCI mode.

#### MCP
- context-aware responses,
- pack metadata in context surfaces,
- recommended next actions in selected tool outputs.

#### Static instruction surfaces
- generated overlays consumed by `.github/copilot-instructions.md` and `CLAUDE.md`.

#### Web console (future)
- run creation assistance,
- active-pack visibility,
- post-run review and extraction.

### Key rule
Each adapter should render the same pack/context system rather than inventing its own local instruction model.

---

## 6.8 Citation and Adherence Validator

### Purpose
Measure whether Amprealize runtime knowledge was actually used.

### Responsibilities
- parse behavior references in outputs,
- record whether required overlays were applied,
- compare recommended vs used guidance,
- support audit, analytics, and retraining.

### Measurements
- valid behavior citations,
- role declaration compliance,
- work-management compliance for scoped repos,
- recommendation adoption rate,
- missed-mandatory-guidance events.

### Output uses
- dashboards,
- run summaries,
- retriever tuning,
- playbook gap analysis,
- future fine-tuning datasets.

---

## 6.9 Reflection and Learning Loop

### Purpose
Turn Amprealize-native runs into better future expertise.

### Responsibilities
- extract candidate behaviors or overlays from successful runs,
- identify recurring operator friction,
- find weak or overlong guidance,
- update ranking and pack composition,
- generate candidate golden traces.

### Learning artifacts
- new behavior proposals,
- overlay effectiveness scores,
- pack health metrics,
- role/surface-specific prompt fragments,
- gold traces for future model adaptation.

---

## 7. Knowledge Pack Data Model

## 7.1 Pack Manifest (illustrative)

```json
{
  "pack_id": "amprealize-platform-core",
  "version": "0.3.0",
  "scope": "workspace",
  "workspace_profiles": ["amprealize-platform"],
  "surfaces": ["vscode", "cli", "mcp", "copilot", "claude"],
  "sources": [
    {
      "type": "file",
      "ref": "AGENTS.md",
      "scope": "canonical"
    },
    {
      "type": "file",
      "ref": "docs/work_management_guide.md",
      "scope": "operational",
      "conditional": true
    }
  ],
  "doctrine_fragments": [
    "role_declaration_protocol",
    "mcp_first",
    "cite_behavior_and_role"
  ],
  "behavior_refs": [
    "behavior_prefer_mcp_tools",
    "behavior_handbook_compliance_prompt"
  ],
  "task_overlays": [
    "platform-doc-writing",
    "work-item-management"
  ],
  "surface_overlays": [
    "vscode-chat",
    "cli-init"
  ],
  "constraints": {
    "strict_role_declaration": true,
    "strict_behavior_citation": true
  }
}
```

## 7.2 Overlay Fragment (illustrative)

```json
{
  "overlay_id": "platform-doc-writing",
  "kind": "task",
  "applies_to": {
    "task_family": ["docs", "strategy", "architecture"],
    "workspace_profiles": ["amprealize-platform"]
  },
  "instructions": [
    "Prefer Amprealize-native terms and surfaces",
    "Reference relevant canonical docs",
    "Keep recommendations aligned with MCP-first behavior"
  ],
  "retrieval_keywords": ["docs", "strategy", "architecture", "amprealize"]
}
```

---

## 8. Bootstrap Flow Design

## 8.1 `amprealize init` sequence

```text
1. Detect workspace signals
2. Ask profile questions if confidence is low
3. Select default knowledge pack
4. Decide which operational playbooks are relevant
5. Generate runtime primer / config metadata
6. Attach extension / MCP / instruction overlays
7. Persist pack activation and bootstrap evidence
```

## 8.2 Detection signals

- presence of `AGENTS.md`
- Amprealize package imports
- extension workspace structure
- `mcp/` folder
- work-item / board / compliance usage
- repo tags or setup flags
- explicit user selections

## 8.3 Scoped playbook rules

`work_management_guide.md` should be enabled when:
- workspace profile = `amprealize-platform`, or
- user enables `amprealize_work_tracking: true`, or
- project setup enables work item execution / board workflows.

---

## 9. Runtime Flow Design

## 9.1 Task-start runtime flow

```text
1. Surface receives task or user action
2. Context Resolver builds normalized runtime context
3. Behavior Retrieval Service fetches top-K relevant behaviors
4. Overlay selector adds pack/task/surface guidance
5. BCI Composer builds runtime context block
6. Surface adapter injects guidance into the active task flow
7. Validator records adoption and citations afterward
```

## 9.2 Example: VS Code chat task

```text
User opens Amprealize Chat
→ workspace profile resolved as amprealize-platform
→ current task inferred from prompt/editor context
→ behaviors + work-management overlay retrieved
→ runtime block attached to the prompt
→ output validated for role declaration and behavior citation
→ telemetry sent for recommendation quality
```

## 9.3 Example: CLI `amprealize run`

```text
amprealize run "Implement X"
→ context resolved from workspace and config
→ active pack loaded
→ BCI retrieval performed
→ runtime block composed
→ task executed
→ citations and compliance logged
```

---

## 10. Telemetry and Evaluation Design

## 10.1 Required telemetry events

- `knowledge_pack.activated`
- `knowledge_pack.attached_to_workspace`
- `knowledge_pack.overlay_selected`
- `runtime_context.resolved`
- `bci.behaviors_retrieved`
- `bci.prompt_composed`
- `bci.citations_validated`
- `guidance.adoption_scored`
- `reflection.overlay_candidate_extracted`

## 10.2 Core metrics

### Bootstrap metrics
- time to configured workspace
- pack selection override rate
- % of workspaces with active pack

### Runtime metrics
- behavior retrieval rate
- overlay adoption rate
- citation compliance
- task-start success rate
- token savings

### Learning metrics
- extracted overlay acceptance rate
- retriever lift over baseline
- pack effectiveness by surface/profile
- reduction in repeated operator mistakes

---

## 11. Storage Strategy

## 11.1 Canonical sources
- source-controlled markdown and service-backed behavior records

## 11.2 Derived artifacts
- pack manifests in Amprealize storage
- generated runtime primer files in workspace or cache
- overlay fragments stored in Amprealize-managed metadata tables

## 11.3 Runtime cache
- per-session resolved context cache
- per-pack compiled fragment cache
- retrieval cache for common task classes

## 11.4 Telemetry warehouse
- store recommendation, usage, and outcome facts for reporting and retriever tuning

---

## 12. Integration Points in Current Repo

## 12.1 Canonical sources
- `/Users/nick/amprealize/AGENTS.md`
- `/Users/nick/amprealize/.github/copilot-instructions.md`
- `/Users/nick/amprealize/CLAUDE.md`
- `/Users/nick/amprealize/docs/work_management_guide.md`

## 12.2 Bootstrap and config
- `/Users/nick/amprealize/amprealize/cli.py`
- `/Users/nick/amprealize/docs/INSTALLATION_AND_REPO_OPTIMIZATION_PLAN.md`

## 12.3 Runtime context and behavior systems
- `/Users/nick/amprealize/amprealize/behavior_service.py`
- `/Users/nick/amprealize/amprealize/bci_service.py`
- `/Users/nick/amprealize/amprealize/mcp_server.py`

## 12.4 Extension surfaces
- `/Users/nick/amprealize/extension/src/extension.ts`
- `/Users/nick/amprealize/extension/src/panels/AmprealizeChatPanel.ts`
- `/Users/nick/amprealize/extension/src/webviews/PlanComposerPanel.ts`
- `/Users/nick/amprealize/extension/src/webviews/BehaviorDetailPanel.ts`
- `/Users/nick/amprealize/extension/src/providers/AuthProvider.ts`
- `/Users/nick/amprealize/extension/src/panels/ProjectSettingsPanel.ts`

These are the most natural first integration points for a phased implementation.

---

## 13. Security and Governance Considerations

1. **Canonical authority must be explicit**
   - derived pack content must declare source provenance.

2. **Operational guidance can become policy-sensitive**
   - some overlays may encode compliance or security constraints and must be versioned/audited.

3. **User/workspace scoping matters**
   - not all users should receive the same org or repo overlays.

4. **Trace reuse must respect consent and governance**
   - before using traces for tuning or model adaptation, define storage, redaction, and reuse policy.

5. **Generated overlays must be testable**
   - pack generation should have validation checks to prevent silent drift or invalid runtime guidance.

---

## 14. Phased Implementation Plan

## Phase 1 — Foundations

### Scope
- Knowledge Source Registry
- pack schema
- pack builder MVP
- runtime primer generation
- config model for active pack

### Deliverables
- pack manifest schema
- pack build/validate commands
- active pack persistence in config
- initial `solo-dev` and `amprealize-platform` profiles

## Phase 2 — Adaptive Bootstrap

### Scope
- workspace detection
- profile selection in `amprealize init`
- scoped playbook enablement
- extension/project surface awareness of active pack

### Deliverables
- `amprealize init` profile flow
- selective work-management guide enablement
- pack attach/inspect commands
- extension settings integration

## Phase 3 — Runtime Injection + BCI Alignment

### Scope
- Context Resolver
- retrieval service inputs expanded with profile/surface/pack
- overlay selector
- BCI prompt composer updated to include runtime overlays

### Deliverables
- normalized runtime context contract
- pack-aware retrieval
- extension chat and CLI run injection
- citation/adherence validation updates

## Phase 4 — Reflection and Learning

### Scope
- extracted overlay candidates
- effectiveness scoring
- pack analytics dashboards
- reranking loops

### Deliverables
- pack and overlay quality reports
- golden trace candidate pipeline
- recommendation lift dashboards
- design memo on specialist model opportunities

---

## 15. Verification Strategy

### Functional verification
- correct pack attached for representative workspace types
- correct playbook enablement in scoped cases
- correct runtime context resolution by surface
- BCI prompt includes pack and behavior overlays when expected

### Quality verification
- no drift between canonical doctrine and generated primer fragments
- pack selection accuracy in representative repos
- recommendation precision improves over baseline
- citation compliance remains parseable and high

### Product verification
- lower setup confusion,
- higher behavior reuse,
- lower repeated operator errors,
- improved task success for Amprealize-native workflows.

---

## 16. Open Questions

1. Should packs be stored only in Amprealize services, or also written to workspace files for transparency/debuggability?
2. Should runtime primers be regenerated eagerly on every relevant source change, or lazily on access?
3. Should some overlays be marked mandatory for specific repo profiles?
4. Should pack composition be rule-based first, ML-ranked later, or hybrid from the start?
5. What trace governance model is required before using run data for model adaptation?

---

## 17. Recommended First Engineering Slice

If implementation begins immediately, the highest-leverage first slice is:

1. define the pack manifest schema,
2. build a compact runtime primer from `AGENTS.md`,
3. add active-pack selection to `amprealize init`,
4. expose active-pack metadata in context surfaces,
5. inject the pack plus retrieved behaviors into the VS Code chat/task-start flow.

That slice creates end-to-end value with minimal speculative infrastructure and establishes the architectural spine for later BCI and learning improvements.

---

## 18. Conclusion

The right technical architecture is a layered one:
- canonical doctrine at the core,
- versioned Knowledge Packs as the transport,
- adaptive bootstrap as the provisioning mechanism,
- BCI and runtime overlays as the intelligence layer,
- and telemetry/reflection as the compounding loop.

This architecture gives Amprealize a practical path to making agents inherently effective on Amprealize tasks without prematurely locking the product into expensive proprietary-model commitments.
