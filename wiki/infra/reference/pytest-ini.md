---
title: "pytest.ini Configuration"
type: reference
source_files:
  - pytest.ini
source_hash: auto
last_updated: "2026-04-09"
applies_to:
  - dev
  - test
visibility: domain-knowledge
---

# pytest.ini Configuration

Pytest settings for test discovery, timeout management, parallel execution, and test categorization.

## Test Discovery

| Setting | Value |
|---------|-------|
| Test paths | `tests/` |
| File pattern | `test_*.py` |
| Class pattern | `Test*` |
| Function pattern | `test_*` |

## Timeout Settings

| Setting | Value |
|---------|-------|
| Hard limit | 60 seconds per test |
| Method | Thread-based (better container compatibility) |
| Warning threshold | 30 seconds |

The warning threshold is configurable via `QUERY_TIMEOUT` environment variable.

## Test Markers

| Marker | Description | Example |
|--------|-------------|---------|
| `slow` | Long-running tests | Skip with `-m "not slow"` |
| `integration` | Requires external services | DB, Redis, etc. |
| `postgres` | Requires PostgreSQL | |
| `redis` | Requires Redis | |
| `kafka` | Requires Kafka | |
| `unit` | Pure unit, no external deps | |
| `parity` | Cross-surface consistency | |
| `load` | Performance/load tests | |
| `production` | Production-level resources | Long duration |
| `manual` | Requires user interaction | Device flow auth |
| `smoke` | Staging validation | |
| `requires_services` | Generic external service | |

## Output & Coverage

| Setting | Value |
|---------|-------|
| Summary | `-ra` (all outcomes) |
| Markers | `--strict-markers` (fail on unknown) |
| Traceback | `--tb=short` (concise) |
| Locals | `--showlocals` (on failure) |
| Coverage threshold | 70% (`--cov-fail-under=70`) |
| Coverage report | HTML + terminal |

## Parallel Execution

| Context | Command | Notes |
|---------|---------|-------|
| Default | `pytest` | Serial, safest |
| Local dev | `pytest -n 2` | 2 workers recommended |
| CI | `pytest -n auto` | Auto-detect cores |
| Distribution | `--dist=loadfile` | Group by file to reduce DB contention |

## See Also

- [run_tests.sh Reference](run-tests-sh.md)
- [How to Run Tests](../howto/run-tests.md)
