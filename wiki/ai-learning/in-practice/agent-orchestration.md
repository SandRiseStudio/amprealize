---
title: "Agent Orchestration in Amprealize"
type: in-practice
difficulty: advanced
prerequisites:
  - concepts/multi-agent.md
  - in-practice/bci-in-amprealize.md
  - in-practice/context-composition.md
tags:
  - amprealize
  - agents
  - orchestration
last_updated: "2026-04-09"
sources:
  - "amprealize/agent_orchestrator_service.py"
  - "amprealize/agent_execution_loop.py"
  - "amprealize/agent_registry_service.py"
amprealize_relevance: "Direct walkthrough of Amprealize's multi-agent system — role-based dispatch, behavior-conditioned execution, and handoff patterns."
visibility: internal
---

# Agent Orchestration in Amprealize

## What It Is

Amprealize implements a supervisor-pattern multi-agent system where the orchestrator routes tasks to specialized agents based on role declarations, behavior conditions, and task requirements.

## How It Maps to Concepts

| AI/ML Concept | Amprealize Implementation |
|--------------|--------------------------|
| [Multi-Agent Orchestration](../concepts/multi-agent.md) | `agent_orchestrator_service.py` — supervisor pattern |
| [Prompt Engineering](../concepts/prompt-engineering.md) | Per-agent system prompts with role-specific instructions |
| [RAG](../concepts/rag.md) | Each agent call includes BCI-retrieved behaviors |

## Architecture

```
Task Request
    ↓
[Agent Orchestrator]
    ├── Role Detection (Student/Teacher/Strategist)
    ├── Behavior Retrieval (BCI)
    ├── Context Composition
    └── Agent Dispatch
         ↓
[Agent Execution Loop]
    ├── Tool Calls (MCP tools)
    ├── Self-Monitoring (adherence tracking)
    └── Result / Handoff
         ↓
[Handoff Work Item] (if ADOPT/ADAPT verdict)
```

## Key Components

- `agent_orchestrator_service.py` — Routes tasks to agents
- `agent_execution_loop.py` — Runs the agent cycle (think → act → observe)
- `agent_registry_service.py` — Registers available agents and their capabilities
- `adherence_tracker.py` — Monitors whether agents follow their behaviors

## Handoff Pattern

When an agent's work produces an actionable verdict (e.g., research evaluation yields ADOPT), the orchestrator creates a work item for the next agent. This is the sequential pipeline pattern from [Multi-Agent Orchestration](../concepts/multi-agent.md).

## See Also

- [BCI In Practice](bci-in-amprealize.md) — How agents get their behaviors
- [Context Composition In Practice](context-composition.md) — How agent prompts are built
