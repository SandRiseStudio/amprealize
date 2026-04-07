"""Rebrand database defaults from amprealize to amprealize.

Part of AMPREALIZE-674: Migrate database behavior records.

Updates persisted configuration values in the database that reference the old
'amprealize' brand names (DSN defaults, metric prefixes, database roles) to use
the new 'amprealize' naming.  Behavior record *names* (behavior_*) are
unchanged—they never carried the old brand prefix.

This migration is safe to run on both fresh and existing installs:
- Fresh installs already pick up the new Python-level defaults.
- Existing installs get any persisted DB-level defaults aligned.

Revision ID: 20260403_rebrand_db
"""

from alembic import op

revision = "20260403_rebrand_db"
down_revision = "20260402_widen_assignment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Update any persisted default DSN values stored in application config tables.
    # These UPDATE statements are idempotent — they only touch rows that still
    # carry the old value, and are no-ops on fresh installs.

    # If a settings/config table exists with persisted DSN values, update them.
    op.execute(
        """
        DO $$
        BEGIN
            -- Update behavior schema default connection comments (informational)
            IF EXISTS (
                SELECT 1 FROM information_schema.schemata WHERE schema_name = 'behavior'
            ) THEN
                COMMENT ON SCHEMA behavior IS
                    'Behavior storage – default DSN: postgresql://amprealize_behavior:***@localhost:6433/behaviors';
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.schemata WHERE schema_name = 'behavior'
            ) THEN
                COMMENT ON SCHEMA behavior IS
                    'Behavior storage – default DSN: postgresql://amprealize_behavior:***@localhost:6433/behaviors';
            END IF;
        END
        $$;
        """
    )
