---
title: "AI Agents: What They Are and How They Work"
type: concept
difficulty: intermediate
prerequisites:
  - "[Prompt Engineering](prompt-engineering.md)"
  - "[RAG (Retrieval-Augmented Generation)](rag.md)"
  - "[Tokens & Tokenization](tokenization.md)"
tags:
  - agents
  - architecture
  - memory
  - tools
  - planning
last_updated: 2026-04-23
sources:
  - "Wang et al. — A Survey on LLM-based Autonomous Agents (2023): https://arxiv.org/abs/2308.08155"
  - "Yao et al. — ReAct: Synergizing Reasoning and Acting in LLMs, ICLR 2023: https://arxiv.org/abs/2210.03629"
  - "Shinn et al. — Reflexion, NeurIPS 2023: https://arxiv.org/abs/2303.11366"
  - "NJ Raman — The Architecture of Agency (April 2026): https://medium.com/@nraman.n6/the-architecture-of-agency-a-deep-technical-guide-to-agentic-ai-systems-in-2026-9df63b37f6df"
  - "CogitX — AI Agents: Complete Overview 2026: https://cogitx.ai/blog/ai-agents-complete-overview-2026"
  - "Google Cloud — What are AI agents?: https://cloud.google.com/discover/what-are-ai-agents"
  - "Endless.sbs — How AI Agents Work: Memory, Tools & Planning 2026: https://endless.sbs/How%20AI%20Agents%20Actually%20Work:%20Memory,%20Tools,%20Planning%20%26%20Real-World%20Systems%20%282026%29"
amprealize_relevance: "Amprealize is an agent platform. Every 'run' is an agent loop: the orchestrator receives a goal, selects specialized agents (Student, Teacher, Strategist), equips them with MCP tools (wiki.query, board.*, etc.), and loops until the task is complete or a human checkpoint is reached."
visibility: public
---

# AI Agents: What They Are and How They Work

## Why This Is the Right Starting Point

Most confusion about AI comes from conflating three different things: **chatbots**, **assistants**, and **agents**. They all involve LLMs, but they are architecturally distinct.

- A **chatbot** gives a response. That's it. Stateless. One round trip.
- An **assistant** maintains conversation history and can answer follow-up questions. Still reactive — it only does something when you ask.
- An **agent** is given a *goal* and autonomously figures out a *plan*, uses *tools* to take real actions, observes the results, and iterates until the goal is done — or until it decides it needs your help.

The practical difference: hand a chatbot the task "book me a flight to New York for Friday." It will explain how you might do that. Hand an agent the same task. It will open a browser, search, find options, check your calendar, and either book the flight or present you with a choice.

---

## The Formal Definition

An AI agent is a system that runs the following loop over an extended time horizon:

```
Goal → Perceive → Reason → Plan → Act → Observe → [update memory] → back to Reason
         ↑                                   |
         └─────────────── loop ──────────────┘
```

The key word is **loop**. A raw LLM call is a single pass: input → output. An agent wraps that in a loop where every output either produces a final answer or causes an action whose *result* feeds back into the next reasoning step. This continues — potentially for minutes, hours, or across multiple sessions — until a stopping condition is reached.

The minimal formal definition from the academic literature (Wang et al., 2023):

> *"An AI agent is a system that can perceive its environment, plan actions, use external tools, and — crucially — run a feedback loop that allows it to act, observe results, and correct itself."*

---

## The ReAct Pattern: How Most Agents Actually Work

The dominant architecture for production agents is **ReAct** (Reason + Act), introduced in a landmark ICLR 2023 paper by Yao et al. at Princeton and Google. It alternates between two modes:

- **Thought** — the model reasons about the current state: what do I know? what do I need? what should I do next?
- **Action** — the model calls a tool and gets back an **Observation**

```
Thought: I need to find the current stock price for NVDA.
Action: search_web(query="NVDA stock price today")
Observation: NVDA is trading at $142.30 as of 9:32 AM ET.

Thought: I have the price. Now I need to compare it to last month's close.
Action: get_historical_price(ticker="NVDA", date="2026-03-23")
Observation: NVDA closed at $118.70 on 2026-03-23.

Thought: I can now calculate the change (+19.9%). I have enough to answer.
Final Answer: NVDA is up 19.9% vs. last month, trading at $142.30.
```

