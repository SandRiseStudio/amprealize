"""drop_internal_users_final

Revision ID: drop_internal_users
Revises: consolidate_auth
Create Date: 2026-01-09

Behavior: behavior_migrate_postgres_schema

This migration forcefully removes all internal_users related tables from both
auth and public schemas. The previous migration (consolidate_auth) attempted
to drop these but they persisted.

Tables to drop (in dependency order):
1. auth.internal_sessions (FK to auth.internal_users)
2. auth.password_reset_tokens (FK to auth.internal_users)
3. auth.internal_users
4. public.internal_sessions (FK to public.internal_users)
5. public.password_reset_tokens (FK to public.internal_users)
6. public.internal_users

These tables are deprecated - human users live in auth.users, agents in execution.agents.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'drop_internal_users'
down_revision: Union[str, None] = 'consolidate_auth'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop all internal_users related tables from auth and public schemas."""

    # =========================================================================
    # Drop from auth schema (in FK dependency order)
    # =========================================================================

    # Drop FK constraints first if they exist
    op.execute("""
        DO $$
        BEGIN
            -- Drop FK from internal_sessions to internal_users
            IF EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = 'internal_sessions_user_id_fkey'
                AND table_schema = 'auth'
            ) THEN
                ALTER TABLE auth.internal_sessions DROP CONSTRAINT internal_sessions_user_id_fkey;
            END IF;

            -- Drop FK from password_reset_tokens to internal_users
            IF EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = 'password_reset_tokens_user_id_fkey'
                AND table_schema = 'auth'
            ) THEN
                ALTER TABLE auth.password_reset_tokens DROP CONSTRAINT password_reset_tokens_user_id_fkey;
            END IF;
        END $$;
    """)

    # Now drop the tables
    op.execute("DROP TABLE IF EXISTS auth.internal_sessions CASCADE")
    op.execute("DROP TABLE IF EXISTS auth.password_reset_tokens CASCADE")
    op.execute("DROP TABLE IF EXISTS auth.internal_users CASCADE")

    # =========================================================================
    # Drop from public schema (in FK dependency order)
    # =========================================================================

    op.execute("""
        DO $$
        BEGIN
            -- Drop FK from internal_sessions to internal_users in public schema
            IF EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = 'internal_sessions_user_id_fkey'
                AND table_schema = 'public'
            ) THEN
                ALTER TABLE public.internal_sessions DROP CONSTRAINT internal_sessions_user_id_fkey;
            END IF;

            -- Drop FK from password_reset_tokens to internal_users in public schema
            IF EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = 'password_reset_tokens_user_id_fkey'
                AND table_schema = 'public'
            ) THEN
                ALTER TABLE public.password_reset_tokens DROP CONSTRAINT password_reset_tokens_user_id_fkey;
            END IF;
        END $$;
    """)

    op.execute("DROP TABLE IF EXISTS public.internal_sessions CASCADE")
    op.execute("DROP TABLE IF EXISTS public.password_reset_tokens CASCADE")
    op.execute("DROP TABLE IF EXISTS public.internal_users CASCADE")

    # =========================================================================
    # Clean up any orphaned sequences
    # =========================================================================
    op.execute("DROP SEQUENCE IF EXISTS auth.internal_users_id_seq CASCADE")
    op.execute("DROP SEQUENCE IF EXISTS public.internal_users_id_seq CASCADE")


def downgrade() -> None:
    """Recreate internal_users tables (for rollback only - these are deprecated)."""

    # Recreate auth.internal_users
    op.execute("""
        CREATE TABLE IF NOT EXISTS auth.internal_users (
            id VARCHAR(36) PRIMARY KEY,
            username VARCHAR(255) NOT NULL UNIQUE,
            email VARCHAR(255),
            hashed_password VARCHAR(255),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            is_admin BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
    """)

    # Recreate auth.internal_sessions
    op.execute("""
        CREATE TABLE IF NOT EXISTS auth.internal_sessions (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES auth.internal_users(id) ON DELETE CASCADE,
            session_token VARCHAR(255) NOT NULL UNIQUE,
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
    """)

    # Recreate auth.password_reset_tokens
    op.execute("""
        CREATE TABLE IF NOT EXISTS auth.password_reset_tokens (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES auth.internal_users(id) ON DELETE CASCADE,
            token VARCHAR(255) NOT NULL UNIQUE,
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
    """)
