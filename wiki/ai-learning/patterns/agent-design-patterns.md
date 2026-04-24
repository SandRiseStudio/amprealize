---
title: "6 Agent Design Patterns"
type: pattern
difficulty: intermediate
prerequisites:
  - "[Multi-Agent Orchestration](../concepts/multi-agent.md)"
  - "[Model Context Protocol (MCP)](../concepts/mcp.md)"
tags:
  - agents
  - architecture
  - patterns
  - design
last_updated: 2026-04-23
sources:
  - "Nilay Parikh — Simplifying Multi-Agent Complexity: 6 Essential Design Patterns (April 2026): https://ai.plainenglish.io/simplifying-multi-agent-complexity-6-essential-design-patterns-bb4f509cb2de"
  - "Zylos Research — AI Agent Tool-Use Optimization (March 2026): https://zylos.ai/research/2026-03-03-ai-agent-tool-use-optimization"
  - "AgentPatterns.ai — Cognitive Reasoning vs Execution: https://agentpatterns.ai/agent-design/cognitive-reasoning-execution-separation/"
amprealize_relevance: "Amprealize's GEP (Guided Execution Protocol) is a Sequential pattern at the top level, with an internal Coordinator pattern for routing to the Student, Teacher, and Strategist agents. The Loop & Critique pattern is used in behavior extraction quality checks."
visibility: public
---

# 6 Agent Design Patterns

## Why This Matters

Without shared patterns, agent systems collapse into technical debt fast. Teams routinely prototype 30+ custom agent designs before realizing that almost every production use case fits one of six fundamental architectures. These six patterns are composable: complex systems are built by combining them, not by inventing new ones.

## Pattern Decision Guide

Before picking a pattern, answer two questions:

1. **Is execution order fixed or dynamic?** Fixed → Sequential or Parallel. Dynamic → Coordinator or Agent-as-Tool.
2. **Does quality need a gate?** Yes → Loop & Critique. No → any of the others.

If the task is simple enough for one LLM call, start with **Single** before adding complexity.

---

## Pattern 1: Single Agent

**One LLM. One tool loop. One output.**

```
User Query → Agent (+ tools) → Response
```

The agent has direct access to all tools it needs and handles the task from start to finish. This is the fastest pattern to build and easiest to debug.

**When to use:**
- The task fits in one context window
- Tool usage is limited and predictable
- Latency requirements are strict

**Watch out for:**
- **Prompt bloat**: adding more tools and instructions to one agent degrades performance
- **Tool-order drift**: the agent starts calling tools in the wrong sequence as the prompt grows

**Signal to move on**: when the system prompt exceeds ~2,000 tokens or tool call errors increase, migrate to Sequential.

---

## Pattern 2: Sequential Agent

**A deterministic, ordered pipeline of specialist agents.**

```
Orchestrator → Agent A (Plan) → Agent B (Execute) → Agent C (Review) → Output
```

Each agent performs one stage and passes structured output to the next. The orchestrator coordinates the pipeline but does not decide at runtime which stage runs — the order is fixed.

**When to use:**
- The task has well-defined, dependent stages
- Each stage needs a different system prompt or tool set
- Auditability and traceability are required (every stage is logged independently)

**Trade-offs:**

| Pro | Con |
|-----|-----|
| Predictable, step-by-step execution | Higher latency (stages run sequentially) |
| Each stage testable in isolation | No branching — can't skip stages dynamically |
| Easy to debug (inspect each handoff) | Brittle if a stage produces unexpected output |

**Amprealize example:** The GEP runs 8 phases in sequence — intake, behavior retrieval, context composition, generation, review, and delivery.

---

## Pattern 3: Parallel (Fan-out / Synthesizer)

**Independent sub-tasks run concurrently; a synthesizer merges the results.**

```
                ┌── Agent A (task 1) ──┐
Orchestrator ──▶├── Agent B (task 2) ──┤──▶ Synthesizer ──▶ Output
                └── Agent C (task 3) ──┘
```

The orchestrator fans work out to agents that can run in parallel. The synthesizer waits for all results and merges them.

**When to use:**
- Sub-tasks are genuinely independent (no data dependency between them)
- Latency reduction is a priority
- The final step requires combining multiple perspectives or data sources

**Trade-offs:**

| Pro | Con |
|-----|-----|
| Significant latency reduction | Partial failure handling is complex |
| Scales well with the number of sub-tasks | Cost scales with parallelism |
| Natural for research, comparison, and aggregation tasks | Synthesizer prompt can become complex |

**Partial failure strategy:** decide whether to fail fast (abort on any error), fail soft (synthesize with available results), or retry individual branches.

