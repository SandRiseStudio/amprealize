#!/usr/bin/env bash
# End-to-end benchmark driver.
#
# 1. Confirm the Amprealize context and running podman stack.
# 2. Run N Playwright journeys (cold + optional warm).
# 3. Tail api container logs for the same wall-clock window.
# 4. Produce a merged markdown report under ./out/<run-id>/report.md.
#
# Usage:
#   ./bench.sh --project=<uuid> --board=<uuid> [--runs=5] [--warm] [--no-api-logs]
#
# Environment:
#   AMPREALIZE_CONSOLE_URL  default http://localhost:5173
#
# Requires:
#   - `amprealize` CLI on PATH (for `amprealize context current`)
#   - `podman` on PATH
#   - `node` >= 18 and a prior `npm install` + `node auth-login.mjs` inside this directory

set -euo pipefail

cd "$(dirname "$0")"

RUNS=5
WARM=""
PROJECT=""
BOARD=""
NO_API_LOGS=""
LABEL=""
DISABLE_RAZE=""
HYDRATE_SLEEP=""
for arg in "$@"; do
  case "$arg" in
    --runs=*) RUNS="${arg#*=}" ;;
    --warm) WARM="--warm" ;;
    --project=*) PROJECT="${arg#*=}" ;;
    --board=*) BOARD="${arg#*=}" ;;
    --no-api-logs) NO_API_LOGS="1" ;;
    --label=*) LABEL="${arg#*=}" ;;
    --disable-raze) DISABLE_RAZE="--disable-raze" ;;
    --hydrate-sleep=*) HYDRATE_SLEEP="--hydrate-sleep=${arg#*=}" ;;
    *) echo "Unknown arg: $arg" >&2; exit 2 ;;
  esac
done

BASE="${AMPREALIZE_CONSOLE_URL:-http://localhost:5173}"

echo "=== Context ==="
CONTEXT_LINE="$(amprealize context current 2>/dev/null | head -1 || true)"
echo "$CONTEXT_LINE"
CONTEXT_NAME="$(echo "$CONTEXT_LINE" | sed -E 's/^Current context: ([^ ]+).*$/\1/' || echo unknown)"
[ -z "$CONTEXT_NAME" ] && CONTEXT_NAME="unknown"

echo "=== Podman containers ==="
API_CONTAINER="$(podman ps --format '{{.Names}}' | grep -m1 amprealize-api || true)"
WEB_CONTAINER="$(podman ps --format '{{.Names}}' | grep -m1 web-console || true)"
echo "api: ${API_CONTAINER:-<missing>}"
echo "web: ${WEB_CONTAINER:-<missing>}"
if [ -z "$API_CONTAINER" ] || [ -z "$WEB_CONTAINER" ]; then
  echo "Stack not running. Try: breakeramp up cloud-dev (or development)." >&2
  exit 3
fi

TS="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
RUN_ID="${CONTEXT_NAME}-${TS}"
[ -n "$LABEL" ] && RUN_ID="${RUN_ID}-${LABEL}"
OUT_DIR="out/${RUN_ID}"
mkdir -p "$OUT_DIR"

T0_EPOCH=$(date +%s)
T0_ISO="$(date -u -r "$T0_EPOCH" +%Y-%m-%dT%H:%M:%SZ)"

echo "=== Running journeys (run-id=$RUN_ID) ==="
NODE_CMD=(node run-journeys.mjs
  --base="$BASE"
  --runs="$RUNS"
  --context="$CONTEXT_NAME"
  --run-id="$RUN_ID"
)
[ -n "$WARM" ] && NODE_CMD+=("$WARM")
[ -n "$PROJECT" ] && NODE_CMD+=(--project="$PROJECT")
[ -n "$BOARD" ] && NODE_CMD+=(--board="$BOARD")
[ -n "$DISABLE_RAZE" ] && NODE_CMD+=("$DISABLE_RAZE")
[ -n "$HYDRATE_SLEEP" ] && NODE_CMD+=("$HYDRATE_SLEEP")

"${NODE_CMD[@]}"

T1_EPOCH=$(date +%s)

if [ -z "$NO_API_LOGS" ]; then
  echo "=== Dumping api container logs for window ==="
  podman logs --since "${T0_ISO}" "$API_CONTAINER" > "$OUT_DIR/api.log" 2>&1 || true
  grep -E '^perf |perf ' "$OUT_DIR/api.log" > "$OUT_DIR/api.perf.log" || true
  echo "wrote $OUT_DIR/api.log ($(wc -l <"$OUT_DIR/api.log") lines, perf lines: $(wc -l <"$OUT_DIR/api.perf.log" 2>/dev/null || echo 0))"
fi

echo "=== Building report ==="
node build-report.mjs --run-dir="$OUT_DIR"
echo "Done. Open $OUT_DIR/report.md"
