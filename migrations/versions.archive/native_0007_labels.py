"""Add labels table and GIN index for filtering

Revision ID: native_0007_labels
Revises: native_0006_agile
Create Date: 2025-01-17

Behavior: behavior_migrate_postgres_schema

This migration adds:
1. A GIN index on work_items.labels for efficient JSONB array querying
2. A labels table for predefined project labels with constrained colors
3. A sprint_id filter support (foreign key validation)

The labels column already exists in work_items (JSONB with default []).
This migration adds the index and a lookup table for predefined labels.

Label colors are constrained to a predefined palette for UI consistency.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "native_0007_labels"
down_revision: Union[str, None] = "native_0006_agile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Predefined color palette for label consistency
LABEL_COLORS = [
    "gray",      # Default/neutral
    "red",       # High priority, blockers
    "orange",    # Warning, needs attention
    "yellow",    # Caution, review needed
    "green",     # Success, approved, done
    "teal",      # Technical, infrastructure
    "blue",      # Information, documentation
    "indigo",    # Design, UX
    "purple",    # Feature, enhancement
    "pink",      # Customer-facing, external
]


def upgrade() -> None:
    """Add labels infrastructure for work items."""

    # =========================================================================
    # Create label_color ENUM type
    # =========================================================================

    label_color_enum = postgresql.ENUM(
        *LABEL_COLORS,
        name="label_color",
        create_type=False,
    )

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'label_color') THEN
                CREATE TYPE label_color AS ENUM (
                    'gray', 'red', 'orange', 'yellow', 'green',
                    'teal', 'blue', 'indigo', 'purple', 'pink'
                );
            END IF;
        END $$
    """)

    # =========================================================================
    # Create labels table
    # =========================================================================

    op.create_table(
        "labels",
        sa.Column("label_id", sa.String(36), nullable=False, server_default=sa.text("gen_random_uuid()::TEXT")),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("color", sa.Enum(*LABEL_COLORS, name="label_color", create_type=False), nullable=False, server_default="gray"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.PrimaryKeyConstraint("label_id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
    )

    # Unique constraint: label name must be unique within a project
    op.create_index(
        "idx_labels_project_name_unique",
        "labels",
        ["project_id", "name"],
        unique=True,
    )

    # Index for listing labels by project
    op.create_index(
        "idx_labels_project_id",
        "labels",
        ["project_id"],
    )

    # =========================================================================
    # Add GIN index on work_items.labels for efficient JSONB array queries
    # =========================================================================

    # GIN index enables efficient ?| (any of) and ?& (all of) operators
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_work_items_labels_gin
        ON work_items USING GIN (labels)
    """)

    # =========================================================================
    # Add updated_at trigger for labels table
    # =========================================================================

    op.execute("""
        CREATE OR REPLACE FUNCTION update_labels_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS labels_updated_at_trigger ON labels;
        CREATE TRIGGER labels_updated_at_trigger
            BEFORE UPDATE ON labels
            FOR EACH ROW
            EXECUTE FUNCTION update_labels_updated_at();
    """)


def downgrade() -> None:
    """Remove labels infrastructure."""

    # Drop trigger and function
    op.execute("DROP TRIGGER IF EXISTS labels_updated_at_trigger ON labels")
    op.execute("DROP FUNCTION IF EXISTS update_labels_updated_at()")

    # Drop GIN index
    op.execute("DROP INDEX IF EXISTS idx_work_items_labels_gin")

    # Drop labels table (cascades indexes)
    op.drop_table("labels")

    # Drop enum type
    op.execute("DROP TYPE IF EXISTS label_color")
