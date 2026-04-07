"""consolidate_auth_model

Revision ID: consolidate_auth
Revises: add_org_columns
Create Date: 2026-01-08

Behavior: behavior_migrate_postgres_schema

This migration consolidates the authentication model:
1. Creates auth.service_principals table for agent/service API credentials
2. Adds FK from execution.agents.owner_id to auth.users
3. Adds optional service_principal_id to execution.agents
4. Drops dead auth.internal_users table (0 records)
5. Drops related dead tables (internal_sessions, password_reset_tokens)

Auth model after migration:
- auth.users: Human users (OAuth via federated_identities)
- auth.service_principals: Agent/service API credentials (client_id/secret)
- auth.federated_identities: Links OAuth providers to users
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'consolidate_auth'
down_revision: Union[str, None] = 'add_org_columns'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Consolidate auth model with service_principals and proper FKs."""

    # =========================================================================
    # 1. Create auth.service_principals table for agent/service API credentials
    # =========================================================================
    op.create_table(
        "service_principals",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("client_id", sa.String(255), nullable=False),
        sa.Column("client_secret_hash", sa.Text(), nullable=False),
        sa.Column("allowed_scopes", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("rate_limit", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("role", sa.String(20), nullable=False, server_default="STUDENT"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column("created_by", sa.String(36), nullable=True),  # Human who created this
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", name="uq_service_principals_client_id"),
        sa.ForeignKeyConstraint(["created_by"], ["auth.users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "role IN ('STRATEGIST', 'TEACHER', 'STUDENT', 'ADMIN', 'OBSERVER')",
            name="ck_service_principals_role"
        ),
        schema="auth",
    )

    # Indexes for service_principals
    op.create_index("idx_service_principals_client_id", "service_principals", ["client_id"], schema="auth")
    op.create_index("idx_service_principals_created_by", "service_principals", ["created_by"], schema="auth")
    op.create_index("idx_service_principals_is_active", "service_principals", ["is_active"], schema="auth")

    # =========================================================================
    # 2. Add service_principal_id to execution.agents (optional FK)
    # =========================================================================
    op.add_column(
        "agents",
        sa.Column("service_principal_id", sa.String(36), nullable=True),
        schema="execution"
    )
    op.create_foreign_key(
        "fk_agents_service_principal",
        "agents",
        "service_principals",
        ["service_principal_id"],
        ["id"],
        source_schema="execution",
        referent_schema="auth",
        ondelete="SET NULL"
    )
    op.create_index(
        "idx_agents_service_principal_id",
        "agents",
        ["service_principal_id"],
        schema="execution"
    )

    # =========================================================================
    # 3. Add FK from execution.agents.owner_id to auth.users
    #    First, we need to handle the 'system' owner_id for builtins
    # =========================================================================

    # Create a system user if it doesn't exist (for builtin agents)
    op.execute("""
        INSERT INTO auth.users (id, email, display_name, is_active, email_verified)
        VALUES ('system', 'system@amprealize.local', 'System', TRUE, TRUE)
        ON CONFLICT (id) DO NOTHING
    """)

    # Now add the FK constraint
    op.create_foreign_key(
        "fk_agents_owner",
        "agents",
        "users",
        ["owner_id"],
        ["id"],
        source_schema="execution",
        referent_schema="auth",
        ondelete="CASCADE"
    )

    # =========================================================================
    # 4. Drop dead auth tables (internal_users is empty, unused)
    # =========================================================================

    # Drop internal_sessions first (depends on internal_users)
    op.execute("DROP TABLE IF EXISTS auth.internal_sessions CASCADE")

    # Drop password_reset_tokens (depends on internal_users)
    op.execute("DROP TABLE IF EXISTS auth.password_reset_tokens CASCADE")

    # Drop internal_users (dead table, 0 records)
    op.execute("DROP TABLE IF EXISTS auth.internal_users CASCADE")

    # =========================================================================
    # 5. Add comments for documentation
    # =========================================================================
    op.execute("""
        COMMENT ON TABLE auth.service_principals IS
        'API credentials for agents and services. Used for client_credentials OAuth flow.'
    """)
    op.execute("""
        COMMENT ON COLUMN auth.service_principals.client_id IS
        'Unique client identifier for API authentication'
    """)
    op.execute("""
        COMMENT ON COLUMN auth.service_principals.client_secret_hash IS
        'Bcrypt-hashed client secret'
    """)
    op.execute("""
        COMMENT ON COLUMN auth.service_principals.allowed_scopes IS
        'JSON array of allowed OAuth scopes'
    """)
    op.execute("""
        COMMENT ON COLUMN auth.service_principals.role IS
        'Role for behavior-conditioned inference: STRATEGIST, TEACHER, STUDENT, ADMIN, OBSERVER'
    """)
    op.execute("""
        COMMENT ON COLUMN execution.agents.service_principal_id IS
        'Optional FK to service_principals for agent API access. Created on demand.'
    """)


def downgrade() -> None:
    """Reverse the auth model consolidation."""

    # Remove FK from agents.owner_id
    op.drop_constraint("fk_agents_owner", "agents", schema="execution", type_="foreignkey")

    # Remove service_principal_id from agents
    op.drop_constraint("fk_agents_service_principal", "agents", schema="execution", type_="foreignkey")
    op.drop_index("idx_agents_service_principal_id", table_name="agents", schema="execution")
    op.drop_column("agents", "service_principal_id", schema="execution")

    # Drop service_principals table
    op.drop_index("idx_service_principals_is_active", table_name="service_principals", schema="auth")
    op.drop_index("idx_service_principals_created_by", table_name="service_principals", schema="auth")
    op.drop_index("idx_service_principals_client_id", table_name="service_principals", schema="auth")
    op.drop_table("service_principals", schema="auth")

    # Recreate internal_users table (dead but for rollback completeness)
    op.create_table(
        "internal_users",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("hashed_password", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uq_internal_users_username"),
        schema="auth",
    )

    # Remove system user
    op.execute("DELETE FROM auth.users WHERE id = 'system'")
