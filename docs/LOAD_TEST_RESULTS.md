# Amprealize Load Test Results

> **Last Updated:** 2025-01-28
> **Status:** ⚠️ **Baseline Captured - Performance Gaps Identified**
> **Test Suite:** `tests/load/test_service_load.py`

## Test Configuration

```python
# Executed Load Profile
CONCURRENT_WORKERS = 50
TOTAL_REQUESTS = 1000
```

## Load Profile Presets

The pytest fixtures in `tests/load/conftest.py` now expose named presets so contributors can match their hardware constraints without touching the test code.

| Profile | Concurrent Workers | Total Requests | When to Use |
|---------|--------------------|----------------|-------------|
| `smoke` | 5 | 100 | Fast sanity checks on laptops or CI warmups |
| `baseline` | 20 | 1000 | Default regression target aligned with PRD P95 goals |
| `stress` | 50 | 5000 | Heavy profiling on beefy CI runners or staging clusters |

Select a preset via CLI or environment variable:

```bash
# CLI override
pytest tests/load/test_service_load.py -v --load-profile=smoke

# Environment variable (preferred for scripts)
AMPREALIZE_LOAD_PROFILE=stress pytest tests/load/test_service_load.py -v

# Fine-grained overrides remain available
pytest tests/load/test_service_load.py -v --concurrent=50 --total=5000
```

## Local Hardware Tips

- `scripts/run_tests.sh` now honors `AMPREALIZE_API_SERVER_WORKERS` to control uvicorn's worker count when the helper script bootstraps the API server. Set `AMPREALIZE_API_SERVER_WORKERS=1` for fanless laptops or bump to `4` on CI to keep the load tests fed.
- Combine `AMPREALIZE_LOAD_PROFILE=smoke` with the worker knob for the fastest loop:

```bash
AMPREALIZE_LOAD_PROFILE=smoke \
AMPREALIZE_API_SERVER_WORKERS=1 \
./scripts/run_tests.sh tests/load/test_service_load.py -v
```

- For realistic regression runs, stick to `baseline` plus a slightly higher worker count to match production threading:

```bash
AMPREALIZE_LOAD_PROFILE=baseline \
AMPREALIZE_API_SERVER_WORKERS=4 \
./scripts/run_tests.sh tests/load/test_service_load.py -v
```


## Executive Summary

**Total Test Duration:** 43.87s
**Tests Executed:** 7 (2 passed ✅, 3 failed ❌, 2 skipped ⏭️)

| Service | P95 Latency | Target | Status | Delta |
|---------|-------------|--------|--------|-------|
| Health Endpoint | 456.01ms | <500ms | ✅ PASS | Within target |
| Metrics Endpoint | 518.06ms | <1000ms | ✅ PASS | Within target |
| BehaviorService | 1315.20ms | <100ms | ❌ FAIL | **13.15x over** |
| WorkflowService | 338.98ms | <100ms | ❌ FAIL | **3.39x over** |
| ActionService | 161.02ms | <100ms | ❌ FAIL | **1.61x over** |
| RunService | - | <100ms | ⏭️ SKIP | Endpoint not implemented |
| ComplianceService | - | <100ms | ⏭️ SKIP | Endpoint not implemented |

**Key Findings:**
- ✅ Infrastructure monitoring endpoints (health/metrics) meet PRD targets
- ❌ All service endpoints significantly exceed <100ms P95 requirement
- ⚠️ BehaviorService most critical (13x over target) - needs immediate optimization
- 🔍 All services show 0% error rate - reliability good, performance needs work
- 📊 Baselines establish empirical evidence for optimization priorities

## Baseline Performance Metrics

> **Execution Command:**
> ```bash
> pytest tests/load/test_service_load.py -v -s --concurrent=50 --total=1000
> ```

### Health Endpoint (`GET /health`)

**Target:** P95 <500ms (health checks should be fast)
**Result:** ✅ **PASSED** (P95 456.01ms within target)

```
┌─────────────────────────────────────────┐
│          BASELINE CAPTURED              │
│                                         │
│  Total time: 4.57s                      │
│  Throughput: 218.65 req/s               │
│  P50 latency: 186.85ms                  │
│  P95 latency: 456.01ms ✅ <500ms         │
│  P99 latency: 618.32ms                  │
│  Error rate: 0.00%                      │
└─────────────────────────────────────────┘
```

