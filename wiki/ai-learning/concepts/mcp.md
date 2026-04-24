---
title: "Model Context Protocol (MCP)"
type: concept
difficulty: intermediate
prerequisites:
  - "[Multi-Agent Orchestration](multi-agent.md)"
  - "[Prompt Engineering](prompt-engineering.md)"
tags:
  - agents
  - protocols
  - tools
  - integrations
last_updated: 2026-04-23
sources:
  - "Anthropic — MCP Specification (2024–2026): https://modelcontextprotocol.io/specification/latest"
  - "MCP Introduction: https://modelcontextprotocol.io/docs/getting-started/intro"
  - "Agent Whispers — What Is MCP? A Practical Guide for 2026: https://www.agentwhispers.com/agent-guides/what-is-mcp"
  - "DEV Community — MCP Explained: Why It Matters in 2026: https://dev.to/swrly/model-context-protocol-mcp-explained-why-it-matters-in-2026-1c7i"
amprealize_relevance: "Amprealize exposes its capabilities as MCP tools (ai_learning_wiki.query, wiki.*, etc.). The agent harness is an MCP client that discovers and calls these tools. Any new platform capability should first be modelled as an MCP tool."
visibility: public
---

# Model Context Protocol (MCP)

## Why This Matters

Before MCP, connecting an AI model to an external tool required custom integration code for every model-tool combination. Ten models, ten tools = up to 100 bespoke connectors. MCP collapses that to 10 + 10: each model implements MCP once, each tool implements MCP once, and any model can reach any tool through the standard.

It is the closest thing the AI tooling ecosystem has to a universal standard, backed by Anthropic (who created it), OpenAI, Google, and Microsoft. Cursor, Claude, ChatGPT, GitHub Copilot, and VS Code all support it. In December 2025 Anthropic donated MCP to the Linux Foundation's Agentic AI Foundation, making it vendor-neutral.

## The Analogy

Think of MCP as the **USB-C port for AI applications**. Before USB-C, every device had its own connector; before MCP, every model-tool pair needed its own glue code. USB-C provides one standard physical and electrical interface regardless of what you plug in; MCP provides one standard protocol interface regardless of which model or tool is involved.

## MCP vs. CLI — Clearing Up a Common Confusion

A CLI (Command Line Interface) is a **user interface** — the shell where a human types commands.

MCP is a **machine-facing protocol** — a standard for exposing tools that models and agents can discover and invoke. MCP does not replace or compete with CLIs. Instead, the same MCP server can sit underneath many different interfaces: a CLI (Claude Code, terminal), a GUI (Claude Desktop, Cursor), or a fully automated agent that never shows output to a human at all.

The right question is not "MCP or CLI?" — it is "what interface should surface these MCP tools to my users?"

## Architecture

MCP uses a **client-server model** over JSON-RPC 2.0:

```
┌─────────────────────────────────────────────────────┐
│                      Host                           │
│  (Claude Desktop, Cursor, your custom agent app)    │
│                                                     │
│   ┌──────────┐         ┌──────────────────────┐    │
│   │  MCP     │ ──────▶ │   MCP Server A       │    │
│   │  Client  │         │   (GitHub tools)     │    │
│   │          │ ──────▶ │   MCP Server B       │    │
│   └──────────┘         │   (database tools)   │    │
│        ▲               └──────────────────────┘    │
│        │                                           │
│   LLM / Agent                                      │
└─────────────────────────────────────────────────────┘
```

| Component | Role |
|-----------|------|
| **Host** | The application that embeds the LLM (Claude Desktop, your app) |
| **Client** | The MCP connector running inside the host; manages one connection per server |
| **Server** | An external service that exposes tools, data, and prompts through MCP |

## Three Primitives

MCP servers expose three types of capability:

### Tools
Functions the model can call. A GitHub MCP server might expose `create_issue`, `list_pull_requests`, or `search_code`. Each tool has:
- A name and description (so the model knows when to use it)
- A typed input schema (JSON Schema — what parameters the model must provide)
- A typed output format (what the model receives back)

### Resources
Read-only context and data that can be injected into the model's context window — files, database records, API responses. Resources are for *reading*, tools are for *acting*.

### Prompts
Reusable prompt templates and workflows that a server can offer. Clients can list available prompts and fetch them with arguments filled in.

## Dynamic Tool Discovery

One of MCP's key advantages over static function calling: when a client connects to a server, it **queries the server's capabilities at runtime**. The server responds with its current tool list, schemas, and descriptions. This means:

- Tools can be added to a server without redeploying clients
- The model selects tools based on their descriptions, not hardcoded logic
- A single client can connect to dozens of servers and present a unified tool catalog

## Transport

MCP supports two transport modes:

| Transport | Use case |
|-----------|----------|
| **stdio** | Local tools — client spawns the server as a subprocess; communication over stdin/stdout |
| **Streamable HTTP (with SSE)** | Remote/production — server runs independently; client uses HTTP POST + optional Server-Sent Events for streaming responses |

## What MCP Does Not Do

- **It does not handle agent-to-agent communication.** That is [A2A](a2a.md)'s job. MCP is agent → tool; A2A is agent → agent.
- **It does not enforce security.** Authentication and authorization are your responsibility. MCP defines *how* to call tools, not *who* is allowed to.
- **It does not replace APIs.** MCP wraps existing APIs in a standard interface. The underlying API still exists; MCP is the adapter.

## A Realistic Production Agent

An agent that is both an MCP client *and* an A2A participant looks like this:

```
User query
    │
    ▼
Orchestrator Agent
    │
    ├─── MCP client ──▶ Postgres MCP server (data tool)
    ├─── MCP client ──▶ GitHub MCP server (code tool)
    ├─── MCP client ──▶ Amprealize wiki MCP (knowledge tool)
    │
    └─── A2A client ──▶ Specialist Agent (delegates sub-task)
```

## Security Considerations

Because MCP enables powerful real-world actions, teams using it in production should:

1. **Authenticate at the server boundary** — validate the caller before executing any tool
2. **Scope permissions per tool** — a read-only tool should not have write access to its underlying system
3. **Validate all inputs** — MCP schemas define structure but not business-rule safety
4. **Audit tool calls** — log every invocation with caller identity and result for compliance

## See Also

- [Agent-to-Agent Protocol (A2A)](a2a.md) — how agents communicate with *other agents*
- [Multi-Agent Orchestration](multi-agent.md) — coordinating multiple agents
- [Agent Harnesses & Context Fragments](agent-harness.md) — the harness that calls MCP tools
- [Semantic Layer & NL-to-Data](semantic-layer.md) — applying MCP to analytics pipelines
