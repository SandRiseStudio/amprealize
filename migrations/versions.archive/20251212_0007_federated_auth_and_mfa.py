"""Add federated identity, MFA, and email verification tables

Revision ID: 0007_federated_auth
Revises: 20251211_0006_legacy_sql_026_031
Create Date: 2025-12-12

Behavior: behavior_migrate_postgres_schema

This migration adds tables for:
- federated_identities: Links OAuth providers (GitHub, Google) to internal users
- mfa_devices: Stores TOTP secrets and backup codes for multi-factor auth
- email_verification_tokens: Tokens for email address confirmation

User decisions implemented:
1. MFA required for high-risk scopes only (policy-driven, not schema-enforced)
2. Email verification required before account is fully active
3. Password confirmation required when linking OAuth to existing email account
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0007_federated_auth"
down_revision: Union[str, None] = "0006_legacy_sql_026_031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create federated auth and MFA tables."""

    # =========================================================================
    # FEDERATED IDENTITIES TABLE
    # =========================================================================
    # Links external OAuth provider accounts to internal users.
    # A user can have multiple federated identities (GitHub + Google + email).
    op.execute("""
        CREATE TABLE IF NOT EXISTS federated_identities (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES internal_users(id) ON DELETE CASCADE,
            provider VARCHAR(50) NOT NULL,
            provider_user_id VARCHAR(255) NOT NULL,
            provider_email VARCHAR(255),
            provider_username VARCHAR(255),
            provider_display_name VARCHAR(255),
            provider_avatar_url TEXT,
            access_token_encrypted TEXT,
            refresh_token_encrypted TEXT,
            token_expires_at TIMESTAMPTZ,
            scopes TEXT[],
            raw_profile JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_used_at TIMESTAMPTZ,
            UNIQUE (provider, provider_user_id)
        );

        CREATE INDEX IF NOT EXISTS idx_federated_identities_user_id
            ON federated_identities(user_id);
        CREATE INDEX IF NOT EXISTS idx_federated_identities_provider_email
            ON federated_identities(provider_email) WHERE provider_email IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_federated_identities_provider_lookup
            ON federated_identities(provider, provider_user_id);

        COMMENT ON TABLE federated_identities IS 'Links external OAuth providers to internal user accounts';
        COMMENT ON COLUMN federated_identities.provider IS 'OAuth provider: github, google, microsoft, etc.';
        COMMENT ON COLUMN federated_identities.provider_user_id IS 'User ID from the OAuth provider';
        COMMENT ON COLUMN federated_identities.access_token_encrypted IS 'Encrypted OAuth access token (AES-256-GCM)';
        COMMENT ON COLUMN federated_identities.scopes IS 'Array of OAuth scopes granted';
    """)

    # Trigger to auto-update updated_at
    op.execute("""
        CREATE OR REPLACE FUNCTION update_federated_identities_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trigger_federated_identities_updated_at ON federated_identities;
        CREATE TRIGGER trigger_federated_identities_updated_at
            BEFORE UPDATE ON federated_identities
            FOR EACH ROW
            EXECUTE FUNCTION update_federated_identities_updated_at();
    """)

    # =========================================================================
    # MFA DEVICES TABLE
    # =========================================================================
    # Stores TOTP secrets and backup codes for multi-factor authentication.
    # Device flow acts as an MFA mechanism for high-risk scopes.
    op.execute("""
        CREATE TABLE IF NOT EXISTS mfa_devices (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES internal_users(id) ON DELETE CASCADE,
            device_type VARCHAR(50) NOT NULL DEFAULT 'totp',
            device_name VARCHAR(255),
            secret_encrypted TEXT NOT NULL,
            backup_codes_encrypted TEXT,
            is_verified BOOLEAN NOT NULL DEFAULT FALSE,
            is_primary BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            verified_at TIMESTAMPTZ,
            last_used_at TIMESTAMPTZ,
            CONSTRAINT valid_device_type CHECK (device_type IN ('totp', 'webauthn', 'sms', 'email'))
        );

        CREATE INDEX IF NOT EXISTS idx_mfa_devices_user_id ON mfa_devices(user_id);
        CREATE INDEX IF NOT EXISTS idx_mfa_devices_user_verified
            ON mfa_devices(user_id, is_verified) WHERE is_verified = TRUE;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_mfa_devices_user_primary
            ON mfa_devices(user_id) WHERE is_primary = TRUE AND is_verified = TRUE;

        COMMENT ON TABLE mfa_devices IS 'Multi-factor authentication devices (TOTP, WebAuthn, etc.)';
        COMMENT ON COLUMN mfa_devices.secret_encrypted IS 'Encrypted TOTP secret or WebAuthn credential (AES-256-GCM)';
        COMMENT ON COLUMN mfa_devices.backup_codes_encrypted IS 'Encrypted JSON array of one-time backup codes';
        COMMENT ON COLUMN mfa_devices.is_primary IS 'Primary MFA device for this user (only one per user)';
    """)

    # =========================================================================
    # EMAIL VERIFICATION TOKENS TABLE
    # =========================================================================
    # Tokens for confirming email addresses before account activation.
    op.execute("""
        CREATE TABLE IF NOT EXISTS email_verification_tokens (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES internal_users(id) ON DELETE CASCADE,
            email VARCHAR(255) NOT NULL,
            token VARCHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL,
            verified_at TIMESTAMPTZ,
            UNIQUE (token)
        );

        CREATE INDEX IF NOT EXISTS idx_email_verification_token ON email_verification_tokens(token);
        CREATE INDEX IF NOT EXISTS idx_email_verification_user_id ON email_verification_tokens(user_id);
        CREATE INDEX IF NOT EXISTS idx_email_verification_email ON email_verification_tokens(email);
        CREATE INDEX IF NOT EXISTS idx_email_verification_expires
            ON email_verification_tokens(expires_at) WHERE verified_at IS NULL;

        COMMENT ON TABLE email_verification_tokens IS 'Tokens for email address verification';
        COMMENT ON COLUMN email_verification_tokens.token IS 'Secure random token sent via email';
    """)

    # =========================================================================
    # ADD email_verified COLUMN TO internal_users
    # =========================================================================
    op.execute("""
        ALTER TABLE internal_users
        ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT FALSE;

        ALTER TABLE internal_users
        ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ;

        CREATE INDEX IF NOT EXISTS idx_internal_users_email_verified
            ON internal_users(email_verified) WHERE email_verified = TRUE;

        COMMENT ON COLUMN internal_users.email_verified IS 'TRUE if email has been verified via token';
    """)

    # =========================================================================
    # CLEANUP FUNCTION
    # =========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION cleanup_expired_verification_tokens()
        RETURNS INTEGER AS $$
        DECLARE
            deleted_count INTEGER := 0;
            temp_count INTEGER;
        BEGIN
            -- Clean up expired email verification tokens (older than 7 days past expiry)
            DELETE FROM email_verification_tokens
            WHERE expires_at < NOW() - INTERVAL '7 days'
            AND verified_at IS NULL;
            GET DIAGNOSTICS temp_count = ROW_COUNT;
            deleted_count := deleted_count + temp_count;

            RETURN deleted_count;
        END;
        $$ LANGUAGE plpgsql;

        COMMENT ON FUNCTION cleanup_expired_verification_tokens IS
            'Removes expired email verification tokens';
    """)

    # =========================================================================
    # VERIFICATION QUERY
    # =========================================================================
    op.execute("""
        DO $$
        BEGIN
            RAISE NOTICE 'Migration 0007_federated_auth completed successfully';
            RAISE NOTICE 'Tables created: federated_identities, mfa_devices, email_verification_tokens';
            RAISE NOTICE 'Columns added: internal_users.email_verified, internal_users.email_verified_at';
        END $$;
    """)


def downgrade() -> None:
    """Remove federated auth and MFA tables."""

    # Drop functions first
    op.execute("DROP FUNCTION IF EXISTS cleanup_expired_verification_tokens();")
    op.execute("DROP FUNCTION IF EXISTS update_federated_identities_updated_at() CASCADE;")

    # Drop tables
    op.execute("DROP TABLE IF EXISTS email_verification_tokens CASCADE;")
    op.execute("DROP TABLE IF EXISTS mfa_devices CASCADE;")
    op.execute("DROP TABLE IF EXISTS federated_identities CASCADE;")

    # Remove columns from internal_users
    op.execute("ALTER TABLE internal_users DROP COLUMN IF EXISTS email_verified;")
    op.execute("ALTER TABLE internal_users DROP COLUMN IF EXISTS email_verified_at;")
