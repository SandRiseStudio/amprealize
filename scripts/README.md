# Test Scripts

Safe testing utilities for Amprealize with Podman containers.

## Quick Start

```bash
# 1. Start test containers
podman-compose -f docker-compose.test.yml up -d

# 2. Check environment
./scripts/run_tests.sh --check-only

# 3. Run tests
./scripts/run_tests.sh
```

## Scripts

### `run_tests.sh`
Safe test runner with automatic environment configuration and health checks.

**Usage**:
```bash
./scripts/run_tests.sh                    # All tests (serial, safest)
./scripts/run_tests.sh --check-only       # Just check environment
./scripts/run_tests.sh -n 2               # Parallel with 2 workers
./scripts/run_tests.sh tests/test_api.py  # Specific test file
```

**Features**:
- Auto-configures PostgreSQL and Redis environment variables
- Validates all containers are accessible before running tests
- Monitors resource usage and warns if containers are stressed
- Provides actionable error messages and troubleshooting tips

### `monitor_test_resources.sh`
Real-time Podman container resource monitoring.

**Usage**:
```bash
./scripts/monitor_test_resources.sh       # One-time check
watch -n 2 ./scripts/monitor_test_resources.sh  # Live monitoring
```

**Shows**:
- CPU and memory usage per container (color-coded: OK/WARN/CRITICAL)
- Container status and port mappings
- System memory pressure (macOS)
- Actionable recommendations based on current load

## Safety Guidelines

### ✅ Safe Practices
- Use `run_tests.sh` instead of raw `pytest`
- Start with serial execution (no `-n` flag)
- Monitor resources during test runs
- Restart containers if usage is high (>80%)

### ⚠️ Warnings
- **Max 2 workers** on local development machines (`-n 2`)
- **Don't run parallel tests** if containers show high resource usage
- **Stop tests immediately** if system becomes sluggish

### 🚨 Emergency
If system becomes unresponsive:
1. Force-quit terminal (Cmd+Q or kill process)
2. Restart containers: `podman-compose -f docker-compose.test.yml restart`
3. If needed, restart Podman: `podman machine stop && podman machine start`

## Documentation

See [`docs/TESTING_GUIDE.md`](../docs/TESTING_GUIDE.md) for comprehensive testing documentation including:
- Architecture overview
- Container management
- Troubleshooting guide
- Writing test-safe code
- CI/CD integration

## Test Infrastructure

### Components
- **5 PostgreSQL databases** (ports 6433-6437): BehaviorService, WorkflowService, ActionService, RunService, ComplianceService
- **Redis** (port 6479): Caching and sessions
- **Resource limits**: 5 connections/service, 5s connect timeout, 60s test timeout

### Configuration Files
- `pytest.ini` - Test discovery, timeouts, markers
- `tests/conftest.py` - Shared fixtures with connection pooling
- `docker-compose.test.yml` - Container definitions

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Container not accessible" | `podman-compose -f docker-compose.test.yml up -d` |
| High resource usage | `podman-compose -f docker-compose.test.yml restart` |
| Tests hang | Check `pytest.ini` timeouts, run serially |
| Connection pool exhausted | Reduce workers, check fixture cleanup |

For detailed troubleshooting, see [`docs/TESTING_GUIDE.md`](../docs/TESTING_GUIDE.md).
