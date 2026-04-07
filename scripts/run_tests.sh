#!/usr/bin/env bash
# Safe test runner for Amprealize with Podman (podman compose) containers
# Behaviors: behavior_align_storage_layers, behavior_unify_execution_records,
#            behavior_instrument_metrics_pipeline
#
# Usage:
#   ./scripts/run_tests.sh                    # Run all tests serially (safest)
#   ./scripts/run_tests.sh -n 2               # Run with 2 workers
#   ./scripts/run_tests.sh tests/test_cli_*.py  # Run specific tests
#   ./scripts/run_tests.sh --check-only       # Only check environment
#   ./scripts/run_tests.sh --breakeramp --env ci    # Use breakeramp with 'ci' environment
#   ./scripts/run_tests.sh --env-file custom.yaml --env prod  # Custom manifest and environment

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export AMPREALIZE_REPO_ROOT="$REPO_ROOT"
cd "$REPO_ROOT"

# =============================================================================
# Terminal Styling (BreakerAmp-aligned)
# =============================================================================

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

# Symbols
SYM_CHECK="✓"
SYM_CROSS="✗"
SYM_WARN="⚠"
SYM_DOT="•"

# Output helpers for consistent styling
print_header() {
    local title="$1"
    local line="━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo -e "${BLUE}${line}${NC}"
    echo -e "${BOLD}              $title${NC}"
    echo -e "${BLUE}${line}${NC}"
}

print_section() {
    echo ""
    echo -e "${CYAN}${BOLD}$1${NC}"
}

print_success() {
    echo -e "  ${GREEN}${SYM_CHECK}${NC} $1"
}

print_error() {
    echo -e "  ${RED}${SYM_CROSS}${NC} $1"
}

print_warning() {
    echo -e "  ${YELLOW}${SYM_WARN}${NC} $1"
}

print_info() {
    echo -e "  ${DIM}${SYM_DOT}${NC} $1"
}

print_kv() {
    local key="$1"
    local value="$2"
    echo -e "  ${DIM}${key}:${NC}$(printf '%*s' $((18 - ${#key})) '') $value"
}

# =============================================================================
# Configuration
# =============================================================================

PARALLEL_WORKERS=0
CHECK_ONLY=false
PYTEST_ARGS=()
CONNECTION_TIMEOUT=5
QUERY_TIMEOUT=30
AMPREALIZE_TEST_INFRA_MODE="${AMPREALIZE_TEST_INFRA_MODE:-legacy}"
AMPREALIZE_BREAKERAMP_ENV_FILE_DEFAULT="$REPO_ROOT/environments.yaml"
export AMPREALIZE_BREAKERAMP_ENV_FILE="${AMPREALIZE_BREAKERAMP_ENV_FILE:-$AMPREALIZE_BREAKERAMP_ENV_FILE_DEFAULT}"
export AMPREALIZE_BREAKERAMP_ENVIRONMENT="${AMPREALIZE_BREAKERAMP_ENVIRONMENT:-ci}"
AMPREALIZE_BREAKERAMP_MANAGED_MACHINE=""
AMPREALIZE_BREAKERAMP_MACHINE_NAME=""
NETSTAT_LAST_RX_BYTES=""
NETSTAT_LAST_TX_BYTES=""
WITH_KAFKA=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --check-only)
            CHECK_ONLY=true
            shift
            ;;
        --breakeramp)
            AMPREALIZE_TEST_INFRA_MODE="breakeramp"
            shift
            ;;
        --with-kafka)
            WITH_KAFKA=true
            shift
            ;;
        --env)
            export AMPREALIZE_BREAKERAMP_ENVIRONMENT="$2"
            shift 2
            ;;
        --env-file)
            export AMPREALIZE_BREAKERAMP_ENV_FILE="$2"
            shift 2
            ;;
        -n)
            PARALLEL_WORKERS="$2"
            shift 2
            ;;
        --help|-h)
            print_header "Amprealize Test Runner"
            echo ""
            echo "Usage: $0 [options] [test-paths...]"
            echo ""
            echo -e "${CYAN}Options:${NC}"
            print_kv "--check-only" "Only check environment, don't run tests"
            print_kv "--breakeramp" "Use BreakerAmp infrastructure mode"
            print_kv "--env <name>" "Specify environment name (default: ci)"
            print_kv "--env-file <path>" "Specify environment manifest file"
            print_kv "--with-kafka" "Enable Kafka streaming module"
            print_kv "-n <workers>" "Number of parallel workers (0=serial)"
            print_kv "AMPREALIZE_COMPOSE_BIN" "Override compose binary (default: podman compose)"
            print_kv "AMPREALIZE_TEST_PER_SERVICE_PG_DATABASES" "1 = legacy one-Postgres-per-service; 0 (default) = modular monolith + Alembic on behavior DB"
            print_kv "COMPOSE_PROFILES" "e.g. per-service-db — start extra Postgres services in infra/docker-compose.test.yml"
            print_kv "-h, --help" "Show this help message"
            echo ""
            echo -e "${CYAN}Examples:${NC}"
            print_info "$0                                    # Run all tests"
            print_info "$0 --breakeramp                       # Use breakeramp infra"
            print_info "$0 --breakeramp --env development     # Use 'development' env"
            print_info "$0 --breakeramp --env test --with-kafka  # Include Kafka"
            print_info "$0 -n 4 tests/test_api.py            # Run tests in parallel"
            echo ""
            exit 0
            ;;
        *)
            PYTEST_ARGS+=("$1")
            shift
            ;;
    esac
done

