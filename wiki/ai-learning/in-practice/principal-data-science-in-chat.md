---
title: "Principal data science in Amprealize chat"
type: in-practice
difficulty: intermediate
prerequisites:
  - "[BCI in Amprealize](bci-in-amprealize.md)"
  - "[LLM Routing in Amprealize](llm-routing-in-amprealize.md)"
tags:
  - data-science
  - chat
  - behaviors
last_updated: 2026-05-05
sources:
  - "Amprealize AGENTS.md — behavior_principal_data_science_workflow"
  - "https://github.com/youssefHosni/Data-Science-Interview-Questions-Answers — external topic taxonomy for study (not copied into product)"
amprealize_relevance: "Chat appends PRINCIPAL_DS_SYSTEM_SUFFIX when intent or metadata indicates data-heavy work; playbook AGENT_DATA_SCIENCE.md defines the practitioner loop."
visibility: internal
---

# Principal data science in Amprealize chat

## What this page covers

How Amprealize nudges chat and agents toward **principal-level data science** discipline: clear metrics, reproducible queries, honest limitations, and stakeholder-safe narratives—without shipping third-party Q&A text as product truth.

## Where it shows up in code

| Mechanism | Location |
| --- | --- |
| System prompt suffix | [`amprealize/services/conversation_reply_service.py`](../../../amprealize/services/conversation_reply_service.py) — `PRINCIPAL_DS_SYSTEM_SUFFIX`, `_should_inject_principal_ds_guidance` |
| Practitioner + review playbook | [`amprealize/agents/playbooks/AGENT_DATA_SCIENCE.md`](../../../amprealize/agents/playbooks/AGENT_DATA_SCIENCE.md) |
| BCI behavior | `behavior_principal_data_science_workflow` in **AGENTS.md** (repo root and `amprealize/AGENTS.md`) |
| Default orchestrator persona | [`amprealize/agent_orchestrator_service.py`](../../../amprealize/agent_orchestrator_service.py) — persona `data_science` |

## External taxonomy (attribution only)

Public interview-Q&A collections (for example [Data-Science-Interview-Questions-Answers](https://github.com/youssefHosni/Data-Science-Interview-Questions-Answers)) are useful as a **topic checklist** (ML, statistics, SQL, probability, etc.) when ensuring Amprealize’s own behaviors and playbook cover common lanes. They are **not** ingested verbatim into prompts or packs unless license and attribution requirements are satisfied separately.

## Related

- [BCI in Amprealize](bci-in-amprealize.md)
- [Agent Orchestration in Amprealize](agent-orchestration.md)
