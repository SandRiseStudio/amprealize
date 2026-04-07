# Amprealize Analytics Dashboard Exports

> **Directory:** Dashboard definitions for Metabase visualization platform
> **Last Updated:** 2025-10-20

## Overview

This directory contains SQL-based dashboard specifications for visualizing Amprealize PRD success metrics in Metabase. Each file documents the layout, queries, and configuration for one analytics dashboard.

## Available Dashboards

### 1. PRD KPI Summary (`prd_kpi_summary.md`)

**Purpose:** Executive overview of all four PRD success metrics
**Metrics:**
- Behavior Reuse Rate (target: ≥70%)
- Token Savings Rate (target: ≥30%)
- Task Completion Rate (target: ≥80%)
- Compliance Coverage Rate (target: ≥95%)

**Key Visualizations:**
- Metric cards with trend comparisons
- 30-day trend line chart (all metrics)
- Run volume bar chart

**Audience:** Executives, Product Managers, Stakeholders

---

### 2. Behavior Usage Trends (`behavior_usage_trends.md`)

**Purpose:** Deep-dive into behavior citation patterns and reuse analytics
**Insights:**
- Most/least cited behaviors
- Behavior adoption curves
- Usage distribution per run
- Co-occurrence patterns

**Key Visualizations:**
- Daily citation time series
- Top 10 behaviors bar chart
- Usage distribution histogram
- Behavior leaderboard table

**Audience:** Engineering, DX, Behavior Curators

---

### 3. Token Savings Analysis (`token_savings_analysis.md`)

**Purpose:** Quantify token efficiency gains and cost optimization from BCI
**Insights:**
- Average token savings percentage
- Cumulative tokens saved
- Estimated cost reduction
- Correlation with behavior usage

**Key Visualizations:**
- Baseline vs output token trends
- Savings distribution histogram
- Savings vs behaviors scatter plot
- Efficiency leaderboard

**Audience:** Product Analytics, Finance, Engineering Leadership

---

### 4. Compliance Coverage (`compliance_coverage.md`)

**Purpose:** Monitor checklist execution and audit trail completeness
**Insights:**
- Coverage rates per checklist
- Step completion heatmap
- Incomplete executions (audit queue)
- Commonly skipped steps

**Key Visualizations:**
- Coverage trend with 95% goal line
- Checklist rankings bar chart
- Step completion heatmap
- Audit queue table

**Audience:** Compliance, Security, Audit Teams

---

## File Format

Each dashboard file follows this structure:

```markdown
# Dashboard Name

> Metadata (purpose, refresh rate, data source)

## Dashboard Layout
- ASCII diagram showing panel arrangement

## Metrics Cards
- SQL queries for summary statistics

## Charts
- SQL queries for visualizations
- Chart type and configuration

## Tables
- SQL queries for data tables
- Column specifications

## Filters
- Dashboard-level filter definitions

## Alerts
- SQL queries for automated alerts

## Setup Instructions
- Step-by-step Metabase configuration

## Referenced Behaviors
- Links to agent behaviors applied
```

## Usage

### Option 1: Manual Dashboard Creation (Recommended)

1. Open Metabase: http://localhost:3000
2. Navigate to: **Collections** → **New Dashboard**
3. Follow the **Setup Instructions** in each `.md` file:
   - Copy SQL queries from "Metrics Cards" and "Charts" sections
   - Create questions in Metabase using these queries
   - Add questions to dashboard canvas
   - Configure visualizations per specifications
4. Connect dashboard-level filters
5. Set auto-refresh rate
6. Save and share

### Option 2: Programmatic Import (Future)

When Metabase's API supports it, use the JSON export/import feature:

```bash
# Export dashboard from Metabase
curl -X GET http://localhost:3000/api/dashboard/1 \
  -H "X-Metabase-Session: YOUR_SESSION_TOKEN" \
  > prd_kpi_summary.json

# Import to another instance
curl -X POST http://localhost:3000/api/dashboard \
  -H "X-Metabase-Session: YOUR_SESSION_TOKEN" \
  -d @prd_kpi_summary.json
```

**Note:** Metabase's export format is complex and database-specific. Manual creation is currently more reliable.

**Container Runtime:** Amprealize uses Podman for container orchestration. See `deployment/PODMAN.md` for setup instructions.

## Data Source Configuration

All dashboards query the **Amprealize Analytics Warehouse (DuckDB)**:

- **Database Path:** `/duckdb/telemetry.duckdb` (inside Metabase container)
- **Local Path:** `data/telemetry.duckdb` (on host)
- **Driver:** SQLite (for read-only DuckDB compatibility)
- **Schemas:**
  - `main` – Current operational schema (fact tables + KPI views)
  - `prd_metrics` – Legacy schema (may be empty)

### Required Tables/Views

Ensure these exist in the warehouse:

```sql
-- Fact tables
main.fact_behavior_usage
main.fact_token_savings
main.fact_execution_status
main.fact_compliance_steps

-- KPI views
main.view_behavior_reuse_rate
main.view_token_savings_rate
main.view_completion_rate
main.view_compliance_coverage_rate
main.view_kpi_summary
```

Verify with:

