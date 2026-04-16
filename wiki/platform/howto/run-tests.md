---
title: "Running Tests"
type: howto
last_updated: 2026-04-14
applies_to:
  - dev
  - test
tags:
  - testing
  - pytest
  - breakeramp
  - ci
---

# Running Tests

Amprealize uses **pytest** with markers to separate test tiers. For CI or
infrastructure-dependent tests, use `run_tests.sh` with BreakerAmp.

## Quick Start

```bash
# Run all unit tests (no DB or infra needed)
pytest -m unit

# Run a specific test file
pytest tests/test_behavior_service.py

# Run with verbose output
pytest -m unit -v
```

## Test Markers

| Marker | Requires | Description |
|--------|----------|-------------|
| `unit` | Nothing | Pure logic tests, mocked dependencies |
| `integration` | Database | Tests against real Postgres/SQLite |
| `parity` | Database | Cross-surface consistency tests |
| `slow` | Varies | Tests that take >5 seconds |
| `e2e` | Full stack | End-to-end workflow tests |

Run by marker:
```bash
pytest -m unit                    # Fast, no infra
pytest -m integration             # Needs DB
pytest -m "not slow"              # Skip slow tests
pytest -m "unit or integration"   # Both tiers
```

## Using run_tests.sh

The test runner script handles infrastructure setup, especially when using BreakerAmp:

```bash
# Standard run
./scripts/run_tests.sh

# With BreakerAmp (spins up Postgres in container)
./scripts/run_tests.sh --breakeramp

# Specific markers
./scripts/run_tests.sh --markers unit

# Fresh environment (destroys and recreates)
./scripts/run_tests.sh --breakeramp --fresh
```

BreakerAmp mode:
1. Runs `breakeramp plan --blueprint test` to check infrastructure
2. Runs `breakeramp apply` to provision containers
3. Waits for health checks
4. Runs migrations (`alembic upgrade head`)
5. Executes pytest
6. Optionally tears down with `breakeramp destroy`

## Test Database

**Unit tests**: Use mocked services or in-memory stores. No real DB needed.

**Integration tests**: Require a database. Options:
- **BreakerAmp** (recommended): Auto-provisions Postgres in Podman container
- **Local Postgres**: Set `DATABASE_URL` in `.env` and run `alembic upgrade head`
- **SQLite**: `amprealize context add test --storage sqlite --path /tmp/test.db`

## Writing Tests

Follow the test pyramid: 70% unit, 20% integration, 10% E2E.

```python
import pytest

pytestmark = pytest.mark.unit  # Mark entire module

class TestBehaviorService:
    def test_create_behavior(self, mock_pool):
        """Test creating a new behavior draft."""
        service = BehaviorService(pool=mock_pool)
        result = service.create_behavior(name="test", description="desc")
        assert result.status == "draft"
```

Key patterns:
- Use `conftest.py` fixtures for shared setup (mock pools, services)
- Mark tests with appropriate markers
- Keep unit tests under 100ms each
- Test both happy path and error paths

## Coverage

```bash
pytest --cov=amprealize --cov-report=html -m unit
open htmlcov/index.html
```

## Parity Tests

Cross-surface parity tests verify CLI, API, and MCP produce identical results:

```bash
pytest -m parity -v
```

These tests are in `tests/test_*_parity.py` files.
