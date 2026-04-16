---
title: "FAISS & Vector Databases"
type: technology
difficulty: intermediate
prerequisites:
  - concepts/embeddings.md
tags:
  - retrieval
  - infrastructure
last_updated: "2026-04-09"
sources:
  - "https://github.com/facebookresearch/faiss"
amprealize_relevance: "Amprealize uses FAISS for behavior retrieval in BCI (Behavior-Conditioned Inference). The FAISS index stores behavior embeddings for fast similarity search during context composition."
visibility: public
---

# FAISS & Vector Databases

## Why This Matters

Once you have embeddings, you need somewhere to store and search them efficiently. FAISS (Facebook AI Similarity Search) is a library purpose-built for this: finding the most similar vectors in a collection of millions.

## The Intuition

Imagine you have a library with 10,000 books, each with GPS coordinates on a concept map (their embeddings). Someone asks a question, and you need to find the 5 nearest books. Checking every single book is slow. FAISS uses clever indexing tricks — like dividing the map into neighborhoods — so you only need to check a few dozen candidates instead of all 10,000.

## How FAISS Works

### Index Types

| Index | Speed | Accuracy | Memory | Best For |
|-------|-------|----------|--------|----------|
| `IndexFlatL2` | Slow (exact) | Perfect | High | < 10K vectors |
| `IndexIVFFlat` | Fast | Very good | Medium | 10K–1M vectors |
| `IndexIVFPQ` | Very fast | Good | Low | > 1M vectors |
| `IndexHNSW` | Fast | Very good | Medium | Read-heavy workloads |

### Basic Usage

```python
import faiss
import numpy as np

# Create index for 384-dimensional vectors
index = faiss.IndexFlatL2(384)

# Add vectors
vectors = np.random.rand(1000, 384).astype('float32')
index.add(vectors)

# Search for 5 nearest neighbors
query = np.random.rand(1, 384).astype('float32')
distances, indices = index.search(query, k=5)
```

## FAISS vs Vector Databases

| Feature | FAISS | Pinecone/Weaviate/Qdrant |
|---------|-------|--------------------------|
| Deployment | Library (in-process) | Managed service |
| Metadata filtering | Manual | Built-in |
| Persistence | File-based | Cloud-managed |
| Cost | Free | Per-query pricing |
| Best for | Embedded, local, < 1M vectors | Production, managed, > 1M vectors |

Amprealize uses FAISS because behavior collections are small enough (< 10K) to fit in-process, and it avoids external service dependencies.

## See Also

- [Embeddings](../concepts/embeddings.md) — What gets stored in FAISS
- [RAG](../concepts/rag.md) — The pattern that uses vector search
- [Hybrid Retrieval](../concepts/hybrid-retrieval.md) — Combining vector search with keyword search
