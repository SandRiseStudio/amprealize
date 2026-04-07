# High-Volume Telemetry Streaming Pipeline Architecture

## Executive Summary
This document defines the production architecture for Amprealize's telemetry streaming pipeline, designed to ingest 10,000+ events/second while supporting near real-time PRD metrics dashboards with <30s latency for operational observability.

**Current Foundation (Phase 5 Complete ✅):**
- TimescaleDB 2.23.0 operational on postgres-telemetry:5432
- 2 hypertables with 7-day chunks, 90-day retention, 3-5x compression
- 3 continuous aggregates (10min/1hr refresh) + 3 helper views
- 19/19 tests passing, 11 rows migrated from DuckDB
- Metabase v0.48.0 configured with continuous aggregate queries

**Sprint 3 Goal:** Kafka → Flink → TimescaleDB → Metabase real-time pipeline operational

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Event Producers (All Surfaces)                       │
│  Web │ REST API │ CLI │ MCP Server │ VS Code Extension │ Background Jobs    │
└────┬───────┬────────┬───────────┬────────────────────┬─────────────────┬────┘
     │       │        │           │                    │                 │
     └───────┴────────┴───────────┴────────────────────┴─────────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │   TelemetrySink (async)     │
                    │  - KafkaTelemetrySink       │
                    │  - PostgresTelemetrySink    │
                    │  - Batching (1000 events)   │
                    │  - Compression (gzip)       │
                    │  - Retry logic (exp backoff)│
                    └──────────────┬──────────────┘
                                   │
              ┌────────────────────┴────────────────────┐
              │                                         │
     ┌────────▼─────────┐                   ┌──────────▼──────────┐
     │  Kafka Cluster   │                   │  Direct PostgreSQL  │
     │  (3 brokers)     │                   │  (fallback/backup)  │
     │  Port: 9092-9094 │                   │  Port: 5432         │
     │                  │                   └─────────────────────┘
     │  Topics:         │
     │  - telemetry.    │
     │    events        │
     │  - telemetry.    │
     │    traces        │
     │                  │
     │  Replication: 3  │
     │  Partitions: 12  │
     │  Retention: 7d   │
     └────────┬─────────┘
              │
     ┌────────▼─────────────────────────────────────────┐
     │         Apache Flink Cluster                     │
     │                                                   │
     │  Job Manager (1):        Task Managers (3):      │
     │  - Port: 8081           - 2 slots each           │
     │  - Checkpointing        - 4 GB heap each         │
     │  - State backend        - Parallelism: 6         │
     │                                                   │
     │  Streaming Jobs:                                 │
     │  1. TelemetryKPIProjector                        │
     │     - Windowing: 1min tumbling                   │
     │     - Exactly-once semantics                     │
     │     - Checkpointing: 60s                         │
     │                                                   │
     │  2. ExecutionTraceProcessor                      │
     │     - Session windows: 5min timeout              │
     │     - Span assembly logic                        │
     │     - Late event handling: 10min                 │
     └────────┬─────────────────────────────────────────┘
              │
     ┌────────▼──────────────────────────────────────┐
     │     TimescaleDB 2.23.0                        │
     │     postgres-telemetry:5432                   │
     │                                               │
     │  Hypertables (7-day chunks):                  │
     │  - telemetry_events                           │
     │  - execution_traces                           │
     │                                               │
     │  Continuous Aggregates (10min refresh):       │
     │  - metrics_10min (behavior reuse, tokens)     │
     │  - metrics_hourly (completion, compliance)    │
     │  - metrics_daily (trends, forecasts)          │
     │                                               │
     │  Policies:                                    │
     │  - Compression: 7 days (3-5x reduction)       │
     │  - Retention: 90 days (telemetry)             │
     │  - Retention: 365 days (traces)               │
     └────────┬──────────────────────────────────────┘
              │
     ┌────────▼──────────────────────────────────────┐
     │          Metabase v0.48.0                     │
     │          Port: 3000                           │
     │                                               │
     │  Real-Time Dashboards:                        │
     │  1. PRD Metrics Overview                      │
     │     - Behavior Reuse % (target: 70%)          │
     │     - Token Savings % (target: 30%)           │
     │     - Task Completion Rate (target: 80%)      │
     │     - Compliance Coverage (target: 95%)       │
     │     - Refresh: 10 minutes                     │
     │                                               │
     │  2. Operational Health                        │
     │     - Pipeline throughput (events/sec)        │
     │     - Flink lag (seconds)                     │
     │     - Query latency (P95, P99)                │
     │     - Error rates by surface                  │
     │     - Refresh: 1 minute                       │
     │                                               │
     │  3. Trace Analysis                            │
     │     - Execution spans by role                 │
     │     - Pattern detection rates                 │
     │     - Behavior extraction metrics             │
     │     - Refresh: 1 hour                         │
     └───────────────────────────────────────────────┘
