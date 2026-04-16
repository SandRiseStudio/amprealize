---
title: "Hybrid Retrieval"
type: concept
difficulty: intermediate
prerequisites:
  - concepts/rag.md
  - concepts/embeddings.md
tags:
  - retrieval
  - patterns
last_updated: "2026-04-09"
sources:
  - "https://arxiv.org/abs/2210.11934"
amprealize_relevance: "Amprealize uses hybrid retrieval in its advanced retrieval service — combining FAISS vector search with keyword-based filtering for behavior and context retrieval."
visibility: public
---

# Hybrid Retrieval

## Why This Matters

Neither pure keyword search nor pure semantic search is perfect. Keyword search misses synonyms ("car" won't match "automobile"). Semantic search can miss exact terms ("error code XYZ-123"). Hybrid retrieval combines both for the best of both worlds.

## The Intuition

Imagine searching for a restaurant. Semantic search is like asking a friend: "Know any good Italian places with outdoor seating?" Keyword search is like Ctrl+F on a list: "patio Italian downtown." Neither alone is perfect, but together they cover each other's blind spots.

## How It Works

```
Query: "How does BCI handle behavior retrieval?"
    ↓
┌──────────────────┐    ┌──────────────────┐
│ Semantic Search   │    │ Keyword Search    │
│ (FAISS/vectors)   │    │ (BM25/TF-IDF)    │
│ → top 20 by       │    │ → top 20 by       │
│   cosine sim      │    │   term frequency   │
└────────┬─────────┘    └────────┬─────────┘
         │                       │
         └───────┬───────────────┘
                 ↓
         [Reciprocal Rank Fusion]
                 ↓
         Final top-k results
```

## Fusion Strategies

| Strategy | Description | Trade-off |
|----------|-------------|-----------|
| **Reciprocal Rank Fusion (RRF)** | Score = Σ 1/(k + rank_i) | Simple, robust, no tuning |
| **Weighted combination** | Score = α × semantic + (1-α) × keyword | Needs tuning of α |
| **Cross-encoder re-ranking** | Re-rank union with a neural model | Best quality, most expensive |

## When to Use

- **Semantic only**: Conceptual questions ("What is attention?")
- **Keyword only**: Exact matches ("error code E1234")
- **Hybrid**: Real-world queries that mix concepts and specifics

## See Also

- [RAG](rag.md) — The broader pattern hybrid retrieval improves
- [FAISS](../technologies/faiss.md) — The vector search component
- [Behavior Retrieval In Practice](../in-practice/bci-in-amprealize.md) — Hybrid retrieval in action
