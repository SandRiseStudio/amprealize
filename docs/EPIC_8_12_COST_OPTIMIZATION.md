# Epic 8.12: Cost Optimization Dashboard

**Status**: 🚧 In Progress
**Timeline**: 1 week (5 days)
**Priority**: P1
**Owner**: Engineering + Finance
**PRD Reference**: Goal 2 (30% token savings), Cost analytics open question

## Mission

Build cost optimization infrastructure that tracks resource usage, calculates ROI, alerts on budget overruns, and surfaces actionable cost insights to both internal teams and customers—enabling data-driven decisions around token savings and infrastructure spend.

### Latest Progress
- **Telemetry KPI Projector now emits cost + resource facts**: `amprealize/analytics/telemetry_kpi_projector.py` writes `fact_resource_usage` and `fact_cost_allocation` rows via `_create_resource_usage_facts()` and `_create_cost_allocation_fact()` helpers, ensuring timestamps default to `_DEFAULT_TIMESTAMP` when events omit them.
- **Resource/cost regression tests**: `tests/test_telemetry_kpi_projector.py` now verifies resource usage records per run, validates cost allocation summaries, and confirms summary totals reflect projected costs (to be executed via `pytest` following `TESTING_GUIDE.md`).
- **Schema alignment**: `amprealize/analytics/__init__.py` exports `TelemetryKPIProjector`, keeping the analytics package interface consistent with DuckDB cost schema expectations.

_Behaviors referenced_: `behavior_instrument_metrics_pipeline`, `behavior_align_storage_layers`

## Success Criteria

- ✅ Cost Optimization Dashboard operational in Metabase with 6+ cost allocation views
- ✅ Resource usage tracking by service/feature (TimescaleDB continuous aggregates)
- ✅ Budget alerts configured in Grafana ($80/day threshold for $2400/month budget)
- ✅ 30% token savings metric visible and accurate (PRD Goal 2)
- ✅ ROI calculation methodology documented (monthly_savings / infrastructure_cost)
- ✅ Customer-facing cost analytics strategy defined (opt-in telemetry, privacy-preserving)
- ✅ Integration with existing Token Savings Analysis dashboard validated

## Architecture Overview

### Existing Infrastructure (Leverage)

#### Token Savings Analysis Dashboard (Operational)
- **Platform**: Metabase v0.48.0
- **Data Source**: DuckDB warehouse (fact_token_savings table)
- **Current Metrics**:
  * Token Savings Rate (avg_savings_rate_pct) - **PRD Target: 30%**
  * Total tokens saved (baseline_tokens - output_tokens)
  * Runs with behavior usage
- **Location**: http://localhost:3000
- **Automation**: `scripts/create_metabase_dashboards.py` (~610 lines)

#### Telemetry Warehouse (Phase 5 Complete)
- **Backend**: TimescaleDB (postgres-telemetry:5432)
- **Storage**: Hypertables with 7-day chunks, compression (3-5x reduction)
- **Event Types**: behavior_retrieved, plan_created, execution_update, reflection_submitted, action_recorded
- **Continuous Aggregates**:
  * telemetry_events_hourly (event counts, unique actors/runs/sessions)
  * execution_traces_hourly (span counts, latency percentiles, total_tokens)
  * telemetry_events_daily (daily rollups)
- **Refresh Policies**: 10-minute refresh for hourly, 1-hour refresh for daily
- **Retention**: 7 days hot (Kafka), 3 years warm (warehouse), 7 years cold (S3 WORM)

#### DuckDB Analytics Warehouse (Operational)
- **Schema**: `docs/analytics/prd_metrics_schema_duckdb.sql`
- **Fact Tables**:
  * fact_behavior_usage (run_id, behavior_ids, behavior_count, baseline_tokens)
  * fact_token_savings (run_id, output_tokens, baseline_tokens, token_savings_pct)
  * fact_execution_status (run_id, status, actor_surface, actor_role)
  * fact_compliance_steps (checklist_id, step_id, coverage_score)
- **KPI Views**:
  * view_behavior_reuse_rate (PRD target: 70%)
  * view_token_savings_rate (PRD target: 30%) ✅
  * view_completion_rate (PRD target: 80%)
  * view_compliance_coverage_rate (PRD target: 95%)

