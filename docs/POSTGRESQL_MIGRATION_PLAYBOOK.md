# PostgreSQL Migration Execution Playbook

> **Last Updated:** 2025-10-24
> **Status:** Phase 3 Backend Migration (BehaviorService + WorkflowService)
> **Owner:** Engineering + DevOps
> **Behaviors:** `behavior_align_storage_layers`, `behavior_unify_execution_records`, `behavior_externalize_configuration`, `behavior_update_docs_after_changes`

## Overview

This playbook documents the step-by-step procedures for migrating amprealize services from SQLite to PostgreSQL in production environments. It covers pre-flight validation, dry-run rehearsals, production cutover, rollback procedures, and post-migration verification.

### Migration Scope

**Phase 3 Services (Current):**
- ✅ TelemetryService (warehouse) – Complete
- ✅ MetricsService (Timescale observability) – Schema tooling complete via `run_postgres_metrics_migration.py`
- ✅ TraceAnalysisService – Schema tooling complete via `run_postgres_trace_migration.py`
- 🚧 BehaviorService – Tooling complete, execution pending
- 🚧 WorkflowService – Tooling complete, execution pending

**Future Phases:**
- ⏳ ActionService – Schema design pending
- ⏳ ComplianceService – Schema design pending
- ⏳ RunService – Schema design pending

### Success Criteria

- Zero data loss during migration
- <5 minutes downtime for production cutover
- All services operational on PostgreSQL with fallback capability
- Telemetry events flowing to PostgreSQL warehouse
- All parity tests passing against PostgreSQL backend

---

## Prerequisites

### Infrastructure Requirements

#### PostgreSQL Instance
- **Version:** PostgreSQL 14+ (for JSONB performance improvements)
- **Extensions:** `uuid-ossp`, `pg_trgm` (for text search), `pgcrypto` (for checksums)
- **Resources:**
  - Dev/Staging: 2 vCPU, 4GB RAM, 50GB storage
  - Production: 4 vCPU, 16GB RAM, 500GB storage (SSD)
- **Connection Pooling:** pgbouncer recommended (max_connections: 100)
- **Backup Strategy:** Point-in-time recovery (PITR) enabled, 7-day retention

#### Docker-Based Development Setup (Recommended)

For local development and validation, use the provided Docker Compose setup with Podman:

```bash
# Start PostgreSQL services (telemetry, behavior, workflow databases)
podman-compose -f docker-compose.postgres.yml up -d

# Verify all containers are healthy
podman-compose -f docker-compose.postgres.yml ps

# Access pgAdmin web interface (optional)
# URL: http://localhost:5050
# Email: admin@amprealize.local
# Password: admin

# Load environment variables
source .env.postgres

# When finished, stop and clean up
podman-compose -f docker-compose.postgres.yml down -v
```

**Container Architecture:**
- `postgres-telemetry` (port 5432): TelemetryService database
- `postgres-behavior` (port 5433): BehaviorService database
- `postgres-workflow` (port 5434): WorkflowService database
- `pgadmin` (port 5050): Web-based database inspection tool

**Note:** Amprealize uses Podman as the standard container runtime per `deployment/CONTAINER_RUNTIME_DECISION.md`. If you have Docker installed, you can use compatibility aliases:
```bash
alias docker=podman
alias docker-compose=podman-compose
```

#### Network Access
- **Dev Environment:** Docker Compose setup (see above) or direct PostgreSQL access via DSN
- **Staging/Production:** Encrypted connections (SSL/TLS required)
- **Firewall Rules:** Allow amprealize application servers on port 5432

### Python Dependencies

Install optional PostgreSQL dependencies:

```bash
# Install psycopg2 for PostgreSQL connectivity
pip install -e ".[postgres]"

# Local-only alternative (when extras are unavailable)
pip install psycopg2-binary

# Verify installation
python -c "import psycopg2; print(psycopg2.__version__)"
```

### Environment Variables

Configure DSN environment variables for each service:

