# Phase 2 Task 6: Staging Validation Checklist

## Overview
Validate all-MiniLM-L6-v2 embedding model in staging environment with 100% rollout before production deployment.

**SLO Targets:**
- P95 retrieval latency: <250ms
- Model memory footprint: <750MB
- Cache hit ratio: >30%
- Lazy loading: Model load count ≤1

## Pre-Validation Setup

### 1. Start Staging Environment
```bash
# Start core services
podman-compose up -d

# Start Prometheus (for metrics collection)
podman-compose -f docker-compose.metrics.yml up -d

# Optional: Start Grafana for visual monitoring
podman-compose -f docker-compose.metrics.yml up -d grafana
```

### 2. Configure Environment Variables
```bash
export EMBEDDING_MODEL_NAME="sentence-transformers/all-MiniLM-L6-v2"
export EMBEDDING_ROLLOUT_PERCENTAGE=100
```

### 3. Verify Configuration
```bash
# Check environment vars loaded
python3 -c "
import os
print(f'Model: {os.getenv(\"EMBEDDING_MODEL_NAME\")}')
print(f'Rollout: {os.getenv(\"EMBEDDING_ROLLOUT_PERCENTAGE\")}%')
"
```

## Validation Steps

### Step 1: Health Check
```bash
# Test server accessibility
curl http://localhost:8000/health

# Expected: HTTP 200, {"status": "healthy"}
```

### Step 2: Metrics Emission
```bash
# Trigger first retrieval to emit metrics
curl -X POST http://localhost:8000/api/v1/behaviors/retrieve \
  -H 'Content-Type: application/json' \
  -d '{"query": "OAuth2 device flow", "top_k": 5, "user_id": "validation_test"}'

# Verify metrics endpoint
curl http://localhost:8000/metrics | grep amprealize_embedding

# Expected metrics:
# - amprealize_embedding_model_load_time_seconds
# - amprealize_embedding_model_memory_bytes
# - amprealize_retrieval_latency_seconds_bucket
# - amprealize_retrieval_requests_total
# - amprealize_cache_hit_ratio (may be 0 initially)
```

### Step 3: Load Test
```bash
# Option A: Apache Bench (if installed)
echo '{"query":"test query","top_k":5,"user_id":"load_user"}' > /tmp/req.json
ab -n 100 -c 10 -p /tmp/req.json -T application/json http://localhost:8000/api/v1/behaviors/retrieve

# Option B: Python concurrent requests
python3 << 'EOF'
import requests
import concurrent.futures
import time

url = "http://localhost:8000/api/v1/behaviors/retrieve"
latencies = []

def make_request(i):
    payload = {"query": "test query", "top_k": 5, "user_id": f"user_{i}"}
    start = time.time()
    resp = requests.post(url, json=payload)
    elapsed = (time.time() - start) * 1000
    return elapsed, resp.status_code

with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    results = list(executor.map(make_request, range(100)))

latencies = sorted([lat for lat, _ in results])
print(f"P50: {latencies[49]:.1f}ms")
print(f"P95: {latencies[94]:.1f}ms")
print(f"P99: {latencies[98]:.1f}ms")
print(f"Max: {max(latencies):.1f}ms")
EOF

# ✓ PASS: P95 <250ms
# ✗ FAIL: P95 ≥250ms (investigate before production)
```

### Step 4: Memory Validation
```bash
# Check model memory from metrics
curl -s http://localhost:8000/metrics | grep amprealize_embedding_model_memory_bytes | awk '{print $2/1024/1024 " MB"}'

# ✓ PASS: <750MB
# ✗ FAIL: ≥750MB (model not loading correctly)
```

### Step 5: Prometheus Queries (if Prometheus running)
```bash
# P95 latency over last 5 minutes
curl -s 'http://localhost:9090/api/v1/query?query=histogram_quantile(0.95,%20rate(amprealize_retrieval_latency_seconds_bucket{model_name="sentence-transformers/all-MiniLM-L6-v2"}[5m]))' \
  | jq -r '.data.result[0].value[1]' \
  | awk '{printf "%.0f ms\n", $1*1000}'

# Model load count
curl -s 'http://localhost:9090/api/v1/query?query=amprealize_embedding_model_load_count' \
  | jq -r '.data.result[0].value[1]'

# Cache hit ratio
curl -s 'http://localhost:9090/api/v1/query?query=rate(amprealize_cache_hits_total[5m])%20/%20(rate(amprealize_cache_hits_total[5m])%20%2B%20rate(amprealize_cache_misses_total[5m]))' \
  | jq -r '.data.result[0].value[1]' \
  | awk '{printf "%.1f%%\n", $1*100}'
```