Each observation updates the model's reasoning. The model can't hallucinate a tool result — the result comes from the actual tool execution. This is what makes agents more reliable than a single LLM call for fact-dependent tasks.

### Reflexion: Adding Self-Critique

The **Reflexion** pattern (Shinn et al., NeurIPS 2023) extends ReAct with explicit error memory. When an agent fails, it writes a natural-language reflection ("my code failed because I didn't handle empty lists — next time check for empty input first") stored for future attempts. This is why agents improve within a session.

---

## The Six Components of a Production Agent

A "prompt + LLM" is not an agent. A production-grade agent in 2026 has six distinct components working together.

### 1. The Model (The Brain)

The LLM is the reasoning core — the component that reads the current context and decides what to think or do next. Model choice matters enormously:

- **Context window size** — determines how much of the task history the model can see at once
- **Instruction following** — how precisely it follows tool schemas and system prompts
- **Tool calling quality** — how reliably it emits valid, correctly-structured tool calls
- **Reasoning depth** — whether it can plan across many steps without losing the thread

For agentic tasks, frontier models (Claude Opus, GPT-5.4, Gemini 3.1 Pro) outperform smaller models significantly. The smaller the context window or the weaker the instruction following, the more often agents derail.

### 2. Tools (The Hands)

An LLM alone can only generate text. Tools are what give it hands. A tool is a typed function that the agent can call by emitting a structured output (usually JSON). The surrounding runtime intercepts this, executes the real function, and feeds the result back as an observation.

```
Model output:    { "tool": "read_file", "path": "/src/auth.py" }
Runtime:         reads the file from disk
Observation:     [file contents injected into context]
Model continues: reasoning with the actual file contents
```

**Common tool categories:**

| Category | Examples |
|----------|----------|
| Search & retrieval | Web search, vector DB query, document lookup |
| Code execution | Run Python/JS in a sandbox, execute shell commands |
| File system | Read, write, list, delete files |
| External APIs | REST calls, database queries, Slack messages |
| Browser | Navigate pages, click elements, fill forms, take screenshots |
| Communication | Send email, post to Slack, create calendar events |
| Creation | Generate images, write to a document, create a ticket |

Tools are described to the model via a schema: a name, a natural-language description, and a typed parameter spec. The model reads these descriptions and decides which tool to call. Poorly written tool descriptions are one of the most common causes of agent failure.

**MCP** (Model Context Protocol) is the standard that makes tool discovery and calling interoperable across models and runtimes. See [Model Context Protocol (MCP)](mcp.md).

### 3. Memory (What the Agent Knows)

Memory determines what information the agent can access during its execution. Modern agents use four layers, each with different scope and retrieval characteristics:

```
┌─────────────────────────────────────────────────────────────────────┐
│  Layer 1: In-Context Memory (Working Memory)                        │
│  Fast. Ephemeral. Everything in the current context window.         │
│  Lost when the conversation ends.                                   │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 2: External Storage (Persistent, Query-based)                │
│  Vector databases (semantic search), key-value stores (exact        │
│  lookup), relational databases (structured queries). Survives       │
│  across sessions. Retrieved on demand.                              │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 3: In-Weights Memory (Parametric, Frozen)                    │
│  World knowledge baked into the model during training. Fast,        │
│  always available, but potentially outdated and unverifiable.       │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 4: In-Cache Memory (KV Cache)                                │
│  Reusable computation from previous requests. Transparent to        │
│  the agent; managed by the inference provider.                      │
└─────────────────────────────────────────────────────────────────────┘
```

**Working memory (Layer 1)** is the context window. Every tool call, every result, every reasoning step accumulates here in real time. The critical constraint: context windows are finite. A complex task that generates many observations can exhaust the context window before completion — this is why agents need the other layers.

