#!/bin/bash
# MinIO WORM Storage Setup Script
#
# Provisions MinIO bucket with Object Lock enabled for audit log archival.
# Required for local development/testing of Audit Log WORM Storage feature.
#
# Behaviors referenced:
# - behavior_use_breakeramp_for_environments: Container orchestration
# - behavior_lock_down_security_surface: WORM storage configuration
# - behavior_externalize_configuration: Environment-based configuration
#
# Prerequisites:
# - Docker/Podman running
# - mc (MinIO Client) installed: brew install minio/stable/mc
#
# Usage:
#   ./scripts/setup_minio_worm.sh [--cleanup]

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────────────

MINIO_CONTAINER_NAME="${MINIO_CONTAINER_NAME:-amprealize-minio-worm}"
MINIO_PORT="${MINIO_PORT:-9000}"
MINIO_CONSOLE_PORT="${MINIO_CONSOLE_PORT:-9001}"
MINIO_ROOT_USER="${MINIO_ROOT_USER:-amprealize}"
MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-amprealize-dev-secret}"
MINIO_BUCKET="${MINIO_BUCKET:-amprealize-audit}"
MINIO_DATA_DIR="${MINIO_DATA_DIR:-${HOME}/.amprealize/minio-worm}"
MINIO_ALIAS="${MINIO_ALIAS:-amprealize-worm}"

# Object Lock configuration
RETENTION_MODE="${RETENTION_MODE:-GOVERNANCE}"  # GOVERNANCE for dev (can be overridden), COMPLIANCE for prod
RETENTION_DAYS="${RETENTION_DAYS:-30}"          # 30 days for dev, 2555 (7 years) for prod

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# ── Helper Functions ───────────────────────────────────────────────────────────

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check for container runtime
    if command -v podman &> /dev/null; then
        CONTAINER_CMD="podman"
    elif command -v docker &> /dev/null; then
        CONTAINER_CMD="docker"
    else
        log_error "Neither Docker nor Podman found. Please install one."
        exit 1
    fi
    log_info "Using container runtime: $CONTAINER_CMD"

    # Check for MinIO Client (mc)
    if ! command -v mc &> /dev/null; then
        log_error "MinIO Client (mc) not found."
        log_info "Install with: brew install minio/stable/mc"
        log_info "Or: https://min.io/docs/minio/linux/reference/minio-mc.html"
        exit 1
    fi
    log_info "MinIO Client found: $(which mc)"
}

cleanup() {
    log_info "Cleaning up existing MinIO WORM container..."

    # Stop and remove container
    if $CONTAINER_CMD ps -a --format '{{.Names}}' | grep -q "^${MINIO_CONTAINER_NAME}$"; then
        $CONTAINER_CMD stop "$MINIO_CONTAINER_NAME" 2>/dev/null || true
        $CONTAINER_CMD rm "$MINIO_CONTAINER_NAME" 2>/dev/null || true
        log_info "Container '$MINIO_CONTAINER_NAME' removed"
    else
        log_info "Container '$MINIO_CONTAINER_NAME' not found, nothing to clean"
    fi

    # Remove mc alias
    mc alias rm "$MINIO_ALIAS" 2>/dev/null || true

    # Optionally remove data directory
    if [[ "${REMOVE_DATA:-false}" == "true" ]] && [[ -d "$MINIO_DATA_DIR" ]]; then
        log_warn "Removing data directory: $MINIO_DATA_DIR"
        rm -rf "$MINIO_DATA_DIR"
    fi
}

start_minio() {
    log_info "Starting MinIO container with Object Lock support..."

    # Create data directory if it doesn't exist
    mkdir -p "$MINIO_DATA_DIR"

    # Start MinIO with Object Lock enabled
    # Note: Object Lock requires versioning, which is enabled by default in MinIO
    $CONTAINER_CMD run -d \
        --name "$MINIO_CONTAINER_NAME" \
        -p "${MINIO_PORT}:9000" \
        -p "${MINIO_CONSOLE_PORT}:9001" \
        -e "MINIO_ROOT_USER=${MINIO_ROOT_USER}" \
        -e "MINIO_ROOT_PASSWORD=${MINIO_ROOT_PASSWORD}" \
        -v "${MINIO_DATA_DIR}:/data:Z" \
        quay.io/minio/minio:latest server /data --console-address ":9001"

    log_info "MinIO container started: $MINIO_CONTAINER_NAME"

    # Wait for MinIO to be ready
    log_info "Waiting for MinIO to be ready..."
    sleep 5

    for i in {1..30}; do
        if curl -sf "http://localhost:${MINIO_PORT}/minio/health/live" >/dev/null 2>&1; then
            log_info "MinIO is ready!"
            break
        fi
        if [[ $i -eq 30 ]]; then
            log_error "MinIO did not become ready in time"
            exit 1
        fi
        sleep 1
    done
}

configure_mc() {
    log_info "Configuring MinIO Client alias..."

    # Remove existing alias if present
    mc alias rm "$MINIO_ALIAS" 2>/dev/null || true

    # Add new alias
    mc alias set "$MINIO_ALIAS" \
        "http://localhost:${MINIO_PORT}" \
        "$MINIO_ROOT_USER" \
        "$MINIO_ROOT_PASSWORD"

    log_info "MinIO Client alias configured: $MINIO_ALIAS"
}

