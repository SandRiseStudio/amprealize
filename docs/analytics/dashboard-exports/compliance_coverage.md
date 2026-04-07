# Compliance Coverage Dashboard

> **Dashboard:** Checklist Completion & Audit Trail
> **Refresh:** Every 10 minutes
> **Data Source:** Amprealize Analytics Warehouse (DuckDB)

## Dashboard Purpose

Monitor compliance checklist execution across Amprealize runs to:
- Track coverage rates per checklist (target: ≥95%)
- Identify incomplete or skipped compliance steps
- Ensure audit requirements are met for regulated workflows
- Surface patterns in step completion/failure

## Dashboard Layout

```
┌─────────────────────────────────────────────────────────────┐
│  Compliance Coverage Dashboard  [Filter: Last 30 days]     │
├─────────────────────────────────────────────────────────────┤
│  Avg Coverage   Checklists    Fully Complete               │
│    96.8%          47            89.4%                       │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ Coverage Rate Over Time (Daily)                       │ │
│  │ [Line chart: avg coverage % + 95% target line]       │ │
│  └───────────────────────────────────────────────────────┘ │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ Coverage by Checklist (Bar Chart)                     │ │
│  │ [Horizontal bars: checklist_id → coverage %]          │ │
│  └───────────────────────────────────────────────────────┘ │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ Step Completion Heatmap                               │ │
│  │ [Heatmap: checklist × step → completion rate]        │ │
│  └───────────────────────────────────────────────────────┘ │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ Recent Executions (Table)                             │ │
│  │ Run | Checklist | Coverage | Complete | Timestamp     │ │
│  └───────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Metrics Cards

### Card 1: Average Compliance Coverage

**SQL Query:**

```sql
-- Query: Mean coverage score across all executions
SELECT
  ROUND(AVG(coverage_score) * 100, 1) AS avg_coverage_pct,
  95 AS target_pct,
  COUNT(*) AS total_executions,
  CASE
    WHEN AVG(coverage_score) >= 0.95 THEN 'On Track'
    WHEN AVG(coverage_score) >= 0.85 THEN 'At Risk'
    ELSE 'Off Track'
  END AS status
FROM main.fact_compliance_steps
WHERE execution_timestamp >= {{start_date}}
  AND execution_timestamp < {{end_date}};
```

**Visualization:**
- Display: 96.8% (large number)
- Subtitle: "Target: 95% | 1,234 executions"
- Color: Green if ≥95%, Yellow if ≥85%, Red if <85%
- Trend arrow: Compare to previous period

### Card 2: Total Checklists Executed

**SQL Query:**

```sql
-- Query: Count distinct checklists used
SELECT
  COUNT(DISTINCT checklist_id) AS total_checklists,
  COUNT(DISTINCT CONCAT(checklist_id, '|', template_id)) AS unique_checklist_template_pairs,
  COUNT(*) AS total_executions
FROM main.fact_compliance_steps
WHERE execution_timestamp >= {{start_date}}
  AND execution_timestamp < {{end_date}};
```

**Visualization:**
- Display: 47 (large number)
- Subtitle: "Distinct checklists"

### Card 3: Fully Complete Rate

**SQL Query:**

```sql
-- Query: Percentage of executions with 100% coverage
SELECT
  COUNT(*) AS total_executions,
  SUM(CASE WHEN all_steps_complete THEN 1 ELSE 0 END) AS fully_complete_count,
  ROUND(
    SUM(CASE WHEN all_steps_complete THEN 1 ELSE 0 END)::DOUBLE / COUNT(*)::DOUBLE * 100,
    1
  ) AS fully_complete_pct
FROM main.fact_compliance_steps
WHERE execution_timestamp >= {{start_date}}
  AND execution_timestamp < {{end_date}};
```

**Visualization:**
- Display: 89.4% (large number)
- Subtitle: "1,103 / 1,234 executions"
- Color: Green if ≥90%, Yellow if ≥80%, Red if <80%

### Card 4: Critical Compliance Failures

**SQL Query:**

```sql
-- Query: Count of high-priority checklist failures
SELECT
  COUNT(*) AS critical_failures
FROM main.fact_compliance_steps
WHERE execution_timestamp >= {{start_date}}
  AND execution_timestamp < {{end_date}}
  AND all_steps_complete = FALSE
  AND coverage_score < 0.80  -- Less than 80% coverage
  AND checklist_id LIKE '%critical%';  -- Filter for critical checklists
