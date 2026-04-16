---
title: "Embeddings"
type: concept
difficulty: beginner
prerequisites:
  - concepts/tokenization.md
tags:
  - nlp
  - retrieval
  - fundamentals
last_updated: "2026-04-09"
sources:
  - "https://platform.openai.com/docs/guides/embeddings"
amprealize_relevance: "Amprealize uses embeddings for behavior retrieval (BCI), semantic search across evaluations, and context composition. The embedding model powers the behavior matching engine."
visibility: public
---

# Embeddings

## Why This Matters

Embeddings are how machines understand meaning. They turn words, sentences, or entire documents into lists of numbers (vectors) where similar meanings end up near each other.

## The Intuition

Imagine a map where every concept has GPS coordinates. "Dog" and "puppy" would be right next to each other. "Dog" and "refrigerator" would be far apart. Embeddings are those GPS coordinates — but instead of 2 dimensions (lat/long), they use hundreds or thousands of dimensions.

## How It Works

1. **Text goes in** → "The cat sat on the mat"
2. **Encoder processes it** → Transformer layers attend to relationships between tokens
3. **Vector comes out** → `[0.023, -0.156, 0.891, ..., 0.034]` (typically 384-1536 dimensions)

The magic is that these vectors capture *semantic meaning*:
- `embed("king") - embed("man") + embed("woman") ≈ embed("queen")`
- `cosine_similarity(embed("happy"), embed("joyful")) ≈ 0.95`

## Common Embedding Models

| Model | Dimensions | Speed | Quality |
|-------|-----------|-------|---------|
| OpenAI text-embedding-3-small | 1536 | Fast | High |
| sentence-transformers/all-MiniLM-L6-v2 | 384 | Very fast | Good |
| OpenAI text-embedding-3-large | 3072 | Medium | Very high |

## Key Operations

- **Cosine similarity**: Measures angle between vectors (most common)
- **Dot product**: Faster but requires normalized vectors
- **Euclidean distance**: Measures straight-line distance

## See Also

- [Vector Databases & FAISS](../technologies/faiss.md) — Where embeddings get stored and searched
- [RAG (Retrieval-Augmented Generation)](rag.md) — Using embeddings to find relevant context
- [Tokenization](tokenization.md) — What happens before embedding
