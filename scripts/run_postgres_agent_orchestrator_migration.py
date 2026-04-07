#!/usr/bin/env python3
"""Run AgentOrchestratorService PostgreSQL migration.

Applies schema migration 011 to create agent orchestrator tables.

Usage:
    AMPREALIZE_AGENT_ORCHESTRATOR_PG_DSN="postgresql://..." python scripts/run_postgres_agent_orchestrator_migration.py
"""

import os
import sys
from pathlib import Path

# Add amprealize to path
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
    """Execute migration 011."""
    print("=" * 80)
    print("AgentOrchestratorService PostgreSQL Migration")
    print("=" * 80)
    print()

    # Discover DSN
    dsn = discover_dsn(None, "AMPREALIZE_AGENT_ORCHESTRATOR_PG_DSN")
    if not dsn:
        print("❌ AMPREALIZE_AGENT_ORCHESTRATOR_PG_DSN environment variable not set")
        print("   Example: postgresql://amprealize_user:local_dev_pw@localhost:5438/amprealize_agent_orchestrator")
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
            version = cur.fetchone()[0]  # type: ignore[index]
            print(f"✅ Connected: {version.split(',')[0]}")
        conn.close()
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        sys.exit(1)

    # Load migration
    migration_path = Path(__file__).parent.parent / "schema" / "migrations" / "011_create_agent_orchestrator.sql"
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
        # Check agent_personas table
        cur.execute("""
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_name = 'agent_personas';
        """)
        personas_cols = cur.fetchone()[0]  # type: ignore[index]
        print(f"  agent_personas table: {personas_cols} columns")

        # Check agent_assignments table
        cur.execute("""
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_name = 'agent_assignments';
        """)
        assignments_cols = cur.fetchone()[0]  # type: ignore[index]
        print(f"  agent_assignments table: {assignments_cols} columns")

        # Check agent_switch_events table
        cur.execute("""
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_name = 'agent_switch_events';
        """)
        events_cols = cur.fetchone()[0]  # type: ignore[index]
        print(f"  agent_switch_events table: {events_cols} columns")

        # Check indexes
        cur.execute("""
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename IN ('agent_personas', 'agent_assignments', 'agent_switch_events')
            ORDER BY indexname;
        """)
        indexes = cur.fetchall()
        print(f"  indexes: {len(indexes)} created")
        for (idx_name,) in indexes:
            print(f"    - {idx_name}")

    conn.close()

    print()
    print("=" * 80)
    print("Migration Complete! ✅")
    print("=" * 80)
    print("Next steps:")
    print("  1. Seed default personas: scripts/seed_agent_personas.py")
    print("  2. Run parity tests: pytest tests/test_agent_orchestrator_parity.py -v")
    print("  3. Update CLI to use PostgresAgentOrchestratorService")
    print()
    print("To rollback (development only):")
    print("  DROP TABLE IF EXISTS agent_switch_events CASCADE;")
    print("  DROP TABLE IF EXISTS agent_assignments CASCADE;")
    print("  DROP TABLE IF EXISTS agent_personas CASCADE;")


if __name__ == "__main__":
    main()