create_bucket_with_object_lock() {
    log_info "Creating bucket with Object Lock enabled..."

    # Check if bucket exists
    if mc ls "${MINIO_ALIAS}/${MINIO_BUCKET}" &>/dev/null; then
        log_warn "Bucket '$MINIO_BUCKET' already exists"
    else
        # Create bucket with Object Lock enabled
        # The --with-lock flag enables Object Lock (versioning is automatic)
        mc mb "${MINIO_ALIAS}/${MINIO_BUCKET}" --with-lock
        log_info "Bucket created: $MINIO_BUCKET (Object Lock enabled)"
    fi

    # Set default retention policy
    log_info "Setting default retention policy: ${RETENTION_MODE} for ${RETENTION_DAYS} days..."
    mc retention set --default "${RETENTION_MODE}" "${RETENTION_DAYS}d" "${MINIO_ALIAS}/${MINIO_BUCKET}"

    # Verify configuration
    log_info "Verifying Object Lock configuration..."
    mc retention info "${MINIO_ALIAS}/${MINIO_BUCKET}"
}

print_env_config() {
    log_info "MinIO WORM storage is ready!"
    echo ""
    echo "=========================================="
    echo "MinIO WORM Storage Configuration"
    echo "=========================================="
    echo ""
    echo "Add these to your .env file or environment:"
    echo ""
    echo "  # Audit Log WORM Storage"
    echo "  AMPREALIZE_AUDIT_AUDIT_BUCKET=${MINIO_BUCKET}"
    echo "  AMPREALIZE_AUDIT_AUDIT_ENDPOINT=http://localhost:${MINIO_PORT}"
    echo "  AMPREALIZE_AUDIT_OBJECT_LOCK_MODE=${RETENTION_MODE}"
    echo "  AMPREALIZE_AUDIT_RETENTION_DAYS=${RETENTION_DAYS}"
    echo ""
    echo "  # AWS/S3 Credentials (for MinIO)"
    echo "  AWS_ACCESS_KEY_ID=${MINIO_ROOT_USER}"
    echo "  AWS_SECRET_ACCESS_KEY=${MINIO_ROOT_PASSWORD}"
    echo "  AWS_REGION=us-east-1"
    echo ""
    echo "Endpoints:"
    echo "  - S3 API:      http://localhost:${MINIO_PORT}"
    echo "  - Web Console: http://localhost:${MINIO_CONSOLE_PORT}"
    echo "    User: ${MINIO_ROOT_USER}"
    echo "    Pass: ${MINIO_ROOT_PASSWORD}"
    echo ""
    echo "MinIO Client Commands:"
    echo "  mc ls ${MINIO_ALIAS}/${MINIO_BUCKET}    # List objects"
    echo "  mc retention info ${MINIO_ALIAS}/${MINIO_BUCKET}/KEY  # Check retention"
    echo ""
    echo "=========================================="
}

test_object_lock() {
    log_info "Testing Object Lock functionality..."

    # Create test object
    local TEST_KEY="test-worm-$(date +%s).txt"
    echo "Test WORM content $(date)" | mc pipe "${MINIO_ALIAS}/${MINIO_BUCKET}/${TEST_KEY}"

    # Verify retention was applied
    if mc retention info "${MINIO_ALIAS}/${MINIO_BUCKET}/${TEST_KEY}" 2>/dev/null | grep -q "Mode:"; then
        log_info "✓ Object Lock retention applied to test object"
    else
        log_warn "Object Lock retention may not be applied automatically"
    fi

    # Try to delete (should fail in COMPLIANCE mode, may succeed in GOVERNANCE)
    if mc rm "${MINIO_ALIAS}/${MINIO_BUCKET}/${TEST_KEY}" 2>&1 | grep -q "Object is WORM protected"; then
        log_info "✓ WORM protection verified - cannot delete protected object"
    else
        if [[ "$RETENTION_MODE" == "GOVERNANCE" ]]; then
            log_info "Object deleted (GOVERNANCE mode allows deletion with proper permissions)"
        else
            log_warn "Unexpected deletion result - verify Object Lock configuration"
        fi
    fi
}

# ── Main Script ────────────────────────────────────────────────────────────────

main() {
    echo "=========================================="
    echo "Amprealize MinIO WORM Storage Setup"
    echo "=========================================="
    echo ""

    # Handle --cleanup flag
    if [[ "${1:-}" == "--cleanup" ]]; then
        check_prerequisites
        cleanup
        log_info "Cleanup complete"
        exit 0
    fi

    # Handle --cleanup-all flag (including data)
    if [[ "${1:-}" == "--cleanup-all" ]]; then
        check_prerequisites
        REMOVE_DATA=true cleanup
        log_info "Full cleanup complete"
        exit 0
    fi

    # Handle --test flag
    if [[ "${1:-}" == "--test" ]]; then
        check_prerequisites
        configure_mc
        test_object_lock
        exit 0
    fi

    # Normal setup
    check_prerequisites
    cleanup
    start_minio
    configure_mc
    create_bucket_with_object_lock
    test_object_lock
    print_env_config
}

main "$@"
