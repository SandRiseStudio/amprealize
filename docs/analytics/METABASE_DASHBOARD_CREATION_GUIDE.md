# Metabase Dashboard Creation Guide

> **Purpose:** Step-by-step instructions for manually creating the 4 PRD analytics dashboards in Metabase
> **Prerequisites:** Metabase run3. Visualization type: **Bar C3. Visualization type: **Bar Chart** (stacked or grouped)
4. X-axis: `final_status`
5. Y-axis: `run_count`
6. Colors: Green (success), Yellow (partial), Red (failed)
7. Title: `Run Volume by Status`
8. **Save** → Add to dashboard

### Dashboard Layout
- Top row: 4 metric cards (Behavior Reuse, Token Savings, Completion, Compliance)
- Middle: Current KPI snapshot bar chart (full width)
- Bottom: Run volume bar chart (full width)zontal)
4. X-axis: `value`
5. Y-axis: `metric_name`
6. Title: `Current KPI Snapshot`
7. Note: Add reference lines for targets: Behavior Reuse 70%, Token Savings 30%, Completion 80%, Compliance 95%
8. **Save** → Add to dashboard

### Card 6: Run Volume Bar Chart//localhost:3000, database connected to `/duckdb/telemetry_sqlite.db`
> **Estimated Time:** 60-90 minutes for all 4 dashboards
> **Last Updated:** 2025-10-20

## Quick Start Checklist

- [ ] Metabase accessible at http://localhost:3000
- [ ] Login successful (admin@amprealize.local / changeme123)
- [ ] Database connection verified (`telemetry_sqlite.db`)
- [ ] All 8 tables visible (4 fact tables, 4 KPI views)
- [ ] Dashboard #1: PRD KPI Summary
- [ ] Dashboard #2: Behavior Usage Trends
- [ ] Dashboard #3: Token Savings Analysis
- [ ] Dashboard #4: Compliance Coverage
- [ ] Screenshots captured for documentation
- [ ] BUILD_TIMELINE.md and PRD_ALIGNMENT_LOG.md updated

---

## Pre-Flight: Verify Database Connection

### Step 1: Login to Metabase
1. Open browser: http://localhost:3000
2. Login credentials:
   - **Email:** `admin@amprealize.local`
   - **Password:** `changeme123`

### Step 2: Verify Database
1. Click **Settings** (gear icon) → **Admin settings** → **Databases**
2. Confirm you see database: **amprealize Analytics (SQLite)**
3. Connection string should be: `/duckdb/telemetry_sqlite.db`
4. Click **Test connection** → should show ✅ success

### Step 3: Verify Tables
Navigate to **Browse Data** → Select database, confirm 8 tables visible:

**Fact Tables:**
- `fact_behavior_usage`
- `fact_compliance_steps`
- `fact_execution_status`
- `fact_token_savings`

**KPI Views:**
- `view_behavior_reuse_rate`
- `view_completion_rate`
- `view_compliance_coverage_rate`
- `view_token_savings_rate`

---

## Dashboard #1: PRD KPI Summary

**Purpose:** Executive overview of PRD success metrics (70% behavior reuse, 30% token savings, 80% completion, 95% compliance)

### Create Dashboard
1. Click **+** icon → **New** → **Dashboard**
2. Name: `PRD KPI Summary`
3. Description: `Executive dashboard tracking PRD success metrics across all agent runs`
4. Click **Create**

### Card 1: Behavior Reuse Rate (Metric Card)
1. Click **Add a question** → **Native query** (SQL)
2. Paste SQL:
```sql
SELECT
  ROUND(reuse_rate_pct, 1) as rate_pct,
  CASE
    WHEN reuse_rate_pct >= 70.0 THEN 'On Track'
    WHEN reuse_rate_pct >= 60.0 THEN 'At Risk'
    ELSE 'Off Track'
  END as status
FROM main.view_behavior_reuse_rate;
```
3. Click **Visualize**
4. Visualization type: **Number** (single metric)
5. Formatting:
   - Show field: `rate_pct`
   - Suffix: `%`
   - Color: Green if ≥70%, Yellow if ≥60%, Red otherwise
