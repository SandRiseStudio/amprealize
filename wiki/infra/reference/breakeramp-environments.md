---
title: "BreakerAmp Environment Configuration"
type: reference
source_files:
  - config/breakeramp/environments.yaml
source_hash: auto
last_updated: "2026-04-09"
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

### Test

| Setting | Value |
|---------|-------|
| Podman Machine | `amprealize-test` |
| Blueprint | `local-test-suite` |
| Auto-teardown | Yes |

Test suite environment. Containers spin up fresh and tear down after each run for isolation.

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
