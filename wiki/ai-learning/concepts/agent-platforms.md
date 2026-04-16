---
title: "Managed Agent Platforms \u2014 Comparative Overview"
type: concept
last_updated: '2026-04-10'
difficulty: intermediate
prerequisites:
- '[LLMs](../concepts/llms.md)'
- '[Tool Use](../concepts/tool-use.md)'
tags:
- agents
- platforms
- managed-runtime
- comparison
amprealize_relevance: Evaluating managed agent platforms to identify patterns worth
  extracting into Amprealize's agent infrastructure
visibility: internal
sources:
- https://platform.claude.com/docs/en/managed-agents/overview
- https://platform.openai.com/docs/assistants/overview
- https://docs.aws.amazon.com/bedrock/latest/userguide/agents.html
- https://python.langchain.com/docs/langgraph
---

## What Are Managed Agent Platforms?

Managed agent platforms provide a hosted runtime where an LLM can autonomously execute tools, run code, and persist state — without the developer building their own agent loop, sandboxing, or streaming infrastructure. You configure an agent (model + tools + instructions) and the platform handles execution, isolation, and event delivery.

This is the "Heroku for agents" pattern: trade control for speed-to-deployment.

---

## Platform Comparison

### Claude Managed Agents (Anthropic)
- **Status**: Beta (2026-04-01)
- **Models**: Claude 4.5+, Opus 4.6
- **Execution**: Ubuntu 22.04 containers, 8GB RAM, 10GB disk
- **Tools**: Built-in (bash, read, write, edit, glob, grep, web_fetch, web_search) + custom + MCP
- **Unique**: Outcomes/grader (separate evaluator context), memory stores (versioned, persistent), multi-agent coordination
- **Limitations**: Claude-only, no self-hosting, 8GB container limit, beta stability risk

### OpenAI Assistants API
- **Status**: GA (v2)
- **Models**: GPT-4o, GPT-4o-mini
- **Execution**: Managed threads with tool calls
- **Tools**: Code Interpreter (sandboxed Python), File Search (vector store), Function Calling
- **Unique**: Built-in RAG via File Search, code interpreter sandbox with matplotlib/tables
- **Limitations**: OpenAI-only, no container access, limited to predefined tool types

### AWS Bedrock Agents
- **Status**: GA
- **Models**: Claude, Llama, Mistral, Titan, Cohere (multi-model)
- **Execution**: AWS Lambda-based action groups
- **Tools**: Action groups (Lambda functions), Knowledge Bases (RAG with OpenSearch/Pinecone)
- **Unique**: Multi-model support, deep AWS integration (S3, DynamoDB, etc.), knowledge bases with automatic chunking
- **Limitations**: AWS lock-in, Lambda cold starts, complex IAM configuration

### Google Vertex AI Agent Builder
- **Status**: GA
- **Models**: Gemini, PaLM
- **Execution**: Google Cloud Functions / Cloud Run
- **Tools**: Extensions, Data Stores, OpenAPI tools
- **Unique**: Multi-modal grounding (web + enterprise data), Dialogflow CX integration
- **Limitations**: GCP lock-in, less mature agent loop than competitors

### LangGraph Cloud
- **Status**: GA
- **Models**: Any (model-agnostic)
- **Execution**: Stateful graph execution with checkpointing
- **Tools**: Any Python function, tool nodes in graph
- **Unique**: Graph-based control flow, persistent state/checkpoints, human-in-the-loop branching, model-agnostic
- **Limitations**: Higher complexity to configure, LangSmith dependency for observability

### CrewAI
- **Status**: Stable (OSS)
- **Models**: Any (model-agnostic)
- **Execution**: Local Python processes or CrewAI Enterprise (hosted)
- **Tools**: Python functions, LangChain tools
- **Unique**: Role-based multi-agent (agents have role, goal, backstory), sequential/hierarchical process models
- **Limitations**: Less mature than managed offerings, no built-in sandboxing

---

## Key Decision Dimensions

| Dimension | What to Ask |
|-----------|-------------|
| **Model portability** | Must you support multiple LLM providers? → LangGraph/CrewAI. Single provider OK? → Managed runtimes. |
| **Sandboxing** | Need isolated code execution? → Claude Managed Agents, OpenAI Code Interpreter. |
| **Enterprise controls** | Need on-prem, audit trails, compliance? → Self-hosted or Bedrock Agents. |
| **Multi-agent** | Multi-agent delegation? → Claude (coordinator), CrewAI (role-based), LangGraph (graph nodes). |
| **Evaluation** | Built-in output evaluation? → Claude Outcomes/Grader is uniquely strong here. |
| **RAG** | Need knowledge base/retrieval? → Bedrock Knowledge Bases, OpenAI File Search. |

---

## Where Amprealize Fits

Amprealize is a **custom agent platform** — it builds the entire agent lifecycle rather than consuming a managed runtime. Key differentiators vs. all platforms above:

1. **8-phase GEP execution pipeline** — structured agent work with planning, execution, and review phases
2. **Behavior system** — procedural knowledge (behaviors) retrieved and applied to guide agent reasoning
3. **Compliance enforcement** — agent outputs validated against organizational policies
4. **Cross-surface parity** — Web, API, CLI, and MCP produce identical results
5. **Work item lifecycle** — boards → agents → PRs → reviews, full traceability
6. **Model-agnostic** — LLMClient abstraction supports multiple providers

### When to Use Managed Platforms Instead

- **Prototyping**: Quick proof-of-concept with minimal infrastructure → OpenAI Assistants or Claude Managed Agents
- **Sandboxed code execution**: Agent needs to run untrusted code → Claude Managed Agents containers
- **Simple Q&A agents**: No need for GEP pipeline → any managed runtime suffices
- **AWS-native workloads**: Already on AWS with data in S3/DynamoDB → Bedrock Agents

### When Amprealize is the Right Choice

- **Governed agent work**: Compliance-sensitive tasks requiring behavior adherence and audit trails
- **Multi-surface delivery**: Same agent logic must work across CLI, API, MCP, and web
- **Enterprise requirements**: On-premise deployment, multi-tenancy, custom auth
- **Self-improving agents**: Behavior extraction, metacognitive reflection, quality gates

---

## Concepts to Extract from Managed Platforms

| Concept | Source | Value | Status |
|---------|--------|-------|--------|
| Outcomes/Grader pattern | Claude Managed Agents | HIGH | GUIDEAI-896 (spike) |
| Memory stores with versioning | Claude Managed Agents | MEDIUM | Evaluate for WikiService |
| Permission policies (allow/ask) | Claude Managed Agents | LOW-MEDIUM | Abstract into ToolExecutor |
| Code Interpreter sandboxing | OpenAI Assistants | MEDIUM | Evaluate for BreakerAmp |
| Knowledge Base auto-chunking | AWS Bedrock | LOW | Our wiki handles this differently |
| Graph-based control flow | LangGraph | LOW | GEP phases serve similar purpose |