**External storage (Layer 2)** is what separates stateless agents from agents that learn and improve. When an agent writes important findings to a vector store during execution and retrieves them in later steps (or later sessions), it starts to behave more like a system with genuine memory. Tools like Mem0, Zep, and LangMem implement this pattern. See [Experiential Memory for AI Agents](experiential-memory.md).

**Parametric knowledge (Layer 3)** is what the model knows from training — world events up to its knowledge cutoff, programming language syntax, scientific facts. Useful as a starting point; unreliable for anything current, proprietary, or precise.

### 4. Planning

Planning is how the agent decides what to do in what order. Three strategies exist in practice:

**Implicit planning** — the model acts step by step and figures it out as it goes. Each observation updates its understanding and the next action emerges naturally. Works for short, well-defined tasks. Fails for complex multi-step goals where early decisions constrain later options.

**Explicit planning** — the model writes a full plan before taking any action. Lists the goal, required steps, dependencies, and anticipated failure points. Then executes the plan, checking progress at each step. More reliable for complex tasks; brittle if the plan is wrong or conditions change.

**Adaptive planning** — write an explicit plan upfront, but with explicit checkpoints where the agent reviews progress and revises the plan if observations don't match expectations. The best of both: structured but responsive to new information.

```
Adaptive plan example:
  Goal: Migrate the authentication module to use JWT.
  Phase 1: Understand current state (read files, map dependencies)
  ↓ [checkpoint: verify understanding is correct]
  Phase 2: Write the new JWT implementation
  ↓ [checkpoint: run tests; revise if failures]
  Phase 3: Update all callers
  ↓ [checkpoint: run full test suite; confirm no regressions]
  Phase 4: Write migration notes
```

### 5. Context Management

Context management is the agent runtime's job of deciding what information to keep in the active context window and what to offload or retrieve. In a long-running agent session:

- Older tool results may be summarized and the originals dropped
- Key facts may be written to external storage and retrieved only when needed
- Large files may be chunked and only the relevant chunk loaded

Poor context management is a silent agent killer — the agent "forgets" something critical because it was pushed out of the context window, causing it to repeat work, contradict itself, or lose the thread of a complex task.

### 6. The Agent Loop / Runtime

The runtime is the orchestration layer that:

1. Initializes the agent with a system prompt, tool schemas, and initial context
2. Calls the model and parses its output
3. If the output is a **tool call** → executes the tool and injects the result as an observation, then calls the model again
4. If the output is a **final answer** → returns it and terminates the loop
5. If the output is a **human checkpoint request** → pauses and waits for user input
6. Enforces safety limits (maximum steps, token budget, restricted tool categories)

---

## The Autonomy Spectrum

Not all agents are fully autonomous. In practice, there is a spectrum:

```
Low autonomy ←────────────────────────────────────→ High autonomy

Bot          Assistant      Agent        Supervised      Fully
(scripted)   (reactive)     (task loop)  agent           autonomous
                                         (human-in-loop) agent
```

| Level | Description | Example |
|-------|-------------|---------|
| **Bot** | Pre-programmed rules, no LLM reasoning | FAQ chatbot, rule-based ticketing |
| **Assistant** | LLM-powered, reactive, stateless per-session | ChatGPT in a single conversation |
| **Task agent** | Goal-directed loop; uses tools; limited autonomy | Claude Code on a single file refactor |
| **Supervised agent** | Long-running; pauses at key decisions for human approval | Agent that drafts PRs; human approves before merge |
| **Autonomous agent** | Long-running; self-directed; only alerts on blockers | Overnight coding agent running against a full repo |

Most production deployments in 2026 sit in the **supervised agent** zone — systems capable of extended autonomous work but designed to pause for human confirmation before irreversible actions (sending emails, deleting data, merging code, spending money).

---

## Types of Agents by Domain

The same agent architecture applies across domains. The differences are in which tools are provided and what the system prompt instructs.