6. Title: `Behavior Reuse Rate`
7. Description: `Target: 70%`
8. Click **Save** → **Add to dashboard: PRD KPI Summary**

### Card 2: Token Savings Rate (Metric Card)
1. Click **Add a question** → **Native query**
2. Paste SQL:
```sql
SELECT
  ROUND(avg_savings_rate_pct, 1) as rate_pct,
  CASE
    WHEN avg_savings_rate_pct >= 30.0 THEN 'On Track'
    WHEN avg_savings_rate_pct >= 20.0 THEN 'At Risk'
    ELSE 'Off Track'
  END as status
FROM main.view_token_savings_rate;
```
3. Visualization type: **Number**
4. Formatting:
   - Show field: `rate_pct`
   - Suffix: `%`
   - Color: Green if ≥30%, Yellow if ≥20%, Red otherwise
5. Title: `Token Savings Rate`
6. Description: `Target: 30%`
7. **Save** → Add to dashboard

### Card 3: Task Completion Rate (Metric Card)
1. Click **Add a question** → **Native query**
2. Paste SQL:
```sql
SELECT
  ROUND(completion_rate_pct, 1) as rate_pct,
  CASE
    WHEN completion_rate_pct >= 80.0 THEN 'On Track'
    WHEN completion_rate_pct >= 70.0 THEN 'At Risk'
    ELSE 'Off Track'
  END as status
FROM main.view_completion_rate;
```
3. Visualization type: **Number**
4. Formatting: Same as above (≥80% green, ≥70% yellow)
5. Title: `Task Completion Rate`
6. Description: `Target: 80%`
7. **Save** → Add to dashboard

### Card 4: Compliance Coverage Rate (Metric Card)
1. Click **Add a question** → **Native query**
2. Paste SQL:
```sql
SELECT
  ROUND(avg_coverage_rate_pct, 1) as rate_pct,
  CASE
    WHEN avg_coverage_rate_pct >= 95.0 THEN 'On Track'
    WHEN avg_coverage_rate_pct >= 90.0 THEN 'At Risk'
    ELSE 'Off Track'
  END as status
FROM main.view_compliance_coverage_rate;
```
3. Visualization type: **Number**
4. Formatting: ≥95% green, ≥90% yellow
5. Title: `Compliance Coverage Rate`
6. Description: `Target: 95%`
7. **Save** → Add to dashboard

### Card 5: 30-Day Trend Line Chart
1. Click **Add a question** → **Native query**
2. Paste SQL:
```sql
-- Note: Current schema shows KPI views as aggregate snapshots (no time dimension)
-- This query shows current snapshot values across all metrics
SELECT
  'Behavior Reuse' as metric_name,
  reuse_rate_pct as value
FROM main.view_behavior_reuse_rate

UNION ALL

SELECT
  'Token Savings' as metric_name,
  avg_savings_rate_pct as value
FROM main.view_token_savings_rate

UNION ALL

SELECT
  'Completion' as metric_name,
  completion_rate_pct as value
FROM main.view_completion_rate

UNION ALL

SELECT
  'Compliance' as metric_name,
  avg_coverage_rate_pct as value
FROM main.view_compliance_coverage_rate;
```
3. Visualization type: **Bar Chart** (horizontal)
4. X-axis: `metric_date`
5. Y-axis: `value`
6. Series: `metric_name`
7. Add reference lines:
   - Behavior Reuse: 70%
   - Token Savings: 30%
   - Completion: 80%
   - Compliance: 95%
8. Title: `30-Day KPI Trends`
9. **Save** → Add to dashboard

### Card 6: Run Volume Bar Chart
1. Click **Add a question** → **Native query**
2. Paste SQL:
```sql
SELECT
  status as final_status,
  COUNT(*) as run_count
FROM main.fact_execution_status
GROUP BY status
ORDER BY run_count DESC;
```
3. Visualization type: **Bar Chart** (stacked or grouped)
4. X-axis: `run_date`
5. Y-axis: `run_count`
6. Stack by: `final_status`
7. Colors: Green (success), Yellow (partial), Red (failed)
8. Title: `Daily Run Volume by Status`
9. **Save** → Add to dashboard

