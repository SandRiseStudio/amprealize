# Testing Infrastructure Implementation Summary

## Overview

Implemented comprehensive testing best practices for Amprealize to prevent system crashes and resource exhaustion when running tests with Podman containers.

**Date**: 2025-10-30
**Context**: Tests with 2 parallel workers caused laptop crash due to resource exhaustion from 5 PostgreSQL containers + Redis + parallel execution.

**Behaviors applied**:
- `behavior_align_storage_layers` - Unified database connection management
- `behavior_unify_execution_records` - Consistent test execution tracking
- `behavior_instrument_metrics_pipeline` - Resource monitoring
- `behavior_update_docs_after_changes` - Documentation updates

---

## What Was Implemented

### 1. Pytest Configuration (`pytest.ini`)
- **Default timeouts**: 60s per test to prevent hung tests
- **Test markers**: For selective execution (unit, integration, postgres, redis, etc.)
- **Safe defaults**: Serial execution by default; parallel requires explicit `-n` flag
- **Structured output**: Better tracebacks with `--showlocals` and `--tb=short`

### 2. Enhanced Test Fixtures (`tests/conftest.py`)
- **Connection pooling**: Max 5 connections per service per worker
- **Timeout enforcement**: 5s connect timeout, 30s query timeout
- **Environment checks**: Session-scoped fixture validates all containers before tests run
- **Resource isolation**: Auto-cleanup between tests with brief pause for connection cleanup
- **DSN builders**: Flexible configuration supporting full DSN or individual components
- **Session-scoped fixtures**: Reusable PostgreSQL and Redis client fixtures

Key features:
```python
# Fail fast if infrastructure missing
@pytest.fixture(scope="session", autouse=True)
def check_test_environment()

# Clean resource isolation between tests
@pytest.fixture(autouse=True)
def isolate_test_resources()

# Properly scoped database fixtures
@pytest.fixture(scope="session")
def postgres_dsn_behavior()
```

### 3. Resource Monitor Script (`scripts/monitor_test_resources.sh`)
- Real-time Podman container stats (CPU%, Memory%)
- Color-coded status indicators (OK/WARN/CRITICAL)
- Thresholds: 80% warn, 95% critical
- macOS-specific memory pressure detection
- Actionable recommendations based on current load

Usage:
```bash
./scripts/monitor_test_resources.sh
watch -n 2 ./scripts/monitor_test_resources.sh  # Live monitoring
```

### 4. Safe Test Runner (`scripts/run_tests.sh`)
- **Environment setup**: Auto-configures all PostgreSQL + Redis env vars
- **Health checks**: Validates all container ports before running tests
- **Resource monitoring**: Warns if containers under high load
- **Flexible execution**: Support for serial, parallel, and targeted test runs
- **Helpful errors**: Actionable troubleshooting suggestions on failure

Usage:
```bash
./scripts/run_tests.sh                    # Serial (safest)
./scripts/run_tests.sh --check-only       # Just health check
./scripts/run_tests.sh -n 2               # Parallel (2 workers max)
./scripts/run_tests.sh tests/test_*.py    # Specific tests
```

### 5. Comprehensive Documentation (`docs/TESTING_GUIDE.md`)
Complete testing guide covering:
- Quick start commands
- Architecture overview (5 PostgreSQL + Redis setup)
- Best practices for safe test execution
- Container management procedures
- Troubleshooting guide for common issues
- Parallel execution guidelines
- Writing test-safe code patterns
- Environment variables reference
- CI/CD considerations

---

## Architecture

### Test Infrastructure Components

```
┌─────────────────────────────────────────────┐
│         Test Execution Layer                │
│  ┌─────────────────────────────────────┐   │
│  │  scripts/run_tests.sh (wrapper)     │   │
│  │  • Env var setup                    │   │
│  │  • Health checks                    │   │
│  │  • Resource validation              │   │
│  └─────────────────────────────────────┘   │
│                    │                        │
│         ┌──────────┴──────────┐            │
│         ▼                      ▼            │
│  ┌────────────┐        ┌────────────────┐  │
│  │   pytest   │        │  Monitor Script│  │
│  │  (serial)  │        │  (resources)   │  │
│  └────────────┘        └────────────────┘  │
└─────────────────────────────────────────────┘
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
┌──────────────────────────────────────────┐
│     Podman Container Layer               │
│  ┌────────┐ ┌────────┐ ┌────────┐       │
│  │  PG    │ │  PG    │ │  PG    │       │
│  │  :6433 │ │  :6434 │ │  :6435 │ ...   │
│  │Behavior│ │Workflow│ │ Action │       │
│  └────────┘ └────────┘ └────────┘       │
│                                          │
│  ┌────────┐ ┌────────┐ ┌────────┐       │
│  │  PG    │ │  PG    │ │ Redis  │       │
│  │  :6436 │ │  :6437 │ │  :6479 │       │
│  │  Run   │ │Complnce│ │        │       │
│  └────────┘ └────────┘ └────────┘       │
└──────────────────────────────────────────┘
```

### Resource Limits

Per worker/process:
- **Max connections**: 5 per PostgreSQL service
- **Connect timeout**: 5 seconds
- **Query timeout**: 30 seconds
- **Test timeout**: 60 seconds (configurable)
- **Isolation delay**: 50ms between tests

