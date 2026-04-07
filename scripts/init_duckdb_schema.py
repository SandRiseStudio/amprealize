#!/usr/bin/env python3
"""Initialize DuckDB schema for telemetry warehouse."""

import os
import sys
from pathlib import Path

try:
    import duckdb
except ImportError:
    print("❌ DuckDB not installed. Run: pip install -e '.[telemetry]'")
    sys.exit(1)

# Resolve paths
repo_root = Path(__file__).parent.parent
schema_file = repo_root / "docs" / "analytics" / "prd_metrics_schema.sql"
db_path = Path(repo_root) / os.getenv("DUCKDB_PATH", "data/telemetry.duckdb")

if not schema_file.exists():
    print(f"❌ Schema file not found: {schema_file}")
    sys.exit(1)

# Ensure data directory exists
Path(db_path).parent.mkdir(parents=True, exist_ok=True)

print(f"Initializing DuckDB schema: {db_path}")
print(f"Using schema DDL: {schema_file}")

# Read schema DDL
with open(schema_file) as f:
    ddl = f.read()

# Connect and execute DDL
conn = duckdb.connect(str(db_path))
conn.execute(ddl)

# Verify tables created
tables = conn.execute("SHOW TABLES").fetchall()
print(f"\n✅ Schema initialized successfully")
print(f"📊 Tables created: {len(tables)}")
for table in tables:
    table_name = table[0]
    result = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
    count = result[0] if result else 0
    print(f"  - {table_name}: {count} rows")

conn.close()
print("\nReady to process telemetry events!")