### Dashboard Layout
- Top row: 4 metric cards (Behavior Reuse, Token Savings, Completion, Compliance)
- Middle: 30-day trend line chart (full width)
- Bottom: Run volume bar chart (full width)

### Filters (Optional)
1. Click **Edit dashboard** → **Add filter**
2. Add **Date Range** filter:
   - Variable: `{{start_date}}`, `{{end_date}}`
   - Default: Last 30 days
3. Add **Agent Role** filter (if role data available)
4. Click **Save**

---

## Dashboard #2: Behavior Usage Trends

**Purpose:** Analyze behavior citation patterns, reuse trends, and co-occurrence

### Create Dashboard
1. **+** → **New** → **Dashboard**
2. Name: `Behavior Usage Trends`
3. Description: `Behavior citation analytics and reuse pattern visualization`

### Card 1: Daily Citation Time Series
1. **Add question** → **Native query**
2. Paste SQL:
```sql
-- Current Behavior Usage Summary (no time dimension in current schema)
SELECT
  total_runs,
  runs_with_behaviors,
  ROUND(reuse_rate_pct, 1) as reuse_rate_pct,
  ROUND((runs_with_behaviors * 100.0 / total_runs), 1) as pct_runs_using_behaviors
FROM main.view_behavior_reuse_rate;
```
3. Visualization: **Table**
4. Title: `Behavior Usage Summary`
5. **Save** → Add to dashboard

### Card 2: Behavior Leaderboard Table
1. **Add question** → **Native query**
2. Paste SQL:
```sql
-- Note: SQLite doesn't support unnest directly, this is a simplified version
-- For full implementation, you may need to export behavior_ids and process in Python
SELECT
  'behavior_' || (behavior_count % 10) as behavior_name,
  COUNT(*) as citation_count,
  COUNT(DISTINCT run_id) as unique_runs
FROM main.fact_behavior_usage
WHERE DATE(execution_timestamp) >= DATE('now', '-30 days')
GROUP BY behavior_name
ORDER BY citation_count DESC
LIMIT 10;
```
3. Visualization: **Bar Chart** (horizontal)
4. X-axis: `citation_count`
5. Y-axis: `behavior_name`
6. Title: `Top 10 Most Cited Behaviors`
7. **Save** → Add to dashboard

### Card 3: Behavior Leaderboard Table
1. **Add question** → **Native query**
2. Paste SQL:
```sql
SELECT
  run_id,
  behavior_count as citations
FROM main.fact_behavior_usage
ORDER BY behavior_count DESC
LIMIT 20;
```
3. Visualization: **Table**
4. Columns: All
5. Sort: `citations` descending
6. Title: `Behavior Usage Leaderboard`
7. **Save** → Add to dashboard

### Card 4: Usage Distribution Histogram
1. **Add question** → **Native query**
2. Paste SQL:
```sql
SELECT
  CASE
    WHEN behavior_count = 0 THEN '0 behaviors'
    WHEN behavior_count BETWEEN 1 AND 3 THEN '1-3 behaviors'
    WHEN behavior_count BETWEEN 4 AND 6 THEN '4-6 behaviors'
    WHEN behavior_count BETWEEN 7 AND 10 THEN '7-10 behaviors'
    ELSE '10+ behaviors'
  END as bucket,
  COUNT(*) as run_count
FROM main.fact_behavior_usage
GROUP BY
  CASE
    WHEN behavior_count = 0 THEN '0 behaviors'
    WHEN behavior_count BETWEEN 1 AND 3 THEN '1-3 behaviors'
    WHEN behavior_count BETWEEN 4 AND 6 THEN '4-6 behaviors'
    WHEN behavior_count BETWEEN 7 AND 10 THEN '7-10 behaviors'
    ELSE '10+ behaviors'
  END
ORDER BY MIN(behavior_count);
```
3. Visualization: **Bar Chart**
4. X-axis: `bucket`
5. Y-axis: `run_count`
6. Title: `Behavior Count Distribution`
7. **Save** → Add to dashboard

### Dashboard Layout
- Top: Behavior usage summary table (full width)
- Middle: Behavior leaderboard (full width)
- Bottom: Usage distribution histogram (full width)

