#!/usr/bin/env python3
"""Apply the PostgreSQL BehaviorService schema migration.

This script bootstraps the tables and indexes required by the BehaviorService
control plane.  It complements ``schema/migrations/002_create_behavior_service.sql``
and aligns with ``behavior_unify_execution_records`` by keeping the
procedural-memory store consistent across backends.

Usage::

    ./scripts/run_postgres_behavior_migration.py --dsn postgresql://user:pass@localhost/db

When ``--dsn`` is omitted, the script falls back to the
``AMPREALIZE_BEHAVIOR_PG_DSN`` environment variable.  Pass ``--dry-run`` to preview
statements without executing them.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from _postgres_migration_utils import (
    discover_dsn,
    execute_statements,
    load_migration,
    split_sql_statements,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MIGRATION = REPO_ROOT / "schema" / "migrations" / "002_create_behavior_service.sql"


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply PostgreSQL BehaviorService migration")
    parser.add_argument("--dsn", help="PostgreSQL DSN (overrides AMPREALIZE_BEHAVIOR_PG_DSN)")
    parser.add_argument(
        "--migration",
        type=Path,
        default=DEFAULT_MIGRATION,
        help=f"Path to migration SQL file (default: {DEFAULT_MIGRATION.relative_to(REPO_ROOT)})",
    )
    parser.add_argument("--connect-timeout", type=int, default=10, help="Connection timeout in seconds")
    parser.add_argument("--dry-run", action="store_true", help="Print statements without executing them")

    args = parser.parse_args(argv)

    dsn = discover_dsn(args.dsn, "AMPREALIZE_BEHAVIOR_PG_DSN")

    if not args.migration.exists():
        print(f"⚠️ Behavior migration file not found: {args.migration}")
        print(
            "ℹ️ Skipping standalone behavior SQL bootstrap. "
            "This is expected when schema is managed via consolidated Alembic migrations."
        )
        return 0

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

    print(f"Applying behavior migration using DSN: {dsn}")
    print(f"Executing {len(statements)} statements from {args.migration}")

    execute_statements(dsn, statements, connect_timeout=args.connect_timeout)

    print("✅ Migration applied successfully.")
    print(
        "📌 Remember to run 'amprealize record-action' to capture this deployment in the audit log "
        "per behavior_replayable_actions."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
