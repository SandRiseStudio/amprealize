---
title: Agent Harnesses & Context Fragments
type: concept
last_updated: '2026-04-15'
difficulty: intermediate
sources:
- https://x.com/vtrivedy10/status/2043427918127513836
- https://www.anthropic.com/research/building-effective-agents
- https://www.anthropic.com/news/model-context-protocol
prerequisites:
- concepts/transformers.md
- concepts/prompt-engineering.md
amprealize_relevance: "Amprealize's ContextComposer is effectively a harness component\
  \ \u2014 it decides which behaviors, run history, and context objects to load into\
  \ the prompt window before each LLM call. The concept of Context Fragments maps\
  \ directly to how Amprealize loads behaviors, run records, and agent instructions\
  \ as discrete, explicitly-chosen units."
---

# Agent Harnesses & Context Fragments

## Why This Matters

An LLM by itself is a stateless function: prompt in, tokens out. The **harness** is everything that wraps around that function to make it useful as a persistent, goal-directed agent. Designing a good harness is arguably the hardest engineering problem in applied AI — because the harness decides what the model knows and doesn't know at every single moment of execution.

---

## What Is an Agent Harness?

An **agent harness** is the orchestration layer that:

1. **Populates** the context window before each model call
2. **Routes** outputs (tool calls, sub-tasks, memory writes) after each call
3. **Manages** state between calls (memory, history, tool results)
4. **Enforces** boundaries (what the agent can see, do, and remember)

The term "harness" captures the idea that you are literally harnessing raw LLM capability — bounding it, directing it, and giving it the connective tissue it needs to do sustained work.

Frameworks like LangChain, AutoGPT, Anthropic's Agent SDK, and AWS Strands Agents are all harness implementations. The context window is the primary resource they compete to manage efficiently.

---

## Context Fragments

The **context window** is the finite space of tokens the model can "see" at any one time. Every LLM call is, at its core, a function over this space.

A **Context Fragment** is a discrete unit of information that the harness has made an explicit decision to load into the context window. Each fragment represents a choice:

| Fragment Type | Examples |
|---|---|
| **System instructions** | Role definition, output format constraints |
| **Behavioral guidance** | Retrieved behaviors/skills, few-shot examples |
| **Working memory** | Recent tool outputs, intermediate reasoning steps |
| **Long-term memory** | Relevant past experiences retrieved from a memory store |
| **External context** | File contents, search results, database rows |
| **Task state** | Current goal, sub-task list, progress markers |

The harness designer's job is to decide: *which fragments are necessary for this model call, in what order, and at what level of compression?*

---

## Why Fragment Management Is Hard

Context windows are large but not infinite. As of 2025–2026, frontier models support 128K–2M tokens, but practical limits emerge earlier:

- **Cost**: Input tokens are priced; unnecessarily large contexts increase per-call cost
- **Latency**: Larger contexts take longer to process
- **Attention dilution**: Models can lose focus on critical information buried in long contexts ("lost in the middle" problem)
- **Staleness**: Long-running agents accumulate outdated fragments that mislead rather than help

This creates a fundamental tension: *the agent benefits from more context but degrades (in quality, speed, and cost) as context grows.*

---

## Harness Design Patterns

### 1. Just-in-Time Loading
Load fragments immediately before the call that needs them; evict or compress them after. Avoids carrying stale context across many turns.

### 2. Hierarchical Summarization
When a fragment exceeds a size budget, replace it with an LLM-generated summary. Common for conversation history and long tool outputs.

### 3. Retrieval-Gated Loading
Only load a fragment if a retrieval signal (semantic search, keyword match, metadata filter) says it's relevant to the current task. This is how RAG and BCI (Behavior-Conditioned Inference) work.

### 4. Priority Stacking
Assign fragments a priority score; when the context budget is tight, drop lower-priority fragments first. System prompts and immediate task instructions are always highest priority.

### 5. Tool-Call Compression
When a tool returns a large result, the harness may summarize or extract key fields before inserting into context, rather than inserting the raw output.

---

## The Agent-Computer Interface (ACI)

Anthropic's research distinguishes between the **Human-Computer Interface (HCI)** and the **Agent-Computer Interface (ACI)** — the surface through which an agent interacts with its tools and environment. A well-designed harness invests as much engineering effort in the ACI as a good product invests in the HCI:

- Tool descriptions must be precise and unambiguous
- Input schemas should prevent common model mistakes
- Outputs should be formatted for easy model consumption

---

## Open Questions

The post that inspired this entry raises several unsolved harness/fragment problems:

1. **Self-managed context**: How do we make models better at autonomously managing their own context window — deciding what to keep, compress, or drop without harness intervention?
2. **Error compounding**: Recursive agents operating over external objects accumulate errors. How do we reduce error rates in multi-step fragment loading pipelines?
3. **JIT vs. pre-loaded**: For long-horizon agents, should critical knowledge be retrieved just-in-time via search, or baked into the model weights through training?
