"""Add knowledge pack tables.

Creates the four core tables for the Knowledge Pack system:
- knowledge_pack_sources: registered pack sources (files, services)
- knowledge_pack_manifests: versioned pack definitions (JSONB)
- knowledge_pack_overlays: individual overlay fragments
- knowledge_pack_activations: workspace-level pack activations

Revision ID: 20260318_add_kp_tables
Revises: 20260218_unify_projects
Create Date: 2026-03-18

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers
revision = "20260318_add_kp_tables"
down_revision = "20260218_project_display_idx"
branch_labels = None
depends_on = None


def upgrade():
    # --- knowledge_pack_sources ---
    op.create_table(
        "knowledge_pack_sources",
        sa.Column("source_id", sa.String(64), primary_key=True),
        sa.Column(
            "source_type",
            sa.String(16),
            nullable=False,
            comment="file | service",
        ),
        sa.Column("ref", sa.Text, nullable=False),
        sa.Column(
            "scope",
            sa.String(32),
            nullable=False,
            server_default="canonical",
        ),
        sa.Column("owner", sa.String(128), nullable=True),
        sa.Column("version_hash", sa.String(64), nullable=True),
        sa.Column("generation_eligible", sa.Boolean, server_default="true"),
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
    )
    op.create_index(
        "ix_kp_sources_scope",
        "knowledge_pack_sources",
        ["scope"],
    )

    # --- knowledge_pack_manifests ---
    op.create_table(
        "knowledge_pack_manifests",
        sa.Column("pack_id", sa.String(128), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("manifest_json", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("pack_id", "version"),
    )
    op.create_index(
        "ix_kp_manifests_status",
        "knowledge_pack_manifests",
        ["status"],
    )

    # --- knowledge_pack_overlays ---
    op.create_table(
        "knowledge_pack_overlays",
        sa.Column("overlay_id", sa.String(128), primary_key=True),
        sa.Column("pack_id", sa.String(128), nullable=False),
        sa.Column("pack_version", sa.String(32), nullable=False),
        sa.Column(
            "kind",
            sa.String(16),
            nullable=False,
            comment="task | surface | role",
        ),
        sa.Column("applies_to", postgresql.JSONB, server_default="{}"),
        sa.Column("instructions", postgresql.JSONB, server_default="[]"),
        sa.Column(
            "retrieval_keywords",
            postgresql.ARRAY(sa.Text),
            server_default="{}",
        ),
        sa.Column("priority", sa.Integer, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_kp_overlays_pack",
        "knowledge_pack_overlays",
        ["pack_id", "pack_version"],
    )
    op.create_index(
        "ix_kp_overlays_kind",
        "knowledge_pack_overlays",
        ["kind"],
    )

    # --- knowledge_pack_activations ---
    op.create_table(
        "knowledge_pack_activations",
        sa.Column("activation_id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(128), nullable=False),
        sa.Column("pack_id", sa.String(128), nullable=False),
        sa.Column("pack_version", sa.String(32), nullable=False),
        sa.Column("profile", sa.String(64), nullable=True),
        sa.Column(
            "activated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("activated_by", sa.String(128), nullable=True),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
    )
    op.create_index(
        "ix_kp_activations_workspace",
        "knowledge_pack_activations",
        ["workspace_id"],
    )
    op.create_index(
        "ix_kp_activations_pack",
        "knowledge_pack_activations",
        ["pack_id", "pack_version"],
    )


def downgrade():
    op.drop_table("knowledge_pack_activations")
    op.drop_table("knowledge_pack_overlays")
    op.drop_table("knowledge_pack_manifests")
    op.drop_table("knowledge_pack_sources")
