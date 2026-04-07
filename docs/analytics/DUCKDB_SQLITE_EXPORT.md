# DuckDB to SQLite Export for Metabase

## Problem

Metabase's SQLite driver cannot directly read DuckDB files because DuckDB uses its own proprietary file format that is **not** SQLite-compatible, despite both being embedded databases.

**Error:** "Failed to connect to Database" when trying to use `/duckdb/telemetry.duckdb` with SQLite driver.

## Solution

Export DuckDB analytics data to SQLite format that Metabase can read.

### Quick Fix

```bash
# 1. Export DuckDB to SQLite
python scripts/export_duckdb_to_sqlite.py

# 2. Restart Metabase (if needed)
podman-compose -f docker-compose.analytics-dashboard.yml restart metabase

# 3. In Metabase, add database:
#    - Type: SQLite
#    - Filename: /duckdb/telemetry_sqlite.db
```

### What the Export Script Does

`scripts/export_duckdb_to_sqlite.py`:
- Reads all tables/views from DuckDB warehouse (`data/telemetry.duckdb`)
- Converts DuckDB-specific types to SQLite equivalents:
  - `BIGINT` → `INTEGER`
  - `DOUBLE` → `REAL`
  - `VARCHAR[]` (arrays) → `TEXT` (JSON strings)
  - `TIMESTAMP WITH TIME ZONE` → `TEXT`
- Creates SQLite database (`data/telemetry_sqlite.db`)
- Adds performance indexes
- **Output:** SQLite file mounted at `/duckdb/telemetry_sqlite.db` in container

### Exported Tables

✅ **8 tables/views available in Metabase:**

**Fact Tables (raw data):**
- `fact_behavior_usage` - Behavior citations per run
- `fact_token_savings` - Token efficiency metrics
- `fact_execution_status` - Run completion status
- `fact_compliance_steps` - Checklist execution records

**KPI Views (aggregated metrics):**
- `view_behavior_reuse_rate` - PRD metric: behavior reuse %
- `view_token_savings_rate` - PRD metric: token savings %
- `view_completion_rate` - PRD metric: task completion %
- `view_compliance_coverage_rate` - PRD metric: compliance coverage %

### When to Re-Export

Run `python scripts/export_duckdb_to_sqlite.py` when:
- ✅ New telemetry data added to DuckDB
- ✅ DuckDB schema changes (new columns, tables, views)
- ✅ Before creating/updating Metabase dashboards
- ✅ Dashboards show stale data

**Recommended:** Set up daily cron job for production:
```bash
0 2 * * * cd /path/to/amprealize && python scripts/export_duckdb_to_sqlite.py
```

## Why Not Use DuckDB Directly?

### Option 1: SQLite Export (Current - ✅ Working)
- ✅ **Pros:** Works today, no dependencies, simple
- ⚠️ **Cons:** Need to re-export when data changes, adds ~1-2 seconds

### Option 2: DuckDB JDBC Driver (Future)
- ✅ **Pros:** Real-time data, no export step
- ❌ **Cons:** Requires Metabase Enterprise or manual JDBC setup, not officially supported yet

### Option 3: REST API Proxy (Already Implemented)
- ✅ **Pros:** Real-time, already working (`/v1/analytics/*` endpoints)
- ⚠️ **Cons:** Metabase can't query REST APIs directly (would need custom connector)

## Alternative: Use REST API Endpoints

If you need real-time data without exports, use the analytics REST API:

```bash
# KPI Summary
curl http://localhost:8000/v1/analytics/kpi-summary

# Behavior Usage
curl http://localhost:8000/v1/analytics/behavior-usage

# Token Savings
curl http://localhost:8000/v1/analytics/token-savings

# Compliance Coverage
curl http://localhost:8000/v1/analytics/compliance-coverage
```

These endpoints query DuckDB directly and are always up-to-date.

## Troubleshooting

### "Failed to connect to Database"
- ✅ **Fix:** Use `/duckdb/telemetry_sqlite.db` NOT `/duckdb/telemetry.duckdb`
- Run export script first: `python scripts/export_duckdb_to_sqlite.py`

### "No tables found" in Metabase
- Check export ran successfully: `ls -lh data/telemetry_sqlite.db` (should be ~40KB)
- Verify mount: `podman exec amprealize-metabase ls -lh /duckdb/`
- Re-export: `python scripts/export_duckdb_to_sqlite.py`

### Dashboards show old data
- Re-run export: `python scripts/export_duckdb_to_sqlite.py`
- In Metabase: Settings → Databases → Amprealize Analytics Warehouse → "Sync database schema now"

### SQLite file not found in container
- Check volume mount in `docker-compose.analytics-dashboard.yml`
- Restart Metabase: `podman-compose restart metabase`
- Verify: `podman exec amprealize-metabase ls /duckdb/telemetry_sqlite.db`

## Architecture

```
┌──────────────┐     export      ┌────────────────┐
│   DuckDB     │───────────────▶│    SQLite      │
│  Warehouse   │  (Python)       │    Export      │
│ (native fmt) │                 │ (compatible)   │
└──────────────┘                 └────────────────┘
                                         │
                                         │ mount :ro
                                         ▼
                                 ┌────────────────┐
                                 │   Metabase     │
                                 │  (SQLite drv)  │
                                 └────────────────┘
```

## Summary

✅ **What works:**
- DuckDB warehouse stores analytics data
- Python export script converts to SQLite format
- Metabase reads SQLite export via standard driver
- Dashboards visualize PRD metrics

⏳ **Future improvements:**
- Automate daily export (cron job)
- Native DuckDB driver when Metabase supports it
- Direct streaming from DuckDB (custom connector)

---

**Created:** 2025-10-20
**Status:** Production-ready ✅
