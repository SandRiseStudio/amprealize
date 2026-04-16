---
title: "Prompt Engineering"
type: concept
difficulty: beginner
prerequisites:
  - concepts/tokenization.md
tags:
  - prompting
  - practical
last_updated: "2026-04-09"
sources:
  - "https://www.promptingguide.ai/"
amprealize_relevance: "Amprealize's ContextComposer is essentially an automated prompt engineer — it assembles system prompts, retrieved behaviors, and user context into optimized prompts."
visibility: public
---

# Prompt Engineering

## Why This Matters

The difference between a useless LLM response and a brilliant one is often just the prompt. Prompt engineering is the art and science of crafting inputs that reliably produce the outputs you want.

## The Intuition

Think of prompt engineering like giving instructions to a very capable but very literal intern. They'll do exactly what you ask — so you need to be precise about what you want, provide examples of good output, and specify constraints.

## Core Techniques

### 1. Role Setting

Tell the model who it is:
```
You are an expert Python developer specializing in async programming.
```

### 2. Few-Shot Examples

Show, don't just tell:
```
Convert these to SQL:
- "all users from New York" → SELECT * FROM users WHERE city = 'New York'
- "orders over $100" → SELECT * FROM orders WHERE total > 100
- "active subscriptions" →
```

### 3. Chain of Thought

Ask the model to reason step by step:
```
Think through this step by step before giving your final answer.
```

### 4. Output Format Specification

Be explicit about structure:
```
Respond in JSON with keys: summary, confidence (0-1), sources (array of URLs)
```

### 5. Constraints

Set boundaries:
```
Use only information from the provided context. If unsure, say "I don't know."
```

## Common Anti-Patterns

| Anti-Pattern | Problem | Fix |
|-------------|---------|-----|
| Vague instructions | Unpredictable output | Be specific about format, length, style |
| No examples | Model guesses your intent | Add 2-3 few-shot examples |
| Contradictory constraints | Model picks one randomly | Review for consistency |
| Token-stuffing | Buries the real question | Put key instruction first or last |

## See Also

- [RAG](rag.md) — Retrieving context to include in prompts
- [Multi-Agent Orchestration](multi-agent.md) — When one prompt isn't enough
- [Context Composition In Practice](../in-practice/context-composition.md) — How Amprealize automates prompting
