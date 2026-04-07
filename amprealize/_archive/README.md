# Archive Directory

This directory contains deprecated service implementations that have been superseded
by PostgreSQL-backed versions.

## Archived Files

| File | Replacement | Notes |
|------|-------------|-------|
| `behavior_service_sqlite_backup.py` | `behavior_service.py` | In-memory service, PostgreSQL via service factory |
| `workflow_service_sqlite_backup.py` | `workflow_service.py` | In-memory service, PostgreSQL via service factory |
| `agent_workspace_manager.py` | `amprealize.workspace_agent` | Extracted to standalone `workspace-agent` gRPC service |

## Archived Packages

| Package | Location | Replacement | Notes |
|---------|----------|-------------|-------|
| `workspace-agent` | `packages/_archive/workspace-agent/` | `breakeramp` | gRPC removed; `amprealize/workspace_agent/` shim now wraps AmpOrchestrator |

## Why Archived?

These SQLite-backed implementations were superseded by a two-tier architecture:
1. **In-memory services**: Used for testing and simple deployments
2. **PostgreSQL services**: Used for production with `*_PG_DSN` environment variables

The PostgreSQL versions provide:
- Better concurrent access
- JSONB for flexible metadata storage
- Proper foreign key constraints
- Integration with the unified migration system (`amprealize migrate schema`)

## Can These Be Deleted?

These files are kept for reference but can be safely deleted. They are not imported
anywhere in the codebase.

---
_Archived: 2025-12-02_
