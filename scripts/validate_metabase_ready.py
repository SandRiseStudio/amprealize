#!/usr/bin/env python3
"""
Metabase Dashboard Pre-Flight Validation Script

Verifies environment is ready for manual dashboard creation:
- Metabase is running and healthy
- Database connection exists
- All required tables/views are accessible
- Sample data exists for visualization
"""

import sys
import json
import subprocess
from pathlib import Path

def check_metabase_health():
    """Verify Metabase is running and healthy"""
    print("🔍 Checking Metabase health...")
    try:
        result = subprocess.run(
            ["curl", "-s", "http://localhost:3000/api/health"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            response = json.loads(result.stdout)
            if response.get("status") == "ok":
                print("✅ Metabase is healthy and running")
                return True
            else:
                print(f"⚠️  Metabase status: {response.get('status')}")
                return False
        else:
            print("❌ Metabase is not responding")
            return False
    except Exception as e:
        print(f"❌ Failed to check Metabase health: {e}")
        return False

def check_sqlite_export():
    """Verify SQLite export exists and is readable"""
    print("\n🔍 Checking SQLite export file...")
    sqlite_path = Path("data/telemetry_sqlite.db")

    if not sqlite_path.exists():
        print(f"❌ SQLite export not found at {sqlite_path}")
        print("   Run: python scripts/export_duckdb_to_sqlite.py")
        return False

    file_size = sqlite_path.stat().st_size
    print(f"✅ SQLite export exists ({file_size / 1024:.1f} KB)")
    return True

def check_database_tables():
    """Verify all required tables/views exist in SQLite export"""
    print("\n🔍 Checking database tables...")

    required_tables = [
        "fact_behavior_usage",
        "fact_compliance_steps",
        "fact_execution_status",
        "fact_token_savings",
        "view_behavior_reuse_rate",
        "view_completion_rate",
        "view_compliance_coverage_rate",
        "view_token_savings_rate",
    ]

    try:
        import sqlite3
        conn = sqlite3.connect("data/telemetry_sqlite.db")
        cursor = conn.cursor()

        # Get all tables and views
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type IN ('table', 'view')
            ORDER BY name
        """)
        existing_tables = [row[0] for row in cursor.fetchall()]

        missing = []
        found = []
        for table in required_tables:
            if table in existing_tables:
                # Check row count
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                found.append((table, count))
                print(f"  ✅ {table} ({count} rows)")
            else:
                missing.append(table)
                print(f"  ❌ {table} (missing)")

        conn.close()

        if missing:
            print(f"\n⚠️  Missing {len(missing)} tables/views")
            print("   Run: python scripts/export_duckdb_to_sqlite.py")
            return False

        print(f"\n✅ All {len(required_tables)} tables/views present")
        return True

    except Exception as e:
        print(f"❌ Failed to check tables: {e}")
        return False

def check_sample_data():
    """Verify tables have enough data for meaningful visualizations"""
    print("\n🔍 Checking sample data availability...")

    try:
        import sqlite3
        conn = sqlite3.connect("data/telemetry_sqlite.db")
        cursor = conn.cursor()

        # Check if we have data in last 30 days
        data_checks = [
            ("fact_execution_status", "Recent runs"),
            ("fact_behavior_usage", "Behavior citations"),
            ("fact_token_savings", "Token savings records"),
            ("fact_compliance_steps", "Compliance records"),
        ]

        all_good = True
        for table, desc in data_checks:
            cursor.execute(f"""
                SELECT COUNT(*) FROM {table}
                WHERE DATE(execution_timestamp) >= DATE('now', '-30 days')
            """)
            count = cursor.fetchone()[0]

            if count > 0:
                print(f"  ✅ {desc}: {count} records")
            else:
                print(f"  ⚠️  {desc}: No data in last 30 days")
                all_good = False

        conn.close()

        if all_good:
            print("\n✅ Sufficient sample data available")
        else:
            print("\n⚠️  Some tables have no recent data (dashboards will work but may show 'No results')")

        return True

    except Exception as e:
        print(f"❌ Failed to check sample data: {e}")
        return False

def check_documentation():
    """Verify dashboard guides are available"""
    print("\n🔍 Checking documentation...")

    docs = [
        ("docs/analytics/METABASE_DASHBOARD_CREATION_GUIDE.md", "Dashboard creation guide"),
        ("docs/analytics/DASHBOARD_QUICK_REFERENCE.md", "Quick reference"),
        ("docs/analytics/dashboard-exports/README.md", "Dashboard exports"),
        ("docs/analytics/metabase_setup.md", "Metabase setup guide"),
    ]

    all_present = True
    for doc_path, desc in docs:
        path = Path(doc_path)
        if path.exists():
            print(f"  ✅ {desc}")
        else:
            print(f"  ❌ {desc} (missing)")
            all_present = False

    if all_present:
        print("\n✅ All documentation available")
    else:
        print("\n⚠️  Some documentation missing")

    return all_present

def print_summary():
    """Print next steps summary"""
    print("\n" + "="*60)
    print("📊 METABASE DASHBOARD CREATION - READY TO START")
    print("="*60)
    print("\n🎯 Next Steps:")
    print("   1. Open browser: http://localhost:3000")
    print("   2. Login: admin@amprealize.local / changeme123")
    print("   3. Follow: docs/analytics/METABASE_DASHBOARD_CREATION_GUIDE.md")
    print("   4. Quick reference: docs/analytics/DASHBOARD_QUICK_REFERENCE.md")
    print("\n📚 Dashboards to Create:")
    print("   1. PRD KPI Summary - Executive metrics overview")
    print("   2. Behavior Usage Trends - Citation analytics")
    print("   3. Token Savings Analysis - Efficiency & ROI")
    print("   4. Compliance Coverage - Audit trail")
    print("\n⏱️  Estimated Time: 60-90 minutes")
    print("="*60)

def main():
    """Run all validation checks"""
    print("🚀 Metabase Dashboard Pre-Flight Validation")
    print("="*60)

    checks = [
        ("Metabase Health", check_metabase_health),
        ("SQLite Export", check_sqlite_export),
        ("Database Tables", check_database_tables),
        ("Sample Data", check_sample_data),
        ("Documentation", check_documentation),
    ]

    results = []
    for name, check_func in checks:
        result = check_func()
        results.append((name, result))

    # Summary
    print("\n" + "="*60)
    print("VALIDATION SUMMARY")
    print("="*60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {name}")

    print(f"\nResult: {passed}/{total} checks passed")

    if passed == total:
        print_summary()
        return 0
    else:
        print("\n⚠️  Some checks failed. Please fix issues before proceeding.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
