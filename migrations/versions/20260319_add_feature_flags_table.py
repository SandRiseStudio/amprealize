"""Add feature_flags table.

Creates the feature_flags table for persistent per-org/per-project
feature flag storage, complementing the in-memory FeatureFlagService.

Revision ID: 20260319_add_feature_flags
Revises: 20260318_add_kp_tables
Create Date: 2026-03-19

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers
revision = "20260319_add_feature_flags"
down_revision = "20260318_add_kp_tables"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "feature_flags",
        sa.Column("flag_name", sa.String(128), nullable=False),
        sa.Column(
            "scope",
            sa.String(16),
            nullable=False,
            server_default="global",
            comment="global | org | project",
        ),
        sa.Column(
            "scope_id",
            sa.String(128),
            nullable=False,
            server_default="__global__",
            comment="org_id or project_id; __global__ for global scope",
        ),
        sa.Column(
            "flag_type",
            sa.String(16),
            nullable=False,
            server_default="boolean",
            comment="boolean | percentage | user_list",
        ),
        sa.Column("enabled", sa.Boolean, server_default="false", nullable=False),
        sa.Column(
            "percentage",
            sa.Integer,
            server_default="0",
            nullable=False,
            comment="Rollout percentage 0-100 (for percentage type)",
        ),
        sa.Column(
            "user_list",
            postgresql.ARRAY(sa.Text),
            server_default="{}",
            nullable=False,
            comment="Allowed user IDs (for user_list type)",
        ),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB,
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("flag_name", "scope", "scope_id"),
    )
    op.create_index(
        "ix_feature_flags_scope",
        "feature_flags",
        ["scope", "scope_id"],
    )
    op.create_index(
        "ix_feature_flags_name",
        "feature_flags",
        ["flag_name"],
    )


def downgrade():
    op.drop_table("feature_flags")
