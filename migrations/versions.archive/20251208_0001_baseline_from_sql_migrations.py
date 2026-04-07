"""Baseline from legacy SQL migrations (001-025)

Revision ID: 0001_baseline
Revises: None
Create Date: 2025-12-08

Behavior: behavior_migrate_postgres_schema

This baseline migration executes the legacy SQL migrations (001-025) so Alembic
can build a fresh database end-to-end.

If you have an existing database that already has the schema from those SQL
migrations, do NOT run this migration. Instead, stamp it:
    alembic stamp 0001_baseline
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

from migrations.sql_utils import execute_sql_filenames


# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# List of SQL migrations covered by this baseline
SQL_MIGRATIONS = [
    "001_create_telemetry_warehouse.sql",
    "002_create_behavior_service.sql",
    "003_create_workflow_service.sql",
    "004_create_action_service.sql",
    "005_create_run_service.sql",
    "006_create_compliance_service.sql",
    "007_extend_replays_metadata.sql",
    "008_optimize_behavior_indexes.sql",
    "009_refactor_workflow_schema.sql",
    "010_create_behavior_embeddings.sql",
    "011_create_agent_orchestrator.sql",
    "012_create_metrics_service.sql",
    "013_create_trace_analysis.sql",
    "014_create_telemetry_warehouse_timescale.sql",
    "015_add_behavior_namespace.sql",
    "016_create_audit_log_worm.sql",
    "017_add_compliance_policies.sql",
    "018_create_behavior_effectiveness.sql",
    "019_audit_log_weekly_partitioning.sql",
    "020_create_reflection_service.sql",
    "021_create_collaboration_service.sql",
    "022_create_auth_service.sql",
    "023_create_organizations.sql",
    "024_add_org_id_to_behavior_tables.sql",
    "024_add_org_id_to_core_tables.sql",
    "025_optional_organizations.sql",
]


def upgrade() -> None:
    execute_sql_filenames(op, SQL_MIGRATIONS)


def downgrade() -> None:
    """Cannot downgrade baseline.

    To fully revert, you would need to drop all tables and re-apply
    the SQL migrations selectively.
    """
    raise NotImplementedError(
        "Cannot downgrade baseline migration. "
        "To reset, drop all tables and re-apply SQL migrations."
    )
