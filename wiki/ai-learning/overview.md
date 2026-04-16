---
title: AI/ML Concept Overview
type: overview
last_updated: 2026-04-09
---

# AI/ML Concept Overview

> A map of AI/ML concepts and how they relate to each other and to Amprealize.

## Foundation Layer

```
Tokens → Embeddings → Attention → Transformers → Inference
```

**Tokens**: The atomic units that LLMs process. Text gets split into tokens (subwords) before the model sees it.

**Embeddings**: Dense vector representations that capture semantic meaning. Tokens become embeddings; similar concepts cluster together in vector space.

**Attention**: The mechanism that lets transformers weigh which parts of input matter most for each output position. The key innovation behind modern LLMs.

**Transformers**: The architecture (Vaswani et al., 2017) that uses self-attention to process sequences in parallel. Foundation of GPT, Claude, etc.

**Inference**: Running a trained model to generate outputs. Where temperature, top-p, and other sampling parameters live.

## Retrieval Layer

```
Embeddings → Vector DB → RAG → Hybrid Retrieval
```

**Vector DB**: Stores and searches embeddings efficiently (e.g., FAISS, Pinecone). Enables similarity search at scale.

**RAG** (Retrieval-Augmented Generation): Retrieve relevant context from external sources, inject into prompt, then generate. Grounds LLM outputs in real data.

**Hybrid Retrieval**: Combines dense (embedding similarity) and sparse (keyword/BM25) search. Used in Amprealize's behavior retrieval system.

## Agent Layer

```
Prompt Engineering → Tool Use → Multi-Agent Orchestration
```

**Prompt Engineering**: Crafting inputs that reliably produce desired LLM behavior. Includes system prompts, few-shot examples, chain-of-thought.

**Tool Use**: LLMs calling external functions (MCP tools, APIs). Transforms LLMs from text generators into actors.

**Multi-Agent Orchestration**: Coordinating multiple specialized agents. Amprealize's GEP (Guided Execution Protocol) orchestrates 8 phases.

## Amprealize-Specific Layer

```
BCI → Behavior Extraction → Behavior Retrieval → Context Composition
```

**BCI** (Behavior-Conditioned Inference): Amprealize's core pattern — conditioning LLM inference on retrieved behaviors to produce consistent, governed outputs.

**Behavior Extraction**: Mining reusable behaviors from conversations, code, and agent outputs.

**Behavior Retrieval**: Finding relevant behaviors using hybrid retrieval (FAISS + keyword matching).

**Context Composition**: Assembling the final prompt from 6 sources with token budgeting. Manages the context window.

---

_This overview auto-updates as concept pages are added to the wiki._
