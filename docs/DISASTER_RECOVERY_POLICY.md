# Disaster Recovery Policy

**Last Updated:** 2025-11-12
**Owner:** DevOps Team
**Review Cycle:** Quarterly

## Service Tier Classification

### Tier 1 - Critical (Control Plane)
**Services:** BehaviorService, RunService, ActionService, ComplianceService
**RTO:** 15 minutes
**RPO:** 5 minutes
**Justification:** Core orchestration; user workflows blocked without these

### Tier 2 - High Priority (Analytics & Auth)
**Services:** MetricsService, ReflectionService, AgentAuthService, TaskService
**RTO:** 1 hour
**RPO:** 15 minutes
**Justification:** Analytics can tolerate short gaps; auth failures block new sessions only

### Tier 3 - Standard (Supporting Services)
**Services:** WorkflowService, TraceAnalysisService, AgentOrchestratorService
**RTO:** 4 hours
**RPO:** 1 hour
**Justification:** Degraded UX acceptable short-term; no immediate workflow blocker

### Tier 4 - Best Effort (Advanced Features)
**Services:** FineTuningService, AgentReviewService, AdvancedRetrievalService, APIRateLimitingService, MultiTenantService, CollaborationService
**RTO:** 24 hours
**RPO:** 4 hours
**Justification:** Premium features; users can retry after recovery

## Data Store Targets

| Store | Tier | RTO | RPO | Backup Frequency | Retention |
|-------|------|-----|-----|------------------|-----------|
| PostgreSQL (behaviors, workflows, auth, tasks, telemetry) | 1 | 15 min | 5 min | Continuous WAL archival + hourly snapshots | 30 days snapshots, 7 days WAL |
| Redis (sessions, cache) | 2 | 1 hour | 15 min | Every 15 min (RDB) | 7 days |
| DuckDB (analytics warehouse) | 2 | 1 hour | 15 min | Hourly exports to S3 | 90 days |
| File Storage (behaviors, artifacts) | 1 | 15 min | 5 min | Real-time replication to S3 | 90 days versioning |

## Recovery Procedures

### Tier 1 Failure (Critical)
1. **Detection:** <5 min (health checks fail 3 consecutive times)
2. **Notification:** PagerDuty alert to on-call + Slack #incidents
3. **Failover:** Automatic to standby region (AWS RDS Multi-AZ, Redis replica)
4. **Validation:** Run smoke tests from `scripts/validate_staging.sh`
5. **Comms:** Status page update within 10 min

### Tier 2/3 Failure (High/Standard)
1. **Detection:** <15 min (scheduled health checks)
2. **Notification:** Slack #ops-alerts
3. **Failover:** Manual runbook execution (scripted)
4. **Validation:** Service-specific smoke tests
5. **Comms:** Status page update within 30 min

### Tier 4 Failure (Best Effort)
1. **Detection:** <1 hour (user reports or scheduled checks)
2. **Notification:** Ticket creation in ops queue
3. **Failover:** Standard deployment from last known good state
4. **Validation:** Integration tests
5. **Comms:** In-app banner or email to affected users

## Backup Strategy

### PostgreSQL
- **Method:** Continuous WAL archiving + automated base backups
- **Tool:** `pg_basebackup` + WAL-G or AWS RDS automated backups
- **Storage:** S3 with lifecycle policy (30d → Glacier, 90d → delete)
- **Test:** Monthly restore drill to staging environment

### Redis
- **Method:** RDB snapshots + AOF append-only file
- **Frequency:** Every 15 minutes (RDB), continuous (AOF)
- **Storage:** S3 with 7-day retention
- **Test:** Weekly restore to local Redis instance

### DuckDB
- **Method:** Export to Parquet + full database file backup
- **Frequency:** Hourly
- **Storage:** S3 with 90-day retention
- **Test:** Bi-weekly query validation against restored warehouse

### File Storage
- **Method:** S3 versioning + cross-region replication
- **Frequency:** Real-time
- **Retention:** 90 days (versioned objects)
- **Test:** Monthly restore spot-check (10 random files)

## Failover Testing Schedule

| Test Type | Frequency | Duration | Success Criteria |
|-----------|-----------|----------|------------------|
| Database failover (PostgreSQL) | Monthly | 2 hours | RTO <15 min, RPO <5 min, all smoke tests pass |
| Cache failover (Redis) | Monthly | 1 hour | RTO <1 hour, sessions persist or gracefully re-auth |
| Full DR drill (all tiers) | Quarterly | 4 hours | All services recover within tier RTOs, data loss within RPOs |
| Backup restore validation | Weekly | 30 min | Random sample restores successfully with data integrity checks |

## Monitoring & Alerting

### Health Checks
- **Interval:** 1 minute (Tier 1), 5 minutes (Tier 2/3), 15 minutes (Tier 4)
- **Timeout:** 10 seconds
- **Failure Threshold:** 3 consecutive failures

### Backup Monitoring
- **Metrics:** Backup success rate, backup duration, restore test results
- **Alerts:**
  - Backup failed (critical)
  - Backup >2x expected duration (warning)
  - Restore test failed (critical)

### RTO/RPO Compliance
- **Dashboard:** Grafana panel tracking actual vs. target recovery times
- **SLO:** 99% of incidents recover within tier RTO
- **Review:** Incidents exceeding RTO trigger post-mortem

## Runbook Index

