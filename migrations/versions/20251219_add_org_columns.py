"""Add missing columns to organizations table.

Revision ID: add_org_columns
Revises: align_behavior_schema
Create Date: 2024-12-19

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "add_org_columns"
down_revision = "align_behavior_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add missing columns to organizations table.

    Note: These columns may already exist in the baseline migration.
    We check for existence before adding.
    """
    conn = op.get_bind()

    # Check if display_name column already exists
    result = conn.execute(sa.text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'auth' AND table_name = 'organizations' AND column_name = 'display_name'
    """))
    if result.fetchone() is None:
        op.add_column(
            "organizations",
            sa.Column("display_name", sa.String(255), nullable=True),
            schema="auth"
        )

    # Check if plan column already exists
    result = conn.execute(sa.text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'auth' AND table_name = 'organizations' AND column_name = 'plan'
    """))
    if result.fetchone() is None:
        op.add_column(
            "organizations",
            sa.Column("plan", sa.String(32), server_default="free", nullable=False),
            schema="auth"
        )

    # Check if status column already exists
    result = conn.execute(sa.text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'auth' AND table_name = 'organizations' AND column_name = 'status'
    """))
    if result.fetchone() is None:
        op.add_column(
            "organizations",
            sa.Column("status", sa.String(32), server_default="active", nullable=False),
            schema="auth"
        )

    # Check if stripe_customer_id column already exists
    result = conn.execute(sa.text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'auth' AND table_name = 'organizations' AND column_name = 'stripe_customer_id'
    """))
    if result.fetchone() is None:
        op.add_column(
            "organizations",
            sa.Column("stripe_customer_id", sa.String(255), nullable=True),
            schema="auth"
        )

    # Check if metadata column already exists
    result = conn.execute(sa.text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'auth' AND table_name = 'organizations' AND column_name = 'metadata'
    """))
    if result.fetchone() is None:
        op.add_column(
            "organizations",
            sa.Column("metadata", postgresql.JSONB(), server_default="{}", nullable=True),
            schema="auth"
        )


def downgrade() -> None:
    """Remove added columns from organizations table."""
    op.drop_column("organizations", "metadata", schema="auth")
    op.drop_column("organizations", "stripe_customer_id", schema="auth")
    op.drop_column("organizations", "status", schema="auth")
    op.drop_column("organizations", "plan", schema="auth")
    op.drop_column("organizations", "display_name", schema="auth")
