#!/usr/bin/env python3
"""
Migrate telemetry fact tables from DuckDB to PostgreSQL/TimescaleDB.

This script exports data from data/telemetry.duckdb and imports it into
the postgres-telemetry container with timestamp preservation and validation.

Usage:
    python scripts/migrate_telemetry_duckdb_to_postgres.py [--dry-run] [--batch-size 1000]

Environment:
    AMPREALIZE_TELEMETRY_PG_DSN - PostgreSQL connection string
    Default: postgresql://amprealize_telemetry:dev_telemetry_pass@localhost:5432/telemetry
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

try:
    import duckdb
except ImportError:
    print("Error: duckdb not installed. Run: pip install duckdb", file=sys.stderr)
    sys.exit(1)

try:
    import psycopg2
    from psycopg2.extras import execute_batch, Json
except ImportError:
    print("Error: psycopg2 not installed. Run: pip install psycopg2-binary", file=sys.stderr)
    sys.exit(1)


def parse_behavior_ids(behavior_ids_str: str) -> List[str]:
    """Parse behavior_ids string from various DuckDB formats to list.

    Handles formats like:
    - '[behavior_instrument_metrics_pipeline]'
    - '["behavior_one", "behavior_two"]'
    - 'set()'
    - Empty/None
    """
    if not behavior_ids_str or not behavior_ids_str.strip():
        return []

    behavior_ids_str = behavior_ids_str.strip()

    # Handle empty set
    if behavior_ids_str == 'set()':
        return []

    # Try JSON parsing first (handles quoted strings)
    try:
        return json.loads(behavior_ids_str)
    except json.JSONDecodeError:
        pass

    # Try ast.literal_eval (handles Python syntax)
    try:
        import ast
        return ast.literal_eval(behavior_ids_str)
    except (ValueError, SyntaxError):
        pass

    # Last resort: regex extract identifiers from [behavior_one, behavior_two]
    if behavior_ids_str.startswith('[') and behavior_ids_str.endswith(']'):
        inner = behavior_ids_str[1:-1]
        # Split by comma and strip whitespace
        items = [item.strip() for item in inner.split(',') if item.strip()]
        return items

    # Give up
    return []


def migrate_fact_behavior_usage(
    duck_conn: duckdb.DuckDBPyConnection,
    pg_conn: Any,
    batch_size: int,
    dry_run: bool,
) -> int:
    """Migrate fact_behavior_usage table."""
    print("\n=== Migrating fact_behavior_usage ===")

    # Export from DuckDB
    cursor = duck_conn.execute("SELECT * FROM fact_behavior_usage ORDER BY first_plan_timestamp")
    rows = cursor.fetchall()
    print(f"  DuckDB rows: {len(rows)}")

    if dry_run:
        if rows:
            print(f"  Sample row: {rows[0]}")
        return len(rows)

    if not rows:
        print("  No data to migrate")
        return 0

    # Prepare PostgreSQL insert
    pg_cursor = pg_conn.cursor()

    insert_sql = """
        INSERT INTO fact_behavior_usage (
            run_id, template_id, template_name, behavior_ids, behavior_count,
            has_behaviors, baseline_tokens, actor_surface, actor_role, first_plan_timestamp
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (run_id) DO UPDATE
        SET template_id = COALESCE(EXCLUDED.template_id, fact_behavior_usage.template_id),
            template_name = COALESCE(EXCLUDED.template_name, fact_behavior_usage.template_name),
            behavior_ids = EXCLUDED.behavior_ids,
            behavior_count = EXCLUDED.behavior_count,
            has_behaviors = EXCLUDED.has_behaviors,
            baseline_tokens = COALESCE(EXCLUDED.baseline_tokens, fact_behavior_usage.baseline_tokens),
            actor_surface = COALESCE(EXCLUDED.actor_surface, fact_behavior_usage.actor_surface),
            actor_role = COALESCE(EXCLUDED.actor_role, fact_behavior_usage.actor_role),
            first_plan_timestamp = COALESCE(fact_behavior_usage.first_plan_timestamp, EXCLUDED.first_plan_timestamp)
    """

    # Convert rows to tuples, parsing behavior_ids string to list
    data = []
    for row in rows:
        run_id, template_id, template_name, behavior_ids_str, behavior_count, has_behaviors, baseline_tokens, actor_surface, actor_role, first_plan_timestamp = row

        # Parse behavior_ids from string representation to list
        behavior_ids = parse_behavior_ids(behavior_ids_str)

        data.append((
            run_id, template_id, template_name, Json(behavior_ids), behavior_count,
            has_behaviors, baseline_tokens, actor_surface, actor_role, first_plan_timestamp
        ))

    execute_batch(pg_cursor, insert_sql, data, page_size=batch_size)
    pg_conn.commit()

    print(f"  ✅ Migrated {len(data)} rows")
    return len(data)


def migrate_fact_compliance_steps(
    duck_conn: duckdb.DuckDBPyConnection,
    pg_conn: Any,
    batch_size: int,
    dry_run: bool,
) -> int:
    """Migrate fact_compliance_steps table."""
    print("\n=== Migrating fact_compliance_steps ===")

    # Export from DuckDB
    cursor = duck_conn.execute("SELECT * FROM fact_compliance_steps ORDER BY timestamp")
    rows = cursor.fetchall()
    print(f"  DuckDB rows: {len(rows)}")

    if dry_run:
        if rows:
            print(f"  Sample row: {rows[0]}")
        return len(rows)

    if not rows:
        print("  No data to migrate")
        return 0

    # Prepare PostgreSQL insert
    pg_cursor = pg_conn.cursor()

    # Note: PostgreSQL has 'id' auto-increment column, we'll insert without it
    insert_sql = """
        INSERT INTO fact_compliance_steps (
            checklist_id, step_id, status, coverage_score, run_id, session_id, behavior_ids, event_timestamp
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT DO NOTHING
    """

    # Convert rows to tuples
    data = []
    for row in rows:
        checklist_id, step_id, status, coverage_score, run_id, session_id, behavior_ids_str, timestamp = row

        # Parse behavior_ids from string representation
        behavior_ids = parse_behavior_ids(behavior_ids_str)

        data.append((
            checklist_id, step_id, status, coverage_score, run_id, session_id, Json(behavior_ids), timestamp
        ))

    execute_batch(pg_cursor, insert_sql, data, page_size=batch_size)
    pg_conn.commit()

    print(f"  ✅ Migrated {len(data)} rows")
    return len(data)


def migrate_fact_execution_status(
    duck_conn: duckdb.DuckDBPyConnection,
    pg_conn: Any,
    batch_size: int,
    dry_run: bool,
) -> int:
    """Migrate fact_execution_status table."""
    print("\n=== Migrating fact_execution_status ===")

    # Export from DuckDB
    cursor = duck_conn.execute("SELECT * FROM fact_execution_status")
    rows = cursor.fetchall()
    print(f"  DuckDB rows: {len(rows)}")

    if dry_run:
        if rows:
            print(f"  Sample row: {rows[0]}")
        return len(rows)

    if not rows:
        print("  No data to migrate")
        return 0

    # Prepare PostgreSQL insert
    pg_cursor = pg_conn.cursor()

    # Note: PostgreSQL has 'updated_at' column with default NOW()
    insert_sql = """
        INSERT INTO fact_execution_status (
            run_id, template_id, status, actor_surface, actor_role
        ) VALUES (
            %s, %s, %s, %s, %s
        )
        ON CONFLICT (run_id) DO UPDATE
        SET template_id = EXCLUDED.template_id,
            status = EXCLUDED.status,
            actor_surface = EXCLUDED.actor_surface,
            actor_role = EXCLUDED.actor_role,
            updated_at = NOW()
    """

    # Convert rows to tuples (DuckDB doesn't have updated_at)
    data = [(row[0], row[1], row[2], row[3], row[4]) for row in rows]

    execute_batch(pg_cursor, insert_sql, data, page_size=batch_size)
    pg_conn.commit()

    print(f"  ✅ Migrated {len(data)} rows")
    return len(data)


def migrate_fact_token_savings(
    duck_conn: duckdb.DuckDBPyConnection,
    pg_conn: Any,
    batch_size: int,
    dry_run: bool,
) -> int:
    """Migrate fact_token_savings table."""
    print("\n=== Migrating fact_token_savings ===")

    # Export from DuckDB
    cursor = duck_conn.execute("SELECT * FROM fact_token_savings")
    rows = cursor.fetchall()
    print(f"  DuckDB rows: {len(rows)}")

    if dry_run:
        if rows:
            print(f"  Sample row: {rows[0]}")
        return len(rows)

    if not rows:
        print("  No data to migrate")
        return 0

    # Prepare PostgreSQL insert
    pg_cursor = pg_conn.cursor()

    insert_sql = """
        INSERT INTO fact_token_savings (
            run_id, template_id, output_tokens, baseline_tokens, token_savings_pct
        ) VALUES (
            %s, %s, %s, %s, %s
        )
        ON CONFLICT (run_id) DO UPDATE
        SET template_id = EXCLUDED.template_id,
            output_tokens = EXCLUDED.output_tokens,
            baseline_tokens = EXCLUDED.baseline_tokens,
            token_savings_pct = EXCLUDED.token_savings_pct
    """

    data = [(row[0], row[1], row[2], row[3], row[4]) for row in rows]

    execute_batch(pg_cursor, insert_sql, data, page_size=batch_size)
    pg_conn.commit()

    print(f"  ✅ Migrated {len(data)} rows")
    return len(data)


def validate_migration(duck_conn: duckdb.DuckDBPyConnection, pg_conn: Any) -> bool:
    """Validate row counts match between DuckDB and PostgreSQL."""
    print("\n=== Validation ===")

    tables = ['fact_behavior_usage', 'fact_compliance_steps', 'fact_execution_status', 'fact_token_savings']
    all_match = True

    pg_cursor = pg_conn.cursor()

    for table in tables:
        duck_count = duck_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        pg_cursor.execute(f"SELECT COUNT(*) FROM {table}")
        pg_count = pg_cursor.fetchone()[0]

        match = "✅" if duck_count == pg_count else "❌"
        print(f"  {table}: DuckDB={duck_count}, PostgreSQL={pg_count} {match}")

        if duck_count != pg_count:
            all_match = False

    return all_match


def main():
    parser = argparse.ArgumentParser(description="Migrate DuckDB telemetry data to PostgreSQL")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be migrated without writing")
    parser.add_argument("--batch-size", type=int, default=1000, help="Batch size for inserts")
    parser.add_argument("--duckdb-path", default="data/telemetry.duckdb", help="Path to DuckDB file")
    args = parser.parse_args()

    # Check DuckDB file exists
    duckdb_path = Path(args.duckdb_path)
    if not duckdb_path.exists():
        print(f"Error: DuckDB file not found: {duckdb_path}", file=sys.stderr)
        sys.exit(1)

    # Get PostgreSQL DSN
    pg_dsn = os.getenv(
        "AMPREALIZE_TELEMETRY_PG_DSN",
        "postgresql://amprealize_telemetry:dev_telemetry_pass@localhost:5432/telemetry"
    )

    print(f"DuckDB source: {duckdb_path}")
    print(f"PostgreSQL target: {pg_dsn.split('@')[1] if '@' in pg_dsn else pg_dsn}")
    print(f"Dry run: {args.dry_run}")
    print(f"Batch size: {args.batch_size}")

    # Connect to both databases
    print("\nConnecting to databases...")
    try:
        duck_conn = duckdb.connect(str(duckdb_path), read_only=True)
        print("  ✅ DuckDB connected")
    except Exception as e:
        print(f"  ❌ DuckDB connection failed: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        pg_conn = psycopg2.connect(pg_dsn)
        print("  ✅ PostgreSQL connected")
    except Exception as e:
        print(f"  ❌ PostgreSQL connection failed: {e}", file=sys.stderr)
        sys.exit(1)

    # Migrate each table
    try:
        total_rows = 0
        total_rows += migrate_fact_behavior_usage(duck_conn, pg_conn, args.batch_size, args.dry_run)
        total_rows += migrate_fact_compliance_steps(duck_conn, pg_conn, args.batch_size, args.dry_run)
        total_rows += migrate_fact_execution_status(duck_conn, pg_conn, args.batch_size, args.dry_run)
        total_rows += migrate_fact_token_savings(duck_conn, pg_conn, args.batch_size, args.dry_run)

        if not args.dry_run:
            # Validate
            if validate_migration(duck_conn, pg_conn):
                print(f"\n✅ Migration complete! {total_rows} total rows migrated.")
            else:
                print(f"\n⚠️  Migration complete with validation warnings. Check counts above.")
                sys.exit(1)
        else:
            print(f"\n✅ Dry run complete. Would migrate {total_rows} total rows.")

    except Exception as e:
        print(f"\n❌ Migration failed: {e}", file=sys.stderr)
        if not args.dry_run:
            pg_conn.rollback()
        raise
    finally:
        duck_conn.close()
        pg_conn.close()


if __name__ == "__main__":
    main()
