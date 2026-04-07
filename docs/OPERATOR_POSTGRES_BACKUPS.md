# Operator runbook: PostgreSQL backups (Amprealize)

This document is for **operators** maintaining Postgres used by Amprealize. It is **not** automated from this repository; schedule and run these steps in your environment (cron, backup appliance, or managed DB snapshots).

**Reference layout:** [infra/docker-compose.postgres.yml](../infra/docker-compose.postgres.yml) (dev-style multi-database stack). Production may use a single instance, RDS, or Cloud SQL—adapt host, user, and volume names accordingly.

---

## Principles

1. **Encrypt backups at rest** and restrict access (least privilege; separate backup role if possible).
2. **Test restores** regularly on a non-production host; an untested backup is a guess.
3. **Retain** per your policy (e.g. daily 7d, weekly 4w, monthly 12m).
4. **Coordinate** with application deploys: note schema migration version (Alembic / `schema/migrations`) in run notes when relevant.

---

## Logical backups with `pg_dump`

### One database from the host (TCP)

Replace connection parameters with values from your `.env` or compose file.

```bash
# Example: behavior service DB (compose maps host 5433 -> container 5432)
export PGPASSWORD='dev_behavior_pass'
pg_dump -h localhost -p 5433 -U amprealize_behavior -d behaviors \
  -Fc -f "behaviors_$(date -u +%Y%m%dT%H%M%SZ).dump"
```

Custom format (`-Fc`) works well with `pg_restore` and parallel restore.

### All logical DBs in the dev compose file (loop)

From the repo root, after containers are healthy:

```bash
# Telemetry (default compose port 5432)
PGPASSWORD=dev_telemetry_pass pg_dump -h localhost -p 5432 -U amprealize_telemetry -d telemetry -Fc -f "telemetry_$(date -u +%Y%m%dT%H%M%SZ).dump"

# Behavior (5433)
PGPASSWORD=dev_behavior_pass pg_dump -h localhost -p 5433 -U amprealize_behavior -d behaviors -Fc -f "behaviors_$(date -u +%Y%m%dT%H%M%SZ).dump"

# Add other services from docker-compose.postgres.yml the same way.
```

### Exec inside the container (no host `pg_dump` required)

```bash
podman exec -t amprealize-postgres-behavior \
  pg_dump -U amprealize_behavior -d behaviors -Fc > "behaviors_$(date -u +%Y%m%dT%H%M%SZ).dump"
```

Use `docker exec` instead of `podman exec` if you use Docker.

---

## Restore (sanity check on a scratch instance)

**Never** overwrite production without a maintenance window and approval.

```bash
pg_restore --clean --if-exists -h localhost -p 5433 -U amprealize_behavior -d behaviors behaviors_YYYYMMDD.dump
```

`--clean` drops objects before recreate; use a **dedicated restore database** first if unsure.

---

## Physical / volume backups

If data lives in a named volume (e.g. `postgres-behavior-data` in compose):

- Snapshot the underlying volume or disk **while Postgres is consistent** (stop container briefly, or use filesystem snapshots + `pg_backup_start`/`pg_backup_stop` on self-managed Postgres).
- Managed clouds: prefer **automated instance backups** and **point-in-time recovery** from the provider.

---

## Related docs

- [TESTING_GUIDE.md](TESTING_GUIDE.md) — local test Postgres/Redis stack (`infra/docker-compose.test.yml`).
- [SECRETS_MANAGEMENT_PLAN.md](SECRETS_MANAGEMENT_PLAN.md) — handling credentials for backup jobs.
