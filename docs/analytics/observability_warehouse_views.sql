-- Amprealize managed-enterprise observability warehouse views
-- Following behavior_update_docs_after_changes (Student): keep warehouse-facing
-- dashboard projections aligned with the governed dashboard contracts.

CREATE SCHEMA IF NOT EXISTS enterprise_warehouse;

CREATE OR REPLACE VIEW enterprise_warehouse.observability_behavior_candidate_lifecycle AS
WITH extracted AS (
    SELECT
        COALESCE(payload->>'candidate_id', payload->>'candidate_slug', record_id) AS candidate_id,
        MIN(record_timestamp) AS extracted_at,
        date_trunc('hour', MIN(record_timestamp)) AS bucket,
        MAX(
            NULLIF(payload->>'estimated_token_savings', '')::NUMERIC
        ) AS estimated_token_savings
    FROM enterprise_warehouse.observability_records
    WHERE kind = 'behavior_candidate'
      AND name = 'reflection.candidate_extracted'
    GROUP BY COALESCE(payload->>'candidate_id', payload->>'candidate_slug', record_id)
),
approved AS (
    SELECT
        payload->>'candidate_id' AS candidate_id,
        MAX(NULLIF(payload->>'reviewer_role', '')) AS reviewer_role
    FROM enterprise_warehouse.observability_records
    WHERE kind = 'behavior_candidate'
      AND name = 'reflection.candidate_approved'
      AND payload ? 'candidate_id'
    GROUP BY payload->>'candidate_id'
),
rejected AS (
    SELECT
        payload->>'candidate_id' AS candidate_id,
        MAX(NULLIF(payload->>'reviewer_role', '')) AS reviewer_role,
        MAX(NULLIF(payload->>'rejection_reason', '')) AS rejection_reason
    FROM enterprise_warehouse.observability_records
    WHERE kind = 'behavior_candidate'
      AND name = 'reflection.candidate_rejected'
      AND payload ? 'candidate_id'
    GROUP BY payload->>'candidate_id'
)
SELECT
    extracted.bucket AS bucket,
    COALESCE(approved.reviewer_role, rejected.reviewer_role, 'unreviewed') AS reviewer_role,
    rejected.rejection_reason AS rejection_reason,
    COUNT(*) AS candidate_extracted_count,
    COUNT(*) FILTER (WHERE approved.candidate_id IS NOT NULL) AS candidate_approved_count,
    COUNT(*) FILTER (WHERE rejected.candidate_id IS NOT NULL) AS candidate_rejected_count,
    CASE
        WHEN COUNT(*) = 0 THEN 0::NUMERIC
        ELSE ROUND(
            (COUNT(*) FILTER (WHERE approved.candidate_id IS NOT NULL))::NUMERIC
            / COUNT(*)::NUMERIC,
            4
        )
    END AS approval_rate,
    SUM(COALESCE(extracted.estimated_token_savings, 0::NUMERIC)) AS estimated_token_savings,
    COUNT(*) FILTER (
        WHERE approved.candidate_id IS NULL
          AND rejected.candidate_id IS NULL
          AND extracted.extracted_at < NOW() - INTERVAL '14 days'
    ) AS decayed_behavior_count
FROM extracted
LEFT JOIN approved ON approved.candidate_id = extracted.candidate_id
LEFT JOIN rejected ON rejected.candidate_id = extracted.candidate_id
GROUP BY
    extracted.bucket,
    COALESCE(approved.reviewer_role, rejected.reviewer_role, 'unreviewed'),
    rejected.rejection_reason;

-- --- Parity with self-hosted public schema views (GUIDEAI-1192) ---
-- Requires canonical hypertable enterprise_warehouse.observability_records and typed
-- projections enterprise_warehouse.observability_generations, observability_tool_calls,
-- observability_outcomes (same shapes as migrations/versions/20260428_add_observability_timescale_storage.py).

CREATE OR REPLACE VIEW enterprise_warehouse.observability_trace_summary AS
SELECT
    trace_id,
    MIN(record_timestamp) AS started_at,
    MAX(record_timestamp) AS last_event_at,
    COUNT(*) AS record_count,
    COUNT(*) FILTER (WHERE status = 'failed') AS failed_record_count,
    COUNT(*) FILTER (WHERE kind = 'generation') AS generation_count,
    COUNT(*) FILTER (WHERE kind = 'tool_call') AS tool_call_count,
    MAX(run_id) AS run_id,
    MAX(work_item_id) AS work_item_id,
    MAX(conversation_id) AS conversation_id,
    MAX(surface) AS surface,
    MAX(project_id) AS project_id