```bash
# Docker-based development (recommended)
source .env.postgres

# Or manual configuration:
export AMPREALIZE_TELEMETRY_PG_DSN="postgresql://amprealize_telemetry:dev_telemetry_pass@localhost:5432/telemetry"
export AMPREALIZE_METRICS_PG_DSN="postgresql://amprealize_metrics:dev_metrics_pass@localhost:5439/metrics"
export AMPREALIZE_BEHAVIOR_PG_DSN="postgresql://amprealize_behavior:dev_behavior_pass@localhost:5433/behaviors"
export AMPREALIZE_WORKFLOW_PG_DSN="postgresql://amprealize_workflow:dev_workflow_pass@localhost:5434/workflows"
export AMPREALIZE_TRACE_ANALYSIS_PG_DSN="postgresql://amprealize_trace:dev_trace_pass@localhost:5435/trace_analysis"

# Production (use secrets manager per SECRETS_MANAGEMENT_PLAN.md)
export AMPREALIZE_BEHAVIOR_PG_DSN="postgresql://amprealize_prod:${PG_PASSWORD}@postgres.internal:5432/amprealize_prod?sslmode=require"
export AMPREALIZE_WORKFLOW_PG_DSN="postgresql://amprealize_prod:${PG_PASSWORD}@postgres.internal:5432/amprealize_prod?sslmode=require"
export AMPREALIZE_TELEMETRY_PG_DSN="postgresql://amprealize_prod:${PG_PASSWORD}@postgres.internal:5432/amprealize_prod?sslmode=require"
export AMPREALIZE_METRICS_PG_DSN="postgresql://amprealize_prod:${PG_PASSWORD}@postgres.internal:5432/amprealize_metrics?sslmode=require"
export AMPREALIZE_TRACE_ANALYSIS_PG_DSN="postgresql://amprealize_prod:${PG_PASSWORD}@postgres.internal:5432/amprealize_trace_analysis?sslmode=require"
```

**Note:** Docker setup uses separate databases per service (matching production microservice architecture). Each service has isolated credentials and ports.

**Security Best Practices:**
- Store DSNs in secrets manager (AWS Secrets Manager, Vault, etc.)
- Rotate credentials every 90 days
- Use read-only replicas for analytics queries
- Enable audit logging for DDL operations

---

## Phase 1: Pre-Flight Validation

### 1.1 SQLite Data Inventory

Capture baseline metrics from existing SQLite databases:

```bash
# BehaviorService inventory
sqlite3 ~/.amprealize/data/behaviors.db <<EOF
.mode column
SELECT 'behaviors' as table_name, COUNT(*) as row_count FROM behaviors
UNION ALL
SELECT 'behavior_versions', COUNT(*) FROM behavior_versions;
EOF

# WorkflowService inventory
sqlite3 ~/.amprealize/workflows.db <<EOF
SELECT 'workflow_templates' as table_name, COUNT(*) as row_count FROM workflow_templates
UNION ALL
SELECT 'workflow_runs', COUNT(*) FROM workflow_runs;
EOF
```

**Document Results:**
```
[Dev Environment - 2025-10-24]
- behaviors: 47 rows
- behavior_versions: 103 rows
- workflow_templates: 12 rows
- workflow_runs: 234 rows
- Total SQLite size: 4.2 MB
```

### 1.2 PostgreSQL Connectivity Test

Verify connectivity to target PostgreSQL instance:

```bash
# Test connection
psql "${AMPREALIZE_BEHAVIOR_PG_DSN}" -c "SELECT version();"

# Check required extensions
psql "${AMPREALIZE_BEHAVIOR_PG_DSN}" -c "CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";"
psql "${AMPREALIZE_BEHAVIOR_PG_DSN}" -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"

# Verify user permissions
psql "${AMPREALIZE_BEHAVIOR_PG_DSN}" -c "SELECT has_database_privilege(current_user, current_database(), 'CREATE');"
```

**Expected Output:**
- PostgreSQL version displayed
- Extensions created successfully
- User has CREATE privilege: `t` (true)

### 1.3 Migration Script Validation

Verify all migration scripts are available and executable:

```bash
# Check schema migrations
ls -lh schema/migrations/
# Expected: 001_create_telemetry_warehouse.sql
#           002_create_behavior_service.sql
#           003_create_workflow_service.sql
#           012_create_metrics_service.sql
#           013_create_trace_analysis.sql

# Check migration runners
ls -lh scripts/run_postgres_*.py
# Expected: run_postgres_telemetry_migration.py
#           run_postgres_metrics_migration.py
#           run_postgres_trace_migration.py
#           run_postgres_behavior_migration.py
#           run_postgres_workflow_migration.py

# Check data migration tools
ls -lh scripts/migrate_*_sqlite_to_postgres.py
# Expected: migrate_behavior_sqlite_to_postgres.py
#           migrate_workflow_sqlite_to_postgres.py

# Verify Python syntax
python -m compileall scripts/run_postgres_*.py scripts/migrate_*.py
```

### 1.4 Backup SQLite Databases

Create timestamped backups before migration:

```bash
# Create backup directory
mkdir -p ~/.amprealize/backups/$(date +%Y%m%d_%H%M%S)

# Backup BehaviorService
cp ~/.amprealize/data/behaviors.db \
   ~/.amprealize/backups/$(date +%Y%m%d_%H%M%S)/behaviors.db.backup

# Backup WorkflowService
cp ~/.amprealize/workflows.db \
   ~/.amprealize/backups/$(date +%Y%m%d_%H%M%S)/workflows.db.backup

# Verify backups
ls -lh ~/.amprealize/backups/$(date +%Y%m%d_%H%M%S)/
sqlite3 ~/.amprealize/backups/$(date +%Y%m%d_%H%M%S)/behaviors.db.backup "PRAGMA integrity_check;"
```

