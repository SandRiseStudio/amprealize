# TimescaleDB + Metabase Connection Guide

> **Last Updated:** 2025-10-30
> **Status:** ✅ **COMPLETE** – Metabase successfully configured for TimescaleDB
> **Migration:** DuckDB → TimescaleDB (Migration 014)

## Quick Start

### 1. Start Infrastructure

```bash
# Start TimescaleDB (if not already running)
podman-compose -f docker-compose.postgres.yml up -d postgres-telemetry

# Start Metabase
podman-compose -f docker-compose.analytics-dashboard.yml up -d

# Verify both containers are healthy
podman ps --filter "name=postgres-telemetry" --filter "name=metabase"
```

### 2. Access Metabase

**URL:** http://localhost:3000

**Default Credentials:**
- Email: `admin@amprealize.local`
- Password: `changeme123`

⚠️ **Change password immediately after first login!**

### 3. Configure TimescaleDB Connection

1. **Go to:** Settings (⚙️) → Admin Settings → Databases → Add Database
2. **Configure:**
   - **Database type:** PostgreSQL
   - **Display name:** Amprealize Telemetry Warehouse (TimescaleDB)
   - **Host:** `postgres-telemetry`
   - **Port:** `5432`
   - **Database name:** `telemetry`
   - **Username:** `amprealize_telemetry`
   - **Password:** `dev_telemetry_pass`
   - **SSL:** ❌ (local dev only; enable for production)
   - **Read-only:** ✅ (recommended for analytics)
3. **Click:** Save
4. **Wait:** 30-60 seconds for schema sync

### 4. Verify Connection

**Test Query:**
```sql
SELECT
  event_type,
  COUNT(*) as count,
  MAX(event_timestamp) as latest
FROM telemetry_events
WHERE event_timestamp > NOW() - INTERVAL '7 days'
GROUP BY event_type
ORDER BY count DESC;
```

**Expected Result:** Rows showing event types (e.g., `behavior_usage`, `token_usage`, `run_completed`)

---

## Architecture

```
┌──────────────────────┐
│  Metabase            │  Port 3000
│  (amprealize-metabase)  │  Networks: amprealize-analytics
│                      │            amprealize_amprealize-postgres-net
└──────────┬───────────┘
           │
           │ PostgreSQL Protocol
           │ (postgres-telemetry:5432)
           ▼
┌──────────────────────┐
│  TimescaleDB 2.23.0  │  Port 5432
│  (postgres-telemetry)│  Database: telemetry
│                      │  User: amprealize_telemetry
└──────────────────────┘
```

### Network Configuration

- **Metabase Container:** `amprealize-metabase`
- **Networks:**
  - `amprealize-analytics` (internal Metabase network)
  - `amprealize_amprealize-postgres-net` (shared with postgres containers)
- **Connectivity:** Container-to-container via Docker/Podman DNS resolution

---

## Available Tables & Views

### Hypertables (Time-Series Partitioned)

| Table | Purpose | Partitioning | Compression |
|-------|---------|--------------|-------------|
| `telemetry_events` | Main event stream | 7-day chunks on `event_timestamp` | 7-day threshold |
| `execution_traces` | Distributed tracing spans | 7-day chunks on `span_start_time` | 7-day threshold |

### Continuous Aggregates (Pre-Computed Rollups)

| Aggregate | Granularity | Refresh Policy | Use Case |
|-----------|-------------|----------------|----------|
| `telemetry_hourly` | Hourly | 10 minutes | Real-time dashboards |
| `telemetry_daily` | Daily | 1 hour | Trend analysis |
| `telemetry_weekly` | Weekly | 1 day | Executive summaries |

### Helper Views

| View | Purpose |
|------|---------|
| `v_latest_events` | Last 1000 events (quick exploration) |
| `v_event_type_summary` | Event type distribution |
| `v_trace_overview` | Execution trace summaries |

---

## Example Queries

### Behavior Usage Trends (Last 30 Days)

```sql
SELECT
  DATE(event_timestamp) as date,
  event_data->>'behavior_id' as behavior_id,
  COUNT(*) as citations
FROM telemetry_events
WHERE event_type = 'behavior_usage'
  AND event_timestamp > NOW() - INTERVAL '30 days'
  AND event_data ? 'behavior_id'
GROUP BY DATE(event_timestamp), event_data->>'behavior_id'
ORDER BY date DESC, citations DESC;
```

### Token Savings Analysis

```sql
SELECT
  event_data->>'behavior_id' as behavior_id,
  SUM((event_data->>'tokens_saved')::int) as total_saved,
  SUM((event_data->>'tokens_baseline')::int) as baseline,
  ROUND(
    100.0 * SUM((event_data->>'tokens_saved')::int) /
    NULLIF(SUM((event_data->>'tokens_baseline')::int), 0),
    2
  ) as savings_pct
FROM telemetry_events
WHERE event_type = 'token_usage'
  AND event_timestamp > NOW() - INTERVAL '7 days'
  AND event_data ? 'tokens_saved'
GROUP BY event_data->>'behavior_id'
ORDER BY savings_pct DESC
LIMIT 20;
```

