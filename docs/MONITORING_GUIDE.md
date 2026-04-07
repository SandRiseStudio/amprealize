# Amprealize Monitoring Guide

> **Last Updated:** 2025-11-24
> **Status:** Priority 1.3.3 Complete + Embedding Optimization (8.10.1)
> **Owner:** DevOps + Engineering

## Overview

This guide describes the monitoring and observability infrastructure for Amprealize's PostgreSQL-backed services. Following Priority 1.3.3 completion, all 5 services expose Prometheus metrics for connection pooling, transaction execution, and query performance.

**New in 8.10.1:** Embedding retrieval metrics for the gradual rollout of the optimized all-MiniLM-L6-v2 model.

## Quick Start

```bash
# 1. Start PostgreSQL containers with slow query logging enabled
podman-compose -f docker-compose.postgres.yml up -d

# 2. Start the Amprealize API server
uvicorn amprealize.api:app --reload

# 3. Check health status
curl http://localhost:8000/health | jq

# 4. View Prometheus metrics
curl http://localhost:8000/metrics

# 5. Run load tests
pytest tests/load/test_service_load.py -v --concurrent=100 --total=10000
```

## Architecture

### Metrics Collection

```
┌─────────────────────┐
│   Amprealize Services  │
│  (BehaviorService,  │
│   WorkflowService,  │
│   ActionService,    │
│   RunService,       │
│   ComplianceService)│
└──────────┬──────────┘
           │
           │ Prometheus metrics
           │ (pool stats, transactions, queries)
           ▼
┌─────────────────────┐
│  /metrics endpoint  │
│  (prometheus_client)│
└──────────┬──────────┘
           │
           │ HTTP scrape (30s interval)
           ▼
┌─────────────────────┐
│   Prometheus Server │
│   (time-series DB)  │
└──────────┬──────────┘
           │
           │ PromQL queries
           ▼
┌─────────────────────┐
│   Grafana Dashboard │
│  (visualization +   │
│    alerting)        │
└─────────────────────┘
```

### Slow Query Logging

All PostgreSQL containers are configured with:
- `log_min_duration_statement=1000` (log queries >1s)
- `log_line_prefix=%m [%p] %q%u@%d` (timestamp, PID, user, database)
- Logs available via: `podman logs amprealize-postgres-<service>`

## Available Metrics

### Connection Pool Metrics

```prometheus
# Number of active connections in use
amprealize_pool_connections_active{service="behavior|workflow|action|run|compliance"}

# Number of idle connections available
amprealize_pool_connections_idle{service="..."}

# Total connections (active + idle)
amprealize_pool_connections_total{service="..."}

# Overflow connections beyond pool_size
amprealize_pool_connections_overflow{service="..."}

# Connection checkout duration (histogram)
amprealize_pool_checkout_duration_seconds{service="..."}

# Connection checkout timeouts
amprealize_pool_checkout_timeouts_total{service="..."}
```

**Pool Configuration (via environment):**
- `AMPREALIZE_PG_POOL_SIZE=10` (default: 10 connections per service)
- `AMPREALIZE_PG_POOL_MAX_OVERFLOW=20` (default: 20 overflow connections)
- `AMPREALIZE_PG_POOL_TIMEOUT=30` (default: 30s checkout timeout)
- `AMPREALIZE_PG_POOL_RECYCLE=1800` (default: 30min connection lifetime)
- `AMPREALIZE_PG_CONNECT_TIMEOUT=5` (default: 5s initial connection timeout)

### Transaction Metrics

```prometheus
# Total transaction attempts
amprealize_transaction_attempts_total{service="...", operation="create_draft|approve_behavior|..."}

# Transaction retries due to deadlocks/serialization failures
amprealize_transaction_retries_total{service="...", operation="..."}

# Transaction failures (non-retriable)
amprealize_transaction_failures_total{service="...", operation="...", error_type="..."}

# Transaction execution duration (histogram)
amprealize_transaction_duration_seconds{service="...", operation="..."}
```

**Transaction Retry Logic:**
- Automatic retry on PostgreSQL errors: `40P01` (deadlock), `40001` (serialization failure)
- Exponential backoff: base 0.05s + jitter (0-10ms), max 3 attempts
- Retry metrics track concurrency issues

### Query Metrics

```prometheus
# Query execution duration by type (histogram)
amprealize_query_duration_seconds{service="...", query_type="SELECT|INSERT|UPDATE|DELETE"}

# Slow queries (>1s) counter
amprealize_slow_queries_total{service="..."}
```