### 1.5 Generate Dry-Run Readiness Report

Run the automation that inspects schema migrations, validates SQLite inventory, and
emits a structured report for the change record. Capture both JSON (for machine
consumption) and Markdown (for the runbook appendix):

```bash
# Generate reports in-place (override paths per environment policy)
python scripts/generate_postgres_migration_report.py \
  --format both \
  --output-json reports/postgres_migration_dry_run.json \
  --output-markdown reports/postgres_migration_dry_run.md
```

**Report Fields:**
- Schema statement counts for BehaviorService and WorkflowService migrations
- SQLite file presence, size, and row counts for behaviors, versions, templates, and runs
- Recommended dry-run and full-execution commands with DSN + path placeholders
- Warnings if SQLite checkpoints are missing (resolve before rehearsal)

Attach the generated report to the change request or ticket for audit evidence
(`behavior_update_docs_after_changes`).

---

## Phase 2: Schema Migration (Dry Run)

### 2.0 Observability Warehouse (Telemetry + Metrics + Trace)

Before touching BehaviorService or WorkflowService, bring every observability
database to the latest schema so telemetry, KPI dashboards, and trace analysis
all share the same ground truth (`behavior_instrument_metrics_pipeline`). Use
the CLI runners to dry-run and then apply the migrations. Each command accepts
`--dry-run`, `--migration`, and `--connect-timeout` just like the telemetry
runner.

```bash
# Dry run (preview statements without executing)
python scripts/run_postgres_telemetry_migration.py --dsn "${AMPREALIZE_TELEMETRY_PG_DSN}" --dry-run
python scripts/run_postgres_metrics_migration.py --dsn "${AMPREALIZE_METRICS_PG_DSN}" --dry-run
python scripts/run_postgres_trace_migration.py --dsn "${AMPREALIZE_TRACE_ANALYSIS_PG_DSN}" --dry-run

# Apply migrations when ready
python scripts/run_postgres_telemetry_migration.py --dsn "${AMPREALIZE_TELEMETRY_PG_DSN}"
python scripts/run_postgres_metrics_migration.py --dsn "${AMPREALIZE_METRICS_PG_DSN}"
python scripts/run_postgres_trace_migration.py --dsn "${AMPREALIZE_TRACE_ANALYSIS_PG_DSN}"
```

**Verification checklist:**
- [ ] Telemetry hypertables and retention policies exist (`SELECT table_name FROM information_schema.tables WHERE table_schema='prd_telemetry';`).
- [ ] Metrics hypertables (`metrics_snapshots`, `behavior_usage_events`, `token_usage_events`, `completion_events`, `compliance_events`) are visible in `prd_metrics` schema.
- [ ] Trace analysis tables (`trace_runs`, `trace_segments`, `pattern_library`, continuous aggregates) exist in `prd_trace_analysis` schema.
- [ ] All three runners print the "✅ Migration applied successfully." confirmation before proceeding.

Archive the stdout for each command inside the change request bundle; this is
required evidence for `behavior_update_docs_after_changes` and the audit log.

### 2.1 BehaviorService Schema Migration

Apply BehaviorService schema to PostgreSQL:

```bash
# Dry run (preview statements)
python scripts/run_postgres_behavior_migration.py \
  --dsn "${AMPREALIZE_BEHAVIOR_PG_DSN}" \
  --dry-run

# Review output, verify 10-15 statements printed
# Expected: CREATE TABLE behaviors, CREATE TABLE behavior_versions,
#           CREATE INDEX statements, etc.
```

**Review Checklist:**
- [ ] All CREATE TABLE statements present
- [ ] Indexes defined (behavior_id, version, role_focus, status, tags GIN)
- [ ] JSONB columns for metadata/trigger_keywords/examples
- [ ] Foreign key constraints with CASCADE delete
- [ ] No syntax errors in DDL

### 2.2 WorkflowService Schema Migration

Apply WorkflowService schema:

```bash
# Dry run
python scripts/run_postgres_workflow_migration.py \
  --dsn "${AMPREALIZE_WORKFLOW_PG_DSN}" \
  --dry-run

# Review output
```

**Review Checklist:**
- [ ] workflow_templates and workflow_runs tables
- [ ] JSONB columns for template_data/run_data/tags
- [ ] Indexes on template_id, role_focus, status, started_at
- [ ] Foreign key from workflow_runs to workflow_templates

### 2.3 Execute Schema Migrations

Apply schemas to PostgreSQL:

