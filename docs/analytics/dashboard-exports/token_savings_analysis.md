# Token Savings Analysis Dashboard

> **Dashboard:** Token Efficiency & Cost Optimization
> **Refresh:** Every 10 minutes
> **Data Source:** Amprealize Analytics Warehouse (DuckDB)

## Dashboard Purpose

Quantify the token efficiency gains from behavior reuse to:
- Measure actual token savings vs baseline (BCI vs non-BCI)
- Track cost reduction over time (ROI for behavior-conditioned inference)
- Identify runs with highest/lowest efficiency
- Correlate token savings with behavior usage patterns

## Dashboard Layout

```
┌─────────────────────────────────────────────────────────────┐
│  Token Savings Analysis            [Filter: Last 30 days]  │
├─────────────────────────────────────────────────────────────┤
│  Avg Savings    Total Saved     Cost Reduction              │
│    34.2%         142.5M          $2,847                     │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ Token Savings Over Time (Daily)                       │ │
│  │ [Line chart: baseline vs output tokens, savings %]    │ │
│  └───────────────────────────────────────────────────────┘ │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ Savings Distribution (Histogram)                      │ │
│  │ [Bar chart: <10%, 10-30%, 30-50%, 50%+]              │ │
│  └───────────────────────────────────────────────────────┘ │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ Savings vs Behavior Count (Scatter)                   │ │
│  │ [Scatter plot: X=behaviors, Y=savings%, size=tokens] │ │
│  └───────────────────────────────────────────────────────┘ │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ Top Efficient Runs (Table)                            │ │
│  │ Run | Baseline | Output | Saved | % | Behaviors       │ │
│  └───────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Metrics Cards

### Card 1: Average Token Savings

**SQL Query:**

```sql
-- Query: Mean token savings percentage
SELECT
  ROUND(AVG(token_savings_pct) * 100, 1) AS avg_savings_pct,
  70 AS baseline_pct,  -- Assume 70% of baseline without BCI
  COUNT(*) AS total_runs
FROM main.fact_token_savings
WHERE execution_timestamp >= {{start_date}}
  AND execution_timestamp < {{end_date}};
```

**Visualization:**
- Display: 34.2% (large number)
- Subtitle: "vs 0% baseline (non-BCI)"
- Color: Green if ≥30%, Yellow if ≥20%, Red if <20%
- Comparison: Show improvement from previous period

### Card 2: Total Tokens Saved

**SQL Query:**

```sql
-- Query: Cumulative token savings
SELECT
  SUM(baseline_tokens - output_tokens) AS total_tokens_saved,
  ROUND(SUM(baseline_tokens - output_tokens) / 1000000.0, 1) AS millions_saved,
  SUM(baseline_tokens) AS total_baseline_tokens
FROM main.fact_token_savings
WHERE execution_timestamp >= {{start_date}}
  AND execution_timestamp < {{end_date}};
```

**Visualization:**
- Display: 142.5M tokens (large number)
- Subtitle: "Total saved in period"
- Trend: Show weekly comparison

### Card 3: Estimated Cost Reduction

**SQL Query:**

```sql
-- Query: Cost savings based on token pricing
-- Assumes $0.02 per 1K output tokens (adjust based on model)
SELECT
  SUM(baseline_tokens - output_tokens) AS tokens_saved,
  ROUND(
    SUM(baseline_tokens - output_tokens) / 1000.0 * 0.02,
    2
  ) AS cost_savings_usd,
  ROUND(
    SUM(baseline_tokens - output_tokens)::DOUBLE / NULLIF(SUM(baseline_tokens), 0)::DOUBLE * 100,
    1
  ) AS pct_cost_reduction
FROM main.fact_token_savings
WHERE execution_timestamp >= {{start_date}}
  AND execution_timestamp < {{end_date}};
```

**Visualization:**
- Display: $2,847 (large number with currency)
- Subtitle: "34.2% cost reduction"
- Note: "Based on $0.02/1K tokens"

### Card 4: Efficiency Leader (Best Run)

**SQL Query:**

```sql
-- Query: Run with highest token savings
SELECT
  run_id,
  ROUND(token_savings_pct * 100, 1) AS savings_pct,
  baseline_tokens - output_tokens AS tokens_saved,
  baseline_tokens,
  output_tokens
FROM main.fact_token_savings
WHERE execution_timestamp >= {{start_date}}
  AND execution_timestamp < {{end_date}}