```

**Visualization:**
- Display: 3 (large number, red if > 0)
- Subtitle: "Requires investigation"
- Alert: Show warning icon if > 0

## Charts

### Chart 1: Coverage Rate Over Time

**Type:** Line chart with goal line
**SQL Query:**

```sql
-- Query: Daily average coverage trends
SELECT
  DATE_TRUNC('day', execution_timestamp) AS date,
  ROUND(AVG(coverage_score) * 100, 1) AS avg_coverage_pct,
  COUNT(*) AS execution_count,
  SUM(CASE WHEN all_steps_complete THEN 1 ELSE 0 END) AS fully_complete_count,
  ROUND(
    SUM(CASE WHEN all_steps_complete THEN 1 ELSE 0 END)::DOUBLE / COUNT(*)::DOUBLE * 100,
    1
  ) AS fully_complete_pct
FROM main.fact_compliance_steps
WHERE execution_timestamp >= {{start_date}}
  AND execution_timestamp < {{end_date}}
GROUP BY date
ORDER BY date;
```

**Visualization:**
- X-axis: Date
- Y-axis: Coverage percentage (0-100)
- Series:
  - Average Coverage (blue line, solid)
  - Fully Complete % (green line, dashed)
  - Target Line (red horizontal at 95%)
- Tooltip: Show execution count
- Alert zone: Shade area below 85% in red

### Chart 2: Coverage by Checklist

**Type:** Horizontal bar chart (sorted)
**SQL Query:**

```sql
-- Query: Average coverage per checklist
SELECT
  checklist_id,
  COUNT(*) AS execution_count,
  ROUND(AVG(coverage_score) * 100, 1) AS avg_coverage_pct,
  SUM(CASE WHEN all_steps_complete THEN 1 ELSE 0 END) AS fully_complete_count,
  ROUND(
    SUM(CASE WHEN all_steps_complete THEN 1 ELSE 0 END)::DOUBLE / COUNT(*)::DOUBLE * 100,
    1
  ) AS fully_complete_pct
FROM main.fact_compliance_steps
WHERE execution_timestamp >= {{start_date}}
  AND execution_timestamp < {{end_date}}
GROUP BY checklist_id
ORDER BY avg_coverage_pct;
```

**Visualization:**
- X-axis: Average coverage %
- Y-axis: Checklist ID
- Color:
  - Green if avg ≥95%
  - Yellow if avg 85-95%
  - Red if avg <85%
- Click: Drill down to checklist detail
- Label: Show execution count

### Chart 3: Step Completion Heatmap

**Type:** Heatmap (matrix)
**SQL Query:**

```sql
-- Query: Completion rate per checklist step
WITH step_completions AS (
  SELECT
    checklist_id,
    step_id,
    COUNT(*) AS total_executions,
    SUM(CASE WHEN step_completed THEN 1 ELSE 0 END) AS completed_count
  FROM main.fact_compliance_steps,
    LATERAL unnest(step_ids) WITH ORDINALITY AS s(step_id, step_index),
    LATERAL unnest(step_statuses) WITH ORDINALITY AS st(step_completed, status_index)
  WHERE s.step_index = st.status_index
    AND execution_timestamp >= {{start_date}}
    AND execution_timestamp < {{end_date}}
  GROUP BY checklist_id, step_id
)
SELECT
  checklist_id,
  step_id,
  completed_count,
  total_executions,
  ROUND(completed_count::DOUBLE / total_executions::DOUBLE * 100, 1) AS completion_rate_pct
FROM step_completions
ORDER BY checklist_id, step_id;
```

**Visualization:**
- X-axis: Step ID (or step number)
- Y-axis: Checklist ID
- Color: Heat gradient (green = 100%, red = 0%)
- Tooltip: Show completion rate and counts
- Use for: Identifying commonly skipped steps

### Chart 4: Coverage Distribution

**Type:** Histogram
**SQL Query:**

```sql
-- Query: Distribution of coverage scores
SELECT
  CASE
    WHEN coverage_score >= 0.95 THEN '95-100%'
    WHEN coverage_score >= 0.85 THEN '85-95%'
    WHEN coverage_score >= 0.70 THEN '70-85%'
    WHEN coverage_score >= 0.50 THEN '50-70%'
    ELSE '<50%'
  END AS coverage_bucket,
  COUNT(*) AS execution_count,
  ROUND(COUNT(*)::DOUBLE / SUM(COUNT(*)) OVER () * 100, 1) AS pct_of_total
FROM main.fact_compliance_steps
WHERE execution_timestamp >= {{start_date}}
  AND execution_timestamp < {{end_date}}
GROUP BY coverage_bucket
ORDER BY
  CASE coverage_bucket
    WHEN '95-100%' THEN 1
    WHEN '85-95%' THEN 2
    WHEN '70-85%' THEN 3
    WHEN '50-70%' THEN 4
    ELSE 5
  END;