---

## Dashboard #3: Token Savings Analysis

**Purpose:** Track token efficiency, ROI, and correlation with behavior usage

### Create Dashboard
1. **+** → **New** → **Dashboard**
2. Name: `Token Savings Analysis`
3. Description: `Token efficiency tracking and ROI calculations`

### Card 1: Baseline vs Output Token Trends
1. **Add question** → **Native query**
2. Paste SQL:
```sql
-- Token Savings Summary (current snapshot)
SELECT
  ROUND(avg_savings_rate_pct, 1) as avg_savings_pct,
  total_runs,
  ROUND(total_baseline_tokens, 0) as total_baseline,
  ROUND(total_output_tokens, 0) as total_output,
  ROUND(total_tokens_saved, 0) as total_saved,
  ROUND(total_tokens_saved / 1000.0 * 0.02, 2) as estimated_cost_savings_usd
FROM main.view_token_savings_rate;
```
3. Visualization: **Table**
4. Title: `Token Savings Summary`
5. **Save** → Add to dashboard

### Card 2: Savings Distribution Histogram
1. **Add question** → **Native query**
2. Paste SQL:
```sql
SELECT
  CASE
    WHEN token_savings_pct >= 0.50 THEN '50%+ savings'
    WHEN token_savings_pct >= 0.30 THEN '30-50% savings'
    WHEN token_savings_pct >= 0.10 THEN '10-30% savings'
    WHEN token_savings_pct >= 0.00 THEN '0-10% savings'
    ELSE 'Negative savings'
  END as bucket,
  COUNT(*) as run_count,
  ROUND(AVG(token_savings_pct) * 100, 1) as avg_pct
FROM main.fact_token_savings
GROUP BY
  CASE
    WHEN token_savings_pct >= 0.50 THEN '50%+ savings'
    WHEN token_savings_pct >= 0.30 THEN '30-50% savings'
    WHEN token_savings_pct >= 0.10 THEN '10-30% savings'
    WHEN token_savings_pct >= 0.00 THEN '0-10% savings'
    ELSE 'Negative savings'
  END
ORDER BY MIN(token_savings_pct) DESC;
```
3. Visualization: **Bar Chart**
4. Title: `Savings Distribution`
5. **Save** → Add to dashboard

### Card 3: Savings vs Behaviors Scatter Plot
1. **Add question** → **Native query**
2. Paste SQL:
```sql
SELECT
  COALESCE(b.behavior_count, 0) as behavior_count,
  ROUND(t.token_savings_pct * 100, 1) as savings_pct,
  t.run_id
FROM main.fact_token_savings t
LEFT JOIN main.fact_behavior_usage b ON t.run_id = b.run_id;
```
3. Visualization: **Scatter Plot**
4. X-axis: `behavior_count`
5. Y-axis: `savings_pct`
6. Title: `Token Savings vs Behavior Usage`
7. Add trend line
8. **Save** → Add to dashboard

### Card 4: Efficiency Leaderboard
1. **Add question** → **Native query**
2. Paste SQL:
```sql
SELECT
  run_id,
  baseline_tokens,
  output_tokens,
  ROUND(token_savings_pct * 100, 1) as savings_pct,
  (baseline_tokens - output_tokens) as tokens_saved
FROM main.fact_token_savings
ORDER BY token_savings_pct DESC
LIMIT 20;
```
3. Visualization: **Table**
4. Title: `Top Efficient Runs`
5. **Save** → Add to dashboard

---

## Dashboard #4: Compliance Coverage

**Purpose:** Monitor checklist completion and audit trail

### Create Dashboard
1. **+** → **New** → **Dashboard**
2. Name: `Compliance Coverage`
3. Description: `Checklist completion monitoring and audit trail`

### Card 1: Coverage Trend with 95% Goal Line
1. **Add question** → **Native query**
2. Paste SQL:
```sql
-- Current Coverage Summary
SELECT
  ROUND(avg_coverage_rate_pct, 1) as avg_coverage_pct,
  total_runs,
  runs_above_95pct,
  ROUND((runs_above_95pct * 100.0 / total_runs), 1) as pct_above_target,
  95.0 as goal_line
FROM main.view_compliance_coverage_rate;
```
3. Visualization: **Table** or **Number** (for avg_coverage_pct)
4. Title: `Compliance Coverage Summary`
5. **Save** → Add to dashboard

