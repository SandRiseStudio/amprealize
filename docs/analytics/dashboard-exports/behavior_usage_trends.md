# Behavior Usage Trends Dashboard

> **Dashboard:** Behavior Citation Analytics & Reuse Patterns
> **Refresh:** Every 10 minutes
> **Data Source:** Amprealize Analytics Warehouse (DuckDB)

## Dashboard Purpose

Track how behaviors are being discovered, referenced, and reused across Amprealize runs to:
- Identify most valuable behaviors (high citation frequency)
- Detect underutilized behaviors (candidates for deprecation)
- Monitor behavior reuse growth over time
- Understand per-run behavior usage patterns

## Dashboard Layout

```
┌───────────────────────────────────────────────────────────┐
│  Behavior Usage Trends                [Filter: Last 30d] │
├───────────────────────────────────────────────────────────┤
│  Total Behaviors    Avg per Run    Total Runs            │
│     142               4.2            1,234               │
│  ┌─────────────────────────────────────────────────────┐ │
│  │ Behavior Citations Over Time (Daily)                │ │
│  │ [Line chart: total citations + unique behaviors]    │ │
│  └─────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────┐ │
│  │ Top 10 Most Cited Behaviors                         │ │
│  │ [Bar chart: behavior_name → citation_count]         │ │
│  └─────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────┐ │
│  │ Behavior Usage Distribution (per run)               │ │
│  │ [Histogram: number of behaviors cited per run]      │ │
│  └─────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────┐ │
│  │ Recent Behavior Citations (Table)                   │ │
│  │ Run ID | Template | Behaviors | Count | Timestamp   │ │
│  └─────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────┘
```

## Metrics Cards

### Card 1: Total Unique Behaviors Cited

**SQL Query:**

```sql
-- Query: Count distinct behaviors cited in time range
SELECT
  COUNT(DISTINCT unnest(behavior_ids)) AS total_behaviors,
  MIN(execution_timestamp) AS period_start,
  MAX(execution_timestamp) AS period_end
FROM main.fact_behavior_usage
WHERE execution_timestamp >= {{start_date}}
  AND execution_timestamp < {{end_date}};
```

### Card 2: Average Behaviors per Run

**SQL Query:**

```sql
-- Query: Average number of behaviors cited per run
SELECT
  ROUND(AVG(behavior_count), 1) AS avg_behaviors_per_run,
  COUNT(DISTINCT run_id) AS total_runs
FROM main.fact_behavior_usage
WHERE execution_timestamp >= {{start_date}}
  AND execution_timestamp < {{end_date}};
```

### Card 3: Total Runs with Behaviors

**SQL Query:**

```sql
-- Query: Count runs that cited at least one behavior
SELECT
  COUNT(DISTINCT run_id) AS total_runs,
  SUM(CASE WHEN has_behaviors THEN 1 ELSE 0 END) AS runs_with_behaviors,
  ROUND(
    SUM(CASE WHEN has_behaviors THEN 1 ELSE 0 END)::DOUBLE / COUNT(*)::DOUBLE * 100,
    1
  ) AS pct_runs_with_behaviors
FROM main.fact_behavior_usage
WHERE execution_timestamp >= {{start_date}}
  AND execution_timestamp < {{end_date}};
```

## Charts

### Chart 1: Behavior Citations Over Time

**Type:** Line chart (dual Y-axis)
**SQL Query:**

```sql
-- Query: Daily behavior citation trends
SELECT
  DATE_TRUNC('day', execution_timestamp) AS date,
  SUM(behavior_count) AS total_citations,
  COUNT(DISTINCT unnest(behavior_ids)) AS unique_behaviors,
  COUNT(DISTINCT run_id) AS total_runs,
  ROUND(AVG(behavior_count), 1) AS avg_per_run
FROM main.fact_behavior_usage
WHERE execution_timestamp >= {{start_date}}
  AND execution_timestamp < {{end_date}}
GROUP BY date
ORDER BY date;
```

**Visualization:**
- X-axis: Date
- Y-axis (left): Total citations (blue line)
- Y-axis (right): Unique behaviors (green line)
- Series:
  - Total Citations (blue, solid)
  - Unique Behaviors (green, dashed)
- Tooltip: Show avg_per_run and total_runs

### Chart 2: Top 10 Most Cited Behaviors

**Type:** Horizontal bar chart
**SQL Query:**

