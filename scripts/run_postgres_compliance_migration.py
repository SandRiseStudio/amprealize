#!/usr/bin/env python3
"""Run ComplianceService PostgreSQL schema migration.

Usage:
    AMPREALIZE_COMPLIANCE_PG_DSN="postgresql://..." python scripts/run_postgres_compliance_migration.py
    python scripts/run_postgres_compliance_migration.py --dry-run

Environment:
    AMPREALIZE_COMPLIANCE_PG_DSN: PostgreSQL connection string (required)
"""

import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import psycopg2
except ImportError:
    print("❌ psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

from scripts._postgres_migration_utils import (
    discover_dsn,
    execute_statements,
    load_migration,
    split_sql_statements,
)


def main() -> None:
    print("=" * 70)
    print("ComplianceService PostgreSQL Migration")
    print("=" * 70)
    print()

    # Discover DSN
    dsn = discover_dsn(None, "AMPREALIZE_COMPLIANCE_PG_DSN")
    if not dsn:
        print("❌ AMPREALIZE_COMPLIANCE_PG_DSN environment variable not set")
        print("   Example: postgresql://amprealize_user:password@localhost:5437/amprealize_compliance")
        sys.exit(1)

    # Mask password in output
    display_dsn = dsn.split("@")[-1] if "@" in dsn else dsn
    print(f"Using DSN: {display_dsn}")
    print()

    # Test connection
    print("Testing database connection...")
    try:
        conn = psycopg2.connect(dsn)
        with conn.cursor() as cur:
            cur.execute("SELECT version();")
            version = cur.fetchone()[0]
            print(f"✅ Connected: {version.split(',')[0]}")
        conn.close()
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        sys.exit(1)

    # Load migration
    migration_path = Path(__file__).parent.parent / "schema" / "migrations" / "006_create_compliance_service.sql"
    if not migration_path.exists():
        print(f"❌ Migration file not found: {migration_path}")
        sys.exit(1)

    print(f"Applying schema from: {migration_path}")
    migration_sql = load_migration(migration_path)
    statements = split_sql_statements(migration_sql)
    print(f"Executing {len(statements)} SQL statements...")

    # Execute migration
    try:
        execute_statements(dsn, statements, connect_timeout=5)
        print("✅ Schema applied successfully")
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        sys.exit(1)

    print()
    print("Verifying schema objects...")

    # Verify tables and columns
    conn = psycopg2.connect(dsn)
    with conn.cursor() as cur:
        # Check checklists table
        cur.execute("""
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_name = 'checklists';
        """)
        checklist_cols = cur.fetchone()[0]
        print(f"  checklists table: {checklist_cols} columns")

        # Check checklist_steps table
        cur.execute("""
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_name = 'checklist_steps';
        """)
        step_cols = cur.fetchone()[0]
        print(f"  checklist_steps table: {step_cols} columns")

        # Check indexes
        cur.execute("""
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename IN ('checklists', 'checklist_steps')
            ORDER BY indexname;
        """)
        indexes = cur.fetchall()
        print(f"  indexes: {len(indexes)} created")
        for (idx_name,) in indexes:
            print(f"    - {idx_name}")

        # Check triggers
        cur.execute("""
            SELECT trigger_name, event_manipulation, event_object_table
            FROM information_schema.triggers
            WHERE event_object_schema = 'public'
              AND event_object_table IN ('checklists', 'checklist_steps')
            ORDER BY trigger_name;
        """)
        triggers = cur.fetchall()
        print(f"  triggers: {len(triggers)} created")
        for trig_name, event, table in triggers:
            print(f"    - {trig_name} on {table} ({event})")

    conn.close()

    print()
    print("=" * 70)
    print("Migration Complete! ✅")
    print("=" * 70)
    print("Next steps:")
    print("  1. Run parity tests: pytest tests/test_compliance_parity.py -v")
    print("  2. Update ComplianceService to use PostgreSQL backend")
    print("  3. Wire AMPREALIZE_COMPLIANCE_PG_DSN in application initialization")
    print()
    print("To rollback (development only):")
    print("  DROP TABLE IF EXISTS checklist_steps CASCADE;")
    print("  DROP TABLE IF EXISTS checklists CASCADE;")


if __name__ == "__main__":
    main()
