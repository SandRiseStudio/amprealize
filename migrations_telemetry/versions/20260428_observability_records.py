"""Add canonical observability records to telemetry database.

Revision ID: telemetry_observability_records
Revises: neon_compat
Create Date: 2026-04-28

Following behavior_migrate_postgres_schema (Student): this migration restores
the existing Timescale/Postgres telemetry path as the runtime home for
canonical observability records used by GUIDEAI-1091 lifecycle dashboards.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "telemetry_observability_records"
down_revision: Union[str, None] = "neon_compat"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        text(
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
    )

    conn.execute(
        text(
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
            END $$
            """
        )
    )

    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_observability_records_trace_time
            ON observability_records (trace_id, record_timestamp DESC)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_observability_records_run_time
            ON observability_records (run_id, record_timestamp DESC)
            WHERE run_id IS NOT NULL
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_observability_records_work_item_time
            ON observability_records (work_item_id, record_timestamp DESC)
            WHERE work_item_id IS NOT NULL
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_observability_records_payload_gin
            ON observability_records USING GIN (payload)
            """
        )
    )

    conn.execute(
        text(
            """
            CREATE OR REPLACE VIEW observability_behavior_candidate_lifecycle AS
            WITH extracted AS (
                SELECT
                    COALESCE(payload->>'candidate_id', payload->>'candidate_slug', record_id)
                        AS candidate_id,
                    MIN(record_timestamp) AS extracted_at,
                    date_trunc('hour', MIN(record_timestamp)) AS bucket,
                    MAX(NULLIF(payload->>'estimated_token_savings', '')::NUMERIC)
                        AS estimated_token_savings
                FROM observability_records
                WHERE kind = 'behavior_candidate'
                  AND name = 'reflection.candidate_extracted'
                GROUP BY COALESCE(payload->>'candidate_id', payload->>'candidate_slug', record_id)
            ),
            approved AS (
                SELECT
                    payload->>'candidate_id' AS candidate_id,
                    MAX(NULLIF(payload->>'reviewer_role', '')) AS reviewer_role
                FROM observability_records
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
                FROM observability_records
                WHERE kind = 'behavior_candidate'
                  AND name = 'reflection.candidate_rejected'
                  AND payload ? 'candidate_id'
                GROUP BY payload->>'candidate_id'
            )
            SELECT
                extracted.bucket AS bucket,
                COALESCE(approved.reviewer_role, rejected.reviewer_role, 'unreviewed')
                    AS reviewer_role,
                rejected.rejection_reason AS rejection_reason,
                COUNT(*) AS candidate_extracted_count,
                COUNT(*) FILTER (WHERE approved.candidate_id IS NOT NULL)
                    AS candidate_approved_count,
                COUNT(*) FILTER (WHERE rejected.candidate_id IS NOT NULL)
                    AS candidate_rejected_count,
                CASE
                    WHEN COUNT(*) = 0 THEN 0::NUMERIC
                    ELSE ROUND(
                        (COUNT(*) FILTER (WHERE approved.candidate_id IS NOT NULL))::NUMERIC
                        / COUNT(*)::NUMERIC,
                        4
                    )
                END AS approval_rate,
                SUM(COALESCE(extracted.estimated_token_savings, 0::NUMERIC))
                    AS estimated_token_savings,
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
                rejected.rejection_reason
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("DROP VIEW IF EXISTS observability_behavior_candidate_lifecycle"))
    conn.execute(text("DROP TABLE IF EXISTS observability_records"))
