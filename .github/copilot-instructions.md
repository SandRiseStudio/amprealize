# Copilot quick reference

**Full operating contract**: [`AGENTS.md`](../AGENTS.md)

**Handbook** (behaviors, lifecycle, MCP, design): [`docs/agent-handbook/README.md`](../docs/agent-handbook/README.md)

---

## Start here

1. `behaviors.getForTask` (MCP) or `amprealize behaviors get-for-task "<task>" --role Student`
2. Declare role; cite `Following \`behavior_xyz\` (Student): ...` in output
3. Prefer Amprealize MCP tools (`tools.guide`, `auth.authStatus`, `context.getContext`, `tools.catalog`)

---

## Non-negotiables

- **Raze** for logging · **BreakerAmp** for environments
- **No hardcoded secrets** · **`pre-commit` before push**
- **Dual-repo** for platform work (OSS + Enterprise unless scoped)
- **Smallest relevant test** after substantive changes

---

## Quick triggers

| Keywords | Behavior |
|----------|----------|
| any new task | `behaviors.getForTask` |
| MCP, IDE | `behavior_prefer_mcp_tools` |
| logging | `behavior_use_raze_for_logging` |
| environment, container | `behavior_use_breakeramp_for_environments` |
| secret, leak | `behavior_prevent_secret_leaks` |
| UI, UX, redesign | design workflow in `AGENTS.md` + `behavior_validate_accessibility` |
| run / SSE / execution | `behavior_unify_execution_records` |
| storage, Postgres | `behavior_align_storage_layers` |
| API, OpenAPI | `behavior_design_api_contract` |
| CI/CD | `behavior_orchestrate_cicd` |
| incident | `behavior_triage_incident` |
| pattern 3+ times | `behaviors.propose` |

**Full table + behavior steps**: [`docs/agent-handbook/behavior-catalog.md`](../docs/agent-handbook/behavior-catalog.md)

---

## Design (short)

`layers-orient` → `superdesign` → `design-taste-frontend` / `impeccable` → `refactor-ui` — see [`docs/agent-handbook/design-workflow.md`](../docs/agent-handbook/design-workflow.md)

---

_Last synced with AGENTS.md: 2026-05-26_
