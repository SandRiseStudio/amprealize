#!/usr/bin/env python3
"""Apply Auth PostgreSQL schema migration.

Usage:
    python scripts/run_postgres_auth_migration.py

Environment:
    AMPREALIZE_AUTH_PG_DSN: PostgreSQL connection string for Auth
        (default: postgresql://amprealize_auth:dev_auth_pass@localhost:5440/amprealize_auth)

This script:
1. Discovers the Auth PostgreSQL DSN from environment or defaults
2. Applies schema/migrations/022_create_auth_service.sql
3. Verifies table creation and index existence
4. Prints summary and next steps

Follows the pattern established by run_postgres_action_migration.py.
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
    """Execute Auth schema migration."""

    print("=" * 70)
    print("Auth PostgreSQL Migration")
    print("=" * 70)
    print()

    # Step 1: Discover DSN
    dsn = discover_dsn(
        cli_dsn=None,
        env_var="AMPREALIZE_AUTH_PG_DSN",
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
        print("   Ensure auth-db container is running.")
        return 1
    print()

    # Step 3: Load and apply base schema
    migration_file = Path(__file__).parent.parent / "schema" / "migrations" / "022_create_auth_service.sql"
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

    # Step 4: Verify tables and indexes
    print("Verifying schema objects...")
    import psycopg2  # type: ignore[import-not-found]

    try:
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                # Check internal_users table
                cur.execute("""
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_name = 'internal_users'
                    ORDER BY ordinal_position;
                """)
                users_columns = cur.fetchall()
                print(f"  internal_users table: {len(users_columns)} columns")

                # Check password_reset_tokens table
                cur.execute("""
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_name = 'password_reset_tokens'
                    ORDER BY ordinal_position;
                """)
                tokens_columns = cur.fetchall()
                print(f"  password_reset_tokens table: {len(tokens_columns)} columns")

                # Check internal_sessions table
                cur.execute("""
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_name = 'internal_sessions'
                    ORDER BY ordinal_position;
                """)
                sessions_columns = cur.fetchall()
                print(f"  internal_sessions table: {len(sessions_columns)} columns")

                # Check indexes
                cur.execute("""
                    SELECT indexname
                    FROM pg_indexes
                    WHERE tablename IN ('internal_users', 'password_reset_tokens', 'internal_sessions')
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
                    WHERE event_object_table IN ('internal_users', 'password_reset_tokens', 'internal_sessions')
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
    print("  1. Run auth tests: pytest tests/unit/test_internal_auth.py -v")
    print("  2. Set AMPREALIZE_AUTH_PG_DSN environment variable")
    print()
    print("To rollback (development only):")
    print("  DROP TABLE IF EXISTS internal_sessions CASCADE;")
    print("  DROP TABLE IF EXISTS password_reset_tokens CASCADE;")
    print("  DROP TABLE IF EXISTS internal_users CASCADE;")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