```bash
# Apply BehaviorService schema
python scripts/run_postgres_behavior_migration.py \
  --dsn "${AMPREALIZE_BEHAVIOR_PG_DSN}"

# Expected output:
# Applying behavior migration using DSN: postgresql://...
# Executing 15 statements from schema/migrations/002_create_behavior_service.sql
# ✅ Migration applied successfully.

# Apply WorkflowService schema
python scripts/run_postgres_workflow_migration.py \
  --dsn "${AMPREALIZE_WORKFLOW_PG_DSN}"
```

### 2.3 Automated Rehearsal Runner

After verifying individual scripts, execute the orchestration helper to perform
both schema dry-runs and data dry-run inspections while capturing timing data.

1. Ensure the same interpreter that has `psycopg2` installed is used (the
  helper shells out with `sys.executable`).
2. Create a dated artifact directory for evidence:

  ```bash
  mkdir -p artifacts/migration/$(date +%F)
  ```

3. Run the orchestration script:

  ```bash
  python scripts/run_postgres_migration_rehearsal.py \
    --behavior-dsn "${AMPREALIZE_BEHAVIOR_PG_DSN}" \
    --workflow-dsn "${AMPREALIZE_WORKFLOW_PG_DSN}" \
    --format both \
    --output-json artifacts/migration/$(date +%F)/rehearsal.json \
    --output-markdown artifacts/migration/$(date +%F)/rehearsal.md
  ```

**What this captures:**
- Duration and exit status for each schema/data dry-run command
- stdout/stderr excerpts for debugging failures
- Warnings when SQLite checkpoints are missing (resolve before staging run)

**Success Criteria:**
- Both schema dry-run steps exit 0 and complete in <2s
- Data dry-run steps exit 0 and report the expected row counts from SQLite
- Reports archived alongside change ticket and linked in CMD record

If running in CI, add `--ci` so the command exits non-zero when any step fails.
Attach both JSON and Markdown outputs from `artifacts/migration/<date>/` to the
rehearsal evidence bundle (and upload alongside the change ticket).

### 2.4 Verify Schema Creation

Inspect created tables and indexes:

```bash
# List BehaviorService tables
psql "${AMPREALIZE_BEHAVIOR_PG_DSN}" -c "\dt"

# Describe behaviors table
psql "${AMPREALIZE_BEHAVIOR_PG_DSN}" -c "\d behaviors"

# List indexes
psql "${AMPREALIZE_BEHAVIOR_PG_DSN}" -c "\di"

# Count rows (should be 0)
psql "${AMPREALIZE_BEHAVIOR_PG_DSN}" -c "SELECT COUNT(*) FROM behaviors;"
psql "${AMPREALIZE_BEHAVIOR_PG_DSN}" -c "SELECT COUNT(*) FROM workflow_templates;"
```

**Expected Output:**
```
                List of relations
 Schema |         Name          | Type  |  Owner
--------+-----------------------+-------+----------
 public | behaviors             | table | amprealize
 public | behavior_versions     | table | amprealize
 public | workflow_templates    | table | amprealize
 public | workflow_runs         | table | amprealize

 count
-------
     0
```

---

## Phase 3: Data Migration (Dry Run)

### 3.1 BehaviorService Data Migration Dry Run

Test data migration without writing to PostgreSQL:

```bash
# Dry run data migration
python scripts/migrate_behavior_sqlite_to_postgres.py \
  --dsn "${AMPREALIZE_BEHAVIOR_PG_DSN}" \
  --sqlite-path ~/.amprealize/data/behaviors.db \
  --dry-run

# Expected output:
# 📥 Loaded 47 behaviors and 103 behavior versions from SQLite
# ℹ️ Dry run complete; no changes applied to PostgreSQL.
```

**Review Checklist:**
- [ ] SQLite database found and readable
- [ ] Row counts match inventory (behaviors: 47, versions: 103)
- [ ] No errors parsing SQLite data
- [ ] Dry run completed without PostgreSQL connection

### 3.2 WorkflowService Data Migration Dry Run

```bash
# Dry run workflow migration
python scripts/migrate_workflow_sqlite_to_postgres.py \
  --dsn "${AMPREALIZE_WORKFLOW_PG_DSN}" \
  --sqlite-path ~/.amprealize/workflows.db \
  --dry-run

# Expected output:
# 📥 Loaded 12 workflow templates and 234 workflow runs from SQLite
# ℹ️ Dry run complete; no changes applied to PostgreSQL.
```

### 3.3 Estimate Migration Timing

Benchmark data migration with small batch:

```bash
# Time full migration (for estimation)
time python scripts/migrate_behavior_sqlite_to_postgres.py \
  --dsn "${AMPREALIZE_BEHAVIOR_PG_DSN}" \
  --sqlite-path ~/.amprealize/data/behaviors.db \
  --chunk-size 100

# Document timing
# Example: real 0m2.341s (47 behaviors, 103 versions)
```

