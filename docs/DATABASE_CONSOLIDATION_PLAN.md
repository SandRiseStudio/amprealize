# Database Consolidation Plan: Modular Monolith + Single Database

> **Status**: ✅ Complete
> **Created**: December 16, 2025
> **Completed**: December 17, 2025
> **Purpose**: Canonical implementation plan for consolidating Amprealize's 10+ separate PostgreSQL databases into a single database with PostgreSQL schemas, using Alembic-only migrations.

---

## 🎯 Executive Summary

Amprealize currently uses 10+ separate PostgreSQL databases (auth-db, board-db, behavior-db, etc.), which creates operational complexity and prevents cross-domain queries/transactions. This plan consolidates to:

1. **One main PostgreSQL database** (`amprealize`) with domain schemas (auth, board, behavior, execution, workflow, consent, audit)
2. **One separate TimescaleDB database** (`telemetry`) for time-series data with hypertables
3. **Alembic-only migrations** - no legacy SQL files in execution paths

---

## 🏗️ Target Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     amprealize-api (Single Process)            │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │  Auth    │ │  Board   │ │ Behavior │ │Execution │ ...   │
│  │  Module  │ │  Module  │ │  Module  │ │  Module  │       │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘       │
│       │            │            │            │              │
│  ┌────┴────────────┴────────────┴────────────┴─────┐       │
│  │              PostgresPool (schema-aware)         │       │
│  └──────────────────────┬──────────────────────────┘       │
└─────────────────────────┼───────────────────────────────────┘
                          │
        ┌─────────────────┴─────────────────┐
        │                                   │
        ▼                                   ▼
