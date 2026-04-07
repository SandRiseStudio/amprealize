# Embedding Rollout Rollback Runbook

> **Last Updated**: 2025-11-24
> **Behaviors**: `behavior_instrument_metrics_pipeline`, `behavior_curate_behavior_handbook`
> **Epic**: 8.10.1 Task 8 - Production Rollout
> **Status**: ✅ ROLLOUT COMPLETE (100% traffic on all-MiniLM-L6-v2)
> **SLO Targets**: P95 <250ms | Memory <750MB | Cache >30% | Error Rate <5%

## Overview

**🎉 Rollout Complete**: As of 2025-11-24, 100% of behavior retrieval traffic is served by the all-MiniLM-L6-v2 model. This runbook is retained for emergency rollback if quality regressions are detected in production.

This runbook documents the rollback procedure for the embedding model (all-MiniLM-L6-v2 → BGE-M3 baseline). Use this when SLO breaches or quality regressions are detected.

---

## Quick Rollback Command

```bash
# Emergency rollback: Route 100% traffic back to BGE-M3 baseline
export EMBEDDING_ROLLOUT_PERCENTAGE=0

# Restart affected services
breakeramp apply --env staging --module behavior-service
# OR manually:
podman restart amprealize-behavior-service
```

---

## Rollback Decision Tree

```
┌────────────────────────────────────────────────────────────────┐
│                    ALERT FIRED OR ANOMALY DETECTED             │
└────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────────┐
│ Is P95 latency > 250ms for > 5 minutes?                        │
│ OR Memory > 750MB for > 2 minutes?                             │
│ OR Error rate > 5% for > 5 minutes?                            │
└────────────────────────────────────────────────────────────────┘
                               │
              ┌────────────────┴────────────────┐
              │ YES                             │ NO
              ▼                                 ▼
┌──────────────────────────┐    ┌──────────────────────────────┐
│ IMMEDIATE ROLLBACK       │    │ Is cache hit rate < 30%      │
│ Set EMBEDDING_ROLLOUT_   │    │ for > 10 minutes?            │
│ PERCENTAGE=0             │    │ OR Degraded mode > 10%?      │
│ Restart services         │    └──────────────────────────────┘
│ Create incident ticket   │                   │
└──────────────────────────┘       ┌───────────┴───────────┐
                                   │ YES                   │ NO
                                   ▼                       ▼
                   ┌─────────────────────────┐  ┌─────────────────┐
                   │ INVESTIGATE + ROLLBACK  │  │ MONITOR         │
                   │ Reduce rollout % by 50% │  │ Continue        │
                   │ Check root cause        │  │ observation     │
                   └─────────────────────────┘  └─────────────────┘
```

---

## Rollback Phases

### Phase 1: Immediate Rollback (< 5 minutes)

**Trigger**: Critical SLO breach (latency, memory, or error rate)

1. **Set rollout to 0%**:
   ```bash
   # Update environment variable
   sed -i 's/EMBEDDING_ROLLOUT_PERCENTAGE=.*/EMBEDDING_ROLLOUT_PERCENTAGE=0/' \
       deployment/staging.env

   # Verify change
   grep EMBEDDING_ROLLOUT_PERCENTAGE deployment/staging.env
   ```

2. **Restart behavior service**:
   ```bash
   # Via BreakerAmp (recommended)
   breakeramp apply --env staging --module behavior-service --force

   # Via Podman directly
   podman restart amprealize-behavior-service

   # Verify restart
   podman logs --tail 50 amprealize-behavior-service
   ```

3. **Confirm baseline restoration**:
   ```bash
   # Check model in use via metrics endpoint
   curl -s http://localhost:8001/metrics | grep amprealize_retrieval_requests_total
   # Should show model_name="BAAI/bge-m3" only
   ```

4. **Notify team**:
   - Create incident ticket with timeline
   - Post to #amprealize-alerts channel
   - Tag on-call engineer

### Phase 2: Gradual Rollback (< 30 minutes)

**Trigger**: Warning-level issues (cache degradation, degraded mode spike)

1. **Reduce rollout percentage by 50%**:
   ```bash
   # If at 100%, reduce to 50%
   # If at 50%, reduce to 25%
   # If at 25%, reduce to 10%
   # If at 10%, reduce to 0%

   CURRENT=$(grep EMBEDDING_ROLLOUT_PERCENTAGE deployment/staging.env | cut -d= -f2)
   NEW=$((CURRENT / 2))
   sed -i "s/EMBEDDING_ROLLOUT_PERCENTAGE=.*/EMBEDDING_ROLLOUT_PERCENTAGE=$NEW/" \
       deployment/staging.env
   ```

2. **Apply change and monitor**:
   ```bash
   breakeramp apply --env staging --module behavior-service

   # Watch metrics for 10 minutes
   watch -n 30 'curl -s http://localhost:8001/metrics | grep amprealize_retrieval'
   ```

3. **If issue persists, continue to Phase 1 (full rollback)**

### Phase 3: Root Cause Analysis (Post-Rollback)