### Safety Features

1. **Fail-fast validation**: Tests won't start if containers unreachable
2. **Connection pooling**: Prevents pool exhaustion
3. **Timeout enforcement**: Prevents hung tests from blocking suite
4. **Resource monitoring**: Real-time visibility into container health
5. **Automatic cleanup**: Fixtures ensure connections close properly

---

## Usage Examples

### Safe Daily Workflow

```bash
# 1. Start containers
podman-compose -f docker-compose.test.yml up -d

# 2. Check environment
./scripts/run_tests.sh --check-only

# 3. Run tests (serial - safest)
./scripts/run_tests.sh

# 4. Monitor in another terminal (optional)
watch -n 2 ./scripts/monitor_test_resources.sh
```

### Development Workflow

```bash
# Run specific test during development
./scripts/run_tests.sh tests/test_cli_analytics.py

# Run only unit tests (fast)
pytest -m unit

# Skip slow tests
pytest -m "not slow"

# Debug single failing test
pytest tests/test_api.py::test_specific_function -vv --tb=long
```

### CI/CD Workflow

```bash
# CI has more resources, can use parallelization
./scripts/run_tests.sh -n 4 tests/

# Or with coverage
pytest -n 4 --cov=amprealize --cov-report=html tests/
```

---

## Key Safety Rules

### ✅ DO

1. **Use the test runner script** (`./scripts/run_tests.sh`)
2. **Start with serial execution** when developing/debugging
3. **Monitor resources** during test runs
4. **Check environment** before running tests (`--check-only`)
5. **Use test markers** for selective execution
6. **Write proper cleanup** in fixtures (try/finally)
7. **Set connection timeouts** in all database clients
8. **Restart containers** if resource usage is high

### ❌ DON'T

1. **Don't run raw pytest** without environment checks
2. **Don't use >2 workers** on local development machines
3. **Don't hardcode connection strings** in tests
4. **Don't skip fixture cleanup** (always use try/finally)
5. **Don't ignore timeout warnings**
6. **Don't run parallel tests** when containers are already stressed
7. **Don't commit test database credentials** to version control
8. **Don't run tests** if monitor shows high resource usage

---

## Troubleshooting Quick Reference

| Symptom | Solution |
|---------|----------|
| System crash / unresponsive | Stop tests, restart containers, run serially |
| Connection pool exhausted | Use serial execution, check connection cleanup |
| Tests hang | Check timeout settings, look for deadlocks |
| Container not accessible | Verify `podman ps`, restart container |
| High CPU/memory | Use `monitor_test_resources.sh`, restart containers |
| Database schema errors | Reset containers with `podman-compose down -v` |

---

## Files Modified/Created

### Created
- ✅ `pytest.ini` - Pytest configuration with timeouts and markers
- ✅ `scripts/monitor_test_resources.sh` - Resource monitoring script
- ✅ `scripts/run_tests.sh` - Safe test runner with health checks
- ✅ `docs/TESTING_GUIDE.md` - Comprehensive testing documentation

### Modified
- ✅ `tests/conftest.py` - Enhanced with connection pooling and environment checks

All scripts are executable and ready to use.

---

## Validation Steps

### 1. Environment Check
```bash
./scripts/run_tests.sh --check-only
```
Expected: Validates all 5 PostgreSQL + Redis containers are accessible

### 2. Resource Monitor
```bash
./scripts/monitor_test_resources.sh
```
Expected: Shows container stats with color-coded status

### 3. Test Execution (After Starting Containers)
```bash
# Start containers first
podman-compose -f docker-compose.test.yml up -d

# Then run tests
./scripts/run_tests.sh tests/test_cli_analytics.py
```
Expected: Tests run without system instability

---

## Next Steps

1. **Start test containers**:
   ```bash
   podman-compose -f docker-compose.test.yml up -d
   ```

2. **Verify environment**:
   ```bash
   ./scripts/run_tests.sh --check-only
   ```

3. **Run a small test first** (smoke test):
   ```bash
   ./scripts/run_tests.sh tests/test_cli_analytics.py
   ```

4. **Monitor resources** in a second terminal:
   ```bash
   watch -n 2 ./scripts/monitor_test_resources.sh
   ```

5. **Gradually scale up** if resources allow:
   ```bash
   ./scripts/run_tests.sh -n 2 tests/
   ```

---

## References

- **AGENTS.md**: Behavior definitions and workflow patterns
- **PRD.md**: System architecture and success metrics
- **MCP_SERVER_DESIGN.md**: Service contracts and parity expectations
- **ACTION_SERVICE_CONTRACT.md**: Action registry and reproducibility
- **PROGRESS_TRACKER.md**: Implementation status and evidence

---

## Behaviors Satisfied

- ✅ `behavior_align_storage_layers` - Connection management unified across adapters
- ✅ `behavior_unify_execution_records` - Test runs tracked consistently
- ✅ `behavior_instrument_metrics_pipeline` - Resource monitoring in place
- ✅ `behavior_update_docs_after_changes` - Testing guide created
- ✅ `behavior_externalize_configuration` - All config via env vars
- ✅ `behavior_prevent_secret_leaks` - Test credentials externalized

---

**Status**: ✅ Complete - Ready for safe testing with proper resource management
