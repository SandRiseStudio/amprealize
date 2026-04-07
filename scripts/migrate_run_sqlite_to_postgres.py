#!/usr/bin/env python3
"""Migrate RunService data from SQLite to PostgreSQL.

Usage:
    python scripts/migrate_run_sqlite_to_postgres.py [--source SOURCE_PATH]

Environment:
    AMPREALIZE_RUN_PG_DSN: Target PostgreSQL connection string
    AMPREALIZE_RUN_DB_PATH: Source SQLite database path (default: ~/.amprealize/data/runs.db)

This script migrates runs and run_steps from SQLite to PostgreSQL, preserving:
- Run state (status, progress, timestamps)
- Actor metadata
- Workflow/template linkage
- Behavior references
- Step tracking
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts._postgres_migration_utils import discover_dsn


def migrate_runs(dsn: str, runs: List[Dict[str, Any]]) -> int:
    """Insert runs into PostgreSQL."""

    try:
        import psycopg2  # type: ignore[import-not-found]
        from psycopg2.extras import Json
    except ImportError as exc:
        raise SystemExit(
            "❌ psycopg2 is not installed. Install with: pip install -e '.[postgres]'"
        ) from exc

    migrated = 0
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            for run in runs:
                try:
                    # Parse JSON fields
                    behavior_ids = json.loads(run.get("behavior_ids", "[]"))
                    outputs = json.loads(run.get("outputs", "{}"))
                    metadata = json.loads(run.get("metadata", "{}"))

                    cur.execute(
                        """
                        INSERT INTO runs (
                            run_id, created_at, updated_at, started_at, completed_at,
                            actor_id, actor_role, actor_surface,
                            status, workflow_id, workflow_name, template_id, template_name,
                            behavior_ids, current_step, progress_pct, message,
                            duration_ms, outputs, error, metadata
                        ) VALUES (
                            %s, %s, %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s, %s
                        )
                        ON CONFLICT (run_id) DO NOTHING;
                        """,
                        (
                            run.get("run_id") or str(uuid.uuid4()),
                            run["created_at"],
                            run["updated_at"],
                            run.get("started_at"),
                            run.get("completed_at"),
                            run["actor_id"],
                            run["actor_role"],
                            run["actor_surface"],
                            run["status"],
                            run.get("workflow_id"),
                            run.get("workflow_name"),
                            run.get("template_id"),
                            run.get("template_name"),
                            Json(behavior_ids),
                            run.get("current_step"),
                            run.get("progress_pct", 0.0),
                            run.get("message"),
                            run.get("duration_ms"),
                            Json(outputs),
                            run.get("error"),
                            Json(metadata),
                        ),
                    )
                    migrated += 1
                except Exception as e:
                    print(f"⚠️  Skipped run {run.get('run_id')}: {e}")
        conn.commit()

    return migrated


def migrate_run_steps(dsn: str, steps: List[Dict[str, Any]]) -> int:
    """Insert run steps into PostgreSQL."""

    try:
        import psycopg2  # type: ignore[import-not-found]
        from psycopg2.extras import Json
    except ImportError as exc:
        raise SystemExit(
            "❌ psycopg2 is not installed. Install with: pip install -e '.[postgres]'"
        ) from exc

    migrated = 0
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            for step in steps:
                try:
                    # Parse JSON fields
                    metadata = json.loads(step.get("metadata", "{}"))

                    cur.execute(
                        """
                        INSERT INTO run_steps (
                            step_id, run_id, name, status,
                            started_at, completed_at, progress_pct, metadata
                        ) VALUES (
                            %s, %s, %s, %s,
                            %s, %s, %s, %s
                        )
                        ON CONFLICT (run_id, step_id) DO NOTHING;
                        """,
                        (
                            step.get("step_id") or str(uuid.uuid4()),
                            step["run_id"],
                            step["name"],
                            step["status"],
                            step.get("started_at"),
                            step.get("completed_at"),
                            step.get("progress_pct", 0.0),
                            Json(metadata),
                        ),
                    )
                    migrated += 1
                except Exception as e:
                    print(f"⚠️  Skipped step {step.get('step_id')}: {e}")
        conn.commit()

    return migrated


def load_sqlite_data(db_path: Path) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Load runs and run_steps from SQLite database."""

    if not db_path.exists():
        return [], []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Load runs
    cursor = conn.execute("SELECT * FROM runs ORDER BY created_at")
    runs = [dict(row) for row in cursor.fetchall()]

    # Load run_steps
    cursor = conn.execute("SELECT * FROM run_steps ORDER BY run_id")
    steps = [dict(row) for row in cursor.fetchall()]

    conn.close()

    return runs, steps


def main() -> int:
    """Execute data migration."""

    parser = argparse.ArgumentParser(
        description="Migrate RunService data from SQLite to PostgreSQL"
    )
    parser.add_argument(
        "--source",
        type=Path,
        help="Path to SQLite database (default: ~/.amprealize/data/runs.db or AMPREALIZE_RUN_DB_PATH env var)",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("RunService Data Migration")
    print("=" * 70)
    print()

    # Discover target DSN
    dsn = discover_dsn(cli_dsn=None, env_var="AMPREALIZE_RUN_PG_DSN")
    print(f"Target: {dsn.split('@')[1] if '@' in dsn else dsn}")
    print()

    # Determine source database
    if args.source:
        source_db = args.source
    else:
        import os
        source_db = Path(os.getenv("AMPREALIZE_RUN_DB_PATH", Path.home() / ".amprealize" / "data" / "runs.db"))

    print(f"Source: {source_db}")

    if not source_db.exists():
        print(f"ℹ️  Source database not found. Validating target schema only.")
        runs = []
        steps = []
    else:
        print(f"Loading data from SQLite...")
        runs, steps = load_sqlite_data(source_db)
        print(f"  Found {len(runs)} runs and {len(steps)} steps")
    print()

    # Verify target schema
    print("Validating target schema...")
    try:
        import psycopg2  # type: ignore[import-not-found]
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM information_schema.tables WHERE table_name IN ('runs', 'run_steps');"
                )
                row = cur.fetchone()
                table_count = row[0] if row else 0  # type: ignore[index]
                if table_count != 2:
                    print("❌ Missing tables. Run: python scripts/run_postgres_run_migration.py")
                    return 1
                print("✅ Schema validated")
    except Exception as e:
        print(f"❌ Schema validation failed: {e}")
        return 1
    print()

    # Migrate runs
    if runs:
        print(f"Migrating {len(runs)} runs...")
        migrated_runs = migrate_runs(dsn, runs)
        print(f"✅ Migrated {migrated_runs} runs")
    else:
        print("ℹ️  No runs to migrate")
    print()

    # Migrate run_steps
    if steps:
        print(f"Migrating {len(steps)} run steps...")
        migrated_steps = migrate_run_steps(dsn, steps)
        print(f"✅ Migrated {migrated_steps} steps")
    else:
        print("ℹ️  No steps to migrate")
    print()

    print("=" * 70)
    print("Migration Complete! ✅")
    print("=" * 70)
    print()
    print("Next steps:")
    print("  1. Run parity tests: pytest tests/test_run_parity.py -v")
    print("  2. Update RunService to use PostgreSQL backend")
    print("  3. Verify SSE streaming works with PostgreSQL")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
