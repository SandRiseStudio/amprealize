---
title: "BCI in Amprealize"
type: in-practice
difficulty: intermediate
prerequisites:
  - concepts/rag.md
  - concepts/embeddings.md
  - technologies/faiss.md
tags:
  - amprealize
  - bci
  - retrieval
last_updated: "2026-05-05"
sources:
  - "amprealize/bci_service.py"
  - "amprealize/behavior_retriever.py"
  - "amprealize/nvidia_nim_rerank.py"
amprealize_relevance: "Direct implementation walkthrough of BCI (Behavior-Conditioned Inference) — the core RAG system powering Amprealize."
visibility: internal
---

# BCI (Behavior-Conditioned Inference) in Amprealize

## What It Is

BCI is Amprealize's implementation of RAG for procedural knowledge. Instead of retrieving documents, it retrieves **behaviors** — proven step-by-step strategies that condition the agent's execution.

## How It Maps to Concepts

| AI/ML Concept | Amprealize Implementation |
|--------------|--------------------------|
| [Embeddings](../concepts/embeddings.md) | `behavior_retriever.py` embeds behavior descriptions via sentence-transformers |
| [FAISS](../technologies/faiss.md) | In-process FAISS index stores behavior vectors for fast similarity search |
| [RAG](../concepts/rag.md) | Query → retrieve top-k behaviors → inject into prompt → generate |
| [Hybrid Retrieval](../concepts/hybrid-retrieval.md) | `behavior_retriever.py` merges FAISS hits with keyword search; `advanced_retrieval_service.py` adds optional heuristics for other flows |

## Optional NVIDIA rerank (BCI)

When **`feature.nvidia_bci_rerank`** is enabled (default from env `AMPREALIZE_NVIDIA_BCI_RERANK`) **and** `NVIDIA_API_KEY` or `NVIDIA_NIM_API_KEY` is set, `behavior_retriever.py` oversamples candidates, calls the NeMo **rerank** NIM at `https://ai.api.nvidia.com/v1` (`nvidia_nim_rerank.py`), re-sorts by model logits, then truncates to `top_k` before pack/surface/phase boosts. Task and behavior text are sent to NVIDIA — use only where policy allows. On API errors, ordering falls back to the pre-rerank list. Redis cache keys include a `rerank_sig` so toggling the flag or model does not reuse stale rankings.

## The Flow

```
Agent receives task
    ↓
behaviors.getForTask(task_description, role)
    ↓
[1] Embed task description → query vector
    ↓
[2] FAISS search → top-k behavior candidates
    ↓
[3] Filter by role (Student/Teacher/Strategist)
    ↓
[4] Score and rank by relevance
    ↓
[5] Return behavior set → injected into agent context
    ↓
Agent executes with behavior conditioning
```

## Key Files

- `amprealize/bci_service.py` — Core BCI orchestration
- `amprealize/behavior_retriever.py` — Embedding + FAISS retrieval (+ optional NVIDIA rerank)
- `amprealize/nvidia_nim_rerank.py` — HTTP client for NeMo rerank NIM
- `amprealize/advanced_retrieval_service.py` — Hybrid retrieval with re-ranking
- `amprealize/context_composer.py` — Assembles behaviors into prompts

## Why BCI Over Fine-Tuning

| Approach | Pros | Cons |
|----------|------|------|
| BCI (RAG) | Instant updates, no training cost, auditable | Depends on retrieval quality |
| Fine-tuning | Baked into model weights | Expensive, slow to update, opaque |

Amprealize chose BCI because behaviors change frequently (new patterns discovered weekly) and auditability matters (every behavior citation is traceable).

## See Also

- [Context Composition In Practice](context-composition.md)
- [Agent Orchestration In Practice](agent-orchestration.md)
