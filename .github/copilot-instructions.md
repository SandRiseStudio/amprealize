# Copilot Instructions

Reference `AGENTS.md` for the full behavior handbook. This file provides quick triggers for common patterns.

## 🚨 Amprealize MCP Tools Work Natively!

**Amprealize MCP tools are available directly in VS Code Copilot Chat.** Use them by name:
- `mcp_amprealize_projects_list` - List projects in an organization
- `mcp_amprealize_behaviors_getfortask` - Retrieve behaviors for a task
- `mcp_amprealize_boards_list` - List boards in a project
- Plus **220 other tools** for behaviors, runs, compliance, agents, and more!

## 🚨 MANDATORY: Retrieve Behaviors Before Every Task

**Before starting ANY task**, retrieve relevant behaviors using MCP directly:

```bash
# MCP (preferred - works natively in VS Code Copilot Chat!)
mcp_amprealize_behaviors_getfortask(task_description="<describe your task>", role="Student")

# CLI alternative (when MCP unavailable)
amprealize behaviors get-for-task "<describe your task>" --role Student
```

Then cite behaviors in your work: `Following behavior_xyz (Student): ...`

**If you observe the same pattern 3+ times** without an existing behavior, propose a new one:
```bash
amprealize behaviors propose --name behavior_xyz --description "..." --instruction "..." --role STUDENT --confidence 0.8
```

## Quick Triggers

| Keywords | Behavior |
|----------|----------|
| MCP tool, MCP server, IDE extension | `behavior_prefer_mcp_tools` |
| logging, structured logs, telemetry sink | `behavior_use_raze_for_logging` |
| environment, blueprint, podman, container | `behavior_use_breakeramp_for_environments` |
| standalone package, reusable service, extract module | `behavior_extract_standalone_package` |
| secret, credential, leak, gitleaks | `behavior_prevent_secret_leaks`, `behavior_rotate_leaked_credentials` |
| execution record, SSE, progress, run status | `behavior_unify_execution_records` |
| storage adapter, audit log, timeline | `behavior_align_storage_layers` |
| config path, env var, secrets manager | `behavior_externalize_configuration` |
| action registry, `amprealize record-action` | `behavior_sanitize_action_registry` |
| telemetry event, Kafka, metrics dashboard | `behavior_instrument_metrics_pipeline` |
| CORS, auth decorator, bearer token | `behavior_lock_down_security_surface` |
| git workflow, branching, merge policy | `behavior_git_governance` |
| ci pipeline, deployment, rollback | `behavior_orchestrate_cicd` |
| feature flag, rollout, percentage flag, gradual release | `behavior_manage_feature_flags` |
| quality gate, regression check, benchmark validation | `behavior_enforce_quality_gates` |
| pack bootstrap, workspace migration, pack rollback | `behavior_bootstrap_pack_migration` |
| auto-reflection, learning loop, reflection trigger | `behavior_run_auto_reflection` |
| **pattern observed 3+ times** | `behaviors.propose` → propose new behavior |

## Key Principles

- **Behavior-first**: ALWAYS retrieve behaviors before starting any task using `behaviors.getForTask`
- **Logging**: Use **Raze** for all structured logging (`packages/raze/`)
- **Environments**: Use **BreakerAmp** for container/resource management (`packages/breakeramp/`)
- **MCP-first**: When MCP tools are available, prefer them over manual CLI/API calls—they provide consistent schemas and automatic telemetry
- **Standalone-first**: When adding significant functionality, consider creating a standalone package under `packages/`
- **Testing**: Run `pytest` or `npm run build` after changes; record outcomes
- **Secrets**: Never hardcode; run `pre-commit` before pushing
- **Docs**: Update `README.md`, `PRD.md`, `BUILD_TIMELINE.md` when APIs/workflows change
- **Behavior proposals**: When pattern repeats 3+ times, propose new behavior with confidence score
- **Branding:** Product name **Amprealize** (capital A only); CLI/package **`amprealize`** (lowercase)—see `AGENTS.md` Additional Instructions

## Standalone Package Pattern

When creating reusable functionality, follow the Raze/BreakerAmp model:
1. Create under `packages/<name>/` with zero amprealize core dependencies
2. Use hooks/callbacks for integration points
3. Define optional extras: `[cli]`, `[fastapi]`, `[dev]`
4. Add thin wrapper in `amprealize/<name>/` for service integration

For detailed behavior steps and compliance checklist, see `AGENTS.md`.

_Last synced with AGENTS.md: 2026-04-03_
