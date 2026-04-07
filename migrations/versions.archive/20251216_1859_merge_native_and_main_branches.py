"""merge_native_and_main_branches

Revision ID: ff0b0a812e10
Revises: 0008_local_project_path, native_0007_labels
Create Date: 2025-12-16 18:59:10.391641+00:00

Behavior: behavior_migrate_postgres_schema
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ff0b0a812e10'
down_revision: Union[str, None] = ('0008_local_project_path', 'native_0007_labels')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply migration."""
    pass


def downgrade() -> None:
    """Revert migration."""
    pass
