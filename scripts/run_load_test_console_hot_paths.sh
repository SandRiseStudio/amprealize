#!/usr/bin/env bash
# Resolve Bearer JWT from the same store as `amprealize auth login`, then run
# scripts/load_test_console_hot_paths.py. Requires repo .venv.
#
# Env (optional):
#   AMPREALIZE_LOAD_TEST_BASE_URL   default http://localhost:8080
#   AMPREALIZE_LOAD_TEST_BEARER_TOKEN  if set, skip resolution and use this token
#   AMPREALIZE_LOAD_TEST_ORG_ID
# All other args pass through to load_test_console_hot_paths.py
#
# Exit codes: 0 ok, 1 missing/invalid token or load test failure, 127 missing .venv

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${ROOT}/.venv/bin/python"
AMP="${ROOT}/.venv/bin/amprealize"
LT="${ROOT}/scripts/load_test_console_hot_paths.py"

if [[ ! -x "$PY" ]]; then
  echo "run_load_test_console_hot_paths: missing ${PY} (create project venv first)." >&2
  exit 127
fi
if [[ ! -f "$LT" ]]; then
  echo "run_load_test_console_hot_paths: missing ${LT}" >&2
  exit 1
fi

export AMPREALIZE_LOAD_TEST_BASE_URL="${AMPREALIZE_LOAD_TEST_BASE_URL:-http://localhost:8080}"

resolve_token() {
  "$PY" -c "
import sys
from amprealize.auth_tokens import get_default_token_store, TokenStoreError
try:
    store = get_default_token_store()
except TokenStoreError:
    store = get_default_token_store(allow_plaintext=True)
b = store.load()
if not b:
    sys.exit(3)
if not b.is_access_valid():
    sys.exit(4)
sys.stdout.write(b.access_token)
"
}

if [[ -z "${AMPREALIZE_LOAD_TEST_BEARER_TOKEN:-}" ]]; then
  rc=0
  tok="$(resolve_token)" || rc=$?
  if [[ "$rc" -eq 4 ]] && [[ -x "$AMP" ]]; then
    echo "run_load_test_console_hot_paths: access token expired; trying auth refresh..." >&2
    "$AMP" auth refresh 2>/dev/null || true
    rc=0
    tok="$(resolve_token)" || rc=$?
  fi
  if [[ "$rc" -eq 3 ]]; then
    echo "run_load_test_console_hot_paths: no cached OAuth tokens." >&2
    echo "  Run: cd ${ROOT} && .venv/bin/amprealize auth login --provider=github" >&2
    exit 1
  fi
  if [[ "$rc" -eq 4 ]]; then
    echo "run_load_test_console_hot_paths: access token expired and refresh did not renew it." >&2
    echo "  Run: cd ${ROOT} && .venv/bin/amprealize auth login --provider=github" >&2
    exit 1
  fi
  if [[ "$rc" -ne 0 ]] || [[ -z "$tok" ]]; then
    echo "run_load_test_console_hot_paths: could not resolve bearer token (code ${rc})." >&2
    exit 1
  fi
  export AMPREALIZE_LOAD_TEST_BEARER_TOKEN="$tok"
fi

exec "$PY" "$LT" "$@"
