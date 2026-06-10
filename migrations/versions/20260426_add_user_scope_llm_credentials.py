"""Add user scope support for LLM BYOK credentials.

Revision ID: 20260426_llm_cred_user_scope
Revises: 20260424_conv_scopes
Create Date: 2026-04-26

Following behavior_migrate_postgres_schema (Student).
"""

from __future__ import annotations

from alembic import op


revision = "20260426_llm_cred_user_scope"
down_revision = "20260424_conv_scopes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE credentials.llm_credentials
        DROP CONSTRAINT IF EXISTS llm_credentials_scope_type_check
        """
    )
    op.execute(
        """
        ALTER TABLE credentials.llm_credentials
        ADD CONSTRAINT llm_credentials_scope_type_check
        CHECK (scope_type IN ('user', 'project', 'org'))
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN credentials.llm_credentials.scope_type
        IS 'Credential scope: user, project, or org'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN credentials.llm_credentials.scope_id
        IS 'user_id, project_id, or org_id depending on scope_type'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE credentials.llm_credentials
        DROP CONSTRAINT IF EXISTS llm_credentials_scope_type_check
        """
    )
    op.execute(
        """
        DELETE FROM credentials.llm_credentials
        WHERE scope_type = 'user'
        """
    )
    op.execute(
        """
        ALTER TABLE credentials.llm_credentials
        ADD CONSTRAINT llm_credentials_scope_type_check
        CHECK (scope_type IN ('project', 'org'))
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN credentials.llm_credentials.scope_type
        IS 'Credential scope: project or org'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN credentials.llm_credentials.scope_id
        IS 'project_id or org_id depending on scope_type'
        """
    )
