# Sprint 3 Streaming Dashboards Guide

> **Created:** 2025-11-03
> **Purpose:** Metabase dashboards for Sprint 3 high-volume streaming pipeline
> **Target:** 10,000 events/sec throughput, <30s end-to-end latency

---

## Overview

The Sprint 3 streaming dashboards provide real-time visibility into the Kafka → Flink → TimescaleDB pipeline, tracking both operational metrics (throughput, latency, errors) and PRD success metrics (behavior reuse, token savings, completion rate, compliance coverage).

**Dashboard Stack:**
- **Data Source:** TimescaleDB 2.23.0 (postgres-telemetry container)
- **Continuous Aggregates:** Hourly/daily rollups (10-minute refresh)
- **Visualization:** Metabase v0.48.0 (port 3000)
- **Creation:** Automated via `scripts/create_streaming_dashboards.py`

---

## Dashboard Catalog

### 1. Streaming Pipeline Health

**Purpose:** Monitor Kafka, Flink, and TimescaleDB throughput and resource utilization.

**Key Metrics:**
- **Events Per Minute:** Real-time event ingestion rate (target: 167 avg for 10k/sec peak)
- **Unique Actors:** Distinct users/agents generating events
- **Event Type Distribution:** Breakdown of event categories (pie chart)
- **Traffic by Surface:** CLI vs API vs MCP vs Web event volumes
- **P95 Latency by Operation:** Slowest operations (target: <30s = 30000ms)

**Use Cases:**
- Capacity planning: Is the pipeline handling target load?
- Bottleneck identification: Which operations exceed latency SLA?
- Surface adoption: Where is traffic coming from?

**Data Sources:**
- `telemetry_events_hourly` continuous aggregate (10-minute refresh)
- `execution_traces_hourly` continuous aggregate (10-minute refresh)

**Refresh Interval:** 10 minutes (automatic via TimescaleDB policy)

---

### 2. PRD Metrics Dashboard (Real-Time)

**Purpose:** Track the 4 PRD success metrics using continuous aggregates.

**Key Metrics:**
1. **Behavior Reuse Rate (Target: ≥70%)**
   - 7-day trend line showing behavior reuse percentage
   - Calculated from `behavior.*` event types vs total events

2. **Token Usage Trend**
   - Daily token consumption from `execution_traces_hourly`
   - Identifies token savings opportunities

3. **Completion Rate by Surface (Target: ≥80%)**
   - Run completion percentage: `run.completed / (run.started + run.completed + run.failed)`
   - Broken down by CLI, API, MCP, Web

4. **Run Volume (Hourly)**
   - Number of unique runs per hour
   - Correlates with adoption and usage patterns

**Use Cases:**
- Executive reporting: Are we meeting PRD targets?
- Surface comparison: Which interfaces have better completion rates?
- Trend analysis: Are metrics improving over time?

**Data Sources:**
- `telemetry_events_hourly` continuous aggregate
- `execution_traces_hourly` continuous aggregate

**Refresh Interval:** 10 minutes

---

### 3. Event Flow Analysis

**Purpose:** Deep-dive into end-to-end latency, checkpoint health, and backpressure indicators.

**Key Metrics:**
- **Trace Duration Distribution:** Latency buckets (<100ms, 100-500ms, 500ms-1s, 1-5s, 5-30s, >30s)
- **Trace Status Distribution:** Success vs error vs timeout
- **Service Performance:** P95 latency heatmap by service + operation
- **Token Consumption by Service:** Which services are most expensive?

**Use Cases:**
- Incident response: Which operations are failing?
- Performance optimization: Where should we optimize first?
- Cost management: Which services consume the most tokens?

**Data Sources:**
- `execution_traces_hourly` continuous aggregate

**Refresh Interval:** 10 minutes

---

### 4. Operational Observability

**Purpose:** Error tracking, retry patterns, and resource utilization for incident response.

**Key Metrics:**
- **Error Events (24h):** Count of `*.failed` and `*.error` events by type
- **Error Rate Trend:** Percentage of failed events over time
- **Activity by Role:** Event distribution across strategist/teacher/student/admin
- **Active Sessions:** Unique session count trend
- **High-Latency Operations:** Alert table for operations exceeding 5s P95

**Use Cases:**
- On-call response: What's currently failing?
- Error pattern analysis: Are errors increasing?
- Role-based analysis: Which agent roles are most active?

**Data Sources:**
- `telemetry_events_hourly` continuous aggregate
- `execution_traces_hourly` continuous aggregate

**Refresh Interval:** 10 minutes

---

## Setup Instructions

### Prerequisites

1. **TimescaleDB Running:**
   ```bash
   podman-compose -f docker-compose.postgres.yml up -d postgres-telemetry
   ```

2. **Migration 014 Applied:**
   ```bash
   podman exec -i amprealize-postgres-telemetry psql -U amprealize_telemetry -d telemetry \
     < schema/migrations/014_upgrade_telemetry_to_timescale.sql
   ```

