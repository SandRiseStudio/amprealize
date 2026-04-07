#!/usr/bin/env python3
"""Apply ActionService PostgreSQL schema migration.

Usage:
    python scripts/run_postgres_action_migration.py

Environment:
    AMPREALIZE_ACTION_PG_DSN: PostgreSQL connection string for ActionService
        (default: postgresql://amprealize_user:local_dev_pw@localhost:5435/amprealize_action)

This script:
1. Discovers the ActionService PostgreSQL DSN from environment or defaults
2. Applies schema/migrations/004_create_action_service.sql
3. Verifies table creation and index existence
4. Prints summary and next steps

Follows the pattern established by run_postgres_behavior_migration.py and
run_postgres_workflow_migration.py for consistency.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts._postgres_migration_utils import (
    discover_dsn,
    execute_statements,
    load_migration,
    split_sql_statements,
)


def main() -> int:
    """Execute ActionService schema migration."""

    print("=" * 70)
    print("ActionService PostgreSQL Migration")
    print("=" * 70)
    print()

    # Step 1: Discover DSN
    dsn = discover_dsn(
        cli_dsn=None,
        env_var="AMPREALIZE_ACTION_PG_DSN",
    )
    print(f"Using DSN: {dsn.split('@')[1] if '@' in dsn else dsn}")  # Hide password
    print()

    # Step 2: Test connection
    print("Testing database connection...")
    try:
        import psycopg2  # type: ignore[import-not-found]
        with psycopg2.connect(dsn, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version();")
                row = cur.fetchone()
                version = row[0] if row else "unknown"
                print(f"✅ Connected: {version.split(',')[0]}")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        print("   Ensure postgres-action container is running:")
        print("   docker-compose -f docker-compose.postgres.yml up -d postgres-action")
        return 1
    print()

    # Step 3: Load and apply base schema
    migration_file = Path(__file__).parent.parent / "schema" / "migrations" / "004_create_action_service.sql"
    print(f"Applying schema from: {migration_file}")

    try:
        sql = load_migration(migration_file)
        statements = split_sql_statements(sql)
        print(f"  Executing {len(statements)} SQL statements...")
        execute_statements(dsn, statements, connect_timeout=5)
        print("✅ Base schema applied successfully")
    except Exception as e:
        print(f"❌ Schema application failed: {e}")
        return 1
    print()

    # Step 3b: Apply replays metadata extension migration
    migration_007_file = Path(__file__).parent.parent / "schema" / "migrations" / "007_extend_replays_metadata.sql"
    print(f"Applying replays extension from: {migration_007_file}")

    try:
        sql = load_migration(migration_007_file)
        statements = split_sql_statements(sql)
        print(f"  Executing {len(statements)} SQL statements...")
        execute_statements(dsn, statements, connect_timeout=5)
        print("✅ Replays metadata extension applied successfully")
    except Exception as e:
        print(f"❌ Replays extension failed: {e}")
        return 1
    print()

    # Step 4: Verify tables and indexes
    print("Verifying schema objects...")
    import psycopg2  # type: ignore[import-not-found]

    try:
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                # Check actions table
                cur.execute("""
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_name = 'actions'
                    ORDER BY ordinal_position;
                """)
                actions_columns = cur.fetchall()
                print(f"  actions table: {len(actions_columns)} columns")

                # Check replays table
                cur.execute("""
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_name = 'replays'
                    ORDER BY ordinal_position;
                """)
                replays_columns = cur.fetchall()
                print(f"  replays table: {len(replays_columns)} columns")

                # Check indexes
                cur.execute("""
                    SELECT indexname
                    FROM pg_indexes
                    WHERE tablename IN ('actions', 'replays')
                    ORDER BY indexname;
                """)
                indexes = cur.fetchall()
                print(f"  indexes: {len(indexes)} created")
                for idx in indexes:
                    print(f"    - {idx[0]}")

                # Check triggers
                cur.execute("""
                    SELECT trigger_name, event_manipulation, event_object_table
                    FROM information_schema.triggers
                    WHERE event_object_table IN ('actions', 'replays')
                    ORDER BY event_object_table, trigger_name;
                """)
                triggers = cur.fetchall()
                print(f"  triggers: {len(triggers)} created")
                for trig in triggers:
                    print(f"    - {trig[0]} on {trig[2]} ({trig[1]})")

    except psycopg2.Error as e:
        print(f"❌ Verification failed: {e}")
        return 1

    print()
    print("=" * 70)
    print("Migration Complete! ✅")
    print("=" * 70)
    print()
    print("Next steps:")
    print("  1. Run parity tests: pytest tests/test_action_parity.py -v")
    print("  2. Update ActionService to use PostgreSQL backend")
    print("  3. Wire AMPREALIZE_ACTION_PG_DSN in application initialization")
    print("  4. Update docker-compose.postgres.yml with postgres-action service")
    print()
    print("To rollback (development only):")
    print("  DROP TABLE IF EXISTS actions CASCADE;")
    print("  DROP TABLE IF EXISTS replays CASCADE;")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
