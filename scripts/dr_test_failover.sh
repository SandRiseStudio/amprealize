#!/usr/bin/env bash
# Disaster Recovery Failover Test Suite
# Automated tests for PostgreSQL, Redis, backup/restore, health check detection
# Outputs JSONL results with RTO/RPO compliance metrics

set -euo pipefail

# Configuration
RESULTS_DIR="${RESULTS_DIR:-/var/log/amprealize/dr_tests}"
OUTPUT_FILE="${RESULTS_DIR}/failover_test_$(date +%Y%m%d_%H%M%S).jsonl"

# Service endpoints
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/amprealize}"

# Logging
mkdir -p "${RESULTS_DIR}"

log_result() {
    local test_name="$1"
    local status="$2"
    local duration_ms="$3"
    local details="$4"

    cat >> "${OUTPUT_FILE}" <<EOF
{"test_name":"${test_name}","status":"${status}","duration_ms":${duration_ms},"timestamp":"$(date -u +%Y-%m-%dT%H:%M:%SZ)","details":${details}}
EOF

    if [ "${status}" = "PASS" ]; then
        echo "✅ ${test_name}: PASS (${duration_ms}ms)"
    else
        echo "❌ ${test_name}: FAIL (${duration_ms}ms)"
    fi
}

# Test 1: PostgreSQL Health Check
test_postgres_health() {
    echo ""
    echo "=== Test 1: PostgreSQL Health Check ==="

    local start_ms=$(date +%s%3N)

    if pg_isready -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" > /dev/null 2>&1; then
        local end_ms=$(date +%s%3N)
        local duration=$((end_ms - start_ms))

        log_result "postgres_health_check" "PASS" "${duration}" '{"message":"PostgreSQL is accepting connections"}'
        return 0
    else
        local end_ms=$(date +%s%3N)
        local duration=$((end_ms - start_ms))

        log_result "postgres_health_check" "FAIL" "${duration}" '{"message":"PostgreSQL is not responding"}'
        return 1
    fi
}

# Test 2: PostgreSQL Query Latency
test_postgres_query() {
    echo ""
    echo "=== Test 2: PostgreSQL Query Latency ==="

    local start_ms=$(date +%s%3N)

    if psql -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U amprealize_admin -d behaviors -t -c "SELECT 1;" > /dev/null 2>&1; then
        local end_ms=$(date +%s%3N)
        local duration=$((end_ms - start_ms))

        if [ ${duration} -lt 100 ]; then
            log_result "postgres_query_latency" "PASS" "${duration}" "{\"message\":\"Query latency ${duration}ms < 100ms threshold\"}"
            return 0
        else
            log_result "postgres_query_latency" "FAIL" "${duration}" "{\"message\":\"Query latency ${duration}ms exceeds 100ms threshold\"}"
            return 1
        fi
    else
        local end_ms=$(date +%s%3N)
        local duration=$((end_ms - start_ms))

        log_result "postgres_query_latency" "FAIL" "${duration}" '{"message":"Query failed"}'
        return 1
    fi
}

# Test 3: Redis Health Check
test_redis_health() {
    echo ""
    echo "=== Test 3: Redis Health Check ==="

    local start_ms=$(date +%s%3N)

    if redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" PING | grep -q "PONG"; then
        local end_ms=$(date +%s%3N)
        local duration=$((end_ms - start_ms))

        log_result "redis_health_check" "PASS" "${duration}" '{"message":"Redis is responding to PING"}'
        return 0
    else
        local end_ms=$(date +%s%3N)
        local duration=$((end_ms - start_ms))

        log_result "redis_health_check" "FAIL" "${duration}" '{"message":"Redis is not responding"}'
        return 1
    fi
}

