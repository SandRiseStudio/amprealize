#!/usr/bin/env python3
"""Migrate ActionService data from in-memory/SQLite to PostgreSQL.

Usage:
    python scripts/migrate_action_sqlite_to_postgres.py [--source SOURCE_PATH]

Environment:
    AMPREALIZE_ACTION_PG_DSN: Target PostgreSQL connection string

This script handles migration from the in-memory ActionService to PostgreSQL.
Since ActionService currently stores data in memory (no persistent SQLite),
this script primarily serves as a template for future migration needs if
actions need to be imported from JSON exports or other sources.

For now, it validates the target PostgreSQL schema and can import from JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts._postgres_migration_utils import discover_dsn


def migrate_actions(dsn: str, actions: List[Dict[str, Any]]) -> int:
    """Insert actions into PostgreSQL."""

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
            for action in actions:
                try:
                    cur.execute(
                        """
                        INSERT INTO actions (
                            action_id, timestamp, actor_id, actor_role, actor_surface,
                            artifact_path, summary, behaviors_cited, metadata,
                            related_run_id, audit_log_event_id, checksum, replay_status
                        ) VALUES (
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s, %s
                        )
                        ON CONFLICT (action_id) DO NOTHING;
                        """,
                        (
                            action.get("action_id") or str(uuid.uuid4()),
                            action["timestamp"],
                            action["actor"]["id"],
                            action["actor"]["role"],
                            action["actor"]["surface"],
                            action["artifact_path"],
                            action["summary"],
                            Json(action.get("behaviors_cited", [])),
                            Json(action.get("metadata", {})),
                            action.get("related_run_id"),
                            action.get("audit_log_event_id"),
                            action.get("checksum", ""),
                            action.get("replay_status", "NOT_STARTED"),
                        ),
                    )
                    migrated += 1
                except Exception as e:
                    print(f"⚠️  Skipped action {action.get('action_id')}: {e}")
        conn.commit()

    return migrated


def migrate_replays(dsn: str, replays: List[Dict[str, Any]]) -> int:
    """Insert replay records into PostgreSQL."""

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
            for replay in replays:
                try:
                    cur.execute(
                        """
                        INSERT INTO replays (
                            replay_id, status, progress, logs, failed_action_ids
                        ) VALUES (
                            %s, %s, %s, %s, %s
                        )
                        ON CONFLICT (replay_id) DO NOTHING;
                        """,
                        (
                            replay.get("replay_id") or str(uuid.uuid4()),
                            replay["status"],
                            replay.get("progress", 0.0),
                            Json(replay.get("logs", [])),
                            Json(replay.get("failed_action_ids", [])),
                        ),
                    )
                    migrated += 1
                except Exception as e:
                    print(f"⚠️  Skipped replay {replay.get('replay_id')}: {e}")
        conn.commit()

    return migrated


def main() -> int:
    """Execute data migration."""

    parser = argparse.ArgumentParser(
        description="Migrate ActionService data to PostgreSQL"
    )
    parser.add_argument(
        "--source",
        type=Path,
        help="Path to JSON file containing actions and replays to import",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("ActionService Data Migration")
    print("=" * 70)
    print()

    # Discover target DSN
    dsn = discover_dsn(cli_dsn=None, env_var="AMPREALIZE_ACTION_PG_DSN")
    print(f"Target: {dsn.split('@')[1] if '@' in dsn else dsn}")
    print()

    # Load source data
    if args.source:
        if not args.source.exists():
            print(f"❌ Source file not found: {args.source}")
            return 1

        print(f"Loading data from: {args.source}")
        with open(args.source, "r", encoding="utf-8") as f:
            data = json.load(f)

        actions = data.get("actions", [])
        replays = data.get("replays", [])
        print(f"  Found {len(actions)} actions and {len(replays)} replays")
    else:
        print("ℹ️  No source file provided. Validating target schema only.")
        actions = []
        replays = []
    print()

    # Verify target schema
    print("Validating target schema...")
    try:
        import psycopg2  # type: ignore[import-not-found]
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM information_schema.tables WHERE table_name IN ('actions', 'replays');"
                )
                table_count = cur.fetchone()[0]  # type: ignore[index]
                if table_count != 2:
                    print("❌ Missing tables. Run: python scripts/run_postgres_action_migration.py")
                    return 1
                print("✅ Schema validated")
    except Exception as e:
        print(f"❌ Schema validation failed: {e}")
        return 1
    print()

    # Migrate actions
    if actions:
        print(f"Migrating {len(actions)} actions...")
        migrated_actions = migrate_actions(dsn, actions)
        print(f"✅ Migrated {migrated_actions} actions")
    else:
        print("ℹ️  No actions to migrate")
    print()

    # Migrate replays
    if replays:
        print(f"Migrating {len(replays)} replays...")
        migrated_replays = migrate_replays(dsn, replays)
        print(f"✅ Migrated {migrated_replays} replays")
    else:
        print("ℹ️  No replays to migrate")
    print()

    print("=" * 70)
    print("Migration Complete! ✅")
    print("=" * 70)
    print()
    print("Next steps:")
    print("  1. Run parity tests: pytest tests/test_action_parity.py -v")
    print("  2. Update ActionService to use PostgreSQL backend")
    print("  3. Verify telemetry events emit correctly")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