**Extrapolation for Production:**
- Small dataset (100 behaviors, 200 versions): ~2-3 seconds
- Medium dataset (1K behaviors, 5K versions): ~30-60 seconds
- Large dataset (10K behaviors, 50K versions): ~5-10 minutes

---

## Phase 4: Full Migration Execution

### 4.1 Pre-Migration Checklist

- [ ] PostgreSQL instance accessible and healthy
- [ ] Schema migrations applied successfully
- [ ] SQLite backups created and verified
- [ ] Dry run completed with expected row counts
- [ ] All services using SQLite are stopped (production only)
- [ ] Maintenance window scheduled (if production)

### 4.2 Execute Data Migrations

Migrate data from SQLite to PostgreSQL:

```bash
# Start migration timestamp
echo "Migration started: $(date)"

# BehaviorService data migration
python scripts/migrate_behavior_sqlite_to_postgres.py \
  --dsn "${AMPREALIZE_BEHAVIOR_PG_DSN}" \
  --sqlite-path ~/.amprealize/data/behaviors.db \
  --chunk-size 500

# WorkflowService data migration
python scripts/migrate_workflow_sqlite_to_postgres.py \
  --dsn "${AMPREALIZE_WORKFLOW_PG_DSN}" \
  --sqlite-path ~/.amprealize/workflows.db \
  --chunk-size 500

# End migration timestamp
echo "Migration completed: $(date)"
```

**Expected Output:**
```
Migration started: Thu Oct 24 14:30:00 PDT 2025
📥 Loaded 47 behaviors and 103 behavior versions from SQLite ~/.amprealize/data/behaviors.db
⬆️ Upserting 47 behavior rows…
⬆️ Upserting 103 behavior version rows…
✅ Migration complete. PostgreSQL now mirrors the SQLite BehaviorService store.
📥 Loaded 12 workflow templates and 234 workflow runs from SQLite ~/.amprealize/workflows.db
⬆️ Upserting 12 workflow templates…
⬆️ Upserting 234 workflow runs…
✅ Migration complete. PostgreSQL now mirrors the SQLite WorkflowService store.
Migration completed: Thu Oct 24 14:32:15 PDT 2025
```

### 4.3 Verify Data Integrity

Compare row counts between SQLite and PostgreSQL:

```bash
# BehaviorService verification
echo "=== BehaviorService Verification ==="
echo -n "SQLite behaviors: "
sqlite3 ~/.amprealize/data/behaviors.db "SELECT COUNT(*) FROM behaviors;"
echo -n "PostgreSQL behaviors: "
psql "${AMPREALIZE_BEHAVIOR_PG_DSN}" -t -c "SELECT COUNT(*) FROM behaviors;"

echo -n "SQLite behavior_versions: "
sqlite3 ~/.amprealize/data/behaviors.db "SELECT COUNT(*) FROM behavior_versions;"
echo -n "PostgreSQL behavior_versions: "
psql "${AMPREALIZE_BEHAVIOR_PG_DSN}" -t -c "SELECT COUNT(*) FROM behavior_versions;"

# WorkflowService verification
echo "=== WorkflowService Verification ==="
echo -n "SQLite workflow_templates: "
sqlite3 ~/.amprealize/workflows.db "SELECT COUNT(*) FROM workflow_templates;"
echo -n "PostgreSQL workflow_templates: "
psql "${AMPREALIZE_WORKFLOW_PG_DSN}" -t -c "SELECT COUNT(*) FROM workflow_templates;"

echo -n "SQLite workflow_runs: "
sqlite3 ~/.amprealize/workflows.db "SELECT COUNT(*) FROM workflow_runs;"
echo -n "PostgreSQL workflow_runs: "
psql "${AMPREALIZE_WORKFLOW_PG_DSN}" -t -c "SELECT COUNT(*) FROM workflow_runs;"
```

**Expected Output:**
```
=== BehaviorService Verification ===
SQLite behaviors: 47
PostgreSQL behaviors: 47
SQLite behavior_versions: 103
PostgreSQL behavior_versions: 103
=== WorkflowService Verification ===
SQLite workflow_templates: 12
PostgreSQL workflow_templates: 12
SQLite workflow_runs: 234
PostgreSQL workflow_runs: 234
```

### 4.4 Spot Check Data Content

Verify sample records match between SQLite and PostgreSQL:

