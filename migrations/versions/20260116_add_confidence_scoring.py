"""Add confidence scoring fields to behavior_versions

Revision ID: add_confidence_scoring
Revises: add_user_github_links
Create Date: 2026-01-16

Behavior: behavior_migrate_postgres_schema

This migration adds confidence scoring fields to behavior_versions table
to support the behavior proposal workflow from AGENTS.md:

1. confidence_score: DECIMAL(3,2) - 0.00 to 1.00, >=0.80 eligible for auto-approval
2. historical_validations: JSONB array - Run IDs that validated this pattern

Auto-Approval Criteria (per AGENTS.md):
- confidence_score >= 0.8
- Validated against 3+ historical cases (len(historical_validations) >= 3)
- Clear, unambiguous triggers
- No overlap with existing behaviors
- Follows behavior_<verb>_<noun> naming
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "add_confidence_scoring"
down_revision: Union[str, None] = "add_user_github_links"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add confidence scoring columns to behavior.behavior_versions."""

    # Add confidence_score column
    # DECIMAL(3,2) allows values from 0.00 to 1.00 (e.g., 0.85, 0.92)
    op.add_column(
        "behavior_versions",
        sa.Column(
            "confidence_score",
            sa.Numeric(precision=3, scale=2),
            nullable=True,
            comment="Confidence score 0.00-1.00, >=0.80 eligible for auto-approval"
        ),
        schema="behavior",
    )

    # Add historical_validations column
    # JSONB array of run_ids that validated this behavior pattern
    op.add_column(
        "behavior_versions",
        sa.Column(
            "historical_validations",
            postgresql.JSONB(),
            server_default="[]",
            nullable=True,
            comment="Array of run_ids that validated this pattern (need 3+ for auto-approval)"
        ),
        schema="behavior",
    )

    # Add proposed_by_role column for tracking who proposed the behavior
    op.add_column(
        "behavior_versions",
        sa.Column(
            "proposed_by_role",
            sa.String(32),
            nullable=True,
            comment="Role that proposed this behavior (Student, Teacher, Strategist)"
        ),
        schema="behavior",
    )

    # Add pattern_id column for linking to TraceAnalysisService patterns
    op.add_column(
        "behavior_versions",
        sa.Column(
            "pattern_id",
            sa.String(64),
            nullable=True,
            comment="Link to TraceAnalysisService pattern that triggered this proposal"
        ),
        schema="behavior",
    )

    # Create index on confidence_score for efficient auto-approval queries
    op.create_index(
        "idx_behavior_versions_confidence",
        "behavior_versions",
        ["confidence_score"],
        schema="behavior",
        postgresql_where=sa.text("confidence_score >= 0.80"),
    )


def downgrade() -> None:
    """Remove confidence scoring columns from behavior.behavior_versions."""

    # Drop index
    op.drop_index(
        "idx_behavior_versions_confidence",
        table_name="behavior_versions",
        schema="behavior",
    )

    # Drop columns
    op.drop_column("behavior_versions", "pattern_id", schema="behavior")
    op.drop_column("behavior_versions", "proposed_by_role", schema="behavior")
    op.drop_column("behavior_versions", "historical_validations", schema="behavior")
    op.drop_column("behavior_versions", "confidence_score", schema="behavior")