1. [PostgreSQL Failover](#postgresql-failover-runbook)
2. [Redis Failover](#redis-failover-runbook)
3. [DuckDB Restore](#duckdb-restore-runbook)
4. [Full Region Failover](#region-failover-runbook)
5. [Data Corruption Recovery](#data-corruption-recovery)

---

## PostgreSQL Failover Runbook

**Trigger:** Primary PostgreSQL unavailable >3 health check failures
**RTO Target:** 15 minutes
**Prerequisites:** Multi-AZ RDS or read replica configured

### Automated Steps (via `amprealize dr failover --service postgres`)

1. **Detect failure:**
   ```bash
   # Health check fails
   pg_isready -h $POSTGRES_PRIMARY -p 5432 || echo "FAIL"
   ```

2. **Promote replica:**
   ```bash
   # AWS RDS
   aws rds promote-read-replica --db-instance-identifier amprealize-replica

   # Self-hosted
   pg_ctl promote -D /var/lib/postgresql/data
   ```

3. **Update connection strings:**
   ```bash
   # Update DNS or load balancer to point to new primary
   aws route53 change-resource-record-sets --hosted-zone-id Z123 \
     --change-batch file://failover-dns.json
   ```

4. **Validate:**
   ```bash
   ./scripts/validate_staging.sh --service postgres
   ```

5. **Alert resolution:**
   ```bash
   amprealize dr notify --status resolved --service postgres
   ```

### Manual Steps (if automation fails)

1. Connect to replica: `psql -h replica.internal -U amprealize_admin`
2. Check replication lag: `SELECT pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn();`
3. If lag <5 min, promote: `SELECT pg_promote();`
4. Update app configs with new primary endpoint
5. Restart services: `podman-compose restart`

**Rollback:** If failover causes issues, restore from last backup (see backup restore runbook)

---

## Redis Failover Runbook

**Trigger:** Redis primary unavailable >3 health check failures
**RTO Target:** 1 hour (sessions can be rebuilt)

### Automated Steps

1. **Promote replica:**
   ```bash
   redis-cli -h redis-replica SLAVEOF NO ONE
   ```

2. **Update configs:**
   ```bash
   export CACHE__REDIS_URL=redis://redis-replica:6379/0
   amprealize dr reload-config
   ```

3. **Validate:**
   ```bash
   redis-cli -h redis-replica PING
   amprealize dr test --service cache
   ```

---

## DuckDB Restore Runbook

**Trigger:** DuckDB corrupted or analytics queries failing
**RTO Target:** 1 hour

### Steps

1. **Download latest backup:**
   ```bash
   aws s3 cp s3://amprealize-backups/duckdb/latest.parquet /tmp/
   ```

2. **Restore:**
   ```python
   import duckdb
   conn = duckdb.connect('data/telemetry.duckdb')
   conn.execute("CREATE TABLE telemetry_backup AS SELECT * FROM '/tmp/latest.parquet'")
   conn.execute("DROP TABLE telemetry; ALTER TABLE telemetry_backup RENAME TO telemetry")
   ```

3. **Validate:**
   ```bash
   amprealize dr test --service analytics
   ```

---

## Region Failover Runbook

**Trigger:** Full region outage (AWS us-west-2 unavailable)
**RTO Target:** 4 hours (manual coordination required)

### Steps

1. **DNS cutover:**
   ```bash
   aws route53 change-resource-record-sets \
     --hosted-zone-id Z123 \
     --change-batch file://region-failover.json
   ```

2. **Restore services in secondary region:**
   ```bash
   cd deployment/
   ./deploy_to_region.sh us-east-1
   ```

3. **Restore data:**
   - PostgreSQL: Restore from S3 WAL archive
   - Redis: Rebuild from PostgreSQL session data
   - DuckDB: Restore from S3 Parquet exports

4. **Validate end-to-end:**
   ```bash
   ./scripts/validate_staging.sh --region us-east-1
   ```

5. **Monitor:**
   - Check Datadog for increased error rates
   - Confirm user traffic shifts to new region

---

## Data Corruption Recovery

**Trigger:** Logical data corruption detected (bad migrations, bugs)
**RPO Target:** 5 minutes (Tier 1), 15 minutes (Tier 2)

### Steps

1. **Identify corruption scope:**
   ```sql
   -- Example: Find corrupt behavior records
   SELECT * FROM behaviors WHERE updated_at > NOW() - INTERVAL '1 hour'
     AND (name IS NULL OR definition IS NULL);
   ```

2. **Point-in-time restore:**
   ```bash
   # PostgreSQL
   aws rds restore-db-instance-to-point-in-time \
     --source-db-instance amprealize-prod \
     --target-db-instance amprealize-recovery \
     --restore-time 2025-11-12T14:30:00Z
   ```

3. **Extract clean data:**
   ```bash
   pg_dump -h recovery.internal -U amprealize_admin \
     -t behaviors -t runs -t actions > clean_data.sql
   ```

4. **Apply to production:**
   ```bash
   psql -h prod.internal -U amprealize_admin < clean_data.sql
   ```

5. **Validate:**
   ```bash
   amprealize dr test --service behaviors --smoke-test
   ```

---

## Incident Response Contacts

| Role | Primary | Secondary | Escalation |
|------|---------|-----------|------------|
| On-Call DevOps | @devops-oncall | @devops-lead | CTO |
| Database Admin | @dba-primary | @dba-secondary | VP Eng |
| Security | @security-oncall | CISO | CEO |
| Communications | @comms-lead | CMO | CEO |

**PagerDuty:** https://amprealize.pagerduty.com
**Status Page:** https://status.amprealize.com
**War Room:** Slack #incident-response