```

## Capacity Planning

### Target Throughput
- **Peak**: 10,000 events/second (36M events/hour)
- **Average**: 5,000 events/second (18M events/hour)
- **Daily volume**: ~430M events/day (compressed: ~50GB/day)

### Resource Requirements

#### Kafka Cluster
```yaml
brokers: 3
cpu_per_broker: 2 cores
memory_per_broker: 4 GB
disk_per_broker: 500 GB (SSD)
partitions: 12 (for telemetry.events)
replication_factor: 3
retention: 7 days (~350GB total)
```

#### Flink Cluster
```yaml
job_manager:
  count: 1
  cpu: 2 cores
  memory: 4 GB

task_managers:
  count: 3
  cpu: 4 cores
  memory: 8 GB
  slots: 2
  heap: 6 GB

total_parallelism: 6
state_backend: RocksDB
checkpointing_interval: 60s
checkpoint_timeout: 300s
```

#### TimescaleDB
```yaml
cpu: 4 cores
memory: 16 GB
disk: 1 TB (SSD)
shared_buffers: 4 GB
effective_cache_size: 12 GB
work_mem: 256 MB
max_connections: 200
```

### Latency Targets
| Metric | Target | P95 | P99 |
|--------|--------|-----|-----|
| Kafka ingestion | <10ms | 15ms | 30ms |
| Flink processing | <100ms | 150ms | 300ms |
| TimescaleDB write | <50ms | 80ms | 150ms |
| Dashboard query | <500ms | 800ms | 1500ms |
| **End-to-end (event → dashboard)** | **<30s** | **45s** | **90s** |

## Data Flow & Batching Strategy

### Producer → Kafka
```python
# amprealize/telemetry.py - Enhanced KafkaTelemetrySink
class KafkaTelemetrySink:
    """High-throughput async Kafka sink with batching."""

    config:
        batch_size: 1000 events
        linger_ms: 100  # Allow batching for up to 100ms
        compression_type: gzip
        acks: 1  # Leader acknowledgment (balance speed/durability)
        retries: 3
        retry_backoff_ms: 100
        buffer_memory: 33554432  # 32 MB
        max_in_flight_requests: 5
```

### Kafka → Flink
```python
# deployment/flink/telemetry_kpi_job.py - Windowing strategy
windowing:
    type: tumbling
    size: 1 minute
    allowed_lateness: 10 seconds

checkpointing:
    interval: 60 seconds
    mode: exactly_once
    min_pause_between: 30 seconds
    timeout: 300 seconds
```

### Flink → TimescaleDB
```sql
-- Continuous aggregate refresh strategy
CREATE MATERIALIZED VIEW metrics_10min
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('10 minutes', timestamp) AS bucket,
    actor_role,
    COUNT(*) AS event_count,
    -- PRD metrics calculations
    ...
FROM telemetry_events
WHERE timestamp > NOW() - INTERVAL '1 hour'
GROUP BY bucket, actor_role;

-- Refresh policy
SELECT add_continuous_aggregate_policy('metrics_10min',
    start_offset => INTERVAL '20 minutes',
    end_offset => INTERVAL '10 minutes',
    schedule_interval => INTERVAL '10 minutes'
);
```

## Monitoring & Observability

### Pipeline Health Metrics
```yaml
kafka:
  - kafka_broker_topic_partition_count
  - kafka_server_brokertopicmetrics_messagesinpersec
  - kafka_server_brokertopicmetrics_bytesinpersec
  - kafka_controller_kafkacontroller_activecontrollercount
  - kafka_network_requestmetrics_totaltimems

flink:
  - flink_taskmanager_job_task_numRecordsInPerSecond
  - flink_taskmanager_job_task_numRecordsOutPerSecond
  - flink_taskmanager_job_task_operator_currentInputWatermark
  - flink_jobmanager_job_lastCheckpointDuration
  - flink_taskmanager_Status_JVM_Memory_Heap_Used

