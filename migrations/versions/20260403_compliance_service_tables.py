"""Add compliance schema tables used by ComplianceService (legacy SQL replacement).

Revision ID: compliance_svc_v1
Revises: 20260403_rebrand_db
Create Date: 2026-04-03

These tables match amprealize/compliance_service.py (unqualified SQL with
search_path=compliance). They are separate from audit.checklists in the baseline.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "compliance_svc_v1"
down_revision: Union[str, None] = "20260403_rebrand_db"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS compliance"))

    op.create_table(
        "checklists",
        sa.Column("checklist_id", sa.String(36), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("template_id", sa.Text(), nullable=True),
        sa.Column("milestone", sa.Text(), nullable=True),
        sa.Column("compliance_category", postgresql.JSONB(), server_default="[]"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("completed_at", sa.Text(), nullable=True),
        sa.Column("coverage_score", sa.Float(), server_default="0"),
        sa.PrimaryKeyConstraint("checklist_id"),
        schema="compliance",
    )

    op.create_table(
        "checklist_steps",
        sa.Column("step_id", sa.String(36), nullable=False),
        sa.Column("checklist_id", sa.String(36), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column("actor_role", sa.Text(), nullable=True),
        sa.Column("actor_surface", sa.Text(), nullable=True),
        sa.Column("evidence", postgresql.JSONB(), server_default="{}"),
        sa.Column("behaviors_cited", postgresql.JSONB(), server_default="[]"),
        sa.Column("related_run_id", sa.Text(), nullable=True),
        sa.Column("audit_log_event_id", sa.Text(), nullable=True),
        sa.Column("validation_result", postgresql.JSONB(), server_default="{}"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("step_id"),
        sa.ForeignKeyConstraint(
            ["checklist_id"],
            ["compliance.checklists.checklist_id"],
            ondelete="CASCADE",
        ),
        schema="compliance",
    )
    op.create_index(
        "idx_compliance_steps_checklist",
        "checklist_steps",
        ["checklist_id"],
        schema="compliance",
    )

    op.create_table(
        "compliance_policies",
        sa.Column("policy_id", sa.String(36), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.Text(), nullable=True),
        sa.Column("org_id", sa.Text(), nullable=True),
        sa.Column("project_id", sa.Text(), nullable=True),
        sa.Column("policy_type", sa.String(64), nullable=False),
        sa.Column("enforcement_level", sa.String(32), nullable=False),
        sa.Column("rules", postgresql.JSONB(), server_default="[]"),
        sa.Column("required_behaviors", postgresql.JSONB(), server_default="[]"),
        sa.Column("compliance_categories", postgresql.JSONB(), server_default="[]"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_by_id", sa.Text(), nullable=True),
        sa.Column("created_by_role", sa.Text(), nullable=True),
        sa.Column("created_by_surface", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), server_default="{}"),
        sa.PrimaryKeyConstraint("policy_id"),
        schema="compliance",
    )
    op.create_index(
        "idx_compliance_policies_org",
        "compliance_policies",
        ["org_id"],
        schema="compliance",
    )
    op.create_index(
        "idx_compliance_policies_project",
        "compliance_policies",
        ["project_id"],
        schema="compliance",
    )


def downgrade() -> None:
    op.drop_table("compliance_policies", schema="compliance")
    op.drop_table("checklist_steps", schema="compliance")
    op.drop_table("checklists", schema="compliance")
    op.execute(sa.text("DROP SCHEMA IF EXISTS compliance CASCADE"))