ORDER BY token_savings_pct DESC
LIMIT 1;
```

**Visualization:**
- Display: Run ID + percentage (e.g., "run-123: 87.3%")
- Link to run detail page

## Charts

### Chart 1: Token Savings Over Time

**Type:** Line chart (dual axis)
**SQL Query:**

```sql
-- Query: Daily token usage and savings trends
SELECT
  DATE_TRUNC('day', execution_timestamp) AS date,
  AVG(baseline_tokens) AS avg_baseline,
  AVG(output_tokens) AS avg_output,
  AVG(baseline_tokens - output_tokens) AS avg_saved,
  ROUND(AVG(token_savings_pct) * 100, 1) AS avg_savings_pct,
  COUNT(*) AS run_count
FROM main.fact_token_savings
WHERE execution_timestamp >= {{start_date}}
  AND execution_timestamp < {{end_date}}
GROUP BY date
ORDER BY date;
```

**Visualization:**
- X-axis: Date
- Y-axis (left): Token count (baseline vs output, area chart)
- Y-axis (right): Savings percentage (line chart)
- Series:
  - Baseline Tokens (gray area, filled)
  - Output Tokens (blue area, filled)
  - Savings % (green line, overlay)
- Tooltip: Show exact values + run count

### Chart 2: Savings Distribution

**Type:** Histogram (bar chart)
**SQL Query:**

```sql
-- Query: Distribution of token savings across runs
SELECT
  CASE
    WHEN token_savings_pct >= 0.50 THEN '50%+'
    WHEN token_savings_pct >= 0.30 THEN '30-50%'
    WHEN token_savings_pct >= 0.10 THEN '10-30%'
    WHEN token_savings_pct >= 0 THEN '0-10%'
    ELSE 'Negative'
  END AS savings_bucket,
  COUNT(*) AS run_count,
  ROUND(AVG(token_savings_pct) * 100, 1) AS avg_savings_in_bucket,
  SUM(baseline_tokens - output_tokens) AS total_tokens_saved
FROM main.fact_token_savings
WHERE execution_timestamp >= {{start_date}}
  AND execution_timestamp < {{end_date}}
GROUP BY savings_bucket
ORDER BY
  CASE savings_bucket
    WHEN '50%+' THEN 1
    WHEN '30-50%' THEN 2
    WHEN '10-30%' THEN 3
    WHEN '0-10%' THEN 4
    ELSE 5
  END;
```

**Visualization:**
- X-axis: Savings buckets (0-10%, 10-30%, 30-50%, 50%+)
- Y-axis: Run count
- Color: Gradient (green for higher savings)
- Goal line: 30% target marker

### Chart 3: Savings vs Behavior Count (Correlation)

**Type:** Scatter plot
**SQL Query:**

```sql
-- Query: Correlation between behavior usage and token savings
SELECT
  ts.run_id,
  COALESCE(bu.behavior_count, 0) AS behavior_count,
  ts.token_savings_pct * 100 AS savings_pct,
  ts.baseline_tokens,
  ts.output_tokens,
  ts.baseline_tokens - ts.output_tokens AS tokens_saved
FROM main.fact_token_savings ts
LEFT JOIN main.fact_behavior_usage bu
  ON ts.run_id = bu.run_id
WHERE ts.execution_timestamp >= {{start_date}}
  AND ts.execution_timestamp < {{end_date}};
```

**Visualization:**
- X-axis: Behavior count (0-20)
- Y-axis: Token savings % (0-100)
- Point size: Baseline tokens (larger = more tokens)
- Color: Gradient based on savings %
- Trendline: Linear regression to show correlation
- Insight: "Each behavior → +X% savings on average"

### Chart 4: Cumulative Token Savings

**Type:** Area chart (cumulative)
**SQL Query:**

```sql
-- Query: Running total of tokens saved over time
WITH daily_savings AS (
  SELECT
    DATE(execution_timestamp) AS date,
    SUM(baseline_tokens - output_tokens) AS daily_saved
  FROM main.fact_token_savings
  WHERE execution_timestamp >= {{start_date}}
    AND execution_timestamp < {{end_date}}
  GROUP BY date
)
SELECT
  date,
  daily_saved,
  SUM(daily_saved) OVER (ORDER BY date) AS cumulative_saved
FROM daily_savings
ORDER BY date;
```

**Visualization:**
- X-axis: Date
- Y-axis: Cumulative tokens saved (millions)
- Series: Blue area chart showing growth
- Annotation: Mark milestones (10M, 50M, 100M tokens saved)

## Tables

### Table 1: Top Efficient Runs

**Type:** Data table (sorted)
**SQL Query:**

```sql
-- Query: Runs with highest absolute token savings
SELECT
  ts.run_id,
  ts.baseline_tokens,
  ts.output_tokens,
  ts.baseline_tokens - ts.output_tokens AS tokens_saved,
  ROUND(ts.token_savings_pct * 100, 1) AS savings_pct,
  COALESCE(bu.behavior_count, 0) AS behaviors_used,
  ts.execution_timestamp