timescaledb:
  - pg_stat_database_tup_inserted
  - pg_stat_database_tup_updated
  - timescaledb_hypertable_chunk_count
  - timescaledb_continuous_aggregate_invalidation_log_count
  - timescaledb_compression_ratio
```

### Alerting Thresholds
```yaml
critical:
  - kafka_lag_seconds > 300  # 5 minutes
  - flink_checkpoint_failures > 3
  - timescaledb_connection_pool_exhausted
  - dashboard_query_p99_ms > 5000

warning:
  - kafka_lag_seconds > 60
  - flink_backpressure > 0.8
  - timescaledb_disk_usage_pct > 80
  - event_validation_error_rate > 0.005  # 0.5%
```

## Failure Scenarios & Recovery

### Kafka Broker Failure
- **Detection**: Broker heartbeat timeout (10s)
- **Recovery**: Automatic partition rebalancing to remaining brokers
- **Impact**: Temporary throughput reduction (33% with 3 brokers)
- **RTO**: <1 minute

### Flink Job Failure
- **Detection**: Job manager health check failure
- **Recovery**: Restart from last successful checkpoint
- **Impact**: Event processing paused, Kafka buffer fills
- **RTO**: <5 minutes (checkpoint restore time)

### TimescaleDB Overload
- **Detection**: Connection pool saturation, query latency spike
- **Mitigation**:
  1. Direct PostgreSQL fallback sink activates
  2. Flink job backpressure reduces Kafka consumption
  3. Auto-scaling triggers (if cloud deployment)
- **RTO**: <2 minutes (connection pool recovery)

### Network Partition
- **Detection**: Producer → Kafka timeout (30s)
- **Mitigation**:
  1. Switch to direct PostgresTelemetrySink
  2. Buffer events locally (max 10,000 events)
  3. Replay from local buffer when connectivity restored
- **Recovery**: Manual intervention if buffer overflow

## Security & Compliance

### Data in Transit
- Kafka: TLS 1.3 encryption for all broker communication
- Flink: TLS for job manager ↔ task manager communication
- PostgreSQL: SSL required for all connections

### Data at Rest
- Kafka: Encryption enabled on disk volumes
- TimescaleDB: Transparent data encryption (TDE)
- Compression: Preserves encryption

### Access Control
```yaml
kafka:
  - Producer SASL/SCRAM authentication
  - Topic-level ACLs (write-only for producers)

flink:
  - Job manager web UI: HTTPS with basic auth
  - Checkpoint storage: IAM role-based access

timescaledb:
  - Role-based access: telemetry_writer, telemetry_reader
  - Row-level security for multi-tenant isolation

metabase:
  - SSO integration (SAML/OIDC)
  - Dashboard-level permissions
```

### Audit Requirements
- All telemetry events include `actor.id`, `session_id`, `run_id` per `contracts/TELEMETRY_SCHEMA.md`
- Pipeline health events logged to `audit.pipeline_health` table
- Schema changes versioned and tracked in migration log
- Dashboard query logs retained for 90 days

## Deployment Strategy

### Phase 1: Infrastructure Setup (Week 1)
1. ✅ TimescaleDB 2.23.0 operational (Phase 5 complete)
2. Deploy Kafka cluster via `docker-compose.streaming.yml`
3. Configure Kafka topics, partitions, and replication
4. Deploy Flink cluster with job/task managers
5. Configure monitoring (Prometheus exporters)

### Phase 2: Pipeline Implementation (Week 2)
1. Enhance `amprealize/telemetry.py` with async Kafka sink
2. Productionize `deployment/flink/telemetry_kpi_job.py`
3. Configure Flink checkpointing and state backend
4. Wire Flink → TimescaleDB continuous aggregates
5. Add comprehensive integration tests

### Phase 3: Dashboard & Validation (Week 2)
1. Build PRD metrics dashboards in Metabase
2. Configure continuous aggregate refresh policies
3. Run load tests (10,000 events/sec)
4. Validate end-to-end latency <30s
5. Document runbooks and troubleshooting

### Phase 4: Production Rollout (Week 3)
1. Blue/green deployment with gradual traffic shift
2. Monitor pipeline health for 48 hours
3. Validate PRD metrics accuracy vs. existing data
4. Enable alerting and on-call rotation
5. Update documentation and training materials

## PRD Metrics Implementation

### Dashboard 1: PRD Success Metrics
```sql
-- Behavior Reuse Rate (Target: 70%)
SELECT
    time_bucket('10 minutes', timestamp) AS bucket,
    (COUNT(DISTINCT CASE WHEN payload->>'behaviors_cited' IS NOT NULL
                         THEN event_id END)::FLOAT /
     COUNT(DISTINCT event_id)) * 100 AS behavior_reuse_pct