┌───────────────────┐             ┌───────────────────┐
│   amprealize-db      │             │   telemetry-db    │
│   (pgvector)      │             │   (TimescaleDB)   │
├───────────────────┤             ├───────────────────┤
│ auth.*            │             │ telemetry.*       │
│ board.*           │             │ (hypertables)     │
│ behavior.*        │             └───────────────────┘
│ execution.*       │
│ workflow.*        │
│ consent.*         │
│ audit.*           │
└───────────────────┘
```

---

## 📋 Implementation Steps

### Step 1: Archive Legacy SQL Migrations

**Goal**: Remove SQL files from execution paths while preserving for reference.

**Files to move**:
```
schema/migrations/*.sql → schema/migrations.archive/
```

**Actions**:
1. Create `schema/migrations.archive/` directory
2. Move all `.sql` files from `schema/migrations/` to archive
3. Update any code referencing these files to use Alembic only
4. Remove SQL init script mounts from all BreakerAmp blueprints (already done)

**Verification**:
```bash
# Should return no results
grep -r "schema/migrations.*\.sql" --include="*.py" --include="*.yaml" .
```

---

### Step 2: Update PostgresPool with Schema Support

**File**: `amprealize/db/postgres_pool.py`

**Changes**:
1. Add `schema` parameter to `PostgresPool.__init__()`
2. Set `search_path` on each connection via event listener
3. Create `get_pool_for_schema(schema_name)` factory method
4. Support single `DATABASE_URL` with schema routing

**New API**:
```python
from amprealize.db.postgres_pool import PostgresPool

# Old way (deprecated)
pool = PostgresPool(dsn="postgresql://user:pass@auth-db:5432/auth")

# New way
pool = PostgresPool(
    dsn="postgresql://user:pass@amprealize-db:5432/amprealize",
    schema="auth"  # Sets search_path to "auth,public"
)

# Or via factory
pool = PostgresPool.for_schema("auth")  # Uses DATABASE_URL env var
```

**Implementation**:
```python
class PostgresPool:
    def __init__(
        self,
        dsn: str | None = None,
        schema: str | None = None,  # NEW
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_timeout: float = 30.0,
        statement_timeout_ms: int = 30000,
        lock_timeout_ms: int = 10000,
    ):
        self.schema = schema
        # ... existing init ...

        if schema:
            @event.listens_for(self.engine, "connect")
            def set_search_path(dbapi_conn, connection_record):
                cursor = dbapi_conn.cursor()
                cursor.execute(f"SET search_path TO {schema}, public")
                cursor.close()

    @classmethod
    def for_schema(cls, schema: str) -> "PostgresPool":
        """Factory method using DATABASE_URL with schema routing."""
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            raise ValueError("DATABASE_URL environment variable required")
        return cls(dsn=dsn, schema=schema)
```

---

### Step 3: Consolidate Alembic Configuration

**Files to modify**:
- `alembic.ini` - Main config
- `migrations/env.py` - Migration environment
- `alembic.workflow.ini` - DELETE (merge into main)
- `migrations_workflow/` - DELETE (merge into main migrations)

**Updated `alembic.ini`**:
```ini
[alembic]
script_location = migrations
sqlalchemy.url = postgresql://amprealize:amprealize@localhost:5432/amprealize

# Single version table in public schema
version_table = alembic_version
version_table_schema = public
```

**Updated `migrations/env.py`**:
```python
import os
from alembic import context
from sqlalchemy import engine_from_config, pool, text

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://amprealize:amprealize@localhost:5432/amprealize"
)

# All schemas managed by Alembic
MANAGED_SCHEMAS = ['auth', 'board', 'behavior', 'execution', 'workflow', 'consent', 'audit']

def run_migrations_online():
    config = context.config
    config.set_main_option("sqlalchemy.url", DATABASE_URL)

    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Create schemas if they don't exist
        for schema in MANAGED_SCHEMAS:
            connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        connection.commit()

        context.configure(
            connection=connection,
            target_metadata=None,  # No SQLAlchemy models yet
            include_schemas=True,
            version_table_schema="public",
        )

        with context.begin_transaction():
            context.run_migrations()
```

---

### Step 4: Create Unified Baseline Migration

**File**: `migrations/versions/20251216_unified_baseline.py`

**Schema structure**:

| Schema | Tables | Purpose |
|--------|--------|---------|
| `auth` | users, sessions, api_keys, organizations, org_memberships, projects | Authentication & multi-tenancy |
| `board` | boards, columns, work_items, sprints, comments | Agile board system |
| `behavior` | behaviors, behavior_executions, behavior_feedback | AI behavior system |
| `execution` | runs, actions, artifacts, action_results | Execution tracking |
| `workflow` | workflows, workflow_runs, workflow_steps | Workflow orchestration |
| `consent` | consents, consent_scopes | Permission management |
| `audit` | audit_log | Immutable audit trail |

**Cross-schema foreign keys** (enabled by single database):
```sql
-- board.work_items can reference auth.users
ALTER TABLE board.work_items
  ADD CONSTRAINT fk_work_items_assignee
  FOREIGN KEY (assignee_id) REFERENCES auth.users(id);

-- execution.runs can reference auth.users
ALTER TABLE execution.runs
  ADD CONSTRAINT fk_runs_user
  FOREIGN KEY (user_id) REFERENCES auth.users(id);
```

---

### Step 5: Update Configuration Settings

**File**: `amprealize/config/settings.py`

**Old environment variables** (to deprecate):
```
AMPREALIZE_TELEMETRY_PG_DSN
AMPREALIZE_BEHAVIOR_PG_DSN
AMPREALIZE_WORKFLOW_PG_DSN
AMPREALIZE_ACTION_PG_DSN
AMPREALIZE_RUN_PG_DSN
AMPREALIZE_EXECUTION_PG_DSN
AMPREALIZE_COMPLIANCE_PG_DSN
AMPREALIZE_AGENT_ORCHESTRATOR_PG_DSN
AMPREALIZE_METRICS_PG_DSN
AMPREALIZE_AUTH_PG_DSN
AMPREALIZE_BOARD_PG_DSN
AMPREALIZE_REFLECTION_PG_DSN
AMPREALIZE_COLLABORATION_PG_DSN
AMPREALIZE_ORG_PG_DSN
AMPREALIZE_TRACE_ANALYSIS_PG_DSN
```

**New environment variables**:
```
DATABASE_URL=postgresql://amprealize:amprealize@amprealize-db:5432/amprealize
TELEMETRY_DATABASE_URL=postgresql://telemetry:telemetry@telemetry-db:5432/telemetry
```

**Backward compatibility**: Keep old DSN variables working by mapping to schema:
```python
def get_dsn_for_service(service: str) -> tuple[str, str]:
    """Returns (dsn, schema) for a service.

    Supports both new single-DB and old multi-DB configurations.
    """
    # New unified approach
    if os.environ.get("DATABASE_URL"):
        schema_map = {
            "auth": "auth",
            "board": "board",
            "behavior": "behavior",
            "action": "execution",
            "run": "execution",
            "workflow": "workflow",
            "compliance": "audit",
            "orchestrator": "execution",
            "metrics": "execution",
            "organization": "auth",
            "reflection": "behavior",
            "collaboration": "board",
        }
        return os.environ["DATABASE_URL"], schema_map.get(service, "public")

    # Legacy multi-DB fallback
    dsn_var = f"AMPREALIZE_{service.upper()}_PG_DSN"
    return os.environ.get(dsn_var), None
```

---

### Step 6: Update BreakerAmp Blueprints

**File**: `packages/breakeramp/src/breakeramp/blueprints/local-test-suite.yaml`

**Before** (10 database containers):
```yaml
services:
  telemetry-db: ...
  behavior-db: ...
  workflow-db: ...
  action-db: ...
  run-db: ...
  compliance-db: ...
  orchestrator-db: ...
  metrics-db: ...
  auth-db: ...
  board-db: ...
```

**After** (2 database containers):
```yaml
services:
  # Main database with all schemas
  amprealize-db:
    image: pgvector/pgvector:pg16
    module: core
    ports:
      - "5432:5432"
    environment:
      POSTGRES_USER: amprealize
      POSTGRES_PASSWORD: amprealize
      POSTGRES_DB: amprealize
    volumes:
      - amprealize-db-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U amprealize -d amprealize"]
      interval: 5s
      timeout: 5s
      retries: 5

  # Separate TimescaleDB for telemetry (hypertables)
  telemetry-db:
    image: timescale/timescaledb:latest-pg16
    module: core
    ports:
      - "5433:5432"
    environment:
      POSTGRES_USER: telemetry
      POSTGRES_PASSWORD: telemetry
      POSTGRES_DB: telemetry
    volumes:
      - telemetry-db-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U telemetry -d telemetry"]
      interval: 5s
      timeout: 5s
      retries: 5

  amprealize-api:
    # ... existing config ...
    environment:
      DATABASE_URL: postgresql://amprealize:amprealize@amprealize-db:5432/amprealize
      TELEMETRY_DATABASE_URL: postgresql://telemetry:telemetry@telemetry-db:5433/telemetry
    depends_on:
      - amprealize-db
      - telemetry-db
    post_start_commands:
      - command: ["alembic", "upgrade", "head"]
        description: "Run Alembic migrations"
        timeout_s: 120

volumes:
  amprealize-db-data:
  telemetry-db-data:
```

---

### Step 7: Update Service Classes

**Pattern for updating services**:

Each service file (`*_service_postgres.py`) needs to:
1. Use `PostgresPool.for_schema(schema_name)` instead of DSN-based pool
2. Or set `search_path` at connection time

**Example: BoardService**

**Before**:
```python
class BoardService:
    def __init__(self, dsn: str | None = None):
        self.pool = PostgresPool(dsn=dsn or os.environ.get("AMPREALIZE_BOARD_PG_DSN"))
```

**After**:
```python
class BoardService:
    def __init__(self, pool: PostgresPool | None = None):
        self.pool = pool or PostgresPool.for_schema("board")
```

**Services to update** (in recommended order):
1. `amprealize/board/board_service.py` - Most complex, tests FK relationships
2. `amprealize/auth/user_service.py` - Foundation for cross-schema refs
3. `amprealize/services/behavior_service.py`
4. `amprealize/services/action_service_postgres.py`
5. `amprealize/services/run_service_postgres.py`
6. `amprealize/services/workflow_service.py`
7. `amprealize/services/compliance_service_postgres.py`
8. `amprealize/services/metrics_service_postgres.py`
9. `amprealize/services/agent_orchestrator_service_postgres.py`
10. `amprealize/services/reflection_service_postgres.py`
11. `amprealize/services/collaboration_service_postgres.py`
12. `amprealize/organization/organization_service_postgres.py`

---

### Step 8: Telemetry Service (Separate Database)

**File**: `amprealize/services/telemetry_service.py`

Telemetry keeps its own database connection since it uses TimescaleDB-specific features:

```python
class TelemetryService:
    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or os.environ.get("TELEMETRY_DATABASE_URL")
        self.pool = PostgresPool(dsn=self.dsn)  # No schema needed, dedicated DB
```

---

### Step 9: Update Application Bootstrap

**File**: `amprealize/services/__init__.py` or wherever services are instantiated

Update service factory to use new schema-based pools:

```python
def create_services() -> dict[str, Any]:
    """Create all services with schema-aware database connections."""

    # Main database schemas
    auth_pool = PostgresPool.for_schema("auth")
    board_pool = PostgresPool.for_schema("board")
    behavior_pool = PostgresPool.for_schema("behavior")
    execution_pool = PostgresPool.for_schema("execution")
    workflow_pool = PostgresPool.for_schema("workflow")
    audit_pool = PostgresPool.for_schema("audit")

    # Separate telemetry database
    telemetry_dsn = os.environ.get("TELEMETRY_DATABASE_URL")
    telemetry_pool = PostgresPool(dsn=telemetry_dsn) if telemetry_dsn else None

    return {
        "auth": AuthService(pool=auth_pool),
        "board": BoardService(pool=board_pool),
        "behavior": BehaviorService(pool=behavior_pool),
        "action": ActionService(pool=execution_pool),
        "run": RunService(pool=execution_pool),
        "workflow": WorkflowService(pool=workflow_pool),
        "compliance": ComplianceService(pool=audit_pool),
        "telemetry": TelemetryService(pool=telemetry_pool) if telemetry_pool else None,
        # ... etc
    }
```

---

## ✅ Verification Checklist

**All items verified on 2025-12-17:**

- [x] `breakeramp plan development` shows only 2 database containers ✅
- [x] `breakeramp apply` successfully starts amprealize-db and telemetry-db ✅
- [x] `alembic upgrade head` creates all schemas and tables ✅ (7 schemas: auth, board, behavior, execution, workflow, consent, audit)
- [x] API health check passes: `curl http://localhost:8000/health` ✅
- [x] Board endpoints work: `curl http://localhost:8000/v1/boards` ✅
- [x] Cross-schema queries work (e.g., work items with user data) ✅
- [x] Telemetry writes to separate database ✅ (TimescaleDB 2.24.0 on port 5433)
- [x] No references to legacy SQL migrations in execution paths ✅

**Containers Running:**
| Container | Image | Port | Status |
|-----------|-------|------|--------|
| amprealize-db | pgvector/pgvector:pg16 | 5432 | ✅ Up |
| telemetry-db | timescale/timescaledb:latest-pg16 | 5433 | ✅ Up |
| redis | redis:7-alpine | 6379 | ✅ Up |
| nginx | nginx:alpine | 8080 | ✅ Up |
| amprealize-api | amprealize-api:dev | 8000 | ✅ Up |
| web-console | web-console:dev | 5173 | ✅ Up |

---

## 🔄 Rollback Plan

If issues arise:

1. Keep old BreakerAmp blueprints in `blueprints.archive/`
2. Keep old DSN environment variables working via mapping
3. Archive (don't delete) old migration files
4. Can revert by restoring old blueprint and running `breakeramp apply`

---

## 📚 References

- [PostgreSQL Schemas Documentation](https://www.postgresql.org/docs/current/ddl-schemas.html)
- [Alembic Multi-Schema Support](https://alembic.sqlalchemy.org/en/latest/cookbook.html#run-multiple-alembic-environments-from-one-ini-file)
- [pgvector Extension](https://github.com/pgvector/pgvector)
- [TimescaleDB Documentation](https://docs.timescale.com/)

---

## 🤖 Agent Instructions

When implementing this plan:

1. **Follow the step order** - Dependencies exist between steps
2. **Test after each step** - Run `pytest` or relevant endpoint tests
3. **Cite this document** - Reference `docs/DATABASE_CONSOLIDATION_PLAN.md` in commits
4. **Update this document** - Mark steps complete, add lessons learned
5. **Don't modify archived SQL** - `schema/migrations.archive/` is reference only

**Behaviors to follow**:
- `behavior_migrate_postgres_schema` - For all Alembic changes
- `behavior_use_breakeramp_for_environments` - For blueprint updates
- `behavior_update_docs_after_changes` - Keep this doc current