## Health Endpoints

### GET /health

Returns detailed service health with pool statistics:

```json
{
  "status": "healthy",
  "services": [
    {
      "service": "behavior",
      "status": "healthy",
      "pool": {
        "service": "behavior",
        "checked_out": 2,
        "pool_size": 10,
        "overflow": 0,
        "available": 8
      }
    },
    ...
  ],
  "pools_summary": {
    "total_checked_out": 10,
    "total_available": 40,
    "total_pool_size": 50
  }
}
```

**Status Values:**
- `healthy`: All services operational, connections available
- `degraded`: One or more services have no available connections
- `error`: Service health check failed

### GET /metrics

Prometheus exposition format metrics for scraping:

```
# HELP amprealize_pool_connections_active Number of active connections in the pool
# TYPE amprealize_pool_connections_active gauge
amprealize_pool_connections_active{service="behavior"} 2.0
amprealize_pool_connections_active{service="workflow"} 1.0
...
```

## Grafana Dashboards

Pre-built dashboard configuration: `web-console/dashboard/grafana/service-health-dashboard.json`

**Panels:**
1. **Connection Pool Utilization** - Active/idle connections by service
2. **Pool Overflow Connections** - Overflow usage (alerts if >5)
3. **Transaction Duration (P95)** - 95th percentile latency by service/operation
4. **Transaction Duration (P99)** - 99th percentile latency
5. **Transaction Retry Rate** - Retry frequency (deadlocks/serialization failures)
6. **Transaction Failure Rate** - Non-retriable failures (alerts if >0.01/sec)
7. **Slow Queries (>1s)** - Slow query frequency (alerts if >0.1/sec over 10min)
8. **Query Duration by Type** - P95 latency for SELECT/INSERT/UPDATE/DELETE
9. **Pool Checkout Duration** - Connection acquisition latency (alerts if P95 >500ms)
10. **Pool Checkout Timeouts** - Connection pool exhaustion (alerts on any timeout)

**Alerts Configured:**
- High overflow connections (>5): Pool undersized
- Transaction failures detected (>0.01/sec): Application errors
- High slow query rate (>0.1/sec): Query optimization needed
- Slow connection checkout (P95 >500ms): Pool contention
- Connection pool exhausted (any timeout): Increase pool_size

### Setup Instructions

```bash
# 1. Install Prometheus
brew install prometheus  # macOS
# or
sudo apt-get install prometheus  # Linux

# 2. Configure Prometheus (prometheus.yml)
cat >> prometheus.yml << 'EOF'
scrape_configs:
  - job_name: 'amprealize'
    scrape_interval: 30s
    static_configs:
      - targets: ['localhost:8000']
        labels:
          instance: 'amprealize-api'
EOF

# 3. Start Prometheus
prometheus --config.file=prometheus.yml

# 4. Install Grafana
brew install grafana  # macOS
# or
sudo apt-get install grafana  # Linux

# 5. Start Grafana
brew services start grafana  # macOS
# or
sudo systemctl start grafana-server  # Linux

# 6. Access Grafana (http://localhost:3000, admin/admin)

# 7. Add Prometheus data source
#   Configuration → Data Sources → Add → Prometheus
#   URL: http://localhost:9090

# 8. Import dashboard
#   Dashboards → Import → Upload JSON file
#   File: dashboard/grafana/service-health-dashboard.json
```

## Load Testing

Comprehensive load testing suite: `tests/load/test_service_load.py`

### Running Load Tests

```bash
# Default: 100 concurrent workers, 10k total requests
pytest tests/load/test_service_load.py -v

# Custom load profile
pytest tests/load/test_service_load.py -v --concurrent=200 --total=20000

# Test specific service
pytest tests/load/test_service_load.py -v -k test_behavior_service_load

# Save results to file
pytest tests/load/test_service_load.py -v > load_test_results.txt 2>&1
```

### Load Test Coverage

| Test | Endpoint | Target P95 | Notes |
|------|----------|------------|-------|
| `test_health_endpoint_load` | `GET /health` | <500ms | Health checks should be fast |
| `test_metrics_endpoint_load` | `GET /metrics` | <1000ms | Metrics collection can be slower |
| `test_behavior_service_load` | `GET /v1/behaviors` | <100ms | Read operations per RETRIEVAL_ENGINE_PERFORMANCE.md |
| `test_workflow_service_load` | `GET /v1/workflows/templates` | <100ms | Read operations |
| `test_action_service_load` | `GET /v1/actions` | <100ms | Read operations |