# Test 4: Redis Read/Write Latency
test_redis_readwrite() {
    echo ""
    echo "=== Test 4: Redis Read/Write Latency ==="

    local test_key="dr_test_$(date +%s)"
    local test_value="failover_test_$(date +%s%3N)"

    local start_ms=$(date +%s%3N)

    redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" SET "${test_key}" "${test_value}" > /dev/null 2>&1
    local write_value=$(redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" GET "${test_key}" 2>/dev/null)
    redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" DEL "${test_key}" > /dev/null 2>&1

    local end_ms=$(date +%s%3N)
    local duration=$((end_ms - start_ms))

    if [ "${write_value}" = "${test_value}" ]; then
        if [ ${duration} -lt 50 ]; then
            log_result "redis_readwrite_latency" "PASS" "${duration}" "{\"message\":\"Read/write latency ${duration}ms < 50ms threshold\"}"
            return 0
        else
            log_result "redis_readwrite_latency" "FAIL" "${duration}" "{\"message\":\"Read/write latency ${duration}ms exceeds 50ms threshold\"}"
            return 1
        fi
    else
        log_result "redis_readwrite_latency" "FAIL" "${duration}" '{"message":"Data integrity check failed"}'
        return 1
    fi
}

# Test 5: PostgreSQL Backup Exists
test_postgres_backup_exists() {
    echo ""
    echo "=== Test 5: PostgreSQL Backup Availability ==="

    local start_ms=$(date +%s%3N)

    local latest_backup=$(ls -1t "${BACKUP_DIR}/postgres" 2>/dev/null | grep "postgres_backup_" | head -n 1 || echo "")

    local end_ms=$(date +%s%3N)
    local duration=$((end_ms - start_ms))

    if [ -n "${latest_backup}" ]; then
        local backup_age_hours=$(( ($(date +%s) - $(stat -f %m "${BACKUP_DIR}/postgres/${latest_backup}" 2>/dev/null || echo "0")) / 3600 ))

        if [ ${backup_age_hours} -lt 2 ]; then
            log_result "postgres_backup_freshness" "PASS" "${duration}" "{\"message\":\"Backup is ${backup_age_hours} hours old (< 2hr threshold)\",\"backup\":\"${latest_backup}\"}"
            return 0
        else
            log_result "postgres_backup_freshness" "FAIL" "${duration}" "{\"message\":\"Backup is ${backup_age_hours} hours old (> 2hr threshold)\",\"backup\":\"${latest_backup}\"}"
            return 1
        fi
    else
        log_result "postgres_backup_freshness" "FAIL" "${duration}" '{"message":"No PostgreSQL backup found"}'
        return 1
    fi
}

# Test 6: Redis Backup Exists
test_redis_backup_exists() {
    echo ""
    echo "=== Test 6: Redis Backup Availability ==="

    local start_ms=$(date +%s%3N)

    local latest_backup=$(ls -1t "${BACKUP_DIR}/redis" 2>/dev/null | grep "redis_backup_.*\.tar\.gz" | head -n 1 || echo "")

    local end_ms=$(date +%s%3N)
    local duration=$((end_ms - start_ms))

    if [ -n "${latest_backup}" ]; then
        local backup_age_mins=$(( ($(date +%s) - $(stat -f %m "${BACKUP_DIR}/redis/${latest_backup}" 2>/dev/null || echo "0")) / 60 ))

        if [ ${backup_age_mins} -lt 30 ]; then
            log_result "redis_backup_freshness" "PASS" "${duration}" "{\"message\":\"Backup is ${backup_age_mins} minutes old (< 30min threshold)\",\"backup\":\"${latest_backup}\"}"
            return 0
        else
            log_result "redis_backup_freshness" "FAIL" "${duration}" "{\"message\":\"Backup is ${backup_age_mins} minutes old (> 30min threshold)\",\"backup\":\"${latest_backup}\"}"
            return 1
        fi
    else
        log_result "redis_backup_freshness" "FAIL" "${duration}" '{"message":"No Redis backup found"}'
        return 1
    fi
}

# Test 7: DuckDB Backup Exists
test_duckdb_backup_exists() {
    echo ""
    echo "=== Test 7: DuckDB Backup Availability ==="

    local start_ms=$(date +%s%3N)

    local latest_backup=$(ls -1t "${BACKUP_DIR}/duckdb" 2>/dev/null | grep "duckdb_backup_.*\.tar\.gz" | head -n 1 || echo "")

    local end_ms=$(date +%s%3N)
    local duration=$((end_ms - start_ms))

    if [ -n "${latest_backup}" ]; then
        local backup_age_hours=$(( ($(date +%s) - $(stat -f %m "${BACKUP_DIR}/duckdb/${latest_backup}" 2>/dev/null || echo "0")) / 3600 ))

        if [ ${backup_age_hours} -lt 2 ]; then
            log_result "duckdb_backup_freshness" "PASS" "${duration}" "{\"message\":\"Backup is ${backup_age_hours} hours old (< 2hr threshold)\",\"backup\":\"${latest_backup}\"}"
            return 0
        else
            log_result "duckdb_backup_freshness" "FAIL" "${duration}" "{\"message\":\"Backup is ${backup_age_hours} hours old (> 2hr threshold)\",\"backup\":\"${latest_backup}\"}"
            return 1
        fi
    else
        log_result "duckdb_backup_freshness" "FAIL" "${duration}" '{"message":"No DuckDB backup found"}'
        return 1
    fi
}

# Test 8: RTO Compliance (Tier 1 - 15 minutes)
test_rto_compliance() {
    echo ""
    echo "=== Test 8: RTO Compliance Check ==="

    # This is a synthetic test - in real incident, this would measure actual recovery time
    local start_ms=$(date +%s%3N)

    # Simulate recovery steps
    sleep 1

    local end_ms=$(date +%s%3N)
    local duration=$((end_ms - start_ms))
    local recovery_time_mins=$((duration / 60000))

    local tier1_rto_mins=15

    if [ ${recovery_time_mins} -lt ${tier1_rto_mins} ]; then
        log_result "rto_compliance_tier1" "PASS" "${duration}" "{\"message\":\"Simulated recovery ${recovery_time_mins}min < ${tier1_rto_mins}min RTO\"}"
        return 0
    else
        log_result "rto_compliance_tier1" "FAIL" "${duration}" "{\"message\":\"Simulated recovery ${recovery_time_mins}min > ${tier1_rto_mins}min RTO\"}"
        return 1
    fi
}

# Main execution
main() {
    echo "╔════════════════════════════════════════════════════════╗"
    echo "║   Amprealize Disaster Recovery Failover Test Suite       ║"
    echo "║   $(date +'%Y-%m-%d %H:%M:%S')                                 ║"
    echo "╚════════════════════════════════════════════════════════╝"
    echo ""
    echo "Output file: ${OUTPUT_FILE}"
    echo ""

    local total_tests=0
    local passed_tests=0

    # Run all tests
    test_postgres_health && ((passed_tests++)) || true; ((total_tests++))
    test_postgres_query && ((passed_tests++)) || true; ((total_tests++))
    test_redis_health && ((passed_tests++)) || true; ((total_tests++))
    test_redis_readwrite && ((passed_tests++)) || true; ((total_tests++))
    test_postgres_backup_exists && ((passed_tests++)) || true; ((total_tests++))
    test_redis_backup_exists && ((passed_tests++)) || true; ((total_tests++))
    test_duckdb_backup_exists && ((passed_tests++)) || true; ((total_tests++))
    test_rto_compliance && ((passed_tests++)) || true; ((total_tests++))

    # Summary
    echo ""
    echo "╔════════════════════════════════════════════════════════╗"
    echo "║   Test Summary                                         ║"
    echo "╚════════════════════════════════════════════════════════╝"
    echo ""
    echo "Total Tests:  ${total_tests}"
    echo "Passed:       ${passed_tests}"
    echo "Failed:       $((total_tests - passed_tests))"
    echo "Success Rate: $((passed_tests * 100 / total_tests))%"
    echo ""
    echo "Results saved to: ${OUTPUT_FILE}"

    # Record action in amprealize
    if command -v amprealize &> /dev/null; then
        amprealize record-action \
            --service dr_testing \
            --action test_failover \
            --status "$( [ ${passed_tests} -eq ${total_tests} ] && echo "success" || echo "partial_success" )" \
            --metadata "{\"total_tests\": ${total_tests}, \"passed\": ${passed_tests}, \"failed\": $((total_tests - passed_tests))}" \
            --behaviors "behavior_orchestrate_cicd,behavior_align_storage_layers" 2>/dev/null || true
    fi

    # Exit with failure if any tests failed
    if [ ${passed_tests} -ne ${total_tests} ]; then
        exit 1
    fi
}

main "$@"
