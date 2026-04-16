---
title: "Attention Mechanism"
type: concept
difficulty: intermediate
prerequisites:
  - concepts/tokenization.md
  - concepts/embeddings.md
tags:
  - transformers
  - architecture
last_updated: "2026-04-09"
sources:
  - "https://arxiv.org/abs/1706.03762"
amprealize_relevance: "Understanding attention explains why LLMs can follow instructions, maintain context, and why context window size matters for Amprealize's context composition."
visibility: public
---

# Attention Mechanism

## Why This Matters

Attention is the core innovation that makes modern LLMs work. It's the mechanism that lets a model look at all parts of the input simultaneously and decide which parts are most relevant to each other.

## The Intuition

Imagine reading a long document and highlighting the most important parts for answering a specific question. Attention does this automatically — for every position in the text, it computes a "relevance score" against every other position.

In the sentence "The cat sat on the mat because **it** was tired", attention lets the model figure out that "it" refers to "cat" (not "mat") by computing high attention scores between "it" and "cat".

## How It Works

The key equation: $\text{Attention}(Q, K, V) = \text{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V$

Where:
- **Q** (Query): "What am I looking for?"
- **K** (Key): "What do I contain?"
- **V** (Value): "What information do I provide?"

Think of it like a library search:
1. You have a **query** (your question)
2. Each book has a **key** (its catalog entry)
3. You match your query against all keys to find relevant books
4. You read the **values** (actual content) of the matched books

## Multi-Head Attention

Instead of one attention computation, transformers use 8-96 "heads" in parallel. Each head learns to attend to different types of relationships:
- Head 1 might track syntax (subject-verb agreement)
- Head 2 might track coreference ("it" → "cat")
- Head 3 might track positional patterns

## Self-Attention vs Cross-Attention

- **Self-attention**: Input attends to itself (used in encoders and decoders)
- **Cross-attention**: Output attends to input (used in encoder-decoder models for translation)

## See Also

- [Transformers](transformers.md) — The full architecture built on attention
- [Embeddings](embeddings.md) — The vectors that attention operates on
