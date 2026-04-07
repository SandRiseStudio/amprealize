# BreakerAmp Orchestrator – Product Requirements Document

## Document Control
- **Status:** Draft – required before implementation
- **Last Updated:** 2025-11-06
- **Author(s):** Platform & DevOps (cross-agent)
- **Surfaces:** CLI, REST API, VS Code extension, MCP tools
- **Upstream References:** `PRD.md` (BreakerAmp section), `PRD_NEXT_STEPS.md` Task 6, `ACTION_REGISTRY_SPEC.md`, `MCP_SERVER_DESIGN.md`, `ACTION_SERVICE_CONTRACT.md`, `COMPLIANCE_SERVICE_CONTRACT.md`, `deployment/PODMAN.md`

## Charter
BreakerAmp is the single front door for every Amprealize infrastructure mutation. It replaces direct Podman, Compose, or cluster access with a declarative manifest workflow (`plan → apply → status → destroy`) that:
1. Keeps audit evidence consistent through ActionService and ComplianceService.
2. Provides deterministic environment manifests that can be replayed or diffed.
3. Emits lifecycle telemetry that feeds the PRD KPIs (behavior reuse, token savings, completion, compliance) plus new infra KPIs (environment reuse %, average lifespan, teardown success rate).
4. Works equally from CLI, IDE, MCP, API, and standalone repos so that Strategist → Teacher → Student workflows never bypass compliance.

## Personas & Responsibilities
| Persona | Responsibilities inside BreakerAmp |
| --- | --- |
| **Strategist / Tech Lead** | Drafts `breakeramp.plan` requests, cites behaviors, attaches compliance checklist IDs, and approves blueprints.
| **Student / Engineer** | Executes `apply`, monitors `status`, runs tests, and triggers `destroy` in traps or failure handlers.
| **Teacher / Reviewer** | Verifies manifests, confirms telemetry, and records evidence in ComplianceService before closing runs.
| **DevOps Operator** | Curates blueprint catalog, enforces Podman/AppleHV guardrails, maintains Terraform/Kubernetes runners.
| **Compliance & Platform Admin** | Audits ActionService logs, validates teardown success, and monitors MetricsService dashboards for infra KPIs.
| **External Repo Consumer** | Uses standalone CLI/MCP endpoints with device-flow auth and never needs access to Amprealize source.

All flows must respect the Strategist → Teacher → Student pipeline described in `AGENTS.md` and `MCP_SERVER_DESIGN.md`.

## Success Criteria
- **Infra Routing:** 100% of environment provisioning, updates, and teardowns flow through BreakerAmp before GA.
- **Telemetry:** `breakeramp.*` events cover 100% of lifecycle transitions with run IDs, action IDs, and checklist IDs to satisfy the 70/30/80/95 PRD metrics plus infra KPIs (avg lifespan, reuse %, teardown success >99%).
- **Parity:** CLI, REST, MCP, VS Code panel, and standalone usage share identical request/response schemas and auth (device flow tokens).
- **Compliance Evidence:** Every plan/apply/destroy call logs an ActionService record, links to ComplianceService checklist entries, and appears in PROGRESS_TRACKER sequences.
- **Podman Guardrails:** Engineers cannot leave the AppleHV VM running while BreakerAmp mode is active; warnings and docs guide safe toggling between modes.

## Lifecycle Interfaces
All interface contracts share core metadata: `run_id`, `action_id`, `actor_surface`, `checklist_id`, `behavior_ids`, and `manifest_digest`. Requests are JSON over REST and structured arguments in CLI/MCP. Responses return a versioned schema (`schema_version` field). Each verb triggers telemetry and ActionService logging as described below.

### `breakeramp.bootstrap`
**Purpose:** Initialize a new project with BreakerAmp configuration and blueprints.

**Inputs**
- `directory` (target path, defaults to current working directory).
- `include_blueprints` (boolean, copies packaged blueprints to local config).
- `blueprints` (optional list of specific blueprint IDs to copy).
- `force` (boolean, overwrites existing files).
- `env_template` (optional path to custom `environments.yaml` template).

**Outputs**
- `environments.yaml` created at `config/breakeramp/environments.yaml`.
- `blueprints/` directory populated with selected blueprints.
- JSON summary of created/skipped files.

**Operational Requirements**
1. Must support running outside of the Amprealize repository (standalone mode).
2. Must correctly handle blueprint normalization (e.g., `postgres.timescale.test` vs `postgres.timescale.test.yaml`).
3. Telemetry event `breakeramp.bootstrap.completed` records the number of blueprints copied and the target directory hash.

