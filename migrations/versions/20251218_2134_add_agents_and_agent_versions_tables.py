"""add_agents_and_agent_versions_tables

Revision ID: c44af61ae484
Revises: schema_baseline
Create Date: 2025-12-18 21:34:49.707465+00:00

Behavior: behavior_migrate_postgres_schema

This migration adds the agents and agent_versions tables to the execution schema.
These tables were missing from the baseline migration but are required by AgentRegistryService.
Schema based on schema/migrations.archive/029_create_agent_registry.sql.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c44af61ae484'
down_revision: Union[str, None] = 'schema_baseline'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create agents and agent_versions tables in execution schema."""

    # =========================================================================
    # execution.agents - Main agents table
    # =========================================================================
    op.create_table(
        "agents",
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("tags", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("latest_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("visibility", sa.Text(), nullable=False, server_default="PRIVATE"),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=True),
        sa.Column("published_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.PrimaryKeyConstraint("agent_id"),
        sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'DEPRECATED')", name="ck_agents_status"),
        sa.CheckConstraint("visibility IN ('PRIVATE', 'ORGANIZATION', 'PUBLIC')", name="ck_agents_visibility"),
        sa.UniqueConstraint("org_id", "slug", name="uq_agents_org_slug"),
        schema="execution",
    )

    # Indexes for agent discovery queries
    op.create_index("idx_agents_status", "agents", ["status"], schema="execution")
    op.create_index("idx_agents_visibility", "agents", ["visibility"], schema="execution")
    op.create_index("idx_agents_owner_id", "agents", ["owner_id"], schema="execution")
    op.create_index("idx_agents_org_id", "agents", ["org_id"], schema="execution", postgresql_where=sa.text("org_id IS NOT NULL"))
    op.create_index("idx_agents_updated_at", "agents", [sa.text("updated_at DESC")], schema="execution")
    op.create_index("idx_agents_slug", "agents", ["slug"], schema="execution")
    op.create_index("idx_agents_tags_gin", "agents", ["tags"], schema="execution", postgresql_using="gin", postgresql_ops={"tags": "jsonb_path_ops"})
    op.create_index("idx_agents_is_builtin", "agents", ["is_builtin"], schema="execution", postgresql_where=sa.text("is_builtin = TRUE"))

    # Text search index for agent discovery
    op.execute("""
        CREATE INDEX idx_agents_fulltext ON execution.agents
        USING GIN (to_tsvector('english', name || ' ' || description))
    """)

    # Composite index for marketplace queries
    op.execute("""
        CREATE INDEX idx_agents_marketplace ON execution.agents (visibility, status, updated_at DESC)
        WHERE visibility = 'PUBLIC' AND status = 'ACTIVE'
    """)

    # =========================================================================
    # execution.agent_versions - Versioned agent content
    # =========================================================================
    op.create_table(
        "agent_versions",
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("mission", sa.Text(), nullable=False),
        sa.Column("role_alignment", sa.Text(), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("default_behaviors", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("playbook_content", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("effective_from", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("effective_to", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_from", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.PrimaryKeyConstraint("agent_id", "version"),
        sa.ForeignKeyConstraint(["agent_id"], ["execution.agents.agent_id"], ondelete="CASCADE"),
        sa.CheckConstraint("role_alignment IN ('STRATEGIST', 'TEACHER', 'STUDENT', 'MULTI_ROLE')", name="ck_agent_versions_role"),
        sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'DEPRECATED')", name="ck_agent_versions_status"),
        schema="execution",
    )

    # Indexes for agent version queries
    op.create_index("idx_agent_versions_status", "agent_versions", ["status"], schema="execution")
    op.create_index("idx_agent_versions_role_alignment", "agent_versions", ["role_alignment"], schema="execution")
    op.create_index("idx_agent_versions_effective_from", "agent_versions", ["effective_from"], schema="execution")
    op.create_index("idx_agent_versions_capabilities", "agent_versions", ["capabilities"], schema="execution", postgresql_using="gin")
    op.create_index("idx_agent_versions_default_behaviors", "agent_versions", ["default_behaviors"], schema="execution", postgresql_using="gin")

    # =========================================================================
    # Row-Level Security policies
    # =========================================================================
    op.execute("ALTER TABLE execution.agents ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE execution.agent_versions ENABLE ROW LEVEL SECURITY")

    # Policy: Users can see their own agents
    op.execute("""
        CREATE POLICY agents_owner_policy ON execution.agents
            FOR ALL
            USING (owner_id = current_setting('app.current_user_id', TRUE))
    """)

    # Policy: Users can see org agents if they belong to the org
    op.execute("""
        CREATE POLICY agents_org_policy ON execution.agents
            FOR SELECT
            USING (
                org_id IS NOT NULL
                AND org_id = current_setting('app.current_org_id', TRUE)
                AND visibility IN ('ORGANIZATION', 'PUBLIC')
            )
    """)

    # Policy: Users can see public agents
    op.execute("""
        CREATE POLICY agents_public_policy ON execution.agents
            FOR SELECT
            USING (visibility = 'PUBLIC' AND status = 'ACTIVE')
    """)

    # Policy: Users can see builtin (system) agents
    op.execute("""
        CREATE POLICY agents_builtin_policy ON execution.agents
            FOR SELECT
            USING (is_builtin = TRUE)
    """)

    # Agent versions inherit access from parent agent
    op.execute("""
        CREATE POLICY agent_versions_policy ON execution.agent_versions
            FOR ALL
            USING (
                agent_id IN (SELECT agent_id FROM execution.agents)
            )
    """)


def downgrade() -> None:
    """Drop agents and agent_versions tables."""
    # Drop policies first
    op.execute("DROP POLICY IF EXISTS agent_versions_policy ON execution.agent_versions")
    op.execute("DROP POLICY IF EXISTS agents_builtin_policy ON execution.agents")
    op.execute("DROP POLICY IF EXISTS agents_public_policy ON execution.agents")
    op.execute("DROP POLICY IF EXISTS agents_org_policy ON execution.agents")
    op.execute("DROP POLICY IF EXISTS agents_owner_policy ON execution.agents")

    # Drop tables
    op.drop_table("agent_versions", schema="execution")
    op.drop_table("agents", schema="execution")
