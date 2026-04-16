---
title: "Maintaining the AI Learning Wiki"
type: howto
last_updated: 2026-04-14
applies_to:
  - dev
  - test
tags:
  - ai-learning-wiki
  - documentation
  - agents
  - mcp
---

# Maintaining the AI Learning Wiki

Use the AI Learning Wiki as part of the definition of done for AI-related work in
Amprealize. If a change teaches the team something new about how the platform
uses AI, the wiki should capture that lesson before the work is considered complete.

## When This Applies

Update the wiki when work changes any of the following:

- how Amprealize uses embeddings, retrieval, prompting, or context composition
- how agent orchestration, tool use, or model behavior is explained
- which AI technologies or patterns are recommended in the platform
- how an AI concept appears in Amprealize code, architecture, or workflows

If none of those changed, say so explicitly in the task summary:

```text
No AI Learning Wiki update required because this change only affected UI chrome
and did not change any AI concept, implementation pattern, or explanation.
```

## Required Workflow

### 1. Search Before Writing

Use the wiki tools before creating a new page:

```text
ai_learning_wiki.query
  query: "embeddings"

wiki.list_pages
  domain: ai-learning
```

This prevents duplicate pages and keeps existing explanations evolving instead of
fragmenting.

### 2. Choose the Right Page Type

| If the change teaches... | Use this page type | Typical path |
|--------------------------|--------------------|--------------|
| A general AI idea | `concept` | `concepts/<slug>.md` |
| A specific tool or model | `technology` | `technologies/<slug>.md` |
| A recurring system approach | `pattern` | `patterns/<slug>.md` |
| A term people keep asking about | `glossary` | `glossary/<slug>.md` |
| How Amprealize uses the idea in code | `in-practice` | `in-practice/<slug>.md` |

Rule of thumb:
- If the page would still make sense outside Amprealize, update a general page.
- If the page explains where the idea appears in Amprealize code, update an
  `in-practice` page.

### 3. Prefer Updating Existing Pages

Use `wiki.read_page` to inspect the current page first. Update instead of creating
new pages when:

- the concept already exists but the explanation is incomplete
- Amprealize now uses the concept in a new place
- prerequisites, sources, or relevance notes are stale

Create a new page only when the concept or usage is genuinely missing.

### 4. Write Through the Wiki Tools

Use MCP wiki tools with the `wiki-contributor` skill:

```text
wiki.create_page
  domain: ai-learning
  page_path: in-practice/<slug>.md
  title: "..."
  page_type: in-practice
  body: |
    ## Concept
    ...

wiki.update_page
  domain: ai-learning
  page_path: concepts/<slug>.md
  body: |
    ...
  append: false
```

For every Amprealize-specific AI capability, the ideal pair is:

1. a general concept or pattern page
2. a matching `in-practice` page that links the idea to real code paths

## What Good Looks Like

An AI learning wiki update is complete when it does all of the following:

- explains the idea clearly enough for a smart teammate who is new to the topic
- includes or refreshes `sources`, `prerequisites`, and `amprealize_relevance`
- links to the relevant concept page if the main update is in `in-practice`
- names the concrete Amprealize files, services, or workflows involved
- passes `ai_learning_wiki.lint`

## Minimum Done Checklist

- [ ] Searched existing AI learning pages first
- [ ] Updated an existing page or created the right new page
- [ ] Added or refreshed an `in-practice` page when the change touched real AI behavior in Amprealize
- [ ] Ran `ai_learning_wiki.lint`
- [ ] Mentioned the wiki impact in the final handoff

## Suggested Review Prompt

Before closing an AI-related task, ask:

> What did this change teach us about AI in Amprealize, and where should that
> lesson live in `wiki/ai-learning/`?

## Related

- [Agent Handbook & Conventions](../reference/agent-handbook.md)
- [Behavior System](../architecture/behavior-system.md)