### `breakeramp.plan`
**Purpose:** Declare desired topology, compliance tier, TTL, and checklist references.

**Inputs**
- `blueprint_id` (e.g., `local-test-suite`, `postgres.timescale.test`).
- `lifetime` (`ISO8601 duration`, default 90m, bounded by policy).
- `compliance_tier` (`dev`, `prod-sim`, `pci-sandbox`).
- `checklist_id` (from ComplianceService, required when `AMPREALIZE_TEST_INFRA_MODE=breakeramp`).
- `behaviors` (array of behavior IDs strategists cite; default retrieved via trigger keywords).
- `variables` (arbitrary map for blueprint inputs: scale, feature flags, dataset fixtures, secrets references per `SECRETS_MANAGEMENT_PLAN.md`).

**Outputs**
- `plan_id` and `amp_run_id` (stable identifier for the lifecycle).
- `signed_manifest` (YAML or JSON) with SHA256 digest + ActionService record ID.
- `environment_estimates` (cost, memory footprint, region, expected boot duration).

**Operational Requirements**
1. `amprealize breakeramp plan ...` must automatically call `amprealize record-action --artifact ACTION_REGISTRY_SPEC.md --summary "breakeramp.plan"` attaching the manifest before returning.
2. CLI/UI must warn if Podman AppleHV VM is running, pointing to `deployment/PODMAN.md`, and block unless user opts into legacy mode.
3. Returned manifest lives at `~/.amprealize/breakeramp/manifests/<plan_id>.json` for standalone consumers.
4. Telemetry event `breakeramp.plan.created` records blueprint, tier, lifetime, strategists, and cited behaviors.

### `breakeramp.apply`
**Purpose:** Execute the signed manifest through Terraform runners, Kubernetes operators, or cloud APIs.

**Inputs**
- `plan_id` or inline manifest (`--manifest -`). Inline manifests must be byte-identical to the signature digest.
- `watch` flag enabling RunService streaming (default true from CLI/IDE).
- `resume` flag to rehydrate paused environments (ensures idempotent apply).

**Outputs**
- `environment_outputs` JSON blob (DSNs, host/port pairs, secrets handles, telemetry topics). Stored at `~/.amprealize/breakeramp/environments/<amp_run_id>.json` and surfaced to `scripts/run_tests.sh` via STDOUT when `--export env` is requested.
- `status_stream` SSE or WebSocket pointer for real-time updates.
- `action_id` referencing ActionService entry capturing apply evidence.

**Operational Requirements**
1. Apply must emit RunService updates: `PENDING → PROVISIONING → HYDRATING_DATA → READY` (or failure states) with timestamps.
2. Telemetry must include `breakeramp.apply.started`, `breakeramp.apply.duration_ms`, `breakeramp.apply.failed`, plus resource usage counters.
3. ComplianceService receives a `record-step` call noting provisioning evidence (even when triggered via automation) referencing the same checklist ID.
4. CLI must block direct pod/kube commands; only BreakerAmp backends talk to infrastructure.

### `breakeramp.status`
**Purpose:** Provide idempotent polling plus streaming views into lifecycle events.

**Capabilities**
- Poll by `amp_run_id` for summary (phase, percent complete, active components, health checks, cost burn).
- Stream SSE/WS updates for IDE panels (Plan Composer, Run Detail) and CLI `--watch` mode.
- Surface derived telemetry (token savings, environment reuse) once available.

**Outputs**
```json
{
  "amp_run_id": "amp-123",
  "phase": "HYDRATING_DATA",
  "progress_pct": 42,
  "checks": [{"name": "postgres", "status": "healthy", "last_probe": "ISO8601"}],
  "environment_outputs_path": "~/.amprealize/breakeramp/environments/amp-123.json",
  "next_maintenance": "ISO8601",
  "telemetry": {
    "token_savings_pct": 0.31,
    "behavior_reuse_pct": 0.72
  }
}
```

**Operational Requirements**
1. `status` API aligns with RunService representation so IDE Execution Tracker can mirror CLI output verbatim.
2. Missing outputs must yield actionable errors (e.g., manifest revoked) and instruct Student to destroy.
3. Telemetry event `breakeramp.status.streamed` captures whether clients consumed streaming updates (used for parity and alerting).

### `breakeramp.destroy`
**Purpose:** Teardown all resources, release quotas, and mark Compliance evidence complete.