#### Telemetry KPI Projector (Operational)
- **Component**: `amprealize/analytics/telemetry_kpi_projector.py`
- **Run Accumulator**: Aggregates events per run_id
- **Fields Tracked**: behavior_ids, token_savings_pct, output_tokens, baseline_tokens, status
- **Pipeline**: Kafka events → Flink consumer → TelemetryKPIProjector.project_batch() → DuckDB writes
- **Validation**: End-to-end tests passing (24 events processed, 4 fact tables populated)

#### Analytics Warehouse Service (Operational)
- **Component**: `amprealize/analytics/warehouse.py` (AnalyticsWarehouse class)
- **Methods**: get_token_savings(start_date, end_date, actor_role, actor_surface)
- **Surfaces**: Web API (`GET /v1/analytics/token-savings`), CLI (`amprealize analytics token-savings`), MCP tool
- **Contracts**: `amprealize/metrics_contracts.py` (MetricsSummary with 14 PRD KPI fields)

### New Infrastructure (Epic 8.12 Deliverables)

#### 1. Enhanced DuckDB Cost Schema (Task 2)
**New Tables**:
```sql
-- Resource usage tracking by service/operation
CREATE TABLE fact_resource_usage (
    usage_id VARCHAR PRIMARY KEY,
    run_id VARCHAR,
    service_name VARCHAR,  -- BehaviorService, ActionService, RunService, etc.
    operation_name VARCHAR,  -- retrieve_behaviors, execute_action, etc.
    token_count INTEGER,
    api_calls INTEGER,
    execution_time_ms INTEGER,
    estimated_cost_usd DECIMAL(10, 6),
    timestamp TIMESTAMP NOT NULL
);

-- Cost allocation per run (aggregate of service costs)
CREATE TABLE fact_cost_allocation (
    run_id VARCHAR PRIMARY KEY,
    template_id VARCHAR,
    service_costs VARCHAR,  -- JSON: {"BehaviorService": 0.003, "ActionService": 0.001}
    total_cost_usd DECIMAL(10, 6),
    savings_vs_baseline_usd DECIMAL(10, 6),  -- 30% token savings = $ saved
    timestamp TIMESTAMP NOT NULL
);

-- Cost model dimension (configurable pricing)
CREATE TABLE dim_cost_model (
    service_name VARCHAR PRIMARY KEY,
    cost_per_1k_input_tokens DECIMAL(10, 6),  -- e.g., $0.03 for GPT-4
    cost_per_1k_output_tokens DECIMAL(10, 6),  -- e.g., $0.06 for GPT-4
    cost_per_api_call DECIMAL(10, 6),  -- e.g., $0.0001 for REST call
    updated_at TIMESTAMP NOT NULL
);
```

**New KPI Views**:
```sql
-- View: Cost by Service (pie chart)
CREATE VIEW view_cost_by_service AS
SELECT
    service_name,
    SUM(estimated_cost_usd) AS total_cost_usd,
    COUNT(*) AS operation_count,
    AVG(execution_time_ms) AS avg_execution_time_ms
FROM fact_resource_usage
GROUP BY service_name
ORDER BY total_cost_usd DESC;

-- View: Cost per Run (line chart over time)
CREATE VIEW view_cost_per_run AS
SELECT
    run_id,
    template_id,
    total_cost_usd,
    savings_vs_baseline_usd,
    (savings_vs_baseline_usd / NULLIF(total_cost_usd, 0)) * 100 AS savings_pct,
    timestamp
FROM fact_cost_allocation
ORDER BY timestamp DESC;

-- View: ROI Analysis (infrastructure cost vs token savings)
CREATE VIEW view_roi_analysis AS
SELECT
    SUM(savings_vs_baseline_usd) AS total_savings_usd,
    COUNT(DISTINCT run_id) AS total_runs,
    SUM(total_cost_usd) AS total_infrastructure_cost_usd,
    (SUM(savings_vs_baseline_usd) / NULLIF(SUM(total_cost_usd), 0)) AS roi_ratio
FROM fact_cost_allocation
WHERE savings_vs_baseline_usd IS NOT NULL;
```

**Behavior Reference**: `behavior_align_storage_layers` (schema discipline, field naming consistency)

