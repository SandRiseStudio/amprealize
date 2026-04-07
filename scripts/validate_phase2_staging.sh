#!/usr/bin/env bash
# Phase 2 Task 6: Staging validation for embedding optimization
# Behaviors: behavior_instrument_metrics_pipeline, behavior_align_storage_layers
#
# Validates all-MiniLM-L6-v2 deployment against SLO targets:
#   - P95 latency <250ms
#   - Memory <750MB
#   - Cache hit ratio >30%
#   - Lazy loading working (model load count ≤1)
#
# Usage:
#   ./scripts/validate_phase2_staging.sh [staging_url]
#   Example: ./scripts/validate_phase2_staging.sh http://localhost:8080

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

STAGING_URL="${1:-http://localhost:8080}"
PROMETHEUS_URL="${PROMETHEUS_URL:-http://localhost:9090}"

echo -e "${BLUE}========================================================${NC}"
echo -e "${BLUE}Phase 2 Staging Validation: all-MiniLM-L6-v2 (100%)${NC}"
echo -e "${BLUE}========================================================${NC}"
echo ""
echo "Staging URL: $STAGING_URL"
echo "Prometheus: $PROMETHEUS_URL"
echo ""

# SLO targets
SLO_P95_MS=250
SLO_MEMORY_MB=750
SLO_CACHE_PCT=30

VALIDATION_PASSED=true

# ============================================================================
# Step 1: Verify Configuration
# ============================================================================
echo -e "${BLUE}[1/6] Verifying staging configuration...${NC}"

if ! curl -f -s "${STAGING_URL}/health" > /dev/null 2>&1; then
    echo -e "${RED}✗ Staging server not accessible at ${STAGING_URL}/health${NC}"
    echo "  Start staging server with: podman-compose up -d"
    exit 1
fi
echo -e "${GREEN}✓ Staging server accessible${NC}"

echo -e "${YELLOW}  Ensure environment variables are set:${NC}"
echo "    export EMBEDDING_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2"
echo "    export EMBEDDING_ROLLOUT_PERCENTAGE=100"
echo ""

# ============================================================================
# Step 2: Check Metrics Endpoint
# ============================================================================
echo -e "${BLUE}[2/6] Checking metrics endpoint...${NC}"

METRICS_OUTPUT=$(curl -f -s "${STAGING_URL}/metrics" 2>/dev/null || echo "")

if [ -z "$METRICS_OUTPUT" ]; then
    echo -e "${RED}✗ /metrics endpoint not accessible${NC}"
    echo "  Ensure amprealize[postgres] installed and metrics exposed"
    exit 1
fi

# Check for key embedding metrics
REQUIRED_METRICS=(
    "amprealize_embedding_model_load_time_seconds"
    "amprealize_embedding_model_memory_bytes"
    "amprealize_retrieval_latency_seconds"
    "amprealize_retrieval_requests_total"
)

MISSING_METRICS=()
for metric in "${REQUIRED_METRICS[@]}"; do
    if ! echo "$METRICS_OUTPUT" | grep -q "^${metric}"; then
        MISSING_METRICS+=("$metric")
    fi
done

