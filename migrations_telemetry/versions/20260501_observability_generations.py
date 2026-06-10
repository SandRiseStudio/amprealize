"""Add observability_generations and generation metrics view to telemetry DB.

Revision ID: telemetry_obs_generations
Revises: telemetry_lifecycle_guard
Create Date: 2026-05-01

Following behavior_migrate_postgres_schema (Student): align telemetry warehouse
typed projections with dashboard views (observability_generation_metrics).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "telemetry_obs_generations"
down_revision: Union[str, None] = "telemetry_lifecycle_guard"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        text(
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
    )

    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_observability_generations_model_time
            ON observability_generations (model_id, record_timestamp DESC)
            """
        )
    )

    conn.execute(
        text(
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
    )


def downgrade() -> None:
    op.execute(text("DROP VIEW IF EXISTS observability_generation_metrics"))
    op.execute(text("DROP TABLE IF EXISTS observability_generations"))
