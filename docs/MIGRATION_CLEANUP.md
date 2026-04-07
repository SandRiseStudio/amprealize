# Migration Cleanup Summary (December 2025)

## Overview

As of December 16, 2025, Amprealize has fully migrated from SQL-based database migrations to **pure-Python Alembic migrations**. This document explains what was changed and where legacy files were archived.

## Current Migration System

### Active Migration File
- **Location**: `migrations/versions/20251216_schema_baseline.py`
- **Revision ID**: `schema_baseline`
- **Previous Revision**: `None` (this is the baseline)
- **Contents**: ~1100 lines of pure Python defining:
  - 7 database schemas: `auth`, `board`, `behavior`, `execution`, `workflow`, `consent`, `audit`
  - 42+ tables including all production tables
  - All indexes, constraints, and ENUMs

### How to Create New Migrations
```bash
# Create a new migration
alembic revision -m "add_new_feature"

# Edit the generated file:
# - Set: down_revision = 'schema_baseline'
# - Use: op.create_table(), op.add_column(), etc.
# - Do NOT use: op.execute() with raw SQL
# - Do NOT reference: schema/migrations/*.sql

# Test with BreakerAmp
breakeramp apply --blueprint core-data-plane

# Apply in production
alembic upgrade head
```

## Archived Files

### SQL Migration Scripts → `schema/migrations.archive/`
All legacy `.sql` migration files (001-031) have been archived. These were the original migration scripts that created the database schema.

### SQL Utilities → `scripts.archive/`
The following scripts were archived because they depended on loading SQL files:

| Archived Script | Original Purpose |
|----------------|------------------|
| `run_postgres_action_migration.py` | Applied `schema/migrations/003_create_action_service.sql` |
| `run_postgres_agent_orchestrator_migration.py` | Applied `schema/migrations/011_create_agent_orchestrator.sql` |
| `run_postgres_auth_migration.py` | Applied auth service SQL migrations |
| `run_postgres_behavior_migration.py` | Applied `schema/migrations/002_create_behavior_service.sql` |
| `run_postgres_compliance_migration.py` | Applied compliance service SQL migrations |
| `run_postgres_metrics_migration.py` | Applied metrics/TimescaleDB migrations |
| `run_postgres_orchestrator_migration.py` | Applied orchestrator SQL migrations |
| `run_postgres_run_migration.py` | Applied run service SQL migrations |
| `run_postgres_telemetry_migration.py` | Applied telemetry warehouse SQL |
| `run_postgres_trace_migration.py` | Applied trace analysis SQL migrations |
| `run_postgres_workflow_migration.py` | Applied workflow service SQL migrations |
| `_postgres_migration_utils.py` | Shared utilities for SQL script execution |
| `sql_utils.py` | Alembic helpers for loading SQL files |
| `migrate_action_sqlite_to_postgres.py` | One-time data migration from SQLite |
| `migrate_behavior_sqlite_to_postgres.py` | One-time data migration from SQLite |
| `migrate_compliance_to_postgres.py` | One-time data migration |
| `migrate_run_sqlite_to_postgres.py` | One-time data migration from SQLite |
| `migrate_telemetry_duckdb_to_postgres.py` | One-time data migration from DuckDB |
| `migrate_workflow_sqlite_to_postgres.py` | One-time data migration from SQLite |
| `run_postgres_migration_rehearsal.py` | Migration dry-run rehearsal tool |
| `generate_postgres_migration_report.py` | Migration readiness report generator |

### Test Archives → `tests.archive/`
The following test files were archived because they tested archived scripts:

| Archived Test | Reason |
|--------------|--------|
| `test_postgres_migration_utils.py` | Tests for archived `_postgres_migration_utils.py` |

### Alembic Version Archives → `migrations/versions.archive/`
Old Alembic migrations that depended on SQL loading were archived:

| Archived Version | Reason |
|-----------------|--------|
| `20251208_0001_baseline_from_sql_migrations.py` | Used `execute_sql_filenames()` |
| `20251211_0006_legacy_sql_026_031.py` | Loaded SQL files 026-031 |
| `native_0001` through `native_0007` | Various dependencies on SQL loading |
| Merge migrations | Related to SQL-dependent versions |

## Why This Was Done

1. **Consistency**: Pure-Python Alembic migrations are easier to review, test, and version control
2. **Portability**: No external SQL file dependencies—everything is in the migration file
3. **Reliability**: Alembic handles revision tracking, rollback, and upgrade paths
4. **BreakerAmp Integration**: Clean integration with `core-data-plane` blueprint

## Schema Overview

The baseline migration creates these schemas and their primary tables:

### `auth` Schema
- `users`, `organizations`, `sessions`, `api_keys`, `federated_identities`
- `mfa_devices`, `org_memberships`, `projects`

### `board` Schema
- `boards`, `columns`, `work_items`, `sprints`
- Collaboration tables: `collaboration_workspaces`, `workspace_members`, `collaboration_documents`, `document_versions`, `active_cursors`, `pending_edits`, `collaboration_events`

### `behavior` Schema
- `behaviors`, `behavior_versions`, `behavior_embeddings`, `behavior_executions`
- Reflection tables: `reflection_patterns`, `behavior_candidates`, `reflection_sessions`, `pattern_observations`

### `execution` Schema
- `runs`, `actions`, `run_steps`, `replays`, `agent_personas`, `agent_assignments`

### `workflow` Schema
- `workflow_templates`, `workflow_runs`, `workflow_step_runs`, `task_cycles`

### `consent` Schema
- `consent_scopes`, `consents`

### `audit` Schema
- Audit logging tables

## Troubleshooting

### "Migration not found" errors
If you see errors about missing SQL files, you may be running old code. Ensure:
1. You've pulled the latest changes
2. Docker/Podman images are rebuilt (`podman rmi amprealize-core`)
3. The `.dockerignore` excludes archive folders

### "Invalid down_revision" errors
New migrations must have `down_revision = 'schema_baseline'`. Do not reference archived revision IDs.

### Need to understand old migrations?
The archived files are preserved in `schema/migrations.archive/` and `scripts.archive/` for historical reference. Do not restore or re-use them.

---

_Last updated: 2025-12-16_
