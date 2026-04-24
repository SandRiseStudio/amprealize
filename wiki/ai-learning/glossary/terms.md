---
title: AI/ML Glossary
type: glossary
difficulty: beginner
prerequisites: []
tags:
- reference
- terminology
last_updated: '2026-04-15'
sources: []
amprealize_relevance: Quick reference for AI/ML terminology used across Amprealize's
  codebase and documentation.
visibility: public
---

# AI/ML Glossary

Quick reference for core terminology. Each entry links to a deeper concept page where available.

---

**Attention** — Mechanism that lets a model weigh the importance of different parts of input relative to each other. Core of the [Transformer](../concepts/attention.md) architecture.

**BCI (Behavior-Conditioned Inference)** — Amprealize's RAG implementation for retrieving and injecting procedural behaviors into agent context. See [BCI In Practice](../in-practice/bci-in-amprealize.md).

**Chain of Thought (CoT)** — Prompting technique that asks the model to show its reasoning step by step, improving accuracy on complex tasks. See [Prompt Engineering](../concepts/prompt-engineering.md).

**Context Window** — Maximum number of tokens a model can process in a single call. Ranges from 4K to 200K+ depending on model.

**Cosine Similarity** — Measure of angle between two vectors. Used to compare [embeddings](../concepts/embeddings.md). Range: -1 (opposite) to 1 (identical).

**Embedding** — Dense vector representation of text that captures semantic meaning. See [Embeddings](../concepts/embeddings.md).

**FAISS** — Facebook AI Similarity Search. Library for efficient nearest-neighbor search over vectors. See [FAISS](../technologies/faiss.md).

**Few-Shot** — Providing examples in the prompt to guide model behavior. Zero-shot = no examples, one-shot = one example.

**Fine-Tuning** — Continuing to train a pre-trained model on domain-specific data. Expensive but bakes knowledge into weights.

**Hallucination** — When a model generates confident but factually incorrect content. Caused by autoregressive generation without knowledge grounding.

**Hybrid Retrieval** — Combining semantic (vector) search with keyword (BM25/TF-IDF) search. See [Hybrid Retrieval](../concepts/hybrid-retrieval.md).

**Inference** — Running a trained model to produce output. See [Inference & Generation](../concepts/inference.md).

**LLM (Large Language Model)** — Neural network with billions of parameters trained on text to predict next tokens. GPT-4, Claude, Llama are LLMs.

**MCP (Model Context Protocol)** — Standard for tools and resources that LLMs can access. Amprealize exposes its functionality as MCP tools.

**Multi-Agent** — System where multiple specialized AI agents collaborate on tasks. See [Multi-Agent Orchestration](../concepts/multi-agent.md).

**RAG (Retrieval-Augmented Generation)** — Pattern of retrieving relevant context before generating to improve accuracy. See [RAG](../concepts/rag.md).

**Temperature** — Parameter controlling randomness in generation. 0 = deterministic, 1 = sample from distribution. See [Inference](../concepts/inference.md).

**Token** — Basic unit of text that LLMs process. ~4 characters or ¾ of a word. See [Tokenization](../concepts/tokenization.md).

**Top-p (Nucleus Sampling)** — Sampling strategy that considers tokens until cumulative probability exceeds p. See [Inference](../concepts/inference.md).

**Transformer** — Neural network architecture based on self-attention. Foundation of all modern LLMs. See [Transformers](../concepts/transformers.md).

**Vector Database** — Storage system optimized for similarity search over embedding vectors. See [FAISS](../technologies/faiss.md).

**Bitter Lesson** — Richard Sutton's 2019 observation that general methods leveraging computation consistently outperform approaches leveraging hand-crafted human knowledge. Implies that search and learning are the only strategies that scale indefinitely. See [The Bitter Lesson & Search at Scale](../concepts/bitter-lesson.md).

**Context Fragment** — A discrete unit of information explicitly loaded into an agent's context window by the harness. Each fragment represents a deliberate design decision about what the model needs to see. See [Agent Harnesses & Context Fragments](../concepts/agent-harness.md).

**Experiential Memory** — Agent memory accumulated over interactions, analogous to human episodic memory. Includes both raw traces and distilled higher-level patterns derived from those traces. See [Experiential Memory for AI Agents](../concepts/experiential-memory.md).

**Harness** — The orchestration layer that wraps an LLM: populating the context window, routing outputs, managing state between calls, and enforcing boundaries. Frameworks like LangChain and Anthropic's Agent SDK are harness implementations. See [Agent Harnesses & Context Fragments](../concepts/agent-harness.md).

**Memory Distillation** — The process of converting raw agent experience traces into compact, generalizable, retrievable higher-level primitives. Analogous to how humans consolidate episodic memories into general knowledge. See [Experiential Memory for AI Agents](../concepts/experiential-memory.md).