```bash
# Compare first behavior
echo "=== SQLite First Behavior ==="
sqlite3 ~/.amprealize/data/behaviors.db "SELECT behavior_id, name, status FROM behaviors LIMIT 1;"

echo "=== PostgreSQL First Behavior ==="
psql "${AMPREALIZE_BEHAVIOR_PG_DSN}" -c "SELECT behavior_id, name, status FROM behaviors LIMIT 1;"

# Compare JSONB payload integrity
psql "${AMPREALIZE_BEHAVIOR_PG_DSN}" -c "SELECT behavior_id, jsonb_array_length(tags) as tag_count FROM behaviors WHERE jsonb_array_length(tags) > 0 LIMIT 1;"
```

---

## Phase 5: Service Configuration Update

### 5.1 Update Service Configuration

Point services to PostgreSQL instead of SQLite:

#### BehaviorService Configuration

```python
# amprealize/behavior_service.py (conceptual - actual implementation uses DSN detection)

# Before (SQLite)
behavior_service = BehaviorService(
    db_path=Path.home() / ".amprealize" / "data" / "behaviors.db"
)

# After (PostgreSQL)
behavior_service = BehaviorService(
    db_path=None,  # Triggers PostgreSQL mode
    postgres_dsn=os.getenv("AMPREALIZE_BEHAVIOR_PG_DSN")
)
```

**Environment-Based Configuration:**

Create environment-specific configs:

```bash
# config/dev.env
AMPREALIZE_BEHAVIOR_BACKEND=sqlite
AMPREALIZE_BEHAVIOR_SQLITE_PATH=~/.amprealize/data/behaviors.db

# config/prod.env
AMPREALIZE_BEHAVIOR_BACKEND=postgresql
AMPREALIZE_BEHAVIOR_PG_DSN=postgresql://...
```

### 5.2 Service Restart Procedure

For production cutover:

```bash
# Stop services
systemctl stop amprealize-api
systemctl stop amprealize-worker

# Update environment variables
source /etc/amprealize/prod.env

# Start services
systemctl start amprealize-api
systemctl start amprealize-worker

# Verify healthy
curl http://localhost:8000/health
```

---

## Phase 6: Post-Migration Validation

### 6.1 Integration Test Suite

Run full parity test suite against PostgreSQL:

```bash
# Set PostgreSQL DSN for tests
export AMPREALIZE_BEHAVIOR_PG_DSN="postgresql://amprealize_dev:password@localhost:5432/amprealize_dev"
export AMPREALIZE_WORKFLOW_PG_DSN="postgresql://amprealize_dev:password@localhost:5432/amprealize_dev"

# Run BehaviorService parity tests
pytest tests/test_behavior_parity.py -v

# Run WorkflowService parity tests
pytest tests/test_workflow_parity.py -v

# Run cross-surface consistency tests
pytest tests/test_cross_surface_consistency.py -v
```

**Expected Results:**
- All tests passing (0 failures)
- PostgreSQL connection successful
- Data operations (create/read/update/delete) functional
- Telemetry events emitted correctly

### 6.2 Functional Smoke Tests

Execute critical user workflows:

```bash
# Create new behavior
amprealize behavior create-draft \
  --name "test-behavior-post-migration" \
  --description "Verify PostgreSQL write operations" \
  --instruction "Test instruction" \
  --role STRATEGIST

# List behaviors (verify read)
amprealize behavior list --format table

# Create workflow template
amprealize workflow create-template \
  --name "test-workflow-post-migration" \
  --role STRATEGIST \
  --steps examples/strategist_workflow_steps.json

# List workflows
amprealize workflow list-templates --format table
```

### 6.3 Performance Baseline

Capture PostgreSQL performance metrics:

```bash
# Query execution time
psql "${AMPREALIZE_BEHAVIOR_PG_DSN}" -c "\timing on" -c "SELECT COUNT(*) FROM behaviors;"
psql "${AMPREALIZE_BEHAVIOR_PG_DSN}" -c "\timing on" -c "SELECT * FROM behaviors WHERE status = 'ACTIVE' LIMIT 100;"

# Index usage
psql "${AMPREALIZE_BEHAVIOR_PG_DSN}" -c "SELECT schemaname, tablename, indexname, idx_scan FROM pg_stat_user_indexes WHERE schemaname = 'public';"
```

**Expected Performance:**
- Simple COUNT queries: <10ms
- Filtered SELECT with index: <50ms
- Index scans > 0 (indexes being used)

### 6.4 Telemetry Verification

Confirm telemetry events flowing to PostgreSQL:

```bash
# Check recent telemetry events
psql "${AMPREALIZE_TELEMETRY_PG_DSN}" -c "SELECT event_type, COUNT(*) FROM telemetry.events WHERE timestamp > NOW() - INTERVAL '1 hour' GROUP BY event_type ORDER BY COUNT DESC;"

# Verify KPI view data
psql "${AMPREALIZE_TELEMETRY_PG_DSN}" -c "SELECT * FROM prd_metrics.view_behavior_reuse_rate;"
```

