# Amprealize Cost Model

**Status**: ✅ Production
**Last Updated**: 2025-11-26
**Related Docs**: [EPIC_8_12_COST_OPTIMIZATION.md](./EPIC_8_12_COST_OPTIMIZATION.md), [COST_ALERT_RUNBOOK.md](./COST_ALERT_RUNBOOK.md)

## Overview

Amprealize tracks and optimizes costs across multiple dimensions: LLM token usage, API calls, execution time, and infrastructure. This document describes the cost calculation methodology, pricing models, and budget thresholds.

## Cost Calculation Methodology

### Token-Based Costs

| Provider | Model | Input (per 1K tokens) | Output (per 1K tokens) |
|----------|-------|----------------------|------------------------|
| OpenAI | GPT-4 | $0.03 | $0.06 |
| OpenAI | GPT-4-32K | $0.06 | $0.12 |
| OpenAI | GPT-3.5-Turbo | $0.001 | $0.002 |
| Anthropic | Claude-3-Opus | $0.015 | $0.075 |
| Anthropic | Claude-3-Sonnet | $0.003 | $0.015 |
| Anthropic | Claude-3-Haiku | $0.00025 | $0.00125 |

### Service-Level Costs

Each Amprealize service has an estimated cost profile:

| Service | Primary Cost Driver | Estimated Cost/Operation |
|---------|---------------------|-------------------------|
| BehaviorService | Embedding lookups, retrieval | $0.001 - $0.005 |
| ActionService | Execution recording, compliance checks | $0.0005 - $0.002 |
| RunService | State persistence, SSE broadcasting | $0.0001 - $0.0005 |
| ComplianceService | Policy evaluation | $0.0002 - $0.001 |
| RazeLogger | Log storage, queries | $0.00001/log entry |
| BreakerAmp | Container orchestration | $0.001/container-minute |

### Formula: Total Run Cost

```
run_cost = Σ(service_costs) + token_cost

token_cost = (input_tokens × input_rate / 1000) + (output_tokens × output_rate / 1000)

service_costs = Σ(operation_count × cost_per_operation) for each service
```

### Formula: Savings vs Baseline

```
baseline_tokens = estimated_tokens_without_behavior_conditioning
output_tokens = actual_tokens_used
token_savings = baseline_tokens - output_tokens
savings_pct = (token_savings / baseline_tokens) × 100
savings_usd = token_savings × weighted_avg_token_rate / 1000
```

## Budget Thresholds

### Environment Variables

Configure via `.env` or system environment:

```bash
# Daily budget threshold (default: $80)
AMPREALIZE_COST_DAILY_BUDGET_USD=80.0

# Monthly budget threshold (default: $2000)
AMPREALIZE_COST_MONTHLY_BUDGET_USD=2000.0

# Alert threshold percentage (default: 80%)
AMPREALIZE_COST_ALERT_THRESHOLD_PCT=0.80
```

### Budget Calculation

| Budget Period | Default Value | Alert Threshold (80%) |
|--------------|---------------|----------------------|
| Daily | $80.00 | $64.00 |
| Monthly | $2,000.00 | $1,600.00 |

### Alert Conditions

1. **Daily Budget Warning**: Triggered when daily spend exceeds 80% of `AMPREALIZE_COST_DAILY_BUDGET_USD`
2. **Daily Budget Exceeded**: Triggered when daily spend exceeds `AMPREALIZE_COST_DAILY_BUDGET_USD`
3. **Monthly Budget Warning**: Triggered when monthly spend exceeds 80% of `AMPREALIZE_COST_MONTHLY_BUDGET_USD`
4. **Monthly Budget Exceeded**: Triggered when monthly spend exceeds `AMPREALIZE_COST_MONTHLY_BUDGET_USD`

## Data Schema

### DuckDB Fact Tables

#### fact_resource_usage
Tracks resource consumption per operation:

