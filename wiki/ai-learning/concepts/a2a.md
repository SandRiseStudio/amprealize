---
title: "Agent-to-Agent Protocol (A2A)"
type: concept
difficulty: advanced
prerequisites:
  - "[Multi-Agent Orchestration](multi-agent.md)"
  - "[Model Context Protocol (MCP)](mcp.md)"
tags:
  - agents
  - protocols
  - interoperability
  - multi-agent
last_updated: 2026-04-23
sources:
  - "Google — Announcing the Agent2Agent Protocol (April 2025): https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability/"
  - "A2A Protocol Specification v0.2.0: https://a2a-protocol.org/v0.2.0/specification"
  - "Rapid Claw — A2A Complete Guide 2026: https://rapidclaw.dev/blog/a2a-protocol-complete-guide-2026"
  - "AI Agent Readiness Scanner — A2A Explained: https://isagentready.com/en/blog/what-is-google-a2a-protocol-agent-to-agent-communication"
amprealize_relevance: "As Amprealize expands to multi-tenant, cross-session agent workflows, A2A is the candidate protocol for coordinating specialized agents (e.g., a Student agent delegating a research sub-task to an external expert agent). Currently at the architecture evaluation stage."
visibility: public
---

# Agent-to-Agent Protocol (A2A)

## Why This Matters

[MCP](mcp.md) lets an agent reach for a tool or a database. **A2A lets an agent reach for another agent.** They solve different problems and are designed to be used together.

Before A2A, multi-agent systems were largely proprietary. LangChain agents could talk to other LangChain agents. Google ADK agents could coordinate internally. But an agent built on CrewAI could not natively delegate work to an agent built on Semantic Kernel — the two didn't share a common language.

A2A defines that common language: a thin, framework-agnostic protocol so any agent built on any framework can receive tasks from, and delegate tasks to, any other agent.

## Background

- **April 2025**: Google launches A2A with 50+ technology partners (Salesforce, SAP, ServiceNow, Atlassian, PayPal, Workday, and others).
- **June 2025**: Google donates A2A to the Linux Foundation's Agentic AI Foundation — the same governing body as MCP — making it fully vendor-neutral.
- **March 2026**: v1.2 stable. 150+ organizations running A2A in production. Native support in Google ADK, LangGraph, CrewAI, LlamaIndex, Semantic Kernel, and AutoGen.

## The Core Insight: Agents as Peers, Not Tools

MCP treats external systems as tools that an agent *uses*. A2A treats remote agents as **peers** that an agent *collaborates with*. A peer agent:

- Advertises what it can do (without revealing how)
- Accepts structured tasks
- Returns typed results
- May ask for more information mid-task
- Can run asynchronously over minutes or hours

This "opacity" principle is intentional. The calling agent should not need to know the remote agent's internal architecture, memory, or tools.

## Architecture

### Agent Card

Every A2A-capable agent publishes a machine-readable **Agent Card** — a JSON document at the well-known URL `/.well-known/agent.json`. It is, literally, a business card for an AI agent:

```json
{
  "name": "Amprealize Research Agent",
  "description": "Specialist in pedagogy research and curriculum design",
  "provider": { "organization": "Amprealize" },
  "url": "https://agents.amprealize.ai/research",
  "capabilities": {
    "streaming": true,
    "pushNotifications": true
  },
  "skills": [
    {
      "id": "curriculum-gap-analysis",
      "name": "Curriculum Gap Analysis",
      "description": "Given a learner profile, identifies knowledge gaps and recommends learning paths",
      "inputModes": ["text"],
      "outputModes": ["text", "application/json"]
    }
  ],
  "authentication": {
    "schemes": ["oauth2"]
  }
}
```

A client agent discovers a remote agent by fetching its Agent Card, reading the skill descriptions, and deciding whether that agent is the right one for a sub-task.

### Task Lifecycle

The **Task** is the unit of work in A2A. Every task has a unique ID and moves through a defined state machine:

