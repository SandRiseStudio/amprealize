-- Amprealize PRD Metrics Schema - DuckDB Edition
-- Purpose: Fact tables for measuring PRD success metrics (behavior reuse, token savings, completion rate, compliance coverage)
-- Backend: DuckDB (embedded, zero-cost analytics engine)
-- Phase: Phase 1 Local Development
-- Note: Schema aligned with TelemetryKPIProjector run-level aggregates

-- Fact: Behavior Usage (Run-Level Aggregate)
-- Tracks behavior usage per workflow run
-- Supports: 70% behavior reuse target, behavior retrieval effectiveness
CREATE TABLE IF NOT EXISTS fact_behavior_usage (
    run_id VARCHAR PRIMARY KEY,
    template_id VARCHAR,
    template_name VARCHAR,
    behavior_ids VARCHAR,  -- JSON array of behavior IDs used in run
    behavior_count INTEGER NOT NULL DEFAULT 0,
    has_behaviors BOOLEAN NOT NULL DEFAULT FALSE,
    baseline_tokens INTEGER,
    actor_surface VARCHAR,  -- CLI | WEB | API | MCP
    actor_role VARCHAR,  -- STRATEGIST | TEACHER | STUDENT
    first_plan_timestamp TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_behavior_usage_template_id ON fact_behavior_usage(template_id);
CREATE INDEX IF NOT EXISTS idx_behavior_usage_actor_role ON fact_behavior_usage(actor_role);
CREATE INDEX IF NOT EXISTS idx_behavior_usage_first_plan_timestamp ON fact_behavior_usage(first_plan_timestamp);

-- Fact: Execution Status (Run-Level Aggregate)
-- Tracks final execution outcome per workflow run
-- Supports: 80% completion rate target, execution time metrics
CREATE TABLE IF NOT EXISTS fact_execution_status (
    run_id VARCHAR PRIMARY KEY,
    template_id VARCHAR,
    status VARCHAR,  -- COMPLETED | FAILED | CANCELLED | IN_PROGRESS
    actor_surface VARCHAR,
    actor_role VARCHAR
);
CREATE INDEX IF NOT EXISTS idx_execution_status_template_id ON fact_execution_status(template_id);
CREATE INDEX IF NOT EXISTS idx_execution_status_status ON fact_execution_status(status);
CREATE INDEX IF NOT EXISTS idx_execution_status_actor_role ON fact_execution_status(actor_role);

-- Fact: Token Savings (Run-Level Aggregate)
-- Tracks token consumption and savings per workflow run
-- Supports: 30% token savings target
CREATE TABLE IF NOT EXISTS fact_token_savings (
    run_id VARCHAR PRIMARY KEY,
    template_id VARCHAR,
    output_tokens INTEGER,
    baseline_tokens INTEGER,
    token_savings_pct DOUBLE
);
CREATE INDEX IF NOT EXISTS idx_token_savings_template_id ON fact_token_savings(template_id);
CREATE INDEX IF NOT EXISTS idx_token_savings_token_savings_pct ON fact_token_savings(token_savings_pct);

-- Fact: Compliance Steps (Event-Level)
-- Tracks compliance checklist step execution across Web/API/CLI/MCP surfaces
-- Supports: 95% compliance coverage target, audit trail
CREATE TABLE IF NOT EXISTS fact_compliance_steps (
    checklist_id VARCHAR,
    step_id VARCHAR,
    status VARCHAR,
    coverage_score DOUBLE,
    run_id VARCHAR,
    session_id VARCHAR,
    behavior_ids VARCHAR,  -- JSON array of behavior IDs
    timestamp TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_compliance_steps_run_id ON fact_compliance_steps(run_id);
CREATE INDEX IF NOT EXISTS idx_compliance_steps_status ON fact_compliance_steps(status);
CREATE INDEX IF NOT EXISTS idx_compliance_steps_timestamp ON fact_compliance_steps(timestamp);

-- View: Behavior Reuse Rate
-- Calculates percentage of runs that reference at least one behavior
CREATE VIEW IF NOT EXISTS view_behavior_reuse_rate AS
SELECT
    COUNT(DISTINCT CASE WHEN has_behaviors = TRUE THEN run_id END) * 100.0 / NULLIF(COUNT(DISTINCT run_id), 0) AS reuse_rate_pct,
    COUNT(DISTINCT run_id) AS total_runs,
    COUNT(DISTINCT CASE WHEN has_behaviors = TRUE THEN run_id END) AS runs_with_behaviors
FROM fact_behavior_usage;

-- View: Token Savings Rate
-- Calculates average percentage reduction in reasoning tokens when using behaviors
CREATE VIEW IF NOT EXISTS view_token_savings_rate AS
SELECT
    AVG(token_savings_pct) AS avg_savings_rate_pct,
    COUNT(*) AS total_runs,
    SUM(baseline_tokens) AS total_baseline_tokens,
    SUM(output_tokens) AS total_output_tokens,
    SUM(baseline_tokens - output_tokens) AS total_tokens_saved
FROM fact_token_savings
WHERE token_savings_pct IS NOT NULL;

-- View: Completion Rate
-- Calculates percentage of runs that reach 'COMPLETED' status
CREATE VIEW IF NOT EXISTS view_completion_rate AS
SELECT
    COUNT(DISTINCT CASE WHEN status = 'COMPLETED' THEN run_id END) * 100.0 / NULLIF(COUNT(DISTINCT run_id), 0) AS completion_rate_pct,
    COUNT(DISTINCT run_id) AS total_runs,
    COUNT(DISTINCT CASE WHEN status = 'COMPLETED' THEN run_id END) AS completed_runs,
    COUNT(DISTINCT CASE WHEN status = 'FAILED' THEN run_id END) AS failed_runs,
    COUNT(DISTINCT CASE WHEN status = 'CANCELLED' THEN run_id END) AS cancelled_runs
FROM fact_execution_status;

-- View: Compliance Coverage Rate
-- Calculates average compliance coverage score across runs
CREATE VIEW IF NOT EXISTS view_compliance_coverage_rate AS
SELECT
    AVG(coverage_score) * 100 AS avg_coverage_rate_pct,
    COUNT(DISTINCT run_id) AS total_runs,
    COUNT(*) AS total_compliance_events,
    COUNT(CASE WHEN coverage_score >= 0.95 THEN 1 END) AS runs_above_95pct
FROM fact_compliance_steps
WHERE coverage_score IS NOT NULL;

-- ==================================================================================
-- EPIC 8.12: COST OPTIMIZATION TABLES (Phase 2)
-- ==================================================================================

-- Fact: Resource Usage (Operation-Level)
-- Tracks resource consumption by service and operation
-- Supports: Cost allocation, service-level budgeting, operation profiling
CREATE TABLE IF NOT EXISTS fact_resource_usage (
    usage_id VARCHAR PRIMARY KEY,
    run_id VARCHAR,
    service_name VARCHAR,  -- BehaviorService, ActionService, RunService, ComplianceService, etc.
    operation_name VARCHAR,  -- retrieve_behaviors, execute_action, start_run, record_step, etc.
    token_count INTEGER,
    api_calls INTEGER,
    execution_time_ms INTEGER,
    estimated_cost_usd DOUBLE,  -- Calculated: (token_count / 1000) * cost_per_1k_tokens
    timestamp TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_resource_usage_run_id ON fact_resource_usage(run_id);
CREATE INDEX IF NOT EXISTS idx_resource_usage_service_name ON fact_resource_usage(service_name);
CREATE INDEX IF NOT EXISTS idx_resource_usage_timestamp ON fact_resource_usage(timestamp);

-- Fact: Cost Allocation (Run-Level Aggregate)
-- Aggregates service costs per workflow run
-- Supports: Total cost per run, savings calculation, ROI analysis
CREATE TABLE IF NOT EXISTS fact_cost_allocation (
    run_id VARCHAR PRIMARY KEY,
    template_id VARCHAR,
    service_costs VARCHAR,  -- JSON object: {"BehaviorService": 0.003, "ActionService": 0.001, ...}
    total_cost_usd DOUBLE,
    savings_vs_baseline_usd DOUBLE,  -- 30% token savings = $ saved (baseline_cost - actual_cost)
    timestamp TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cost_allocation_template_id ON fact_cost_allocation(template_id);
CREATE INDEX IF NOT EXISTS idx_cost_allocation_timestamp ON fact_cost_allocation(timestamp);

-- Dimension: Cost Model (Service-Level Pricing)
-- Configurable pricing model for cost estimation
-- Supports: Token pricing updates, service-specific rates, historical pricing
CREATE TABLE IF NOT EXISTS dim_cost_model (
    service_name VARCHAR PRIMARY KEY,
    cost_per_1k_input_tokens DOUBLE,  -- e.g., $0.03 for GPT-4 input
    cost_per_1k_output_tokens DOUBLE,  -- e.g., $0.06 for GPT-4 output
    cost_per_api_call DOUBLE,  -- e.g., $0.0001 for REST API call overhead
    updated_at TIMESTAMP NOT NULL
);

-- View: Cost by Service
-- Aggregates resource usage and cost by service
-- Supports: Service-level cost breakdown (pie chart), top expensive services
CREATE VIEW IF NOT EXISTS view_cost_by_service AS
SELECT
    service_name,
    SUM(estimated_cost_usd) AS total_cost_usd,
    COUNT(*) AS operation_count,
    SUM(token_count) AS total_tokens,
    AVG(execution_time_ms) AS avg_execution_time_ms,
    SUM(api_calls) AS total_api_calls
FROM fact_resource_usage
WHERE estimated_cost_usd IS NOT NULL
GROUP BY service_name
ORDER BY total_cost_usd DESC;

-- View: Cost per Run
-- Aggregates cost allocation by run with savings calculation
-- Supports: Cost trend over time (line chart), cost anomaly detection
CREATE VIEW IF NOT EXISTS view_cost_per_run AS
SELECT
    run_id,
    template_id,
    total_cost_usd,
    savings_vs_baseline_usd,
    CASE
        WHEN total_cost_usd > 0 THEN (savings_vs_baseline_usd / total_cost_usd) * 100
        ELSE NULL
    END AS savings_pct,
    timestamp
FROM fact_cost_allocation
WHERE total_cost_usd IS NOT NULL
ORDER BY timestamp DESC;

-- View: ROI Analysis
-- Calculates return on investment from token savings
-- Supports: ROI gauge, financial impact reporting
CREATE VIEW IF NOT EXISTS view_roi_analysis AS
SELECT
    SUM(savings_vs_baseline_usd) AS total_savings_usd,
    COUNT(DISTINCT run_id) AS total_runs,
    SUM(total_cost_usd) AS total_infrastructure_cost_usd,
    CASE
        WHEN SUM(total_cost_usd) > 0 THEN SUM(savings_vs_baseline_usd) / SUM(total_cost_usd)
        ELSE NULL
    END AS roi_ratio
FROM fact_cost_allocation
WHERE savings_vs_baseline_usd IS NOT NULL;

-- View: Daily Cost Summary
-- Aggregates cost by day for budget tracking
-- Supports: Budget vs actual (progress bar), daily spend alerts
CREATE VIEW IF NOT EXISTS view_daily_cost_summary AS
SELECT
    DATE(timestamp) AS date,
    SUM(total_cost_usd) AS daily_cost_usd,
    COUNT(DISTINCT run_id) AS runs_count,
    AVG(total_cost_usd) AS avg_cost_per_run_usd,
    SUM(savings_vs_baseline_usd) AS daily_savings_usd
FROM fact_cost_allocation
WHERE total_cost_usd IS NOT NULL
GROUP BY DATE(timestamp)
ORDER BY DATE(timestamp) DESC;

-- View: Top Expensive Workflows
-- Identifies workflows with highest cumulative cost
-- Supports: Cost optimization targeting, workflow profiling
CREATE VIEW IF NOT EXISTS view_top_expensive_workflows AS
SELECT
    template_id,
    SUM(total_cost_usd) AS total_cost_usd,
    COUNT(DISTINCT run_id) AS runs_count,
    AVG(total_cost_usd) AS avg_cost_per_run_usd,
    SUM(savings_vs_baseline_usd) AS total_savings_usd
FROM fact_cost_allocation
WHERE total_cost_usd IS NOT NULL
GROUP BY template_id
ORDER BY SUM(total_cost_usd) DESC
LIMIT 10;

-- DuckDB-specific optimizations:
-- 1. Indexes created separately (DuckDB doesn't support inline INDEX)
-- 2. VARCHAR used instead of STRING (DuckDB prefers VARCHAR)
-- 3. TIMESTAMP without timezone (DuckDB default)
-- 4. NULLIF guards against division by zero
-- 5. Views use IF NOT EXISTS for idempotency
-- 6. Schema aligned with TelemetryKPIProjector run-level aggregates
-- 7. DOUBLE precision for cost calculations (financial accuracy)
-- 8. CASE expressions for safe division (NULL instead of division by zero)
