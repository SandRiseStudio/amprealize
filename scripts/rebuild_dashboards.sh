#!/bin/bash
# Complete Metabase Dashboard Rebuild Pipeline
# Run this script to regenerate all dashboards with fresh data

set -e  # Exit on error

echo "🚀 Amprealize Metabase Dashboard Rebuild Pipeline"
echo "================================================"

# Step 1: Generate sample telemetry data
echo ""
echo "📊 Step 1/3: Generating telemetry data..."
python scripts/seed_telemetry_data.py --runs 100

# Step 2: Export DuckDB to SQLite
echo ""
echo "📦 Step 2/3: Exporting to SQLite..."
python scripts/export_duckdb_to_sqlite.py

# Step 3: Recreate Metabase dashboards
echo ""
echo "📈 Step 3/3: Creating Metabase dashboards..."
python scripts/create_metabase_dashboards.py

echo ""
echo "================================================"
echo "✅ Pipeline complete!"
echo ""
echo "🌐 View dashboards at: http://localhost:3000"
echo ""
echo "📊 Dashboard URLs:"
echo "  1. PRD KPI Summary: http://localhost:3000/dashboard/12"
echo "  2. Behavior Usage: http://localhost:3000/dashboard/13"
echo "  3. Token Savings: http://localhost:3000/dashboard/14"
echo "  4. Compliance Coverage: http://localhost:3000/dashboard/15"
echo ""