**Inputs**
- `amp_run_id` (required) or `plan_id` (resolved to run ID).
- `cascade` flag controlling dependent resource teardown (default true).
- `reason` enumerations: `POST_TEST`, `FAILED`, `ABANDONED`, `MANUAL`.

**Outputs**
- `teardown_report` (list of resources removed, durations, incidents).
- `action_id` for ActionService entry; appended to PROGRESS_TRACKER.

**Operational Requirements**
1. Telemetry events: `breakeramp.destroy.started`, `breakeramp.destroy.completed`, `breakeramp.destroy.duration_ms`, `breakeramp.destroy.failed`.
2. ComplianceService step `teardown_complete` must be recorded with the same checklist ID.
3. `scripts/run_tests.sh` installs a `trap` to call destroy when it previously called plan/apply. CLI must expose `--skip-destroy` only for blue/green workflows with explicit approval.
4. Teardown success rate target: >99% within 5 minutes for typical blueprints; failures auto-page DevOps.

## Run Tests Harness Handshake (`scripts/run_tests.sh`)
BreakerAmp becomes the default provisioner once Phase 1 ships. The harness must observe the following:
1. `AMPREALIZE_TEST_INFRA_MODE` defaults to `breakeramp`. Users may set `legacy` to keep Podman bootstrap until GA.
2. When in BreakerAmp mode the script:
   - Calls `amprealize breakeramp plan --blueprint local-test-suite --lifetime ${RUN_TESTS_TTL:-90m} --checklist ${CHECKLIST_ID}` before any Podman commands.
   - Pipes the signed manifest to `amprealize breakeramp apply --manifest - --watch` and waits for readiness by polling `breakeramp.status` instead of port checks.
   - Consumes `environment_outputs` to export DSNs (`AMPREALIZE_PG_HOST_*`, `AMPREALIZE_REDIS_HOST`, `STAGING_API_URL`) for pytest.
   - Installs a `trap` to run `amprealize breakeramp destroy --run-id $AMP_RUN_ID --reason POST_TEST`.
   - Logs each verb with ActionService and ComplianceService using the same checklist ID used for Behavior/Workflow evidence.
3. The harness must detect a running Podman machine and warn the user to stop it (`podman machine stop`) before calling BreakerAmp to free the AppleHV 4–8 GB footprint.
4. Legacy mode retains Podman bootstrap but prints reminders that standalone support ends once BreakerAmp GA launches.
5. `RUN_TESTS_TTL`, `RUN_TESTS_BLUEPRINT`, and `RUN_TESTS_COMPLIANCE_CHECKLIST` env vars must be documented so CI can override defaults.

## Standalone CLI / MCP Usage
Requirements for users operating BreakerAmp outside the Amprealize repo:
- CLI commands accept manifests via `--manifest ./breakeramp/local-dev.yaml` or STDIN. Responses store outputs at `~/.amprealize/breakeramp/environments/<run_id>.json` for reuse.
- `amprealize breakeramp bootstrap --directory <path>` scaffolds `config/breakeramp/environments.yaml` plus optional packaged blueprints so external repos can start from a known-good manifest without hunting through the Amprealize tree. `--include-blueprints` copies every packaged blueprint, `--blueprint <id>` targets a subset, and `--force` safely overwrites existing scaffolding.
- Authentication uses the AgentAuth device flow; tokens cached under `~/.amprealize/breakeramp/credentials.json`. No kubeconfig or cloud credentials leak to users.
- REST endpoints live under `/v1/breakeramp/*` with OpenAPI definitions checked into `docs/api/openapi_breakeramp.yaml` (to be authored alongside implementation).
- MCP tools: `breakeramp.plan`, `breakeramp.apply`, `breakeramp.status`, `breakeramp.destroy`. They must mirror CLI parameters, return the same JSON, and emit the same telemetry/action logs.
- Every CLI invocation chains to `amprealize record-action ...` and, when applicable, to `amprealize compliance record-step ...` so standalone adopters still feed the evidence pipeline.
- Docs must restate Podman guardrails so non-Amprealize users stop their AppleHV VM before provisioning and restart it only for legacy Compose stacks.

## Telemetry, Action Logging, and Compliance Evidence
- **Telemetry Events:**
  - `breakeramp.plan.created`, `breakeramp.plan.rejected` (validation failures).
  - `breakeramp.apply.started`, `breakeramp.apply.duration_ms`, `breakeramp.apply.failed`.
  - `breakeramp.status.streamed`, `breakeramp.status.alerted` (health regressions).
  - `breakeramp.destroy.started`, `breakeramp.destroy.completed`, `breakeramp.destroy.failed`.
  - All events include: `amp_run_id`, `plan_id`, `action_id`, `checklist_id`, `behavior_ids`, `actor_surface`, `token_savings_pct`, `behavior_reuse_pct`, `duration_ms`, `resource_counts`, `cost_estimate`.
