"""Align behavior schema with behavior_service.py expectations

Revision ID: align_behavior_schema
Revises: add_agents_and_agent_versions
Create Date: 2025-12-19

Behavior: behavior_migrate_postgres_schema

This migration aligns the behavior.behaviors and behavior.behavior_versions tables
with the expected schema in amprealize/behavior_service.py by:
1. Adding missing columns to behaviors table (status, tags as JSONB)
2. Adding missing columns to behavior_versions table for the versioning workflow
3. Preserving existing data by migrating keywords→tags, is_active→status, etc.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "align_behavior_schema"
down_revision: Union[str, None] = "c44af61ae484"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add missing columns to align with behavior_service.py expectations."""
    conn = op.get_bind()

    # =========================================================================
    # STEP 1: Add missing columns to behavior.behaviors
    # =========================================================================

    # Add 'status' column (maps from is_active/is_deprecated)
    op.add_column(
        "behaviors",
        sa.Column("status", sa.String(32), server_default="ACTIVE"),
        schema="behavior",
    )

    # Add 'tags' as JSONB (the code expects JSONB, not varchar[])
    op.add_column(
        "behaviors",
        sa.Column("tags", postgresql.JSONB(), server_default="[]"),
        schema="behavior",
    )

    # Add 'latest_version' column (string version identifier)
    op.add_column(
        "behaviors",
        sa.Column("latest_version", sa.String(32), server_default="1"),
        schema="behavior",
    )

    # Migrate existing data: keywords array → tags JSONB
    conn.execute(sa.text("""
        UPDATE behavior.behaviors
        SET tags = COALESCE(to_jsonb(keywords), '[]'::jsonb),
            status = CASE
                WHEN is_deprecated THEN 'DEPRECATED'
                WHEN is_active THEN 'ACTIVE'
                ELSE 'DRAFT'
            END,
            latest_version = version::text
    """))

    # Add index on status
    op.create_index(
        "idx_behavior_behaviors_status",
        "behaviors",
        ["status"],
        schema="behavior",
    )

    # =========================================================================
    # STEP 2: Add missing columns to behavior.behavior_versions
    # =========================================================================

    # Add 'instruction' column (text content for the version)
    op.add_column(
        "behavior_versions",
        sa.Column("instruction", sa.Text(), server_default=""),
        schema="behavior",
    )

    # Add 'role_focus' column (student, teacher, strategist)
    op.add_column(
        "behavior_versions",
        sa.Column("role_focus", sa.String(32), server_default="student"),
        schema="behavior",
    )

    # Add 'status' column for version workflow (DRAFT, PENDING_REVIEW, APPROVED, REJECTED)
    op.add_column(
        "behavior_versions",
        sa.Column("status", sa.String(32), server_default="APPROVED"),
        schema="behavior",
    )

    # Add 'trigger_keywords' as JSONB array
    op.add_column(
        "behavior_versions",
        sa.Column("trigger_keywords", postgresql.JSONB(), server_default="[]"),
        schema="behavior",
    )

    # Add 'examples' as JSONB array
    op.add_column(
        "behavior_versions",
        sa.Column("examples", postgresql.JSONB(), server_default="[]"),
        schema="behavior",
    )

    # Add 'metadata' as JSONB object
    op.add_column(
        "behavior_versions",
        sa.Column("metadata", postgresql.JSONB(), server_default="{}"),
        schema="behavior",
    )

    # Add 'effective_from' timestamp
    op.add_column(
        "behavior_versions",
        sa.Column("effective_from", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        schema="behavior",
    )

    # Add 'effective_to' timestamp (nullable for current versions)
    op.add_column(
        "behavior_versions",
        sa.Column("effective_to", sa.TIMESTAMP(timezone=True), nullable=True),
        schema="behavior",
    )

    # Add 'created_by' column
    op.add_column(
        "behavior_versions",
        sa.Column("created_by", sa.String(128), server_default="system"),
        schema="behavior",
    )

    # Add 'approval_action_id' for audit trail
    op.add_column(
        "behavior_versions",
        sa.Column("approval_action_id", sa.String(36), nullable=True),
        schema="behavior",
    )

    # Add 'embedding_checksum' for cache invalidation
    op.add_column(
        "behavior_versions",
        sa.Column("embedding_checksum", sa.String(64), nullable=True),
        schema="behavior",
    )

    # Add 'embedding' as BYTEA for vector storage
    op.add_column(
        "behavior_versions",
        sa.Column("embedding", sa.LargeBinary(), nullable=True),
        schema="behavior",
    )

    # Migrate existing data: populate instruction from parent behavior's steps
    conn.execute(sa.text("""
        UPDATE behavior.behavior_versions bv
        SET instruction = COALESCE(b.steps::text, ''),
            role_focus = COALESCE(b.role, 'student'),
            trigger_keywords = COALESCE(to_jsonb(b.keywords), '[]'::jsonb),
            effective_from = COALESCE(bv.created_at, NOW()),
            created_by = COALESCE(bv.changed_by, 'system')
        FROM behavior.behaviors b
        WHERE bv.behavior_id = b.id
    """))

    # Add indexes for version queries
    op.create_index(
        "idx_behavior_versions_status",
        "behavior_versions",
        ["status"],
        schema="behavior",
    )
    op.create_index(
        "idx_behavior_versions_role_focus",
        "behavior_versions",
        ["role_focus"],
        schema="behavior",
    )
    op.create_index(
        "idx_behavior_versions_effective_from",
        "behavior_versions",
        ["effective_from"],
        schema="behavior",
    )


def downgrade() -> None:
    """Remove added columns."""
    # Remove indexes
    op.drop_index("idx_behavior_versions_effective_from", table_name="behavior_versions", schema="behavior")
    op.drop_index("idx_behavior_versions_role_focus", table_name="behavior_versions", schema="behavior")
    op.drop_index("idx_behavior_versions_status", table_name="behavior_versions", schema="behavior")
    op.drop_index("idx_behavior_behaviors_status", table_name="behaviors", schema="behavior")

    # Remove columns from behavior_versions
    op.drop_column("behavior_versions", "embedding", schema="behavior")
    op.drop_column("behavior_versions", "embedding_checksum", schema="behavior")
    op.drop_column("behavior_versions", "approval_action_id", schema="behavior")
    op.drop_column("behavior_versions", "created_by", schema="behavior")
    op.drop_column("behavior_versions", "effective_to", schema="behavior")
    op.drop_column("behavior_versions", "effective_from", schema="behavior")
    op.drop_column("behavior_versions", "metadata", schema="behavior")
    op.drop_column("behavior_versions", "examples", schema="behavior")
    op.drop_column("behavior_versions", "trigger_keywords", schema="behavior")
    op.drop_column("behavior_versions", "status", schema="behavior")
    op.drop_column("behavior_versions", "role_focus", schema="behavior")
    op.drop_column("behavior_versions", "instruction", schema="behavior")

    # Remove columns from behaviors
    op.drop_column("behaviors", "latest_version", schema="behavior")
    op.drop_column("behaviors", "tags", schema="behavior")
    op.drop_column("behaviors", "status", schema="behavior")
