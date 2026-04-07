# Service Performance Optimization Plan

> **Created:** 2025-01-28
> **Priority:** 1.3.4 - BLOCKER for Phase 4
> **Goal:** Reduce service P95 latencies to meet <100ms target per RETRIEVAL_ENGINE_PERFORMANCE.md

## Executive Summary

Load testing revealed all three primary services significantly exceed P95 <100ms targets:
- **BehaviorService**: 1315ms (13.15x over) - CRITICAL
- **WorkflowService**: 339ms (3.39x over) - HIGH
- **ActionService**: 161ms (1.61x over) - MEDIUM

**Root causes identified**:
1. N+1 query problems (fetching related records in loops)
2. Missing database indexes on frequently queried fields
3. No result caching layer
4. SELECT * queries fetching unnecessary data

## BehaviorService Optimization (CRITICAL - 13x improvement needed)

### Current Performance
- P95 latency: 1315.20ms
- P50 latency: 200.44ms
- Throughput: 168.27 req/s
- Target: P95 <100ms

### Root Cause Analysis

**N+1 Query Problem in `list_behaviors()`**:
```python
# Current implementation (amprealize/behavior_service.py:584-606)
def list_behaviors(self, *, status=None, tags=None, role_focus=None):
    rows = self._fetch_behaviors(status=status)  # Query 1: Fetch all behaviors
    results = []
    for behavior in rows:  # N+1 problem starts here
        active_versions = self._fetch_behavior_versions(behavior.behavior_id)  # Query per behavior!
        # ... filtering logic
    return results
```

With 3 behaviors in database, this executes:
- 1 query to fetch behaviors
- 3 queries to fetch versions (one per behavior)
- **Total: 4 queries instead of 2**

Under load (1000 requests), if behaviors grow to 100 records:
- 1000 requests × 101 queries = 101,000 database round trips!
- Each round trip adds ~10-15ms latency
- Total added latency: 1000-1500ms ✓ (matches observed 1315ms)

### Optimization Strategy

#### Phase 1: Fix N+1 Queries (Estimated impact: 10-12x improvement)

**1.1 Join Optimization**
Replace separate queries with single JOIN:
```sql
-- Current (2 queries per behavior):
SELECT * FROM behaviors WHERE status = 'APPROVED' ORDER BY updated_at DESC;
SELECT * FROM behavior_versions WHERE behavior_id = ?;

-- Optimized (1 query total):
SELECT b.*, bv.*
FROM behaviors b
LEFT JOIN behavior_versions bv ON b.behavior_id = bv.behavior_id
  AND bv.status = 'APPROVED'
  AND bv.effective_to IS NULL
WHERE b.status = 'APPROVED'
ORDER BY b.updated_at DESC;
```

**Implementation**:
- Create `_fetch_behaviors_with_versions()` method using JOIN
- Update `list_behaviors()` to use new method
- Add composite index on `behavior_versions(behavior_id, status, effective_to)`

**Expected improvement**: 1315ms → 120-150ms (9-11x faster)

#### Phase 2: Selective Field Projection (Estimated impact: additional 20-30%)

**2.1 Reduce Data Transfer**
```sql
-- Current:
SELECT * FROM behaviors...  -- Returns 8 columns including large JSONB

-- Optimized:
SELECT behavior_id, name, description, status, updated_at
FROM behaviors...  -- Only fields needed for list view
```

**Implementation**:
- Add `fields` parameter to `_fetch_behaviors()`
- Default to essential fields only
- Fetch full records only when `behavior_id` specified

**Expected improvement**: 120ms → 90-100ms

#### Phase 3: Missing Indexes (Already exists, validate)

Current indexes on `behaviors`:
```sql
✓ behaviors_pkey (behavior_id)
✓ behaviors_name_key (name UNIQUE)
✓ idx_behaviors_status (status)
✓ idx_behaviors_tags_gin (tags jsonb_path_ops)
✓ idx_behaviors_updated_at (updated_at DESC)
```

**Additional indexes needed**:
```sql
-- For behavior_versions JOIN optimization
CREATE INDEX idx_behavior_versions_lookup
ON behavior_versions(behavior_id, status, effective_to)
WHERE status = 'APPROVED' AND effective_to IS NULL;

-- For filtering by role_focus in versions
CREATE INDEX idx_behavior_versions_role_focus
ON behavior_versions(role_focus);
```