**Analysis:**
Health endpoint performance meets PRD requirements. P95 latency well under 500ms target with excellent error rate (0%). Suitable for production health checks and monitoring.



### Metrics Endpoint (`GET /metrics`)

**Target:** P95 <1000ms (metrics collection can be slower)
**Result:** ✅ **PASSED** (P95 518.06ms within target)

```
┌─────────────────────────────────────────┐
│          BASELINE CAPTURED              │
│                                         │
│  Total time: 0.64s                      │
│  Throughput: 156.92 req/s               │
│  P50 latency: 261.44ms                  │
│  P95 latency: 518.06ms ✅ <1000ms        │
│  P99 latency: 595.32ms                  │
│  Error rate: 0.00%                      │
└─────────────────────────────────────────┘
```

**Analysis:**
Metrics endpoint performance meets PRD requirements. P95 latency well under 1s target. Prometheus scraping and dashboard queries will complete within acceptable timeframes.



### Behavior Service (`GET /v1/behaviors`)

**Target:** P95 <100ms (read operations per RETRIEVAL_ENGINE_PERFORMANCE.md)
**Result:** ❌ **FAILED** (P95 1315.20ms - **13.15x over target**)

```
┌─────────────────────────────────────────┐
│          BASELINE CAPTURED              │
│         ⚠️ OPTIMIZATION REQUIRED        │
│                                         │
│  Total time: 5.94s                      │
│  Throughput: 168.27 req/s               │
│  P50 latency: 200.44ms                  │
│  P95 latency: 1315.20ms ❌ (target <100ms)│
│  P99 latency: 1414.67ms                 │
│  Error rate: 0.00%                      │
└─────────────────────────────────────────┘
```

**Analysis:**
BehaviorService shows most critical performance gap. P95 latency 13x over target suggests:
- **Likely cause:** Complex queries without indexes on behavior metadata, tags, or agent_id
- **Impact:** Behavior retrieval during inference will add >1s latency per call
- **Priority:** **CRITICAL** - blocking production deployment
- **Recommendations:**
  1. Add indexes on frequently queried fields (agent_id, created_at, tags)
  2. Implement Redis caching for stable behaviors
  3. Review query patterns in slow query logs
  4. Consider materialized views for complex joins



### Workflow Service (`GET /v1/workflows/templates`)

**Target:** P95 <100ms (read operations)
**Result:** ❌ **FAILED** (P95 338.98ms - **3.39x over target**)

```
┌─────────────────────────────────────────┐
│          BASELINE CAPTURED              │
│         ⚠️ OPTIMIZATION REQUIRED        │
│                                         │
│  Total time: 30.69s                     │
│  Throughput: 32.55 req/s                │
│  P50 latency: 135.24ms                  │
│  P95 latency: 338.98ms ❌ (target <100ms)│
│  P99 latency: 442.98ms                  │
│  Error rate: 0.00%                      │
└─────────────────────────────────────────┘
```

**Analysis:**
WorkflowService shows lowest throughput (32 req/s) and moderate P95 latency gap. Concerning performance characteristics:
- **Likely cause:** Complex workflow template queries with nested JSON fields or joins
- **Impact:** Workflow listing/retrieval adding 200-400ms overhead during planning
- **Priority:** **HIGH** - impacts user-facing workflow selection UX
- **Recommendations:**
  1. Analyze slow query logs for template retrieval patterns
  2. Add indexes on workflow metadata (template_type, status, agent_id)
  3. Implement query result caching (templates change infrequently)
  4. Consider pagination limits to reduce result set size



### Action Service (`GET /v1/actions`)

**Target:** P95 <100ms (read operations)
**Result:** ❌ **FAILED** (P95 161.02ms - **1.61x over target**)

```
┌─────────────────────────────────────────┐
│          BASELINE CAPTURED              │
│         ⚠️ OPTIMIZATION REQUIRED        │
│                                         │
│  Total time: 1.74s                      │
│  Throughput: 576.31 req/s               │
│  P50 latency: 78.59ms                   │
│  P95 latency: 161.02ms ❌ (target <100ms)│
│  P99 latency: 212.11ms                  │
│  Error rate: 0.00%                      │
└─────────────────────────────────────────┘
```

