# AI/ML Learning Wiki Schema

> Governance document for the AI/ML Learning Wiki. Defines conventions, frontmatter spec, writing style, operations, and lint rules.

## Frontmatter Spec

Every AI Learning Wiki page (except `index.md`, `log.md`, `overview.md`, and this file) must have YAML frontmatter:

```yaml
---
title: "Page Title"
type: concept | technology | pattern | glossary | in-practice | learning-path
difficulty: beginner | intermediate | advanced
prerequisites:
  - "[Embeddings](../concepts/embeddings.md)"
  - "[Tokens](../glossary/tokens.md)"
tags:
  - retrieval
  - embeddings
last_updated: 2026-04-09
sources:
  - "Vaswani et al., 2017 — 'Attention Is All You Need'"
  - "https://jalammar.github.io/illustrated-transformer/"
amprealize_relevance: "Used in behavior retrieval via FAISS index"
visibility: public | internal
---
```

### Field Definitions

| Field | Required | Description |
|-------|----------|-------------|
| `title` | Yes | Human-readable page title |
| `type` | Yes | One of: `concept`, `technology`, `pattern`, `glossary`, `in-practice`, `learning-path` |
| `difficulty` | Yes | `beginner` (intuition + analogies), `intermediate` (technical detail), `advanced` (implementation + math) |
| `prerequisites` | No | Markdown links to pages the reader should understand first |
| `tags` | No | Free-form tags for discovery |
| `last_updated` | Yes | ISO date of last content update |
| `sources` | Yes | Citations: papers, articles, tutorials, conversations that informed this page |
| `amprealize_relevance` | No | One-line note on how this concept relates to the Amprealize codebase |
| `visibility` | No | `public` (default, shareable) or `internal` (Amprealize-specific, excluded from public exports) |

## Page Types

### Concept Pages (`concepts/`)
Core AI/ML ideas with explanations at the stated difficulty level.
- File: `wiki/ai-learning/concepts/<slug>.md` (e.g., `attention-mechanism.md`, `embeddings.md`)
- Must include: "What is it?", "Why does it matter?", "How does it work?", prerequisites, related concepts
- Updated when: understanding deepens or new context is gained

### Technology Pages (`tech/`)
Specific tools, frameworks, or models.
- File: `wiki/ai-learning/tech/<slug>.md` (e.g., `faiss.md`, `tiktoken.md`)
- Must include: what it does, when to use it, key concepts it implements, Amprealize usage (if any)
- Updated when: new versions ship or usage patterns change

### Pattern Pages (`patterns/`)
Recurring architectural patterns in AI/ML systems.
- File: `wiki/ai-learning/patterns/<slug>.md` (e.g., `rag.md`, `chain-of-thought.md`)
- Must include: the pattern, when to use it, how it works, variations, Amprealize examples
- Updated when: new variations are encountered

### Glossary Pages (`glossary/`)
Quick-reference terminology definitions.
- File: `wiki/ai-learning/glossary/<slug>.md` (e.g., `tokens.md`, `context-window.md`)
- Must include: one-line definition, expanded explanation, example, related terms
- Difficulty: always `beginner`

### In-Practice Pages (`in-practice/`)
Theory-to-practice bridges showing how concepts manifest in Amprealize.
- File: `wiki/ai-learning/in-practice/<slug>.md` (e.g., `how-bci-uses-embeddings.md`)
- Must include: the concept, where it appears in code (with file paths), simplified walkthrough
- `visibility: internal` — excluded from public exports
- Updated when: the relevant Amprealize code changes

### Learning Path Pages (`paths/`)
Ordered sequences of pages forming a curriculum.
- File: `wiki/ai-learning/paths/<slug>.md` (e.g., `llm-fundamentals.md`, `from-rag-to-agents.md`)
- Must include: goal statement, ordered list of pages with brief descriptions, estimated complexity
- No difficulty jumps: beginner → intermediate → advanced must be smooth

## Writing Style

1. **Explain like the reader is smart but new.** Don't assume AI/ML background.
2. **Lead with intuition.** Start with a relatable analogy or "why."
3. **Follow with technical detail.** Once intuition is set, go as deep as the difficulty level allows.
4. **Use analogies.** Especially for beginner-level pages.
5. **Always include "Why does this matter?"** Connect the concept to real-world impact or Amprealize usage.
6. **Cite sources.** Every claim should trace back to a paper, article, or direct experience.
7. **Show, don't just tell.** Include examples, diagrams (mermaid), or code snippets where helpful.

## Cross-Referencing Rules

- Use standard markdown links: `[Embeddings](../concepts/embeddings.md)`
- All links MUST resolve to existing pages — never link to a non-existent page
- Every concept page should link to its prerequisites
- Every "in-practice" page should link to the concept it demonstrates
- Cross-wiki links to Research Wiki: `[FAISS evaluation](../../research/entities/faiss.md)`
- Cross-wiki direction: Research → Learning is **automatic** (new concepts trigger learning page creation). Learning → Research is **manual**.

## Difficulty Progression

- **Beginner**: Intuition, analogies, "what" and "why." No math. No code unless trivial.
- **Intermediate**: Technical detail, "how it works" mechanically. Simple math allowed. Code examples.
- **Advanced**: Implementation details, proofs, math, performance characteristics. Production considerations.

Learning paths must not jump from beginner to advanced without an intermediate step.

## Ingest Workflow

### From Research Evaluations (automatic)

1. After Research Wiki ingest, extract novel concepts not yet in AI Learning Wiki
2. For each novel concept: create a beginner-level concept page with initial explanation
3. If the concept has an Amprealize connection, create a stub in-practice page
4. Update `index.md` and append to `log.md`

### From Development (manual trigger)

1. When a new AI feature is built, create/update the relevant in-practice page
2. Link to the concept page explaining the underlying technique

### From External Sources (manual trigger)

1. Drop an article/tutorial URL → extract key concepts
2. Create/update concept and glossary pages
3. Cite the source in frontmatter

## Lint Rules

Run via `ai_learning_wiki.lint` MCP tool. Checks for:

| Rule | Severity | Description |
|------|----------|-------------|
| `missing-concept-page` | warning | A concept is mentioned but has no concept page |
| `orphan-prerequisite` | warning | A page lists a prerequisite that doesn't exist |
| `difficulty-jump` | warning | A learning path jumps from beginner to advanced with no intermediate |
| `stale-practice` | warning | An in-practice page references code paths that no longer exist |
| `stale-benchmark` | warning | Model/benchmark info is >6 months old |
| `broken-link` | error | A markdown link points to a non-existent page |
| `missing-frontmatter` | error | Page lacks required YAML frontmatter fields |
| `no-why-section` | info | A concept page lacks a "Why does this matter?" section |
| `empty-section` | info | A page has section headers with no content |

## Merge Rules

1. **One page per concept** — don't create duplicates for the same idea
2. **Layer difficulty** — if a concept needs beginner AND advanced coverage, use one page with headed sections
3. **Cite all sources** — update `sources` frontmatter when adding information
4. **Keep Amprealize connections current** — update `amprealize_relevance` when codebase changes