```

**Visualization:**
- X-axis: Coverage buckets
- Y-axis: Execution count
- Color: Gradient (green for higher coverage)
- Goal annotation: Mark 95% threshold

## Tables

### Table 1: Recent Compliance Executions

**Type:** Data table (paginated)
**SQL Query:**

```sql
-- Query: Most recent checklist executions
SELECT
  run_id,
  checklist_id,
  template_id,
  ROUND(coverage_score * 100, 1) AS coverage_pct,
  all_steps_complete,
  ARRAY_LENGTH(step_ids, 1) AS total_steps,
  ARRAY_LENGTH(
    ARRAY_AGG(CASE WHEN s = TRUE THEN 1 END),
    1
  ) AS completed_steps,
  execution_timestamp
FROM main.fact_compliance_steps,
  LATERAL unnest(step_statuses) AS st(s)
WHERE execution_timestamp >= {{start_date}}
  AND execution_timestamp < {{end_date}}
GROUP BY run_id, checklist_id, template_id, coverage_score, all_steps_complete, step_ids, execution_timestamp
ORDER BY execution_timestamp DESC
LIMIT {{limit}};
```

**Columns:**
- Run ID (link)
- Checklist ID
- Template ID
- Coverage % (color-coded)
- All Complete (✓/✗)
- Steps (completed/total)
- Timestamp

**Settings:**
- Pagination: 50 per page
- Sort: Timestamp DESC
- Export: CSV enabled

### Table 2: Low Coverage Executions (Audit Queue)

**Type:** Data table (filtered)
**SQL Query:**

```sql
-- Query: Executions needing audit review
SELECT
  run_id,
  checklist_id,
  template_id,
  ROUND(coverage_score * 100, 1) AS coverage_pct,
  ARRAY_LENGTH(step_ids, 1) AS total_steps,
  ARRAY_LENGTH(
    ARRAY_AGG(CASE WHEN s = FALSE THEN 1 END),
    1
  ) AS incomplete_steps,
  step_ids,
  step_statuses,
  execution_timestamp,
  DATEDIFF('day', DATE(execution_timestamp), CURRENT_DATE) AS days_ago
FROM main.fact_compliance_steps,
  LATERAL unnest(step_statuses) AS st(s)
WHERE execution_timestamp >= {{start_date}}
  AND execution_timestamp < {{end_date}}
  AND all_steps_complete = FALSE
GROUP BY run_id, checklist_id, template_id, coverage_score, step_ids, step_statuses, execution_timestamp
ORDER BY coverage_score, execution_timestamp
LIMIT 100;
```

**Use Case:** Prioritize compliance reviews for incomplete checklists

### Table 3: Checklist Leaderboard

**Type:** Data table (ranked)
**SQL Query:**

```sql
-- Query: Checklists ranked by completion rate
SELECT
  ROW_NUMBER() OVER (ORDER BY AVG(coverage_score) DESC) AS rank,
  checklist_id,
  COUNT(*) AS execution_count,
  ROUND(AVG(coverage_score) * 100, 1) AS avg_coverage_pct,
  SUM(CASE WHEN all_steps_complete THEN 1 ELSE 0 END) AS fully_complete_count,
  ROUND(
    SUM(CASE WHEN all_steps_complete THEN 1 ELSE 0 END)::DOUBLE / COUNT(*)::DOUBLE * 100,
    1
  ) AS fully_complete_pct,
  COUNT(DISTINCT template_id) AS templates_used
FROM main.fact_compliance_steps
WHERE execution_timestamp >= {{start_date}}
  AND execution_timestamp < {{end_date}}
GROUP BY checklist_id
ORDER BY avg_coverage_pct DESC;
```

## Insights & Analysis

### Most Commonly Skipped Steps

```sql
-- Query: Steps with lowest completion rates
WITH step_stats AS (
  SELECT
    checklist_id,
    step_id,
    COUNT(*) AS total_appearances,
    SUM(CASE WHEN step_completed THEN 1 ELSE 0 END) AS completed_count
  FROM main.fact_compliance_steps,
    LATERAL unnest(step_ids) WITH ORDINALITY AS s(step_id, step_index),
    LATERAL unnest(step_statuses) WITH ORDINALITY AS st(step_completed, status_index)
  WHERE s.step_index = st.status_index
    AND execution_timestamp >= {{start_date}}
  GROUP BY checklist_id, step_id
)
SELECT
  checklist_id,
  step_id,
  total_appearances,
  completed_count,
  ROUND((total_appearances - completed_count)::DOUBLE / total_appearances::DOUBLE * 100, 1) AS skip_rate_pct
