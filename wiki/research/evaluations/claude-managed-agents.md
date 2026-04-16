---
title: "Claude Managed Agents \u2014 Evaluation Summary"
type: evaluation-summary
last_updated: '2026-04-10'
confidence: medium
sources:
- https://platform.claude.com/docs/en/managed-agents/overview
- https://platform.claude.com/docs/en/managed-agents/quickstart
- https://platform.claude.com/docs/en/managed-agents/sessions
- https://platform.claude.com/docs/en/managed-agents/defining-agents
- https://platform.claude.com/docs/en/managed-agents/outcomes
- https://platform.claude.com/docs/en/managed-agents/multiagent
- https://platform.claude.com/docs/en/managed-agents/memory-stores
tags:
- agents
- anthropic
- managed-runtime
- evaluation
- competitive-landscape
---

## Verdict: ADAPT (6/10)

Claude Managed Agents (beta, 2026-04-01) is Anthropic's fully-managed agent runtime. You define an agent (model + system prompt + tools + MCP + skills), an environment (container config), and launch sessions where Claude autonomously runs bash, edits files, searches the web, and connects to MCP servers — all in Anthropic-hosted cloud containers.

**Bottom line**: Well-designed infrastructure that overlaps with ~7K-8.5K LOC of Amprealize's agent infrastructure. Full adoption is premature (beta, vendor lock-in, model lock-in). The right play is **extract specific patterns** — the outcomes/grader system and memory stores — while keeping our differentiated agent intelligence.

---

## Core Architecture

| Concept | Description |
|---------|-------------|
| **Agent** | Reusable, versioned config (model, system prompt, tools, MCP servers, skills). Claude 4.5+ models including Opus 4.6. |
| **Environment** | Ubuntu 22.04 container. Up to 8GB RAM, 10GB disk. Python 3.12+, Node 20+, Go 1.22+, Rust, Java, Ruby, PHP, C/C++. |
| **Session** | Running agent instance. Stateful multi-turn. Files persistent within session. Isolated containers per session. |
| **Events/Streaming** | SSE-based. User → Agent → Session events. Server-side history persistence. |

### Built-in Tools (`agent_toolset_20260401`)
bash, read, write, edit, glob, grep, web_fetch, web_search. Individually toggleable with permission policies (always_allow / always_ask).

### MCP Integration
MCP servers declared at agent level. Vault-based auth with auto-refresh OAuth2 credentials.

---

## Research Preview Features

1. **Outcomes/Grader** (HIGH VALUE): Define rubric → agent works → separate grader evaluates in isolated context → iterates (max 20). Returns per-criterion breakdown. Deliverables to `/mnt/session/outputs/`.
2. **Multiagent**: Coordinator + callable_agents. One level of delegation. Shared filesystem, isolated context per thread.
3. **Memory Stores**: Persistent across sessions, workspace-scoped. Auto-read before tasks, auto-write learnings. CRUD + version history + redaction. 100KB per memory, optimistic concurrency via SHA256.

---

## Scores

| Dimension | Score | Notes |
|-----------|-------|-------|
| Relevance | 8/10 | Directly addresses agent execution — our core domain |
| Feasibility | 6/10 | Beta API, no pricing, vendor lock-in concerns |
| Novelty | 7/10 | Outcomes/grader is novel; rest is expected evolution |
| ROI | 5/10 | High integration cost for modest gain over existing infra |
| Safety | 7/10 | Sandboxed containers good; data-leaving-infra is a concern |
| **Overall** | **6/10** | |

---

## What to Extract for Amprealize

### 1. Outcomes/Grader Pattern (HIGH)
Separate-context evaluator grades agent work against a rubric. Directly applicable to compliance review and behavior validation. Prototype using existing LLM infra — strengthen `compliance_service.py` and `agent_review_service.py`. Tracked under GUIDEAI-896.

### 2. Memory Stores Architecture (MEDIUM)
Versioned, path-based memory with optimistic concurrency and audit trail. Consider whether WikiService should adopt: SHA-based conflict detection, memory versioning/redaction, auto-read/auto-write agent behavior.

### 3. Permission Policy Model (LOW-MEDIUM)
always_allow / always_ask gating with per-tool overrides. Cleaner than current ExecutionPolicy. Worth abstracting into ToolExecutor.

---

## What NOT to Adopt

- **The agent loop itself** — Our GEP phases, behavior adherence tracking, and multi-surface parity are more sophisticated.
- **Container execution** — BreakerAmp for test infra; Anthropic-hosted containers are a non-starter for enterprise.
- **MCP vault system** — We have auth_tokens.py and agent_auth.py.

---

## Competitive Landscape

| Platform | Type | Maturity | Key Differentiator |
|----------|------|----------|--------------------|
| Claude Managed Agents | Managed runtime | Beta (2026-04) | Outcomes/grader, built-in caching |
| OpenAI Assistants API | Managed runtime | GA (v2) | File search, code interpreter sandbox |
| Google Vertex AI Agent Builder | Agent platform | GA | Multi-modal grounding, GCP integration |
| AWS Bedrock Agents | Managed runtime | GA | Multi-model, knowledge bases with RAG |
| LangGraph Cloud | Orchestration | GA | Model-agnostic, stateful graph execution |
| CrewAI | Multi-agent framework | Stable OSS | Python-native, role-based agents |
| **Amprealize** | Custom platform | Internal | GEP phases, behaviors, compliance, parity testing |

---

## Related Work Items

- **GUIDEAI-895**: Add Session Mode for lightweight agent execution (goal)
- **GUIDEAI-896**: Spike: Prototype outcomes/grader pattern for compliance reviews
- **GUIDEAI-869**: Implement always-on persistent agent infrastructure
- **GUIDEAI-718**: Adopt OpenClaw production patterns for multi-agent operations
