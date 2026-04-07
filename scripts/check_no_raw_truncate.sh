#!/usr/bin/env bash
# Fail if any test file contains raw TRUNCATE SQL (must use safe_truncate from conftest)
#
# Allowed patterns (not flagged):
#   - References to safe_truncate (the approved helper)
#   - conftest.py itself (defines safe_truncate)
#   - Lines with "# safe_truncate exempt" comment (escape hatch)
#   - Function/variable names containing "truncate" (e.g., _truncate_tables)
#
# Blocked patterns:
#   - cur.execute("TRUNCATE ...")
#   - conn.execute("TRUNCATE ...")
#   - Any literal SQL TRUNCATE statement in test files

set -euo pipefail

HITS=$(grep -rn "TRUNCATE" tests/ --include="*.py" \
    | grep -v "safe_truncate" \
    | grep -v "conftest\.py" \
    | grep -v "# safe_truncate exempt" \
    | grep -v "def _truncate" \
    | grep -v "_truncate_.*(" \
    || true)

if [ -n "$HITS" ]; then
    echo "============================================================"
    echo "ERROR: Raw TRUNCATE found in test files!"
    echo "Use safe_truncate() from conftest.py instead."
    echo "============================================================"
    echo "$HITS"
    echo ""
    echo "To exempt a line, add: # safe_truncate exempt"
    exit 1
fi

echo "✓ No raw TRUNCATE statements in test files."