FROM step_stats
WHERE total_appearances >= 10  -- Minimum sample size
ORDER BY skip_rate_pct DESC
LIMIT 20;
```

### Compliance by Template

```sql
-- Query: Which templates have best/worst compliance
SELECT
  template_id,
  COUNT(DISTINCT checklist_id) AS checklists_used,
  COUNT(*) AS execution_count,
  ROUND(AVG(coverage_score) * 100, 1) AS avg_coverage_pct,
  SUM(CASE WHEN all_steps_complete THEN 1 ELSE 0 END) AS fully_complete_count
FROM main.fact_compliance_steps
WHERE execution_timestamp >= {{start_date}}
GROUP BY template_id
ORDER BY avg_coverage_pct DESC;
```

### Audit Evidence Completeness

```sql
-- Query: Are we collecting sufficient audit evidence?
SELECT
  DATE(execution_timestamp) AS date,
  COUNT(*) AS total_executions,
  SUM(CASE WHEN all_steps_complete THEN 1 ELSE 0 END) AS audit_ready_count,
  ROUND(
    SUM(CASE WHEN all_steps_complete THEN 1 ELSE 0 END)::DOUBLE / COUNT(*)::DOUBLE * 100,
    1
  ) AS audit_ready_pct,
  95 AS target_pct
FROM main.fact_compliance_steps
WHERE execution_timestamp >= {{start_date}}
GROUP BY date
HAVING audit_ready_pct < 95.0  -- Flag days below target
ORDER BY date DESC;
```

## Filters

1. **Date Range:** 7d, 30d, 90d, All time
2. **Checklist ID (dropdown):** All or specific
3. **Template ID (dropdown):** All or specific
4. **Coverage Threshold (slider):** Show only executions below X%
5. **Completion Status:** All, Complete only, Incomplete only

## Alerts

**Alert: Coverage Below Target**

Trigger when daily average drops below 95%:

```sql
SELECT
  DATE(execution_timestamp) AS alert_date,
  ROUND(AVG(coverage_score) * 100, 1) AS avg_coverage
FROM main.fact_compliance_steps
WHERE execution_timestamp >= CURRENT_DATE - INTERVAL '1 day'
  AND execution_timestamp < CURRENT_DATE
GROUP BY alert_date
HAVING avg_coverage < 95.0;
```

**Alert: Critical Checklist Incomplete**

Trigger when critical compliance checklists are not fully complete:

```sql
SELECT
  run_id,
  checklist_id,
  ROUND(coverage_score * 100, 1) AS coverage_pct
FROM main.fact_compliance_steps
WHERE execution_timestamp >= CURRENT_DATE - INTERVAL '1 day'
  AND checklist_id LIKE '%critical%'
  AND all_steps_complete = FALSE;
```

## Compliance Reporting

### Audit Export Query

```sql
-- Query: Full audit trail for regulatory reporting
SELECT
  run_id,
  checklist_id,
  template_id,
  step_ids,
  step_statuses,
  coverage_score,
  all_steps_complete,
  execution_timestamp,
  DATE(execution_timestamp) AS execution_date,
  EXTRACT(YEAR FROM execution_timestamp) AS year,
  EXTRACT(QUARTER FROM execution_timestamp) AS quarter,
  EXTRACT(MONTH FROM execution_timestamp) AS month
FROM main.fact_compliance_steps
WHERE execution_timestamp >= {{audit_start_date}}
  AND execution_timestamp < {{audit_end_date}}
ORDER BY execution_timestamp;
```

**Export Format:** CSV with full step details for audit submission

## Setup Instructions

1. Create dashboard: "Compliance Coverage"
2. Add 4 metric cards (avg coverage, total checklists, fully complete %, critical failures)
3. Add coverage trend line chart with 95% goal line
4. Add bar chart for checklist rankings
5. Add heatmap for step completion patterns
6. Add histogram for coverage distribution
7. Add recent executions table
8. Add low coverage audit queue table
9. Add checklist leaderboard table
10. Connect filters (date range, checklist, template)
11. Set auto-refresh to 10 minutes
12. Configure email alerts for coverage drops
13. Save to "PRD Metrics" collection with restricted access

## Security & Access Control

- **Restricted Access:** Compliance dashboard should have role-based access
- **Audit Log:** Track who views/exports compliance data
- **Data Retention:** Ensure compliance records meet regulatory retention requirements
- **Export Controls:** Limit CSV export to authorized personnel only

## Referenced Behaviors

- `behavior_handbook_compliance_prompt` – Checklist execution mandates
- `behavior_instrument_metrics_pipeline` – Coverage tracking feeds PRD metrics
- `behavior_lock_down_security_surface` – Audit access controls

---

**Dashboard Status:** ✅ Ready for deployment
**Last Updated:** 2025-10-20