#### Phase 4: Redis Caching (Optional, Phase 2)
- Cache stable/approved behaviors (low churn)
- TTL: 5 minutes
- Invalidate on approval/update
- Estimated additional improvement: 10-20%

### Implementation Plan

**Day 1-2**:
- [x] Analyze current queries and identify N+1 problems
- [ ] Implement `_fetch_behaviors_with_versions()` JOIN method
- [ ] Create migration `008_optimize_behavior_indexes.sql`
- [ ] Update `list_behaviors()` to use optimized query
- [ ] Run unit tests to confirm correctness

**Day 3**:
- [ ] Implement selective field projection
- [ ] Add integration tests for optimized queries
- [ ] Run load test: target P95 <100ms with 1000 requests

**Success Criteria**:
- ✅ P95 latency <100ms (currently 1315ms)
- ✅ Zero test failures (maintain correctness)
- ✅ Throughput >500 req/s (currently 168 req/s)

---

## WorkflowService Optimization (HIGH - 3.4x improvement needed)

### Current Performance
- P95 latency: 338.98ms
- P50 latency: 135.24ms
- Throughput: 32.55 req/s (lowest of all services!)
- Target: P95 <100ms

### Root Cause Analysis

**Current indexes on `workflow_templates`**:
```sql
✓ workflow_templates_pkey (template_id)
✓ idx_workflow_templates_created_at (created_at DESC)
✓ idx_workflow_templates_role_focus (role_focus)
✓ idx_workflow_templates_tags_gin (tags jsonb_path_ops)
```

**Likely issues**:
1. N+1 query problem with workflow_runs (similar to behaviors)
2. Large JSONB `template_data` column in SELECT *
3. Missing composite indexes for common filter combinations

### Optimization Strategy

#### Phase 1: Query Analysis
```bash
# Check what queries the load test triggers
podman exec -i amprealize-postgres-workflow psql -U amprealize_workflow -d workflows \
  -c "SELECT query, calls, mean_exec_time, max_exec_time
      FROM pg_stat_statements
      WHERE query LIKE '%workflow_templates%'
      ORDER BY mean_exec_time DESC LIMIT 10;"
```

#### Phase 2: Selective Field Projection
- Exclude large `template_data` JSONB from list queries
- Fetch full template only when template_id specified
- Expected improvement: 339ms → 200-250ms

#### Phase 3: Query Result Caching
- Workflow templates change infrequently
- Cache list results with 10-minute TTL
- Invalidate on template create/update
- Expected improvement: 200ms → <100ms

#### Phase 4: Pagination
- Implement LIMIT/OFFSET for large result sets
- Default page size: 50 templates
- Expected improvement: Prevents degradation as data grows

### Implementation Plan

**Day 4-5**:
- [ ] Enable `pg_stat_statements` extension
- [ ] Capture query patterns during load test
- [ ] Implement selective field projection
- [ ] Add `created_by_id` index if needed
- [ ] Run load test: target P95 <100ms

**Success Criteria**:
- ✅ P95 latency <100ms (currently 339ms)
- ✅ Throughput >200 req/s (currently 33 req/s)

---

## ActionService Optimization (MEDIUM - 1.6x improvement needed)

### Current Performance
- P95 latency: 161.02ms
- P50 latency: 78.59ms
- Throughput: 576.31 req/s (best of all services!)
- Target: P95 <100ms

### Current Index Coverage

ActionService already has comprehensive indexes:
```sql
✓ actions_pkey (action_id)
✓ idx_actions_actor_id (actor_id)
✓ idx_actions_behaviors_cited (behaviors_cited GIN)
✓ idx_actions_metadata (metadata GIN)
✓ idx_actions_related_run_id (related_run_id WHERE NOT NULL)
✓ idx_actions_replay_status (replay_status)
✓ idx_actions_timestamp (timestamp)
```

### Why Still Slow?

**1. Missing composite index for common queries**:
```sql
-- Load test likely queries: recent actions by actor
SELECT * FROM actions
WHERE actor_id = ?
ORDER BY timestamp DESC
LIMIT 100;

-- Current plan: Uses idx_actions_actor_id + sort
-- Optimal: Composite index avoiding sort
```

**2. Large JSONB columns in SELECT ***:
- `behaviors_cited` JSONB array
- `metadata` JSONB object
- Fetched even when not needed

