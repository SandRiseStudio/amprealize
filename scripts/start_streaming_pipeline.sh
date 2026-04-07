#!/usr/bin/env bash
# Streaming Pipeline Deployment Script
#
# Usage:
#   ./scripts/start_streaming_pipeline.sh         # Start all services
#   ./scripts/start_streaming_pipeline.sh stop    # Stop all services
#   ./scripts/start_streaming_pipeline.sh restart # Restart all services
#   ./scripts/start_streaming_pipeline.sh status  # Check service status
#
# Dependencies:
#   - Podman or Docker installed
#   - podman-compose or docker-compose installed
#   - postgres-telemetry container running (from docker-compose.telemetry.yml)
#
# Runtime Detection:
#   - Automatically detects Podman (preferred) or Docker
#   - Uses podman-compose or docker-compose accordingly
#   - Override via: CONTAINER_RUNTIME=podman COMPOSE_TOOL=podman-compose
#
# References:
#   - docs/PODMAN_DEPLOYMENT.md
#   - docs/STREAMING_PIPELINE_ARCHITECTURE.md
#   - docker-compose.streaming.yml

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging helpers
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STREAMING_COMPOSE="$PROJECT_ROOT/docker-compose.streaming.yml"
TELEMETRY_COMPOSE="$PROJECT_ROOT/docker-compose.telemetry.yml"

# ============================================================================
# Container Runtime Detection (Podman or Docker)
# ============================================================================

detect_container_runtime() {
    # Allow environment override
    if [[ -n "${CONTAINER_RUNTIME:-}" ]]; then
        echo "${CONTAINER_RUNTIME}"
        return
    fi

    # Check for Podman first (preferred for amprealize)
    if command -v podman &> /dev/null; then
        echo "podman"
    elif command -v docker &> /dev/null; then
        echo "docker"
    else
        log_error "Neither Podman nor Docker found. Install one of them:"
        log_error "  Podman: https://podman.io/getting-started/installation"
        log_error "  Docker: https://docs.docker.com/get-docker/"
        exit 1
    fi
}

detect_compose_tool() {
    local runtime="$1"

    # Allow environment override
    if [[ -n "${COMPOSE_TOOL:-}" ]]; then
        echo "${COMPOSE_TOOL}"
        return
    fi

    if [[ "${runtime}" == "podman" ]]; then
        if command -v podman-compose &> /dev/null; then
            echo "podman-compose"
        elif command -v docker-compose &> /dev/null; then
            # Podman can use docker-compose with socket compatibility
            echo "docker-compose"
        else
            log_error "Neither podman-compose nor docker-compose found"
            log_error "Install podman-compose: pip install podman-compose"
            exit 1
        fi
    else
        if command -v docker-compose &> /dev/null; then
            echo "docker-compose"
        else
            log_error "docker-compose not found"
            log_error "Install: https://docs.docker.com/compose/install/"
            exit 1
        fi
    fi
}

# Detect runtime at script start
CONTAINER_RUNTIME=$(detect_container_runtime)
COMPOSE_TOOL=$(detect_compose_tool "${CONTAINER_RUNTIME}")

export CONTAINER_RUNTIME
export COMPOSE_TOOL

log_info "Container runtime: ${CONTAINER_RUNTIME}"
log_info "Compose tool: ${COMPOSE_TOOL}"

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."

    # Runtime already detected at script start
    log_success "Using ${CONTAINER_RUNTIME} runtime with ${COMPOSE_TOOL}"

    # Check if postgres-telemetry is running
    if ! ${CONTAINER_RUNTIME} ps | grep -q "postgres-telemetry"; then
        log_warning "postgres-telemetry container is not running."
        log_warning "Starting TimescaleDB from docker-compose.telemetry.yml..."
        ${COMPOSE_TOOL} -f "$TELEMETRY_COMPOSE" up -d postgres-telemetry

        # Wait for postgres to be ready
        log_info "Waiting for TimescaleDB to be ready..."
        sleep 10
    fi

    log_success "Prerequisites check complete!"
}

# Start streaming pipeline
start_pipeline() {
    log_info "Starting streaming pipeline..."

    check_prerequisites

    # Start services
    log_info "Starting Zookeeper cluster..."
    ${COMPOSE_TOOL} -f "$STREAMING_COMPOSE" up -d zookeeper-1 zookeeper-2 zookeeper-3

    log_info "Waiting for Zookeeper cluster to be ready..."
    sleep 15

    log_info "Starting Kafka cluster (3 brokers)..."
    ${COMPOSE_TOOL} -f "$STREAMING_COMPOSE" up -d kafka-1 kafka-2 kafka-3

    log_info "Waiting for Kafka cluster to be ready..."
    sleep 30

    log_info "Initializing Kafka topics..."
    ${COMPOSE_TOOL} -f "$STREAMING_COMPOSE" up kafka-init

    log_info "Starting Schema Registry..."
    ${COMPOSE_TOOL} -f "$STREAMING_COMPOSE" up -d schema-registry

    log_info "Waiting for Schema Registry to be ready..."
    sleep 10

    log_info "Starting Flink cluster (1 job manager, 3 task managers)..."
    ${COMPOSE_TOOL} -f "$STREAMING_COMPOSE" up -d flink-jobmanager
    sleep 10
    ${COMPOSE_TOOL} -f "$STREAMING_COMPOSE" up -d flink-taskmanager-1 flink-taskmanager-2 flink-taskmanager-3

    log_info "Waiting for Flink cluster to be ready..."
    sleep 20

    log_success "Streaming pipeline started successfully!"
    echo ""
    log_info "Service URLs:"
    echo "  - Flink UI:        http://localhost:8082"
    echo "  - Schema Registry: http://localhost:8081"
    echo "  - Kafka brokers:   localhost:19092, localhost:19093, localhost:19094"
    echo "  - Metabase:        http://localhost:3000 (start with docker-compose.analytics-dashboard.yml)"
    echo ""
    log_info "To deploy Flink jobs, run:"
    echo "  ${CONTAINER_RUNTIME} exec -it amprealize-flink-jobmanager flink run /opt/flink/jobs/telemetry_kpi_job.py"
    echo ""
    log_info "To view logs:"
    echo "  ${COMPOSE_TOOL} -f docker-compose.streaming.yml logs -f <service>"
}