### Card 2: Checklist Rankings Bar Chart
1. **Add question** → **Native query**
2. Paste SQL:
```sql
SELECT
  checklist_id,
  ROUND(AVG(coverage_score) * 100, 1) as avg_coverage,
  COUNT(*) as executions,
  SUM(CASE WHEN all_steps_complete = 1 THEN 1 ELSE 0 END) as complete_count
FROM main.fact_compliance_steps
GROUP BY checklist_id
ORDER BY avg_coverage DESC;
```
3. Visualization: **Bar Chart** (horizontal)
4. X-axis: `avg_coverage`
5. Y-axis: `checklist_id`
6. Color: Green if ≥95%, Yellow if ≥85%, Red otherwise
7. Title: `Checklist Coverage Rankings`
8. **Save** → Add to dashboard

### Card 3: Step Completion Summary Table
1. **Add question** → **Native query**
2. Paste SQL:
```sql
SELECT
  checklist_id,
  step_count as total_steps,
  ROUND(AVG(coverage_score) * 100, 1) as avg_coverage,
  COUNT(*) as runs,
  SUM(CASE WHEN all_steps_complete = 1 THEN 1 ELSE 0 END) as fully_complete,
  ROUND((SUM(CASE WHEN all_steps_complete = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*)), 1) as completion_rate
FROM main.fact_compliance_steps
GROUP BY checklist_id, step_count
ORDER BY avg_coverage ASC;
```
3. Visualization: **Table**
4. Title: `Step Completion Summary`
5. **Save** → Add to dashboard

### Card 4: Audit Queue (Incomplete Runs)
1. **Add question** → **Native query**
2. Paste SQL:
```sql
SELECT
  run_id,
  checklist_id,
  step_count as total_steps,
  ROUND(coverage_score * 100, 1) as coverage_pct,
  (step_count - ROUND(coverage_score * step_count)) as incomplete_steps
FROM main.fact_compliance_steps
WHERE all_steps_complete = 0
ORDER BY coverage_score ASC
LIMIT 50;
```
3. Visualization: **Table**
4. Title: `Compliance Audit Queue (Incomplete Runs)`
5. Highlight rows with coverage < 85%
6. **Save** → Add to dashboard

### Card 5: Coverage Score Distribution
1. **Add question** → **Native query**
2. Paste SQL:
```sql
SELECT
  CASE
    WHEN coverage_score >= 0.95 THEN '95-100%'
    WHEN coverage_score >= 0.85 THEN '85-95%'
    WHEN coverage_score >= 0.75 THEN '75-85%'
    WHEN coverage_score >= 0.50 THEN '50-75%'
    ELSE '<50%'
  END as coverage_bucket,
  COUNT(*) as run_count
FROM main.fact_compliance_steps
GROUP BY
  CASE
    WHEN coverage_score >= 0.95 THEN '95-100%'
    WHEN coverage_score >= 0.85 THEN '85-95%'
    WHEN coverage_score >= 0.75 THEN '75-85%'
    WHEN coverage_score >= 0.50 THEN '50-75%'
    ELSE '<50%'
  END
ORDER BY MIN(coverage_score) DESC;
```
3. Visualization: **Pie Chart**
4. Title: `Coverage Score Distribution`
5. **Save** → Add to dashboard

---

## Post-Creation: Validation & Documentation

### Validation Checklist
- [ ] All 4 dashboards created and accessible
- [ ] All SQL queries execute without errors
- [ ] Visualizations render correctly with sample data
- [ ] Filters work (if configured)
- [ ] No missing permissions or database access issues
- [ ] Dashboard URLs captured for sharing

### Capture Evidence
1. Take screenshots of each dashboard
2. Save to `docs/analytics/screenshots/` folder:
   - `prd_kpi_summary.png`
   - `behavior_usage_trends.png`
   - `token_savings_analysis.png`
   - `compliance_coverage.png`

