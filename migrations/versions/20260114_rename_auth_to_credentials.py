"""move_byok_to_credentials_schema

Revision ID: move_byok_to_credentials
Revises: add_github_credentials
Create Date: 2026-01-14

Behavior: behavior_migrate_postgres_schema

Moves BYOK credential tables from 'auth' schema to new 'credentials' schema.
The 'auth' schema remains for user authentication (users, sessions, etc.).
The 'credentials' schema is specifically for API keys and tokens (BYOK).

Tables moved:
- auth.llm_credentials -> credentials.llm_credentials
- auth.llm_credential_audit_log -> credentials.llm_credential_audit_log
- auth.github_credentials -> credentials.github_credentials
- auth.github_credential_audit_log -> credentials.github_credential_audit_log
"""
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "move_byok_to_credentials"
down_revision: str = "add_github_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Move BYOK credential tables to 'credentials' schema."""
    # Create the new credentials schema
    op.execute("CREATE SCHEMA IF NOT EXISTS credentials")

    # Move tables from auth to credentials schema
    op.execute("ALTER TABLE auth.llm_credentials SET SCHEMA credentials")
    op.execute("ALTER TABLE auth.llm_credential_audit_log SET SCHEMA credentials")
    op.execute("ALTER TABLE auth.github_credentials SET SCHEMA credentials")
    op.execute("ALTER TABLE auth.github_credential_audit_log SET SCHEMA credentials")


def downgrade() -> None:
    """Move BYOK credential tables back to 'auth' schema."""
    # Move tables back to auth schema
    op.execute("ALTER TABLE credentials.llm_credentials SET SCHEMA auth")
    op.execute("ALTER TABLE credentials.llm_credential_audit_log SET SCHEMA auth")
    op.execute("ALTER TABLE credentials.github_credentials SET SCHEMA auth")
    op.execute("ALTER TABLE credentials.github_credential_audit_log SET SCHEMA auth")

    # Drop credentials schema if empty
    op.execute("DROP SCHEMA IF EXISTS credentials")
