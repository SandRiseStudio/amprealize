"""observability_records query indexes and analytics views (span tree, run, conversation).

Revision ID: 20260505_observability_analytics
Revises: 20260501_global_personal_thread
Create Date: 2026-05-05

Governed observability list queries filter by project_id, conversation_id, and kind;
partial B-tree indexes support those paths (GUIDEAI-1192).

Adds dashboard-ready views: observability_span_tree (recursive span hierarchy),
observability_run_summary, observability_conversation_summary.
"""

from __future__ import annotations

from alembic import op


revision = "20260505_observability_analytics"
down_revision = "20260501_global_personal_thread"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Query paths: GovernedObservabilityQueryService / observability API filters
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_observability_records_project_time
        ON observability_records (project_id, record_timestamp DESC)
        WHERE project_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_observability_records_conversation_time
        ON observability_records (conversation_id, record_timestamp DESC)
        WHERE conversation_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_observability_records_kind_time
        ON observability_records (kind, record_timestamp DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_observability_records_surface_time
        ON observability_records (surface, record_timestamp DESC)
        WHERE surface IS NOT NULL
        """
    )

    op.execute(
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
        """
    )

    op.execute(
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
        """
    )

    op.execute(
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
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS observability_conversation_summary")
    op.execute("DROP VIEW IF EXISTS observability_run_summary")
    op.execute("DROP VIEW IF EXISTS observability_span_tree")
    op.execute("DROP INDEX IF EXISTS ix_observability_records_surface_time")
    op.execute("DROP INDEX IF EXISTS ix_observability_records_kind_time")
    op.execute("DROP INDEX IF EXISTS ix_observability_records_conversation_time")
    op.execute("DROP INDEX IF EXISTS ix_observability_records_project_time")