```
submitted
    │
    ▼
working  ◀──── (agent is processing)
    │
    ├──── input-required  ◀──── (agent needs more info from caller)
    │         │
    │         └──── working  (after caller provides info)
    │
    ├──── completed  ✓
    ├──── failed     ✗
    └──── canceled   ⊘
```

Tasks can:
- Complete immediately (synchronous response)
- Stream incremental updates via Server-Sent Events (`working` → partial artifacts → `completed`)
- Pause to request more information from the calling agent (`input-required`)
- Report results asynchronously via push notifications (webhook)

### Transport

A2A uses HTTP as its transport, which means existing enterprise infrastructure — load balancers, WAFs, OIDC, mTLS, OpenTelemetry — works without modification. This is a deliberate design choice and a key reason for rapid enterprise adoption.

| Method | Use |
|--------|-----|
| `message/send` | Send a task and get a synchronous JSON response |
| `message/stream` | Send a task and subscribe to a streaming SSE response |
| `tasks/get` | Poll the current state of an existing task |
| `tasks/resubscribe` | Reconnect to an SSE stream after a dropped connection |
| `tasks/cancel` | Cancel an in-progress task |

Wire format is **JSON-RPC 2.0**. An optional gRPC transport (added in v0.3) is available for high-throughput, low-latency service-to-service scenarios.

## MCP vs. A2A Side by Side

| Dimension | MCP | A2A |
|-----------|-----|-----|
| Who talks to whom? | Agent → tool / data source | Agent → agent |
| Unit of work | Tool call / resource read | Task (stateful, multi-turn) |
| Discovery | Tool list from server | Agent Card (`.well-known/agent.json`) |
| State | Stateless per call | Stateful with full history |
| Streaming | SSE for responses | SSE + push notifications |
| Typical duration | Milliseconds | Seconds to hours |
| Opacity | Server exposes schema | Agent exposes only capabilities |

## A Production Agent Is Both

In practice, a real agent uses both protocols simultaneously:

```
External Orchestrator (A2A client)
    │
    │  A2A Task: "Analyze learning gap for user X"
    ▼
Amprealize Agent (A2A server + MCP client)
    │
    ├─── MCP: query ai_learning_wiki.query → knowledge retrieval
    ├─── MCP: query learner profile database → user data
    │
    └─── A2A: delegate "generate curriculum outline" to Curriculum Agent
                    │
                    └─── A2A server + MCP client (its own tool calls)
```

Mentally separate the two axes: **MCP = reaching for resources**, **A2A = reaching for expertise**.

## Security

A2A is designed for enterprise environments where trust boundaries matter:

- **Inside a trust boundary**: mTLS between agents; shared credential store
- **Across trust boundaries**: OAuth 2.1 with tightly scoped tokens; never share root keys
- **Signed Agent Cards** (v0.3+): Agent Cards can be cryptographically signed so callers can verify authenticity before establishing contact
- **Capability-scoped credentials**: Each caller gets credentials scoped to the specific skills they are authorized to invoke

## Framework Support

As of March 2026, native A2A support ships in:

| Framework | Notes |
|-----------|-------|
| Google Agent Development Kit (ADK) | Reference implementation |
| LangGraph | Agent-to-agent edge types |
| CrewAI | Crew-to-crew delegation |
| LlamaIndex Agents | `A2AAgent` wrapper |
| Semantic Kernel | Plugin-based integration |
| AutoGen | Multi-agent conversation |

Python and TypeScript SDKs are actively maintained at the [A2A GitHub repository](https://github.com/a2aproject/A2A).

## See Also

- [Model Context Protocol (MCP)](mcp.md) — agent-to-tool communication; complements A2A
- [Multi-Agent Orchestration](multi-agent.md) — architectural patterns for coordinating agents
- [Agent Design Patterns](../patterns/agent-design-patterns.md) — the six reusable patterns for building agent systems
- [Agent Harnesses & Context Fragments](agent-harness.md) — how the harness manages agent context