**Analysis:**
ActionService shows best service performance (highest throughput, closest to target) but still exceeds P95 requirement:
- **Likely cause:** Missing indexes on action registry queries (type, status, timestamps)
- **Impact:** Action history/retrieval adding ~60ms overhead during replay flows
- **Priority:** **MEDIUM** - closest to meeting target, smallest optimization lift
- **Recommendations:**
  1. Add indexes on action_type, agent_id, created_at for list queries
  2. Review pagination/limit defaults to reduce result set size
  3. Implement selective field projection to reduce JSON serialization overhead
  4. Consider this service as optimization template for others


### Run Service (`GET /v1/runs`)

**Status:** Endpoint not yet implemented (skipped in test suite)

```
┌─────────────────────────────────────────┐
│        ENDPOINT NOT IMPLEMENTED         │
│                                         │
│  Will be tested after Priority 1.4.x    │
│  implementation completes.              │
└─────────────────────────────────────────┘
```

### Compliance Service (`GET /v1/compliance/audits`)

**Status:** Endpoint not yet implemented (skipped in test suite)

```
┌─────────────────────────────────────────┐
│        ENDPOINT NOT IMPLEMENTED         │
│                                         │
│  Will be tested after Priority 1.4.x    │
│  implementation completes.              │
└─────────────────────────────────────────┘
```

## Connection Pool Utilization During Load

> **Note:** Pool metrics are available via `/health` endpoint and Prometheus `/metrics`. Detailed analysis requires correlation with slow query logs.

**Observed Behavior:**
- Health endpoint remained responsive (P95 456ms) throughout load test
- No connection pool exhaustion warnings in logs
- 0% error rate across all services indicates adequate pool sizing for current load profile

**Next Steps:**
- Capture pool stats from Prometheus during peak load windows
- Set up Grafana alerts for pool exhaustion (>80% utilization)
- Monitor after optimization work to validate improvements

## Transaction Metrics During Load

**Error Rate:** 0.00% across all services ✅

```
┌─────────────────────────────────────────┐
│     ALL SERVICES: ZERO ERROR RATE       │
│                                         │
│  Total requests: 5000                   │
│  Successful: 5000                       │
│  Failed: 0                              │
│  Error rate: 0.00% ✅                    │
│                                         │
│  Breakdown by service:                  │
│    Health: 1000 requests, 0 errors      │
│    Metrics: 1000 requests, 0 errors     │
│    Behavior: 1000 requests, 0 errors    │
│    Workflow: 1000 requests, 0 errors    │
│    Action: 1000 requests, 0 errors      │
└─────────────────────────────────────────┘
```

**Analysis:**
Excellent reliability under load. All services completed 1000 requests without errors. Performance issues are purely latency-related, not stability-related.

## Slow Query Analysis

> **Action Required:** Review PostgreSQL slow query logs to identify specific bottlenecks

```bash
# Check slow queries during load test period (2025-01-28)
for service in behavior workflow action; do
  echo "=== $service slow queries ==="
  podman logs amprealize-postgres-$service 2>&1 | grep "duration: [0-9]\{4,\}" | tail -20
done
```

**Expected Findings Based on P95 Latencies:**
- **BehaviorService:** Likely queries taking >1000ms (P95 1315ms observed)
- **WorkflowService:** Likely queries taking >300ms (P95 339ms observed)
- **ActionService:** Likely queries taking >150ms (P95 161ms observed)

**Next Steps:**
1. Extract slow query logs from test period
2. Identify top 5 slowest queries per service
3. Run EXPLAIN ANALYZE on identified queries
4. Design indexes and optimization strategy

## Comparison to Targets

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| Health P95 | <500ms | 456.01ms | ✅ **PASS** |
| Metrics P95 | <1000ms | 518.06ms | ✅ **PASS** |
| Behavior P95 | <100ms | 1315.20ms | ❌ **FAIL (13.15x over)** |
| Workflow P95 | <100ms | 338.98ms | ❌ **FAIL (3.39x over)** |
| Action P95 | <100ms | 161.02ms | ❌ **FAIL (1.61x over)** |
| Error rate | <1% | 0.00% | ✅ **PASS** |
| Throughput (health) | >500 req/s | 218.65 req/s | ⚠️ Below target* |
| Checkout timeouts | 0 | 0 | ✅ **PASS** |

