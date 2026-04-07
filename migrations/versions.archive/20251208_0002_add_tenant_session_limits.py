"""Add tenant session limits and migration tracking

Revision ID: 0002_tenant_limits
Revises: 0001_baseline
Create Date: 2025-12-08

Behavior: behavior_migrate_postgres_schema

Adds:
1. Tenant-specific session limits (statement_timeout, lock_timeout)
2. Tenant limit configuration in organizations table
3. Migration version tracking table for visibility
4. Helper functions for applying session limits
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002_tenant_limits"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply tenant session limits schema."""

    # Add tenant-specific limit columns to organizations table
    op.execute("""
        ALTER TABLE organizations
        ADD COLUMN IF NOT EXISTS statement_timeout_ms INT NOT NULL DEFAULT 30000,
        ADD COLUMN IF NOT EXISTS lock_timeout_ms INT NOT NULL DEFAULT 10000,
        ADD COLUMN IF NOT EXISTS max_connections INT NOT NULL DEFAULT 5,
        ADD COLUMN IF NOT EXISTS max_rows_per_query INT NOT NULL DEFAULT 10000
    """)

    # Add comment
    op.execute("""
        COMMENT ON COLUMN organizations.statement_timeout_ms IS
            'Max query execution time in milliseconds (default: 30s)';
        COMMENT ON COLUMN organizations.lock_timeout_ms IS
            'Max time to wait for locks in milliseconds (default: 10s)';
        COMMENT ON COLUMN organizations.max_connections IS
            'Max concurrent connections per tenant (default: 5)';
        COMMENT ON COLUMN organizations.max_rows_per_query IS
            'Max rows returned per query (default: 10000)';
    """)

    # Create function to apply tenant session limits
    op.execute("""
        CREATE OR REPLACE FUNCTION apply_tenant_limits(p_org_id TEXT)
        RETURNS VOID AS $$
        DECLARE
            v_statement_timeout INT;
            v_lock_timeout INT;
        BEGIN
            -- Get tenant-specific limits (or defaults)
            SELECT
                COALESCE(statement_timeout_ms, 30000),
                COALESCE(lock_timeout_ms, 10000)
            INTO v_statement_timeout, v_lock_timeout
            FROM organizations
            WHERE id = p_org_id;

            -- Apply limits if org found
            IF FOUND THEN
                EXECUTE format('SET statement_timeout = %s', v_statement_timeout);
                EXECUTE format('SET lock_timeout = %s', v_lock_timeout);
            ELSE
                -- Apply defaults for unknown/no org
                SET statement_timeout = 30000;
                SET lock_timeout = 10000;
            END IF;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER;
    """)

    # Create function to set tenant context WITH limits
    op.execute("""
        CREATE OR REPLACE FUNCTION set_tenant_context(
            p_org_id TEXT,
            p_user_id TEXT DEFAULT NULL
        ) RETURNS VOID AS $$
        BEGIN
            -- Set session variables for RLS
            PERFORM set_config('app.current_org_id', COALESCE(p_org_id, ''), false);
            PERFORM set_config('app.current_user_id', COALESCE(p_user_id, ''), false);

            -- Apply tenant-specific resource limits
            IF p_org_id IS NOT NULL THEN
                PERFORM apply_tenant_limits(p_org_id);
            END IF;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER;
    """)

    # Create migration tracking table for visibility (supplements alembic_version)
    op.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version VARCHAR(100) PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            checksum VARCHAR(64),
            applied_by VARCHAR(100) DEFAULT current_user,
            execution_time_ms INT,
            success BOOLEAN NOT NULL DEFAULT TRUE,
            error_message TEXT
        );

        COMMENT ON TABLE schema_migrations IS
            'Detailed migration tracking with timing and error info (supplements alembic_version)';
    """)

    # Index for recent migrations
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_schema_migrations_applied
        ON schema_migrations(applied_at DESC);
    """)


def downgrade() -> None:
    """Revert tenant session limits schema."""

    # Drop functions
    op.execute("DROP FUNCTION IF EXISTS set_tenant_context(TEXT, TEXT)")
    op.execute("DROP FUNCTION IF EXISTS apply_tenant_limits(TEXT)")

    # Drop migration tracking table
    op.execute("DROP TABLE IF EXISTS schema_migrations")

    # Remove tenant limit columns from organizations
    op.execute("""
        ALTER TABLE organizations
        DROP COLUMN IF EXISTS statement_timeout_ms,
        DROP COLUMN IF EXISTS lock_timeout_ms,
        DROP COLUMN IF EXISTS max_connections,
        DROP COLUMN IF EXISTS max_rows_per_query
    """)
