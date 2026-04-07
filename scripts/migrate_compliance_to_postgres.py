#!/usr/bin/env python3
"""Migrate ComplianceService data from in-memory to PostgreSQL.

Since ComplianceService is currently in-memory only, this script is a no-op
but follows the migration pattern for consistency. In production, this would
migrate from any persistent backing store (SQLite, JSON files, etc.) if they exist.

Usage:
    AMPREALIZE_COMPLIANCE_PG_DSN="postgresql://..." python scripts/migrate_compliance_to_postgres.py
"""

import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("❌ psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

from scripts._postgres_migration_utils import discover_dsn


def main() -> None:
    print("=" * 70)
    print("ComplianceService Data Migration")
    print("=" * 70)
    print()

    # Discover DSN
    dsn = discover_dsn("AMPREALIZE_COMPLIANCE_PG_DSN")
    if not dsn:
        print("❌ AMPREALIZE_COMPLIANCE_PG_DSN environment variable not set")
        sys.exit(1)

    display_dsn = dsn.split("@")[-1] if "@" in dsn else dsn
    print(f"Target: {display_dsn}")
    print()

    # Check for any persistent data sources
    print("Source: In-memory only (no persistent backing store)")
    print()

    print("ℹ️  ComplianceService is currently in-memory only.")
    print("   No data to migrate. PostgreSQL backend is ready for new checklists.")
    print()

    # Verify schema exists
    print("Validating target schema...")
    try:
        conn = psycopg2.connect(dsn)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name IN ('checklists', 'checklist_steps');
            """)
            table_count = cur.fetchone()[0]
            if table_count != 2:
                print(f"❌ Expected 2 tables, found {table_count}")
                print("   Run: python scripts/run_postgres_compliance_migration.py")
                sys.exit(1)
        conn.close()
        print("✅ Schema validated")
    except Exception as e:
        print(f"❌ Schema validation failed: {e}")
        sys.exit(1)

    print()
    print("=" * 70)
    print("Migration Complete! ✅")
    print("=" * 70)
    print("Next steps:")
    print("  1. Run parity tests: pytest tests/test_compliance_parity.py -v")
    print("  2. Update ComplianceService to use PostgreSQL backend")
    print("  3. Verify compliance checklist operations via API/CLI/MCP")


if __name__ == "__main__":
    main()
