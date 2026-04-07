# Metabase Dashboard Fix - Final Summary

**Date:** 2025-10-22
**Status:** ✅ **RESOLVED**

## Issues Fixed

1. ✅ **Empty dashboards** - Cards weren't being attached due to incorrect Metabase API usage
2. ✅ **Duplicate dashboards** - Multiple old dashboards not being deleted
3. ✅ **Corrupted SQLite database** - Database disk image malformed error
4. ✅ **Cards not displaying** - Required Metabase container restart after SQLite regeneration

## Root Causes

### 1. Incorrect add_card_to_dashboard API
**Problem:** Used wrong endpoint (`/api/dashboard/:id/cards` → 404)
**Solution:** Use `PUT /api/dashboard/:id` with `dashcards` array containing negative IDs for new cards

### 2. Incomplete cleanup
**Problem:** `delete_dashboard_by_name()` only searched for exact "KPI" matches
**Solution:** Created comprehensive `metabase_nuclear_cleanup.py` that searches with 30+ terms to find ALL content

### 3. SQLite corruption
**Problem:** Concurrent writes or interrupted export created malformed database
**Solution:** Delete and regenerate SQLite from scratch; restart Metabase container to clear cache

## Complete End-to-End Workflow

```bash
# 1. Generate fresh telemetry data
python scripts/seed_telemetry_data.py --runs 100

# 2. Export DuckDB → SQLite
python scripts/export_duckdb_to_sqlite.py

# 3. Clean up ALL old Metabase content
python scripts/metabase_nuclear_cleanup.py

# 4. Create dashboards with proper API
python scripts/create_metabase_dashboards.py

# 5. Restart Metabase if database was regenerated
podman-compose -f docker-compose.analytics-dashboard.yml restart metabase

# 6. Trigger database resync (after restart completes)
curl -X POST http://localhost:3000/api/database/2/sync_schema \
  -H "X-Metabase-Session: YOUR_SESSION_TOKEN"
```

## Files Created/Modified

### New Files
- **`scripts/seed_telemetry_data.py`** - Generates sample workflow runs with behaviors, tokens, compliance
- **`scripts/metabase_nuclear_cleanup.py`** - Comprehensive cleanup using multiple search terms
- **`scripts/rebuild_dashboards.sh`** - One-command full rebuild pipeline
- **`docs/analytics/DASHBOARD_REBUILD_SUMMARY.md`** - Technical documentation

### Modified Files
- **`scripts/export_duckdb_to_sqlite.py`**
  - Changed export source from `main` → `prd_metrics` schema
  - Fixed index column names (removed non-existent `execution_timestamp`)

- **`scripts/create_metabase_dashboards.py`**
  - Fixed `add_card_to_dashboard()` to use PUT with `dashcards` array
  - Added comprehensive `clean_all_dashboards_and_cards()` (now superseded by nuclear cleanup)
  - Removed `main.` schema prefixes from SQL (SQLite compatibility)

### DuckDB Schema Updates
Created 4 aggregate views in `prd_metrics` schema:
```sql
prd_metrics.view_behavior_reuse_rate
prd_metrics.view_token_savings_rate
prd_metrics.view_completion_rate
prd_metrics.view_compliance_coverage_rate
```

## Current State

### Metabase (http://localhost:3000)
✅ **4 Dashboards, 18 Cards, All Working**

| Dashboard | ID | Cards | Status |
|-----------|----|----|--------|
| PRD KPI Summary | 18 | 6 | ✅ Data displaying |
| Behavior Usage Trends | 19 | 3 | ✅ Data displaying |
| Token Savings Analysis | 20 | 4 | ✅ Data displaying |
| Compliance Coverage | 21 | 5 | ✅ Data displaying |

### Data Pipeline
```
Telemetry Events (sample)
    ↓ TelemetryKPIProjector
prd_metrics.fact_* tables (DuckDB)
    ↓ export_duckdb_to_sqlite.py
telemetry_sqlite.db (200+ rows per table)
    ↓ Podman volume mount
Metabase container → Dashboards
```

### Sample Metrics
- **Behavior Reuse:** 100.0% (200/200 runs) ✅
- **Token Savings:** 45.6% avg ✅
- **Completion Rate:** 100.0% ✅
- **Compliance Coverage:** 77.7% avg ⚠️

## Testing Performed

1. ✅ SQLite integrity check: `PRAGMA integrity_check` → `ok`
2. ✅ View queries: All 4 views return data
3. ✅ Card query via API: Returns correct data
4. ✅ Dashboard card counts: All dashboards have expected number of cards
5. ✅ Metabase resync: `sync_schema` returns `{"status":"ok"}`

## Key Learnings

### Metabase API Quirks
1. Adding cards requires PUT to `/api/dashboard/:id` with full `dashcards` array
2. New dashcards need **negative integer IDs** (e.g., -1, -2, -3)
3. Must GET current dashboard, append new dashcard, then PUT entire array back
4. Search API can return non-dict items - always check `isinstance(item, dict)`

### SQLite & Metabase
1. Metabase caches SQLite file handles - container restart required after regeneration
2. Always run `sync_schema` after database changes
3. Volume mounts are read-only (`:ro`) - regenerate on host, Metabase reads fresh copy after restart

### DuckDB → SQLite Export
1. Views must exist in source schema (`prd_metrics`) before export
2. Arrays need conversion to lists for DuckDB compatibility
3. Schema prefixes (`main.`) break SQLite - use unqualified table names

## Future Maintenance

### Regular Data Refresh
```bash
# Weekly or daily, depending on telemetry volume
./scripts/rebuild_dashboards.sh
```

### Adding New Dashboards
1. Add dashboard creation function to `create_metabase_dashboards.py`
2. Update `metabase_nuclear_cleanup.py` search terms if using new keywords
3. Update `main()` to call new function
4. Run full cleanup → create cycle

### Troubleshooting Empty Dashboards
```bash
# Check SQLite is valid
sqlite3 data/telemetry_sqlite.db "PRAGMA integrity_check;"

# Check Metabase can see tables
SESSION="<your-session-token>"
curl -X GET "http://localhost:3000/api/database/2" \
  -H "X-Metabase-Session: $SESSION" | jq .tables

# Force resync
curl -X POST "http://localhost:3000/api/database/2/sync_schema" \
  -H "X-Metabase-Session: $SESSION"

# Last resort: restart Metabase
podman-compose -f docker-compose.analytics-dashboard.yml restart metabase
```

## Behaviors Applied

- `behavior_instrument_metrics_pipeline` - Telemetry projection, dashboard automation
- `behavior_align_storage_layers` - DuckDB ↔ SQLite schema parity
- `behavior_externalize_configuration` - Metabase connection config via env vars
- `behavior_lock_down_security_surface` - Metabase auth, search result guards
- `behavior_update_docs_after_changes` - This document, rebuild summary

---

**Last Updated:** 2025-10-22
**Verified Working:** ✅ All 4 dashboards displaying data correctly
**Next Steps:** Replace sample data with production telemetry events from amprealize runtime
