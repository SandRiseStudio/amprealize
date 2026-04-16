# Skill: Wiki Contributor

**Slug**: `wiki-contributor`
**Version**: 1.0
**Role**: Any agent that needs to read or write wiki pages

## Purpose

Provides conventions, templates, and a quality checklist for contributing to the Amprealize wiki system. Use this skill whenever creating or updating wiki pages to ensure consistency across all three domains.

## Wiki Tools

| Tool | Purpose |
|------|---------|
| `wiki.list_pages` | List pages in a domain with optional type/folder filters |
| `wiki.read_page` | Read a page's frontmatter and body |
| `wiki.create_page` | Create a new page (auto-lints after write) |
| `wiki.update_page` | Append or replace content (auto-lints after write) |
| `wiki.delete_page` | Delete a page (index.md, log.md, SCHEMA.md are protected) |

## Domains

| Domain | Slug | Content Focus |
|--------|------|---------------|
| Research | `research` | Papers, concepts, experiments, benchmarks |
| Infrastructure | `infra` | DevOps, test infra, deployment, troubleshooting |
| AI Learning | `ai-learning` | ML fundamentals, tutorials, learning paths |

## Page Types

| Type | When to Use |
|------|-------------|
| `reference` | Factual lookups — config tables, API specs, parameter lists |
| `howto` | Step-by-step procedures — "How to do X" |
| `architecture` | System design — diagrams, data flow, component relationships |
| `troubleshooting` | Problem/diagnosis/fix — "X is broken, here's why and how to fix it" |
| `practice` | Conventions and best practices — "How we do X and why" |

## Frontmatter Conventions

Every wiki page must start with YAML frontmatter:

```yaml
---
title: "Human-Readable Page Title"
type: reference | howto | architecture | troubleshooting | practice
difficulty: beginner | intermediate | advanced    # optional
tags: [tag1, tag2]                                 # optional
last_updated: "YYYY-MM-DD"                        # auto-set by WikiService
---
```

Rules:
- `title` and `type` are **required**
- `difficulty` is recommended for ai-learning, optional elsewhere
- `tags` should use lowercase, hyphenated terms
- Do not set `last_updated` manually — WikiService manages it

## Templates

### Reference Page

```markdown
---
title: "Component Name Reference"
type: reference
tags: [component, config]
---

## Overview

Brief description of what this reference covers.

## Parameters / Configuration

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `param_a` | string | `""` | What it controls |

## Examples

\`\`\`python
# Usage example
\`\`\`

## See Also

- [Related Page](../related/page.md)
```

### How-To Page

```markdown
---
title: "How to Do X"
type: howto
tags: [topic]
---

## Goal

What the reader will accomplish after following these steps.

## Prerequisites

- Requirement 1
- Requirement 2

## Steps

### 1. First Step

Explanation and commands:

\`\`\`bash
command here
\`\`\`

### 2. Second Step

Explanation.

## Verification

How to confirm it worked.

## Troubleshooting

- **Problem**: Description → **Fix**: Solution
```

### Troubleshooting Page

```markdown
---
title: "Issue Name"
type: troubleshooting
tags: [error, component]
---

## Symptoms

- What the user sees or experiences
- Error messages (exact text)

## Diagnosis

1. Step to identify the root cause
2. Commands to run for diagnostics

## Root Cause

Explanation of why this happens.

## Fix

1. Step-by-step resolution
2. Commands to run

## Prevention

How to avoid this issue in the future.
```

### Architecture Page

```markdown
---
title: "System Name Architecture"
type: architecture
tags: [system, design]
---

## Overview

High-level description of the system.

## Components

### Component A

- **Role**: What it does
- **Location**: Where it runs
- **Dependencies**: What it needs

### Component B

...

## Data Flow

Describe how data moves through the system.

## Design Decisions

| Decision | Rationale | Trade-offs |
|----------|-----------|------------|
| Choice A | Why | What we gave up |

## Diagrams

(Mermaid or ASCII diagrams if useful)
```

### Practice Page

```markdown
---
title: "Practice Name"
type: practice
tags: [convention, topic]
---

## Summary

One-paragraph description of the practice.

## Rules

1. **Rule name** — explanation
2. **Rule name** — explanation

## Examples

### Good

\`\`\`python
# Correct approach
\`\`\`

### Bad

\`\`\`python
# Anti-pattern to avoid
\`\`\`

## Rationale

Why we follow this practice.
```

## Quality Checklist

Before submitting a wiki page, verify:

- [ ] **Frontmatter** — `title` and `type` are present and valid
- [ ] **No duplicates** — ran `wiki.list_pages` to check the page doesn't already exist
- [ ] **Correct domain** — page is in the right wiki domain
- [ ] **Lint clean** — create/update tools auto-lint; address any warnings returned
- [ ] **Links valid** — any cross-references point to existing pages
- [ ] **Actionable** — troubleshooting pages have concrete fix steps, not just descriptions

## Workflow: Creating a New Page

1. **Check for duplicates**: `wiki.list_pages domain=<domain>` — scan titles for overlap
2. **Pick the right type**: Match your content to the page types table above
3. **Use the template**: Copy the appropriate template from this skill
4. **Create**: `wiki.create_page` with all required fields
5. **Review lint output**: Fix any warnings returned in the response
6. **Verify**: `wiki.read_page` to confirm the page looks correct

## Workflow: Updating an Existing Page

1. **Read current content**: `wiki.read_page domain=<domain> page_path=<path>`
2. **Decide on mode**:
   - `body_additions` — append new content (default, preserves existing)
   - `replace_body=true` — overwrite body entirely (use for rewrites)
   - `frontmatter_updates` — update metadata without touching body
3. **Update**: `wiki.update_page` with the chosen parameters
4. **Review lint output**: Fix any warnings