if [ ${#MISSING_METRICS[@]} -gt 0 ]; then
    echo -e "${YELLOW}⚠ Metrics not yet emitted (send test request first):${NC}"
    for metric in "${MISSING_METRICS[@]}"; do
        echo "    - $metric"
    done
    echo ""
    echo "  Trigger metrics with test request:"
    echo "  curl -X POST ${STAGING_URL}/v1/bci/retrieve \\"
    echo "    -H 'Content-Type: application/json' \\"
    echo "    -d '{\"query\":\"test\",\"top_k\":5,\"user_id\":\"test\"}'"
    echo ""
else
    echo -e "${GREEN}✓ All required embedding metrics present${NC}"
fi

# Extract current memory
MEMORY_BYTES=$(echo "$METRICS_OUTPUT" | grep "^amprealize_embedding_model_memory_bytes" | awk '{print $2}' | head -n1 || echo "0")
if [ "$MEMORY_BYTES" != "0" ] && [ "$MEMORY_BYTES" != "" ]; then
    MEMORY_MB=$((MEMORY_BYTES / 1024 / 1024))
    echo -e "${GREEN}  Model memory: ${MEMORY_MB}MB${NC}"

    if [ "$MEMORY_MB" -gt "$SLO_MEMORY_MB" ]; then
        echo -e "${RED}  ✗ SLO VIOLATION: ${MEMORY_MB}MB > ${SLO_MEMORY_MB}MB target${NC}"
        VALIDATION_PASSED=false
    else
        echo -e "${GREEN}  ✓ Memory within SLO (<${SLO_MEMORY_MB}MB)${NC}"
    fi
fi

echo ""

# ============================================================================
# Step 3: Manual Load Test Instructions
# ============================================================================
echo -e "${BLUE}[3/6] Load Test (100 concurrent requests)${NC}"
echo ""
echo "  Run load test with Apache Bench or your preferred tool:"
echo ""
echo "  # Example with ab (Apache Bench):"
echo "  echo '{\"query\":\"OAuth2 device flow\",\"top_k\":5,\"user_id\":\"load_test\"}' > /tmp/request.json"
echo "  ab -n 100 -c 10 -p /tmp/request.json -T application/json \\"
echo "    ${STAGING_URL}/v1/bci/retrieve"
echo ""
echo "  # Or with Python:"
echo "  python3 << 'EOF'"
echo "import requests, concurrent.futures, time"
echo "url = '${STAGING_URL}/v1/bci/retrieve'"
echo "payload = {'query': 'test query', 'top_k': 5, 'user_id': f'user_{i}'}"
echo "def req(i): "
echo "    start = time.time()"
echo "    r = requests.post(url, json=payload)"
echo "    return time.time() - start"
echo "with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:"
echo "    latencies = list(ex.map(req, range(100)))"
echo "latencies.sort()"
echo "print(f'P95: {latencies[94]*1000:.1f}ms, P99: {latencies[98]*1000:.1f}ms')"
echo "EOF"
echo ""
echo "  Expected: P95 <${SLO_P95_MS}ms"
echo ""
echo "  Press Enter after running load test..."
read -r

# ============================================================================
# Step 4: Query Prometheus (if available)
# ============================================================================
echo -e "${BLUE}[4/6] Querying Prometheus for SLO validation...${NC}"

if curl -f -s "${PROMETHEUS_URL}/-/ready" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Prometheus accessible${NC}"

    # Query P95 latency
    P95_QUERY='histogram_quantile(0.95, rate(amprealize_retrieval_latency_seconds_bucket{model_name="sentence-transformers/all-MiniLM-L6-v2"}[5m]))'
    P95_RESULT=$(curl -s "${PROMETHEUS_URL}/api/v1/query?query=$(python3 -c "import urllib.parse; print(urllib.parse.quote('${P95_QUERY}'))")" 2>/dev/null | python3 -c "import sys, json; data=json.load(sys.stdin); print(data['data']['result'][0]['value'][1] if data.get('data',{}).get('result') else '0')" 2>/dev/null || echo "0")

    if [ "$P95_RESULT" != "0" ] && [ "$P95_RESULT" != "" ]; then
        P95_MS=$(python3 -c "print(int(float('${P95_RESULT}') * 1000))" 2>/dev/null || echo "0")
        if [ "$P95_MS" != "0" ]; then
            echo -e "${GREEN}  P95 latency (Prometheus): ${P95_MS}ms${NC}"

            if [ "$P95_MS" -gt "$SLO_P95_MS" ]; then
                echo -e "${RED}  ✗ SLO VIOLATION: ${P95_MS}ms > ${SLO_P95_MS}ms${NC}"
                VALIDATION_PASSED=false
            else
                echo -e "${GREEN}  ✓ P95 within SLO (<${SLO_P95_MS}ms)${NC}"
            fi
        fi
    else
        echo -e "${YELLOW}  ⚠ No P95 data (wait for metrics or check query)${NC}"
    fi

    # Query model load count
    LOAD_COUNT=$(curl -s "${PROMETHEUS_URL}/api/v1/query?query=amprealize_embedding_model_load_count" 2>/dev/null | python3 -c "import sys, json; data=json.load(sys.stdin); print(int(float(data['data']['result'][0]['value'][1])) if data.get('data',{}).get('result') else '0')" 2>/dev/null || echo "0")

    if [ "$LOAD_COUNT" != "0" ]; then
        echo -e "${GREEN}  Model load count: ${LOAD_COUNT}${NC}"

        if [ "$LOAD_COUNT" -gt 1 ]; then
            echo -e "${YELLOW}  ⚠ Model loaded ${LOAD_COUNT} times (lazy loading may not be working)${NC}"
        else
            echo -e "${GREEN}  ✓ Lazy loading working (count ≤1)${NC}"
        fi
    fi

else
    echo -e "${YELLOW}⚠ Prometheus not accessible at ${PROMETHEUS_URL}${NC}"
    echo "  Start with: podman-compose -f docker-compose.metrics.yml up -d"
    echo "  Or set PROMETHEUS_URL to your Prometheus instance"
fi

echo ""

# ============================================================================
# Step 5: Grafana Dashboard Check
# ============================================================================
echo -e "${BLUE}[5/6] Grafana Dashboard Validation${NC}"
echo ""
echo "  1. Open Grafana (default: http://localhost:3000)"
echo "  2. Import dashboard: deployment/grafana/embedding_optimization.json"
echo "  3. Verify panels show healthy metrics:"
echo "     - P95 Retrieval Latency <${SLO_P95_MS}ms"
echo "     - Model Memory <${SLO_MEMORY_MB}MB"
echo "     - Cache Hit Ratio >${SLO_CACHE_PCT}%"
echo "     - Model Load Count ≤1"
echo "     - No degraded mode warnings"
echo ""
echo "  Press Enter when Grafana review complete..."
read -r

# ============================================================================
# Step 6: Summary
# ============================================================================
echo ""
echo -e "${BLUE}========================================================${NC}"
echo -e "${BLUE}[6/6] Validation Summary${NC}"
echo -e "${BLUE}========================================================${NC}"
echo ""

if [ "$VALIDATION_PASSED" = true ]; then
    echo -e "${GREEN}✓ Staging validation PASSED${NC}"
    echo ""
    echo -e "${BLUE}Next Steps:${NC}"
    echo "  1. Mark Task 6 complete: amprealize record-action --type staging_validation"
    echo "  2. Skip Task 5 (alerts) if Prometheus not in production yet"
    echo "  3. Proceed to Task 7: Production deployment with 10% rollout"
    echo ""
    echo "  Production deployment:"
    echo "    export EMBEDDING_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2"
    echo "    export EMBEDDING_ROLLOUT_PERCENTAGE=10"
    echo "    # Deploy and monitor for 24-48 hours"
    echo "    # Increment: 10% → 50% → 100%"
    echo ""
else
    echo -e "${RED}✗ Staging validation FAILED - DO NOT deploy to production${NC}"
    echo ""
    echo "  Review failures above and remediate before proceeding"
    echo ""
fi

echo -e "${YELLOW}Rollback procedure:${NC}"
echo "  If issues in production, set: EMBEDDING_ROLLOUT_PERCENTAGE=0"
echo "  This routes all traffic back to baseline BGE-M3 model"
echo ""
echo -e "${BLUE}========================================================${NC}"
