"""Add consent_requests table for JIT authorization

Revision ID: add_consent_requests
Revises: add_confidence_scoring
Create Date: 2026-01-22

Behavior: behavior_migrate_postgres_schema

This migration adds the consent_requests table to support Just-In-Time (JIT)
authorization consent flows across Web, CLI, and VS Code surfaces.

Phase 6 of MCP Auth Implementation Plan:
- Stores pending consent requests with user-friendly codes (e.g., "ABCD-1234")
- Tracks approval/denial status with timestamps
- Supports polling from MCP clients waiting for user approval
- Enables consent dashboard for approval workflows
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'add_consent_requests'
down_revision: Union[str, None] = 'add_confidence_scoring'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create consent_requests table in auth schema."""

    # Ensure auth schema exists
    op.execute("CREATE SCHEMA IF NOT EXISTS auth")

    # Create consent_requests table
    op.create_table(
        'consent_requests',
        sa.Column('id', postgresql.UUID(as_uuid=True),
                  server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('user_id', sa.String(255), nullable=False,
                  comment='User who must approve the consent request'),
        sa.Column('agent_id', sa.String(255), nullable=False,
                  comment='Agent/service principal requesting access'),
        sa.Column('tool_name', sa.String(255), nullable=False,
                  comment='MCP tool that triggered the consent request'),
        sa.Column('scopes', postgresql.JSONB, nullable=False,
                  comment='Array of scope strings being requested'),
        sa.Column('context', postgresql.JSONB, nullable=True,
                  comment='Additional context (tool params, session info)'),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending',
                  comment='pending, approved, denied, expired'),
        sa.Column('user_code', sa.String(20), nullable=False, unique=True,
                  comment='User-friendly code for display (e.g., ABCD-1234)'),
        sa.Column('user_code_normalized', sa.String(20), nullable=False,
                  comment='Normalized code without hyphens for lookup'),
        sa.Column('verification_uri', sa.String(500), nullable=False,
                  comment='Full URL for consent approval page'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False,
                  comment='When this consent request expires'),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True,
                  comment='When user approved/denied the request'),
        sa.Column('decision_by', sa.String(255), nullable=True,
                  comment='User ID of who made the decision'),
        sa.Column('decision_reason', sa.Text, nullable=True,
                  comment='Optional reason provided for approval/denial'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        schema='auth'
    )

    # Create indexes for common query patterns
    op.create_index(
        'ix_consent_requests_user_code',
        'consent_requests',
        ['user_code_normalized'],
        schema='auth'
    )

    op.create_index(
        'ix_consent_requests_user_status',
        'consent_requests',
        ['user_id', 'status'],
        schema='auth'
    )

    op.create_index(
        'ix_consent_requests_expires',
        'consent_requests',
        ['expires_at'],
        schema='auth'
    )

    op.create_index(
        'ix_consent_requests_agent',
        'consent_requests',
        ['agent_id'],
        schema='auth'
    )

    # Add trigger for updated_at
    op.execute("""
        CREATE OR REPLACE FUNCTION auth.update_consent_requests_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER consent_requests_updated_at
            BEFORE UPDATE ON auth.consent_requests
            FOR EACH ROW
            EXECUTE FUNCTION auth.update_consent_requests_updated_at();
    """)

    # Add check constraint for status values
    op.execute("""
        ALTER TABLE auth.consent_requests
        ADD CONSTRAINT consent_requests_status_check
        CHECK (status IN ('pending', 'approved', 'denied', 'expired'))
    """)


def downgrade() -> None:
    """Drop consent_requests table."""
    op.execute("DROP TRIGGER IF EXISTS consent_requests_updated_at ON auth.consent_requests")
    op.execute("DROP FUNCTION IF EXISTS auth.update_consent_requests_updated_at()")
    op.drop_table('consent_requests', schema='auth')