#### 2. Extended Analytics Warehouse (Task 3)
**New Methods**:
```python
class AnalyticsWarehouse:
    def get_cost_by_service(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        service_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Query cost allocation by service from view_cost_by_service."""
        # SQL: SELECT * FROM view_cost_by_service WHERE timestamp BETWEEN ...
        pass

    def get_cost_per_run(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        template_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Query cost per run from view_cost_per_run."""
        # SQL: SELECT * FROM view_cost_per_run WHERE timestamp BETWEEN ...
        pass

    def get_roi_summary(self) -> Dict[str, Any]:
        """Calculate ROI summary from view_roi_analysis."""
        # SQL: SELECT * FROM view_roi_analysis
        # Returns: {total_savings_usd, total_infrastructure_cost_usd, roi_ratio}
        pass
```

**API Endpoints**:
- `GET /v1/analytics/cost-by-service` (query params: start_date, end_date, service_name)
- `GET /v1/analytics/cost-per-run` (query params: start_date, end_date, template_id)
- `GET /v1/analytics/roi-summary` (no params, global summary)

**CLI Commands**:
- `amprealize analytics cost-by-service [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD] [--service SERVICE]`
- `amprealize analytics cost-per-run [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD] [--template TEMPLATE_ID]`
- `amprealize analytics roi-summary`

**Behavior Reference**: `behavior_wire_cli_to_orchestrator` (CLI/API/MCP parity)

#### 3. Cost Optimization Dashboard (Task 4)
**Metabase Dashboard**: "Cost Optimization Dashboard" (6 cards)

**Card 1: Cost by Service (Bar Chart)**
- SQL: `SELECT * FROM view_cost_by_service`
- Visualization: Bar chart (X: service_name, Y: total_cost_usd)
- Purpose: Identify most expensive services

**Card 2: Cost per Run (Line Chart)**
- SQL: `SELECT timestamp, AVG(total_cost_usd) FROM fact_cost_allocation GROUP BY DATE(timestamp)`
- Visualization: Line chart (X: date, Y: avg_cost_usd)
- Purpose: Track cost trends over time

**Card 3: Token Savings ROI (Gauge)**
- SQL: `SELECT roi_ratio FROM view_roi_analysis`
- Visualization: Gauge (0-5x ROI, target: >1.0x)
- Purpose: Show return on investment from token savings

**Card 4: Budget vs Actual (Progress Bar)**
- SQL: `SELECT SUM(total_cost_usd) FROM fact_cost_allocation WHERE timestamp >= DATE_TRUNC('month', NOW())`
- Visualization: Progress bar (monthly budget $2400, current spend)
- Purpose: Track monthly budget adherence

**Card 5: Cost Trend 30-Day (Line Chart)**
- SQL: `SELECT DATE(timestamp), SUM(total_cost_usd) FROM fact_cost_allocation WHERE timestamp >= NOW() - INTERVAL '30 days' GROUP BY DATE(timestamp)`
- Visualization: Line chart with trend line
- Purpose: Identify cost anomalies

**Card 6: Top 10 Expensive Workflows (Table)**
- SQL: `SELECT template_id, SUM(total_cost_usd), COUNT(*) FROM fact_cost_allocation GROUP BY template_id ORDER BY SUM(total_cost_usd) DESC LIMIT 10`
- Visualization: Table with sorting
- Purpose: Optimize high-cost workflows

**Deployment**: Auto-create via `scripts/create_metabase_dashboards.py` (extend existing script)

**Behavior Reference**: `behavior_instrument_metrics_pipeline` (dashboard instrumentation, PRD KPI alignment)

#### 4. Budget Alerts (Task 5)
**Grafana Dashboard**: `web-console/dashboard/grafana/cost-alerts-dashboard.json`

**Alert 1: Daily Budget Threshold**
- **Condition**: `SUM(total_cost_usd) > 80` (daily budget for $2400/month = $80/day)
- **Frequency**: Check every 1 hour
- **Notification**: Slack webhook + email to finance@amprealize.local
- **Message**: "⚠️ Daily cost budget exceeded: $X / $80"

**Alert 2: Token Usage Spike**
- **Condition**: `(hourly_tokens - prev_hourly_tokens) / prev_hourly_tokens > 0.20` (20% increase hour-over-hour)
- **Frequency**: Check every 10 minutes
- **Notification**: Slack webhook to #ops-alerts
- **Message**: "📈 Token usage spike detected: +X% in last hour"

**Alert 3: Cost Anomaly Detection**
- **Condition**: `total_cost_usd > AVG(total_cost_usd) + 2*STDDEV(total_cost_usd)` (2 standard deviations above 7-day mean)
- **Frequency**: Check every 1 hour
- **Notification**: Email to engineering-leads@amprealize.local
- **Message**: "🚨 Cost anomaly detected: $X (mean: $Y, stddev: $Z)"

