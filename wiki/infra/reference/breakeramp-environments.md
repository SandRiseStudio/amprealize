---
title: "BreakerAmp Environment Configuration"
type: reference
source_files:
  - infra/environments.yaml
source_hash: auto
last_updated: "2026-05-05"
applies_to:
  - dev
  - test
  - staging
visibility: domain-knowledge
---

# BreakerAmp Environment Configuration

Single source of truth for infrastructure provisioning and environment-specific variables. The `run_tests.sh` script parses this file to set database DSNs, credentials, and service ports.

## Environments

### Development

| Setting | Value |
|---------|-------|
| Podman Machine | `amprealize-dev` |
| Blueprint | `local-dev` |
| Auto-teardown | No |

Local development environment. Containers persist between runs for fast iteration.

BreakerAmp aligns the host default Podman connection to the machine for the environment you applied (`amprealize-dev` for development, **cloud-dev**, **neon**, and **test**).

### Test

| Setting | Value |
|---------|-------|
| Podman Machine | `amprealize-dev` (same VM as dev; stop other stacks on :8080/:8000 before applying **test** if ports collide) |
| Blueprint | `local-test-env` (distinct from `local-dev` / `local-test-suite`; test-scoped Docker volume names) |
| Active modules | `core`, `console`, `whiteboard` (same subset as development; no extra services vs dev) |
| Auto-teardown | Yes |

Test suite environment: Postgres + telemetry + Redis + **gateway (8080)** + API + web console + whiteboard sidecar, for pytest and `run_load_test_console_hot_paths.sh` against `http://localhost:8080`. Containers tear down after each run.

### Staging

| Setting | Value |
|---------|-------|
| Memory Limit | 4096 MB |
| Compliance Tier | Strict |
| Lifetime | 4 hours |

High-compliance environment for pre-production validation.

## Key Variables (Test Environment)

| Variable | Value |
|----------|-------|
| `AMPREALIZE_PG_USER_BEHAVIOR` | `amprealize_test` |
| `AMPREALIZE_PG_PASS_BEHAVIOR` | `amprealize_dev` |
| `AMPREALIZE_PG_DB_BEHAVIOR` | `amprealize_test` |
| `AMPREALIZE_PG_PORT_BEHAVIOR` | `5432` (modular monolith) |
| Telemetry DB Port | `5433` (separate TimescaleDB) |
| Redis | `localhost:6379` |

## Runtime Configuration

- **Provider**: Podman (all environments)
- **Auto-start machines**: `true`
- **Memory limits**: Staging only (4096 MB)
- **Blueprint IDs**: Map to specific Docker Compose configurations

## See Also

- [run_tests.sh Reference](run-tests-sh.md)
- [Docker Compose Test Stack](../architecture/docker-compose-test.md)
