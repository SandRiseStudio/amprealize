"""merge_github_app_with_byok

Revision ID: ad1244ed2cf6
Revises: move_byok_to_credentials, add_github_app_installations
Create Date: 2026-01-15 04:31:39.181681+00:00

Behavior: behavior_migrate_postgres_schema
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ad1244ed2cf6'
down_revision: Union[str, None] = ('move_byok_to_credentials', 'add_github_app_installations')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply migration."""
    pass


def downgrade() -> None:
    """Revert migration."""
    pass
