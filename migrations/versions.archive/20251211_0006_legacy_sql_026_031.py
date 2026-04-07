"""Port remaining legacy SQL migrations (026-029, 031*) into Alembic.

Revision ID: 0006_legacy_sql_026_031
Revises: 0005_add_board_columns_updated_at
Create Date: 2025-12-11

Behavior: behavior_migrate_postgres_schema

This revision executes the remaining legacy SQL migration files that have not
been ported to native SQLAlchemy/Alembic operations yet.

Notes:
- We intentionally skip `030_create_agile_board.sql` because it has already been
  ported to Alembic in prior revisions.
- There are two `031_*.sql` files in the legacy directory; we execute both.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

from migrations.sql_utils import execute_sql_filenames


# revision identifiers, used by Alembic.
revision: str = "0006_legacy_sql_026_031"
down_revision: Union[str, None] = "0005_board_columns_updated_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SQL_MIGRATIONS = [
    "026_user_management_invitations.sql",
    "027_create_billing_infrastructure.sql",
    "028_add_agent_idle_status.sql",
    "029_create_agent_registry.sql",
    "031_unified_work_items.sql",
    "031_agent_performance_metrics.sql",
]


def upgrade() -> None:
    execute_sql_filenames(op, SQL_MIGRATIONS)


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrade is not implemented for legacy SQL execution migrations. "
        "If you need to revert, restore from backup or recreate the database."
    )
