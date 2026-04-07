"""Add token_vault and blacklist tables for secure OAuth token storage

Revision ID: add_token_vault
Revises: add_consent_requests
Create Date: 2026-01-22

Behavior: behavior_migrate_postgres_schema, behavior_lock_down_security_surface

This migration adds the token_vault and token_blacklist tables to support
KMS-encrypted OAuth token storage with revocation capabilities.

Phase 8 of MCP Auth Implementation Plan:
- Stores encrypted OAuth tokens (access + refresh)
- Tracks token lifecycle (issued, rotated, expired, revoked)
- Maintains blacklist for revoked tokens
- Supports multiple encryption providers (Fernet, AWS KMS, HashiCorp Vault)
- Enables automatic token rotation and cleanup

Security features:
- Tokens are encrypted at rest using envelope encryption
- Only token metadata is stored in clear text
- Blacklist prevents reuse of revoked tokens
- Automatic cleanup of expired entries
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'add_token_vault'
down_revision: Union[str, None] = 'add_consent_requests'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create token_vault and token_blacklist tables in auth schema."""

    # Ensure auth schema exists
    op.execute("CREATE SCHEMA IF NOT EXISTS auth")

    # Create token_vault table
    op.create_table(
        'token_vault',
        sa.Column('id', postgresql.UUID(as_uuid=True),
                  server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('user_id', sa.String(255), nullable=False,
                  comment='User ID who owns this token'),
        sa.Column('provider', sa.String(100), nullable=False,
                  comment='OAuth provider (google, github, microsoft, amprealize, custom)'),
        sa.Column('token_type', sa.String(50), nullable=False,
                  comment='Token type (access, refresh, api_key, service_principal)'),
        sa.Column('encrypted_data', sa.Text, nullable=False,
                  comment='Encrypted token data (access_token + refresh_token)'),
        sa.Column('scopes', postgresql.JSONB, nullable=True,
                  comment='Array of granted scope strings'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True,
                  comment='When the access token expires'),
        sa.Column('issued_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False,
                  comment='When the token was issued/stored'),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True,
                  comment='When the token was last accessed'),
        sa.Column('rotation_count', sa.Integer, server_default='0', nullable=False,
                  comment='Number of times token has been rotated'),
        sa.Column('status', sa.String(50), server_default='active', nullable=False,
                  comment='Token status (active, expired, revoked, rotated)'),
        sa.Column('metadata', postgresql.JSONB, nullable=True,
                  comment='Additional metadata (client_id, device_info, etc.)'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        schema='auth'
    )

    # Create unique constraint on (user_id, provider, token_type)
    # This ensures only one active token per user/provider/type combination
    op.create_unique_constraint(
        'uq_token_vault_user_provider_type',
        'token_vault',
        ['user_id', 'provider', 'token_type'],
        schema='auth'
    )

    # Create indexes for common query patterns
    op.create_index(
        'ix_token_vault_user_id',
        'token_vault',
        ['user_id'],
        schema='auth'
    )

    op.create_index(
        'ix_token_vault_user_provider',
        'token_vault',
        ['user_id', 'provider'],
        schema='auth'
    )

    op.create_index(
        'ix_token_vault_status',
        'token_vault',
        ['status'],
        schema='auth'
    )

    op.create_index(
        'ix_token_vault_expires_at',
        'token_vault',
        ['expires_at'],
        schema='auth'
    )

    op.create_index(
        'ix_token_vault_provider_status',
        'token_vault',
        ['provider', 'status'],
        schema='auth'
    )

    # Create token_blacklist table
    op.create_table(
        'token_blacklist',
        sa.Column('id', postgresql.UUID(as_uuid=True),
                  server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True,
                  comment='SHA-256 hash of the revoked token'),
        sa.Column('user_id', sa.String(255), nullable=False,
                  comment='User ID who owned the revoked token'),
        sa.Column('provider', sa.String(100), nullable=False,
                  comment='OAuth provider of the revoked token'),
        sa.Column('reason', sa.Text, nullable=False,
                  comment='Reason for revocation'),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=False,
                  comment='When the token was revoked'),
        sa.Column('revoked_by', sa.String(255), nullable=False,
                  comment='User/system that performed the revocation'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True,
                  comment='When this blacklist entry can be cleaned up'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        schema='auth'
    )

    # Create indexes for token_blacklist
    op.create_index(
        'ix_token_blacklist_hash',
        'token_blacklist',
        ['token_hash'],
        schema='auth'
    )

    op.create_index(
        'ix_token_blacklist_user_id',
        'token_blacklist',
        ['user_id'],
        schema='auth'
    )

    op.create_index(
        'ix_token_blacklist_expires_at',
        'token_blacklist',
        ['expires_at'],
        schema='auth'
    )

    op.create_index(
        'ix_token_blacklist_revoked_at',
        'token_blacklist',
        ['revoked_at'],
        schema='auth'
    )

    # Create audit log table for token operations
    op.create_table(
        'token_audit_log',
        sa.Column('id', postgresql.UUID(as_uuid=True),
                  server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('token_id', postgresql.UUID(as_uuid=True), nullable=True,
                  comment='Reference to token_vault.id (null if token deleted)'),
        sa.Column('user_id', sa.String(255), nullable=False,
                  comment='User ID involved in the operation'),
        sa.Column('provider', sa.String(100), nullable=False,
                  comment='OAuth provider'),
        sa.Column('operation', sa.String(50), nullable=False,
                  comment='Operation type (store, get, rotate, revoke, delete)'),
        sa.Column('status', sa.String(50), nullable=False,
                  comment='Operation status (success, failure)'),
        sa.Column('details', postgresql.JSONB, nullable=True,
                  comment='Additional operation details'),
        sa.Column('ip_address', sa.String(45), nullable=True,
                  comment='Client IP address (for web operations)'),
        sa.Column('user_agent', sa.Text, nullable=True,
                  comment='Client user agent (for web operations)'),
        sa.Column('performed_by', sa.String(255), nullable=False,
                  comment='User/system that performed the operation'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        schema='auth'
    )

    # Create indexes for audit log
    op.create_index(
        'ix_token_audit_log_user_id',
        'token_audit_log',
        ['user_id'],
        schema='auth'
    )

    op.create_index(
        'ix_token_audit_log_token_id',
        'token_audit_log',
        ['token_id'],
        schema='auth'
    )

    op.create_index(
        'ix_token_audit_log_operation',
        'token_audit_log',
        ['operation'],
        schema='auth'
    )

    op.create_index(
        'ix_token_audit_log_created_at',
        'token_audit_log',
        ['created_at'],
        schema='auth'
    )

    # Create partial index for active tokens (performance optimization)
    op.execute("""
        CREATE INDEX ix_token_vault_active
        ON auth.token_vault (user_id, provider, token_type)
        WHERE status = 'active'
    """)

    # Create partial index for permanent blacklist entries (no expiry)
    # Note: For time-based filtering, queries should use expires_at > CURRENT_TIMESTAMP
    op.execute("""
        CREATE INDEX ix_token_blacklist_permanent
        ON auth.token_blacklist (token_hash)
        WHERE expires_at IS NULL
    """)

    # Add trigger for updated_at timestamp
    op.execute("""
        CREATE OR REPLACE FUNCTION auth.update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)

    op.execute("""
        CREATE TRIGGER update_token_vault_updated_at
        BEFORE UPDATE ON auth.token_vault
        FOR EACH ROW
        EXECUTE FUNCTION auth.update_updated_at_column();
    """)


def downgrade() -> None:
    """Remove token_vault, token_blacklist, and token_audit_log tables."""

    # Drop trigger first
    op.execute("DROP TRIGGER IF EXISTS update_token_vault_updated_at ON auth.token_vault")
    op.execute("DROP FUNCTION IF EXISTS auth.update_updated_at_column()")

    # Drop partial indexes
    op.execute("DROP INDEX IF EXISTS auth.ix_token_vault_active")
    op.execute("DROP INDEX IF EXISTS auth.ix_token_blacklist_permanent")

    # Drop tables
    op.drop_table('token_audit_log', schema='auth')
    op.drop_table('token_blacklist', schema='auth')
    op.drop_table('token_vault', schema='auth')
