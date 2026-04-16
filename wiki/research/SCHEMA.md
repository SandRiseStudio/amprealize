# Research Wiki Schema

> Governance document for the Research Wiki. Defines conventions, frontmatter spec, operations, and lint rules.

## Frontmatter Spec

Every Research Wiki page (except `index.md`, `log.md`, and this file) must have YAML frontmatter:

```yaml
---
title: "Page Title"
type: entity | concept | evaluation-summary | synthesis | contradiction
sources:
  - "arxiv:2401.12345"
  - "https://example.com/paper"
  - "research.reports:<report_id>"
last_updated: 2026-04-09
confidence: high | medium | low
tags:
  - retrieval
  - embeddings
---
```

### Field Definitions

| Field | Required | Description |
|-------|----------|-------------|
| `title` | Yes | Human-readable page title |
| `type` | Yes | One of: `entity`, `concept`, `evaluation-summary`, `synthesis`, `contradiction` |
| `sources` | Yes | List of source references (arxiv IDs, URLs, report IDs) |
| `last_updated` | Yes | ISO date of last content update |
| `confidence` | Yes | `high` (multiple corroborating sources), `medium` (single source or recent), `low` (uncertain or contested) |
| `tags` | No | Free-form tags for cross-referencing |

## Page Types

### Entity Pages (`entities/`)
One page per tool, framework, model, or lab/organization.
- File: `wiki/research/entities/<slug>.md` (e.g., `faiss.md`, `anthropic-claude.md`)
- Must include: what it is, key capabilities, limitations, evaluation history (linked to evaluation summaries)
- Updated when: a new evaluation mentions this entity

### Concept Pages (`concepts/`)
One page per technique, pattern, or architectural approach.
- File: `wiki/research/concepts/<slug>.md` (e.g., `hybrid-retrieval.md`, `behavior-extraction.md`)
- Must include: definition, how it works, where it's used, related concepts (linked)
- Updated when: a new evaluation discusses this concept

### Evaluation Summaries (`evaluations/`)
Compiled from `research.reports` table entries.
- File: `wiki/research/evaluations/<slug>.md` (e.g., `2026-04-karpathy-llm-wiki.md`)
- Must include: paper/source title, verdict, score, key findings, entities mentioned (linked), concepts discussed (linked)
- Created during: ingest after `research.evaluate` completion

### Synthesis Pages (`synthesis/`)
Cross-cutting analysis spanning multiple evaluations.
- File: `wiki/research/synthesis/<slug>.md` (e.g., `rag-vs-compiled-knowledge.md`)
- Must include: thesis, evidence from multiple evaluations (linked), open questions
- Created when: 3+ evaluations touch the same topic area

### Contradiction Pages (`contradictions/`)
Where evaluations disagree or newer findings supersede older ones.
- File: `wiki/research/contradictions/<slug>.md`
- Must include: the conflicting claims, source references for each side, resolution status
- Created when: ingest detects conflicting claims against existing pages

## Cross-Referencing Rules

- Use standard markdown links: `[FAISS](../entities/faiss.md)`
- All links MUST be resolved against existing pages at write time — never link to a page that doesn't exist
- When an entity/concept is mentioned but has no page yet, create the page first, then link
- Relative paths from the page's location (e.g., from `entities/` to `concepts/` use `../concepts/`)
- Cross-wiki links to AI Learning Wiki use: `[embeddings](../../ai-learning/concepts/embeddings.md)`

## Ingest Workflow

Triggered after every `research.evaluate` completion (automatic, with opt-out flag):

1. Read the evaluation report from `research.reports`
2. Extract entities (tools, frameworks, models, labs) and concepts (techniques, patterns)
3. For each entity:
   - If page exists in `entities/`: update with new findings, bump `last_updated`
   - If page doesn't exist: create new entity page
4. For each concept:
   - If page exists in `concepts/`: update with new findings, bump `last_updated`
   - If page doesn't exist: create new concept page
5. Create evaluation summary page in `evaluations/`
6. Check for contradictions against existing pages
7. Update `index.md` — add new entries, update summaries
8. Append to `log.md` — timestamp, operation type, pages affected
9. Feed novel concepts to AI Learning Wiki (automatic cross-wiki)

## Lint Rules

Run via `research_wiki.lint` MCP tool. Checks for:

| Rule | Severity | Description |
|------|----------|-------------|
| `orphan-page` | warning | Page exists but no other page links to it and it's not in index.md |
| `stale-claim` | warning | Page hasn't been updated in >90 days and covers a fast-moving topic |
| `missing-entity` | error | An entity is mentioned in text but has no entity page |
| `broken-link` | error | A markdown link points to a non-existent page |
| `missing-frontmatter` | error | Page lacks required YAML frontmatter fields |
| `contradiction-unresolved` | warning | A contradiction page has no resolution status |
| `empty-section` | info | A page has a section header with no content |

## Merge Rules

When two sources discuss the same entity or concept:

1. **Don't duplicate** — update the existing page, don't create a second one
2. **Append, don't overwrite** — add new findings to existing sections
3. **Track provenance** — every claim should cite its source in the `sources` frontmatter
4. **Flag disagreements** — if new findings conflict with existing content, create a contradiction page
5. **Bump confidence** — if multiple sources agree, upgrade confidence to `high`
