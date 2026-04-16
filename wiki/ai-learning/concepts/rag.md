---
title: "RAG (Retrieval-Augmented Generation)"
type: concept
difficulty: intermediate
prerequisites:
  - concepts/embeddings.md
  - technologies/faiss.md
tags:
  - retrieval
  - architecture
  - patterns
last_updated: "2026-04-09"
sources:
  - "https://arxiv.org/abs/2005.11401"
amprealize_relevance: "Amprealize's core architecture IS a RAG system. BCI retrieves relevant behaviors, ContextComposer assembles them, and the LLM generates behavior-conditioned responses."
visibility: public
---

# RAG (Retrieval-Augmented Generation)

## Why This Matters

RAG is the most practical pattern for making LLMs useful with your own data. Instead of fine-tuning (expensive, brittle), you retrieve relevant context at query time and inject it into the prompt.

## The Intuition

Think of an open-book exam. The LLM is the student, and RAG is the process of finding the right pages in the textbook before answering each question. Without RAG, the model relies only on what it memorized during training. With RAG, it gets to look things up.

## How It Works

```
User Query
    ↓
[1. Embed Query] → query vector
    ↓
[2. Search Vector DB] → top-k relevant documents
    ↓
[3. Build Prompt] = system instructions + retrieved docs + user query
    ↓
[4. LLM Generates] → grounded answer with citations
```

## Key Design Decisions

### Chunk Size

| Size | Pros | Cons |
|------|------|------|
| Small (128 tokens) | Precise retrieval | Loses context |
| Medium (512 tokens) | Good balance | Standard choice |
| Large (1024+ tokens) | Rich context | Dilutes relevance |

### Retrieval Strategy

- **Naive RAG**: Embed query → top-k → stuff into prompt
- **Advanced RAG**: Re-ranking, query expansion, hybrid search
- **Modular RAG**: Routing, filtering, iterative retrieval

### Common Failure Modes

1. **Retrieved but not used**: Model ignores context (fix: better prompting)
2. **Wrong context retrieved**: Embedding mismatch (fix: hybrid retrieval, re-ranking)
3. **Context too large**: Exceeds token budget (fix: summarization, chunking)
4. **Hallucination despite context**: Model confabulates (fix: citation enforcement)

## See Also

- [Hybrid Retrieval](hybrid-retrieval.md) — Improving RAG with keyword + semantic search
- [Prompt Engineering](prompt-engineering.md) — Crafting prompts that use retrieved context
- [BCI In Practice](../in-practice/bci-in-amprealize.md) — How Amprealize implements RAG for behaviors