---

## Pattern 4: Coordinator

**An LLM-driven dispatch layer dynamically routes tasks to specialist agents.**

```
User Query → Coordinator (LLM decides routing) → Agent A or B or C → Output
```

Unlike Sequential (fixed order) or Parallel (all run), the Coordinator reads the task at runtime and decides which specialist agent(s) to invoke. The routing decision itself is an LLM call.

**When to use:**
- The task type is not known at design time
- A growing catalog of specialist agents handles different domains
- You need to add new agent types without changing the routing code

**Trade-offs:**

| Pro | Con |
|-----|-----|
| Highly flexible — new agents slot in without refactoring | Routing is non-deterministic (LLM can mis-route) |
| Scales to large agent catalogs | One extra LLM call per routing decision |
| Natural fit for user-facing chat systems | Harder to test — you must test routing logic separately |

**Key implementation detail:** each specialist agent's description must be precise. The Coordinator's routing quality is only as good as the descriptions it reads. Vague descriptions → mis-routing.

---

## Pattern 5: Agent-as-Tool

**Specialist sub-agents are exposed as callable tools to a primary orchestrator.**

```
Primary Agent ──▶ tool: research_agent() ──▶ Research Sub-Agent
               ──▶ tool: summarizer_agent() ──▶ Summarizer Sub-Agent
               ──▶ tool: validator_agent() ──▶ Validator Sub-Agent
```

Instead of delegating to an autonomous agent (as in Coordinator), the primary agent calls sub-agents the same way it calls any other tool — with a defined input schema and a structured return value. The primary agent retains full control of synthesis and the final response.

**When to use:**
- The primary agent must maintain ownership of the final output
- Sub-agents perform information gathering or transformation, not autonomous decision-making
- You want MCP-compatible composition (sub-agents can be exposed as MCP tools)

**Trade-offs:**

| Pro | Con |
|-----|-----|
| Primary agent retains full context and control | Sub-agents cannot act autonomously |
| Sub-agents are testable as pure functions | Sub-agent output feeds back into primary context (token cost) |
| Clean separation of concerns | Primary agent's context window fills faster with sub-agent results |

**MCP connection:** this pattern pairs naturally with MCP — sub-agents can be wrapped as MCP tools and discovered dynamically, rather than being hardcoded into the primary agent's tool list.

---

## Pattern 6: Loop & Critique

**A generator produces output; a critic evaluates it; the loop repeats until a quality gate passes.**

```
                  ┌────────────────────────────────────┐
                  │                                    │
User Query → Generator Agent → Critic Agent → [pass?] ──▶ Output
                                                  │
                                              [fail] ──▶ Generator (with feedback)
```

The critic has its own system prompt and evaluates the generator's output against explicit criteria. If the output fails, the critic's feedback is added to the generator's context for the next attempt. The loop exits when the critic approves or a maximum iteration count is reached.

**When to use:**
- Output quality is non-negotiable (compliance text, medical content, legal summaries)
- Hallucination risk is high and must be caught automatically
- The domain has clear, expressible quality criteria

**Trade-offs:**

| Pro | Con |
|-----|-----|
| Catches errors that single-pass generation misses | Token cost scales with iterations |
| Critic feedback improves generator context on each pass | Latency scales with iterations |
| Self-validating — reduces need for human review | Risk of infinite loops — always set a max iteration cap |

**Implementation tips:**
- Keep the critic's criteria explicit and enumerable (not "is this good?" but "does it answer the question? is every claim cited?")
- Log every iteration for debugging
- Set `max_iterations = 3` as a default; raise only with measured evidence

---

## Composing Patterns

Complex production systems combine patterns. Common compositions:

| System type | Composition |
|-------------|-------------|
| Research assistant | Coordinator → Parallel (gather) → Synthesizer |
| Content pipeline | Sequential (draft → edit) with Loop & Critique on the edit stage |
| Customer support | Coordinator (route to domain) → Agent-as-Tool (retrieve + respond) |
| Amprealize GEP | Sequential (8 phases) + internal Coordinator (agent routing) |

The "seventh pattern test": if you think you need a new pattern, try to express it as a composition of these six first. Production experience suggests you almost always can.

## See Also

- [Multi-Agent Orchestration](../concepts/multi-agent.md) — deeper look at orchestration mechanics
- [Model Context Protocol (MCP)](../concepts/mcp.md) — the tool protocol that powers Pattern 5
- [Agent-to-Agent Protocol (A2A)](../concepts/a2a.md) — for when agents need to talk to agents across frameworks
- [Agent Harnesses & Context Fragments](../concepts/agent-harness.md) — the harness that runs these patterns
