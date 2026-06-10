# Agent Operating Contract

> **TL;DR**: Declare your role at task start. **Retrieve behaviors before work** (`behaviors.getForTask`). Prefer Amprealize MCP tools. Log with Raze. Environments with BreakerAmp. Never hardcode secrets; run `pre-commit` before push. Cite **behavior + role** in output.
>
> **Deep handbook** (roles, lifecycle, full behavior catalog, MCP details, design routing): [`docs/agent-handbook/README.md`](docs/agent-handbook/README.md)
>
> Work tracking: `WORK_MANAGEMENT_GUIDE.md`

---

## Before every task

1. **Retrieve behaviors** (required):
   - MCP: `behaviors.getForTask` with `task_description` and `role` (`Student` | `Teacher` | `Metacognitive Strategist`)
   - CLI fallback: `amprealize behaviors get-for-task "<task>" --role Student`
2. **Declare role** at task start with rationale and behaviors you will apply.
3. **Amprealize platform work**: follow [MCP startup](docs/agent-handbook/mcp-startup.md) and [dual-repo parity](#amprealize-dual-repo-parity) below.

Cite in output: `Following \`behavior_use_raze_for_logging\` (Student): ...`

If the same workaround appears **3+ times** without a behavior, escalate to Strategist or propose via `behaviors.propose`.

---

## Critical rules

| Rule | Behavior | Why |
|------|----------|-----|
| Retrieve behaviors before work | `behaviors.getForTask` | Procedural guidance, telemetry |
| Prefer MCP over CLI/API | `behavior_prefer_mcp_tools` | Schemas, parity |
| Structured logging | `behavior_use_raze_for_logging` | Queryable telemetry |
| Environments | `behavior_use_breakeramp_for_environments` | Blueprints, compliance |
| No secrets in repo | `behavior_prevent_secret_leaks` | Security |
| Pre-commit before push | `behavior_prevent_secret_leaks` | Leak prevention |
| Update docs on API/workflow changes | `behavior_update_docs_after_changes` | Alignment |
| AI platform / concept changes | `behavior_maintain_ai_learning_wiki` | Teaching layer |

---

## Roles (summary)

| Role | Use when |
|------|----------|
| **Student** | Routine execution; existing behavior covers the task |
| **Teacher** | Examples, docs, reviews, validation |
| **Metacognitive Strategist** | Novel patterns, RCA, architecture, new behaviors |

**Declaration** (required):

```
🎭 Role: Student
📋 Rationale: ...
🔗 Behaviors: `behavior_...`, ...
```

**Escalation**: Student → Teacher (teaching/review); Student → Strategist (3+ repeats, no behavior, architecture).

Full role protocol, lifecycle, proposals, checklists: [`docs/agent-handbook/behavior-lifecycle.md`](docs/agent-handbook/behavior-lifecycle.md)

---

## Design workflow (summary)

For UI work, do not default to a single generic style. Order of operations:

1. **Product/design decisions** — `layers-orient` and related Layers skills when scope is unclear.
2. **Drafts / directions** — `superdesign` when exploration helps (CLI logged in).
3. **Implementation** — `design-taste-frontend` (marketing/landing/portfolio/redesigns) or `impeccable` (app UI, dashboards, forms, design systems); `ui-ux-pro-max` for general UI/UX implementation patterns.
4. **Polish** — `refactor-ui` before calling done.
5. **Accessibility** — `behavior_validate_accessibility` + smoke/build check.

Details: [`docs/agent-handbook/design-workflow.md`](docs/agent-handbook/design-workflow.md)

---

## Amprealize MCP startup (summary)

At session start for Amprealize tasks: `tools.guide` → `auth.authStatus` (auth refresh/login if needed) → `behaviors.getForTask` → `context.getContext` → `tools.activeGroups` → `tools.catalog` (activate groups as needed).

Use `original_name` in docs; `normalized_name` in Cursor (e.g. `workitems_get`). Prefer session defaults for `user_id`, `org_id`, `project_id`.

Full steps: [`docs/agent-handbook/mcp-startup.md`](docs/agent-handbook/mcp-startup.md)

---

## Amprealize dual-repo parity

Platform work defaults to **both** repos unless the user says OSS-only or Enterprise-only:

- **OSS**: this repository root (`amprealize`)
- **Enterprise**: `amprealize-enterprise` (sibling checkout; set `AMPREALIZE_ENTERPRISE_REPO_PATH` if layout differs)

Implement features, MCP tools, manifests, tests, and docs in both; validate in both; state parity in the summary.

---

## Agent etiquette

- **Tests**: Smallest relevant check after substantive changes (`pytest`, `npm run build`, lint). Use `run_tests.sh` (BreakerAmp mode for heavier runs). Record command and outcome.
- **Secrets**: Env vars / `.env`; never hardcode. On leak: `behavior_rotate_leaked_credentials`.
- **MCP-first** when available; avoid loopback HTTP unless architecture requires it.
- **Edits**: Focused diffs; diagnose root cause; preserve compatibility.
- **Docs**: Update `README.md`, `PRD.md`, `BUILD_TIMELINE.md` when workflows change; wiki for AI-related work when applicable.
- **Data**: No silent discard/mutation; invertible migrations or documented recovery.
- **Git**: No force-push or destructive history rewrite unless the user explicitly requests it.

---

## Standalone packages

| Package | Purpose |
|---------|---------|
| `packages/raze/` | Structured logging |
| `packages/breakeramp/` | Environments / containers |

Pattern: zero core deps → hooks → optional `[cli]`, `[fastapi]` → thin `amprealize/<name>/` wrapper. See `behavior_extract_standalone_package` in the catalog.

---

## Quick triggers (essential)

Before any task: **`behaviors.getForTask`**. Full table: [`docs/agent-handbook/behavior-catalog.md`](docs/agent-handbook/behavior-catalog.md)

| Keywords | Behavior(s) | Role |
|----------|-------------|------|
| MCP, IDE extension | `behavior_prefer_mcp_tools` | Student |
| logging, telemetry | `behavior_use_raze_for_logging` | Student |
| environment, container, blueprint | `behavior_use_breakeramp_for_environments` | Student |
| secret, credential, leak | `behavior_prevent_secret_leaks`, `behavior_rotate_leaked_credentials` | Student |
| run status, SSE, execution record | `behavior_unify_execution_records` | Student |
| storage, audit, Postgres | `behavior_align_storage_layers` | Student |
| CORS, auth, security surface | `behavior_lock_down_security_surface` | Student |
| UI / UX / redesign | Design workflow + `behavior_validate_accessibility` | Teacher |
| API, OpenAPI, contract | `behavior_design_api_contract` | Teacher |
| PostgreSQL, Alembic, migration | `behavior_migrate_postgres_schema` | Student |
| MCP tool schema, Copilot Chat | `behavior_design_mcp_tool_schema` | Student |
| CI/CD, deploy | `behavior_orchestrate_cicd` | Student |
| incident, outage | `behavior_triage_incident` | Student |
| new feature scope | `behavior_define_feature_scope` | Teacher |
| work items, GWS naming | `behavior_standardize_work_items` | Student |
| major subsystem, LangChain/Temporal duplicate | `behavior_justify_platform_subsystem` | Strategist |
| pattern 3+ times, new behavior | `behaviors.propose` | Strategist |

---

## Additional instructions

- Prefer updating existing docs over new summary files.
- Public APIs: OpenAPI specs; follow `TESTING_GUIDE.md`.
- Sync instruction files via Brief CLI or MCP when handbook structure changes.
- After editing [`docs/agent-handbook/behavior-catalog.md`](docs/agent-handbook/behavior-catalog.md), run `python scripts/seed_behaviors_from_agents_md.py` (`--apply-context` when Neon is canonical).
- **Branding**: **Amprealize** (product); **`amprealize`** (CLI/package, lowercase).

---

_Last updated: 2026-05-26 — compact contract; full handbook in `docs/agent-handbook/`_
