---
title: "Agent Handbook & Conventions"
type: reference
last_updated: 2026-04-14
applies_to:
  - dev
  - test
  - staging
  - prod
tags:
  - agent-handbook
  - behaviors
  - roles
  - conventions
  - critical-rules
---

# Agent Handbook & Conventions

Behaviors and conventions from `AGENTS.md` that govern all agent activity.
This is the authoritative reference for agent rules, roles, and behavior lifecycle.

## Critical Rules (Always Follow)

| Rule | Behavior | Why |
|------|----------|-----|
| Retrieve behaviors before every task | `behaviors.getForTask` | Behavior-conditioned execution |
| Use MCP tools over CLI/API | `behavior_prefer_mcp_tools` | Consistent schemas, automatic telemetry |
| Use Raze for all logging | `behavior_use_raze_for_logging` | Centralized, queryable, context-enriched |
| Use BreakerAmp for environments | `behavior_use_breakeramp_for_environments` | Blueprint-driven, compliance hooks |
| Never hardcode secrets | `behavior_prevent_secret_leaks` | Security, auditability |
| Run pre-commit before pushing | `behavior_prevent_secret_leaks` | Catches leaks before git |
| Update docs after API/workflow changes | `behavior_update_docs_after_changes` | Keeps team aligned |
| Update the AI Learning Wiki when AI behavior or platform usage changes | `behavior_maintain_ai_learning_wiki` | Keeps the teaching layer current for future agents |

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

```
DISCOVER (Student)  →  PROPOSE (Strategist)  →  APPROVE (Teacher)  →  INTEGRATE (All)
  Observe 3+           Draft behavior with       Validate quality      Add to handbook
  occurrences          procedural steps          on test cases         + retrieval index
```

1. **DISCOVER**: Student observes recurring pattern 3+ times
2. **PROPOSE**: Strategist drafts behavior using `behavior_<verb>_<noun>` naming
3. **APPROVE**: Teacher validates (auto-approve if confidence ≥ 0.8)
4. **INTEGRATE**: Add to AGENTS.md, seed to BehaviorService, update retrieval index

## Behavior Retrieval

```bash
# MCP (preferred — works in VS Code Copilot Chat)
mcp_amprealize_behaviors_getfortask(task_description="...", role="Student")

# CLI (fallback)
amprealize behaviors get-for-task "..." --role Student

# REST API (programmatic)
POST /v1/behaviors:getForTask {"task_description": "...", "role": "Student"}
```

Achieves ~46% token reduction by reusing proven procedural knowledge.

## Quick Triggers

Scan before starting any task. If keywords match, follow the linked behavior:

| Keywords | Behavior | Role |
|----------|----------|------|
| logging, telemetry | `behavior_use_raze_for_logging` | 📖 |
| environment, container | `behavior_use_breakeramp_for_environments` | 📖 |
| secret, credential, token | `behavior_prevent_secret_leaks` | 📖 |
| MCP tool, IDE extension | `behavior_prefer_mcp_tools` | 📖 |
| AI concept, retrieval strategy, prompt pattern, agent orchestration | `behavior_maintain_ai_learning_wiki` | 📖 |
| API design, OpenAPI | `behavior_design_api_contract` | 🎓 |
| test strategy, coverage | `behavior_design_test_strategy` | 🎓 |
| incident, outage, alert | `behavior_triage_incident` | 📖 |
| postmortem, root cause | `behavior_write_postmortem` | 🎓 |
| migration, schema change | `behavior_migrate_postgres_schema` | 📖 |

For the complete trigger table, see `AGENTS.md` § Quick Triggers.

## See Also

- [Behavior System Architecture](../architecture/behavior-system.md) — technical design
- [MCP Tool Families](mcp-tools.md) — behavior and BCI tools
- [Surfaces](surfaces.md) — where behaviors are invoked
- [Maintaining the AI Learning Wiki](../howto/maintain-ai-learning-wiki.md) — required workflow for AI-related changes
