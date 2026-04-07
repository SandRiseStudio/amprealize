#!/usr/bin/env bash
set -euo pipefail

if ! command -v pre-commit >/dev/null 2>&1; then
  echo "pre-commit CLI is required. Install with 'pip install pre-commit' or see docs for alternatives." >&2
  exit 1
fi

pre-commit run gitleaks --all-files --hook-stage manual "$@"