**Configuration**: Environment variables (ALERT_DAILY_BUDGET_USD=80, ALERT_SPIKE_THRESHOLD_PCT=20, ALERT_ANOMALY_SIGMA=2)

**Runbook**: `docs/COST_ALERT_RUNBOOK.md` (escalation, mitigation steps)

**Behavior Reference**: `behavior_externalize_configuration` (alert thresholds configurable)

#### 5. Cost Model Documentation (Task 6)
**Document**: `docs/COST_MODEL.md`

**Infrastructure Costs** (Monthly Baseline):
- PostgreSQL (telemetry + behaviors + actions): $300-500
- Kafka + Flink (streaming pipeline): $200-400
- TimescaleDB (warm storage): $200-300
- DuckDB (embedded, zero cost): $0
- Metabase/Grafana (dashboards): $100-200
- S3 (cold storage, WORM): $100-200
- Compute (API/CLI/MCP servers): $600-900
- **Total**: $1,500-2,500/month

**Token Pricing** (OpenAI GPT-4):
- Input tokens: $0.03 per 1,000 tokens
- Output tokens: $0.06 per 1,000 tokens
- Average task baseline: 200 input + 2,500 output tokens = $0.156 per task
- With 30% token savings: 200 input + 1,750 output tokens = $0.111 per task
- **Savings**: $0.045 per task (29% cost reduction)

**Monthly Savings Calculation** (10,000 tasks/month):
- Baseline cost: 10,000 tasks × $0.156 = $1,560/month
- Optimized cost: 10,000 tasks × $0.111 = $1,110/month
- **Token savings**: $450/month (30% reduction meets PRD Goal 2 ✅)
- **ROI**: $450 / $2,000 infrastructure = 0.225x (22.5% return)

**ROI Formula**:
```
monthly_savings = (baseline_tokens - output_tokens) × cost_per_token
infrastructure_cost = sum(service_costs)
roi_ratio = monthly_savings / infrastructure_cost
```

**Customer-Facing Cost Analytics Strategy**:
- **Opt-In Telemetry**: Customers explicitly consent to cost tracking (CMD-007 consent UX)
- **Privacy-Preserving Metrics**: Aggregate cost reports (no PII, no code snippets)
- **Savings Reports**: Monthly PDF showing token savings % and estimated $ saved
- **Pricing Transparency**: Surface cost model in UI (e.g., "$0.03/1k input tokens")
- **Cost Allocation**: Allow customers to allocate costs to projects/teams
- **Budget Alerts**: Customers set their own budget thresholds

**Behavior Reference**: `behavior_validate_financial_impact` (ROI validation, Finance approval)

#### 6. Cost Instrumentation (Task 7)
**Telemetry KPI Projector Updates**:
```python
@dataclass
class _RunAccumulator:
    # ... existing fields ...
    cost_usd: Optional[float] = None  # NEW: Track estimated cost per run

class TelemetryKPIProjector:
    def project_batch(self, events: List[Dict[str, Any]]) -> _Projection:
        # ... existing logic ...

        # NEW: Calculate cost from token usage
        if accumulator.output_tokens and accumulator.baseline_tokens:
            input_cost = (accumulator.baseline_tokens / 1000) * 0.03  # $0.03/1k
            output_cost = (accumulator.output_tokens / 1000) * 0.06  # $0.06/1k
            accumulator.cost_usd = input_cost + output_cost
```

**Telemetry Event Payload Extension**:
```json
{
  "event_type": "execution_update",
  "payload": {
    "output_tokens": 1750,
    "baseline_tokens": 200,
    "token_savings_pct": 0.30,
    "estimated_cost_usd": 0.111  // NEW FIELD
  }
}
```

**TimescaleDB Continuous Aggregate Extension**:
```sql
-- execution_traces_hourly: Add cost rollups
SELECT
    time_bucket('1 hour', trace_timestamp) AS hour,
    SUM(token_count) AS total_tokens,
    SUM(estimated_cost_usd) AS total_cost_usd,  -- NEW
    AVG(estimated_cost_usd) AS avg_cost_per_span  -- NEW
FROM execution_traces
GROUP BY hour;
```

**Validation**: End-to-end test (Kafka → Flink → DuckDB) confirms cost_usd field populated