# Stop streaming pipeline
stop_pipeline() {
    log_info "Stopping streaming pipeline..."

    ${COMPOSE_TOOL} -f "$STREAMING_COMPOSE" down

    log_success "Streaming pipeline stopped!"
}

# Restart streaming pipeline
restart_pipeline() {
    log_info "Restarting streaming pipeline..."

    stop_pipeline
    sleep 5
    start_pipeline
}

# Check service status
check_status() {
    log_info "Checking streaming pipeline status..."
    echo ""

    # Check Zookeeper
    log_info "Zookeeper Status:"
    for i in 1 2 3; do
        if ${CONTAINER_RUNTIME} ps | grep -q "amprealize-zookeeper-$i"; then
            log_success "  zookeeper-$i: Running"
        else
            log_error "  zookeeper-$i: Stopped"
        fi
    done
    echo ""

    # Check Kafka
    log_info "Kafka Status:"
    for i in 1 2 3; do
        if ${CONTAINER_RUNTIME} ps | grep -q "amprealize-kafka-$i"; then
            log_success "  kafka-$i: Running"
        else
            log_error "  kafka-$i: Stopped"
        fi
    done
    echo ""

    # Check Schema Registry
    log_info "Schema Registry Status:"
    if ${CONTAINER_RUNTIME} ps | grep -q "amprealize-schema-registry"; then
        log_success "  schema-registry: Running"
    else
        log_error "  schema-registry: Stopped"
    fi
    echo ""

    # Check Flink
    log_info "Flink Status:"
    if ${CONTAINER_RUNTIME} ps | grep -q "amprealize-flink-jobmanager"; then
        log_success "  flink-jobmanager: Running"
    else
        log_error "  flink-jobmanager: Stopped"
    fi

    for i in 1 2 3; do
        if ${CONTAINER_RUNTIME} ps | grep -q "amprealize-flink-taskmanager-$i"; then
            log_success "  flink-taskmanager-$i: Running"
        else
            log_error "  flink-taskmanager-$i: Stopped"
        fi
    done
    echo ""

    # Check TimescaleDB
    log_info "TimescaleDB Status:"
    if ${CONTAINER_RUNTIME} ps | grep -q "postgres-telemetry"; then
        log_success "  postgres-telemetry: Running"
    else
        log_error "  postgres-telemetry: Stopped (required for streaming pipeline)"
    fi
    echo ""

    # Display resource usage
    log_info "Resource Usage:"
    ${CONTAINER_RUNTIME} stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}" \
        $(${CONTAINER_RUNTIME} ps --filter "name=amprealize-" --format "{{.Names}}") 2>/dev/null || true
}

# Show help
show_help() {
    echo "Amprealize Streaming Pipeline Deployment Script"
    echo ""
    echo "Usage:"
    echo "  $0 [command]"
    echo ""
    echo "Commands:"
    echo "  start    - Start all streaming pipeline services (default)"
    echo "  stop     - Stop all streaming pipeline services"
    echo "  restart  - Restart all streaming pipeline services"
    echo "  status   - Check status of all services"
    echo "  help     - Show this help message"
    echo ""
    echo "Architecture:"
    echo "  - Zookeeper: 3-node ensemble for Kafka coordination"
    echo "  - Kafka: 3-broker cluster (12 partitions, replication factor 3)"
    echo "  - Flink: 1 job manager + 3 task managers (6 total slots)"
    echo "  - Schema Registry: Avro/JSON schema management"
    echo "  - TimescaleDB: postgres-telemetry:5432 (must be running)"
    echo ""
    echo "Capacity:"
    echo "  - Target throughput: 10,000 events/second"
    echo "  - Kafka retention: 7 days"
    echo "  - Total parallelism: 6"
    echo ""
    echo "For more details, see:"
    echo "  - docs/STREAMING_PIPELINE_ARCHITECTURE.md"
    echo "  - docker-compose.streaming.yml"
}

# Main script
main() {
    cd "$PROJECT_ROOT"

    case "${1:-start}" in
        start)
            start_pipeline
            ;;
        stop)
            stop_pipeline
            ;;
        restart)
            restart_pipeline
            ;;
        status)
            check_status
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            log_error "Unknown command: $1"
            show_help
            exit 1
            ;;
    esac
}

main "$@"