1. **Capture diagnostic data**:
   ```bash
   # Export recent metrics
   curl "http://localhost:9090/api/v1/query_range?query=amprealize_retrieval_latency_seconds_bucket&start=$(date -d '1 hour ago' +%s)&end=$(date +%s)&step=60" > metrics_dump.json

   # Capture container stats
   podman stats --no-stream amprealize-behavior-service > container_stats.txt

   # Save recent logs
   podman logs --since 1h amprealize-behavior-service > service_logs.txt
   ```

2. **Document findings**:
   - Timeline of events
   - Alert that triggered rollback
   - Metrics at time of rollback
   - Suspected root cause
   - Remediation actions

3. **Update rollout plan** before re-attempting:
   - Address identified issues
   - Adjust SLO thresholds if needed
   - Add monitoring coverage gaps

---

## SLO Thresholds Reference

| Metric | Alert Threshold | Rollback Threshold | Duration |
|--------|-----------------|-------------------|----------|
| P95 Latency | > 250ms | > 300ms | 5 min |
| Memory | > 750MB | > 800MB | 2 min |
| Error Rate | > 5% | > 10% | 5 min |
| Cache Hit Rate | < 30% | < 20% | 10 min |
| Degraded Mode | > 10% | > 20% | 10 min |
| Model Load Count | > 1 | > 2 | 1 min |

---

## Monitoring Queries

### Prometheus Queries for Rollback Decision

```promql
# P95 Latency by model (should be <250ms)
histogram_quantile(0.95, sum(rate(amprealize_retrieval_latency_seconds_bucket[5m])) by (le, model_name))

# Memory by model (should be <750MB)
amprealize_embedding_model_memory_bytes

# Error rate (should be <5%)
sum(rate(amprealize_retrieval_failures_total[5m])) / sum(rate(amprealize_retrieval_requests_total[5m]))

# Cache hit rate (should be >30%)
sum(rate(amprealize_retrieval_cache_hits_total[10m])) /
(sum(rate(amprealize_retrieval_cache_hits_total[10m])) + sum(rate(amprealize_retrieval_cache_misses_total[10m])))

# Traffic split between models (A/B cohort)
sum(rate(amprealize_retrieval_requests_total[5m])) by (model_name)
```

### Grafana Dashboard Panels to Check

1. **Embedding Latency P95** - deployment/grafana/dashboards/embedding_dashboard.json
2. **Memory Footprint** - Should show step-down after rollback
3. **Model Traffic Split** - Verify all traffic routes to baseline
4. **Error Rate by Model** - Identify which model caused errors

---

## Environment-Specific Rollback

### Development (MacBook Air / Low-Resource)

```bash
# Development uses lazy loading by default, rollback rarely needed
# If needed:
export EMBEDDING_MODEL_LAZY_LOAD=true
export EMBEDDING_MODEL_NAME="sentence-transformers/all-MiniLM-L6-v2"
# Note: Development always uses new model to conserve resources
```

### Staging

```bash
# Standard rollback
export EMBEDDING_ROLLOUT_PERCENTAGE=0
breakeramp apply --env staging --module behavior-service
```

### Production (Future)

```bash
# Production requires change management approval
# 1. Create change request in ITSM
# 2. Get approval from service owner
# 3. Execute during maintenance window if possible
export EMBEDDING_ROLLOUT_PERCENTAGE=0
breakeramp apply --env production --module behavior-service
# 4. Monitor for 30 minutes
# 5. Close change request with results
```

---

## Post-Rollback Checklist

- [ ] Verify `EMBEDDING_ROLLOUT_PERCENTAGE=0` in environment file
- [ ] Confirm behavior service restarted
- [ ] Check metrics show only baseline model (`model_name="BAAI/bge-m3"`)
- [ ] Verify P95 latency returned to acceptable range
- [ ] Verify memory usage normalized
- [ ] Create incident ticket with timeline
- [ ] Update `WORK_STRUCTURE.md` rollout status
- [ ] Schedule root cause analysis meeting
- [ ] Document lessons learned

---

## Recovery: Re-attempting Rollout

After resolving the root cause:

1. **Start at lower percentage** than when rollback occurred:
   ```bash
   # If rolled back from 50%, restart at 10%
   export EMBEDDING_ROLLOUT_PERCENTAGE=10
   ```

2. **Extend observation window**:
   - 10% phase: 48 hours (instead of 24)
   - 50% phase: 36 hours (instead of 24)

3. **Add targeted monitoring** for the specific failure mode

4. **Update this runbook** with lessons learned

---

## Contact & Escalation

| Role | Contact | When to Escalate |
|------|---------|------------------|
| On-Call Engineer | #amprealize-oncall | Any SLO breach |
| Service Owner | @behavior-team | Repeated rollbacks |
| Platform Team | #platform-support | Infrastructure issues |
| Data Science | @ml-team | Quality regression (nDCG@5 drop) |

---

## Related Documentation

- [WORK_STRUCTURE.md](../WORK_STRUCTURE.md) - Epic 8.10.1 progress tracking
- [deployment/prometheus/embedding_alerts.yml](../deployment/prometheus/embedding_alerts.yml) - Alert definitions
- [docs/MONITORING_GUIDE.md](MONITORING_GUIDE.md) - Metrics catalog
- [RETRIEVAL_ENGINE_PERFORMANCE.md](contracts/RETRIEVAL_ENGINE_PERFORMANCE.md) - SLO definitions
- [environments.yaml](../environments.yaml) - Environment configurations
