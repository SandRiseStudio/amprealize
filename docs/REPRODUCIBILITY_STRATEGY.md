# Reproducible Build Strategy – Metacognitive Behavior Platform

## Goals
- **Auditability:** Every action taken to create and evolve the platform must be recorded with metadata (who, when, why, outcomes).
- **Reproducibility:** Another team can replay the sequence to bootstrap their own deployment or to regenerate artifacts.
- **Parity:** API, platform UI, CLI, and MCP tools expose identical capabilities for capturing and replaying build actions.
- **Evidence for PRD Metrics:** Action logs provide data for behavior reuse, token savings, task completion, and compliance coverage targets defined in `PRD.md`.
- **Progress Transparency:** Maintain `PROGRESS_TRACKER.md` so replayed actions surface milestone status alongside artifacts.

## Action Taxonomy
Each action aligns with phases captured in `BUILD_TIMELINE.md` and categories in `AGENTS.md` behaviors.
- **Handbook Creation** – authoring `AGENTS.md` and updating behaviors.
- **Research References** – adding source documents (`Metacognitive_reuse.txt`).
- **Product Definition** – creating and updating `PRD.md`, `MCP_SERVER_DESIGN.md`.
- **Agent Enablement** – generating agent playbooks.
- **Review & Feedback** – recording outputs in `PRD_AGENT_REVIEWS.md` and `PRD_NEXT_STEPS.md`.
- **Follow-up Tracking** – action plans, issue links, and progress logs.

## Capture Mechanisms
1. **Action Registry Service** (part of MCP server) storing entries with:
   - `action_id`, `timestamp`, `actor`, `role`, `artifact_path`, `summary`, `behaviors_cited`, `related_run_id`.
2. **CLI Hooks:** Commands like `amprealize record-action --artifact PRD.md --summary "Draft PRD" --behaviors behavior_handbook_compliance_prompt`.
3. **Platform UI Workflow:** After completing a task, Strategist/Teacher/Student fill out action forms linked to the registry.
4. **APIs / MCP Tools:** `actions.create`, `actions.list`, `actions.replay` endpoints/tools for automation and integration with agent frameworks.
5. **Git Metadata Integration:** Optional webhook that correlates commits with action entries for end-to-end traceability.

## Replay Workflow
1. **Select Timeline** – Retrieve action sequence via `actions.list` filtered by date range or milestone.
2. **Provision Resources** – Use MCP tools to recreate required behaviors, PRDs, and playbooks in target environment.
3. **Automated Execution** – CLI command `amprealize replay --from build_timeline` replays actions, generating artifacts and logs (idempotent where possible).
4. **Verification** – Generate report comparing replayed artifacts against reference checksums or validation tests.
5. **Progress Sync** – Replay pipeline updates `PROGRESS_TRACKER.md` entries and records completion via `actions.create` to reflect milestone status.

## Parity Enforcement
- **Capability Matrix Integration:** Each action type recorded in matrix with corresponding API path, MCP tool name, CLI command, and UI flow.
- **Contract Tests:** Ensure `actions.create` used by CLI matches UI form submission behavior.
- **Docs & Tutorials:** Provide guided walkthrough demonstrating replay on fresh workspace.

## Security & Compliance
- Actions include role-based attribution; compliance agent verifies checklist alignment for each entry.
- Audit logs stored in append-only medium; access limited by RBAC scopes.
- Sensitive summaries redacted or classified as needed before storage.

## Next Steps
- Extend `MCP_SERVER_DESIGN.md` with `ActionService` component.
- Update CLI spec with `record-action`, `list-actions`, and `replay` commands.
- Add parity tests covering action capture across surfaces.
- Draft user guide in `README.md` describing how to replay platform bootstrap.