- **MetricsService Integration:** Map telemetry into `behavior_usage_events`, `token_usage_events`, `completion_events`, and new `infra_environment_events` table (schema TBD) to support dashboards.
- **ActionService Logging:** Each verb automatically records an action referencing `behavior_wire_cli_to_orchestrator` and `behavior_update_docs_after_changes` behaviors with summaries such as `breakeramp.plan blueprint=local-test-suite`.
- **ComplianceService Evidence:** Checklists must include at least `plan_submitted`, `apply_completed`, `status_monitored`, `tests_executed`, `destroy_verified`. CLI should auto-log these steps when `--checklist` is provided, but allow manual overrides for advanced workflows.
- **Audit Trails:** All manifests, outputs, and telemetry records must be immutable and replayable via `amprealize replay amp_run_id` to satisfy `REPRODUCIBILITY_STRATEGY.md`.

## Podman / AppleHV Guardrails
- BreakerAmp mode requires the Podman AppleHV VM to be stopped to reclaim its 4–8 GB RAM footprint. Tooling must:
  1. Detect running Podman machines (`podman machine list --format json`).
  2. Print a blocking warning that lists the VM name, allocated CPUs, and memory, referencing `deployment/PODMAN.md`.
  3. Offer a `--force-podman` override only when `AMPREALIZE_TEST_INFRA_MODE=legacy`.
  4. Document the steps to restart Podman when engineers switch back to legacy mode (`podman machine start --cpus 4 --memory 4096`).
  5. Explain why AppleHV virtualization keeps memory reserved even when containers stop, so users intentionally shut the VM down during BreakerAmp sessions.
- Docs and CLI help must emphasize that BreakerAmp eliminates the need for Podman-managed compose stacks during default runs, reducing double provisioning and macOS oversubscription.

## Parity & Observability Requirements
- Publish OpenAPI + JSON Schema definitions for every verb; ensure CLI, REST, MCP, and VS Code panels generate from the same source of truth.
- VS Code extension must add an BreakerAmp panel showing lifecycle state using the same `status` schema. Reuse Run Detail Panel components for streaming output.
- MCP tools must be wired before GA so agents running inside Claude Desktop / Cursor / Cline can call BreakerAmp.
- `ACTION_REGISTRY_SPEC.md` needs entries for `breakeramp.plan|apply|status|destroy`, including example payloads and replay steps.
- Tests must follow `TESTING_GUIDE.md` using `pytest` and cover: manifest validation, Podman guardrail warnings, ActionService logging, Compliance logging, telemetry emission, standalone credential caching, and `scripts/run_tests.sh` handshake behavior (`AMPREALIZE_TEST_INFRA_MODE` switching logic).

## Self-Testing Strategy
To ensure BreakerAmp reliability, we employ a "dogfooding" strategy where BreakerAmp is used to test itself:
1. **Bootstrap Verification:** `tests/test_breakeramp_bootstrap.py` uses the `BreakerAmpService` to bootstrap a temporary workspace, verifying that blueprints and configuration are correctly scaffolded.
2. **CLI Integration:** `tests/test_cli_breakeramp.py` invokes the CLI commands against the bootstrapped workspace, ensuring the CLI correctly maps arguments to the service layer.
3. **Infrastructure Bootstrapping:** Future tests will use `amprealize breakeramp apply` to provision the test infrastructure itself (replacing the legacy `scripts/run_tests.sh` Podman logic), effectively using the tool to create the environment for its own tests.

## Open Questions & Next Steps
1. Finalize blueprint catalog format (YAML vs JSON) and sharing mechanism for external repos.
2. Define schema for the new `infra_environment_events` TimescaleDB table and dashboards showing reuse %, avg lifespan, and teardown SLAs.
3. Decide how BreakerAmp handles long-lived sandboxes (pause/resume vs destroy/recreate) while satisfying ActionService replay constraints.
4. Determine if we need a migration path for existing Podman Compose configs (automated manifest converter) before GA.
5. Update `PRD_ALIGNMENT_LOG.md`, `PRD_NEXT_STEPS.md`, and `BUILD_TIMELINE.md` after implementation to document evidence per `behavior_update_docs_after_changes`.
