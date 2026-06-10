---
title: 'Evaluation: Multi-shot'
type: evaluation-summary
last_updated: '2026-05-14'
sources:
- paper_79571924cbac
confidence: medium
tags:
- defer
---

# Multi-shot

**Verdict**: DEFER | **Score**: 6.05/10

## Full evaluation report

## Paper

- **Paper ID:** `paper_79571924cbac`
- **Source:** https://arxiv.org/html/2605.13511v1
- **Words:** 12,285
- **Extraction confidence:** 100%

### Abstract

(no abstract)

## Comprehension

**Core idea:** Many-shot chain-of-thought in-context learning (CoT-ICL) for reasoning tasks behaves fundamentally differently from standard many-shot ICL on non-reasoning tasks. While non-reasoning tasks show stable performance improvements with more demonstrations, reasoning tasks exhibit unstable scaling for non-reasoning LLMs but positive scaling for reasoning-oriented LLMs. The authors reframe many-shot CoT-ICL as in-context test-time learning rather than pattern matching, proposing that effective demonstrations must be both understandable to the model and smoothly sequenced.

**Problem addressed:** Current understanding of many-shot ICL derives from non-reasoning tasks, where adding more demonstrations reliably improves performance and order sensitivity diminishes. However, it's unknown whether these principles extend to many-shot CoT-ICL for reasoning tasks, creating a gap in understanding how to effectively deploy reasoning-capable LLMs with long contexts.

**Proposed solution:** The authors propose viewing many-shot CoT-ICL as in-context test-time learning guided by two principles: (1) demonstrations should align with the model's ability to understand them, and (2) demonstrations should be ordered to create smooth conceptual transitions. They introduce Curvilinear Demonstration Selection (CDS), a method that orders demonstrations by minimizing curvature in embedding space to create a smooth learning trajectory.

- **Novelty:** 8.0/10 — The paper provides the first systematic study of many-shot CoT-ICL scaling behavior and introduces a novel theoretical framework viewing it as in-context test-time learning, backed by extensive empirical evidence and a practical ordering method.
- **Comprehension confidence:** 95%

### Key contributions

- Empirical discovery that many-shot CoT-ICL exhibits setting-dependent scaling: unstable for non-reasoning LLMs on reasoning tasks but positive for reasoning-oriented LLMs
- Finding that similarity-based retrieval fails for reasoning tasks because question similarity doesn't ensure procedural compatibility
- Identification of an order-scaling effect where performance variance increases with more CoT demonstrations
- Reframing of many-shot CoT-ICL as in-context test-time learning with two guiding principles: ease of understanding and smoothness of information flow
- Introduction of CDS method that achieves up to 5.42 percentage-point gains on geometry tasks by optimizing demonstration ordering

### Claimed results

- **Accuracy improvement on geometry:** 5.42 percentage points (_Using CDS with 64 demonstrations_)
- **Correlation between ordering smoothness and accuracy:** r = -0.547 (_Negative correlation indicating smoother orderings yield better performance_)
- **Performance gain from self-generated CoT:** Consistent outperformance over dataset-provided CoTs (_When prompting weaker models with their own generated demonstrations_)
- **Thinking token reduction for Qwen3-14B:** 24.02% reduction (_When increasing demonstrations from 16 to 128 on geometry_)

## Evaluation (Amprealize fit)

| Dimension | Score | Notes |
|-----------|------:|-------|
| Relevance | 5.0 |  |
| Feasibility | 8.0 |  |
| Novelty | 5.0 |  |
| ROI | 5.0 |  |
| Safety | 8.0 |  |

**Overall score:** 6.05/10

### Honest assessment

This paper is solid academic work on optimizing demonstration ordering for reasoning tasks, but it's solving a problem Amprealize already addressed differently and better. The platform's BCI system with structured behaviors, role-based execution, and governance workflows is fundamentally incompatible with the paper's approach of ordering raw CoT demonstrations. Adopting this would be like replacing a well-organized library catalog system with a 'smooth trajectory through random books' approach.

## Recommendation

- **Verdict:** **DEFER**
- **Priority:** P4

### Rationale

This paper offers marginal insights about many-shot prompting that don't justify implementation effort. The core finding—that reasoning models benefit from many examples while non-reasoning models don't—is already well-understood by practitioners. Amprealize's existing behavior system with structured prompts and role-based execution already captures the benefits without needing many-shot demonstrations.

### Executive summary

This paper repackages known limitations of in-context learning with academic framing but no actionable improvements. The 'discovery' that GPT-4 handles many-shot reasoning better than GPT-3.5 is unsurprising. For Amprealize, implementing many-shot prompting would conflict with your existing behavior versioning system and create maintenance nightmares without measurable gains. Your current approach of curated, versioned behaviors is superior to dumping 50+ examples into prompts.