```sql
-- Query: Behaviors with highest citation counts
WITH behavior_citations AS (
  SELECT
    unnest(behavior_ids) AS behavior_id,
    COUNT(*) AS citation_count,
    COUNT(DISTINCT run_id) AS unique_runs,
    MIN(execution_timestamp) AS first_cited,
    MAX(execution_timestamp) AS last_cited
  FROM main.fact_behavior_usage
  WHERE execution_timestamp >= {{start_date}}
    AND execution_timestamp < {{end_date}}
  GROUP BY behavior_id
)
SELECT
  behavior_id,
  citation_count,
  unique_runs,
  ROUND(citation_count::DOUBLE / unique_runs::DOUBLE, 1) AS avg_citations_per_run,
  DATEDIFF('day', first_cited, last_cited) AS days_active
FROM behavior_citations
ORDER BY citation_count DESC
LIMIT 10;
```

**Visualization:**
- X-axis: Citation count
- Y-axis: Behavior ID
- Color: Gradient (darker = more citations)
- Click: Drill down to behavior detail page

### Chart 3: Behavior Usage Distribution

**Type:** Histogram
**SQL Query:**

```sql
-- Query: Distribution of behaviors per run
SELECT
  behavior_count AS behaviors_per_run,
  COUNT(*) AS run_count,
  ROUND(COUNT(*)::DOUBLE / SUM(COUNT(*)) OVER () * 100, 1) AS pct_of_runs
FROM main.fact_behavior_usage
WHERE execution_timestamp >= {{start_date}}
  AND execution_timestamp < {{end_date}}
GROUP BY behavior_count
ORDER BY behavior_count;
```

**Visualization:**
- X-axis: Behaviors per run (bins: 0, 1-2, 3-5, 6-10, 11+)
- Y-axis: Run count
- Color: Blue gradient
- Tooltip: Show percentage of total runs

### Chart 4: Behavior Co-Occurrence Heatmap (Advanced)

**Type:** Heatmap
**SQL Query:**

```sql
-- Query: Which behaviors are frequently cited together
WITH behavior_pairs AS (
  SELECT
    b1.behavior_id AS behavior_1,
    b2.behavior_id AS behavior_2,
    COUNT(DISTINCT bu.run_id) AS co_occurrence_count
  FROM main.fact_behavior_usage bu,
    LATERAL unnest(bu.behavior_ids) AS b1(behavior_id),
    LATERAL unnest(bu.behavior_ids) AS b2(behavior_id)
  WHERE b1.behavior_id < b2.behavior_id
    AND bu.execution_timestamp >= {{start_date}}
    AND bu.execution_timestamp < {{end_date}}
  GROUP BY behavior_1, behavior_2
)
SELECT *
FROM behavior_pairs
WHERE co_occurrence_count >= 5
ORDER BY co_occurrence_count DESC
LIMIT 50;
```

**Visualization:**
- X-axis: Behavior 1
- Y-axis: Behavior 2
- Color: Heat intensity (darker = higher co-occurrence)
- Use for: Identifying behavior chains or common patterns

## Tables

### Table 1: Recent Behavior Citations

**Type:** Data table (paginated)
**SQL Query:**

```sql
-- Query: Most recent runs with behavior details
SELECT
  run_id,
  template_id,
  behavior_count,
  behavior_ids,
  has_behaviors,
  execution_timestamp
FROM main.fact_behavior_usage
WHERE execution_timestamp >= {{start_date}}
  AND execution_timestamp < {{end_date}}
ORDER BY execution_timestamp DESC
LIMIT {{limit}};
```

**Columns:**
- Run ID (link to run detail)
- Template ID
- Behavior Count
- Behavior IDs (truncated list, tooltip shows full)
- Timestamp

**Settings:**
- Pagination: 50 rows per page
- Sort: Default by timestamp DESC
- Export: CSV enabled

### Table 2: Behavior Citation Leaderboard

**Type:** Data table (ranked)
**SQL Query:**

```sql
-- Query: All behaviors ranked by citation frequency
WITH behavior_stats AS (
  SELECT
    unnest(behavior_ids) AS behavior_id,
    COUNT(*) AS total_citations,
    COUNT(DISTINCT run_id) AS unique_runs,
    COUNT(DISTINCT template_id) AS templates_used,
    MIN(execution_timestamp) AS first_cited,
    MAX(execution_timestamp) AS last_cited,
    DATEDIFF('day', MIN(execution_timestamp), MAX(execution_timestamp)) AS days_active
  FROM main.fact_behavior_usage
  WHERE execution_timestamp >= {{start_date}}
    AND execution_timestamp < {{end_date}}
  GROUP BY behavior_id
)
SELECT
  ROW_NUMBER() OVER (ORDER BY total_citations DESC) AS rank,
  behavior_id,
  total_citations,
  unique_runs,
  templates_used,
  ROUND(total_citations::DOUBLE / unique_runs::DOUBLE, 2) AS avg_per_run,
  days_active,
  ROUND(total_citations::DOUBLE / NULLIF(days_active, 0)::DOUBLE, 2) AS citations_per_day
FROM behavior_stats
ORDER BY total_citations DESC;
```