**Latency Targets (from PRD/performance specs):**
- Read operations (list/get): P95 <100ms
- Write operations (create/update): P95 <500ms
- Health checks: P95 <500ms
- Error rate: <1% under load

### Interpreting Results

```
/health Endpoint Load Test Results:
  Total time: 12.34s
  Throughput: 810.37 req/s          # Should be >500 req/s
  P50 latency: 45.23ms              # Median response time
  P95 latency: 123.45ms             # 95% of requests faster than this
  P99 latency: 234.56ms             # 99% of requests faster than this
  Error rate: 0.00%                 # Should be <1%
```

**Red Flags:**
- P95 > target threshold: Query optimization or indexing needed
- High error rate (>1%): Connection pool exhausted or application errors
- Throughput degradation: CPU/IO bottleneck or lock contention
- Increasing P99-P95 gap: Outliers indicate intermittent issues

## Troubleshooting

### High Connection Pool Utilization

**Symptoms:** `amprealize_pool_connections_idle` approaching 0 (or overflow rising), checkout timeouts

**Diagnosis:**
```bash
# Check current pool stats
curl -s http://localhost:8000/health | jq '.services[] | select(.service=="behavior") | .pool'

# Check for slow queries
podman logs amprealize-postgres-behavior | grep "duration:"

# Check transaction retry rate
curl -s http://localhost:8000/metrics | grep amprealize_transaction_retries_total
```

**Solutions:**
- Increase `AMPREALIZE_PG_POOL_SIZE` (default: 10)
- Increase `AMPREALIZE_PG_POOL_MAX_OVERFLOW` (default: 20)
- Optimize slow queries (add indexes, refactor joins)
- Reduce transaction duration (batch operations)

### High Transaction Retry Rate

**Symptoms:** `amprealize_transaction_retries_total` increasing rapidly

**Diagnosis:**
```bash
# Check retry metrics by service/operation
curl -s http://localhost:8000/metrics | grep amprealize_transaction_retries_total

# Check PostgreSQL logs for deadlocks
podman logs amprealize-postgres-behavior | grep "deadlock detected"
```

**Solutions:**
- Reduce lock contention (shorter transactions, row-level locking)
- Adjust isolation level if appropriate (currently SERIALIZABLE)
- Increase retry attempts if transient (default: 3)
- Reorder operations to avoid circular lock dependencies

### Slow Queries

**Symptoms:** `amprealize_slow_queries_total` increasing, P95 latency degradation

**Diagnosis:**
```bash
# View slow query logs
podman logs amprealize-postgres-behavior | grep "duration: [0-9]\{4,\}"

# Check query plans
podman exec -it amprealize-postgres-behavior psql -U amprealize_behavior -d behaviors
EXPLAIN ANALYZE SELECT ...;
```

**Solutions:**
- Add missing indexes on frequently filtered/joined columns
- Avoid SELECT * (fetch only needed columns)
- Paginate large result sets
- Use connection pooling to reduce connection overhead

### Pool Checkout Timeouts

**Symptoms:** `amprealize_pool_checkout_timeouts_total` > 0, 503 errors

**Diagnosis:**
```bash
# Check timeout metrics
curl -s http://localhost:8000/metrics | grep amprealize_pool_checkout_timeouts_total

# Verify pool configuration
env | grep AMPREALIZE_PG_POOL
```

**Solutions:**
- Increase `AMPREALIZE_PG_POOL_TIMEOUT` (default: 30s)
- Increase pool size to handle burst traffic
- Investigate long-running transactions blocking pool
- Consider read replicas for read-heavy workloads

## Performance Baselines

See [`docs/LOAD_TEST_RESULTS.md`](LOAD_TEST_RESULTS.md) for detailed baseline metrics captured during Priority 1.3.3 validation.

**Summary (100 concurrent, 10k requests):**
- Health endpoint: 810 req/s, P95 123ms
- Behavior list: 450 req/s, P95 89ms
- Workflow list: 520 req/s, P95 76ms
- Action list: 480 req/s, P95 82ms
- Error rate: <0.1% across all services

## Next Steps

