---
title: "Transformers"
type: concept
difficulty: intermediate
prerequisites:
  - concepts/attention.md
  - concepts/embeddings.md
tags:
  - architecture
  - fundamentals
last_updated: "2026-04-09"
sources:
  - "https://arxiv.org/abs/1706.03762"
amprealize_relevance: "Every LLM Amprealize calls (GPT-4, Claude, Llama) is a transformer. Understanding the architecture explains model behavior, context limits, and why certain prompting strategies work."
visibility: public
---

# Transformers

## Why This Matters

Transformers are the architecture behind every modern LLM. Understanding them explains why models have context windows, why they sometimes hallucinate, and why scaling works.

## The Intuition

Think of a transformer as an assembly line where each station (layer) refines a rough draft. The input text enters as raw tokens, gets converted to embeddings, then passes through layer after layer. Each layer uses attention to remix information between positions, gradually building up a richer understanding.

## Architecture Overview

```
Input Text
    ↓
[Tokenization] → token IDs
    ↓
[Embedding Layer] → vectors
    ↓
[Transformer Block × N]
  ├── Multi-Head Self-Attention
  ├── Layer Normalization
  ├── Feed-Forward Network
  └── Layer Normalization
    ↓
[Output Head] → next token probabilities
```

## Key Concepts

### Encoder vs Decoder

- **Encoder-only** (BERT): Sees all tokens at once. Good for understanding (classification, embedding).
- **Decoder-only** (GPT, Claude, Llama): Sees tokens left-to-right. Good for generation.
- **Encoder-Decoder** (T5, original Transformer): Encodes input, then generates output. Good for translation.

### Scaling Laws

More parameters + more data + more compute = better performance (Chinchilla scaling laws). This is why models keep getting bigger.

### Context Window

The maximum number of tokens a model can process at once. Limited by memory (attention is $O(n^2)$ in sequence length).

## See Also

- [Attention Mechanism](attention.md) — The core building block
- [Inference & Generation](inference.md) — How transformers produce text
