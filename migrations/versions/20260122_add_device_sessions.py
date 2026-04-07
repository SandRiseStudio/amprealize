"""Add device_sessions table for shared device flow state.

Revision ID: 20260122_device_sessions
Revises: 20260122_add_personal_projects
Create Date: 2026-01-22

This migration creates the auth.device_sessions table to enable
PostgreSQL-backed device flow authentication. This allows MCP server
and REST API to share device flow state, enabling true E2E auth:

1. User starts device flow via MCP (auth.deviceInit)
2. User approves via web console or REST API
3. MCP polls and receives tokens (auth.devicePoll)

Following behavior_migrate_postgres_schema (Student).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260122_device_sessions"
down_revision = "add_personal_projects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create device_sessions table in auth schema
    op.create_table(
        "device_sessions",
        sa.Column("device_code", sa.String(255), primary_key=True),
        sa.Column("user_code", sa.String(20), nullable=False, unique=True),
        sa.Column("client_id", sa.String(255), nullable=False),
        sa.Column("scopes", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("approver", sa.String(255), nullable=True),
        sa.Column("approver_surface", sa.String(50), nullable=True),
        sa.Column("denial_reason", sa.String(500), nullable=True),
        # Token fields (populated on approval)
        sa.Column("access_token", sa.String(255), nullable=True),
        sa.Column("refresh_token", sa.String(255), nullable=True),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refresh_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        # OAuth provider fields (for real OAuth flows)
        sa.Column("oauth_user_id", sa.String(255), nullable=True),
        sa.Column("oauth_username", sa.String(255), nullable=True),
        sa.Column("oauth_email", sa.String(255), nullable=True),
        sa.Column("oauth_display_name", sa.String(255), nullable=True),
        sa.Column("oauth_avatar_url", sa.String(1024), nullable=True),
        sa.Column("oauth_provider", sa.String(50), nullable=True),
        # Metadata
        sa.Column("surface", sa.String(50), nullable=False, server_default="mcp"),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
        sa.Column("poll_interval", sa.Integer, nullable=False, server_default="5"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        schema="auth",
    )

    # Index for user_code lookup (consent page)
    op.create_index(
        "ix_device_sessions_user_code",
        "device_sessions",
        ["user_code"],
        schema="auth",
    )

    # Index for access_token lookup (token validation)
    op.create_index(
        "ix_device_sessions_access_token",
        "device_sessions",
        ["access_token"],
        schema="auth",
        postgresql_where=sa.text("access_token IS NOT NULL"),
    )

    # Index for cleanup of expired sessions
    op.create_index(
        "ix_device_sessions_expires_at",
        "device_sessions",
        ["expires_at"],
        schema="auth",
    )

    # Index for pending sessions by client_id
    op.create_index(
        "ix_device_sessions_client_pending",
        "device_sessions",
        ["client_id", "status"],
        schema="auth",
        postgresql_where=sa.text("status = 'PENDING'"),
    )


def downgrade() -> None:
    op.drop_index("ix_device_sessions_client_pending", table_name="device_sessions", schema="auth")
    op.drop_index("ix_device_sessions_expires_at", table_name="device_sessions", schema="auth")
    op.drop_index("ix_device_sessions_access_token", table_name="device_sessions", schema="auth")
    op.drop_index("ix_device_sessions_user_code", table_name="device_sessions", schema="auth")
    op.drop_table("device_sessions", schema="auth")
