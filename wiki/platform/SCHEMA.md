# Platform Wiki Schema

> Governance document for the Platform Wiki. Defines conventions, frontmatter spec, operations, and lint rules.

## Frontmatter Spec

Every Platform Wiki page (except `index.md`, `log.md`, and this file) must have YAML frontmatter:

```yaml
---
title: "Page Title"
type: reference | howto | architecture
last_updated: 2026-04-14
applies_to:
  - dev
  - test
  - staging
  - prod
tags:
  - context-system
  - getting-started
---
```

### Field Definitions

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `title` | Yes | string | Human-readable page title |
| `type` | Yes | enum | One of: `reference`, `howto`, `architecture` |
| `last_updated` | Yes | date | ISO date of last modification |
| `applies_to` | Yes | list | Environments: `dev`, `test`, `staging`, `prod` |
| `tags` | Yes | list | Topic tags for categorization and search |

### Notes

- Unlike infra wiki, platform pages do **not** require `source_files` or `source_hash` — most platform pages are original content, not derived from specific source files.
- Tags should be lowercase, hyphenated (e.g., `context-system`, `mcp-tools`).
- Page types:
  - **reference**: What something is (definitions, catalogs, matrices)
  - **howto**: Step-by-step procedures (getting started, setup, workflows)
  - **architecture**: Why it's shaped this way (design decisions, service maps)

## Operations

| MCP Tool | Description |
|----------|-------------|
| `platform_wiki.ingest` | Create or update a platform wiki page |
| `platform_wiki.query` | Search platform wiki pages |
| `platform_wiki.lint` | Run lint checks on all platform wiki pages |
| `platform_wiki.status` | Get page counts and last update timestamp |

## Lint Rules

1. **missing-frontmatter**: All required fields must be present
2. **broken-links**: Internal links must resolve to existing files
3. **type-mismatch**: Page must be in correct directory for its type
