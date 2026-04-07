# Programmatic Metabase Dashboard Creation

## Overview

Instead of manually creating dashboards in the Metabase UI, you can use the **Metabase REST API** to programmatically create all 4 PRD KPI dashboards with one command.

## Quick Start

```bash
# Ensure Metabase is running
podman-compose -f docker-compose.analytics-dashboard.yml up -d

# Run the dashboard creation script
python scripts/create_metabase_dashboards.py
```

This will create all 4 dashboards (18 cards total) in approximately 10-15 seconds.

## What Gets Created

The script creates:

1. **PRD KPI Summary** (6 cards)
   - 4 metric cards: Behavior Reuse %, Token Savings %, Completion %, Compliance %
   - KPI snapshot bar chart
   - Run volume by status bar chart

2. **Behavior Usage Trends** (3 cards)
   - Behavior usage summary table
   - Behavior leaderboard (top 20 runs)
   - Usage distribution histogram

3. **Token Savings Analysis** (4 cards)
   - Token savings summary table
   - Savings distribution histogram
   - Savings vs behaviors scatter plot
   - Efficiency leaderboard (top 20 runs)

4. **Compliance Coverage** (5 cards)
   - Coverage summary table
   - Checklist rankings bar chart
   - Step completion summary table
   - Audit queue (incomplete runs)
   - Coverage distribution pie chart

## Configuration

The script uses environment variables with sensible defaults:

```bash
# Set credentials (do not commit actual passwords!)
export METABASE_URL="http://localhost:3000"
export METABASE_USERNAME="admin@amprealize.local"
# Password should be set via secure means (keychain, vault, etc.)
# For local dev only: export METABASE_PASSWORD="<your-password>"

python scripts/create_metabase_dashboards.py
```

## How It Works

The script uses the [Metabase REST API](https://www.metabase.com/docs/latest/api-documentation):

1. **Authentication** - `POST /api/session` to get session token
2. **Find Database** - `GET /api/database` to locate SQLite database ID
3. **Create Cards** - `POST /api/card` to create native SQL questions
4. **Create Dashboards** - `POST /api/dashboard` to create dashboard containers
5. **Add Cards** - `POST /api/dashboard/:id/cards` to add cards with positioning

All SQL queries come from `docs/analytics/CORRECTED_SQL_QUERIES.md` with corrected column names for the actual SQLite schema.

## Requirements

```bash
# Install Python requests library (already in pyproject.toml)
pip install requests
```

## Troubleshooting

### Authentication Failed
```
❌ Error: 401 Client Error: Unauthorized
```
**Solution:** Check Metabase credentials. Default is `admin@amprealize.local` / `changeme123`. Update environment variables if you changed them.

### Database Not Found
```
❌ Error: Database 'telemetry_sqlite' not found
```
**Solution:**
1. Ensure Metabase is running: `podman ps`
2. Verify database connection in Metabase UI: http://localhost:3000/admin/databases
3. Check SQLite file is mounted: `podman exec metabase ls -la /duckdb/`

### Connection Refused
```
❌ Error: Connection refused
```
**Solution:** Start Metabase container:
```bash
podman-compose -f docker-compose.analytics-dashboard.yml up -d
curl http://localhost:3000/api/health  # Should return {"status":"ok"}
```

### Cards Already Exist
The script will fail if dashboards/cards with the same names already exist. To recreate:

1. Delete existing dashboards in Metabase UI: http://localhost:3000/collection/root
2. Or change dashboard names in the script

## Advantages Over Manual Creation

| Manual UI | Programmatic API |
|-----------|------------------|
| 60-90 minutes | 10-15 seconds |
| Error-prone copy/paste | Automated from corrected queries |
| Hard to reproduce | One command to recreate |
| Difficult to version | Script in git |
| Manual updates | Update script and rerun |

## Integration with CI/CD

You can integrate dashboard creation into deployment pipelines:

```yaml
# .github/workflows/deploy-analytics.yml
- name: Create Metabase dashboards
  run: python scripts/create_metabase_dashboards.py
  env:
    METABASE_URL: ${{ secrets.METABASE_URL }}
    METABASE_USERNAME: ${{ secrets.METABASE_USERNAME }}
    METABASE_PASSWORD: ${{ secrets.METABASE_PASSWORD }}
```

## Alternative Approaches

### 1. Export/Import Feature
Metabase has built-in export/import:
- Export: `GET /api/dashboard/:id` → JSON
- Import: `POST /api/dashboard` with JSON payload

**Pros:** Easy to backup/restore
**Cons:** Requires manual export first, database IDs may differ

### 2. Metabase CLI (Community Tool)
[metabase-cli](https://github.com/VolodymyrTymets/metabase-cli) provides command-line interface.

**Pros:** Higher-level abstractions
**Cons:** Extra dependency, less control

### 3. Direct H2 Database Access
Metabase stores metadata in H2/Postgres. You could insert directly.

**Pros:** Fastest
**Cons:** Very fragile, bypasses API validation, not recommended

## References

- **Metabase API Documentation:** https://www.metabase.com/docs/latest/api-documentation
- **API Reference (Swagger):** http://localhost:3000/api/docs (when Metabase running)
- **Python Metabase API Client:** https://github.com/vvaezian/metabase_api_python
- **Corrected SQL Queries:** `docs/analytics/CORRECTED_SQL_QUERIES.md`

## Behaviors

- `behavior_orchestrate_cicd` - Automate dashboard deployment
- `behavior_instrument_metrics_pipeline` - PRD metrics visualization
- `behavior_update_docs_after_changes` - Keep docs in sync

## Next Steps

After running the script:

1. Access dashboards: http://localhost:3000/collection/root
2. Verify all cards render correctly
3. Capture screenshots: `docs/analytics/screenshots/`
4. Update `BUILD_TIMELINE.md` with automation entry
5. Update `PRD_ALIGNMENT_LOG.md` with Phase 3b completion

---

_Last Updated: 2025-10-21_
