#!/usr/bin/env python3
"""
Export DuckDB Analytics Warehouse to SQLite for Metabase Compatibility

DuckDB files are not directly readable by SQLite drivers, so we export
the analytics data to a SQLite database that Metabase can query.

Usage:
    python scripts/export_duckdb_to_sqlite.py

Output:
    data/telemetry_sqlite.db - SQLite database with all analytics tables/views
"""

import duckdb
import sqlite3
from pathlib import Path


def export_duckdb_to_sqlite(
    duckdb_path: str = "data/telemetry.duckdb",
    sqlite_path: str = "data/telemetry_sqlite.db",
) -> None:
    """Export DuckDB warehouse to SQLite format."""

    duckdb_file = Path(duckdb_path)
    sqlite_file = Path(sqlite_path)

    # Connect to DuckDB (read-only)
    print(f"📖 Reading from DuckDB: {duckdb_file}")
    duck_conn = duckdb.connect(str(duckdb_file), read_only=True)

    # Connect to SQLite (create new)
    if sqlite_file.exists():
        print(f"🗑️  Removing existing SQLite database: {sqlite_file}")
        sqlite_file.unlink()

    print(f"📝 Creating SQLite database: {sqlite_file}")
    sqlite_conn = sqlite3.connect(str(sqlite_file))
    sqlite_cursor = sqlite_conn.cursor()

    # Get list of tables from DuckDB (prd_metrics schema - the source of truth)
    tables_query = """
        SELECT table_name, table_type
        FROM information_schema.tables
        WHERE table_schema = 'prd_metrics'
        ORDER BY table_type DESC, table_name;
    """
    tables = duck_conn.execute(tables_query).fetchall()

    print(f"\n📊 Found {len(tables)} tables/views in DuckDB:")
    for table_name, table_type in tables:
        print(f"  - {table_name} ({table_type})")

    # Export each table/view
    exported_count = 0
    for table_name, table_type in tables:
        try:
            print(f"\n🔄 Exporting {table_type.lower()}: {table_name}...")

            # Get DuckDB data from prd_metrics schema
            df = duck_conn.execute(f"SELECT * FROM prd_metrics.{table_name}").fetchdf()
            row_count = len(df)

            if row_count == 0:
                print(f"  ⚠️  {table_name} is empty, skipping")
                continue

            # Get DuckDB schema
            schema = duck_conn.execute(
                f"SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='prd_metrics' AND table_name='{table_name}' ORDER BY ordinal_position"
            ).fetchall()

            # Convert DuckDB types to SQLite types
            type_mapping = {
                'BIGINT': 'INTEGER',
                'INTEGER': 'INTEGER',
                'DOUBLE': 'REAL',
                'VARCHAR': 'TEXT',
                'TIMESTAMP WITH TIME ZONE': 'TEXT',
                'BOOLEAN': 'INTEGER',
                'DATE': 'TEXT',
            }

            columns_def = []
            for col_name, col_type in schema:
                # Handle array types (convert to TEXT in SQLite)
                if '[]' in col_type or 'ARRAY' in col_type.upper():
                    sqlite_type = 'TEXT'
                else:
                    sqlite_type = type_mapping.get(col_type.upper(), 'TEXT')
                columns_def.append(f"{col_name} {sqlite_type}")

            # Create SQLite table
            create_sql = f"CREATE TABLE {table_name} ({', '.join(columns_def)})"
            sqlite_cursor.execute(create_sql)

            # Convert arrays to JSON strings for SQLite
            for col in df.columns:
                if df[col].dtype == 'object':
                    # Check if column contains lists
                    sample = df[col].iloc[0] if len(df) > 0 else None
                    if isinstance(sample, list):
                        df[col] = df[col].apply(lambda x: str(x) if isinstance(x, list) else x)

            # Insert data into SQLite
            df.to_sql(table_name, sqlite_conn, if_exists='replace', index=False)

            print(f"  ✅ Exported {row_count} rows to SQLite")
            exported_count += 1

        except Exception as e:
            print(f"  ❌ Failed to export {table_name}: {e}")

    # Create indexes for common query patterns
    print(f"\n🔍 Creating indexes for performance...")
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_behavior_usage_timestamp ON fact_behavior_usage(first_plan_timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_compliance_steps_timestamp ON fact_compliance_steps(timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_behavior_usage_run_id ON fact_behavior_usage(run_id)",
        "CREATE INDEX IF NOT EXISTS idx_token_savings_run_id ON fact_token_savings(run_id)",
        "CREATE INDEX IF NOT EXISTS idx_execution_status_run_id ON fact_execution_status(run_id)",
        "CREATE INDEX IF NOT EXISTS idx_compliance_steps_run_id ON fact_compliance_steps(run_id)",
    ]

    for idx_sql in indexes:
        try:
            sqlite_cursor.execute(idx_sql)
            print(f"  ✅ {idx_sql.split('idx_')[1].split(' ')[0]}")
        except Exception as e:
            print(f"  ⚠️  Index creation skipped: {e}")

    # Commit and close
    sqlite_conn.commit()
    sqlite_conn.close()
    duck_conn.close()

    # Get final file size
    size_mb = sqlite_file.stat().st_size / (1024 * 1024)

    print(f"\n✅ Export complete!")
    print(f"📊 Exported {exported_count} tables/views")
    print(f"💾 SQLite database size: {size_mb:.2f} MB")
    print(f"📁 Location: {sqlite_file.absolute()}")
    print(f"\n🔗 Metabase connection:")
    print(f"   Database type: SQLite")
    print(f"   Filename (container): /duckdb/telemetry_sqlite.db")
    print(f"   Filename (host): {sqlite_file.absolute()}")


if __name__ == "__main__":
    export_duckdb_to_sqlite()
