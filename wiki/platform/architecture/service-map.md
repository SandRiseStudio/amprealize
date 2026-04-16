---
title: "Service Map"
type: architecture
last_updated: 2026-04-14
applies_to:
  - dev
  - test
  - staging
  - prod
tags:
  - architecture
  - services
  - dependencies
  - data-flow
---

# Service Map

Amprealize is composed of domain services that communicate through a shared service
layer. Every surface (CLI, API, MCP, VS Code, Web Console) calls the same service
instances.

## Request Flow

```
┌─────────────────────────────────────────────────────┐
│                    Surfaces                          │
│  CLI ─┐   Web Console ─┐   VS Code ─┐   MCP ─┐    │
│       └───────┐         └──────┐     └───┐    │    │
└───────────────┼────────────────┼─────────┼────┼────┘
                ▼                ▼         ▼    ▼
         ┌──────────────────────────────────────┐
         │        Nginx Gateway (:8080)         │
         │  TLS · Rate Limiting · Auth · CORS   │
         └──────────────┬───────────────────────┘
                        ▼
         ┌──────────────────────────────────────┐
         │     FastAPI Application (:8000)      │
         │     + MCP Server (stdio/SSE)         │
         └──────────────┬───────────────────────┘
                        ▼
         ┌──────────────────────────────────────┐
         │           Service Layer              │
         └──────────────────────────────────────┘
```

## Core Services

| Service | Module | Storage | Purpose |
|---------|--------|---------|---------|
| **BehaviorService** | `behavior_service.py` | PostgreSQL | Full behavior lifecycle: draft → submit → approve → deprecate |
| **BCIService** | `bci_service.py` | In-memory index + Postgres | Behavior-Conditioned Inference: retrieve, compose prompts, detect patterns |
| **RunService** | `run_service.py` | SQLite | Execution run orchestration: create, progress, complete, cancel |
| **ActionService** | `action_service.py` | In-memory | Action recording and replay |
| **ComplianceService** | `compliance_service.py` | PostgreSQL | Checklists, policies, validation |
| **AuthService** | `agent_auth.py` | PostgreSQL | Device flow, tokens, grants, RBAC |

## Knowledge Pack Services

| Service | Module | Storage | Purpose |
|---------|--------|---------|---------|
| **SourceRegistryService** | `knowledge_pack/source_registry.py` | PostgreSQL | Register and track source files, drift detection |
| **ActivationService** | `knowledge_pack/activation_service.py` | PostgreSQL | Activate/deactivate packs per workspace |
| **KnowledgePackStorage** | `knowledge_pack/storage.py` | Postgres/Neon/SQLite | Persist pack manifests, overlays, artifacts |

## Supporting Services

| Service | Module | Storage | Purpose |
|---------|--------|---------|---------|
| **WikiService** | `wiki_service.py` | Filesystem (git) | 4-domain wiki: research, infra, ai-learning, platform |
| **AgentRegistryService** | `agent_registry_service.py` | PostgreSQL | Agent registration and lifecycle |
| **CollaborationService** | `collaboration_service.py` | PostgreSQL | Shared editing (Enterprise) |
| **RateInfoService** | `api_rate_limiting_service.py` | In-memory | API rate limiting |
| **ContextComposer** | `context_composer.py` | — | Compose rich context for agent prompts |

## Standalone Packages

| Package | Location | Purpose |
|---------|----------|---------|
| **Raze** | `packages/raze/` | Structured logging + telemetry sinks (Timescale, JSONL, in-memory) |
| **BreakerAmp** | `packages/breakeramp/` | Container orchestration (Podman blueprints, plan/apply/destroy) |

Zero core dependencies — they integrate via hooks and optional extras.

## Service Dependencies

```
BehaviorService ←── BCIService (retrieval, prompt composition)
                ←── ComplianceService (behavior validation)
                ←── ContextComposer (behavior context)

RunService ←── ActionService (action recording per run)
           ←── BehaviorService (behavior refs in runs)

AuthService ←── All services (token validation)

KnowledgePackStorage ←── ActivationService (pack bindings)
                     ←── SourceRegistryService (source refs in manifests)

WikiService ←── Independent (filesystem-only)

Raze ←── All services (logging)
```

## Per-Service Schema Isolation

Each service can use its own database schema via dedicated DSN environment variables:

```
AMPREALIZE_AUTH_PG_DSN       → auth tables
AMPREALIZE_BEHAVIOR_PG_DSN   → behavior tables
AMPREALIZE_EXECUTION_PG_DSN  → run/action tables
AMPREALIZE_COMPLIANCE_PG_DSN → compliance tables
DATABASE_URL                 → default fallback
```

The context system (`apply_context_to_environment()`) wires these automatically.
See [Context System](../reference/context-system.md).

## Data Flow: Behavior Lifecycle

```
Agent observes pattern → behaviors.create (draft)
                       → behaviors.submit (review)
                       → behaviors.approve (active)
                       → bci.rebuildIndex
                       → bci.retrieve (available for future tasks)
                       → bci.composePrompt (injected into agent prompt)
```

## Data Flow: Knowledge Pack

```
seed_pack_sources.py → SourceRegistryService.register_source()
                     → SourceExtractor.extract_all() → Fragments
                     → PrimerGenerator → primer_text
                     → PackBuilder.build() → KnowledgePackArtifact
                     → KnowledgePackStorage.save_artifact()
                     → ActivationService.activate_pack()
                     → ContextComposer reads active pack
```