**Behavior Reference**: `behavior_instrument_metrics_pipeline` (telemetry instrumentation, event schema)

## Implementation Timeline (1 week = 5 days)

### Day 1: Planning + Review (Tasks 1-2)
- **Morning**: Define Epic 8.12 scope, review existing infrastructure (this document) ✅
- **Afternoon**: Enhance DuckDB schema (fact_resource_usage, fact_cost_allocation, dim_cost_model, 3 KPI views)
- **Deliverables**: `prd_metrics_schema_duckdb.sql` updated, migration tested locally
- **Behaviors**: `behavior_align_storage_layers`, `behavior_handbook_compliance_prompt`

### Day 2: Warehouse + API (Task 3)
- **Morning**: Extend AnalyticsWarehouse with `get_cost_by_service()`, `get_cost_per_run()`, `get_roi_summary()`
- **Afternoon**: Add REST API endpoints (`/v1/analytics/cost-*`) and CLI commands (`amprealize analytics cost-*`)
- **Deliverables**: `amprealize/analytics/warehouse.py` updated, API/CLI parity validated, integration tests passing
- **Behaviors**: `behavior_wire_cli_to_orchestrator`, `behavior_instrument_metrics_pipeline`

### Day 3: Dashboards (Task 4)
- **Morning**: Extend `scripts/create_metabase_dashboards.py` with Cost Optimization Dashboard (6 cards)
- **Afternoon**: Deploy dashboard to Metabase, validate card queries, screenshot for docs
- **Deliverables**: Cost Optimization Dashboard operational at http://localhost:3000, automation script updated
- **Behaviors**: `behavior_instrument_metrics_pipeline`, `behavior_update_docs_after_changes`

### Day 4: Alerts + Cost Model (Tasks 5-6)
- **Morning**: Create Grafana dashboard JSON with 3 alert rules (daily budget, spike, anomaly)
- **Afternoon**: Document cost model (`COST_MODEL.md`), define ROI formula, customer-facing strategy
- **Deliverables**: `cost-alerts-dashboard.json`, `COST_MODEL.md`, `COST_ALERT_RUNBOOK.md` created
- **Behaviors**: `behavior_externalize_configuration`, `behavior_validate_financial_impact`

### Day 5: Instrumentation + Validation (Tasks 7-9)
- **Morning**: Extend TelemetryKPIProjector with cost tracking, update event schema, add TimescaleDB aggregates
- **Afternoon**: Validate PRD Goal 2 (30% token savings visible), smoke test dashboards, update docs
- **Deliverables**: End-to-end cost tracking validated, `PRD_ALIGNMENT_LOG.md` updated, Epic 8.12 complete ✅
- **Behaviors**: `behavior_instrument_metrics_pipeline`, `behavior_validate_financial_impact`, `behavior_update_docs_after_changes`

## Dependencies & Risks

### Dependencies (All Operational ✅)
- ✅ Token Savings Analysis dashboard (operational, Metabase)
- ✅ TimescaleDB telemetry warehouse (Phase 5 complete)
- ✅ DuckDB analytics warehouse (fact_token_savings operational)
- ✅ Metabase automation framework (`scripts/create_metabase_dashboards.py`)
- ✅ TelemetryKPIProjector (Kafka → Flink → DuckDB pipeline operational)

### Risks & Mitigations

**Risk 1: Scope Creep (Customer-Facing Analytics)**
- **Impact**: Customer-facing cost analytics could balloon into multi-week effort
- **Mitigation**: Define MVP scope (opt-in telemetry, aggregated reports only), defer advanced features (cost allocation by team, multi-tenant dashboards) to Epic 9.x
- **Status**: ✅ Mitigated (customer-facing strategy documented, implementation deferred)

**Risk 2: Budget Alert Configuration**
- **Impact**: Alert thresholds may require infrastructure changes if Grafana not available
- **Mitigation**: Use existing Grafana setup (service-health-dashboard.json exists), externalize thresholds via env vars
- **Status**: ✅ Mitigated (Grafana operational, alert JSON schema validated)

**Risk 3: Cost Model Accuracy**
- **Impact**: Token pricing changes (OpenAI rate updates) could invalidate cost calculations
- **Mitigation**: Externalize pricing in `dim_cost_model` table, support manual updates, document refresh process
- **Status**: ✅ Mitigated (dim_cost_model schema designed for updates)