---

## Phase 7: Rollback Procedures

### 7.1 When to Rollback

Trigger rollback if:
- Data integrity validation fails (row count mismatch)
- Parity tests fail after migration
- Performance degradation >2x compared to SQLite
- Critical functionality broken (unable to create/read behaviors)
- Production incidents within 24 hours of cutover

### 7.2 Immediate Rollback (Production)

Revert to SQLite backends:

```bash
# Stop services
systemctl stop amprealize-api
systemctl stop amprealize-worker

# Switch to SQLite configuration
source /etc/amprealize/sqlite.env

# Verify SQLite databases intact
sqlite3 ~/.amprealize/data/behaviors.db "PRAGMA integrity_check;"
sqlite3 ~/.amprealize/workflows.db "PRAGMA integrity_check;"

# Start services
systemctl start amprealize-api
systemctl start amprealize-worker

# Verify healthy
curl http://localhost:8000/health
amprealize behavior list --limit 5
```

**Downtime:** 2-3 minutes

### 7.3 Data Rollback (if PostgreSQL data corrupted)

Restore from SQLite backups:

```bash
# Identify backup timestamp
ls -lh ~/.amprealize/backups/

# Restore from backup
cp ~/.amprealize/backups/20251024_143000/behaviors.db.backup \
   ~/.amprealize/data/behaviors.db

cp ~/.amprealize/backups/20251024_143000/workflows.db.backup \
   ~/.amprealize/workflows.db

# Verify integrity
sqlite3 ~/.amprealize/data/behaviors.db "PRAGMA integrity_check;"

# Restart services
systemctl restart amprealize-api
```

### 7.4 PostgreSQL Data Recovery

If PostgreSQL has newer data to preserve:

```bash
# Dump PostgreSQL data
pg_dump "${AMPREALIZE_BEHAVIOR_PG_DSN}" \
  --table=behaviors \
  --table=behavior_versions \
  --data-only \
  --format=custom \
  --file=/tmp/behaviors_pg_backup.dump

# Merge strategy options:
# 1. Re-run data migration with --truncate flag (loses PG-only data)
# 2. Manual reconciliation (identify delta, update SQLite)
# 3. Keep PostgreSQL, fix underlying issue
```

---

## Phase 8: Cleanup and Documentation

### 8.1 Post-Migration Cleanup

After 7-day stabilization period:

```bash
# Archive SQLite databases
mkdir -p ~/.amprealize/archive/$(date +%Y%m%d)
mv ~/.amprealize/data/behaviors.db \
   ~/.amprealize/archive/$(date +%Y%m%d)/behaviors.db
mv ~/.amprealize/workflows.db \
   ~/.amprealize/archive/$(date +%Y%m%d)/workflows.db

# Update configuration to remove SQLite paths
# (keep for 90-day retention per compliance requirements)

# Document migration completion
amprealize record-action \
  --artifact schema/migrations/002_create_behavior_service.sql \
  --summary "Complete BehaviorService + WorkflowService PostgreSQL migration" \
  --behaviors behavior_align_storage_layers behavior_unify_execution_records
```

### 8.2 Update Documentation

Sync migration status:

- [ ] Update `PROGRESS_TRACKER.md` PostgreSQL migration row to "✅ Complete"
- [ ] Add `BUILD_TIMELINE.md` entry with migration execution evidence
- [ ] Log completion in `PRD_ALIGNMENT_LOG.md`
- [ ] Update `PRD_NEXT_STEPS.md` to mark Phase 3 complete
- [ ] Document lessons learned in this playbook (Section 9)

### 8.3 Monitoring Configuration

Set up ongoing PostgreSQL monitoring:

```bash
# Connection pool monitoring
psql "${AMPREALIZE_BEHAVIOR_PG_DSN}" -c "SELECT * FROM pg_stat_activity WHERE datname = 'amprealize_prod';"

# Table bloat monitoring
psql "${AMPREALIZE_BEHAVIOR_PG_DSN}" -c "SELECT schemaname, tablename, pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size FROM pg_tables WHERE schemaname = 'public' ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;"

# Query performance
psql "${AMPREALIZE_BEHAVIOR_PG_DSN}" -c "SELECT query, calls, total_time, mean_time FROM pg_stat_statements ORDER BY mean_time DESC LIMIT 10;"
```

---

## Phase 9: Lessons Learned (Post-Migration)

_To be completed after production migration execution_

### What Went Well
- [ ] _Document successes_

### What Could Be Improved
- [ ] _Document challenges_

### Action Items for Future Migrations
- [ ] _Document process improvements_

---

## Appendix A: Troubleshooting Guide

### Issue: Migration Script Fails with "psycopg2 not found"

