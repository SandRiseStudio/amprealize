# Metabase Analytics Dashboard Setup

> **Purpose:** Deploy and configure Metabase for Amprealize PRD metrics visualization
> **Owner:** Product Analytics + Engineering
> **Last Updated:** 2025-10-30
> **Database:** TimescaleDB 2.23.0 (postgres-telemetry container)

---

## ⚠️ **Migration Notice (2025-10-30)**

**The telemetry warehouse has migrated from DuckDB to TimescaleDB.** This document has been updated to reflect the new connection process.

**Key Changes:**
- ✅ **Database:** DuckDB → TimescaleDB 2.23.0 (PostgreSQL 16)
- ✅ **Connection:** File mount → Network connection to `postgres-telemetry` container
- ✅ **Schema:** Migration 014 executed (2 hypertables, compression, retention policies)
- ✅ **Data:** 11 rows migrated from DuckDB (100% integrity verified)
- 📋 **Dashboard Queries:** Updated for TimescaleDB schema (see [Dashboard Query Migration](#dashboard-query-migration))
- ✅ **Sprint 3:** High-volume streaming dashboards created (see `docs/analytics/STREAMING_DASHBOARDS.md`)

**For DuckDB setup (legacy), see:** [Historical DuckDB Setup (Archive)](#historical-duckdb-setup-archive)

---

## Overview

Metabase is the visualization layer for Amprealize's analytics infrastructure, connecting to the TimescaleDB telemetry warehouse to provide interactive dashboards tracking the four PRD success metrics:

1. **Behavior Reuse Rate** (target: ≥70%)
2. **Token Savings Rate** (target: ≥30%)
3. **Task Completion Rate** (target: ≥80%)
4. **Compliance Coverage Rate** (target: ≥95%)

## Architecture

```
┌─────────────┐      ┌──────────────────┐      ┌────────────────┐
│ Telemetry   │─────▶│ TimescaleDB      │◀────▶│ Metabase       │
│ Events      │      │ (postgres-       │      │ (Port 3000)    │
│ (Kafka/API) │      │  telemetry)      │      │                │
└─────────────┘      └──────────────────┘      └────────────────┘
                            │
                            ▼
                     ┌──────────────────┐
                     │ 2 Hypertables    │
                     │ • telemetry_     │
                     │   events         │
                     │ • execution_     │
                     │   traces         │
                     │                  │
                     │ 3 Continuous     │
                     │ Aggregates       │
                     │ • hourly/daily/  │
                     │   weekly rollups │
                     └──────────────────┘
```

**Key Components:**
- **TimescaleDB Container:** `amprealize-postgres-telemetry` (port 5432)
- **Database:** `telemetry`
- **User:** `amprealize_telemetry` / `dev_telemetry_pass`
- **Compression:** 7-day threshold, automatic background jobs
- **Retention:** 90-day hot storage (configurable)

## Quick Start (Local Development)

### Prerequisites

1. **Start TimescaleDB container:**
   ```bash
   # Ensure Podman machine is running
   podman machine start

   # Start postgres-telemetry container
   podman-compose -f docker-compose.postgres.yml up -d postgres-telemetry

   # Verify container health
   podman ps --filter "name=postgres-telemetry"
   # Should show: Up X hours (healthy)
   ```

2. **Verify migration 014 is applied:**
   ```bash
   podman exec -it amprealize-postgres-telemetry psql -U amprealize_telemetry -d telemetry -c "\d telemetry_events"
   # Should show hypertable with event_id, event_timestamp composite primary key
   ```

### 1. Start Metabase

```bash
# From repository root
podman-compose -f docker-compose.analytics-dashboard.yml up -d

# Check logs
podman-compose -f docker-compose.analytics-dashboard.yml logs -f metabase

# Wait for "Metabase Initialization COMPLETE" (30-60 seconds)
```

**Note:** The updated `docker-compose.analytics-dashboard.yml` connects Metabase to the `amprealize-postgres-net` network, allowing direct communication with `postgres-telemetry` container.

### 2. Access Web Interface

Open browser: **http://localhost:3000**

**Default Credentials:**
- Email: `admin@amprealize.local`
- Password: `changeme123`

⚠️ **Change password immediately after first login!**

### 3. Connect to TimescaleDB Telemetry Warehouse

**New Process (TimescaleDB):** Metabase connects directly via PostgreSQL protocol—no export scripts needed!

#### Configure Database Connection

1. Go to **Settings** (gear icon) → **Admin Settings** → **Databases** → **Add Database**
2. Configure:
   - **Database type:** PostgreSQL
   - **Display name:** Amprealize Telemetry Warehouse (TimescaleDB)
   - **Host:** `postgres-telemetry` (container hostname on shared network)
   - **Port:** `5432`
   - **Database name:** `telemetry`
   - **Username:** `amprealize_telemetry`
   - **Password:** `dev_telemetry_pass`
   - **Advanced options:**
     - Use a secure connection (SSL): ❌ (local dev only)
     - Read-only: ✅ (recommended for analytics)
     - Rerun queries for simple exploration: ✅
     - Choose when Metabase syncs: Daily at midnight
3. Click **Save**
4. Wait for schema sync (should detect 2 hypertables + 3 continuous aggregates + 3 helper views)

**Available Tables & Views:**
- `telemetry_events` - **Hypertable** (time-series partitioned on `event_timestamp`)
- `execution_traces` - **Hypertable** (distributed tracing spans)
- `telemetry_hourly` - Continuous aggregate (hourly rollups, 10-min refresh)
- `telemetry_daily` - Continuous aggregate (daily rollups, 1-hour refresh)
- `telemetry_weekly` - Continuous aggregate (weekly rollups, 1-day refresh)
- `v_latest_events` - Helper view (last 1000 events)
- `v_event_type_summary` - Helper view (event type counts)
- `v_trace_overview` - Helper view (execution trace summaries)

**Connection Test Query:**
```sql
SELECT
  event_type,
  COUNT(*) as event_count,
  MAX(event_timestamp) as latest_event
FROM telemetry_events
WHERE event_timestamp > NOW() - INTERVAL '7 days'
GROUP BY event_type
ORDER BY event_count DESC;
```
---

## Dashboard Query Migration

**Goal:** Update existing dashboard queries from DuckDB/SQLite schema to TimescaleDB schema.

### Schema Mapping

| DuckDB/SQLite Table | TimescaleDB Equivalent | Notes |
|---------------------|------------------------|-------|
| `fact_behavior_usage` | `telemetry_events` WHERE `event_type = 'behavior_usage'` | Parse `event_data` JSONB for behavior_id |
| `fact_token_savings` | `telemetry_events` WHERE `event_type = 'token_usage'` | Parse `event_data` for token counts |
| `fact_execution_status` | `telemetry_events` WHERE `event_type = 'run_completed'` | Parse `event_data` for status |
| `fact_compliance_steps` | `telemetry_events` WHERE `event_type = 'compliance_check'` | Parse `event_data` for checklist steps |
| `view_*` (KPI aggregates) | Use continuous aggregates or custom queries | See examples below |

### Example Query Migrations

#### Before (DuckDB/SQLite):
```sql
-- Behavior reuse rate (last 30 days)
SELECT
  DATE(run_timestamp) as date,
  AVG(reuse_rate) as avg_reuse_rate
FROM view_behavior_reuse_rate
WHERE run_timestamp > CURRENT_DATE - INTERVAL '30 days'
GROUP BY DATE(run_timestamp)
ORDER BY date DESC;
```

#### After (TimescaleDB):
```sql
-- Behavior reuse rate (last 30 days) using telemetry_daily aggregate
SELECT
  bucket as date,
  (total_behavior_citations::float / NULLIF(total_runs, 0)) * 100 as avg_reuse_rate
FROM telemetry_daily
WHERE bucket > NOW() - INTERVAL '30 days'
  AND event_type = 'behavior_usage'
GROUP BY bucket
ORDER BY bucket DESC;
```

#### Token Savings Query (TimescaleDB):
```sql
-- Token savings % by behavior_id
SELECT
  event_data->>'behavior_id' as behavior_id,
  SUM((event_data->>'tokens_saved')::int) as total_tokens_saved,
  SUM((event_data->>'tokens_baseline')::int) as total_tokens_baseline,
  (SUM((event_data->>'tokens_saved')::int)::float /
   NULLIF(SUM((event_data->>'tokens_baseline')::int), 0)) * 100 as savings_pct
FROM telemetry_events
WHERE event_type = 'token_usage'
  AND event_timestamp > NOW() - INTERVAL '7 days'
  AND event_data ? 'behavior_id'
GROUP BY event_data->>'behavior_id'
ORDER BY savings_pct DESC
LIMIT 20;
```

### Dashboard Update Checklist

For each dashboard in `docs/analytics/dashboard-exports/`:

- [ ] **prd_kpi_summary.json**
  - [ ] Update behavior reuse rate query
  - [ ] Update token savings rate query
  - [ ] Update completion rate query
  - [ ] Update compliance coverage query
  - [ ] Test all filters (date range, run_id, agent_id)

- [ ] **behavior_usage_trends.json**
  - [ ] Replace fact_behavior_usage references with telemetry_events
  - [ ] Update time-series aggregation to use telemetry_hourly/daily
  - [ ] Verify behavior_id extraction from JSONB event_data

- [ ] **token_savings_analysis.json**
  - [ ] Replace fact_token_savings with telemetry_events
  - [ ] Update token_saved/token_baseline calculations
  - [ ] Add baseline vs. actual comparison charts

- [ ] **compliance_coverage_breakdown.json**
  - [ ] Replace fact_compliance_steps with telemetry_events
  - [ ] Update checklist step parsing from event_data
  - [ ] Verify coverage % formula matches PRD target (95%)

**Status:** 🚧 **TODO** – Dashboard queries pending migration (estimated 2-3 hours)

---

## Sprint 3 Streaming Dashboards (NEW)

**Purpose:** Real-time monitoring for the high-volume Kafka → Flink → TimescaleDB streaming pipeline.

**Target:** 10,000 events/sec throughput, <30s end-to-end latency.

### Quick Setup

```bash
# Ensure streaming infrastructure is running
./scripts/start_streaming_pipeline.sh start

# Create streaming-specific dashboards (4 dashboards, 18 cards)
export METABASE_URL="http://localhost:3000"
export METABASE_USERNAME="admin@amprealize.local"
export METABASE_PASSWORD="changeme123"
python scripts/create_streaming_dashboards.py
```

**Dashboards Created:**
1. **Streaming Pipeline Health** (5 cards): Events/min, unique actors, event type distribution, surface distribution, P95 latency
2. **PRD Metrics Real-Time** (4 cards): Behavior reuse trend, token usage, completion rate by surface, run volume
3. **Event Flow Analysis** (4 cards): Trace duration buckets, status distribution, service performance, token consumption
4. **Operational Observability** (5 cards): Error events, error rate trend, activity by role, sessions, high-latency alerts

**Data Sources:** TimescaleDB continuous aggregates (`telemetry_events_hourly`, `execution_traces_hourly`, `telemetry_events_daily`) with 10-minute refresh policies.

**Access:**
- Dashboard URLs: http://localhost:3000/dashboard/18-21 (adjust IDs based on creation order)
- Collection: "Sprint 3 Streaming Dashboards"

**Full Guide:** See `docs/analytics/STREAMING_DASHBOARDS.md` for detailed metric descriptions, troubleshooting, and optimization tips.

---

### 4. Import Dashboard Definitions

1. Go to **Collections** → **New Collection** → Name: "PRD Metrics"
2. For each JSON file in `docs/analytics/dashboard-exports/`:
   - Click **+** → **Dashboard** → **Import**
   - Upload JSON file
   - Verify queries execute successfully
3. Pin primary dashboard to homepage

**Available Dashboards:**
- `prd_kpi_summary.json` – Executive overview (all 4 metrics)
- `behavior_usage_trends.json` – Time series of behavior citations
- `token_savings_analysis.json` – Efficiency tracking over time
- `compliance_coverage_breakdown.json` – Checklist completion heatmap

### 5. Verify Data

Navigate to each dashboard and confirm:
- ✅ Queries return data (not empty state)
- ✅ Metrics match REST API values (`curl http://localhost:8000/v1/analytics/kpi-summary`)
- ✅ Date filters work correctly
- ✅ Drill-down links navigate properly

## Configuration Reference

### Environment Variables

Customize via `.env` file or export before `docker-compose up`:

```bash
# Admin account (first-time setup only)
export MB_ADMIN_EMAIL="your-email@company.com"
export MB_ADMIN_PASSWORD="SecurePassword123!"
export MB_ADMIN_FIRST_NAME="Your"
export MB_ADMIN_LAST_NAME="Name"

# Site configuration
export MB_SITE_NAME="Amprealize Analytics"
export MB_SITE_URL="https://analytics.amprealize.company.com"
export MB_TIMEZONE="America/New_York"

# Application database (production: use Postgres)
export MB_DB_TYPE="postgres"
export MB_DB_HOST="postgres.internal"
export MB_DB_PORT="5432"
export MB_DB_NAME="metabase"
export MB_DB_USER="metabase"
export MB_DB_PASS="SecureDBPassword!"

# Email (for alerts and subscriptions)
export MB_EMAIL_SMTP_HOST="smtp.sendgrid.net"
export MB_EMAIL_SMTP_PORT="587"
export MB_EMAIL_SMTP_USERNAME="apikey"
export MB_EMAIL_SMTP_PASSWORD="SG.xxxxx"
export MB_EMAIL_FROM_ADDRESS="noreply@amprealize.company.com"
```

### Volume Mounts

```yaml
volumes:
  # Metabase app database (H2/Postgres metadata)
  - metabase-data:/metabase-data

  # DuckDB warehouse (READ-ONLY to prevent corruption)
  - ./data/telemetry.duckdb:/duckdb/telemetry.duckdb:ro

  # Dashboard exports (backup/restore)
  - ./docs/analytics/dashboard-exports:/dashboard-exports:ro
```

## Dashboard Queries

Each dashboard executes SQL against the DuckDB warehouse. Example queries:

### KPI Summary (Last 30 Days)

```sql
SELECT
  snapshot_time,
  behavior_reuse_pct,
  average_token_savings_pct,
  task_completion_rate_pct,
  average_compliance_coverage_pct,
  total_runs,
  completed_runs,
  failed_runs
FROM main.view_kpi_summary
WHERE snapshot_time >= CURRENT_DATE - INTERVAL '30 days'
ORDER BY snapshot_time DESC
LIMIT 1;
```

### Behavior Usage Trends (Time Series)

```sql
SELECT
  DATE_TRUNC('day', execution_timestamp) AS date,
  COUNT(DISTINCT run_id) AS total_runs,
  SUM(behavior_count) AS total_behaviors_cited,
  AVG(behavior_count) AS avg_behaviors_per_run,
  COUNT(DISTINCT UNNEST(behavior_ids)) AS unique_behaviors
FROM main.fact_behavior_usage
WHERE execution_timestamp >= {{start_date}}
  AND execution_timestamp < {{end_date}}
GROUP BY date
ORDER BY date;
```

### Token Savings Distribution

```sql
SELECT
  CASE
    WHEN token_savings_pct >= 0.5 THEN '50%+'
    WHEN token_savings_pct >= 0.3 THEN '30-50%'
    WHEN token_savings_pct >= 0.1 THEN '10-30%'
    ELSE '<10%'
  END AS savings_bucket,
  COUNT(*) AS run_count,
  AVG(token_savings_pct) * 100 AS avg_savings_pct
FROM main.fact_token_savings
WHERE execution_timestamp >= {{start_date}}
GROUP BY savings_bucket
ORDER BY savings_bucket DESC;
```

### Compliance Coverage by Checklist

```sql
SELECT
  checklist_id,
  template_id,
  AVG(coverage_score) AS avg_coverage,
  COUNT(*) AS execution_count,
  SUM(CASE WHEN all_steps_complete THEN 1 ELSE 0 END) AS fully_complete_count
FROM main.fact_compliance_steps
WHERE execution_timestamp >= {{start_date}}
GROUP BY checklist_id, template_id
ORDER BY avg_coverage DESC;
```

## Production Deployment

### Prerequisites

- [ ] Provision Postgres database for Metabase application metadata
- [ ] Configure TLS certificates for HTTPS
- [ ] Set up reverse proxy (nginx/Traefik) with rate limiting
- [ ] Provision persistent volume for DuckDB warehouse (if using network storage)
- [ ] Configure SSO/SAML authentication (Metabase Enterprise)
- [ ] Set up backup strategy for Metabase metadata

### Deployment Steps

1. **Update `docker-compose.analytics-dashboard.yml` for production:**

```yaml
services:
  metabase:
    environment:
      # Use Postgres for app DB
      MB_DB_TYPE: postgres
      MB_DB_HOST: ${POSTGRES_HOST}
      MB_DB_PORT: ${POSTGRES_PORT}
      MB_DB_NAME: ${POSTGRES_DB}
      MB_DB_USER: ${POSTGRES_USER}
      MB_DB_PASS: ${POSTGRES_PASSWORD}

      # Production site URL
      MB_SITE_URL: https://analytics.amprealize.company.com

      # Email configuration
      MB_EMAIL_SMTP_HOST: ${SMTP_HOST}
      MB_EMAIL_SMTP_PORT: ${SMTP_PORT}
      MB_EMAIL_SMTP_USERNAME: ${SMTP_USER}
      MB_EMAIL_SMTP_PASSWORD: ${SMTP_PASS}

      # SAML SSO (Enterprise)
      MB_SAML_ENABLED: true
      MB_SAML_IDP_URI: ${SAML_IDP_URI}
      MB_SAML_IDP_CERT: ${SAML_IDP_CERT}
```

2. **Set up nginx reverse proxy:**

```nginx
server {
    listen 443 ssl http2;
    server_name analytics.amprealize.company.com;

    ssl_certificate /etc/ssl/certs/analytics.crt;
    ssl_certificate_key /etc/ssl/private/analytics.key;

    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

3. **Deploy and validate:**

```bash
# Load secrets from vault
export $(cat .env.production | xargs)

# Start services
docker-compose -f docker-compose.analytics-dashboard.yml up -d

# Check health
curl -f https://analytics.amprealize.company.com/api/health

# Monitor logs
docker-compose -f docker-compose.analytics-dashboard.yml logs -f
```

4. **Configure monitoring:**

```yaml
# Add to prometheus.yml
scrape_configs:
  - job_name: 'metabase'
    static_configs:
      - targets: ['localhost:3000']
    metrics_path: '/api/health'
```

## Maintenance

### Backup Metabase Configuration

```bash
# Export all dashboards/questions
podman exec amprealize-metabase \
  java -jar /app/metabase.jar export \
  /backup/metabase-$(date +%Y%m%d).dump

# Copy to safe location
podman cp amprealize-metabase:/backup/metabase-20251020.dump \
  ./backups/
```

### Update Metabase Version

```bash
# Stop current instance
podman-compose -f docker-compose.analytics-dashboard.yml down

# Update image tag in docker-compose.analytics-dashboard.yml
# metabase/metabase:v0.48.0 → v0.49.0

# Restart with new version
podman-compose -f docker-compose.analytics-dashboard.yml up -d

# Verify upgrade
podman-compose -f docker-compose.analytics-dashboard.yml logs metabase
```

### Refresh DuckDB Connection

If warehouse schema changes:

1. Go to **Admin** → **Databases** → **Amprealize Analytics Warehouse**
2. Click **Sync database schema now**
3. Wait for completion (~10 seconds)
4. Verify new tables/views appear in **Data Model**

## Troubleshooting

### Metabase won't start

```bash
# Check logs
podman-compose -f docker-compose.analytics-dashboard.yml logs metabase

# Common issues:
# - Podman machine not running → podman machine start
# - Port 3000 already in use → change ports: "3001:3000"
# - Insufficient memory → increase JAVA_OPTS: "-Xmx2g"
# - Corrupted H2 database → delete volume: podman volume rm amprealize_metabase-data
```

### Can't connect to DuckDB

```bash
# Verify file exists and is readable
podman exec amprealize-metabase ls -lh /duckdb/telemetry.duckdb

# Test query directly
podman exec amprealize-metabase \
  sqlite3 /duckdb/telemetry.duckdb \
  "SELECT COUNT(*) FROM main.fact_behavior_usage;"

# If not found, check volume mount in docker-compose.analytics-dashboard.yml
```

### Dashboards show "No results"

```bash
# Verify warehouse has data
python -c "import duckdb; conn = duckdb.connect('data/telemetry.duckdb'); print(conn.execute('SELECT COUNT(*) FROM main.fact_behavior_usage').fetchone())"

# Check date filters (may be filtering out all data)
# Adjust dashboard date range to "All Time"

# Verify SQL syntax compatibility
# DuckDB uses slightly different syntax than SQLite
```

### Queries are slow

```bash
# Add indexes to DuckDB warehouse
python -c "
import duckdb
conn = duckdb.connect('data/telemetry.duckdb')
conn.execute('CREATE INDEX IF NOT EXISTS idx_behavior_usage_timestamp ON main.fact_behavior_usage(execution_timestamp);')
conn.execute('CREATE INDEX IF NOT EXISTS idx_token_savings_timestamp ON main.fact_token_savings(execution_timestamp);')
conn.close()
"

# Increase Metabase memory
# Edit docker-compose.yml: JAVA_OPTS: "-Xmx2g -Xms1g"
```

## Security Considerations

- [ ] Change default admin password immediately
- [ ] Enable HTTPS for production deployments
- [ ] Configure firewall rules (allow only internal network)
- [ ] Mount DuckDB warehouse as read-only (`:ro` flag)
- [ ] Use secrets manager for credentials (avoid .env files in production)
- [ ] Enable audit logging in Metabase Enterprise
- [ ] Configure row-level permissions if multi-tenant
- [ ] Regularly update Metabase image for security patches

## Resources

- **Metabase Documentation:** https://www.metabase.com/docs/latest/
- **DuckDB SQL Reference:** https://duckdb.org/docs/sql/introduction
- **Podman Setup Guide:** `deployment/PODMAN.md`
- **Container Comparison:** `deployment/CONTAINER_COMPARISON.md`
- **PRD Metrics Schema:** `docs/analytics/prd_metrics_schema.sql`
- **Warehouse Client:** `amprealize/analytics/warehouse.py`
- **REST API Endpoints:** http://localhost:8000/v1/analytics/*

## Referenced Behaviors

- `behavior_orchestrate_cicd` – Docker Compose configuration and deployment
- `behavior_externalize_configuration` – Environment variables and secrets management
- `behavior_instrument_metrics_pipeline` – Dashboard queries wired to warehouse
- `behavior_update_docs_after_changes` – Documentation and runbook maintenance
- `behavior_lock_down_security_surface` – Security checklist and production hardening

---

**Next Steps:**
1. ✅ Deploy Metabase locally and test DuckDB connection
2. ⏳ Author dashboard JSON exports for 4 PRD metrics
3. ⏳ Provision production Postgres for Metabase metadata
4. ⏳ Configure SSO/SAML authentication (if Enterprise)
5. ⏳ Set up alerting and scheduled email reports

---

## Additional Troubleshooting (TimescaleDB)

### Metabase Can't Connect to TimescaleDB

**Symptom:** "Unable to connect to postgres-telemetry:5432"

**Solutions:**

1. **Verify container network:**
   ```bash
   podman network inspect amprealize-postgres-net
   # Should list both postgres-telemetry and amprealize-metabase containers
   ```

2. **Check postgres-telemetry is running:**
   ```bash
   podman ps --filter "name=postgres-telemetry"
   # Should show: Up X hours (healthy)
   ```

3. **Test connection from Metabase container:**
   ```bash
   podman exec -it amprealize-metabase sh
   apk add --no-cache postgresql-client
   psql -h postgres-telemetry -U amprealize_telemetry -d telemetry -c "SELECT version();"
   # Should return PostgreSQL + TimescaleDB version
   exit
   ```

4. **Recreate Metabase with network access:**
   ```bash
   podman-compose -f docker-compose.analytics-dashboard.yml down
   podman-compose -f docker-compose.analytics-dashboard.yml up -d
   ```

### Schema Sync Shows 0 Tables

**Symptom:** Metabase connects successfully but shows no tables/views

**Solutions:**

1. **Verify migration 014 is applied:**
   ```bash
   podman exec -it amprealize-postgres-telemetry psql -U amprealize_telemetry -d telemetry -c "\dt"
   # Should list: telemetry_events, execution_traces
   ```

2. **Force schema re-sync in Metabase:**
   - Settings → Admin → Databases → Amprealize Telemetry Warehouse
   - Click "Sync database schema now"
   - Wait 30-60 seconds

### Performance: Queries are Slow

**Solution:** Use continuous aggregates (telemetry_daily, telemetry_hourly) instead of raw hypertables for dashboard queries.

---

## Historical DuckDB Setup (Archive)

<details>
<summary><b>⚠️ Legacy Documentation (Pre-2025-10-30)</b> – Click to expand</summary>

**Note:** The telemetry warehouse migrated from DuckDB to TimescaleDB on 2025-10-30. This section is preserved for historical reference only.

For DuckDB setup instructions, see git history at commit prior to migration 014.

</details>