### Optimization Strategy

#### Phase 1: Composite Indexes
```sql
-- For list queries with ordering
CREATE INDEX idx_actions_actor_timestamp
ON actions(actor_id, timestamp DESC);

-- For filtered queries
CREATE INDEX idx_actions_status_timestamp
ON actions(replay_status, timestamp DESC)
WHERE replay_status != 'NOT_STARTED';
```

#### Phase 2: Selective Fields
- List endpoint: Exclude `behaviors_cited` and `metadata`
- Detail endpoint: Fetch all fields
- Expected improvement: 161ms → 120ms

#### Phase 3: Result Limit
- Enforce default LIMIT 100 for list queries
- Require pagination for larger result sets
- Expected improvement: 120ms → <100ms

### Implementation Plan

**Day 6**:
- [ ] Add composite indexes
- [ ] Implement selective field projection
- [ ] Add query result limits
- [ ] Run load test: target P95 <100ms

**Success Criteria**:
- ✅ P95 latency <100ms (currently 161ms)
- ✅ Maintain throughput >500 req/s

---

## Validation Plan

### Load Test Execution
```bash
# After each optimization phase
pytest tests/load/test_service_load.py -v -s --concurrent=50 --total=1000

# Full validation with higher load
pytest tests/load/test_service_load.py -v -s --concurrent=100 --total=10000
```

### Regression Prevention
```bash
# Add performance regression tests
pytest tests/test_performance_regression.py -v

# CI integration: Fail if P95 exceeds thresholds
- BehaviorService: P95 must be <100ms
- WorkflowService: P95 must be <100ms
- ActionService: P95 must be <100ms
```

### Monitoring
- Set up Grafana alerts for P95 latency >100ms
- Track query execution plans via `pg_stat_statements`
- Monitor cache hit rates (when implemented)

---

## Timeline & Resources

| Phase | Services | Duration | Owner |
|-------|----------|----------|-------|
| **Sprint 1** | BehaviorService N+1 fix | 3 days | Engineering |
| **Sprint 1** | WorkflowService analysis | 2 days | Engineering |
| **Sprint 2** | WorkflowService optimization | 3 days | Engineering |
| **Sprint 2** | ActionService optimization | 2 days | Engineering |
| **Sprint 3** | Caching layer (optional) | 3-4 days | Engineering + DevOps |
| **Sprint 3** | Full validation & docs | 2 days | Engineering + DX |

**Total Timeline**: 2-3 sprints (4-6 weeks)

---

## Risk Mitigation

### Correctness Risks
- **Risk**: Query optimization breaks filtering logic
- **Mitigation**: Comprehensive parity tests must pass before/after

### Performance Risks
- **Risk**: Optimizations don't achieve target improvement
- **Mitigation**: Measure after each phase, adjust strategy

### Deployment Risks
- **Risk**: Index creation locks tables in production
- **Mitigation**: Use `CREATE INDEX CONCURRENTLY` (PostgreSQL 11+)

---

## Success Metrics

### Performance Targets (from RETRIEVAL_ENGINE_PERFORMANCE.md)
- ✅ All services P95 <100ms
- ✅ Health endpoint P95 <500ms (already passing: 456ms)
- ✅ Error rate <1% (already passing: 0%)
- ✅ Throughput >500 req/s for critical paths

### Code Quality
- ✅ Zero parity test failures
- ✅ Query execution plans documented
- ✅ Performance regression tests in CI

### Documentation
- ✅ Optimization strategies documented
- ✅ Index rationale captured in migrations
- ✅ Load test results updated in `LOAD_TEST_RESULTS.md`

---

## References

- **Baseline Metrics**: `docs/LOAD_TEST_RESULTS.md`
- **Performance Targets**: `RETRIEVAL_ENGINE_PERFORMANCE.md`
- **Database Schemas**: `schema/migrations/002_*.sql`, `003_*.sql`, `004_*.sql`
- **Service Code**: `amprealize/{behavior_service,workflow_service,action_service_postgres}.py`
- **Load Tests**: `tests/load/test_service_load.py`

---

## Next Steps

1. **Immediate (Day 1)**: Fix BehaviorService N+1 query problem
2. **Short-term (Week 1)**: Complete all service optimizations
3. **Mid-term (Week 2-3)**: Implement caching layer if needed
4. **Validation (Week 4)**: Full load testing and regression suite
