#!/usr/bin/env python3
"""Apply the PostgreSQL metrics service migration.

This helper materialises the tables, hypertables, indexes, and aggregates
introduced in ``schema/migrations/012_create_metrics_service.sql`` so that the
MetricsService can run against TimescaleDB.  It mirrors the telemetry runner to
keep ``behavior_align_storage_layers`` compliant while accelerating KPI
reporting for ``behavior_instrument_metrics_pipeline``.

Usage::

    ./scripts/run_postgres_metrics_migration.py --dsn postgresql://user:pass@localhost/db

When the ``--dsn`` flag is omitted, the script falls back to the
``AMPREALIZE_METRICS_PG_DSN`` environment variable.  Pass ``--dry-run`` to see
which statements would run without executing them.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MIGRATION = REPO_ROOT / "schema" / "migrations" / "012_create_metrics_service.sql"

from _postgres_migration_utils import (
    discover_dsn,
    execute_statements,
    load_migration,
    split_sql_statements,
)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply PostgreSQL metrics service migration")
    parser.add_argument("--dsn", help="PostgreSQL DSN (overrides AMPREALIZE_METRICS_PG_DSN)")
    parser.add_argument(
        "--migration",
        type=Path,
        default=DEFAULT_MIGRATION,
        help=f"Path to migration SQL file (default: {DEFAULT_MIGRATION.relative_to(REPO_ROOT)})",
    )
    parser.add_argument("--connect-timeout", type=int, default=10, help="Connection timeout in seconds")
    parser.add_argument("--dry-run", action="store_true", help="Print statements without executing them")

    args = parser.parse_args(argv)

    dsn = discover_dsn(args.dsn, "AMPREALIZE_METRICS_PG_DSN")
    migration_sql = load_migration(args.migration)
    statements = split_sql_statements(migration_sql)

    if not statements:
        print("⚠️ No statements found in migration; nothing to do.")
        return 0

    if args.dry_run:
        print("-- Dry run --")
        for index, statement in enumerate(statements, start=1):
            print(f"[{index}] {statement.strip()}\n")
        return 0

    print(f"Applying metrics migration using DSN: {dsn}")
    print(f"Executing {len(statements)} statements from {args.migration}")

    execute_statements(dsn, statements, connect_timeout=args.connect_timeout)

    print("✅ Migration applied successfully.")
    print(
        "📌 Remember to run 'amprealize record-action' so this infrastructure change is captured in the audit log "
        "per behavior_replayable_actions."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
