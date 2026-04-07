"""Add index on (project_id, display_number) for display-ID resolution.

Revision ID: 20260218_project_display_idx
Revises: 20260218_unify_projects
Create Date: 2026-02-18

The resolve_work_item_id() service method looks up work items by
project_id + display_number when resolving display IDs like
'myproject-42'. An index makes this O(log n) instead of a seq scan.

Following behavior_migrate_postgres_schema (Student).
"""

from alembic import op

revision = "20260218_project_display_idx"
down_revision = "20260218_unify_projects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_work_items_project_display_number",
        "work_items",
        ["project_id", "display_number"],
        schema="board",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_work_items_project_display_number",
        table_name="work_items",
        schema="board",
    )