**Risk 4: Performance (Cost Queries)**
- **Impact**: Cost allocation queries could slow down analytics endpoints
- **Mitigation**: Leverage DuckDB indexes (view_cost_by_service pre-aggregated), add query caching (30s TTL), monitor query latency
- **Status**: ⚠️ Monitor (validate query performance during Day 3 dashboard deployment)

## Validation Checklist (Task 8)

Smoke tests to confirm Cost Optimization Dashboard operational:

- [ ] 30% token savings metric visible in Token Savings Analysis dashboard (PRD Goal 2 ✅)
- [ ] Cost allocation by service accurate (fact_resource_usage populated, view_cost_by_service returns data)
- [ ] ROI calculation matches documented methodology (view_roi_analysis.roi_ratio = monthly_savings / infrastructure_cost)
- [ ] Budget alerts trigger correctly (Grafana alert fires when daily spend > $80)
- [ ] Customer-facing analytics strategy documented (`COST_MODEL.md` includes opt-in telemetry, privacy-preserving metrics)
- [ ] CLI commands work (`amprealize analytics cost-by-service` returns JSON)
- [ ] API endpoints work (`GET /v1/analytics/roi-summary` returns 200 OK)
- [ ] Metabase dashboard displays all 6 cards (Cost by Service, Cost per Run, ROI Gauge, Budget vs Actual, Cost Trend, Top 10 Workflows)

**Behavior Reference**: `behavior_validate_financial_impact`, `behavior_handbook_compliance_prompt`

## Documentation Updates (Task 9)

Files to update upon Epic 8.12 completion:

- [ ] `PRD_ALIGNMENT_LOG.md`: Add Epic 8.12 completion entry (cost dashboard deployed, ROI methodology, budget alerts operational)
- [ ] `BUILD_TIMELINE.md`: Add artifact list (schema SQL, warehouse methods, Metabase script, Grafana JSON, cost model doc)
- [ ] `WORK_STRUCTURE.md`: Update Epic 8.12 status to ✅ Complete (lines 1374-1382)
- [ ] `README.md`: Add user guide section for cost dashboard access (Metabase URL, CLI commands)
- [ ] `PROGRESS_TRACKER.md`: Mark Epic 8.12 complete with evidence links (dashboard screenshots, ROI calculations)
- [ ] `docs/COST_MODEL.md`: Created (infrastructure costs, token pricing, ROI formula, customer strategy)
- [ ] `docs/COST_ALERT_RUNBOOK.md`: Created (alert escalation, mitigation steps)

**Behavior Reference**: `behavior_update_docs_after_changes`

## Behaviors Applied

Epic 8.12 implementation follows these handbook behaviors:

1. **behavior_instrument_metrics_pipeline** - Cost tracking telemetry, dashboard instrumentation, PRD KPI alignment
2. **behavior_validate_financial_impact** - ROI analysis, budget validation, Finance approval
3. **behavior_align_storage_layers** - Schema discipline (DuckDB fact tables, TimescaleDB continuous aggregates)
4. **behavior_externalize_configuration** - Alert thresholds, pricing model, budget configuration
5. **behavior_wire_cli_to_orchestrator** - CLI/API/MCP parity for cost analytics endpoints
6. **behavior_update_docs_after_changes** - Documentation updates (PRD_ALIGNMENT_LOG, BUILD_TIMELINE, WORK_STRUCTURE)
7. **behavior_handbook_compliance_prompt** - Implementation documentation, checklist adherence

## Next Steps

After Epic 8.12 completion:

1. **Epic 6.5 - Multi-IDE MCP Extension Distribution** (1 week)
2. **Analytics Enhancements** (Epic 9.x):
   - Multi-tenant cost allocation (allocate costs to projects/teams)
   - Advanced ROI modeling (forecast savings, payback period)
   - Customer-facing cost dashboard (embed in Web UI)
   - Cost optimization recommendations (e.g., "Switch to GPT-3.5 for 90% of tasks saves $X/month")
3. **Finance Integration**:
   - Export cost data to accounting systems (QuickBooks, Xero)
   - Automated monthly cost reports (PDF generation, email delivery)
   - Cost center tagging (department, project, customer)

---

**Last Updated**: 2025-01-XX
**Epic 8.12 Status**: 🚧 In Progress (Day 1 of 5)
**Completion**: 11% (1/9 tasks)