1. **Production Deployment:** Configure Prometheus/Grafana in production environment
2. **Alerting:** Set up PagerDuty/Slack integration for critical alerts
3. **Capacity Planning:** Monitor trends over 30 days, adjust pool sizes
4. **Query Optimization:** Address any slow queries identified during load testing
5. **Read Replicas:** Consider read replicas for BehaviorService (read-heavy)

---

## Embedding Retrieval Metrics (Epic 8.10.1)

The embedding optimization rollout introduces 14 Prometheus metrics for monitoring the behavior retrieval system during the gradual model transition.

### SLO Targets

| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| P95 Latency | < 250ms | > 250ms for 5min |
| Memory Footprint | < 750MB | > 750MB for 2min |
| Cache Hit Rate | > 30% | < 30% for 10min |
| Error Rate | < 5% | > 5% for 5min |
| Degraded Mode Rate | < 10% | > 10% for 10min |

### Embedding Model Metrics

```prometheus
# Model load tracking (lazy loading validation)
amprealize_embedding_model_load_count_total{model_name="all-MiniLM-L6-v2|BAAI/bge-m3"}
amprealize_embedding_model_load_time_seconds{model_name="..."}
amprealize_embedding_model_memory_bytes{model_name="..."}
```

### Retrieval Performance Metrics

```prometheus
# Retrieval latency (histogram for P50/P95/P99)
amprealize_retrieval_latency_seconds_bucket{strategy="semantic|keyword", model_name="...", le="0.01|0.05|0.1|0.25|0.5|1.0"}
amprealize_retrieval_latency_seconds_sum{...}
amprealize_retrieval_latency_seconds_count{...}

# Request counting
amprealize_retrieval_requests_total{strategy="...", model_name="..."}
amprealize_retrieval_failures_total{strategy="...", error_type="model_load|index_error|timeout"}
```

### Cache Metrics

```prometheus
# Cache efficiency (target >30% hit rate)
amprealize_retrieval_cache_hits_total{strategy="..."}
amprealize_retrieval_cache_misses_total{strategy="..."}
```

### FAISS Index Metrics

```prometheus
# Index health
amprealize_faiss_index_behaviors_total
amprealize_faiss_index_rebuild_total
amprealize_faiss_index_rebuild_duration_seconds
```

### A/B Rollout Metrics

```prometheus
# Traffic split monitoring (behavior_instrument_metrics_pipeline)
amprealize_retrieval_requests_total{model_name="all-MiniLM-L6-v2"}  # New model traffic
amprealize_retrieval_requests_total{model_name="BAAI/bge-m3"}       # Baseline traffic

# Quality comparison
amprealize_retrieval_degraded_mode_total{model_name="..."}
```

### Useful PromQL Queries

```promql
# P95 Latency by model (should be <250ms)
histogram_quantile(0.95, sum(rate(amprealize_retrieval_latency_seconds_bucket[5m])) by (le, model_name))

# Cache hit rate (should be >30%)
sum(rate(amprealize_retrieval_cache_hits_total[10m])) /
(sum(rate(amprealize_retrieval_cache_hits_total[10m])) + sum(rate(amprealize_retrieval_cache_misses_total[10m])))

# Error rate by model (should be <5%)
sum(rate(amprealize_retrieval_failures_total[5m])) by (model_name) /
sum(rate(amprealize_retrieval_requests_total[5m])) by (model_name)

# Traffic distribution (A/B split validation)
sum(rate(amprealize_retrieval_requests_total[5m])) by (model_name)

# Memory footprint (should be <750MB)
amprealize_embedding_model_memory_bytes

# Model load count (should be exactly 1 for lazy loading)
amprealize_embedding_model_load_count_total
```

### Embedding Alerts Configuration

Alerts are defined in `deployment/prometheus/embedding_alerts.yml` and include:

| Alert | Severity | Trigger |
|-------|----------|---------|
| `EmbeddingRetrievalLatencyHigh` | page | P95 > 250ms for 5min |
| `EmbeddingModelMemoryHigh` | page | Memory > 750MB for 2min |
| `EmbeddingCacheHitRateLow` | warning | Cache < 30% for 10min |
| `EmbeddingRetrievalFailureRateHigh` | critical | Error > 5% for 5min |
| `EmbeddingDegradedModeHigh` | warning | Degraded > 10% for 10min |
| `EmbeddingModelNotLazyLoaded` | warning | Load count > 1 |
| `EmbeddingIndexRebuildStorm` | warning | > 2 rebuilds/hour |

