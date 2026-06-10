"""Add canonical observability Timescale storage.

Revision ID: 20260428_observability_timescale
Revises: 20260426_llm_cred_user_scope
Create Date: 2026-04-28

Following behavior_migrate_postgres_schema (Student): this migration creates
the self-hosted Timescale/Postgres storage profile for canonical observability
records, typed projections, retention policy metadata, and dashboard views.
"""

from alembic import op


revision = "20260428_observability_timescale"
down_revision = "20260426_llm_cred_user_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS observability_records (
            record_id TEXT NOT NULL,
            record_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'completed',
            sensitivity TEXT NOT NULL DEFAULT 'metadata',
            trace_id TEXT NOT NULL,
            span_id TEXT NOT NULL,
            parent_span_id TEXT,
            org_id TEXT,
            project_id TEXT,
            conversation_id TEXT,
            message_id TEXT,
            run_id TEXT,
            cycle_id TEXT,
            work_item_id TEXT,
            action_id TEXT,
            tool_call_id TEXT,
            llm_call_id TEXT,
            behavior_id TEXT,
            actor_id TEXT,
            actor_role TEXT,
            surface TEXT,
            permission_action TEXT,
            model_id TEXT,
            queue_job_id TEXT,
            phase TEXT,
            correlation JSONB NOT NULL DEFAULT '{}'::jsonb,
            attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            data_class TEXT NOT NULL DEFAULT 'metadata_trace',
            retention_until TIMESTAMPTZ,
            archived_after TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (record_id, record_timestamp),
            CHECK (kind IN (
                'trace',
                'span',
                'event',
                'generation',
                'tool_call',
                'action',
                'artifact',
                'behavior_candidate',
                'outcome'
            )),
            CHECK (status IN ('started', 'completed', 'failed', 'denied', 'skipped')),
            CHECK (sensitivity IN ('metadata', 'summary', 'restricted', 'raw'))
        )
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
                PERFORM create_hypertable(
                    'observability_records',
                    'record_timestamp',
                    if_not_exists => TRUE
                );
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_observability_records_trace_time
        ON observability_records (trace_id, record_timestamp DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_observability_records_run_time
        ON observability_records (run_id, record_timestamp DESC)
        WHERE run_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_observability_records_work_item_time
        ON observability_records (work_item_id, record_timestamp DESC)
        WHERE work_item_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_observability_records_payload_gin
        ON observability_records USING GIN (payload)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS observability_generations (
            record_id TEXT NOT NULL,
            record_timestamp TIMESTAMPTZ NOT NULL,
            trace_id TEXT NOT NULL,
            span_id TEXT NOT NULL,
            run_id TEXT,
            work_item_id TEXT,
            provider TEXT,
            model_id TEXT,
            input_tokens BIGINT,
            output_tokens BIGINT,
            cost_usd NUMERIC(18, 8),
            latency_ms NUMERIC,
            first_token_latency_ms NUMERIC,
            credential_scope TEXT,
            status TEXT NOT NULL DEFAULT 'completed',
            error_class TEXT,
            attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (record_id, record_timestamp)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_observability_generations_model_time
        ON observability_generations (model_id, record_timestamp DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS observability_tool_calls (
            record_id TEXT NOT NULL,
            record_timestamp TIMESTAMPTZ NOT NULL,
            trace_id TEXT NOT NULL,
            span_id TEXT NOT NULL,
            run_id TEXT,
            work_item_id TEXT,
            tool_name TEXT,
            call_id TEXT,
            elapsed_ms NUMERIC,
            status TEXT NOT NULL DEFAULT 'completed',
            target_resource_type TEXT,
            target_resource_id TEXT,
            input_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
            output_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
            attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (record_id, record_timestamp)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_observability_tool_calls_tool_time
        ON observability_tool_calls (tool_name, record_timestamp DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS observability_actions (
            record_id TEXT NOT NULL,
            record_timestamp TIMESTAMPTZ NOT NULL,
            trace_id TEXT NOT NULL,
            span_id TEXT NOT NULL,
            run_id TEXT,
            work_item_id TEXT,
            action_type TEXT,
            action_id TEXT,
            target_resource_type TEXT,
            target_resource_id TEXT,
            status TEXT NOT NULL DEFAULT 'completed',
            decision TEXT,
            attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (record_id, record_timestamp)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_observability_actions_action_time
        ON observability_actions (action_type, record_timestamp DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS observability_outcomes (
            record_id TEXT NOT NULL,
            record_timestamp TIMESTAMPTZ NOT NULL,
            trace_id TEXT NOT NULL,
            span_id TEXT NOT NULL,
            run_id TEXT,
            work_item_id TEXT,
            outcome_type TEXT,
            outcome_ref TEXT,
            resource_type TEXT,
            resource_id TEXT,
            status TEXT NOT NULL DEFAULT 'completed',
            attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (record_id, record_timestamp)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_observability_outcomes_type_time
        ON observability_outcomes (outcome_type, record_timestamp DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS observability_retention_policies (
            data_class TEXT PRIMARY KEY,
            sensitivity TEXT NOT NULL,
            default_retention_days INTEGER NOT NULL,
            max_retention_days INTEGER NOT NULL,
            archive_years INTEGER NOT NULL DEFAULT 0,
            purge_action TEXT NOT NULL DEFAULT 'delete',
            anonymize_on_delete BOOLEAN NOT NULL DEFAULT FALSE,
            allowed_access_tiers JSONB NOT NULL DEFAULT '[]'::jsonb,
            notes TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        INSERT INTO observability_retention_policies (
            data_class,
            sensitivity,
            default_retention_days,
            max_retention_days,
            archive_years,
            purge_action,
            anonymize_on_delete,
            allowed_access_tiers,
            notes
        )
        VALUES
            (
                'metadata_trace',
                'metadata',
                1095,
                2555,
                7,
                'anonymize_actor',
                TRUE,
                '["viewer", "data_analyst", "admin", "compliance"]'::jsonb,
                'Trace, span, event, token, cost, and correlation metadata.'
            ),
            (
                'summary',
                'summary',
                1095,
                2555,
                7,
                'anonymize_actor',
                TRUE,
                '["viewer", "data_analyst", "admin", "compliance"]'::jsonb,
                'Sanitized prompt, output, tool, and artifact summaries.'
            ),
            (
                'behavior_mining_feature',
                'summary',
                1095,
                2555,
                7,
                'anonymize_actor',
                TRUE,
                '["data_analyst", "admin", "compliance"]'::jsonb,
                'Long-lived derived features for trace analysis and behavior mining.'
            ),
            (
                'raw_prompt',
                'raw',
                30,
                90,
                0,
                'delete',
                FALSE,
                '["admin", "compliance"]'::jsonb,
                'Short-lived raw prompt debug payloads.'
            ),
            (
                'raw_response',
                'raw',
                30,
                90,
                0,
                'delete',
                FALSE,
                '["admin", "compliance"]'::jsonb,
                'Short-lived raw response debug payloads.'
            )
        ON CONFLICT (data_class) DO UPDATE SET
            sensitivity = EXCLUDED.sensitivity,
            default_retention_days = EXCLUDED.default_retention_days,
            max_retention_days = EXCLUDED.max_retention_days,
            archive_years = EXCLUDED.archive_years,
            purge_action = EXCLUDED.purge_action,
            anonymize_on_delete = EXCLUDED.anonymize_on_delete,
            allowed_access_tiers = EXCLUDED.allowed_access_tiers,
            notes = EXCLUDED.notes,
            updated_at = NOW()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE VIEW observability_trace_summary AS
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
        FROM observability_records
        GROUP BY trace_id
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW observability_generation_metrics AS
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
        FROM observability_generations
        GROUP BY bucket, provider, model_id, status
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW observability_tool_performance AS
        SELECT
            date_trunc('hour', record_timestamp) AS bucket,
            tool_name,
            status,
            COUNT(*) AS call_count,
            AVG(elapsed_ms) AS avg_elapsed_ms,
            COUNT(*) FILTER (WHERE status = 'failed') AS failed_count
        FROM observability_tool_calls
        GROUP BY bucket, tool_name, status
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW observability_business_outcomes AS
        SELECT
            date_trunc('day', record_timestamp) AS bucket,
            outcome_type,
            resource_type,
            status,
            COUNT(*) AS outcome_count
        FROM observability_outcomes
        GROUP BY bucket, outcome_type, resource_type, status
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS observability_business_outcomes")
    op.execute("DROP VIEW IF EXISTS observability_tool_performance")
    op.execute("DROP VIEW IF EXISTS observability_generation_metrics")
    op.execute("DROP VIEW IF EXISTS observability_trace_summary")
    op.execute("DROP TABLE IF EXISTS observability_retention_policies")
    op.execute("DROP TABLE IF EXISTS observability_outcomes")
    op.execute("DROP TABLE IF EXISTS observability_actions")
    op.execute("DROP TABLE IF EXISTS observability_tool_calls")
    op.execute("DROP TABLE IF EXISTS observability_generations")
    op.execute("DROP TABLE IF EXISTS observability_records")
