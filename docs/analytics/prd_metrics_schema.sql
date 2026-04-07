-- DuckDB schema for PRD KPI analytics.
-- Mirrors the facts produced by amprealize.analytics.telemetry_kpi_projector.TelemetryKPIProjector.

CREATE SCHEMA IF NOT EXISTS prd_metrics;

CREATE TABLE IF NOT EXISTS prd_metrics.fact_behavior_usage (
    run_id VARCHAR NOT NULL,
    template_id VARCHAR,
    template_name VARCHAR,
    behavior_ids VARCHAR[], -- DuckDB array syntax
    behavior_count INTEGER,
    has_behaviors BOOLEAN,
    baseline_tokens BIGINT,
    actor_surface VARCHAR,
    actor_role VARCHAR,
    first_plan_timestamp TIMESTAMPTZ,
    recorded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE prd_metrics.fact_behavior_usage IS 'Per-run behavior citation context derived from plan_created and execution_update telemetry events.';

CREATE TABLE IF NOT EXISTS prd_metrics.fact_token_savings (
    run_id VARCHAR NOT NULL,
    template_id VARCHAR,
    output_tokens BIGINT,
    baseline_tokens BIGINT,
    token_savings_pct DOUBLE, -- DuckDB uses DOUBLE for decimals
    recorded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE prd_metrics.fact_token_savings IS 'Token accounting for workflow runs, including baseline comparisons for savings % tracking.';

CREATE TABLE IF NOT EXISTS prd_metrics.fact_execution_status (
    run_id VARCHAR NOT NULL,
    template_id VARCHAR,
    status VARCHAR,
    actor_surface VARCHAR,
    actor_role VARCHAR,
    recorded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE prd_metrics.fact_execution_status IS 'Terminal status rollups for workflow runs (COMPLETED/FAILED/CANCELLED).';

CREATE TABLE IF NOT EXISTS prd_metrics.fact_compliance_steps (
    checklist_id VARCHAR,
    step_id VARCHAR,
    status VARCHAR,
    coverage_score DOUBLE,
    run_id VARCHAR,
    session_id VARCHAR,
    behavior_ids VARCHAR[],
    timestamp TIMESTAMPTZ,
    recorded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE prd_metrics.fact_compliance_steps IS 'Checklist activity and coverage scores; includes behavior retrieval traces for attribution analysis.';

-- KPI summary view combining the fact tables into PRD success metrics.
CREATE OR REPLACE VIEW prd_metrics.kpi_summary AS
SELECT
    usage.window_start,
    usage.window_end,
    usage.total_runs,
    usage.runs_with_behaviors,
    CASE WHEN usage.total_runs = 0 THEN NULL ELSE ROUND(usage.runs_with_behaviors::DOUBLE / usage.total_runs * 100, 2) END AS behavior_reuse_pct,
    CASE WHEN savings.run_count = 0 THEN NULL ELSE ROUND(savings.avg_savings * 100, 2) END AS average_token_savings_pct,
    status.completed_runs,
    status.terminal_runs,
    CASE WHEN status.terminal_runs = 0 THEN NULL ELSE ROUND(status.completed_runs::DOUBLE / status.terminal_runs * 100, 2) END AS task_completion_rate_pct,
    CASE WHEN compliance.sampled_checklists = 0 THEN NULL ELSE ROUND(compliance.avg_coverage * 100, 2) END AS average_compliance_coverage_pct
FROM (
    SELECT
        DATE_TRUNC('day', recorded_at) AS window_start,
        DATE_TRUNC('day', recorded_at) + INTERVAL 1 DAY AS window_end,
        COUNT(*) AS total_runs,
        SUM(CASE WHEN has_behaviors THEN 1 ELSE 0 END) AS runs_with_behaviors
    FROM prd_metrics.fact_behavior_usage
    GROUP BY 1, 2
) usage
LEFT JOIN (
    SELECT
        DATE_TRUNC('day', recorded_at) AS window_start,
        DATE_TRUNC('day', recorded_at) + INTERVAL 1 DAY AS window_end,
        COUNT(token_savings_pct) AS run_count,
        AVG(token_savings_pct) AS avg_savings
    FROM prd_metrics.fact_token_savings
    GROUP BY 1, 2
) savings USING (window_start, window_end)
LEFT JOIN (
    SELECT
        DATE_TRUNC('day', recorded_at) AS window_start,
        DATE_TRUNC('day', recorded_at) + INTERVAL 1 DAY AS window_end,
        SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) AS completed_runs,
        COUNT(*) FILTER (WHERE status IN ('COMPLETED', 'FAILED', 'CANCELLED')) AS terminal_runs
    FROM prd_metrics.fact_execution_status
    GROUP BY 1, 2
) status USING (window_start, window_end)
LEFT JOIN (
    SELECT
        DATE_TRUNC('day', recorded_at) AS window_start,
        DATE_TRUNC('day', recorded_at) + INTERVAL 1 DAY AS window_end,
        COUNT(DISTINCT checklist_id) AS sampled_checklists,
        AVG(coverage_score) AS avg_coverage
    FROM prd_metrics.fact_compliance_steps
    WHERE status != 'BEHAVIOR_RETRIEVAL' AND coverage_score IS NOT NULL
    GROUP BY 1, 2
) compliance USING (window_start, window_end);