3. **Metabase Running:**
   ```bash
   podman-compose -f docker-compose.analytics-dashboard.yml up -d metabase
   ```

4. **Metabase Database Connection Created:**
   - Navigate to http://localhost:3000/admin/databases/create
   - **Database type:** PostgreSQL
   - **Name:** Amprealize Telemetry (TimescaleDB)
   - **Host:** `amprealize-postgres-telemetry` (or `postgres-telemetry` depending on network setup)
   - **Port:** 5432
   - **Database name:** `telemetry`
   - **Username:** `amprealize_telemetry`
   - **Password:** `dev_telemetry_pass`
   - **Additional settings:** Leave defaults
   - **Save & Test Connection**

### Dashboard Creation

```bash
# Set Metabase credentials
export METABASE_URL="http://localhost:3000"
export METABASE_USERNAME="admin@amprealize.local"
export METABASE_PASSWORD="changeme123"  # Or your configured password

# Create all 4 dashboards
python scripts/create_streaming_dashboards.py
```

**Expected Output:**
```
==================================================================
Sprint 3 Streaming Dashboards Creator
==================================================================
Metabase URL: http://localhost:3000
Username: admin@amprealize.local

✅ Authenticated to Metabase
✅ Found telemetry database (ID: 2)

📊 Creating Dashboard #1: Streaming Pipeline Health...
  ✅ Created card: Events Per Minute (Real-Time)
  ✅ Created card: Unique Actors per Hour
  ✅ Created card: Event Type Distribution
  ✅ Created card: Traffic by Surface
  ✅ Created card: P95 Latency by Operation
✅ Dashboard #1 created with 5 cards

📊 Creating Dashboard #2: PRD Metrics (Real-Time)...
  ✅ Created card: Behavior Reuse Trend
  ✅ Created card: Token Usage Trend
  ✅ Created card: Completion Rate by Surface
  ✅ Created card: Recent Run Volume
✅ Dashboard #2 created with 4 cards

📊 Creating Dashboard #3: Event Flow Analysis...
  ✅ Created card: Trace Duration Distribution
  ✅ Created card: Trace Status Distribution
  ✅ Created card: Service Performance (P95 Latency)
  ✅ Created card: Token Consumption by Service
✅ Dashboard #3 created with 4 cards

📊 Creating Dashboard #4: Operational Observability...
  ✅ Created card: Error Events (24h)
  ✅ Created card: Error Rate Trend
  ✅ Created card: Activity by Role
  ✅ Created card: Active Sessions
  ✅ Created card: High-Latency Operations (>5s)
✅ Dashboard #4 created with 5 cards

==================================================================
✅ All Sprint 3 Streaming Dashboards Created Successfully!
==================================================================

📊 Dashboards created: 4

🔗 Access dashboards at: http://localhost:3000/collection/root

Dashboard URLs:
  1. http://localhost:3000/dashboard/18
  2. http://localhost:3000/dashboard/19
  3. http://localhost:3000/dashboard/20
  4. http://localhost:3000/dashboard/21
```

### Verification

1. **Open Metabase:** http://localhost:3000
2. **Navigate to Dashboards:** Click "Browse Data" → "Our analytics"
3. **Verify Dashboards:** All 4 dashboards should be visible
4. **Check Data:** Some dashboards may show "No results" until telemetry flows

---

## Generating Sample Data

If dashboards show "No results", generate sample telemetry:

```bash
# Start streaming pipeline
./scripts/start_streaming_pipeline.sh start

# Deploy Flink KPI projection job (production mode)
podman exec -it amprealize-flink-jobmanager python /opt/flink/jobs/telemetry_kpi_job.py \
  --mode prod \
  --kafka-servers kafka-1:9092,kafka-2:9092,kafka-3:9092 \
  --postgres-dsn "postgresql://amprealize_telemetry:dev_telemetry_pass@postgres-telemetry:5432/telemetry"

# Generate test events via CLI
amprealize telemetry emit \
  --event-type "behavior.retrieved" \
  --actor-id "test-user" \
  --actor-role "strategist" \
  --actor-surface "cli" \
  --payload '{"behavior_name": "test_behavior", "score": 0.95}'

# Or use the seed script (creates 200 runs with telemetry)
python scripts/seed_telemetry_data.py --runs 200
```

**Wait 10-15 minutes** for continuous aggregates to refresh, then reload dashboards.

---

## Dashboard Maintenance

### Refresh Schedule

Continuous aggregates refresh every 10 minutes automatically via TimescaleDB policies:

```sql
-- Verify refresh policies
SELECT application_name, schedule_interval
FROM timescaledb_information.jobs
WHERE proc_name = 'policy_refresh_continuous_aggregate';

-- Expected output:
-- telemetry_events_hourly: 10 minutes
-- execution_traces_hourly: 10 minutes
-- telemetry_events_daily: 1 hour
```