FROM main.fact_token_savings ts
LEFT JOIN main.fact_behavior_usage bu
  ON ts.run_id = bu.run_id
WHERE ts.execution_timestamp >= {{start_date}}
  AND ts.execution_timestamp < {{end_date}}
ORDER BY tokens_saved DESC
LIMIT 50;
```

**Columns:**
- Run ID (link)
- Baseline Tokens
- Output Tokens
- Tokens Saved
- Savings % (color-coded)
- Behaviors Used
- Timestamp

### Table 2: Low Efficiency Runs (Anomalies)

**Type:** Data table (sorted)
**SQL Query:**

```sql
-- Query: Runs with low or negative savings (investigate)
SELECT
  ts.run_id,
  ts.baseline_tokens,
  ts.output_tokens,
  ts.baseline_tokens - ts.output_tokens AS tokens_saved,
  ROUND(ts.token_savings_pct * 100, 1) AS savings_pct,
  COALESCE(bu.behavior_count, 0) AS behaviors_used,
  ts.execution_timestamp
FROM main.fact_token_savings ts
LEFT JOIN main.fact_behavior_usage bu
  ON ts.run_id = bu.run_id
WHERE ts.execution_timestamp >= {{start_date}}
  AND ts.execution_timestamp < {{end_date}}
  AND ts.token_savings_pct < 0.10  -- Less than 10% savings
ORDER BY ts.token_savings_pct, tokens_saved
LIMIT 50;
```

**Use Case:** Identify runs where BCI didn't provide expected efficiency (potential issues or edge cases)

## Insights & Analysis

### ROI Calculation

**Query: 30-Day ROI**

```sql
-- Query: Return on investment for behavior-conditioned inference
WITH savings AS (
  SELECT
    SUM(baseline_tokens - output_tokens) AS total_tokens_saved,
    COUNT(*) AS total_runs,
    AVG(token_savings_pct) AS avg_savings_rate
  FROM main.fact_token_savings
  WHERE execution_timestamp >= CURRENT_DATE - INTERVAL '30 days'
)
SELECT
  total_tokens_saved,
  ROUND(total_tokens_saved / 1000.0 * 0.02, 2) AS cost_savings_usd,
  total_runs,
  ROUND(avg_savings_rate * 100, 1) AS avg_savings_pct,
  -- Assume BCI overhead is 5% additional infrastructure cost
  ROUND(total_tokens_saved / 1000.0 * 0.02 * 0.95, 2) AS net_savings_usd
FROM savings;
```

### Efficiency by Template

```sql
-- Query: Which templates benefit most from BCI
SELECT
  bu.template_id,
  COUNT(*) AS run_count,
  AVG(ts.token_savings_pct) * 100 AS avg_savings_pct,
  SUM(ts.baseline_tokens - ts.output_tokens) AS total_tokens_saved,
  AVG(bu.behavior_count) AS avg_behaviors_used
FROM main.fact_token_savings ts
JOIN main.fact_behavior_usage bu ON ts.run_id = bu.run_id
WHERE ts.execution_timestamp >= {{start_date}}
GROUP BY bu.template_id
ORDER BY avg_savings_pct DESC;
```

## Filters

1. **Date Range:** 7d, 30d, 90d, All time
2. **Min Savings % (slider):** 0-100%
3. **Template ID (dropdown):** All or specific
4. **Token Range (slider):** Filter by baseline token count

## Alerts

**Alert: Low Efficiency Detected**

Trigger when average savings drops below 20%:

```sql
SELECT AVG(token_savings_pct) * 100 AS avg_savings
FROM main.fact_token_savings
WHERE execution_timestamp >= CURRENT_DATE - INTERVAL '7 days'
HAVING avg_savings < 20.0;
```

**Alert: Milestone Reached**

Trigger when cumulative savings hits thresholds:

```sql
SELECT SUM(baseline_tokens - output_tokens) AS total_saved
FROM main.fact_token_savings
HAVING total_saved >= 100000000;  -- 100M tokens
```

## Setup Instructions

1. Create dashboard: "Token Savings Analysis"
2. Add 4 metric cards at top
3. Add line chart for daily trends
4. Add histogram for distribution
5. Add scatter plot for correlation analysis
6. Add cumulative savings chart
7. Add top/bottom performers tables
8. Connect filters
9. Set refresh to 10 minutes
10. Save to collection

## Referenced Behaviors

- `behavior_instrument_metrics_pipeline` – Token accounting feeds PRD metrics
- `behavior_validate_financial_impact` – ROI calculations inform budget decisions

---

**Dashboard Status:** ✅ Ready for deployment
**Last Updated:** 2025-10-20
