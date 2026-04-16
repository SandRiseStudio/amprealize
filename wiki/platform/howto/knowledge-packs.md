---
title: "Knowledge Packs"
type: howto
last_updated: 2026-04-14
applies_to:
  - dev
  - test
  - staging
  - prod
tags:
  - knowledge-packs
  - sources
  - primer
  - overlays
  - activation
---

# Knowledge Packs

Knowledge packs bundle curated documentation into compact artifacts that can be
injected into agent prompts. This guide covers the full lifecycle: register sources,
build packs, activate in workspaces.

## Concepts

| Concept | Description |
|---------|-------------|
| **Source** | A registered file or service that provides content (e.g., AGENTS.md, context.py) |
| **Fragment** | Extracted content from a source (DoctrineFragment, BehaviorFragment, PlaybookFragment) |
| **Manifest** | Pack metadata: ID, version, scope, status, constraints, sources list |
| **Primer** | Compressed text (~2000 chars) summarizing the pack's core knowledge |
| **Overlay** | Additional content layers (role-specific, task-specific) applied at runtime |
| **Activation** | Binding a pack to a workspace so agents receive its knowledge |

## Architecture

```
Sources ──→ SourceExtractor.extract_all() ──→ Fragments
                                                 │
                                          PrimerGenerator
                                                 │
                                           primer_text
                                                 │
                              PackBuilder.build() ──→ KnowledgePackArtifact
                                                       ├── manifest
                                                       ├── primer_text
                                                       ├── overlays[]
                                                       └── retrieval_metadata
```

## Pack Composition Model

Amprealize uses a **layered pack architecture**:

- **Core pack**: Built at build time. Contains the full primer covering platform essentials.
- **Role packs** (student, teacher, strategist): Separate packs with role-specific overlays, applied at runtime.
- **Task packs** (feature, incident, data, launch): Separate packs with task-domain overlays, applied at runtime.

Core packs are built standalone. Role and task packs are NOT merged at build time —
they serve as overlays composed at runtime by the activation service.

## Step 1: Register Sources

Sources are files or services that feed content into packs.

```bash
# Via CLI
amprealize pack sources register --type file --ref AGENTS.md --scope canonical

# Via seed script (bulk registration)
python scripts/seed_pack_sources.py
```

Source scopes:
- **canonical**: Core doctrine (AGENTS.md, README.md)
- **operational**: Runtime configs and procedures
- **surface**: Surface-specific docs (CLI help, API specs)
- **runtime**: Dynamic content (wiki pages, generated docs)

Check registered sources:
```bash
amprealize pack sources list
amprealize pack sources drift <source-id>  # Check if source file changed
```

## Step 2: Build a Pack

```bash
# Build core pack
amprealize pack build --pack-id core-v1 --version 1.0.0 --scope project
```

The build process:
1. Resolves all registered sources
2. Extracts fragments using `SourceExtractor`
3. Generates primer text (budget ~2000 chars)
4. Assembles `KnowledgePackArtifact` with manifest + primer + overlays

## Step 3: Activate in Workspace

```bash
# Activate for current workspace
amprealize pack activate --pack-id core-v1 --version 1.0.0

# Check active pack
amprealize pack status

# Deactivate
amprealize pack deactivate
```

Activation binds the pack to a workspace using a stable workspace ID derived from
the filesystem path (SHA-256 hash).

## Storage Backends

Pack storage supports three backends:

| Backend | Use Case | Config |
|---------|----------|--------|
| **Postgres (local)** | Development with local DB | Context system auto-configures |
| **Neon (cloud)** | Shared/CI environments | DSN in context config |
| **SQLite** | OSS / offline use | File path in context config |

The storage backend is selected automatically based on the active context.

## Drift Detection

Sources track content hashes. When a source file changes, drift is detected:

```bash
amprealize pack sources drift <source-id>
```

Returns stored hash vs. current hash. Rebuild the pack when drift is detected.

## MCP Tools

| Tool | Description |
|------|-------------|
| `pack.status` | Get active pack info |
| `pack.activate` | Activate a pack |
| `pack.deactivate` | Deactivate current pack |
| `pack.sources.list` | List registered sources |

## Related

- [Service Map](../architecture/service-map.md) — where pack services fit
- [Behavior System](../architecture/behavior-system.md) — how BCI uses pack content