**AI-Native IDE** — A code editor rebuilt from the ground up around AI capabilities (e.g., Cursor, Windsurf, Zed). You install it *instead of* VS Code. Distinct from an IDE Extension, which adds AI to your existing editor. See [AI Ecosystem Map](../concepts/ai-ecosystem-map.md).

**A2A (Agent-to-Agent Protocol)** — Open protocol, originally by Google and now governed by the Linux Foundation, for agent-to-agent communication. Agents advertise capabilities via Agent Cards and exchange stateful Tasks using JSON-RPC 2.0 over HTTPS. Complements MCP (agent → tool). See [Agent-to-Agent Protocol (A2A)](../concepts/a2a.md).

**Agent Card** — A JSON document published at `/.well-known/agent.json` that describes an A2A-compatible agent's skills, authentication requirements, streaming capabilities, and endpoint URL. The machine-readable equivalent of a business card for AI agents. See [Agent-to-Agent Protocol (A2A)](../concepts/a2a.md).

**Semantic Layer** — A business logic layer sitting between raw data sources (databases, data warehouses) and consumers (dashboards, agents, APIs). Encodes metric definitions, access controls, dimension hierarchies, and join logic. Enables consistent, governed, NL-driven data access at scale. See [Semantic Layer & NL-to-Data Architecture](../concepts/semantic-layer.md).

**Tool RAG** — Applying the RAG (Retrieval-Augmented Generation) pattern to tool selection. When an agent has access to a large catalog of MCP tools, Tool RAG performs semantic search over tool descriptions to surface only the most relevant tools for the current query — reducing token cost and selection confusion. See [Model Context Protocol (MCP)](../concepts/mcp.md).

**ChatGPT** — OpenAI's consumer chat application (Layer 3). Uses GPT-5.x models. Distinct from the models themselves (GPT-5.4, GPT-5.5) and from Codex (OpenAI's separate coding agent product). Available on web, iOS, Android, and desktop. See [AI Ecosystem Map](../concepts/ai-ecosystem-map.md).

**Codex** — OpenAI's autonomous coding agent product (Layer 4). Available as a web app (chatgpt.com/codex), CLI (open-source), and IDE extension. Uses GPT-5.3-Codex and GPT-5.5 models internally. Distinct from ChatGPT (general chat) and from "GPT-5.3-Codex" (the model name). See [AI Ecosystem Map](../concepts/ai-ecosystem-map.md).

**IDE Extension** — A plugin installed inside your existing code editor (VS Code, JetBrains, Xcode, etc.) that adds AI capabilities without replacing the editor itself. Examples: GitHub Copilot, Claude Code extension, Gemini Code Assist. Distinct from an AI-Native IDE (which replaces the editor) and a CLI (which runs in a terminal). See [AI Ecosystem Map](../concepts/ai-ecosystem-map.md).

**Inference Provider** — A service that hosts and serves foundation model weights via an API, so applications don't have to run the model themselves. Examples: OpenAI API, Anthropic API, AWS Bedrock, Google Vertex AI, OpenRouter, Groq, Ollama (local). The same model (e.g., Claude Sonnet 4.6) may be available from multiple inference providers. See [AI Ecosystem Map](../concepts/ai-ecosystem-map.md).

**Foundation Model** — A large neural network trained on massive datasets that serves as the base for many downstream applications and products. The "weights" — the actual AI brain. A foundation model is not an app: GPT-5.4 is a model; ChatGPT is an app that uses it. See [AI Ecosystem Map](../concepts/ai-ecosystem-map.md).

**Agent** — A software system that is given a *goal* and autonomously plans, uses tools, observes results, and iterates until the goal is complete. Distinct from a chatbot (single response) or assistant (reactive, stateless). Key properties: runs a loop, takes real actions via tools, maintains memory across steps. See [AI Agents: What They Are and How They Work](../concepts/agents.md).

**Agent Loop** — The core execution pattern of an AI agent: Perceive → Reason → Plan → Act → Observe → (update memory) → back to Reason. The loop continues until the task is done or a stopping condition is reached. See [AI Agents](../concepts/agents.md).

**ReAct** — "Reason + Act." The dominant agent architecture (Yao et al., ICLR 2023) where the model alternates between generating a Thought (reasoning about the current state) and an Action (tool call), receiving an Observation after each action. See [AI Agents](../concepts/agents.md).

**Tool Call** — A structured JSON output emitted by the model to invoke an external function (search, code execution, file read, etc.). The surrounding runtime intercepts the output, executes the function, and returns the result as an Observation. See [AI Agents](../concepts/agents.md).

**Observation** — The result returned to the model after a tool executes. Feeds back into the next reasoning step, grounding the model's reasoning in real-world data rather than hallucination. See [AI Agents](../concepts/agents.md).

**Human-in-Loop** — A design pattern where an agent pauses at key decision points and waits for human approval before taking irreversible actions (sending emails, merging code, deleting data, spending money). Most production agents in 2026 use this pattern. See [AI Agents](../concepts/agents.md).