FROM telemetry_events
WHERE event_type = 'plan_created'
  AND timestamp > NOW() - INTERVAL '24 hours'
GROUP BY bucket
ORDER BY bucket DESC;

-- Token Savings % (Target: 30%)
SELECT
    time_bucket('1 hour', timestamp) AS bucket,
    AVG((payload->>'baseline_tokens')::INT -
        (payload->>'actual_tokens')::INT)::FLOAT /
        NULLIF((payload->>'baseline_tokens')::INT, 0) * 100 AS token_savings_pct
FROM telemetry_events
WHERE event_type = 'execution_update'
  AND payload->>'status' = 'completed'
  AND timestamp > NOW() - INTERVAL '7 days'
GROUP BY bucket;

-- Task Completion Rate (Target: 80%)
SELECT
    time_bucket('1 hour', timestamp) AS bucket,
    (COUNT(CASE WHEN payload->>'status' = 'completed' THEN 1 END)::FLOAT /
     COUNT(*)::FLOAT) * 100 AS completion_rate
FROM telemetry_events
WHERE event_type = 'execution_update'
  AND timestamp > NOW() - INTERVAL '7 days'
GROUP BY bucket;

-- Compliance Coverage (Target: 95%)
SELECT
    time_bucket('1 day', timestamp) AS bucket,
    (COUNT(DISTINCT CASE WHEN payload->>'status' = 'completed'
                         THEN payload->>'checklist_step' END)::FLOAT /
     COUNT(DISTINCT payload->>'checklist_step')::FLOAT) * 100 AS compliance_coverage
FROM telemetry_events
WHERE event_type = 'compliance_step_recorded'
  AND timestamp > NOW() - INTERVAL '30 days'
GROUP BY bucket;
```

### Dashboard 2: Operational Health
```sql
-- Pipeline Throughput
SELECT
    time_bucket('1 minute', timestamp) AS bucket,
    COUNT(*) AS events_per_minute,
    COUNT(*) / 60.0 AS events_per_second
FROM telemetry_events
WHERE timestamp > NOW() - INTERVAL '1 hour'
GROUP BY bucket;

-- Flink Processing Lag
SELECT
    job_name,
    task_name,
    MAX(EXTRACT(EPOCH FROM (NOW() - watermark))) AS lag_seconds
FROM flink_metrics
WHERE timestamp > NOW() - INTERVAL '10 minutes'
GROUP BY job_name, task_name;

-- Error Rates by Surface
SELECT
    time_bucket('10 minutes', timestamp) AS bucket,
    actor->>'surface' AS surface,
    COUNT(*) FILTER (WHERE event_type = 'error') AS error_count,
    COUNT(*) AS total_events,
    (COUNT(*) FILTER (WHERE event_type = 'error')::FLOAT /
     COUNT(*)::FLOAT) * 100 AS error_rate_pct
FROM telemetry_events
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY bucket, surface;
```

## Testing Strategy

### Unit Tests
- `tests/test_telemetry_sinks.py` - Kafka/Postgres sink behavior
- `tests/test_flink_projection.py` - KPI calculation logic
- `tests/test_continuous_aggregates.py` - TimescaleDB queries

### Integration Tests
- `tests/test_telemetry_streaming.py` - End-to-end pipeline
- `tests/test_dashboard_queries.py` - Metabase query correctness
- `tests/test_backpressure.py` - Flink backpressure handling

### Load Tests
```python
# scripts/load_test_streaming.py
async def test_10k_events_per_second():
    """Validate pipeline handles 10,000 events/sec sustained load."""

    producer = AsyncKafkaProducer(...)
    start = time.time()
    target_events = 600_000  # 1 minute at 10k/sec

    # Generate and publish events
    tasks = [produce_event(i) for i in range(target_events)]
    await asyncio.gather(*tasks)

    elapsed = time.time() - start
    throughput = target_events / elapsed

    assert throughput >= 10_000, f"Throughput {throughput:.0f}/sec below target"

    # Wait for pipeline to process
    await asyncio.sleep(60)

    # Validate dashboard latency
    dashboard_lag = measure_dashboard_lag()
    assert dashboard_lag < 30, f"Dashboard lag {dashboard_lag}s exceeds 30s target"
