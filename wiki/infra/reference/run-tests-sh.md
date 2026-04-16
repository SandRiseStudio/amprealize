---
title: "run_tests.sh — Test Runner"
type: reference
source_files:
  - scripts/run_tests.sh
source_hash: auto
last_updated: "2026-04-09"
applies_to:
  - dev
  - test
visibility: domain-knowledge
---

# run_tests.sh — Test Runner

Comprehensive Bash test orchestrator for Amprealize that manages test infrastructure, database DSNs, and pytest execution.

## Execution Modes

| Mode | Command | Use Case |
|------|---------|----------|
| Serial (default) | `./scripts/run_tests.sh` | Safest, no parallel contention |
| Parallel | `./scripts/run_tests.sh -n 2` | 2 workers (recommended for laptops) |
| Check only | `./scripts/run_tests.sh --check-only` | Validate environment without running tests |
| BreakerAmp | `./scripts/run_tests.sh --breakeramp --env test` | Use BreakerAmp environment blueprint |

## Key Flags

| Flag | Description |
|------|-------------|
| `--breakeramp` | Enable BreakerAmp infrastructure mode |
| `--env <name>` | Specify environment (default: `ci`) |
| `--env-file <path>` | Override environment manifest path |
| `--with-kafka` | Enable Kafka module for test run |
| `-n <N>` | Parallel workers (passed to pytest-xdist) |
| `--check-only` | Validate environment, skip test execution |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AMPREALIZE_COMPOSE_BIN` | `podman compose` | Container runtime override |
| `AMPREALIZE_TEST_PER_SERVICE_PG_DATABASES` | `0` | Set `1` for legacy per-service DB layout |
| `COMPOSE_PROFILES` | (none) | Activate compose profiles (e.g., `per-service-db`) |

## Database Configuration

### Modular Monolith (Default)

All services share one Postgres instance at `localhost:6433`. This is the recommended layout for local development and CI.

### Per-Service (Legacy)

Optional separate databases for each service domain (behavior, workflow, action, run, compliance, auth, telemetry, metrics). Enable via `AMPREALIZE_TEST_PER_SERVICE_PG_DATABASES=1`.

### DSN Construction

- Connection timeout: 5s
- Query timeout: 30s (statement_timeout)
- Search path and timeouts encoded in DSN options
- **Safety check**: Rejects production DB names to prevent data destruction
- BreakerAmp mode bypasses safety check (containers are isolated)

## Service DSNs

The script configures DSNs for: Behavior, Workflow, Action, Run, Compliance, Auth, Telemetry, Metrics, and Board databases.

## See Also

- [pytest.ini Configuration](pytest-ini.md)
- [BreakerAmp Environments](breakeramp-environments.md)
- [Docker Compose Test Stack](../architecture/docker-compose-test.md)