### Grafana Dashboard

Import `deployment/grafana/dashboards/embedding_dashboard.json` for:

1. **P95 Latency vs SLO** - Real-time latency with 250ms threshold line
2. **Memory Footprint** - Model memory with 750MB threshold
3. **Cache Hit/Miss Ratio** - Efficiency tracking with 30% target
4. **Model Traffic Split** - A/B cohort distribution
5. **Model Load Count** - Lazy loading validation
6. **Error Rate by Type** - Failure categorization

### Rollback Monitoring

During gradual rollout phases, watch for:

```promql
# Rollback trigger conditions (any of these warrant investigation)

# 1. Latency regression >20% vs baseline
histogram_quantile(0.95, sum(rate(amprealize_retrieval_latency_seconds_bucket{model_name="all-MiniLM-L6-v2"}[5m])) by (le)) /
histogram_quantile(0.95, sum(rate(amprealize_retrieval_latency_seconds_bucket{model_name="BAAI/bge-m3"}[5m])) by (le)) > 1.2

# 2. Error rate difference >2%
(sum(rate(amprealize_retrieval_failures_total{model_name="all-MiniLM-L6-v2"}[5m])) / sum(rate(amprealize_retrieval_requests_total{model_name="all-MiniLM-L6-v2"}[5m]))) -
(sum(rate(amprealize_retrieval_failures_total{model_name="BAAI/bge-m3"}[5m])) / sum(rate(amprealize_retrieval_requests_total{model_name="BAAI/bge-m3"}[5m]))) > 0.02
```

**Rollback Procedure:** See [docs/EMBEDDING_ROLLBACK_RUNBOOK.md](EMBEDDING_ROLLBACK_RUNBOOK.md)

---

## BreakerAmp Resource Recommendations

For resource-constrained environments (MacBook Air, low-memory CI runners):

### Development Environment (4GB RAM)

```yaml
# environments.yaml - development
embedding:
  model_name: "sentence-transformers/all-MiniLM-L6-v2"  # 80MB vs 2.3GB
  lazy_load: true   # Essential - defer load until first query
  cache_size: 500   # Smaller cache for limited RAM
  rollout_percentage: 100  # Always use new model (saves ~3GB)
```

**Expected Memory Profile:**
- Startup: ~704MB (no model loaded)
- After first query: ~712MB (+8MB model overhead)
- Peak with cache: ~800MB
- **Headroom:** ~3.2GB remaining from 4GB allocation

### Test Environment (8GB RAM)

```yaml
# environments.yaml - test
embedding:
  model_name: "sentence-transformers/all-MiniLM-L6-v2"
  lazy_load: true
  cache_size: 1000
  rollout_percentage: 100  # Full new model for fast CI
```

### Staging Environment (12GB RAM)

```yaml
# environments.yaml - staging
embedding:
  model_name: "sentence-transformers/all-MiniLM-L6-v2"
  lazy_load: true
  cache_size: 1000
  rollout_percentage: 10  # 10% canary (current phase)
  # Progression: 10% → 50% → 100% over observation windows
```

### Production Environment (16GB+ RAM)

```yaml
# environments.yaml - production
embedding:
  model_name: "sentence-transformers/all-MiniLM-L6-v2"
  lazy_load: true
  cache_size: 2000  # Larger cache for production traffic
  rollout_percentage: 0  # Start at 0% until staging validated
```

### Resource Validation Commands

```bash
# Check current environment embedding config
breakeramp status --env development | grep -A5 embedding

# Validate model memory usage
curl -s http://localhost:8001/metrics | grep amprealize_embedding_model_memory_bytes

# Monitor container memory
podman stats --no-stream amprealize-behavior-service

# Check lazy loading (should be 1)
curl -s http://localhost:8001/metrics | grep amprealize_embedding_model_load_count_total
```

---

## References

- **Priority 1.3.3 Implementation:** `BUILD_TIMELINE.md` #97
- **Load Test Results:** `docs/LOAD_TEST_RESULTS.md`
- **Retrieval Performance Targets:** `RETRIEVAL_ENGINE_PERFORMANCE.md`
- **PostgreSQL Pool Configuration:** `amprealize/storage/postgres_pool.py`
- **Metrics Implementation:** `amprealize/storage/postgres_metrics.py`
- **Grafana Dashboard:** `web-console/dashboard/grafana/service-health-dashboard.json`