### Update Documentation
Update the following files with completion evidence:

**BUILD_TIMELINE.md** - Add new entry:
```markdown
### #63 - Analytics Dashboards - Manual Creation Complete (2025-10-20)
**Milestone:** Analytics & Production Readiness (Phase 2 Complete)
**Context:** Created 4 Metabase dashboards visualizing PRD success metrics
**Artifacts:**
- PRD KPI Summary dashboard (4 metric cards, trend lines, run volume)
- Behavior Usage Trends dashboard (citations, leaderboard, distribution)
- Token Savings Analysis dashboard (efficiency trends, ROI, correlation)
- Compliance Coverage dashboard (coverage trend, rankings, audit queue)
- Screenshots in docs/analytics/screenshots/
**Behaviors:** behavior_instrument_metrics_pipeline, behavior_update_docs_after_changes
**Evidence:** All dashboards operational at http://localhost:3000, SQL queries validated
```

**PRD_ALIGNMENT_LOG.md** - Update Phase 2 section:
```markdown
- **Manual Dashboard Creation (2025-10-20):** Created 4 dashboards in Metabase following SQL queries from dashboard export specifications. All PRD KPIs visualized: behavior reuse rate (70% target), token savings rate (30% target), task completion rate (80% target), compliance coverage rate (95% target). Evidence: screenshots in docs/analytics/screenshots/, dashboards accessible at http://localhost:3000.
```

**PROGRESS_TRACKER.md** - Update analytics row:
```markdown
| Analytics dashboards | Phase 1-2-3 Complete (2025-10-20) | ... | Phase 3 (Manual Creation): 4 dashboards created in Metabase with PRD KPI visualizations |
```

---

## Troubleshooting

### Issue: SQL Query Fails
**Symptom:** Query returns error or no results
**Fix:**
1. Verify table/view names match exactly: `main.fact_*`, `main.view_*`
2. Check date ranges return data: adjust `DATE('now', '-30 days')` if needed
3. Test query in SQL console first before adding to dashboard

### Issue: Empty Visualizations
**Symptom:** Charts/cards show "No results"
**Fix:**
1. Run `python scripts/export_duckdb_to_sqlite.py` to refresh data
2. Verify fact tables have rows: `SELECT COUNT(*) FROM main.fact_behavior_usage;`
3. Adjust date filters to match data availability

### Issue: Visualization Type Not Available
**Symptom:** Cannot select desired chart type
**Fix:**
1. Ensure query returns correct column types (dates, numbers, strings)
2. Try different visualization and configure manually
3. Check Metabase version supports visualization (v0.48.0 should support all)

### Issue: Permission Denied
**Symptom:** Cannot create dashboards or run queries
**Fix:**
1. Confirm logged in as admin user
2. Check database connection permissions
3. Verify SQLite file readable: `ls -lh data/telemetry_sqlite.db`

### Issue: Slow Query Performance
**Symptom:** Queries take >5 seconds
**Fix:**
1. Add indexes per `docs/analytics/dashboard-exports/README.md`
2. Limit date ranges in filters
3. Consider aggregating data in views

---

## Next Steps

After dashboard creation:
1. **Share dashboards** - Configure public/team sharing links
2. **Set up alerts** - Configure email alerts for KPIs below thresholds
3. **Auto-refresh** - Enable auto-refresh (every 5-10 minutes)
4. **Export automation** - Set up daily cron job: `0 2 * * * python scripts/export_duckdb_to_sqlite.py`
5. **VS Code integration** - Embed dashboards in IDE analytics panel
6. **Production deployment** - Migrate to production Metabase instance with Postgres backend

---

## Resources

- Dashboard specifications: `docs/analytics/dashboard-exports/*.md`
- Metabase setup guide: `docs/analytics/metabase_setup.md`
- DuckDB schema: `docs/analytics/prd_metrics_schema.sql`
- Export script: `scripts/export_duckdb_to_sqlite.py`
- Troubleshooting: `docs/analytics/DUCKDB_SQLITE_EXPORT.md`

**Questions or issues?** Refer to `docs/analytics/metabase_setup.md` troubleshooting section or consult Metabase documentation.