if [ ${#PYTEST_ARGS[@]} -eq 0 ]; then
    PYTEST_ARGS=("tests/")
fi

STAGING_STACK_MODE="${AMPREALIZE_ENABLE_STAGING_STACK:-auto}"
START_STAGING_STACK=false
STAGING_STACK_ACTIVE=false
STAGING_PORT_REASSIGNED=false

# =============================================================================
# Environment Variables Loading
# =============================================================================

# Load breakeramp environment variables from environments.yaml
# This exports all variables from the 'variables' section of the specified environment
load_breakeramp_variables() {
    local env_file="$1"
    local env_name="$2"

    [ ! -f "$env_file" ] && return 1

    # Parse YAML and export variables
    eval "$(python - "$env_file" "$env_name" <<'PY'
import sys, yaml
from pathlib import Path

manifest_path, env_name = Path(sys.argv[1]), sys.argv[2]
try:
    data = yaml.safe_load(manifest_path.read_text()) or {}
except Exception:
    sys.exit(1)

env = (data.get("environments") or {}).get(env_name)
if not env:
    sys.exit(1)

variables = env.get("variables") or {}
for key, value in variables.items():
    # Escape single quotes in values
    safe_value = str(value).replace("'", "'\\''")
    print(f"export {key}='{safe_value}'")
PY
)"
}

# Load required_endpoints from environments.yaml (breakeramp-driven health checks)
# Returns endpoints as "host|port|label" lines for the specified environment
load_breakeramp_endpoints() {
    local env_file="$1"
    local env_name="$2"

    [ ! -f "$env_file" ] && return 1

    python - "$env_file" "$env_name" <<'PY'
import sys, yaml
from pathlib import Path

manifest_path, env_name = Path(sys.argv[1]), sys.argv[2]
try:
    data = yaml.safe_load(manifest_path.read_text()) or {}
except Exception:
    sys.exit(1)

env = (data.get("environments") or {}).get(env_name)
if not env:
    sys.exit(1)

endpoints = env.get("required_endpoints") or []
for ep in endpoints:
    host = ep.get("host", "localhost")
    port = ep.get("port", 0)
    label = ep.get("label", f"{host}:{port}")
    print(f"{host}|{port}|{label}")
PY
}

# If in breakeramp mode, load variables from environments.yaml FIRST
# These will override the defaults set below
if [ "$AMPREALIZE_TEST_INFRA_MODE" = "breakeramp" ]; then
    # IMPORTANT: Unset any pre-existing DSN variables to prevent stale values
    # from overriding freshly constructed DSNs. The ${VAR:-default} pattern
    # only applies defaults if VAR is unset, so we must explicitly unset.
    unset AMPREALIZE_TELEMETRY_PG_DSN 2>/dev/null || true
    unset AMPREALIZE_BEHAVIOR_PG_DSN 2>/dev/null || true
    unset AMPREALIZE_WORKFLOW_PG_DSN 2>/dev/null || true
    unset AMPREALIZE_ACTION_PG_DSN 2>/dev/null || true
    unset AMPREALIZE_RUN_PG_DSN 2>/dev/null || true
    unset AMPREALIZE_COMPLIANCE_PG_DSN 2>/dev/null || true
    unset AMPREALIZE_ORCHESTRATOR_PG_DSN 2>/dev/null || true
    unset AMPREALIZE_METRICS_PG_DSN 2>/dev/null || true
    unset AMPREALIZE_AUTH_PG_DSN 2>/dev/null || true
    unset AMPREALIZE_BOARD_PG_DSN 2>/dev/null || true
    unset AMPREALIZE_ORG_PG_DSN 2>/dev/null || true
    unset AMPREALIZE_AGENT_REGISTRY_PG_DSN 2>/dev/null || true
    unset AMPREALIZE_AGENT_ORCHESTRATOR_PG_DSN 2>/dev/null || true
    unset AMPREALIZE_EXECUTION_PG_DSN 2>/dev/null || true
    unset AMPREALIZE_TRACE_ANALYSIS_PG_DSN 2>/dev/null || true
    unset AMPREALIZE_AGENTAUTH_PG_DSN 2>/dev/null || true
    unset AMPREALIZE_TASK_PG_DSN 2>/dev/null || true
    unset AMPREALIZE_PG_DSN 2>/dev/null || true
    unset AMPREALIZE_ALEMBIC_DATABASE_URL 2>/dev/null || true
    unset DATABASE_URL 2>/dev/null || true
    unset DATABASE__POSTGRES_URL 2>/dev/null || true

    if [ -f "$AMPREALIZE_BREAKERAMP_ENV_FILE" ]; then
        load_breakeramp_variables "$AMPREALIZE_BREAKERAMP_ENV_FILE" "$AMPREALIZE_BREAKERAMP_ENVIRONMENT" || true
    fi
fi

# =============================================================================
# Default Environment Variables (used when not overridden by breakeramp)
# =============================================================================

# Database connection defaults - breakeramp mode overrides these via environments.yaml
export AMPREALIZE_PG_HOST_BEHAVIOR="${AMPREALIZE_PG_HOST_BEHAVIOR:-localhost}"
export AMPREALIZE_PG_PORT_BEHAVIOR="${AMPREALIZE_PG_PORT_BEHAVIOR:-6433}"
export AMPREALIZE_PG_USER_BEHAVIOR="${AMPREALIZE_PG_USER_BEHAVIOR:-behavior_test}"
export AMPREALIZE_PG_PASS_BEHAVIOR="${AMPREALIZE_PG_PASS_BEHAVIOR:-behavior_test_pass}"
export AMPREALIZE_PG_DB_BEHAVIOR="${AMPREALIZE_PG_DB_BEHAVIOR:-behavior_test}"

export AMPREALIZE_PG_HOST_WORKFLOW="${AMPREALIZE_PG_HOST_WORKFLOW:-localhost}"
export AMPREALIZE_PG_PORT_WORKFLOW="${AMPREALIZE_PG_PORT_WORKFLOW:-6434}"
export AMPREALIZE_PG_USER_WORKFLOW="${AMPREALIZE_PG_USER_WORKFLOW:-workflow_test}"
export AMPREALIZE_PG_PASS_WORKFLOW="${AMPREALIZE_PG_PASS_WORKFLOW:-workflow_test_pass}"
export AMPREALIZE_PG_DB_WORKFLOW="${AMPREALIZE_PG_DB_WORKFLOW:-workflow_test}"

export AMPREALIZE_PG_HOST_ACTION="${AMPREALIZE_PG_HOST_ACTION:-localhost}"
export AMPREALIZE_PG_PORT_ACTION="${AMPREALIZE_PG_PORT_ACTION:-6435}"
export AMPREALIZE_PG_USER_ACTION="${AMPREALIZE_PG_USER_ACTION:-action_test}"
export AMPREALIZE_PG_PASS_ACTION="${AMPREALIZE_PG_PASS_ACTION:-action_test_pass}"
export AMPREALIZE_PG_DB_ACTION="${AMPREALIZE_PG_DB_ACTION:-action_test}"

export AMPREALIZE_PG_HOST_RUN="${AMPREALIZE_PG_HOST_RUN:-localhost}"
export AMPREALIZE_PG_PORT_RUN="${AMPREALIZE_PG_PORT_RUN:-6436}"
export AMPREALIZE_PG_USER_RUN="${AMPREALIZE_PG_USER_RUN:-run_test}"
export AMPREALIZE_PG_PASS_RUN="${AMPREALIZE_PG_PASS_RUN:-run_test_pass}"
export AMPREALIZE_PG_DB_RUN="${AMPREALIZE_PG_DB_RUN:-run_test}"

export AMPREALIZE_PG_HOST_COMPLIANCE="${AMPREALIZE_PG_HOST_COMPLIANCE:-localhost}"
export AMPREALIZE_PG_PORT_COMPLIANCE="${AMPREALIZE_PG_PORT_COMPLIANCE:-6437}"
export AMPREALIZE_PG_USER_COMPLIANCE="${AMPREALIZE_PG_USER_COMPLIANCE:-compliance_test}"
export AMPREALIZE_PG_PASS_COMPLIANCE="${AMPREALIZE_PG_PASS_COMPLIANCE:-compliance_test_pass}"
export AMPREALIZE_PG_DB_COMPLIANCE="${AMPREALIZE_PG_DB_COMPLIANCE:-compliance_test}"

export AMPREALIZE_PG_HOST_TELEMETRY="${AMPREALIZE_PG_HOST_TELEMETRY:-localhost}"
export AMPREALIZE_PG_PORT_TELEMETRY="${AMPREALIZE_PG_PORT_TELEMETRY:-6432}"
export AMPREALIZE_PG_USER_TELEMETRY="${AMPREALIZE_PG_USER_TELEMETRY:-telemetry_test}"
export AMPREALIZE_PG_PASS_TELEMETRY="${AMPREALIZE_PG_PASS_TELEMETRY:-telemetry_test_pass}"
export AMPREALIZE_PG_DB_TELEMETRY="${AMPREALIZE_PG_DB_TELEMETRY:-telemetry_test}"

export AMPREALIZE_PG_HOST_METRICS="${AMPREALIZE_PG_HOST_METRICS:-localhost}"
export AMPREALIZE_PG_PORT_METRICS="${AMPREALIZE_PG_PORT_METRICS:-6439}"
export AMPREALIZE_PG_USER_METRICS="${AMPREALIZE_PG_USER_METRICS:-amprealize_metrics_test}"
export AMPREALIZE_PG_PASS_METRICS="${AMPREALIZE_PG_PASS_METRICS:-metrics_test_pass}"
export AMPREALIZE_PG_DB_METRICS="${AMPREALIZE_PG_DB_METRICS:-amprealize_metrics_test}"

export AMPREALIZE_PG_HOST_AUTH="${AMPREALIZE_PG_HOST_AUTH:-localhost}"
export AMPREALIZE_PG_PORT_AUTH="${AMPREALIZE_PG_PORT_AUTH:-6440}"
export AMPREALIZE_PG_USER_AUTH="${AMPREALIZE_PG_USER_AUTH:-amprealize_auth_test}"
export AMPREALIZE_PG_PASS_AUTH="${AMPREALIZE_PG_PASS_AUTH:-auth_test_pass}"
export AMPREALIZE_PG_DB_AUTH="${AMPREALIZE_PG_DB_AUTH:-amprealize_auth_test}"

# Blueprint port variables (used by local-test-suite.yaml)
# These map to the same ports as AMPREALIZE_PG_PORT_* but with the naming the blueprint expects
export TELEMETRY_DB_PORT="${TELEMETRY_DB_PORT:-$AMPREALIZE_PG_PORT_TELEMETRY}"
export BEHAVIOR_DB_PORT="${BEHAVIOR_DB_PORT:-$AMPREALIZE_PG_PORT_BEHAVIOR}"
export WORKFLOW_DB_PORT="${WORKFLOW_DB_PORT:-$AMPREALIZE_PG_PORT_WORKFLOW}"
export ACTION_DB_PORT="${ACTION_DB_PORT:-$AMPREALIZE_PG_PORT_ACTION}"
export RUN_DB_PORT="${RUN_DB_PORT:-$AMPREALIZE_PG_PORT_RUN}"
export COMPLIANCE_DB_PORT="${COMPLIANCE_DB_PORT:-$AMPREALIZE_PG_PORT_COMPLIANCE}"
export ORCHESTRATOR_DB_PORT="${ORCHESTRATOR_DB_PORT:-6438}"
export METRICS_DB_PORT="${METRICS_DB_PORT:-$AMPREALIZE_PG_PORT_METRICS}"
export AUTH_DB_PORT="${AUTH_DB_PORT:-$AMPREALIZE_PG_PORT_AUTH}"
export REDIS_LOCAL_PORT="${REDIS_LOCAL_PORT:-6379}"
export KAFKA_EXTERNAL_PORT="${KAFKA_EXTERNAL_PORT:-10092}"
# Redis and Kafka port mappings for the blueprint
export REDIS_PORT="${REDIS_PORT:-$REDIS_LOCAL_PORT}"
export KAFKA_PORT="${KAFKA_PORT:-$KAFKA_EXTERNAL_PORT}"

export REDIS_HOST="${REDIS_HOST:-localhost}"
export REDIS_URL="${REDIS_URL:-redis://${REDIS_HOST}:${REDIS_PORT}/0}"
export CACHE_REDIS_URL="${CACHE_REDIS_URL:-$REDIS_URL}"
export KAFKA_BOOTSTRAP_SERVERS="${KAFKA_BOOTSTRAP_SERVERS:-localhost:${KAFKA_PORT}}"

# Default: one Postgres (modular monolith) for behavior/workflow/execution/compliance/auth domains.
# Set AMPREALIZE_TEST_PER_SERVICE_PG_DATABASES=1 and compose profile per-service-db for legacy layout.
if [ "${AMPREALIZE_TEST_PER_SERVICE_PG_DATABASES:-0}" != "1" ]; then
    export AMPREALIZE_PG_HOST_WORKFLOW="$AMPREALIZE_PG_HOST_BEHAVIOR"
    export AMPREALIZE_PG_PORT_WORKFLOW="$AMPREALIZE_PG_PORT_BEHAVIOR"
    export AMPREALIZE_PG_USER_WORKFLOW="$AMPREALIZE_PG_USER_BEHAVIOR"
    export AMPREALIZE_PG_PASS_WORKFLOW="$AMPREALIZE_PG_PASS_BEHAVIOR"
    export AMPREALIZE_PG_DB_WORKFLOW="$AMPREALIZE_PG_DB_BEHAVIOR"
    export AMPREALIZE_PG_HOST_ACTION="$AMPREALIZE_PG_HOST_BEHAVIOR"
    export AMPREALIZE_PG_PORT_ACTION="$AMPREALIZE_PG_PORT_BEHAVIOR"
    export AMPREALIZE_PG_USER_ACTION="$AMPREALIZE_PG_USER_BEHAVIOR"
    export AMPREALIZE_PG_PASS_ACTION="$AMPREALIZE_PG_PASS_BEHAVIOR"
    export AMPREALIZE_PG_DB_ACTION="$AMPREALIZE_PG_DB_BEHAVIOR"
    export AMPREALIZE_PG_HOST_RUN="$AMPREALIZE_PG_HOST_BEHAVIOR"
    export AMPREALIZE_PG_PORT_RUN="$AMPREALIZE_PG_PORT_BEHAVIOR"
    export AMPREALIZE_PG_USER_RUN="$AMPREALIZE_PG_USER_BEHAVIOR"
    export AMPREALIZE_PG_PASS_RUN="$AMPREALIZE_PG_PASS_BEHAVIOR"
    export AMPREALIZE_PG_DB_RUN="$AMPREALIZE_PG_DB_BEHAVIOR"
    export AMPREALIZE_PG_HOST_COMPLIANCE="$AMPREALIZE_PG_HOST_BEHAVIOR"
    export AMPREALIZE_PG_PORT_COMPLIANCE="$AMPREALIZE_PG_PORT_BEHAVIOR"
    export AMPREALIZE_PG_USER_COMPLIANCE="$AMPREALIZE_PG_USER_BEHAVIOR"
    export AMPREALIZE_PG_PASS_COMPLIANCE="$AMPREALIZE_PG_PASS_BEHAVIOR"
    export AMPREALIZE_PG_DB_COMPLIANCE="$AMPREALIZE_PG_DB_BEHAVIOR"
    export AMPREALIZE_PG_HOST_AUTH="$AMPREALIZE_PG_HOST_BEHAVIOR"
    export AMPREALIZE_PG_PORT_AUTH="$AMPREALIZE_PG_PORT_BEHAVIOR"
    export AMPREALIZE_PG_USER_AUTH="$AMPREALIZE_PG_USER_BEHAVIOR"
    export AMPREALIZE_PG_PASS_AUTH="$AMPREALIZE_PG_PASS_BEHAVIOR"
    export AMPREALIZE_PG_DB_AUTH="$AMPREALIZE_PG_DB_BEHAVIOR"
fi

ENCODED_STATEMENT_TIMEOUT="-c%20statement_timeout%3D${QUERY_TIMEOUT}s"
DSN_QUERY_PARAMS="?connect_timeout=${CONNECTION_TIMEOUT}&options=${ENCODED_STATEMENT_TIMEOUT}"

# search_path + statement_timeout for domain DSNs (matches amprealize.config.settings patterns)
amprealize_pg_options_schema() {
    local schema="$1"
    echo "-c%20search_path%3D${schema}%2Cpublic%20-c%20statement_timeout%3D${QUERY_TIMEOUT}s"
}

amprealize_service_dsn() {
    local R="$1"
    local schema="$2"
    local u="AMPREALIZE_PG_USER_${R}"
    local pw="AMPREALIZE_PG_PASS_${R}"
    local h="AMPREALIZE_PG_HOST_${R}"
    local p="AMPREALIZE_PG_PORT_${R}"
    local d="AMPREALIZE_PG_DB_${R}"
    echo "postgresql://${!u}:${!pw}@${!h}:${!p}/${!d}?connect_timeout=${CONNECTION_TIMEOUT}&options=$(amprealize_pg_options_schema "$schema")"
}

# Alembic URL: same database as behavior, no search_path (migrations set schemas explicitly)
export AMPREALIZE_ALEMBIC_DATABASE_URL="${AMPREALIZE_ALEMBIC_DATABASE_URL:-postgresql://${AMPREALIZE_PG_USER_BEHAVIOR}:${AMPREALIZE_PG_PASS_BEHAVIOR}@${AMPREALIZE_PG_HOST_BEHAVIOR}:${AMPREALIZE_PG_PORT_BEHAVIOR}/${AMPREALIZE_PG_DB_BEHAVIOR}${DSN_QUERY_PARAMS}}"

# Construct DSNs from the (possibly overridden) variables
export AMPREALIZE_BEHAVIOR_PG_DSN="${AMPREALIZE_BEHAVIOR_PG_DSN:-$(amprealize_service_dsn BEHAVIOR behavior)}"
export AMPREALIZE_WORKFLOW_PG_DSN="${AMPREALIZE_WORKFLOW_PG_DSN:-$(amprealize_service_dsn WORKFLOW workflow)}"
export AMPREALIZE_ACTION_PG_DSN="${AMPREALIZE_ACTION_PG_DSN:-$(amprealize_service_dsn ACTION execution)}"
export AMPREALIZE_RUN_PG_DSN="${AMPREALIZE_RUN_PG_DSN:-$(amprealize_service_dsn RUN execution)}"
export AMPREALIZE_COMPLIANCE_PG_DSN="${AMPREALIZE_COMPLIANCE_PG_DSN:-$(amprealize_service_dsn COMPLIANCE compliance)}"
export AMPREALIZE_AUTH_PG_DSN="${AMPREALIZE_AUTH_PG_DSN:-$(amprealize_service_dsn AUTH auth)}"
export AMPREALIZE_TELEMETRY_PG_DSN="${AMPREALIZE_TELEMETRY_PG_DSN:-postgresql://${AMPREALIZE_PG_USER_TELEMETRY}:${AMPREALIZE_PG_PASS_TELEMETRY}@${AMPREALIZE_PG_HOST_TELEMETRY}:${AMPREALIZE_PG_PORT_TELEMETRY}/${AMPREALIZE_PG_DB_TELEMETRY}${DSN_QUERY_PARAMS}}"
export AMPREALIZE_METRICS_PG_DSN="${AMPREALIZE_METRICS_PG_DSN:-postgresql://${AMPREALIZE_PG_USER_METRICS}:${AMPREALIZE_PG_PASS_METRICS}@${AMPREALIZE_PG_HOST_METRICS}:${AMPREALIZE_PG_PORT_METRICS}/${AMPREALIZE_PG_DB_METRICS}${DSN_QUERY_PARAMS}}"
export AMPREALIZE_TRACE_ANALYSIS_PG_DSN="${AMPREALIZE_TRACE_ANALYSIS_PG_DSN:-$AMPREALIZE_BEHAVIOR_PG_DSN}"
export AMPREALIZE_AGENTAUTH_PG_DSN="${AMPREALIZE_AGENTAUTH_PG_DSN:-$AMPREALIZE_TELEMETRY_PG_DSN}"
export DATABASE__POSTGRES_URL="${DATABASE__POSTGRES_URL:-$AMPREALIZE_AGENTAUTH_PG_DSN}"
export AMPREALIZE_TASK_PG_DSN="${AMPREALIZE_TASK_PG_DSN:-$AMPREALIZE_TELEMETRY_PG_DSN}"

# Additional DSNs for services that share the modular monolith DB
export AMPREALIZE_BOARD_PG_DSN="${AMPREALIZE_BOARD_PG_DSN:-$(amprealize_service_dsn BEHAVIOR board)}"
export AMPREALIZE_ORG_PG_DSN="${AMPREALIZE_ORG_PG_DSN:-$(amprealize_service_dsn AUTH auth)}"
export AMPREALIZE_AGENT_REGISTRY_PG_DSN="${AMPREALIZE_AGENT_REGISTRY_PG_DSN:-$(amprealize_service_dsn BEHAVIOR public)}"
export AMPREALIZE_AGENT_ORCHESTRATOR_PG_DSN="${AMPREALIZE_AGENT_ORCHESTRATOR_PG_DSN:-$(amprealize_service_dsn BEHAVIOR execution)}"
export AMPREALIZE_EXECUTION_PG_DSN="${AMPREALIZE_EXECUTION_PG_DSN:-$AMPREALIZE_ACTION_PG_DSN}"
export AMPREALIZE_PG_DSN="${AMPREALIZE_PG_DSN:-$(amprealize_service_dsn BEHAVIOR public)}"

# Convenience for tools that read DATABASE_URL (only if unset)
if [ "${AMPREALIZE_TEST_PER_SERVICE_PG_DATABASES:-0}" != "1" ] && [ -n "${AMPREALIZE_ALEMBIC_DATABASE_URL:-}" ]; then
    export DATABASE_URL="${DATABASE_URL:-$AMPREALIZE_ALEMBIC_DATABASE_URL}"
fi

# ── Safety check: reject production/dev database names in test DSNs ──
# This prevents test fixtures from accidentally truncating real data.
# Blocks: unified prod names (amprealize, telemetry) AND legacy dev names
# (behavior, workflow, action, run, compliance). Test DBs should use
# _test suffix (e.g. behavior_test, amprealize_test).
PRODUCTION_DB_NAMES="amprealize|telemetry|behavior|workflow|action|run|compliance"
DSN_SAFETY_FAILED=0
for dsn_var in AMPREALIZE_BEHAVIOR_PG_DSN AMPREALIZE_WORKFLOW_PG_DSN AMPREALIZE_ACTION_PG_DSN \
               AMPREALIZE_RUN_PG_DSN AMPREALIZE_COMPLIANCE_PG_DSN AMPREALIZE_TELEMETRY_PG_DSN \
               AMPREALIZE_METRICS_PG_DSN AMPREALIZE_AUTH_PG_DSN AMPREALIZE_TRACE_ANALYSIS_PG_DSN \
               AMPREALIZE_AGENTAUTH_PG_DSN AMPREALIZE_TASK_PG_DSN; do
    dsn_value="${!dsn_var}"
    if [ -n "$dsn_value" ]; then
        # Extract database name from DSN path (after last / before ? or end)
        db_name=$(echo "$dsn_value" | sed -n 's|.*://[^/]*/\([^?]*\).*|\1|p')
        if echo "$db_name" | grep -qxE "${PRODUCTION_DB_NAMES}"; then
            print_error "SAFETY: ${dsn_var} targets production database '${db_name}'. Tests would destroy real data!"
            print_error "  DSN: ${dsn_value%%:*}://***@${dsn_value#*@}"
            print_error "  Fix: Set AMPREALIZE_PG_DB to a test-specific name (e.g. amprealize_test)"
            DSN_SAFETY_FAILED=1
        fi
    fi
done
if [ "$DSN_SAFETY_FAILED" -eq 1 ] && [ "${AMPREALIZE_TEST_SAFETY_OVERRIDE:-0}" != "1" ]; then
    print_error "Aborting. Set AMPREALIZE_TEST_SAFETY_OVERRIDE=1 to bypass (NOT recommended)."
    exit 1
fi
API_SERVER_HOST="${AMPREALIZE_API_SERVER_HOST:-localhost}"
API_SERVER_PORT="${AMPREALIZE_API_SERVER_PORT:-8000}"
API_SERVER_LOG_DIR="${AMPREALIZE_API_SERVER_LOG_DIR:-$REPO_ROOT/.tmp}"
API_SERVER_LOG_FILE="${AMPREALIZE_API_SERVER_LOG_FILE:-$API_SERVER_LOG_DIR/api_server.log}"
API_SERVER_WORKERS="${AMPREALIZE_API_SERVER_WORKERS:-1}"

if ! [[ "$API_SERVER_WORKERS" =~ ^[0-9]+$ ]] || [ "$API_SERVER_WORKERS" -lt 1 ]; then
    print_error "AMPREALIZE_API_SERVER_WORKERS must be a positive integer (received '${API_SERVER_WORKERS}')"
    exit 1
fi

ORIGINAL_API_BASE_URL="http://${API_SERVER_HOST}:${API_SERVER_PORT}"

build_default_api_server_cmd() {
    local cmd="uvicorn amprealize.api:create_app --factory --host 0.0.0.0 --port ${API_SERVER_PORT}"
    if [ "$API_SERVER_WORKERS" -gt 1 ]; then
        cmd="${cmd} --workers ${API_SERVER_WORKERS}"
    fi
    echo "$cmd"
}

DEFAULT_API_SERVER_CMD="$(build_default_api_server_cmd)"
API_SERVER_CMD="${AMPREALIZE_API_SERVER_CMD:-$DEFAULT_API_SERVER_CMD}"
API_SERVER_STARTED_BY_SCRIPT=false
API_SERVER_PID=""

# Default endpoints for non-breakeramp mode
if [ "${AMPREALIZE_TEST_PER_SERVICE_PG_DATABASES:-0}" != "1" ]; then
    DEFAULT_REQUIRED_ENDPOINTS=(
        "${AMPREALIZE_PG_HOST_BEHAVIOR}|${AMPREALIZE_PG_PORT_BEHAVIOR}|PostgreSQL (modular monolith)"
        "${AMPREALIZE_PG_HOST_TELEMETRY}|${AMPREALIZE_PG_PORT_TELEMETRY}|TimescaleDB Telemetry"
        "${AMPREALIZE_PG_HOST_METRICS}|${AMPREALIZE_PG_PORT_METRICS}|TimescaleDB Metrics"
        "${REDIS_HOST}|${REDIS_PORT}|Redis"
    )
else
    DEFAULT_REQUIRED_ENDPOINTS=(
        "${AMPREALIZE_PG_HOST_BEHAVIOR}|${AMPREALIZE_PG_PORT_BEHAVIOR}|PostgreSQL Behavior"
        "${AMPREALIZE_PG_HOST_WORKFLOW}|${AMPREALIZE_PG_PORT_WORKFLOW}|PostgreSQL Workflow"
        "${AMPREALIZE_PG_HOST_ACTION}|${AMPREALIZE_PG_PORT_ACTION}|PostgreSQL Action"
        "${AMPREALIZE_PG_HOST_RUN}|${AMPREALIZE_PG_PORT_RUN}|PostgreSQL Run"
        "${AMPREALIZE_PG_HOST_COMPLIANCE}|${AMPREALIZE_PG_PORT_COMPLIANCE}|PostgreSQL Compliance"
        "${AMPREALIZE_PG_HOST_TELEMETRY}|${AMPREALIZE_PG_PORT_TELEMETRY}|TimescaleDB Telemetry"
        "${AMPREALIZE_PG_HOST_METRICS}|${AMPREALIZE_PG_PORT_METRICS}|TimescaleDB Metrics"
        "${AMPREALIZE_PG_HOST_AUTH}|${AMPREALIZE_PG_PORT_AUTH}|PostgreSQL Auth"
        "${REDIS_HOST}|${REDIS_PORT}|Redis"
    )
fi

# Build REQUIRED_ENDPOINTS: use breakeramp config if available, otherwise use defaults
REQUIRED_ENDPOINTS=()
if [ "$AMPREALIZE_TEST_INFRA_MODE" = "breakeramp" ] && [ -f "$AMPREALIZE_BREAKERAMP_ENV_FILE" ]; then
    # Read endpoints from environments.yaml (breakeramp-driven health checks)
    while IFS= read -r line; do
        [ -n "$line" ] && REQUIRED_ENDPOINTS+=("$line")
    done < <(load_breakeramp_endpoints "$AMPREALIZE_BREAKERAMP_ENV_FILE" "$AMPREALIZE_BREAKERAMP_ENVIRONMENT" 2>/dev/null)
fi

# Fall back to defaults if no breakeramp endpoints defined
if [ ${#REQUIRED_ENDPOINTS[@]} -eq 0 ]; then
    REQUIRED_ENDPOINTS=("${DEFAULT_REQUIRED_ENDPOINTS[@]}")
    # Only require Kafka if explicitly requested (legacy mode)
    if [ "$WITH_KAFKA" = "true" ]; then
        REQUIRED_ENDPOINTS+=("localhost|${KAFKA_PORT}|Kafka")
    fi
fi

COMPOSE_FILE="$REPO_ROOT/docker-compose.test.yml"
if [ ! -f "$COMPOSE_FILE" ]; then
    COMPOSE_FILE="$REPO_ROOT/infra/docker-compose.test.yml"
fi
STAGING_COMPOSE_FILE="$REPO_ROOT/deployment/podman-compose-staging.yml"
STAGING_NETWORK_NAME="amprealize-postgres-net"
STAGING_ENDPOINTS=(
    "localhost|8000|Staging API"
    "localhost|8080|Staging NGINX"
)

if [ ! -f "$COMPOSE_FILE" ]; then
    print_error "Missing compose file docker-compose.test.yml (tried repo root and infra/)"
    exit 1
fi

# =============================================================================
# Utility Functions
# =============================================================================

is_port_ready() {
    # Use -G for connection timeout on macOS, -w on Linux
    nc -z -G 2 "$1" "$2" 2>/dev/null || nc -z -w 2 "$1" "$2" 2>/dev/null
}

check_port() {
    local host=$1 port=$2 service=$3
    if nc -z -G 2 "$host" "$port" 2>/dev/null || nc -z -w 2 "$host" "$port" 2>/dev/null; then
        print_success "$service"
        return 0
    else
        print_error "$service ${DIM}($host:$port)${NC}"
        return 1
    fi
}

find_free_port() {
    python - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
}

format_bytes() {
    local bytes="${1:-0}"
    if ! [[ "$bytes" =~ ^[0-9]+$ ]]; then
        echo "${bytes}B"
        return
    fi
    python - <<PY
value = float(${bytes:-0})
units = ["B", "KB", "MB", "GB", "TB"]
idx = 0
while value >= 1024 and idx < len(units) - 1:
    value /= 1024.0
    idx += 1
print(f"{value:.1f}{units[idx]}")
PY
}

format_duration() {
    local seconds=$1
    if [ "$seconds" -lt 60 ]; then
        echo "${seconds}s"
    elif [ "$seconds" -lt 3600 ]; then
        echo "$((seconds / 60))m $((seconds % 60))s"
    else
        echo "$((seconds / 3600))h $((seconds % 3600 / 60))m"
    fi
}

# =============================================================================
# Resource Monitoring
# =============================================================================

capture_netstat_totals() {
    if ! command -v netstat >/dev/null 2>&1; then
        return 1
    fi
    local sums
    sums=$(netstat -ib 2>/dev/null | awk 'NR>1 && NF>=11 && $10 ~ /^[0-9]+$/ && $11 ~ /^[0-9]+$/ {rx+=$10; tx+=$11} END {if (rx+tx>0) printf "%s %s", rx, tx}')
    [ -n "$sums" ] && echo "$sums"
}

report_resources() {
    local stage="$1"

    if [ "$AMPREALIZE_TEST_INFRA_MODE" != "breakeramp" ]; then
        return
    fi

    print_section "Resources ($stage)"

    # Host info
    local host_name host_desc
    host_name=$(hostname 2>/dev/null || echo "unknown")
    host_desc=$(uname -srm 2>/dev/null || echo "unknown")
    print_kv "Host" "$host_name (${host_desc})"
    print_kv "Environment" "${AMPREALIZE_BREAKERAMP_ENVIRONMENT:-n/a}"

    # Memory (macOS)
    local memory_used_mb=0 memory_total_mb=0 memory_pct=0
    if command -v vm_stat >/dev/null 2>&1 && command -v sysctl >/dev/null 2>&1; then
        local page_size total_bytes free_pages free_bytes used_bytes
        page_size=$(sysctl -n hw.pagesize 2>/dev/null || echo 4096)
        total_bytes=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
        free_pages=$(vm_stat | awk '/Pages (free|inactive)/ {gsub(".", "", $3); total+=$3} END {print total+0}' 2>/dev/null)
        free_bytes=$((free_pages * page_size))
        [ "$free_bytes" -lt 0 ] && free_bytes=0
        used_bytes=$((total_bytes - free_bytes))
        [ "$used_bytes" -lt 0 ] && used_bytes=0
        memory_used_mb=$((used_bytes / 1024 / 1024))
        memory_total_mb=$((total_bytes / 1024 / 1024))
        if [ "$memory_total_mb" -gt 0 ]; then
            memory_pct=$((memory_used_mb * 100 / memory_total_mb))
        fi
        print_kv "Memory" "$(format_bytes "$used_bytes") / $(format_bytes "$total_bytes")"
    fi

    # Podman machine specs
    local podman_cpus=0 podman_memory_mb=0 podman_disk_gb=0
    if [ -n "$AMPREALIZE_BREAKERAMP_MACHINE_NAME" ] && command -v podman >/dev/null 2>&1; then
        local inspect_output cpus memory_mb disk_gb
        if inspect_output=$(podman machine inspect "$AMPREALIZE_BREAKERAMP_MACHINE_NAME" 2>/dev/null); then
            cpus=$(printf '%s' "$inspect_output" | jq -r '.[0].VM.Resources.CPUs // empty' 2>/dev/null)
            memory_mb=$(printf '%s' "$inspect_output" | jq -r '.[0].VM.Resources.Memory // empty' 2>/dev/null)
            disk_gb=$(printf '%s' "$inspect_output" | jq -r '.[0].VM.Resources.DiskSize // empty' 2>/dev/null)
            if [ -n "$cpus" ] && [ -n "$memory_mb" ]; then
                podman_cpus=$cpus
                podman_memory_mb=$memory_mb
                [ -n "$disk_gb" ] && podman_disk_gb=$disk_gb
                print_kv "Podman VM" "${cpus} CPU / $(format_bytes $((memory_mb * 1024 * 1024)))"
            fi
        fi
    fi

    # Container stats (max CPU/mem)
    local cpu_max_num=0
    if command -v podman >/dev/null 2>&1 && command -v jq >/dev/null 2>&1; then
        local stats_json cpu_max mem_max
        stats_json=$(podman stats --no-stream --format "json" 2>/dev/null)
        if [ -n "$stats_json" ]; then
            cpu_max=$(echo "$stats_json" | jq -r 'max_by(.CPUPerc // 0) | .CPUPerc' 2>/dev/null)
            mem_max=$(echo "$stats_json" | jq -r 'max_by(.MemPerc // 0) | .MemPerc' 2>/dev/null)
            if [ -n "$cpu_max" ] && [ "$cpu_max" != "null" ]; then
                cpu_max_num=$(echo "$cpu_max" | tr -d '%' | cut -d. -f1)
                print_kv "Container Peak" "CPU ${cpu_max} / Mem ${mem_max}"
            fi
        fi
    fi

    # Disk usage from Podman
    local disk_used_mb=0 disk_total_mb=0
    if command -v podman >/dev/null 2>&1; then
        local df_output total_size
        df_output=$(podman system df --format "json" 2>/dev/null || echo "{}")
        total_size=$(echo "$df_output" | jq '[.Images[]?.Size // 0, .Containers[]?.Size // 0, .Volumes[]?.Size // 0] | add // 0' 2>/dev/null || echo "0")
        disk_used_mb=$((total_size / 1024 / 1024))
        disk_total_mb=$((podman_disk_gb * 1024))
    fi

    # Network delta
    local totals current_rx current_tx
    if totals=$(capture_netstat_totals); then
        current_rx=$(echo "$totals" | awk '{print $1}')
        current_tx=$(echo "$totals" | awk '{print $2}')
        if [ -n "$NETSTAT_LAST_RX_BYTES" ] && [ -n "$NETSTAT_LAST_TX_BYTES" ]; then
            local delta_rx=$((current_rx - NETSTAT_LAST_RX_BYTES))
            local delta_tx=$((current_tx - NETSTAT_LAST_TX_BYTES))
            [ "$delta_rx" -lt 0 ] && delta_rx=0
            [ "$delta_tx" -lt 0 ] && delta_tx=0
            print_kv "Network" "↓$(format_bytes "$delta_rx") ↑$(format_bytes "$delta_tx")"
        fi
        NETSTAT_LAST_RX_BYTES="$current_rx"
        NETSTAT_LAST_TX_BYTES="$current_tx"
    fi

    # Resource Insights (plain-English status)
    # Thresholds from env vars or defaults
    local memory_warning="${BREAKERAMP_INSIGHT_MEMORY_WARNING:-70}"
    local memory_critical="${BREAKERAMP_INSIGHT_MEMORY_CRITICAL:-90}"
    local disk_warning="${BREAKERAMP_INSIGHT_DISK_WARNING:-75}"
    local disk_critical="${BREAKERAMP_INSIGHT_DISK_CRITICAL:-90}"
    local cpu_warning="${BREAKERAMP_INSIGHT_CPU_WARNING:-70}"
    local cpu_critical="${BREAKERAMP_INSIGHT_CPU_CRITICAL:-90}"

    # Color codes
    local GREEN='\033[32m' YELLOW='\033[33m' RED='\033[31m' RESET='\033[0m'

    echo ""
    echo "  Resource Insights:"

    # Memory insight
    if [ "$memory_total_mb" -gt 0 ]; then
        local mem_color="$GREEN" mem_icon="🟢" mem_msg="healthy"
        if [ "$memory_pct" -ge "$memory_critical" ]; then
            mem_color="$RED"; mem_icon="🔴"; mem_msg="at capacity - performance may degrade"
        elif [ "$memory_pct" -ge "$memory_warning" ]; then
            mem_color="$YELLOW"; mem_icon="🟡"; mem_msg="nearing capacity"
        elif [ "$memory_pct" -lt 10 ]; then
            mem_color="$GREEN"; mem_icon="🟢"; mem_msg="plenty available"
        fi
        echo -e "    Memory: ${mem_color}${mem_icon} ${mem_msg}${RESET} (${memory_pct}%)"
    fi

    # Disk insight
    if [ "$disk_total_mb" -gt 0 ]; then
        local disk_pct=$((disk_used_mb * 100 / disk_total_mb))
        local disk_color="$GREEN" disk_icon="🟢" disk_msg="healthy"
        if [ "$disk_pct" -ge "$disk_critical" ]; then
            disk_color="$RED"; disk_icon="🔴"; disk_msg="nearly full - action required"
        elif [ "$disk_pct" -ge "$disk_warning" ]; then
            disk_color="$YELLOW"; disk_icon="🟡"; disk_msg="running low"
        elif [ "$disk_pct" -lt 30 ]; then
            disk_color="$GREEN"; disk_icon="🟢"; disk_msg="plenty available"
        fi
        echo -e "    Disk: ${disk_color}${disk_icon} ${disk_msg}${RESET} (${disk_pct}%)"
    fi

    # CPU insight (from container stats)
    if [ "$cpu_max_num" -gt 0 ] 2>/dev/null; then
        local cpu_color="$GREEN" cpu_icon="🟢" cpu_msg="healthy"
        if [ "$cpu_max_num" -ge "$cpu_critical" ]; then
            cpu_color="$RED"; cpu_icon="🔴"; cpu_msg="maxed out - system under heavy load"
        elif [ "$cpu_max_num" -ge "$cpu_warning" ]; then
            cpu_color="$YELLOW"; cpu_icon="🟡"; cpu_msg="usage elevated"
        elif [ "$cpu_max_num" -lt 20 ]; then
            cpu_color="$GREEN"; cpu_icon="🟢"; cpu_msg="barely utilized"
        fi
        echo -e "    CPU: ${cpu_color}${cpu_icon} ${cpu_msg}${RESET} (${cpu_max_num}%)"
    fi
}

# =============================================================================
# Staging Stack
# =============================================================================

requires_staging_tests() {
    local total=${#PYTEST_ARGS[@]}
    [ $total -eq 0 ] && return 1

    for ((i = 0; i < total; i++)); do
        local arg="${PYTEST_ARGS[$i]}"
        case "$arg" in
            tests/smoke|tests/smoke/*|tests/smoke/test_staging_core.py*)
                return 0 ;;
        esac
        [[ "$arg" == *"staging"* ]] && return 0
        if [[ "$arg" == "-k" || "$arg" == "-m" ]] && [ $((i + 1)) -lt $total ]; then
            [[ "${PYTEST_ARGS[$((i + 1))]}" == *"staging"* ]] && return 0
        fi
    done
    return 1
}

should_enable_staging_stack() {
    local mode
    mode="$(printf '%s' "$STAGING_STACK_MODE" | tr '[:upper:]' '[:lower:]')"
    case "$mode" in
        1|true|on|yes) return 0 ;;
        0|false|off|no) return 1 ;;
    esac
    requires_staging_tests
}

should_enable_staging_stack && START_STAGING_STACK=true

refresh_api_server_cmd() {
    [ -z "${AMPREALIZE_API_SERVER_CMD:-}" ] && API_SERVER_CMD="$(build_default_api_server_cmd)"
    ORIGINAL_API_BASE_URL="http://${API_SERVER_HOST}:${API_SERVER_PORT}"
}

set_api_env_vars() {
    local computed_url="http://${API_SERVER_HOST}:${API_SERVER_PORT}"
    if [ -z "${AMPREALIZE_GATEWAY_URL:-}" ] || [ "${AMPREALIZE_GATEWAY_URL}" = "${ORIGINAL_API_BASE_URL}" ]; then
        export AMPREALIZE_GATEWAY_URL="$computed_url"
    fi
    export AMPREALIZE_API_SERVER_PORT="$API_SERVER_PORT"
}

api_server_supports_internal_auth() {
    local base_url="http://${API_SERVER_HOST}:${API_SERVER_PORT}"
    command -v curl >/dev/null 2>&1 || return 1
    # Use --max-time to prevent hanging on slow/unresponsive servers
    curl -sf --max-time 2 "${base_url}/health" >/dev/null 2>&1 && \
    curl -sf --max-time 2 "${base_url}/api/v1/auth/providers" >/dev/null 2>&1
}

# =============================================================================
# BreakerAmp Infrastructure
# =============================================================================

load_breakeramp_env_details() {
    python - "$1" "$2" <<'PY'
import json, sys, yaml
from pathlib import Path

manifest_path, env_name = Path(sys.argv[1]), sys.argv[2]
try:
    data = yaml.safe_load(manifest_path.read_text()) or {}
except FileNotFoundError:
    print(f"Error: Manifest not found at {manifest_path}", file=sys.stderr)
    sys.exit(1)

env = (data.get("environments") or {}).get(env_name)
if not env:
    print(f"Error: Environment '{env_name}' not defined", file=sys.stderr)
    sys.exit(1)

infra = env.get("infrastructure") or {}
if not infra.get("blueprint_id"):
    print(f"Error: Missing blueprint_id for '{env_name}'", file=sys.stderr)
    sys.exit(1)

# Return environment details including active_modules for breakeramp-driven module filtering
print(json.dumps({
    "blueprint_id": infra["blueprint_id"],
    "runtime": env.get("runtime") or {},
    "active_modules": env.get("active_modules") or []
}))
PY
}

cleanup_breakeramp_machine() {
    if [ -n "$AMPREALIZE_BREAKERAMP_MANAGED_MACHINE" ]; then
        podman machine stop "$AMPREALIZE_BREAKERAMP_MANAGED_MACHINE" >/dev/null 2>&1 || true
        AMPREALIZE_BREAKERAMP_MANAGED_MACHINE=""
        AMPREALIZE_BREAKERAMP_MACHINE_NAME=""
    fi
}

ensure_breakeramp_podman_machine() {
    local provider="$1" machine_name="$2" memory_limit_mb="$3" cpu_limit="$4"
    [ "$provider" != "podman" ] || [ -z "$machine_name" ] && return

    command -v podman >/dev/null 2>&1 || { print_error "Podman CLI required"; exit 1; }
    command -v jq >/dev/null 2>&1 || { print_error "jq required"; exit 1; }

    local machine_list
    machine_list=$(podman machine list --format json 2>/dev/null) || { print_error "Cannot query podman machines"; exit 1; }

    # Stop conflicting machines
    local running_machines
    running_machines=$(echo "$machine_list" | jq -r '.[] | select(.Running == true) | .Name')
    for name in $running_machines; do
        [ "$name" != "$machine_name" ] && podman machine stop "$name" >/dev/null 2>&1 || true
    done

    # Initialize if needed
    machine_list=$(podman machine list --format json 2>/dev/null)
    if ! echo "$machine_list" | jq -e ".[] | select(.Name == \"$machine_name\")" >/dev/null; then
        print_info "Initializing Podman machine '$machine_name'..."
        local init_args=()
        [[ "$cpu_limit" =~ ^[0-9]+$ ]] && [ "$cpu_limit" -gt 0 ] && init_args+=(--cpus "$cpu_limit")
        [[ "$memory_limit_mb" =~ ^[0-9]+$ ]] && [ "$memory_limit_mb" -gt 0 ] && init_args+=(--memory "$memory_limit_mb")
        podman machine init "${init_args[@]}" "$machine_name"
    fi

    # Start if needed
    if ! echo "$machine_list" | jq -e ".[] | select(.Name == \"$machine_name\" and .Running == true)" >/dev/null; then
        print_info "Starting Podman machine '$machine_name'..."
        podman machine start "$machine_name"
    fi

    # Get socket
    local socket_path=""
    local inspect_output
    if inspect_output=$(podman machine inspect "$machine_name" 2>/dev/null); then
        socket_path=$(printf '%s' "$inspect_output" | jq -r '.[0].ConnectionInfo.PodmanSocket.Path // ""')
    fi

    if [ -n "$socket_path" ] && [ "$socket_path" != "<nil>" ]; then
        export CONTAINER_HOST="unix://$socket_path"
        export AMPREALIZE_BREAKERAMP_PODMAN_SOCKET="$socket_path"
    fi

    AMPREALIZE_BREAKERAMP_MANAGED_MACHINE="$machine_name"
}

ensure_breakeramp_infrastructure() {
    print_section "BreakerAmp Infrastructure"

    local env_file="$AMPREALIZE_BREAKERAMP_ENV_FILE"
    local env_name="$AMPREALIZE_BREAKERAMP_ENVIRONMENT"

    [ ! -f "$env_file" ] && { print_error "Manifest not found: $env_file"; exit 1; }

    export AMPREALIZE_ENV_FILE="$env_file"
    local env_details
    env_details=$(load_breakeramp_env_details "$env_file" "$env_name") || { cleanup_breakeramp_machine; exit 1; }

    local blueprint_id runtime_provider runtime_machine runtime_memory runtime_cpus active_modules_json
    blueprint_id=$(echo "$env_details" | jq -r '.blueprint_id')
    runtime_provider=$(echo "$env_details" | jq -r '.runtime.provider // ""')
    runtime_machine=$(echo "$env_details" | jq -r '.runtime.podman_machine // ""')
    runtime_memory=$(echo "$env_details" | jq -r '.runtime.memory_limit_mb // 0')
    runtime_cpus=$(echo "$env_details" | jq -r '.runtime.cpu_limit // 0')
    active_modules_json=$(echo "$env_details" | jq -c '.active_modules // []')

    AMPREALIZE_BREAKERAMP_MACHINE_NAME="$runtime_machine"
    ensure_breakeramp_podman_machine "$runtime_provider" "$runtime_machine" "$runtime_memory" "$runtime_cpus"

    print_kv "Environment" "$env_name"
    print_kv "Blueprint" "$blueprint_id"
    print_kv "Manifest" "$env_file"

    # Build module arguments from environment config (breakeramp-driven)
    local module_args=()
    local modules_display=""

    # Read active_modules from environment config
    while IFS= read -r mod; do
        [ -n "$mod" ] && module_args+=("--module" "$mod") && modules_display="${modules_display:+$modules_display, }$mod"
    done < <(echo "$active_modules_json" | jq -r '.[]' 2>/dev/null)

    # If WITH_KAFKA is set and streaming not already included, add it
    if [ "$WITH_KAFKA" = "true" ]; then
        if [[ ! " ${module_args[*]} " =~ " streaming " ]]; then
            module_args+=("--module" "streaming")
            modules_display="${modules_display:+$modules_display, }streaming (Kafka via --with-kafka)"
        fi
    fi

    # Fallback to core if no modules defined
    if [ ${#module_args[@]} -eq 0 ]; then
        module_args=("--module" "core")
        modules_display="core (default)"
    fi

    print_kv "Modules" "$modules_display"

    # Plan
    print_info "Planning..."
    local plan_output
    plan_output=$(AMPREALIZE_ENV_FILE="$env_file" amprealize breakeramp plan \
        --blueprint-id "$blueprint_id" \
        --environment "$env_name" \
        --env-file "$env_file" \
        --force-podman \
        "${module_args[@]}" \
        --output json) || { print_error "Plan failed"; cleanup_breakeramp_machine; exit 1; }

    export AMPREALIZE_BREAKERAMP_PLAN_ID=$(echo "$plan_output" | jq -r '.plan_id')
    export AMPREALIZE_BREAKERAMP_RUN_ID=$(echo "$plan_output" | jq -r '.amp_run_id')

    [ -z "$AMPREALIZE_BREAKERAMP_PLAN_ID" ] || [ "$AMPREALIZE_BREAKERAMP_PLAN_ID" = "null" ] && {
        print_error "Failed to extract plan_id"
        exit 1
    }

    local service_count estimated_boot
    service_count=$(echo "$plan_output" | jq '.signed_manifest.blueprint.services | keys | length' 2>/dev/null || echo "?")
    estimated_boot=$(echo "$plan_output" | jq -r '.environment_estimates.expected_boot_duration_s // "?"' 2>/dev/null)

    print_success "Plan created"
    print_kv "Plan ID" "$AMPREALIZE_BREAKERAMP_PLAN_ID"
    print_kv "Services" "$service_count"
    print_kv "Est. Boot" "${estimated_boot}s"

    # Apply with full resource management enabled:
    # - proactive-cleanup: Run cleanup BEFORE resource check
    # - auto-cleanup: Handle low resources during provisioning
    # - auto-cleanup-aggressive: Include images/cache in cleanup
    # - auto-resolve-stale: Remove stale/exited/dead containers
    # - auto-resolve-conflicts: Resolve port conflicts automatically
    # - stale-max-age-hours=0: Clean ALL stale containers (any age)
    print_info "Applying (with auto-resolve and proactive cleanup enabled)..."
    AMPREALIZE_ENV_FILE="$env_file" amprealize breakeramp apply \
        --plan-id "$AMPREALIZE_BREAKERAMP_PLAN_ID" \
        --env-file "$env_file" \
        --force-podman \
        --proactive-cleanup \
        --auto-cleanup \
        --auto-cleanup-aggressive \
        --auto-resolve-stale \
        --auto-resolve-conflicts \
        --stale-max-age-hours 0 \
        --allow-host-resource-warning \
        --watch || { print_error "Apply failed"; cleanup_breakeramp_machine; exit 1; }

    # Wait for all required services to be ready (including Kafka if enabled)
    print_info "Waiting for services to be ready..."
    local max_attempts=60
    local attempt=0
    while [ $attempt -lt $max_attempts ]; do
        local all_ready=true
        for endpoint in "${REQUIRED_ENDPOINTS[@]}"; do
            IFS='|' read -r host port label <<< "$endpoint"
            if ! is_port_ready "$host" "$port"; then
                all_ready=false
                if [ $((attempt % 10)) -eq 0 ]; then
                    print_warning "Waiting for $label on $host:$port..."
                fi
                break
            fi
        done

        if [ "$all_ready" = true ]; then
            break
        fi

        attempt=$((attempt + 1))
        sleep 2
    done

    if [ "$all_ready" != true ]; then
        print_error "Services not ready after ${max_attempts} attempts"
        for endpoint in "${REQUIRED_ENDPOINTS[@]}"; do
            IFS='|' read -r host port label <<< "$endpoint"
            if ! is_port_ready "$host" "$port"; then
                print_error "  - $label on $host:$port not responding"
            fi
        done
        cleanup_breakeramp_machine
        exit 1
    fi

    print_success "Infrastructure ready"
    export AMPREALIZE_TEST_INFRA_MODE="breakeramp"
}

teardown_breakeramp_infrastructure() {
    if [ "$AMPREALIZE_TEST_INFRA_MODE" = "breakeramp" ] && [ -n "${AMPREALIZE_BREAKERAMP_RUN_ID:-}" ]; then
        local env_file="$AMPREALIZE_BREAKERAMP_ENV_FILE"
        [ -f "$env_file" ] && export AMPREALIZE_ENV_FILE="$env_file"
        print_info "Tearing down infrastructure..."
        amprealize breakeramp destroy \
            --run-id "$AMPREALIZE_BREAKERAMP_RUN_ID" \
            --reason "POST_TEST" \
            --force-podman \
            --env-file "$env_file" 2>/dev/null || true
        unset AMPREALIZE_BREAKERAMP_PLAN_ID AMPREALIZE_BREAKERAMP_RUN_ID
    fi
}

# =============================================================================
# Legacy Infrastructure
# =============================================================================

# Resolve compose invocation for Podman. Prefer `podman compose` (Podman 4+); the
# `podman-compose` shim often shells out to docker-compose and breaks Podman-only
# setups (wrong network labels, volumes "in use"). Override with AMPREALIZE_COMPOSE_BIN
# (e.g. "podman compose" or "podman-compose") if needed.
pick_podman_compose_cmd() {
    PODMAN_COMPOSE_CMD=()
    if [ -n "${AMPREALIZE_COMPOSE_BIN:-}" ]; then
        # shellcheck disable=SC2206
        PODMAN_COMPOSE_CMD=($AMPREALIZE_COMPOSE_BIN)
        return 0
    fi
    if podman compose version >/dev/null 2>&1; then
        PODMAN_COMPOSE_CMD=(podman compose)
        return 0
    fi
    if command -v podman-compose >/dev/null 2>&1; then
        PODMAN_COMPOSE_CMD=(podman-compose)
        return 0
    fi
    return 1
}

# When using `podman compose`, Podman 5+ prefers docker-compose if both are installed.
# That breaks rootless Podman networks on macOS. Prefer podman-compose as the provider.
apply_podman_compose_provider_for_podman_socket() {
    [ -n "${PODMAN_COMPOSE_PROVIDER:-}" ] && return 0
    [ ${#PODMAN_COMPOSE_CMD[@]} -ge 2 ] || return 0
    [ "${PODMAN_COMPOSE_CMD[0]}" = "podman" ] && [ "${PODMAN_COMPOSE_CMD[1]}" = "compose" ] || return 0
    local pc
    pc=$(command -v podman-compose 2>/dev/null) || return 0
    export PODMAN_COMPOSE_PROVIDER="$pc"
}

ensure_test_infrastructure() {
    if [ "$AMPREALIZE_TEST_INFRA_MODE" = "breakeramp" ]; then
        ensure_breakeramp_infrastructure
        return
    fi

    print_section "Infrastructure"

    local missing_services=()
    for endpoint in "${REQUIRED_ENDPOINTS[@]}"; do
        IFS='|' read -r host port label <<< "$endpoint"
        is_port_ready "$host" "$port" || missing_services+=("$label")
    done

    if [ ${#missing_services[@]} -eq 0 ]; then
        print_success "All services reachable"
        return
    fi

    print_warning "Starting missing services..."

    command -v podman >/dev/null 2>&1 || { print_error "Podman not installed"; exit 1; }
    podman info >/dev/null 2>&1 || {
        command -v podman-machine >/dev/null 2>&1 && podman machine start >/dev/null || {
            print_error "Podman machine not running"
            print_info "Start with: ${DIM}podman machine start${NC}"
            exit 1
        }
    }

    pick_podman_compose_cmd || {
        print_error "Podman Compose required (try: podman compose version)"
        exit 1
    }
    apply_podman_compose_provider_for_podman_socket
    local -a compose_cmd=("${PODMAN_COMPOSE_CMD[@]}")

    "${compose_cmd[@]}" -f "$COMPOSE_FILE" up -d >/dev/null

    local attempt=0 max_attempts=30
    while [ $attempt -lt $max_attempts ]; do
        local ready=true
        for endpoint in "${REQUIRED_ENDPOINTS[@]}"; do
            IFS='|' read -r host port _ <<< "$endpoint"
            is_port_ready "$host" "$port" || { ready=false; break; }
        done
        [ "$ready" = true ] && { print_success "Infrastructure ready"; return; }
        attempt=$((attempt + 1))
        sleep 2
    done

    print_error "Infrastructure failed to start"
    exit 1
}

ensure_staging_stack() {
    [ "$START_STAGING_STACK" != true ] && return
    [ "$STAGING_STACK_ACTIVE" = true ] && return
    if [ ! -f "$STAGING_COMPOSE_FILE" ]; then
        print_warning "Missing staging compose at $STAGING_COMPOSE_FILE — skipping staging stack (smoke tests may skip)"
        START_STAGING_STACK=false
        return 0
    fi

    print_section "Staging Stack"

    command -v podman >/dev/null 2>&1 || { print_error "Podman required"; exit 1; }
    podman info >/dev/null 2>&1 || podman machine start >/dev/null
    podman network exists "$STAGING_NETWORK_NAME" >/dev/null 2>&1 || podman network create "$STAGING_NETWORK_NAME" >/dev/null

    pick_podman_compose_cmd || {
        print_error "Podman Compose required (try: podman compose version)"
        exit 1
    }
    apply_podman_compose_provider_for_podman_socket
    local -a compose_cmd=("${PODMAN_COMPOSE_CMD[@]}")

    export AMPREALIZE_STAGING_UPSTREAM_HOST="${AMPREALIZE_STAGING_UPSTREAM_HOST:-amprealize-api-staging}"
    export AMPREALIZE_STAGING_UPSTREAM_PORT="${AMPREALIZE_STAGING_UPSTREAM_PORT:-8000}"

    local staging_ready=true
    for endpoint in "${STAGING_ENDPOINTS[@]}"; do
        IFS='|' read -r host port _ <<< "$endpoint"
        is_port_ready "$host" "$port" || { staging_ready=false; break; }
    done

    if [ "$staging_ready" = false ]; then
        print_info "Starting staging containers..."
        "${compose_cmd[@]}" -f "$STAGING_COMPOSE_FILE" up -d >/dev/null

        local attempt=0 max_attempts=60
        while [ $attempt -lt $max_attempts ]; do
            local ready=true
            for endpoint in "${STAGING_ENDPOINTS[@]}"; do
                IFS='|' read -r host port _ <<< "$endpoint"
                is_port_ready "$host" "$port" || { ready=false; break; }
            done
            [ "$ready" = true ] && { staging_ready=true; break; }
            attempt=$((attempt + 1))
            sleep 2
        done
        [ "$staging_ready" = false ] && { print_error "Staging stack failed to start"; exit 1; }
    fi

    STAGING_STACK_ACTIVE=true
    # Gateway is the primary entry point (port 8080), API is internal (port 8000)
    export STAGING_GATEWAY_URL="${STAGING_GATEWAY_URL:-http://localhost:8080}"
    export STAGING_API_URL="${STAGING_API_URL:-http://localhost:8000}"  # Internal API

    if [ "$STAGING_PORT_REASSIGNED" = false ]; then
        local fallback_port
        fallback_port="$(find_free_port)"
        if [ -n "$fallback_port" ]; then
            API_SERVER_PORT="$fallback_port"
            STAGING_PORT_REASSIGNED=true
            refresh_api_server_cmd
        fi
    fi

    print_success "Staging stack ready"
}

# =============================================================================
# Schema Migrations
# =============================================================================

ensure_schema() {
    local name="$1" table="$2" dsn_var="$3" migration_script="$4"

    local table_exists=""
    if command -v psql >/dev/null 2>&1; then
        local dsn="${!dsn_var}"
        table_exists=$(psql "$dsn" -Atqc "SELECT to_regclass('public.${table}');" 2>/dev/null || echo "")
    fi

    if [[ "$table_exists" == "$table" ]]; then
        return 0
    fi

    # Run migration - suppress output but allow failures (migrations may have been applied)
    python "$migration_script" --dsn "${!dsn_var}" >/dev/null 2>&1 || true
    return 0
}

ensure_all_schemas() {
    print_section "Database Schemas"

    # Helper to check if a service is in required endpoints
    is_service_required() {
        local port="$1"
        for endpoint in "${REQUIRED_ENDPOINTS[@]}"; do
            IFS='|' read -r host p label <<< "$endpoint"
            [ "$p" = "$port" ] && return 0
        done
        return 1
    }

    # Telemetry schema (port 6432 in default compose)
    if is_service_required "$AMPREALIZE_PG_PORT_TELEMETRY"; then
        ensure_schema "Telemetry" "telemetry_events" "AMPREALIZE_TELEMETRY_PG_DSN" "$REPO_ROOT/scripts/run_postgres_telemetry_migration.py"
        # Base telemetry warehouse (001)
        python "$REPO_ROOT/scripts/run_postgres_telemetry_migration.py" --dsn "$AMPREALIZE_TELEMETRY_PG_DSN" --migration "$REPO_ROOT/schema/migrations/001_create_telemetry_warehouse.sql" >/dev/null 2>&1 || true
    fi

    # Metrics schema (port 6439)
    if is_service_required "$AMPREALIZE_PG_PORT_METRICS"; then
        ensure_schema "Metrics" "metrics_snapshots" "AMPREALIZE_METRICS_PG_DSN" "$REPO_ROOT/scripts/run_postgres_metrics_migration.py"
    fi

    # Modular monolith domains: single Alembic upgrade (auth, board, behavior, execution, workflow, …)
    if is_service_required "$AMPREALIZE_PG_PORT_BEHAVIOR"; then
        if [ "${AMPREALIZE_TEST_PER_SERVICE_PG_DATABASES:-0}" != "1" ]; then
            print_info "Applying Alembic migrations (modular monolith Postgres)…"
            if ! DATABASE_URL="$AMPREALIZE_ALEMBIC_DATABASE_URL" python "$REPO_ROOT/scripts/run_alembic_migrations.py"; then
                print_error "Alembic upgrade failed"
                exit 1
            fi
            export AMPREALIZE_ALEMBIC_SCHEMA_READY=1
        else
            # Legacy: separate Postgres per service — raw SQL migration scripts when present
            local migrations=(
                "$REPO_ROOT/schema/migrations/002_create_behavior_service.sql"
                "$REPO_ROOT/schema/migrations/015_add_behavior_namespace.sql"
            )
            for migration in "${migrations[@]}"; do
                [ -f "$migration" ] && python "$REPO_ROOT/scripts/run_postgres_behavior_migration.py" --migration "$migration" >/dev/null 2>&1
            done
            python "$REPO_ROOT/scripts/run_postgres_trace_migration.py" --dsn "$AMPREALIZE_TRACE_ANALYSIS_PG_DSN" >/dev/null 2>&1 || true
        fi
    fi

    if [ "${AMPREALIZE_TEST_PER_SERVICE_PG_DATABASES:-0}" = "1" ]; then
        if is_service_required "$AMPREALIZE_PG_PORT_WORKFLOW"; then
            local workflow_migrations=(
                "$REPO_ROOT/schema/migrations/003_create_workflow_service.sql"
                "$REPO_ROOT/schema/migrations/009_refactor_workflow_schema.sql"
            )
            for migration in "${workflow_migrations[@]}"; do
                [ -f "$migration" ] && python "$REPO_ROOT/scripts/run_postgres_workflow_migration.py" --migration "$migration" >/dev/null 2>&1 || true
            done
        fi
        if is_service_required "$AMPREALIZE_PG_PORT_ACTION"; then
            python "$REPO_ROOT/scripts/run_postgres_action_migration.py" >/dev/null 2>&1 || true
        fi
        if is_service_required "$AMPREALIZE_PG_PORT_RUN"; then
            python "$REPO_ROOT/scripts/run_postgres_run_migration.py" >/dev/null 2>&1 || true
        fi
        if is_service_required "$AMPREALIZE_PG_PORT_COMPLIANCE"; then
            python "$REPO_ROOT/scripts/run_postgres_compliance_migration.py" >/dev/null 2>&1 || true
        fi
        if is_service_required "$AMPREALIZE_PG_PORT_AUTH"; then
            python "$REPO_ROOT/scripts/run_postgres_auth_migration.py" >/dev/null 2>&1 || true
        fi
    fi

    print_success "Schemas ready"
}

# =============================================================================
# API Server
# =============================================================================

start_api_server() {
    if [ "${AMPREALIZE_SKIP_API_SERVER:-0}" = "1" ]; then
        set_api_env_vars
        return
    fi

    if is_port_ready "$API_SERVER_HOST" "$API_SERVER_PORT"; then
        if api_server_supports_internal_auth; then
            print_success "API server ready (${API_SERVER_HOST}:${API_SERVER_PORT})"
            set_api_env_vars
            return
        fi

        local fallback_port
        fallback_port="$(find_free_port)"
        [ -z "$fallback_port" ] && { print_error "No free port for API server"; exit 1; }
        API_SERVER_PORT="$fallback_port"
        refresh_api_server_cmd
    fi

    print_info "Starting API server on port ${API_SERVER_PORT}..."
    mkdir -p "$API_SERVER_LOG_DIR"
    nohup bash -c "$API_SERVER_CMD" > "$API_SERVER_LOG_FILE" 2>&1 &
    API_SERVER_PID=$!
    API_SERVER_STARTED_BY_SCRIPT=true

    local attempt=0 max_attempts=60
    while [ $attempt -lt $max_attempts ]; do
        if is_port_ready "$API_SERVER_HOST" "$API_SERVER_PORT"; then
            print_success "API server ready"
            set_api_env_vars
            return
        fi
        kill -0 "$API_SERVER_PID" >/dev/null 2>&1 || {
            print_error "API server exited unexpectedly"
            tail -n 20 "$API_SERVER_LOG_FILE" 2>/dev/null || true
            exit 1
        }
        attempt=$((attempt + 1))
        sleep 0.5
    done

    print_error "API server timeout"
    exit 1
}

stop_api_server() {
    if [ "$API_SERVER_STARTED_BY_SCRIPT" = true ] && [ -n "$API_SERVER_PID" ]; then
        kill "$API_SERVER_PID" >/dev/null 2>&1 || true
        wait "$API_SERVER_PID" >/dev/null 2>&1 || true
    fi
}

cleanup() {
    local exit_code="${1:-0}"
    stop_api_server
    [ "$AMPREALIZE_TEST_INFRA_MODE" = "breakeramp" ] && teardown_breakeramp_infrastructure
    cleanup_breakeramp_machine
}

# Handle signals properly - INT/TERM should exit after cleanup
handle_signal() {
    echo ""
    print_warning "Interrupted - cleaning up..."
    cleanup
    exit 130  # Standard exit code for SIGINT
}

trap cleanup EXIT
trap handle_signal INT TERM

# =============================================================================
# Main Execution
# =============================================================================

print_header "Amprealize Test Runner"

# Show configuration
print_kv "Mode" "$AMPREALIZE_TEST_INFRA_MODE"
[ "$AMPREALIZE_TEST_INFRA_MODE" = "breakeramp" ] && print_kv "Environment" "$AMPREALIZE_BREAKERAMP_ENVIRONMENT"
print_kv "Workers" "${PARALLEL_WORKERS:-serial}"
print_kv "Tests" "${PYTEST_ARGS[*]}"

# Setup infrastructure
ensure_test_infrastructure

# Verify services
print_section "Service Health"
all_healthy=true
for endpoint in "${REQUIRED_ENDPOINTS[@]}"; do
    IFS='|' read -r host port label <<< "$endpoint"
    check_port "$host" "$port" "$label" || all_healthy=false
done

if [ "$all_healthy" = false ]; then
    echo ""
    print_error "Some services unavailable"
    print_info "Start containers: ${DIM}podman compose -f infra/docker-compose.test.yml up -d${NC}"
    exit 1
fi

# Schemas & staging
ensure_all_schemas
# Optional staging stack when smoke paths are selected and compose file exists
# (tests/smoke/* skips in pytest when ports are down — see tests/smoke/conftest.py)
ensure_staging_stack

# Resource snapshot
report_resources "pre-tests"

# Check only mode
if [ "$CHECK_ONLY" = true ]; then
    echo ""
    print_success "Environment ready"
    exit 0
fi

# Clean up stale API server processes before starting
cleanup_stale_api_server() {
    local port="${API_SERVER_PORT:-8000}"
    local pid
    pid=$(lsof -i ":$port" -t -sTCP:LISTEN 2>/dev/null | head -1) || true

    if [ -n "$pid" ]; then
        local cmd
        cmd=$(ps -p "$pid" -o comm= 2>/dev/null) || cmd="unknown"

        # Only kill amprealize-related processes (python, uvicorn, etc.)
        case "$cmd" in
            python*|uvicorn*|gunicorn*|amprealize*)
                print_info "Killing stale process on port $port (PID: $pid, cmd: $cmd)..."
                kill "$pid" 2>/dev/null || true
                sleep 0.5
                # Force kill if still alive
                kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
                print_success "Cleaned up stale process"
                ;;
            *)
                print_warning "Port $port in use by: $cmd (PID: $pid) - skipping cleanup"
                ;;
        esac
    fi
}

# Start API server
print_section "API Server"
cleanup_stale_api_server
start_api_server

# =============================================================================
# Test Execution
# =============================================================================

print_header "Running Tests"

PYTEST_CMD="pytest"
[ "$PARALLEL_WORKERS" -gt 0 ] && PYTEST_CMD="$PYTEST_CMD -n $PARALLEL_WORKERS --dist=loadfile"
PYTEST_CMD="$PYTEST_CMD -v ${PYTEST_ARGS[*]}"

echo ""
echo -e "${DIM}$PYTEST_CMD${NC}"
echo ""

start_time=$(date +%s)

set +e
eval "$PYTEST_CMD"
test_exit_code=$?
set -e

end_time=$(date +%s)
duration=$((end_time - start_time))

# =============================================================================
# Results
# =============================================================================

print_header "Results"

print_kv "Duration" "$(format_duration $duration)"

if [ $test_exit_code -eq 0 ]; then
    print_success "All tests passed"
else
    print_error "Tests failed (exit code: $test_exit_code)"
    echo ""
    print_info "Troubleshooting:"
    print_info "  ${DIM}podman logs <container>${NC}"
    print_info "  ${DIM}pytest -v <test>::<name>${NC}"
fi

report_resources "post-tests"

exit $test_exit_code
