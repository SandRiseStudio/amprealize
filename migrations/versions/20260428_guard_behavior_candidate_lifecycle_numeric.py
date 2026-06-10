"""Guard behavior-candidate lifecycle numeric casts.

Revision ID: 20260428_lifecycle_numeric_guard
Revises: 20260428_obs_beh_cand_lc
Create Date: 2026-04-28

Following behavior_migrate_postgres_schema (Student): keep lifecycle dashboard
queries resilient when sanitized telemetry payloads contain redacted or
otherwise non-numeric token-savings values.
"""

from alembic import op


revision = "20260428_lifecycle_numeric_guard"
down_revision = "20260428_obs_beh_cand_lc"
branch_labels = None
depends_on = None


LIFECYCLE_VIEW_SQL = """
CREATE OR REPLACE VIEW observability_behavior_candidate_lifecycle AS
WITH extracted AS (
    SELECT
        COALESCE(payload->>'candidate_id', payload->>'candidate_slug', record_id) AS candidate_id,
        MIN(record_timestamp) AS extracted_at,
        date_trunc('hour', MIN(record_timestamp)) AS bucket,
        MAX(
            CASE
                WHEN NULLIF(payload->>'estimated_token_savings', '') ~ '^-?[0-9]+(\\.[0-9]+)?$'
                THEN (payload->>'estimated_token_savings')::NUMERIC
                ELSE NULL::NUMERIC
            END
        ) AS estimated_token_savings
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
    rejected.rejection_reason
"""


def upgrade() -> None:
    op.execute(LIFECYCLE_VIEW_SQL)


def downgrade() -> None:
    op.execute(LIFECYCLE_VIEW_SQL)
