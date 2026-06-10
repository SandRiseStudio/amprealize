---
title: 'Evaluation: JSON LLM alternative'
type: evaluation-summary
last_updated: '2026-05-14'
sources:
- paper_9013c247ec18
confidence: medium
tags:
- defer
---

# JSON LLM alternative

**Verdict**: DEFER | **Score**: 5.3/10

## Full evaluation report

## Paper

- **Paper ID:** `paper_9013c247ec18`
- **Source:** https://www.kdnuggets.com/stop-wasting-tokens-a-smarter-alternative-to-json-for-llm-pipelines
- **Words:** 1,585
- **Extraction confidence:** 100%

### Abstract

(no abstract)

## Comprehension

**Core idea:** TOON (Token-Oriented Object Notation) is a serialization format designed to reduce token usage when feeding structured data into LLMs by eliminating JSON's repetitive syntax like braces, quotes, and repeated field names. It achieves this by declaring field structure once and then listing values in a compact tabular format, making it particularly useful for uniform arrays of objects in LLM pipelines.

**Problem addressed:** JSON wastes tokens in LLM pipelines by repeating structural elements (field names, braces, quotes, commas) for every object in arrays, creating unnecessary token overhead that increases costs without adding value for the model

**Proposed solution:** Use TOON format for LLM input which declares field names once then streams row values in tabular form, while keeping JSON for application logic, APIs, and model outputs - essentially converting JSON to TOON only at the point of LLM input

- **Novelty:** 4.0/10 — TOON represents an incremental optimization for a specific use case (reducing LLM input tokens) rather than a fundamental breakthrough, though it addresses a real cost concern in production LLM pipelines.
- **Comprehension confidence:** 95%

### Key contributions

- Introduces TOON as a lossless, compact representation of JSON specifically optimized for LLM input
- Provides practical implementation guidance with CLI tools and conversion examples
- Establishes clear use case boundaries - TOON for repeated structured records, JSON for irregular/nested data
- Advocates for empirical benchmarking rather than blanket adoption

### Claimed results

- **token_reduction:** Significant reduction in token count for arrays of uniform objects (_Most effective with repeated structured records like support tickets, catalog rows, or CRM entries_)

## Evaluation (Amprealize fit)

| Dimension | Score | Notes |
|-----------|------:|-------|
| Relevance | 5.0 |  |
| Feasibility | 5.0 |  |
| Novelty | 5.0 |  |
| ROI | 5.0 |  |
| Safety | 8.0 |  |

**Overall score:** 5.30/10

### Honest assessment

TOON is a clever but narrow optimization for uniform JSON arrays that achieves 20-40% token reduction in its sweet spot. However, it's solving a problem Amprealize doesn't have - our behaviors, MCP tools, and telemetry are heterogeneous nested structures where TOON admits it provides no benefit. The engineering effort to support a new serialization format across our stack would be significant, and we'd be adopting a format with zero ecosystem support when mature alternatives like MessagePack already exist.

### Potential benefits

- Could reduce tokens for hypothetical future bulk data APIs if we designed them as uniform arrays
- Demonstrates thinking about LLM-specific optimizations

### Concerns

- Author acknowledges TOON doesn't help with nested/irregular data, which describes most of Amprealize's structures
- No ecosystem support - we'd be maintaining custom parsers forever
- Breaking change for all IDE integrations and MCP tools
- Solving a non-problem while creating real maintenance burden

## Recommendation

- **Verdict:** **DEFER**
- **Priority:** P4

### Rationale

TOON solves a non-problem for Amprealize while creating significant maintenance burden. Our MCP tools, API contracts, and integrations all require JSON compatibility. The author admits TOON fails for nested/irregular data, which describes 95% of our structures (work items, behaviors, telemetry). Breaking VS Code Copilot Chat and Claude Desktop compatibility for marginal token savings on uniform arrays we don't use is engineering malpractice.

### Executive summary

TOON is a custom serialization format that saves tokens on uniform arrays by eliminating JSON syntax. For Amprealize, this is solving the wrong problem. Our data is deeply nested (behaviors with configs, work items with metadata, telemetry with context) where TOON provides zero benefit. Worse, adopting it would break our entire MCP ecosystem (220 tools), VS Code integrations, and OpenAPI contracts. The honest assessment: we'd spend months building custom parsers to save tokens on data structures we don't have.