### PRD KPI Dashboard (Using Continuous Aggregates)

```sql
-- Hourly metrics for last 24 hours
SELECT
  bucket,
  event_count,
  avg_event_count,
  max_event_count
FROM telemetry_hourly
WHERE bucket > NOW() - INTERVAL '24 hours'
ORDER BY bucket DESC;
```

---

## Troubleshooting

### ❌ "Unable to connect to postgres-telemetry:5432"

**Cause:** Network configuration issue

**Solution:**
```bash
# 1. Verify network exists
podman network inspect amprealize_amprealize-postgres-net

# 2. Check postgres-telemetry is running
podman ps --filter "name=postgres-telemetry"

# 3. Test connectivity from Metabase container
podman exec amprealize-metabase nc -zv postgres-telemetry 5432

# 4. Recreate Metabase container
podman-compose -f docker-compose.analytics-dashboard.yml down
podman-compose -f docker-compose.analytics-dashboard.yml up -d
```

### ❌ Schema Sync Shows 0 Tables

**Cause:** Migration 014 not applied

**Solution:**
```bash
# Verify migration
podman exec -it amprealize-postgres-telemetry psql -U amprealize_telemetry -d telemetry -c "\dt"

# Should list: telemetry_events, execution_traces

# If missing, apply migration
podman exec -i amprealize-postgres-telemetry psql -U amprealize_telemetry -d telemetry < schema/migrations/014_upgrade_telemetry_to_timescale.sql
```

### ⚠️ Queries Return Empty Results

**Cause:** Data migration incomplete or date filters too narrow

**Solution:**
```bash
# Check row count
podman exec amprealize-postgres-telemetry psql -U amprealize_telemetry -d telemetry -c "SELECT COUNT(*) FROM telemetry_events;"

# Check date range
podman exec amprealize-postgres-telemetry psql -U amprealize_telemetry -d telemetry -c "SELECT MIN(event_timestamp), MAX(event_timestamp) FROM telemetry_events;"

# If needed, adjust dashboard date filters to include historical data
```

---

## Production Considerations

### Security

- [ ] **Change default password** for `admin@amprealize.local`
- [ ] **Enable SSL/TLS** for postgres-telemetry connection
- [ ] **Use secrets manager** for credentials (e.g., Vault, AWS Secrets Manager)
- [ ] **Configure read-only user** with limited privileges:
  ```sql
  CREATE USER metabase_readonly WITH PASSWORD 'SecurePassword!';
  GRANT CONNECT ON DATABASE telemetry TO metabase_readonly;
  GRANT USAGE ON SCHEMA public TO metabase_readonly;
  GRANT SELECT ON ALL TABLES IN SCHEMA public TO metabase_readonly;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO metabase_readonly;
  ```

### Performance

- [ ] **Enable query caching** in Metabase (Settings → Admin → Caching → Enable)
- [ ] **Use continuous aggregates** instead of raw hypertables for dashboards
- [ ] **Monitor query performance:**
  ```sql
  EXPLAIN ANALYZE
  SELECT * FROM telemetry_events WHERE event_timestamp > NOW() - INTERVAL '7 days';
  ```
- [ ] **Verify compression policies are active:**
  ```bash
  podman exec amprealize-postgres-telemetry psql -U amprealize_telemetry -d telemetry -c "SELECT * FROM timescaledb_information.jobs WHERE proc_name = 'policy_compression';"
  ```

### High Availability

- [ ] **Migrate Metabase metadata** from H2 to PostgreSQL:
  ```yaml
  environment:
    MB_DB_TYPE: postgres
    MB_DB_HOST: metabase-postgres.internal
    MB_DB_PORT: 5432
    MB_DB_NAME: metabase
    MB_DB_USER: metabase
    MB_DB_PASS: ${METABASE_DB_PASSWORD}
  ```
- [ ] **Set up TimescaleDB replication** (primary + replica)
- [ ] **Configure load balancer** (nginx/HAProxy) for Metabase

### Monitoring

- [ ] **Prometheus metrics endpoint:** `/api/health`
- [ ] **Grafana dashboard:** Import Metabase dashboard template
- [ ] **Alert rules:**
  - Metabase down (health check fails)
  - TimescaleDB connection failures
  - Query latency > 5s
  - Dashboard refresh errors

---

## Evidence & References

- **Migration:** `schema/migrations/014_upgrade_telemetry_to_timescale.sql`
- **Tests:** `tests/test_telemetry_warehouse_postgres.py` (19/19 passing)
- **Data Migration:** `scripts/migrate_telemetry_duckdb_to_postgres.py` (11 rows migrated)
- **Documentation:** `docs/analytics/metabase_setup.md` (updated 2025-10-30)
- **PRD Tracking:** `PRD_NEXT_STEPS.md` Phase 4.5 Item 1 (Telemetry warehouse hardening)

**Completion Date:** 2025-10-30
**Behaviors Applied:**
- `behavior_align_storage_layers` – Unified TimescaleDB schema
- `behavior_update_docs_after_changes` – Comprehensive documentation
- `behavior_lock_down_security_surface` – Security best practices documented
- `behavior_instrument_metrics_pipeline` – Dashboard query examples provided