### Manual Refresh

Force immediate refresh if needed:

```sql
-- Connect to TimescaleDB
podman exec -it amprealize-postgres-telemetry psql -U amprealize_telemetry -d telemetry

-- Refresh specific continuous aggregate
CALL refresh_continuous_aggregate('telemetry_events_hourly', NULL, NULL);
CALL refresh_continuous_aggregate('execution_traces_hourly', NULL, NULL);
```

### Dashboard Export/Backup

```bash
# Export dashboards via Metabase API
curl -X GET "http://localhost:3000/api/dashboard/18" \
  -H "X-Metabase-Session: YOUR_SESSION_TOKEN" \
  > docs/analytics/dashboard-exports/streaming-pipeline-health.json

# Repeat for dashboards 19, 20, 21
```

---

## Troubleshooting

### Dashboard Shows "No Results"

**Cause:** No telemetry data in TimescaleDB.

**Solution:**
1. Verify postgres-telemetry is running: `podman ps | grep postgres-telemetry`
2. Check for events: `podman exec -it amprealize-postgres-telemetry psql -U amprealize_telemetry -d telemetry -c "SELECT COUNT(*) FROM telemetry_events;"`
3. Generate sample data: `python scripts/seed_telemetry_data.py --runs 50`
4. Wait 10 minutes for continuous aggregate refresh

### Dashboard Shows "Database Connection Error"

**Cause:** Metabase cannot reach postgres-telemetry container.

**Solution:**
1. Verify network: `podman network inspect amprealize_amprealize-postgres-net`
2. Test connection: `podman exec -it amprealize-metabase ping postgres-telemetry`
3. Update database connection in Metabase admin panel with correct host

### Continuous Aggregate Not Updating

**Cause:** TimescaleDB background jobs paused or failing.

**Solution:**
```sql
-- Check job status
SELECT * FROM timescaledb_information.job_stats
WHERE job_id IN (SELECT job_id FROM timescaledb_information.continuous_aggregates);

-- If job failed, check logs
podman logs amprealize-postgres-telemetry | grep "continuous aggregate"

-- Restart background jobs
SELECT alter_job(<job_id>, scheduled => true);
```

### High Dashboard Latency

**Cause:** Queries scanning too much data.

**Solution:**
1. Add time filters to dashboard cards (e.g., `WHERE bucket >= NOW() - INTERVAL '7 days'`)
2. Ensure continuous aggregate refresh is working (check `timescaledb_information.continuous_aggregate_stats`)
3. Monitor compression policy: `SELECT * FROM timescaledb_information.chunks WHERE is_compressed = false;`

---

## Performance Optimization

### Query Optimization

All dashboard queries are optimized to use continuous aggregates:

```sql
-- ✅ Good: Uses continuous aggregate (fast)
SELECT bucket, SUM(event_count) FROM telemetry_events_hourly WHERE bucket >= NOW() - INTERVAL '24 hours' GROUP BY bucket;

-- ❌ Bad: Scans raw hypertable (slow)
SELECT DATE_TRUNC('hour', event_timestamp), COUNT(*) FROM telemetry_events WHERE event_timestamp >= NOW() - INTERVAL '24 hours' GROUP BY 1;
```

### Continuous Aggregate Tuning

Adjust refresh intervals based on dashboard usage:

```sql
-- More frequent refresh (5 minutes) for real-time dashboards
SELECT alter_job(
    (SELECT job_id FROM timescaledb_information.jobs WHERE proc_name = 'policy_refresh_continuous_aggregate' AND application_name = 'telemetry_events_hourly'),
    schedule_interval => INTERVAL '5 minutes'
);

-- Less frequent refresh (1 hour) for historical dashboards
SELECT alter_job(
    (SELECT job_id FROM timescaledb_information.jobs WHERE proc_name = 'policy_refresh_continuous_aggregate' AND application_name = 'telemetry_events_daily'),
    schedule_interval => INTERVAL '1 hour'
);
```

---

## References

- **Architecture:** `docs/STREAMING_PIPELINE_ARCHITECTURE.md`
- **TimescaleDB Migration:** `schema/migrations/014_upgrade_telemetry_to_timescale.sql`
- **Metabase Setup:** `docs/analytics/metabase_setup.md`
- **Podman Deployment:** `docs/PODMAN_DEPLOYMENT.md`
- **PRD Metrics:** `PRD.md` (Sprint 3 success criteria)
- **Behavior:** `behavior_instrument_metrics_pipeline` (AGENTS.md)

---

**Next Steps:**
1. ✅ Dashboards created
2. ⏸️ Generate sample telemetry data
3. ⏸️ Validate dashboard queries return results
4. ⏸️ Configure refresh intervals for production
5. ⏸️ Set up alerting for SLA violations (Metabase Pulse or Grafana)
