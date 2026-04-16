---
title: "Context Composition in Amprealize"
type: in-practice
difficulty: intermediate
prerequisites:
  - concepts/prompt-engineering.md
  - concepts/rag.md
  - in-practice/bci-in-amprealize.md
tags:
  - amprealize
  - prompting
  - context
last_updated: "2026-04-09"
sources:
  - "amprealize/context_composer.py"
  - "amprealize/context_resolver.py"
amprealize_relevance: "The ContextComposer is Amprealize's automated prompt engineering — it assembles system prompts, behaviors, knowledge packs, and user context into optimized LLM inputs."
visibility: internal
---

# Context Composition in Amprealize

## What It Is

ContextComposer is the module that builds the final prompt sent to the LLM. It's essentially an automated prompt engineer that combines multiple context sources while respecting token budgets.

## How It Maps to Concepts

| AI/ML Concept | Amprealize Implementation |
|--------------|--------------------------|
| [Prompt Engineering](../concepts/prompt-engineering.md) | `context_composer.py` applies role setting, few-shot examples, format specs automatically |
| [Tokenization](../concepts/tokenization.md) | Token counting for budget management — ensures prompts fit context windows |
| [RAG](../concepts/rag.md) | Retrieved behaviors and knowledge packs are injected into the composed prompt |

## Context Assembly Order

```
1. System Instructions (role, rules, constraints)
2. Retrieved Behaviors (from BCI)
3. Knowledge Pack Overlays (domain-specific context)
4. Conversation History (trimmed to fit budget)
5. User Message
```

Each layer has a token budget. If the total exceeds the model's context window, lower-priority layers get trimmed first (conversation history → knowledge packs → behaviors).

## Key Files

- `amprealize/context_composer.py` — Orchestrates assembly
- `amprealize/context_resolver.py` — Resolves references and dependencies
- `amprealize/context.py` — Context data structures

## See Also

- [BCI In Practice](bci-in-amprealize.md) — How behaviors get retrieved before composition
- [Agent Orchestration In Practice](agent-orchestration.md) — What happens after the prompt is composed
