---
title: "Docker Compose Test Stack"
type: architecture
source_files:
  - infra/docker-compose.test.yml
  - infra/docker-compose.postgres.yml
  - infra/Dockerfile.core.simple
source_hash: auto
last_updated: "2026-04-09"
applies_to:
  - dev
  - test
visibility: domain-knowledge
---

# Docker Compose Test Stack

Container orchestration for local development and testing. Uses Podman as the container runtime.

## Compose Files

### docker-compose.test.yml (Primary)

Modular monolith layout — single Postgres instance for all services.

| Service | Image | Port | Database | User |
|---------|-------|------|----------|------|
| postgres-behavior-test | TimescaleDB | 6433 | behavior_test | behavior_test |

Optional per-service DBs (activate via `profiles: [per-service-db]`):

| Service | Port | Database |
|---------|------|----------|
| postgres-workflow-test | 6434 | workflow_test |
| postgres-action-test | 6435 | action_test |
| postgres-run-test | 6436 | run_test |
| postgres-compliance-test | 6437 | compliance_test |

**Resource limits** (test): 0.5 CPU, 256MB memory per container.

### docker-compose.postgres.yml (Dev Reference)

Full multi-service development setup.

| Service | Image | Port | Database |
|---------|-------|------|----------|
| postgres-telemetry | TimescaleDB | 5432 | telemetry_test |
| postgres-behavior | TimescaleDB | 5433 | behaviors |
| postgres-workflow | Postgres:16-alpine | 5434 | workflows |

## Dockerfile (Dockerfile.core.simple)

Production-ready minimal image:

| Setting | Value |
|---------|-------|
| Base | `python:3.11-slim` |
| User | `amprealize` (UID 1000) |
| Installs | core + telemetry, postgres, redis extras |
| Healthcheck | `GET /health` |
| Port | 8000 |
| Workers | 2 (Uvicorn) |

## Networking

- **Test**: All services in `amprealize-test-net`
- **Dev**: All services in `amprealize-postgres-net`
- Named volumes for persistent data (e.g., `postgres-behavior-test-data`)

## Healthchecks

All Postgres services use `pg_isready`:
- Interval: 10s
- Timeout: 5s
- Retries: 5

## Entrypoint Script

`infra/scripts/entrypoint.sh`:
- Initializes DuckDB warehouse if schema file present
- Supports `WAREHOUSE_DB` and `SCHEMA_FILE` env vars
- Passes through to main command (uvicorn)

## See Also

- [BreakerAmp Environments](../reference/breakeramp-environments.md)
- [run_tests.sh Reference](../reference/run-tests-sh.md)
