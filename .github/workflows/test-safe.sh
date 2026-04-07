#!/bin/bash
# Safe test execution script for CI and local development
# Prevents system overload by limiting parallel workers

set -e

# Detect environment
if [ -n "$CI" ]; then
  # CI environment: use more workers (GitHub Actions has 2-4 cores)
  WORKERS="${PYTEST_WORKERS:-4}"
  echo "🔧 CI environment detected, using $WORKERS parallel workers"
else
  # Local development: conservative settings
  WORKERS="${PYTEST_WORKERS:-2}"
  echo "💻 Local environment detected, using $WORKERS parallel workers"
  echo "   (Set PYTEST_WORKERS env var to override, e.g., PYTEST_WORKERS=4)"
fi

# Memory check (optional, skip if not available)
if command -v free &> /dev/null; then
  MEM_AVAILABLE=$(free -m | awk '/^Mem:/{print $7}')
  if [ "$MEM_AVAILABLE" -lt 2000 ]; then
    echo "⚠️  Low memory detected ($MEM_AVAILABLE MB), reducing workers to 1"
    WORKERS=1
  fi
fi

# Run tests with safe parallelization
echo "🧪 Running test suite with $WORKERS workers..."
pytest -n "$WORKERS" "$@"