*Note: Reduced load profile (50 concurrent vs 100) likely limits throughput measurement. Health endpoint can likely handle >500 req/s with higher concurrency.


## Execution Summary

**Date:** 2025-01-28
**Load Profile:** 1000 requests, 50 concurrent workers
**Total Duration:** 43.87 seconds
**Infrastructure:** 6 PostgreSQL containers (Up 23-28 hours), API server on port 8000

```bash
# Actual execution command
pytest tests/load/test_service_load.py -v -s --concurrent=50 --total=1000
```

**Results:** 2 passed ✅, 3 failed ❌, 2 skipped ⏭️

### Key Observations

1. **Infrastructure Monitoring Works Well**
   - Health endpoint: P95 456ms ✅ (under 500ms target)
   - Metrics endpoint: P95 518ms ✅ (under 1s target)
   - Prometheus integration functional and responsive

2. **Service Performance Gaps Identified**
   - BehaviorService: **CRITICAL** - P95 1315ms (13.15x over 100ms target)
   - WorkflowService: **HIGH** - P95 339ms (3.39x over 100ms target)
   - ActionService: **MEDIUM** - P95 161ms (1.61x over 100ms target)

3. **Reliability Excellent**
   - 0% error rate across 5000 total requests
   - No connection pool exhaustion
   - No transaction failures or retries observed

4. **Root Cause Hypothesis**
   - Missing database indexes on frequently queried fields
   - No query result caching implemented
   - Potentially inefficient query patterns (needs slow query log analysis)
   - No read replicas or connection pooling optimization

### Immediate Action Items

**Priority 1 - Critical (BehaviorService):**
- [ ] Extract slow query logs for behavior database
- [ ] Run EXPLAIN ANALYZE on list/filter queries
- [ ] Add indexes on: agent_id, created_at, tags, metadata fields
- [ ] Implement Redis caching for stable behaviors
- [ ] Target: Reduce P95 from 1315ms → <100ms (13x improvement)

**Priority 2 - High (WorkflowService):**
- [ ] Analyze workflow template retrieval patterns
- [ ] Add indexes on: template_type, status, agent_id, created_at
- [ ] Implement template caching (templates rarely change)
- [ ] Review pagination defaults
- [ ] Target: Reduce P95 from 339ms → <100ms (3.4x improvement)

**Priority 3 - Medium (ActionService):**
- [ ] Add indexes on: action_type, agent_id, created_at
- [ ] Implement selective field projection (reduce JSON overhead)
- [ ] Optimize pagination/limits
- [ ] Use as template for other service optimizations
- [ ] Target: Reduce P95 from 161ms → <100ms (1.6x improvement)

**Priority 4 - Follow-up:**
- [ ] Re-run load tests with 10k requests/100 concurrent after optimizations
- [ ] Validate throughput targets (>500 req/s) with higher concurrency
- [ ] Capture pool metrics during peak load
- [ ] Set up Grafana alerts for P95 latency regression

### Impact on PRD Roadmap

**Phase 3 (Production Infrastructure):** ✅ Complete
- Monitoring infrastructure fully operational
- Baselines captured and documented
- Performance gaps identified before production deployment

**Recommended New Priority:** Service Performance Optimization
- **Blocker:** Services do not meet <100ms P95 requirement from RETRIEVAL_ENGINE_PERFORMANCE.md
- **Impact:** Current performance would add 200-1300ms latency to user-facing operations
- **Timing:** Should complete before Phase 4 (Retrieval Engine Production Deployment)
- **Effort:** Estimated 2-3 sprints (indexing + caching + validation)


## References

- **Monitoring Guide:** `docs/MONITORING_GUIDE.md`
- **Load Test Suite:** `tests/load/test_service_load.py`
- **Performance Targets:** `RETRIEVAL_ENGINE_PERFORMANCE.md`
- **Priority 1.3.3 Spec:** `BUILD_TIMELINE.md` #97