```bash
python -c "
import duckdb
conn = duckdb.connect('data/telemetry.duckdb', read_only=True)
tables = conn.execute(\"SELECT table_schema, table_name FROM information_schema.tables WHERE table_schema = 'main'\").fetchall()
print('\n'.join([f'{s}.{t}' for s, t in tables]))
"
```

## Filter Variables

Dashboards use these common filter variables (configured at dashboard level):

| Variable | Type | Default | Description |
| --- | --- | --- | --- |
| `{{start_date}}` | Date | 30 days ago | Start of date range |
| `{{end_date}}` | Date | Today | End of date range (exclusive) |
| `{{limit}}` | Number | 100 | Pagination limit for tables |
| `{{template_id}}` | String | NULL | Filter by specific template |
| `{{checklist_id}}` | String | NULL | Filter by specific checklist |

### Connecting Filters

In Metabase:

1. Add filter: **Dashboard → Add Filter → Time**
2. Map to questions: Click filter → **Map to** → Select column for each question
3. Common mappings:
   - `execution_timestamp` (fact tables)
   - `snapshot_time` (KPI views)

## Query Optimization

### Indexes

Add these indexes to improve dashboard performance:

```sql
-- Fact table indexes
CREATE INDEX IF NOT EXISTS idx_behavior_usage_timestamp
  ON main.fact_behavior_usage(execution_timestamp);

CREATE INDEX IF NOT EXISTS idx_token_savings_timestamp
  ON main.fact_token_savings(execution_timestamp);

CREATE INDEX IF NOT EXISTS idx_execution_status_timestamp
  ON main.fact_execution_status(execution_timestamp);

CREATE INDEX IF NOT EXISTS idx_compliance_steps_timestamp
  ON main.fact_compliance_steps(execution_timestamp);

-- Lookup indexes
CREATE INDEX IF NOT EXISTS idx_behavior_usage_run_id
  ON main.fact_behavior_usage(run_id);
```

### Caching

Metabase caches query results. Configure per question:

- **KPI Summary:** 60 seconds (real-time metrics)
- **Trend Charts:** 5 minutes (less frequent updates)
- **Leaderboards:** 10 minutes (historical data)

## Maintenance

### Refreshing Dashboard Definitions

When warehouse schema changes:

1. Update SQL queries in `.md` files
2. Increment "Last Updated" timestamp
3. Note changes in dashboard changelog (below)
4. Notify dashboard users via Slack/email
5. Update dashboards in Metabase

### Version Control

Track changes via Git:

```bash
# Commit dashboard updates
git add docs/analytics/dashboard-exports/
git commit -m "Update token savings dashboard: add ROI calculation"

# Tag dashboard releases
git tag -a dashboards-v1.1 -m "Added compliance heatmap"
```

### Container Runtime (Podman)

Amprealize uses Podman instead of Docker for:
- Lighter resource usage (no daemon)
- Rootless containers by default (better security)
- Full Docker Compose compatibility via `podman-compose`

See `deployment/PODMAN.md` for installation and configuration.

## Changelog

### 2025-10-20 – Initial Release (v1.0)

- ✅ Created 4 core dashboards (KPI Summary, Behavior Usage, Token Savings, Compliance)
- ✅ Documented SQL queries for all visualizations
- ✅ Added setup instructions for Metabase
- ✅ Defined filters and alerts
- ✅ Included optimization recommendations

### Future Enhancements

- [ ] Add drill-down dashboards (per-behavior detail, per-checklist audit)
- [ ] Implement JSON exports when Metabase API stabilizes
- [ ] Create Python scripts for programmatic dashboard deployment
- [ ] Add user segmentation dashboards (by role, team, project)
- [ ] Build predictive analytics (forecasting token savings, behavior adoption)

## Troubleshooting

### Queries return empty results

```bash
# Verify warehouse has data
python -c "
import duckdb
conn = duckdb.connect('data/telemetry.duckdb', read_only=True)
print('Behavior usage rows:', conn.execute('SELECT COUNT(*) FROM main.fact_behavior_usage').fetchone()[0])
print('Token savings rows:', conn.execute('SELECT COUNT(*) FROM main.fact_token_savings').fetchone()[0])
"
```

### Queries are slow

- Add indexes (see Query Optimization section)
- Increase Metabase memory: `JAVA_OPTS: "-Xmx2g"` in docker-compose
- Reduce date range filter default (90d → 30d)

### DuckDB compatibility issues

- Use SQLite driver in Metabase (most compatible for read-only)
- Avoid DuckDB-specific syntax (e.g., `LIST` type, `STRUCT`)
- Test queries in DuckDB CLI before adding to Metabase

## Resources

- **Metabase Setup Guide:** `docs/analytics/metabase_setup.md`
- **Warehouse Schema:** `docs/analytics/prd_metrics_schema.sql`
- **REST API Endpoints:** `amprealize/api.py` (analytics routes)
- **MCP Tools:** `mcp/tools/analytics.*.json`

## Referenced Behaviors

- `behavior_instrument_metrics_pipeline` – Dashboard queries aligned with PRD metrics
- `behavior_update_docs_after_changes` – Documentation maintenance workflow
- `behavior_curate_behavior_handbook` – Behavior usage insights feed handbook curation

---

**Dashboard Export Status:** ✅ Production-Ready
**Last Updated:** 2025-10-20