### Step 6: Grafana Dashboard (Optional)
```bash
# Import dashboard
# 1. Open Grafana: http://localhost:3000 (admin/admin)
# 2. Import → Upload JSON: deployment/grafana/embedding_optimization.json
# 3. Select Prometheus datasource
# 4. Review panels:
#    - P95 Latency timeseries
#    - Model Memory gauge
#    - Cache Hit Ratio
#    - Model Load Count
#    - Degraded Mode percentage
```

## Automated Validation

Run the automated validation script:
```bash
./scripts/validate_phase2_staging.sh http://localhost:8000
```

This script will:
1. Check server health
2. Verify metrics emission
3. Provide load test instructions
4. Query Prometheus (if available)
5. Prompt for Grafana review
6. Provide pass/fail summary

## Success Criteria

- [ ] Server accessible and healthy
- [ ] All embedding metrics present in /metrics endpoint
- [ ] P95 latency <250ms under 100 concurrent requests
- [ ] Model memory <750MB
- [ ] Model load count ≤1 (lazy loading working)
- [ ] Cache hit ratio >30% (after warmup)
- [ ] No degraded mode warnings (>10% requests)
- [ ] Grafana dashboard shows healthy state

## Failure Scenarios & Remediation

### P95 Latency >250ms
- **Root Cause**: Model inference slower than expected, FAISS index issues, or hardware constraints
- **Remediation**:
  1. Check FAISS index size: `curl http://localhost:8000/metrics | grep faiss_vectors_total`
  2. Verify CPU/GPU resources: `podman stats`
  3. Review logs for warnings: `podman logs amprealize_web`
  4. If persistent, escalate to AGENT_ENGINEERING.md

### Memory >750MB
- **Root Cause**: Model not using all-MiniLM-L6-v2 or lazy loading failed
- **Remediation**:
  1. Verify EMBEDDING_MODEL_NAME env var: `podman exec amprealize_web env | grep EMBEDDING`
  2. Check model loaded: `curl http://localhost:8000/metrics | grep model_load_count`
  3. Restart with correct env vars
  4. If still high, may need Phase 3 quantization

### Model Load Count >1
- **Root Cause**: Lazy loading not working, multiple processes, or initialization issue
- **Remediation**:
  1. Check singleton pattern in BehaviorRetriever._shared_models
  2. Verify only one worker process: `podman exec amprealize_web ps aux | grep gunicorn`
  3. Review initialization logs for errors

### Cache Hit Ratio <30%
- **Root Cause**: Cache disabled, TTL too short, or dataset too diverse
- **Remediation**:
  1. Check cache configuration: `curl http://localhost:8000/metrics | grep cache`
  2. Verify Redis accessible: `redis-cli -p 6379 ping`
  3. Increase cache TTL if needed
  4. **Note**: Low ratio acceptable during initial warmup

## Next Steps (if validation passes)

1. **Record validation completion:**
   ```bash
   # Once amprealize CLI available:
   amprealize record-action --type staging_validation \
     --metadata '{"phase":"2","task":"6","status":"passed","p95_ms":180,"memory_mb":650}'
   ```

2. **Update progress tracker:**
   - Mark Task 6 complete in PROGRESS_TRACKER.md
   - Update todo list: Task 6 → completed

3. **Proceed to production deployment (Task 7):**
   - Set EMBEDDING_ROLLOUT_PERCENTAGE=10 in production
   - Monitor Grafana for 24-48 hours
   - Compare cohort performance (all-MiniLM vs BGE-M3)
   - Increment rollout: 10% → 50% → 100%

4. **Rollback plan:**
   - If P95 spikes or degraded mode increases, set EMBEDDING_ROLLOUT_PERCENTAGE=0
   - This routes all traffic back to baseline BGE-M3 model

## Reference Documents
- `PRD.md` - Phase 2 objectives and success metrics
- `RETRIEVAL_ENGINE_PERFORMANCE.md` - SLO definitions
- `deployment/grafana/README.md` - Monitoring setup guide
- `MCP_SERVER_DESIGN.md` - BehaviorService contract
- `AGENTS.md` - behavior_instrument_metrics_pipeline

---
*Last Updated: 2025-11-10 (Phase 2 Task 6)*
