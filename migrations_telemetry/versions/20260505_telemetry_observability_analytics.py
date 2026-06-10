"""Telemetry DB: observability_records indexes + span/run/conversation analytics views.

Revision ID: telemetry_obs_analytics
Revises: telemetry_obs_typed_parity
Create Date: 2026-05-05

Mirrors ``20260505_observability_analytics_indexes_views.py`` for the telemetry warehouse DSN
(GUIDEAI-1192).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "telemetry_obs_analytics"
down_revision: Union[str, None] = "telemetry_obs_typed_parity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    stmts = [
        """
        CREATE INDEX IF NOT EXISTS ix_observability_records_project_time
        ON observability_records (project_id, record_timestamp DESC)
        WHERE project_id IS NOT NULL
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_observability_records_conversation_time
        ON observability_records (conversation_id, record_timestamp DESC)
        WHERE conversation_id IS NOT NULL
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_observability_records_kind_time
        ON observability_records (kind, record_timestamp DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_observability_records_surface_time
        ON observability_records (surface, record_timestamp DESC)
        WHERE surface IS NOT NULL
        """,
        """
        CREATE OR REPLACE VIEW observability_span_tree AS
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
            FROM observability_records o
            WHERE o.kind = 'span'
              AND (
                  o.parent_span_id IS NULL
                  OR NOT EXISTS (
                      SELECT 1 FROM observability_records p
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
            FROM observability_records c
            INNER JOIN walk w
                ON c.trace_id = w.trace_id
               AND c.parent_span_id = w.span_id
            WHERE c.kind = 'span'
        )
        SELECT * FROM walk
        """,
        """
        CREATE OR REPLACE VIEW observability_run_summary AS
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
        FROM observability_records
        WHERE run_id IS NOT NULL
        GROUP BY run_id
        """,
        """
        CREATE OR REPLACE VIEW observability_conversation_summary AS
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
        FROM observability_records
        WHERE conversation_id IS NOT NULL
        GROUP BY conversation_id
        """,
    ]
    for sql in stmts:
        conn.execute(text(sql))


def downgrade() -> None:
    op.execute(text("DROP VIEW IF EXISTS observability_conversation_summary"))
    op.execute(text("DROP VIEW IF EXISTS observability_run_summary"))
    op.execute(text("DROP VIEW IF EXISTS observability_span_tree"))
    op.execute(text("DROP INDEX IF EXISTS ix_observability_records_surface_time"))
    op.execute(text("DROP INDEX IF EXISTS ix_observability_records_kind_time"))
    op.execute(text("DROP INDEX IF EXISTS ix_observability_records_conversation_time"))
    op.execute(text("DROP INDEX IF EXISTS ix_observability_records_project_time"))
