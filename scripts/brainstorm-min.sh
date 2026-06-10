#!/usr/bin/env bash
#
# brainstorm-min.sh — bare-minimum LIVE whiteboard stack for the Brainstorm agent.
#
# Runs three local processes (NO Podman, NO full amprealize-api):
#   1. minimal whiteboard API  (scripts/whiteboard_min_api.py)   :8000
#   2. whiteboard-sync sidecar (packages/whiteboard-sync)        :3040
#   3. web-console (Vite)      (web-console)                     :5173
#
# Claude Code's MCP server (already running via /Users/nick/Main/.mcp.json)
# shares the SAME whiteboard store, so rooms the brainstorm agent opens are
# visible in the browser. The store is selected by the profile arg below and
# MUST match what .mcp.json sets for the MCP server.
#
# Usage:
#   scripts/brainstorm-min.sh [profile]
#
# Profiles (storage backend shared MCP <-> API):
#   sqlite   (default)  shared sqlite file, no DB process        — lightest
#   neon                cloud Postgres (WHITEBOARD_PG_DSN / DATABASE_URL)
#   postgres            bring-your-own Postgres via WHITEBOARD_PG_DSN
#   memory              single-process only — NOT live (browser will 404)
#
# Env overrides: WHITEBOARD_SQLITE_PATH, WHITEBOARD_PG_DSN, API_PORT (8000),
#                SYNC_PORT (3040), WEB_PORT (5173).
set -euo pipefail

REPO_ROOT="/Users/nick/Main/amprealize"
VENV_PY="${REPO_ROOT}/.venv/bin/python"     # has fastapi + uvicorn + psycopg2
PROFILE="${1:-sqlite}"

API_PORT="${API_PORT:-8000}"
SYNC_PORT="${SYNC_PORT:-3040}"
WEB_PORT="${WEB_PORT:-5173}"

cd "$REPO_ROOT"

# --- Resolve storage profile -> WHITEBOARD_STORAGE_BACKEND + creds ----------
case "$PROFILE" in
  sqlite)
    export WHITEBOARD_STORAGE_BACKEND="sqlite"
    export WHITEBOARD_SQLITE_PATH="${WHITEBOARD_SQLITE_PATH:-${REPO_ROOT}/.whiteboard-dev.db}"
    STORE_DESC="sqlite file: ${WHITEBOARD_SQLITE_PATH}"
    ;;
  neon|postgres)
    export WHITEBOARD_STORAGE_BACKEND="postgres"
    # Prefer an explicit whiteboard DSN, then generic DSNs from the env/.env.
    export WHITEBOARD_PG_DSN="${WHITEBOARD_PG_DSN:-${AMPREALIZE_WHITEBOARD_PG_DSN:-${DATABASE_URL:-${AMPREALIZE_PG_DSN:-}}}}"
    if [ -z "${WHITEBOARD_PG_DSN}" ]; then
      echo "ERROR: profile '$PROFILE' needs a Postgres DSN. Set WHITEBOARD_PG_DSN (or DATABASE_URL / AMPREALIZE_PG_DSN)." >&2
      exit 1
    fi
    STORE_DESC="postgres: ${WHITEBOARD_PG_DSN%%@*}@…"   # hide creds/host tail
    ;;
  memory)
    export WHITEBOARD_STORAGE_BACKEND="memory"
    STORE_DESC="in-memory (single process — browser will NOT see agent rooms)"
    ;;
  *)
    echo "Unknown profile '$PROFILE'. Use: sqlite | neon | postgres | memory" >&2
    exit 1
    ;;
esac

PIDS=()
cleanup() {
  echo ""
  echo "Shutting down brainstorm-min stack…"
  for pid in "${PIDS[@]:-}"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "=================================================================="
echo " brainstorm-min  |  profile: ${PROFILE}"
echo " store: ${STORE_DESC}"
echo "=================================================================="

# --- 1. Minimal whiteboard API ----------------------------------------------
echo "[1/3] starting whiteboard API on :${API_PORT} …"
WHITEBOARD_MIN_API_PORT="$API_PORT" \
  "$VENV_PY" -m uvicorn scripts.whiteboard_min_api:app \
  --host 127.0.0.1 --port "$API_PORT" --log-level warning &
PIDS+=($!)

# Wait for /healthz
for i in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:${API_PORT}/healthz" >/dev/null 2>&1; then
    echo "      API healthy."
    break
  fi
  [ "$i" -eq 30 ] && { echo "ERROR: API did not become healthy." >&2; exit 1; }
  sleep 0.5
done

# --- 2. whiteboard-sync sidecar ---------------------------------------------
echo "[2/3] starting whiteboard-sync sidecar on :${SYNC_PORT} …"
( cd packages/whiteboard-sync && \
  SYNC_PORT="$SYNC_PORT" \
  PYTHON_API_BASE="http://localhost:${API_PORT}/api/v1" \
  npm run dev >/tmp/brainstorm-min-sync.log 2>&1 ) &
PIDS+=($!)

# --- 3. web-console (Vite) ---------------------------------------------------
echo "[3/3] starting web-console on :${WEB_PORT} …"
TLDRAW_KEY="${VITE_TLDRAW_LICENSE_KEY:-${TLDRAW_LICENSE_KEY:-}}"
( cd web-console && \
  VITE_API_BASE_URL="http://localhost:${API_PORT}" \
  VITE_WHITEBOARD_SYNC_URL="http://localhost:${SYNC_PORT}" \
  VITE_TLDRAW_LICENSE_KEY="$TLDRAW_KEY" \
  npm run dev -- --port "$WEB_PORT" >/tmp/brainstorm-min-web.log 2>&1 ) &
PIDS+=($!)

sleep 2
cat <<EOF

------------------------------------------------------------------
 Stack is up.
   API          http://localhost:${API_PORT}/healthz
   sync sidecar ws://localhost:${SYNC_PORT}   (log: /tmp/brainstorm-min-sync.log)
   web-console  http://localhost:${WEB_PORT}    (log: /tmp/brainstorm-min-web.log)

 In Claude Code, run /brainstorm and opt into the whiteboard.
 Open the room_url it returns. If the canvas shows a login/empty
 state, set a dev token first in the browser console:

     localStorage.setItem('amprealize_token', 'dev');  // any non-empty value

 NOTE: .mcp.json must use the SAME store as this profile
 (WHITEBOARD_STORAGE_BACKEND=${WHITEBOARD_STORAGE_BACKEND}).

 Press Ctrl-C to stop everything.
------------------------------------------------------------------
EOF

wait