**Columns:**
- Rank (#)
- Behavior ID
- Total Citations
- Unique Runs
- Templates Used
- Avg per Run
- Days Active
- Citations/Day (velocity metric)

## Filters

1. **Date Range:**
   - Default: Last 30 days
   - Options: 7d, 30d, 90d, All time, Custom

2. **Template ID (optional):**
   - Default: All
   - Options: Dropdown

3. **Has Behaviors:**
   - Default: All
   - Options: Yes (has_behaviors=true), No (has_behaviors=false)

4. **Min Behavior Count (slider):**
   - Default: 0
   - Range: 0-20

## Insights & Analysis

### Behavior Adoption Curve

Track cumulative unique behaviors over time to measure handbook growth:

```sql
-- Query: Cumulative behavior adoption
WITH daily_behaviors AS (
  SELECT
    DATE(execution_timestamp) AS date,
    behavior_id
  FROM main.fact_behavior_usage,
    LATERAL unnest(behavior_ids) AS b(behavior_id)
  WHERE execution_timestamp >= {{start_date}}
),
cumulative AS (
  SELECT DISTINCT
    date,
    behavior_id,
    MIN(date) OVER (PARTITION BY behavior_id) AS first_cited_date
  FROM daily_behaviors
)
SELECT
  date,
  COUNT(DISTINCT CASE WHEN first_cited_date <= date THEN behavior_id END) AS cumulative_behaviors
FROM cumulative
GROUP BY date
ORDER BY date;
```

### Underutilized Behaviors (Candidates for Review)

```sql
-- Query: Behaviors with low usage (potential deprecation candidates)
WITH behavior_stats AS (
  SELECT
    unnest(behavior_ids) AS behavior_id,
    COUNT(*) AS citation_count,
    MAX(execution_timestamp) AS last_cited
  FROM main.fact_behavior_usage
  WHERE execution_timestamp >= CURRENT_DATE - INTERVAL '90 days'
  GROUP BY behavior_id
)
SELECT
  behavior_id,
  citation_count,
  last_cited,
  DATEDIFF('day', last_cited, CURRENT_DATE) AS days_since_cited
FROM behavior_stats
WHERE citation_count < 5
  OR days_since_cited > 30
ORDER BY days_since_cited DESC, citation_count;
```

## Setup Instructions

1. Create new dashboard: "Behavior Usage Trends"
2. Add metric cards (3 cards at top)
3. Add line chart for daily trends
4. Add bar chart for top behaviors
5. Add histogram for distribution
6. Add data table for recent citations
7. Connect date range filter to all questions
8. Set auto-refresh to 10 minutes
9. Save to "PRD Metrics" collection

## Alerts

**Alert: New Behavior Discovered**

Trigger when a previously unseen behavior ID appears:

```sql
-- Alert when behavior count increases by 10+
SELECT
  COUNT(DISTINCT unnest(behavior_ids)) AS current_count
FROM main.fact_behavior_usage
WHERE execution_timestamp >= CURRENT_DATE - INTERVAL '1 day'
HAVING current_count > (
  SELECT COUNT(DISTINCT unnest(behavior_ids))
  FROM main.fact_behavior_usage
  WHERE execution_timestamp >= CURRENT_DATE - INTERVAL '2 days'
    AND execution_timestamp < CURRENT_DATE - INTERVAL '1 day'
) + 10;
```

**Alert: Behavior Reuse Rate Declining**

Trigger when average behaviors per run drops below threshold:

```sql
-- Alert when avg behaviors/run < 3.0
SELECT
  ROUND(AVG(behavior_count), 1) AS avg_behaviors
FROM main.fact_behavior_usage
WHERE execution_timestamp >= CURRENT_DATE - INTERVAL '7 days'
HAVING avg_behaviors < 3.0;
```

## Referenced Behaviors

- `behavior_curate_behavior_handbook` – Insights inform handbook maintenance
- `behavior_instrument_metrics_pipeline` – Usage tracking feeds PRD metrics

---

**Dashboard Status:** ✅ Ready for deployment
**Last Updated:** 2025-10-20