| Type | Primary tools | What it does |
|------|--------------|--------------|
| **Coding agent** | File system, code execution, git, web search | Reads a codebase, plans changes, writes and tests code |
| **Research agent** | Web search, document retrieval, summarization | Searches, synthesizes, and structures information |
| **Data agent** | SQL, APIs, charting tools | Queries data sources, analyzes, generates reports |
| **Browser agent** | Playwright/Puppeteer, screenshot | Navigates websites, fills forms, extracts content |
| **Personal assistant** | Email, calendar, messaging, search | Manages tasks, communications, and scheduling |
| **DevOps agent** | Terminal, cloud CLIs, monitoring APIs | Provisions infra, responds to alerts, runs deployments |

---

## What Goes Wrong: Common Agent Failure Modes

Knowing failure modes is as important as knowing the architecture.

| Failure | Why it happens | How to mitigate |
|---------|---------------|-----------------|
| **Hallucinated tool calls** | Model emits an invalid tool name or wrong parameter format | Strong tool schemas; few-shot examples in the system prompt |
| **Infinite loops** | Agent keeps trying the same failed action | Step limit enforcement; reflexion-style failure memory |
| **Context exhaustion** | Task history fills the context window | Summarization, external memory, smaller working sets |
| **Plan rigidity** | Explicit plan doesn't adapt when observations differ from expectations | Adaptive planning with checkpoints |
| **Tool overuse** | Agent calls tools unnecessarily when it already has the information | Clear tool descriptions; "only call X when you don't already know Y" |
| **Irreversible actions** | Agent deletes/sends/deploys without a confirmation gate | Human-in-loop checkpoints before destructive actions |
| **Prompt injection** | Malicious content in a tool result hijacks the agent's instructions | Input sanitization; instruction defense prompts |
| **Goal drift** | Agent loses track of the original goal over a long session | Explicit goal statement prepended at each reasoning step |

---

## How Agents Connect to the Broader Ecosystem

```
┌─────────────────────────────────────────────────────────┐
│  Multi-agent system (Orchestrator + Specialist agents)  │
│  ← see: Multi-Agent Orchestration                       │
└──────────────────────────┬──────────────────────────────┘
                           │ each agent is...
                           ▼
┌─────────────────────────────────────────────────────────┐
│  Single Agent                                           │
│  [Model] + [Memory] + [Tools] + [Planning] + [Runtime]  │
└──────┬────────────────────┬────────────────────────────┘
       │                    │
       │ discovers tools via │ memory backed by
       ▼                    ▼
  ┌────────┐          ┌──────────────────────┐
  │  MCP   │          │  Vector DB / KV store │
  │ server │          │  (Mem0, Zep, Neon...) │
  └────────┘          └──────────────────────┘
       │
       │ agents talk to each other via
       ▼
  ┌────────┐
  │  A2A   │
  │protocol│
  └────────┘
```

- **[Multi-Agent Orchestration](multi-agent.md)** — how to coordinate multiple agents working together
- **[Model Context Protocol (MCP)](mcp.md)** — the standard for tool discovery and invocation
- **[Agent-to-Agent Protocol (A2A)](a2a.md)** — how agents delegate tasks to other agents
- **[6 Agent Design Patterns](../patterns/agent-design-patterns.md)** — architectural patterns for structuring agent systems
- **[Agent Harnesses & Context Fragments](agent-harness.md)** — how context is assembled before each model call
- **[Experiential Memory for AI Agents](experiential-memory.md)** — deep dive on persistent agent memory

---

## Quick Reference

| Term | What it means |
|------|--------------|
| **Agent loop** | The repeating Perceive → Reason → Act → Observe cycle |
| **ReAct** | Alternating Thought / Action / Observation pattern (Yao et al., 2023) |
| **Reflexion** | Storing failure reflections to improve across attempts (Shinn et al., 2023) |
| **Tool call** | A structured JSON output the model emits to invoke a function |
| **Observation** | The result returned to the model after a tool executes |
| **In-context memory** | Information currently in the active context window |
| **External memory** | Persistent storage retrieved via semantic search or key lookup |
| **Parametric memory** | Knowledge baked into model weights at training time |
| **Human-in-loop** | A pause point where the agent waits for human confirmation |
| **Step limit** | Maximum number of tool calls before the agent is forced to stop |
| **Context window** | The total amount of text (tokens) the model can see at once |
| **System prompt** | Instructions that define the agent's role, tools, and constraints |
