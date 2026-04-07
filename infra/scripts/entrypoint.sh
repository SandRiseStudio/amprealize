#!/bin/bash
# Amprealize API Entrypoint
# Initializes warehouse and starts API server

set -e

echo "=== Amprealize API Startup ==="

# Initialize DuckDB warehouse if schema file exists
WAREHOUSE_DB="${WAREHOUSE_DB:-/app/data/telemetry.duckdb}"
SCHEMA_FILE="${SCHEMA_FILE:-/app/docs/analytics/prd_metrics_schema_duckdb.sql}"

if [ -f "$SCHEMA_FILE" ]; then
    echo "Initializing DuckDB warehouse..."
    python /app/deployment/scripts/init-warehouse.py "$WAREHOUSE_DB" "$SCHEMA_FILE"
else
    echo "WARNING: Schema file not found at $SCHEMA_FILE, skipping warehouse init"
fi

echo "Starting API server..."
exec "$@"
