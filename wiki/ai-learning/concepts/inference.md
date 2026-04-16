---
title: "Inference & Generation"
type: concept
difficulty: intermediate
prerequisites:
  - concepts/transformers.md
tags:
  - generation
  - architecture
last_updated: "2026-04-09"
sources:
  - "https://huggingface.co/docs/transformers/generation_strategies"
amprealize_relevance: "Understanding generation parameters (temperature, top-p) helps tune Amprealize's LLM calls for different tasks — low temperature for code, higher for creative synthesis."
visibility: public
---

# Inference & Generation

## Why This Matters

When an LLM "writes", it's really predicting one token at a time. Understanding how this works explains why models sometimes hallucinate, why temperature matters, and what you're actually tuning.

## The Intuition

Imagine autocomplete on your phone, but much better. After each word, the model looks at everything so far and picks the most likely next word. The key insight: it doesn't "plan" a whole sentence — it just picks the next token, then the next, then the next.

## How Autoregressive Generation Works

```
Input: "The capital of France is"
    ↓
Model predicts distribution over vocabulary:
  "Paris": 0.85
  "Lyon": 0.03
  "a": 0.02
  ...
    ↓
Sample or pick the highest probability → "Paris"
    ↓
Input becomes: "The capital of France is Paris"
    ↓
Repeat until stop token or max length
```

## Key Parameters

### Temperature

Controls randomness of sampling.

| Value | Behavior | Use Case |
|-------|----------|----------|
| 0.0 | Always pick highest probability (greedy) | Code generation, factual Q&A |
| 0.7 | Moderate randomness | General conversation |
| 1.0 | Sample according to probabilities | Creative writing |
| > 1.0 | More random than the model's distribution | Brainstorming (use carefully) |

### Top-p (Nucleus Sampling)

Only sample from the smallest set of tokens whose cumulative probability exceeds `p`.
- `top_p=0.9`: Consider tokens until 90% of probability mass is covered
- `top_p=1.0`: Consider all tokens (equivalent to temperature-only sampling)

### Top-k

Only consider the k most likely tokens.
- `top_k=50`: Standard
- `top_k=1`: Greedy decoding (same as temperature=0)

## Why Hallucinations Happen

The model always picks a next token — it never says "I don't know what comes next." If the training data doesn't cover a topic well, the model will still confidently generate plausible-sounding but incorrect tokens.

## See Also

- [Transformers](transformers.md) — The architecture doing the predicting
- [Tokenization](tokenization.md) — The vocabulary being sampled from
- [Prompt Engineering](prompt-engineering.md) — Influencing what gets generated
