"""Add missing observability typed tables, retention seed, and dashboard views to telemetry DB.

Revision ID: telemetry_obs_typed_parity
Revises: telemetry_obs_generations
Create Date: 2026-05-05

Following behavior_migrate_postgres_schema (Student): bring ``migrations_telemetry`` in line with
``migrations/versions/20260428_add_observability_timescale_storage.py`` for tool_call/outcome/action
projections and Metabase-style views (GUIDEAI-1192).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "telemetry_obs_typed_parity"
down_revision: Union[str, None] = "telemetry_obs_generations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        text(
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
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_observability_tool_calls_tool_time
            ON observability_tool_calls (tool_name, record_timestamp DESC)
            """
        )
    )

    conn.execute(
        text(
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
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_observability_actions_action_time
            ON observability_actions (action_type, record_timestamp DESC)
            """
        )
    )

    conn.execute(
        text(
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
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_observability_outcomes_type_time
            ON observability_outcomes (outcome_type, record_timestamp DESC)
            """
        )
    )

    conn.execute(
        text(
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
    )
    conn.execute(
        text(
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
    )

    conn.execute(
        text(
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
    )
    conn.execute(
        text(
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
    )
    conn.execute(
        text(
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
    )


def downgrade() -> None:
    op.execute(text("DROP VIEW IF EXISTS observability_business_outcomes"))
    op.execute(text("DROP VIEW IF EXISTS observability_tool_performance"))
    op.execute(text("DROP VIEW IF EXISTS observability_trace_summary"))
    op.execute(text("DROP TABLE IF EXISTS observability_retention_policies"))
    op.execute(text("DROP TABLE IF EXISTS observability_outcomes"))
    op.execute(text("DROP TABLE IF EXISTS observability_actions"))
    op.execute(text("DROP TABLE IF EXISTS observability_tool_calls"))