```

### Chaos Engineering
- Kafka broker kill tests (validate rebalancing)
- Flink job manager restart (validate checkpoint recovery)
- TimescaleDB connection saturation (validate fallback)
- Network partition simulation (validate buffering)

## Migration Path (Phase 5 → Streaming)

### Pre-Streaming (Current State - Phase 5)
- ✅ Events written directly to postgres-telemetry via PostgresTelemetrySink
- ✅ Continuous aggregates refreshed every 10 minutes
- ✅ Metabase dashboards query continuous aggregates
- **Limitation**: Synchronous writes, limited throughput (~1,000 events/sec)

### Streaming (Target State - Sprint 3)
- Events published to Kafka asynchronously
- Flink processes events and writes to TimescaleDB
- Continuous aggregates refreshed every 10 minutes (unchanged)
- Metabase dashboards query continuous aggregates (unchanged)
- **Improvement**: Async ingestion, 10x throughput, buffering, exactly-once

### Migration Steps
1. **Parallel Write Phase** (Week 1):
   - Configure producers to write to both PostgreSQL and Kafka
   - Validate event parity between both paths
   - Monitor for data consistency issues

2. **Gradual Cutover** (Week 2):
   - Shift 10% of traffic to Kafka path
   - Monitor metrics, error rates, latency
   - Increment to 50%, 90%, 100% over 4 days

3. **Cleanup** (Week 3):
   - Remove direct PostgreSQL writes from producers
   - Keep PostgresTelemetrySink as fallback for failures
   - Archive parallel write monitoring data

## Runbook References

### Common Operations
- **Start pipeline**: `docker-compose -f docker-compose.streaming.yml up -d`
- **Stop pipeline**: `docker-compose -f docker-compose.streaming.yml down`
- **View Flink UI**: `http://localhost:8081`
- **View Metabase**: `http://localhost:3000`
- **Kafka topic stats**: `scripts/kafka_topic_stats.sh telemetry.events`

### Troubleshooting
- **High Kafka lag**: Check Flink task manager logs, validate checkpoint success
- **Dashboard stale**: Verify continuous aggregate refresh policy, check TimescaleDB load
- **Flink job stuck**: Restart from last checkpoint: `flink run -s <checkpoint-path> ...`
- **Event validation errors**: Check `contracts/TELEMETRY_SCHEMA.md`, validate producer payload

## Owners & Dependencies

**Owners:**
- Engineering: Pipeline implementation, Flink job, monitoring
- DevOps: Infrastructure deployment, Kafka/Flink operations
- Product Analytics: Dashboard design, PRD metrics validation
- Compliance: Audit requirements, data retention policies

**Dependencies:**
- ✅ Phase 5 Complete: TimescaleDB 2.23.0 operational
- ✅ Sprint 1 P0 Complete: MCP tools unblock telemetry emission
- 🚧 Sprint 3 P1: Kafka cluster deployment
- 🚧 Sprint 3 P1: Flink cluster deployment
- 🚧 Sprint 3 P1: PRD dashboard implementation

## Success Criteria

### Technical
- [ ] Pipeline sustains 10,000 events/second for 1 hour continuous load
- [ ] End-to-end latency (event → dashboard) <30 seconds at P95
- [ ] Exactly-once semantics validated (no duplicate/missing events)
- [ ] All failure scenarios tested with documented recovery times
- [ ] Comprehensive monitoring and alerting operational

### Business
- [ ] PRD metrics dashboards operational with 10-minute refresh
- [ ] Behavior reuse %, token savings %, completion rate, compliance coverage tracked
- [ ] Dashboard query latency <500ms at P95
- [ ] Zero data loss during migration from Phase 5
- [ ] Runbooks and training materials complete

---

**Next Steps:**
1. Build `docker-compose.streaming.yml` with Kafka + Flink clusters
2. Enhance `amprealize/telemetry.py` with async Kafka sink
3. Productionize Flink KPI projection job
4. Create Metabase dashboards
5. Run comprehensive load tests
6. Update tracking documents

_References:_ `contracts/TELEMETRY_SCHEMA.md`, `PRD.md`, `BUILD_TIMELINE.md` #114-115-122, `PROGRESS_TRACKER.md` Phase 5
