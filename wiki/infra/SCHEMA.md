# Infrastructure Wiki Schema

> Governance document for the Infrastructure & Testing Wiki. Defines conventions, frontmatter spec, operations, and lint rules.

## Frontmatter Spec

Every Infra Wiki page (except `index.md`, `log.md`, and this file) must have YAML frontmatter:

```yaml
---
title: "Page Title"
type: reference | howto | architecture | troubleshooting | practice
source_files:
  - "scripts/run_tests.sh"
  - "config/breakeramp/environments.yaml"
source_hash:
  scripts/run_tests.sh: "abc123"
  config/breakeramp/environments.yaml: "def456"
last_updated: 2026-04-09
applies_to:
  - dev
  - test
tags:
  - testing
  - breakeramp
visibility: domain-knowledge | proprietary
---
```

### Field Definitions

| Field | Required | Description |
|-------|----------|-------------|
| `title` | Yes | Human-readable page title |
| `type` | Yes | One of: `reference`, `howto`, `architecture`, `troubleshooting`, `practice` |
| `source_files` | Yes | List of repo-relative file paths this page was compiled from |
| `source_hash` | Yes | Git short hashes of source files at time of last update (for staleness detection) |
| `last_updated` | Yes | ISO date of last content update |
| `applies_to` | Yes | Environments: `dev`, `test`, `staging`, `prod` (one or more) |
| `tags` | No | Free-form tags for cross-referencing |
| `visibility` | No | `domain-knowledge` (shareable, default) or `proprietary` (enterprise-only) |

## Page Types

### Reference Pages (`reference/`)
One page per system, tool, or configuration file.
- File: `wiki/infra/reference/<slug>.md` (e.g., `breakeramp.md`, `run-tests-sh.md`, `pytest-markers.md`)
- Must include: what it is, where the source file lives, key parameters/options, common usage
- Updated when: source file changes (detected via `source_hash`)

### How-To Pages (`howto/`)
Procedural guides for common tasks.
- File: `wiki/infra/howto/<slug>.md` (e.g., `run-tests-locally.md`, `add-new-migration.md`)
- Must include: prerequisites, step-by-step instructions, expected output, common pitfalls
- Updated when: referenced tools or procedures change

### Architecture Pages (`architecture/`)
System design decisions and topology.
- File: `wiki/infra/architecture/<slug>.md` (e.g., `multi-db-topology.md`, `rls-strategy.md`)
- Must include: decision context, design choice, tradeoffs, current state diagram
- Updated when: architecture changes or new components are added

### Troubleshooting Pages (`troubleshooting/`)
Common failure modes and fixes.
- File: `wiki/infra/troubleshooting/<slug>.md` (e.g., `postgres-connection-failures.md`)
- Must include: symptom, root cause, fix steps, prevention
- Updated when: new failure modes are discovered or fixes change

### Practice Pages (`practices/`)
Best practices and domain knowledge.
- File: `wiki/infra/practices/<slug>.md` (e.g., `test-isolation-patterns.md`, `migration-safety.md`)
- Must include: the practice, rationale, examples, anti-patterns
- Updated when: practices evolve or new ones are established

## Cross-Referencing Rules

- Use standard markdown links: `[BreakerAmp](../reference/breakeramp.md)`
- All links MUST resolve to existing pages — never create dangling links
- Relative paths from the page's location
- Cross-wiki links: not typical for infra wiki, but if needed use `../../research/` or `../../ai-learning/`

## Staleness Detection

The infra wiki uses **flag-and-suggest** staleness detection:

1. Each page tracks `source_hash` for every file in `source_files`
2. On `infra_wiki.lint`, compare current git hash of each source file against stored `source_hash`
3. If any source file has changed → flag the page as **potentially stale**
4. Generate a suggested diff showing what may need updating
5. Human or reviewer approves the update

This is intentionally conservative — source files changing doesn't always mean the wiki page is wrong.

## Ingest Workflow

### Initial Bootstrap (one-time)

1. **`scripts/run_tests.sh`** → `reference/run-tests-sh.md` + `howto/run-tests-locally.md` + `howto/run-specific-test-suites.md`
2. **`config/breakeramp/environments.yaml`** + `docs/BREAKERAMP_PRD.md` → `reference/breakeramp.md` + `architecture/multi-db-topology.md` + `howto/provision-test-environment.md`
3. **`pytest.ini`** + test directory → `reference/pytest-markers.md` + `practices/test-isolation-patterns.md`
4. **`migrations/`** → `reference/alembic-migrations.md` + `howto/add-new-migration.md` + `practices/migration-safety.md`
5. **`CLAUDE.md`** + `AGENTS.md` → `practices/mandatory-behaviors.md` + relevant practice pages
6. **`infra/`** → `architecture/container-strategy.md` + `reference/podman-setup.md`

### Incremental Updates (ongoing)

1. Detect modified source files via `git diff` against `source_hash` in frontmatter
2. Re-read modified sources
3. Update affected wiki pages, bump `last_updated` and `source_hash`
4. Update `index.md` and append to `log.md`

## Lint Rules

Run via `infra_wiki.lint` MCP tool. Checks for:

| Rule | Severity | Description |
|------|----------|-------------|
| `stale-source` | warning | Source file hash differs from `source_hash` in frontmatter |
| `new-source-no-page` | warning | New script/config file has no corresponding wiki page |
| `broken-link` | error | A markdown link points to a non-existent page |
| `missing-frontmatter` | error | Page lacks required YAML frontmatter fields |
| `missing-source-hash` | error | Page has `source_files` but no `source_hash` |
| `orphan-page` | warning | Page not linked from any other page or index |
| `empty-section` | info | A page has section headers with no content |
| `contradiction` | warning | Wiki page content contradicts current source file |

## Merge Rules

When multiple source files contribute to the same wiki page:

1. **Cite every source** — list all contributing files in `source_files`
2. **Track all hashes** — `source_hash` must cover every source file
3. **Attribute claims** — note which source file each piece of information came from
4. **Resolve conflicts** — if sources contradict, prefer the more specific source and note the discrepancy
