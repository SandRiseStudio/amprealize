# PRD KPI Summary Dashboard

> **Dashboard:** Executive Overview - All PRD Success Metrics
> **Refresh:** Every 5 minutes
> **Data Source:** Amprealize Analytics Warehouse (DuckDB)

## Dashboard Layout

```
┌─────────────────────────────────────────────────────────────┐
│  Amprealize PRD Metrics - Executive Summary                   │
│  Last Updated: {{current_timestamp}}                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │ Behavior    │  │ Token       │  │ Task        │        │
│  │ Reuse       │  │ Savings     │  │ Completion  │        │
│  │   72.5%     │  │   34.2%     │  │   85.3%     │        │
│  │ Target: 70% │  │ Target: 30% │  │ Target: 80% │        │
│  │ ✅ On Track │  │ ✅ On Track │  │ ✅ On Track │        │
│  └─────────────┘  └─────────────┘  └─────────────┘        │
│                                                             │
│  ┌─────────────┐  ┌─────────────────────────────────────┐ │
│  │ Compliance  │  │  Metric Trends (30 Days)            │ │
│  │ Coverage    │  │                                     │ │
│  │   96.8%     │  │  [Line chart showing 4 metrics]    │ │
│  │ Target: 95% │  │                                     │ │
│  │ ✅ On Track │  │                                     │ │
│  └─────────────┘  └─────────────────────────────────────┘ │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐ │
│  │  Run Volume by Status (30 Days)                       │ │
│  │  [Bar chart: Total, Completed, Failed]                │ │
│  └───────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Metrics Cards

### Card 1: Behavior Reuse Rate

**Type:** Number (with comparison)
**SQL Query:**

```sql
-- Query: Latest behavior reuse percentage
SELECT
  behavior_reuse_pct * 100 AS value,
  70 AS target,
  CASE
    WHEN behavior_reuse_pct >= 0.70 THEN 'On Track'
    WHEN behavior_reuse_pct >= 0.60 THEN 'At Risk'
    ELSE 'Off Track'
  END AS status,
  snapshot_time AS last_updated
FROM main.view_kpi_summary
ORDER BY snapshot_time DESC
LIMIT 1;
```

**Visualization:**
- Display: Large number (72.5%)
- Subtitle: "Target: 70%"
- Color: Green if ≥70%, Yellow if ≥60%, Red if <60%
- Trend arrow: Compare to previous period

### Card 2: Token Savings Rate

**Type:** Number (with comparison)
**SQL Query:**

```sql
-- Query: Latest average token savings
SELECT
  average_token_savings_pct * 100 AS value,
  30 AS target,
  CASE
    WHEN average_token_savings_pct >= 0.30 THEN 'On Track'
    WHEN average_token_savings_pct >= 0.20 THEN 'At Risk'
    ELSE 'Off Track'
  END AS status,
  snapshot_time AS last_updated
FROM main.view_kpi_summary
ORDER BY snapshot_time DESC
LIMIT 1;
```

**Visualization:**
- Display: Large number (34.2%)
- Subtitle: "Target: 30%"
- Color: Green if ≥30%, Yellow if ≥20%, Red if <20%
- Trend arrow: Compare to previous period

### Card 3: Task Completion Rate

**Type:** Number (with comparison)
**SQL Query:**

```sql
-- Query: Latest task completion rate
SELECT
  task_completion_rate_pct * 100 AS value,
  80 AS target,
  CASE
    WHEN task_completion_rate_pct >= 0.80 THEN 'On Track'
    WHEN task_completion_rate_pct >= 0.70 THEN 'At Risk'
    ELSE 'Off Track'
  END AS status,
  completed_runs,
  total_runs,
  snapshot_time AS last_updated
FROM main.view_kpi_summary
ORDER BY snapshot_time DESC
LIMIT 1;
```

**Visualization:**
- Display: Large number (85.3%)
- Subtitle: "Target: 80% | 123/144 runs"
- Color: Green if ≥80%, Yellow if ≥70%, Red if <70%
- Trend arrow: Compare to previous period

### Card 4: Compliance Coverage Rate

**Type:** Number (with comparison)
**SQL Query:**

```sql
-- Query: Latest compliance coverage
SELECT
  average_compliance_coverage_pct * 100 AS value,
  95 AS target,
  CASE
    WHEN average_compliance_coverage_pct >= 0.95 THEN 'On Track'
    WHEN average_compliance_coverage_pct >= 0.85 THEN 'At Risk'
    ELSE 'Off Track'
  END AS status,
  snapshot_time AS last_updated
