---
title: "Agent Handbook & Conventions"
type: practice
source_files:
  - CLAUDE.md
  - AGENTS.md
source_hash: auto
last_updated: "2026-04-09"
applies_to:
  - dev
  - test
  - staging
  - prod
visibility: domain-knowledge
---

# Agent Handbook & Conventions

Behaviors and conventions from `CLAUDE.md` and `AGENTS.md` that govern all agent activity.

## Critical Rules (Always Follow)

1. **Retrieve behaviors before every task** — `behaviors.getForTask` ensures behavior-conditioned execution
2. **Use MCP tools over CLI/API** — Consistent schemas, automatic telemetry
3. **Use Raze for all logging** — Centralized, queryable, context-enriched
4. **Use BreakerAmp for environments** — Blueprint-driven, compliance hooks
5. **Never hardcode secrets** — Security and auditability
6. **Run pre-commit before pushing** — Catches secret leaks before git
7. **Update docs after API/workflow changes** — Keeps team aligned

## Role Declaration Protocol

Every task must start with a role declaration:

| Role | Symbol | Responsibility |
|------|--------|---------------|
| **Student** | 📖 | Execute established behaviors; cite behavior + rationale |
| **Teacher** | 🎓 | Create examples, templates, docs; validate quality |
| **Metacognitive Strategist** | 🧠 | Analyze patterns (3+ occurrences), reflect on traces, propose behaviors |

### Escalation Triggers

- **Student → Teacher**: Teaching others, writing docs, reviewing quality
- **Student → Strategist**: Pattern observed 3+ times, root cause needed, no behavior fits
- **Teacher → Strategist**: Behavior gaps discovered, quality patterns need extraction

## Behavior Lifecycle

1. **DISCOVER** (Student) — Observe 3+ recurring patterns
2. **PROPOSE** (Strategist) — Draft behavior with procedural steps
3. **APPROVE** (Teacher) — Validate quality on test cases
4. **INTEGRATE** (All) — Add to handbook, update retrieval index

## Behavior Retrieval

```bash
# MCP (preferred)
mcp_amprealize_behaviors_getfortask(task_description="...", role="Student")

# CLI (fallback)
amprealize behaviors get-for-task "..." --role Student

# REST API (programmatic)
POST /v1/behaviors:getForTask {"task_description": "...", "role": "Student"}
```

Achieves ~46% token reduction by reusing proven procedural knowledge.

## See Also

- [run_tests.sh Reference](../reference/run-tests-sh.md) — test conventions
- [BreakerAmp Environments](../reference/breakeramp-environments.md) — environment management
