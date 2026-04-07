"""Add enhanced analysis columns to research evaluations and recommendations.

Adds columns for:
- evaluations: structured_cons, competitive_landscape, value_proposition, honest_assessment
- recommendations: executive_summary, adoption_strategy, handoff_context

These fields were added to the research pipeline to support richer evaluation
output (competitive landscape, adoption strategy, brutal honesty assessment)
but were missing from the PostgreSQL schema and storage layer.

Revision ID: 20260329_research_enhanced
Revises: 20260327_create_research
Create Date: 2026-03-29

Behavior: behavior_migrate_postgres_schema
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "20260329_research_enhanced"
down_revision: Union[str, None] = "20260327_create_research"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add missing enhanced-analysis columns to research tables."""

    # -- research.evaluations: new JSONB/TEXT columns ----------------------
    op.execute(
        "ALTER TABLE research.evaluations "
        "ADD COLUMN IF NOT EXISTS structured_cons JSONB"
    )
    op.execute(
        "ALTER TABLE research.evaluations "
        "ADD COLUMN IF NOT EXISTS competitive_landscape JSONB"
    )
    op.execute(
        "ALTER TABLE research.evaluations "
        "ADD COLUMN IF NOT EXISTS value_proposition JSONB"
    )
    op.execute(
        "ALTER TABLE research.evaluations "
        "ADD COLUMN IF NOT EXISTS honest_assessment TEXT"
    )

    # -- research.recommendations: new JSONB/TEXT columns ------------------
    op.execute(
        "ALTER TABLE research.recommendations "
        "ADD COLUMN IF NOT EXISTS executive_summary TEXT"
    )
    op.execute(
        "ALTER TABLE research.recommendations "
        "ADD COLUMN IF NOT EXISTS adoption_strategy JSONB"
    )
    op.execute(
        "ALTER TABLE research.recommendations "
        "ADD COLUMN IF NOT EXISTS handoff_context JSONB"
    )


def downgrade() -> None:
    """Remove enhanced-analysis columns (data will be lost)."""

    op.execute("ALTER TABLE research.recommendations DROP COLUMN IF EXISTS handoff_context")
    op.execute("ALTER TABLE research.recommendations DROP COLUMN IF EXISTS adoption_strategy")
    op.execute("ALTER TABLE research.recommendations DROP COLUMN IF EXISTS executive_summary")

    op.execute("ALTER TABLE research.evaluations DROP COLUMN IF EXISTS honest_assessment")
    op.execute("ALTER TABLE research.evaluations DROP COLUMN IF EXISTS value_proposition")
    op.execute("ALTER TABLE research.evaluations DROP COLUMN IF EXISTS competitive_landscape")
    op.execute("ALTER TABLE research.evaluations DROP COLUMN IF EXISTS structured_cons")
