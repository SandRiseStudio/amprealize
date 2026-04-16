---
title: "How to Run Tests"
type: howto
source_files:
  - scripts/run_tests.sh
  - pytest.ini
source_hash: auto
last_updated: "2026-04-09"
applies_to:
  - dev
  - test
visibility: domain-knowledge
---

# How to Run Tests

Step-by-step guide for running the Amprealize test suite.

## Quick Start

```bash
# Run all tests (serial, safest)
./scripts/run_tests.sh

# Run with 2 parallel workers (recommended for laptops)
./scripts/run_tests.sh -n 2

# Validate environment only (no tests)
./scripts/run_tests.sh --check-only
```

## Using BreakerAmp

```bash
# Use BreakerAmp test environment
./scripts/run_tests.sh --breakeramp --env test

# Custom environment file
./scripts/run_tests.sh --breakeramp --env-file ./my-env.yaml
```

## Running Specific Test Categories

```bash
# Unit tests only (fast, no external deps)
pytest -m unit

# Integration tests only
pytest -m integration

# Skip slow tests
pytest -m "not slow"

# Postgres-dependent tests only
pytest -m postgres

# Smoke tests (staging validation)
pytest -m smoke
```

## Running with Kafka

```bash
# Enable Kafka module
./scripts/run_tests.sh --with-kafka
```

## Legacy Per-Service Database Mode

```bash
# Use separate databases per service (legacy)
AMPREALIZE_TEST_PER_SERVICE_PG_DATABASES=1 ./scripts/run_tests.sh
```

## CI Configuration

```bash
# Auto-detect cores, load-balanced by file
pytest -n auto --dist=loadfile
```

## Troubleshooting

### Tests timing out

Default timeout is 60 seconds per test. If tests consistently time out:
- Check for missing `@pytest.mark.slow` on long-running tests
- Verify database connectivity (`--check-only`)
- Check container health: `podman ps`

### Database connection refused

1. Ensure containers are running: `podman compose -f infra/docker-compose.test.yml up -d`
2. Verify port availability: `lsof -i :6433`
3. Check modular vs. per-service mode matches your compose file

### Coverage below threshold

Minimum coverage threshold is 70%. Check report:
```bash
pytest --cov=amprealize --cov-report=html
open htmlcov/index.html
```

## See Also

- [run_tests.sh Reference](../reference/run-tests-sh.md)
- [pytest.ini Configuration](../reference/pytest-ini.md)
- [Docker Compose Test Stack](../architecture/docker-compose-test.md)
