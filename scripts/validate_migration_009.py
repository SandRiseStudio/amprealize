#!/usr/bin/env python3
"""
Validate Migration 009: WorkflowService Schema Refactoring
Purpose: Test migration creates workflow_template_versions table and migrates data correctly
Context: Priority 1.3.4.B - Architecture Standardization
"""

import psycopg2
import json
from datetime import datetime
from typing import Dict, List, Any

# Connection string for postgres-workflow container
DSN = "postgresql://amprealize_workflow:dev_workflow_pass@localhost:5434/workflows"

def run_validation():
    """Run comprehensive validation checks on migration 009"""
    print("=" * 80)
    print("Migration 009 Validation: WorkflowService Schema Refactoring")
    print("=" * 80)

    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    cur = conn.cursor()

    results = {
        "passed": [],
        "failed": [],
        "warnings": []
    }

    try:
        # Check 1: workflow_template_versions table exists
        print("\n[1/10] Checking workflow_template_versions table exists...")
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'workflow_template_versions'
            )
        """)
        if cur.fetchone()[0]:
            results["passed"].append("✅ workflow_template_versions table created")
            print("  PASS: Table exists")
        else:
            results["failed"].append("❌ workflow_template_versions table missing")
            print("  FAIL: Table not found")

        # Check 2: Verify column schema matches BehaviorService pattern
        print("\n[2/10] Validating workflow_template_versions column schema...")
        cur.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'workflow_template_versions'
            ORDER BY ordinal_position
        """)
        columns = cur.fetchall()
        expected_columns = {
            'template_id', 'version', 'steps', 'status', 'metadata',
            'effective_from', 'effective_to', 'created_by_id',
            'created_by_role', 'created_by_surface', 'approval_action_id'
        }
        actual_columns = {col[0] for col in columns}

        if expected_columns.issubset(actual_columns):
            results["passed"].append("✅ All required columns present")
            print(f"  PASS: Found {len(actual_columns)} columns")
            for col in columns:
                print(f"    - {col[0]}: {col[1]} {'NULL' if col[2] == 'YES' else 'NOT NULL'}")
        else:
            missing = expected_columns - actual_columns
            results["failed"].append(f"❌ Missing columns: {missing}")
            print(f"  FAIL: Missing columns: {missing}")

        # Check 3: Verify composite primary key
        print("\n[3/10] Checking composite primary key (template_id, version)...")
        cur.execute("""
            SELECT COUNT(*)
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
            WHERE tc.table_name = 'workflow_template_versions'
                AND tc.constraint_type = 'PRIMARY KEY'
                AND kcu.column_name IN ('template_id', 'version')
        """)
        if cur.fetchone()[0] == 2:
            results["passed"].append("✅ Composite primary key configured")
            print("  PASS: (template_id, version) primary key exists")
        else:
            results["failed"].append("❌ Composite primary key missing or incorrect")
            print("  FAIL: Primary key not properly configured")

        # Check 4: Verify foreign key constraint
        print("\n[4/10] Checking foreign key to workflow_templates...")
        cur.execute("""
            SELECT COUNT(*)
            FROM information_schema.table_constraints
            WHERE table_name = 'workflow_template_versions'
                AND constraint_type = 'FOREIGN KEY'
        """)
        if cur.fetchone()[0] >= 1:
            results["passed"].append("✅ Foreign key constraint exists")
            print("  PASS: FK constraint to workflow_templates configured")
        else:
            results["failed"].append("❌ Foreign key constraint missing")
            print("  FAIL: No FK constraint found")

        # Check 5: Verify indexes created
        print("\n[5/10] Checking composite indexes for optimization...")
        cur.execute("""
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'workflow_template_versions'
            ORDER BY indexname
        """)
        indexes = [row[0] for row in cur.fetchall()]
        expected_indexes = [
            'idx_workflow_template_versions_lookup',
            'idx_workflow_template_versions_status',
            'idx_workflow_template_versions_effective_from',
            'idx_workflow_template_versions_steps_gin',
            'idx_workflow_template_versions_metadata_gin'
        ]

        found_indexes = [idx for idx in expected_indexes if idx in indexes]
        if len(found_indexes) == len(expected_indexes):
            results["passed"].append("✅ All composite indexes created")
            print(f"  PASS: Found {len(found_indexes)}/{len(expected_indexes)} indexes")
            for idx in found_indexes:
                print(f"    - {idx}")
        else:
            missing = set(expected_indexes) - set(found_indexes)
            results["warnings"].append(f"⚠️  Missing indexes: {missing}")
            print(f"  WARN: Missing indexes: {missing}")

        # Check 6: Verify workflow_templates header columns added
        print("\n[6/10] Checking workflow_templates header columns...")
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'workflow_templates'
                AND column_name IN ('status', 'latest_version', 'updated_at')
        """)
        header_cols = [row[0] for row in cur.fetchall()]
        if len(header_cols) == 3:
            results["passed"].append("✅ Header columns added to workflow_templates")
            print(f"  PASS: Added {header_cols}")
        else:
            results["failed"].append(f"❌ Missing header columns: {set(['status', 'latest_version', 'updated_at']) - set(header_cols)}")
            print(f"  FAIL: Missing columns")

        # Check 7: Verify data migration (row counts)
        print("\n[7/10] Validating data migration...")
        cur.execute("SELECT COUNT(*) FROM workflow_templates")
        template_count = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM workflow_template_versions")
        version_count = cur.fetchone()[0]

        print(f"  workflow_templates: {template_count} rows")
        print(f"  workflow_template_versions: {version_count} rows")

        if template_count > 0 and version_count == template_count:
            results["passed"].append("✅ Data migration successful (1:1 mapping)")
            print("  PASS: All templates have corresponding versions")
        elif template_count == 0:
            results["warnings"].append("⚠️  No templates to migrate")
            print("  WARN: Empty database (expected for fresh install)")
        else:
            results["failed"].append(f"❌ Row count mismatch: {template_count} templates, {version_count} versions")
            print("  FAIL: Row counts don't match")

        # Check 8: Verify version data structure
        if version_count > 0:
            print("\n[8/10] Validating version data structure...")
            cur.execute("""
                SELECT template_id, version, steps, status, effective_from, effective_to
                FROM workflow_template_versions
                LIMIT 1
            """)
            sample = cur.fetchone()

            checks = []
            checks.append(("template_id format", sample[0] and sample[0].startswith('wf-')))
            checks.append(("version format", sample[1] and '.' in sample[1]))
            checks.append(("steps is JSONB array", isinstance(sample[2], (list, dict))))
            checks.append(("status is APPROVED", sample[3] == 'APPROVED'))
            checks.append(("effective_from set", sample[4] is not None))
            checks.append(("effective_to is NULL", sample[5] is None))

            passed_checks = [check for check in checks if check[1]]
            if len(passed_checks) == len(checks):
                results["passed"].append("✅ Version data structure valid")
                print("  PASS: All data structure checks passed")
                for check_name, _ in checks:
                    print(f"    - {check_name} ✓")
            else:
                failed_checks = [check[0] for check in checks if not check[1]]
                results["failed"].append(f"❌ Data structure issues: {failed_checks}")
                print(f"  FAIL: {failed_checks}")
        else:
            print("\n[8/10] Skipping version data validation (no data)")
            results["warnings"].append("⚠️  No version data to validate")

        # Check 9: Verify JSONB operators work
        print("\n[9/10] Testing JSONB query operators...")
        cur.execute("""
            SELECT COUNT(*)
            FROM workflow_template_versions
            WHERE steps @> '[]'::jsonb
        """)
        jsonb_count = cur.fetchone()[0]
        if jsonb_count >= 0:  # Query succeeded
            results["passed"].append("✅ JSONB operators functional")
            print(f"  PASS: JSONB query returned {jsonb_count} results")
        else:
            results["failed"].append("❌ JSONB operator query failed")
            print("  FAIL: JSONB query error")

        # Check 10: Verify JOIN query pattern works
        print("\n[10/10] Testing JOIN query pattern...")
        cur.execute("""
            SELECT
                wt.template_id,
                wt.name,
                wt.status as template_status,
                wtv.version,
                wtv.steps,
                wtv.status as version_status
            FROM workflow_templates wt
            LEFT JOIN workflow_template_versions wtv
                ON wt.template_id = wtv.template_id
                AND wtv.status = 'APPROVED'
                AND wtv.effective_to IS NULL
            LIMIT 5
        """)
        join_results = cur.fetchall()
        if join_results or template_count == 0:
            results["passed"].append("✅ JOIN query pattern works")
            print(f"  PASS: JOIN query returned {len(join_results)} results")
        else:
            results["failed"].append("❌ JOIN query pattern failed")
            print("  FAIL: Expected JOIN results")

    except Exception as e:
        results["failed"].append(f"❌ Validation error: {str(e)}")
        print(f"\n  ERROR: {e}")

    finally:
        cur.close()
        conn.close()

    # Summary
    print("\n" + "=" * 80)
    print("VALIDATION SUMMARY")
    print("=" * 80)

    print(f"\n✅ Passed: {len(results['passed'])}")
    for item in results["passed"]:
        print(f"  {item}")

    if results["warnings"]:
        print(f"\n⚠️  Warnings: {len(results['warnings'])}")
        for item in results["warnings"]:
            print(f"  {item}")

    if results["failed"]:
        print(f"\n❌ Failed: {len(results['failed'])}")
        for item in results["failed"]:
            print(f"  {item}")
        return 1

    print("\n🎉 All critical checks passed! Migration 009 validated successfully.")
    print("\nNext steps:")
    print("  1. Refactor WorkflowService methods to use JOIN queries")
    print("  2. Update create_template() to INSERT into both tables")
    print("  3. Migrate from ThreadedConnectionPool to PostgresPool")
    print("  4. Run pytest tests/test_workflow_parity.py -v")

    return 0

if __name__ == "__main__":
    exit(run_validation())