FROM main.view_kpi_summary
ORDER BY snapshot_time DESC
LIMIT 1;
```

**Visualization:**
- Display: Large number (96.8%)
- Subtitle: "Target: 95%"
- Color: Green if ≥95%, Yellow if ≥85%, Red if <85%
- Trend arrow: Compare to previous period

## Charts

### Chart 1: Metric Trends (30 Days)

**Type:** Line chart (multi-series)
**SQL Query:**

```sql
-- Query: Daily KPI trends over last 30 days
SELECT
  DATE(snapshot_time) AS date,
  behavior_reuse_pct * 100 AS behavior_reuse,
  average_token_savings_pct * 100 AS token_savings,
  task_completion_rate_pct * 100 AS completion_rate,
  average_compliance_coverage_pct * 100 AS compliance_coverage
FROM main.view_kpi_summary
WHERE snapshot_time >= CURRENT_DATE - INTERVAL '30 days'
ORDER BY date;
```

**Visualization:**
- X-axis: Date
- Y-axis: Percentage (0-100)
- Series:
  - Behavior Reuse (blue line, target line at 70)
  - Token Savings (green line, target line at 30)
  - Completion Rate (orange line, target line at 80)
  - Compliance Coverage (purple line, target line at 95)
- Smoothing: 7-day rolling average (optional)

### Chart 2: Run Volume by Status (30 Days)

**Type:** Bar chart (stacked or grouped)
**SQL Query:**

```sql
-- Query: Daily run counts by status
SELECT
  DATE(execution_timestamp) AS date,
  COUNT(*) AS total_runs,
  SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_runs,
  SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_runs,
  SUM(CASE WHEN status IN ('pending', 'running') THEN 1 ELSE 0 END) AS in_progress_runs
FROM main.fact_execution_status
WHERE execution_timestamp >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY date
ORDER BY date;
```

**Visualization:**
- X-axis: Date
- Y-axis: Run count
- Series:
  - Completed (green bars)
  - Failed (red bars)
  - In Progress (yellow bars)
- Stack mode: Stacked or grouped (user preference)

## Filters

Add dashboard-level filters:

1. **Date Range:**
   - Default: Last 30 days
   - Options: Last 7 days, Last 30 days, Last 90 days, All time, Custom range

2. **Agent Role (optional):**
   - Default: All
   - Options: Strategist, Teacher, Student

3. **Template ID (optional):**
   - Default: All
   - Options: Dropdown of available templates

## Dashboard Settings

- **Auto-refresh:** Every 5 minutes
- **Cache TTL:** 60 seconds
- **Export:** Allow CSV/JSON export
- **Permissions:** All authenticated users (read-only)
- **Embedding:** Enabled for iframe embedding

## Setup Instructions

1. **Create Dashboard:**
   - In Metabase, click **+** → **Dashboard**
   - Name: "PRD KPI Summary"
   - Description: "Executive overview of Amprealize PRD success metrics"

2. **Add Metric Cards:**
   - Click **Add a Question** → **Custom Question**
   - Select data source: "Amprealize Analytics Warehouse"
   - Paste SQL query from each metric card above
   - Configure visualization (Number with goal)
   - Add to dashboard

3. **Add Charts:**
   - Repeat process for each chart
   - Configure line/bar chart settings
   - Position on dashboard grid

4. **Add Filters:**
   - Click **Add a Filter** → **Time**
   - Connect to all questions using `snapshot_time` or `execution_timestamp`
   - Set default to "Previous 30 Days"

5. **Configure Auto-Refresh:**
   - Dashboard settings → **Auto-refresh**
   - Set to 5 minutes

6. **Save and Share:**
   - Click **Save**
   - Set permissions (Collection: "PRD Metrics", Public: No)
   - Generate shareable link or embed code

## Alerts (Optional)

Configure Metabase alerts to notify when metrics fall below targets:

```sql
-- Alert: Behavior Reuse Below Target
SELECT
  behavior_reuse_pct * 100 AS current_value,
  'Behavior Reuse Rate dropped below 70%' AS alert_message
FROM main.view_kpi_summary
ORDER BY snapshot_time DESC
LIMIT 1
HAVING behavior_reuse_pct < 0.70;
```

Set alert to email/Slack when query returns results.

## Sample Screenshot

```
┌────────────────────────────────────────────────┐
│ Amprealize PRD Metrics                            │
├────────────────────────────────────────────────┤
│ [72.5%]  [34.2%]  [85.3%]  [96.8%]            │
│ Behavior  Token   Task    Compliance           │
│                                                │
│ [Line chart showing upward trends]             │
│ [Bar chart showing run volumes]                │
└────────────────────────────────────────────────┘
```

## Referenced Behaviors

- `behavior_instrument_metrics_pipeline` – KPI queries mapped to PRD targets
- `behavior_update_docs_after_changes` – Dashboard documentation

---

**Dashboard Status:** ✅ Ready for deployment
**Last Updated:** 2025-10-20