```sql
CREATE TABLE fact_resource_usage (
    usage_id VARCHAR PRIMARY KEY,
    run_id VARCHAR,
    service_name VARCHAR,      -- BehaviorService, ActionService, etc.
    operation_name VARCHAR,    -- retrieve_behaviors, execute_action
    token_count INTEGER,
    api_calls INTEGER,
    execution_time_ms INTEGER,
    estimated_cost_usd DECIMAL(10, 6),
    timestamp TIMESTAMP NOT NULL
);
```

#### fact_cost_allocation
Aggregate cost per run:

```sql
CREATE TABLE fact_cost_allocation (
    run_id VARCHAR PRIMARY KEY,
    template_id VARCHAR,
    service_costs VARCHAR,     -- JSON: {"BehaviorService": 0.003}
    total_cost_usd DECIMAL(10, 6),
    savings_vs_baseline_usd DECIMAL(10, 6),
    timestamp TIMESTAMP NOT NULL
);
```

#### dim_cost_model
Configurable pricing rates:

```sql
CREATE TABLE dim_cost_model (
    service_name VARCHAR PRIMARY KEY,
    cost_per_1k_input_tokens DECIMAL(10, 6),
    cost_per_1k_output_tokens DECIMAL(10, 6),
    cost_per_api_call DECIMAL(10, 6),
    updated_at TIMESTAMP NOT NULL
);
```

## Surface Availability

Cost analytics are exposed across all surfaces for cross-surface parity:

| Surface | Access Method |
|---------|--------------|
| CLI | `amprealize analytics cost-by-service`, `cost-per-run`, `roi-summary`, `daily-costs`, `top-expensive` |
| REST API | `GET /v1/analytics/cost-by-service`, `/cost-per-run`, `/roi-summary`, `/daily-costs`, `/top-expensive` |
| MCP | `analytics.costByService`, `analytics.costPerRun`, `analytics.roiSummary`, `analytics.dailyCosts`, `analytics.topExpensive` |
| Metabase | Cost Optimization Dashboard (6 cards) |
| Grafana | cost-optimization-dashboard.json (6 panels with alerts) |
| VS Code | Cost Tracker tree view (customer-facing) |

## ROI Calculation

### Monthly ROI Formula

```
ROI = Total Token Savings ($) / Total Infrastructure Cost ($)
```

### Example Calculation

| Metric | Value |
|--------|-------|
| Total Runs (30 days) | 10,000 |
| Avg Tokens Saved/Run | 450 |
| Total Tokens Saved | 4,500,000 |
| Weighted Token Rate | $0.04/1K |
| Token Savings ($) | $180.00 |
| Infrastructure Cost | $2,000.00 |
| ROI Ratio | 0.09x (9%) |

> **Note**: ROI improves significantly with higher token savings rates (PRD target: 30%) and increased run volume.

## Customer-Facing Cost Visibility

Customers can view their cost analytics in the VS Code extension:

1. **Summary View**: Daily/weekly/monthly spend, budget status
2. **Service Breakdown**: Cost allocation by service
3. **Top Workflows**: Most expensive workflow templates
4. **Trend View**: Daily cost trend with sparkline visualization

### Privacy Considerations

- Costs are calculated per organization/tenant
- No cross-tenant cost data is exposed
- Opt-in telemetry respects user preferences
- Cost data is aggregated (not per-user breakdown)

## Updating the Cost Model

### Adding a New Service

1. Add entry to `dim_cost_model` table
2. Update `TelemetryKPIProjector` to emit `fact_resource_usage` for new service
3. Update cost calculation formulas in warehouse methods
4. Add tests in `tests/test_telemetry_kpi_projector.py`

### Updating Token Rates

1. Update `dim_cost_model` entries with new rates
2. Document rate change in this file
3. Backfill is NOT supported (new rates apply to new data only)

---

**Behaviors Referenced**: `behavior_instrument_metrics_pipeline`, `behavior_align_storage_layers`, `behavior_externalize_configuration`
