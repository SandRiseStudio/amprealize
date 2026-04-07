#!/usr/bin/env bash
set -euo pipefail

if ! command -v pre-commit >/dev/null 2>&1; then
  echo "pre-commit CLI is required. Install it via 'pip install pre-commit' or your preferred package manager." >&2
  exit 1
fi

# Install hooks so standard git workflows trigger the configured checks automatically.
pre-commit install --hook-type pre-commit --hook-type commit-msg --hook-type pre-push >/dev/null

echo "pre-commit hooks installed. 'git commit' and 'git push' will now run the configured checks automatically."