**Symptom:**
```
ImportError: No module named 'psycopg2'
```

**Resolution:**
```bash
pip install -e ".[postgres]"
# or
pip install psycopg2-binary
```

### Issue: Connection Refused to PostgreSQL

**Symptom:**
```
psycopg2.OperationalError: could not connect to server: Connection refused
```

**Resolution:**
1. Verify PostgreSQL is running: `pg_isready -h localhost -p 5432`
2. Check DSN format: `postgresql://user:pass@host:port/database`
3. Verify firewall rules: `telnet postgres.internal 5432`
4. Check pg_hba.conf allows connections from application server

### Issue: Row Count Mismatch After Migration

**Symptom:**
```
SQLite behaviors: 47
PostgreSQL behaviors: 45
```

**Resolution:**
1. Check migration logs for errors during upsert
2. Verify ON CONFLICT resolution didn't skip rows
3. Re-run migration with `--truncate` flag:
   ```bash
   python scripts/migrate_behavior_sqlite_to_postgres.py \
     --dsn "${AMPREALIZE_BEHAVIOR_PG_DSN}" \
     --sqlite-path ~/.amprealize/data/behaviors.db \
     --truncate
   ```

### Issue: JSONB Column Contains Invalid JSON

**Symptom:**
```
psycopg2.errors.InvalidTextRepresentation: invalid input syntax for type json
```

**Resolution:**
1. Identify problematic row in SQLite:
   ```bash
   sqlite3 ~/.amprealize/data/behaviors.db "SELECT behavior_id, tags FROM behaviors WHERE tags NOT LIKE '[%' AND tags NOT LIKE '{%';"
   ```
2. Fix data in SQLite before re-running migration
3. Add validation to migration script to skip/log invalid JSON

### Issue: Performance Degradation After Migration

**Symptom:**
- Queries taking >500ms (previously <50ms in SQLite)

**Resolution:**
1. Verify indexes created: `\di` in psql
2. Run ANALYZE to update statistics:
   ```sql
   ANALYZE behaviors;
   ANALYZE behavior_versions;
   ```
3. Check query plans:
   ```sql
   EXPLAIN ANALYZE SELECT * FROM behaviors WHERE status = 'ACTIVE';
   ```
4. Consider creating additional indexes based on query patterns

---

## Appendix B: Quick Reference Commands

### Pre-Flight
```bash
# Inventory SQLite
sqlite3 ~/.amprealize/data/behaviors.db "SELECT COUNT(*) FROM behaviors;"

# Test PostgreSQL connection
psql "${AMPREALIZE_BEHAVIOR_PG_DSN}" -c "SELECT 1;"

# Backup SQLite
cp ~/.amprealize/data/behaviors.db ~/.amprealize/backups/$(date +%Y%m%d_%H%M%S)/
```

### Migration
```bash
# Schema migration
python scripts/run_postgres_behavior_migration.py --dsn "${AMPREALIZE_BEHAVIOR_PG_DSN}"

# Data migration
python scripts/migrate_behavior_sqlite_to_postgres.py \
  --dsn "${AMPREALIZE_BEHAVIOR_PG_DSN}" \
  --sqlite-path ~/.amprealize/data/behaviors.db
```

### Verification
```bash
# Row count verification
psql "${AMPREALIZE_BEHAVIOR_PG_DSN}" -c "SELECT COUNT(*) FROM behaviors;"

# Integration tests
pytest tests/test_behavior_parity.py -v
```

### Rollback
```bash
# Switch to SQLite
source /etc/amprealize/sqlite.env
systemctl restart amprealize-api
```

---

## Appendix C: Migration Checklist Template

Copy this checklist for each migration execution:

```
Migration Date: ___________
Environment: [ ] Dev  [ ] Staging  [ ] Production
Services: [ ] BehaviorService  [ ] WorkflowService

Pre-Flight:
[ ] SQLite inventory captured
[ ] PostgreSQL connectivity verified
[ ] Backups created
[ ] Dry run successful

Execution:
[ ] Schema migration applied
[ ] Data migration completed
[ ] Row counts verified
[ ] Spot checks passed

Post-Migration:
[ ] Parity tests passing
[ ] Smoke tests passing
[ ] Performance baseline captured
[ ] Telemetry flowing

Rollback (if needed):
[ ] Rollback executed
[ ] Services operational on SQLite
[ ] Incident documented

Sign-off:
Engineer: _______________  Date: __________
DevOps:   _______________  Date: __________
```

---

**End of Playbook**

For questions or issues, consult:
- `scripts/_postgres_migration_utils.py` (helper functions)
- `tests/test_postgres_migration_utils.py` (validation examples)
- `BUILD_TIMELINE.md` #70-72-76 (migration tooling history)