FROM enterprise_warehouse.observability_records
GROUP BY trace_id;

CREATE OR REPLACE VIEW enterprise_warehouse.observability_generation_metrics AS
SELECT
    date_trunc('hour', record_timestamp) AS bucket,
    provider,
    model_id,
    status,
    COUNT(*) AS generation_count,
    SUM(COALESCE(input_tokens, 0)) AS input_tokens,
    SUM(COALESCE(output_tokens, 0)) AS output_tokens,
    SUM(COALESCE(cost_usd, 0)) AS cost_usd,
    AVG(latency_ms) AS avg_latency_ms,
    AVG(first_token_latency_ms) AS avg_first_token_latency_ms
FROM enterprise_warehouse.observability_generations
GROUP BY bucket, provider, model_id, status;

CREATE OR REPLACE VIEW enterprise_warehouse.observability_tool_performance AS
SELECT
    date_trunc('hour', record_timestamp) AS bucket,
    tool_name,
    status,
    COUNT(*) AS call_count,
    AVG(elapsed_ms) AS avg_elapsed_ms,
    COUNT(*) FILTER (WHERE status = 'failed') AS failed_count
FROM enterprise_warehouse.observability_tool_calls
GROUP BY bucket, tool_name, status;

CREATE OR REPLACE VIEW enterprise_warehouse.observability_business_outcomes AS
SELECT
    date_trunc('day', record_timestamp) AS bucket,
    outcome_type,
    resource_type,
    status,
    COUNT(*) AS outcome_count
FROM enterprise_warehouse.observability_outcomes
GROUP BY bucket, outcome_type, resource_type, status;

CREATE OR REPLACE VIEW enterprise_warehouse.observability_span_tree AS
WITH RECURSIVE walk AS (
    SELECT
        o.record_id,
        o.record_timestamp,
        o.trace_id,
        o.span_id,
        o.parent_span_id,
        o.name,
        o.status,
        o.kind,
        0 AS depth
    FROM enterprise_warehouse.observability_records o
    WHERE o.kind = 'span'
      AND (
          o.parent_span_id IS NULL
          OR NOT EXISTS (
              SELECT 1 FROM enterprise_warehouse.observability_records p
              WHERE p.trace_id = o.trace_id
                AND p.span_id = o.parent_span_id
                AND p.kind IN ('span', 'trace')
          )
      )

    UNION ALL

    SELECT
        c.record_id,
        c.record_timestamp,
        c.trace_id,
        c.span_id,
        c.parent_span_id,
        c.name,
        c.status,
        c.kind,
        w.depth + 1
    FROM enterprise_warehouse.observability_records c
    INNER JOIN walk w
        ON c.trace_id = w.trace_id
       AND c.parent_span_id = w.span_id
    WHERE c.kind = 'span'
)
SELECT * FROM walk;

CREATE OR REPLACE VIEW enterprise_warehouse.observability_run_summary AS
SELECT
    run_id,
    MIN(record_timestamp) AS started_at,
    MAX(record_timestamp) AS last_event_at,
    COUNT(*) AS record_count,
    COUNT(*) FILTER (WHERE status = 'failed') AS failed_record_count,
    COUNT(*) FILTER (WHERE kind = 'generation') AS generation_count,
    COUNT(*) FILTER (WHERE kind = 'tool_call') AS tool_call_count,
    COUNT(*) FILTER (WHERE kind = 'span') AS span_count,
    MAX(trace_id) AS primary_trace_id,
    MAX(project_id) AS project_id,
    MAX(work_item_id) AS work_item_id,
    MAX(surface) AS surface
FROM enterprise_warehouse.observability_records
WHERE run_id IS NOT NULL
GROUP BY run_id;

CREATE OR REPLACE VIEW enterprise_warehouse.observability_conversation_summary AS
SELECT
    conversation_id,
    MIN(record_timestamp) AS started_at,
    MAX(record_timestamp) AS last_event_at,
    COUNT(*) AS record_count,
    COUNT(DISTINCT trace_id) AS trace_count,
    COUNT(*) FILTER (WHERE kind = 'generation') AS generation_count,
    COUNT(*) FILTER (WHERE kind = 'tool_call') AS tool_call_count,
    MAX(project_id) AS project_id,
    MAX(surface) AS surface
FROM enterprise_warehouse.observability_records
WHERE conversation_id IS NOT NULL
GROUP BY conversation_id;
