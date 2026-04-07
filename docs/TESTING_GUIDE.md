# Testing Guide for Amprealize

This guide covers best practices for running tests safely with Podman containers. Following these practices prevents resource exhaustion, system crashes, and connection pool issues.

**Behaviors referenced**: `behavior_align_storage_layers`, `behavior_unify_execution_records`, `behavior_instrument_metrics_pipeline`

---

## Quick Start

**Warning — protect your data:** Do **not** set `AMPREALIZE_*_PG_DSN`, `AMPREALIZE_*_PG_DSN`, or any other test database URL to Postgres you use for **local dev or production**; the suite may truncate or reset schemas. Use `./scripts/run_tests.sh` so DSNs target **`infra/docker-compose.test.yml`** (isolated ports and test DB names), or a dedicated **test-only** remote instance.

### Check Environment
```bash
./scripts/run_tests.sh --check-only
```

### Run All Tests (Serial - Safest)
```bash
./scripts/run_tests.sh
```

### Run Specific Tests
```bash
./scripts/run_tests.sh tests/test_cli_analytics.py
./scripts/run_tests.sh tests/test_cli_*.py
```

### Run with Limited Parallelization
```bash
# Maximum 2 workers recommended for local dev
./scripts/run_tests.sh -n 2
```

### Podman: `proxy already running` or stuck compose

If `podman compose` fails with **`proxy already running`** (or the test runner hangs after image pulls), the Podman VM networking proxy (`gvproxy`) is usually in a bad state.

1. Restart the machine:
   ```bash
   podman machine stop
   podman machine start
   ```
2. Retry `./scripts/run_tests.sh --check-only`.
3. If it persists: quit **Podman Desktop** (if installed), restart the machine again, or reboot the host.

**Alternative:** bring up the same stack with Docker and run pytest with the same env vars the script exports, or use `./scripts/run_tests.sh --env-file config/breakeramp/environments.yaml --breakeramp` when that manifest matches your stack.

### Podman Compose (avoid docker-compose)

This repo targets **Podman**. `./scripts/run_tests.sh` prefers **`podman compose`** (built into Podman 4+) over the **`podman-compose`** Python shim, because the shim often invokes **docker-compose**, which can create mismatched network labels and “volume still in use” errors on macOS.

- Bring the test stack up manually with: `podman compose -f infra/docker-compose.test.yml up -d`
- On macOS, if **`podman compose`** keeps using Homebrew **docker-compose** (warning: “Executing external compose provider”), install **`podman-compose`** and set **`export PODMAN_COMPOSE_PROVIDER="$(command -v podman-compose)"`** before `podman compose`, or let **`./scripts/run_tests.sh`** set it when `podman-compose` is on your `PATH`.
- To force a specific binary: `export AMPREALIZE_COMPOSE_BIN='podman compose'` before running the script (or `AMPREALIZE_COMPOSE_BIN='podman-compose'`).

### BreakerAmp CLI Output Modes
```bash
# Human-friendly summary (default when running in a terminal)
amprealize breakeramp plan --blueprint-id tests --environment ci

# Machine readable JSON (preferred for scripts)
amprealize breakeramp plan --blueprint-id tests --environment ci --output json
```

BreakerAmp commands now write every raw response to
`~/.amprealize/breakeramp/snapshots/<timestamp>-<command>.json`. Reference these files
when you need the exact payload that powered the concise terminal summaries.

---

## Architecture

### Test Infrastructure Components

1. **PostgreSQL — modular monolith (default)**
   - One database on **6433** (`postgres-behavior-test`): all domain schemas applied with **Alembic** (`scripts/run_alembic_migrations.py`).
   - `./scripts/run_tests.sh` points workflow, action, run, compliance, and auth DSNs at this same instance with per-schema `search_path` (unless `AMPREALIZE_TEST_PER_SERVICE_PG_DATABASES=1`).

2. **Legacy: one Postgres per service (optional)**
   - Start extra containers with:
     `COMPOSE_PROFILES=per-service-db podman compose -f infra/docker-compose.test.yml up -d`
   - Set `AMPREALIZE_TEST_PER_SERVICE_PG_DATABASES=1` when using that layout.

3. **TimescaleDB telemetry** (default port **6432** in `infra/docker-compose.test.yml`; CI may use another mapped port — follow `AMPREALIZE_PG_PORT_TELEMETRY`).

4. **TimescaleDB metrics** (default **6439**).

5. **Redis** (port 6479)
   - Caching and session management

6. **Resource limits per service**
   - Max 5 concurrent connections per worker
   - 5-second connection timeout
   - 30-second query timeout
   - 60-second test timeout (configurable in `pytest.ini`)

### Configuration Files

- **`pytest.ini`**: Test discovery, timeouts, markers, and parallel execution settings
- **`tests/conftest.py`**: Shared fixtures with connection pooling and resource management
- **`scripts/run_tests.sh`**: Safe test runner with environment setup and health checks
- **`scripts/monitor_test_resources.sh`**: Real-time container resource monitoring

---

## Best Practices

### 1. Always Use the Test Runner Script

```bash
# ✅ Good - uses safe defaults
./scripts/run_tests.sh

# ❌ Avoid - raw pytest without resource checks
pytest tests/
```

The script provides:
- Environment variable configuration
- Container health checks
- Resource monitoring
- Safe parallelization limits
- Helpful error messages

### 2. Start with Serial Execution

When debugging or developing new tests, always run serially first:

```bash
./scripts/run_tests.sh tests/test_new_feature.py
```

Only add parallelization (`-n 2`) once tests are stable and you've verified resource usage.

### 3. Monitor Resources During Test Runs

Open a second terminal and run:

```bash
watch -n 2 ./scripts/monitor_test_resources.sh
```

This shows real-time container CPU and memory usage. If you see warnings, stop tests and restart containers:

```bash
podman compose -f infra/docker-compose.test.yml restart
```

### 4. Use Test Markers

Tests are tagged with markers for selective execution:

```bash
# Run only unit tests (no external dependencies)
pytest -m unit

# Skip slow tests
pytest -m "not slow"

# Run only PostgreSQL tests
pytest -m postgres

# Run integration tests
pytest -m integration
```

Available markers (see `pytest.ini`):
- `unit`: Pure unit tests
- `integration`: Tests requiring external services
- `postgres`: PostgreSQL-dependent tests
- `redis`: Redis-dependent tests
- `kafka`: Kafka-dependent tests
- `parity`: Cross-surface consistency tests
- `slow`: Long-running tests
- `load`: Performance/load tests

### 5. Isolate Test Failures

When tests fail, narrow down the problem:

```bash
# Run single test file
pytest tests/test_run_backend_parity.py -v

# Run single test function
pytest tests/test_run_backend_parity.py::test_create_run_parity -v

# Add extra debugging
pytest tests/test_api.py -vv --tb=long --showlocals
```

### 6. Handle Timeouts Properly

Default timeout is 60 seconds per test (configured in `pytest.ini`). If tests legitimately need more time:

```python
import pytest

@pytest.mark.timeout(120)  # 2 minutes
def test_slow_operation():
    # Long-running test
    pass
```

Or skip timeout for specific tests:

```python
@pytest.mark.timeout(0)  # No timeout
def test_interactive():
    pass
```

### 7. Opt-in to Hour-Long Streaming Load Tests

The primary streaming pipeline validation (`tests/load/test_streaming_pipeline_load.py::test_sustained_10k_events_per_second`) requires a dedicated Kafka/Flink cluster and runs for roughly one hour while sending 36M events. To prevent accidental hangs on laptops, the test is skipped by default. Enable it explicitly when you have the required infrastructure:

```bash
export AMPREALIZE_RUN_PRIMARY_STREAM_LOAD_TEST=1
./scripts/run_tests.sh tests/load/test_streaming_pipeline_load.py::test_sustained_10k_events_per_second -v
```

Unset the variable (or leave it at the default `0`) for day-to-day suites so the rest of the load tests run without waiting on the production-scale scenario.

### Opt-in to the 5-Minute 1k/sec Streaming Test

The `tests/load/test_streaming_pipeline_load.py::test_sustained_1k_events_per_second` case streams 300k events over five minutes and monopolizes Kafka/Flink resources. It now requires an explicit opt-in just like the hour-long scenario. When you are ready to run it (for example, on a staging rig or nightly validation host), export the following variable:

```bash
export AMPREALIZE_RUN_1K_STREAM_LOAD_TEST=1
./scripts/run_tests.sh tests/load/test_streaming_pipeline_load.py::test_sustained_1k_events_per_second -v
```

Keep the variable unset (default `0`) to skip the test during local development and CI smoke runs.

### 8. API Server Auto-Start

`./scripts/run_tests.sh` launches a FastAPI server via `uvicorn amprealize.api:create_app --factory` and automatically exports `AMPREALIZE_API_URL` so integration tests (auth/device flow, CLI parity) and the REST load suite (`tests/load/test_service_load.py`) hit the repo version of the API instead of any long-lived staging container.

- If `localhost:8000` is free, the runner boots the server there (previous behavior). When the port is already in use but the resident process does **not** expose `/api/v1/auth/*`, the script now finds an open high port, starts a private server there, and rewrites `AMPREALIZE_API_URL` to `http://localhost:<new-port>` for the current test run.
- Logs stream to `.tmp/api_server.log` (configurable with `AMPREALIZE_API_SERVER_LOG_FILE`). Tail this file if the server fails to boot.
- Override defaults with:
   - `AMPREALIZE_API_SERVER_HOST` / `AMPREALIZE_API_SERVER_PORT` (defaults: `localhost` / `8000`).
   - `AMPREALIZE_API_SERVER_CMD` if you need a custom launch command (include the port flag yourself). When you override the command, also set `AMPREALIZE_API_URL` to match the port you choose.
- Set `AMPREALIZE_SKIP_API_SERVER=1` when you already have a long-lived staging instance running and do not want the runner to manage it. Export `AMPREALIZE_API_URL` yourself in that scenario so the integration tests know which endpoint to target.

### Staging Stack Auto-Start

The staging smoke suite (`tests/smoke/test_staging_core.py`) now runs against a managed staging stack (API + NGINX) whenever it is part of your test selection. `./scripts/run_tests.sh` automatically:

- Launches `deployment/podman-compose-staging.yml` (amprealize-api, amprealize-mcp, redis, nginx) when needed and keeps it running for the duration of the test run.
- Waits for `http://localhost:8000` (`STAGING_API_URL`) and `http://localhost:8080` (`STAGING_NGINX_URL`) to respond before punting to pytest.
- Moves the local FastAPI server to a free high port so staging containers can continue to bind :8000/:8080 without conflicts. The script updates `AMPREALIZE_API_URL` accordingly.

Control the behavior with `AMPREALIZE_ENABLE_STAGING_STACK`:

- `AMPREALIZE_ENABLE_STAGING_STACK=1` – force-enable staging stack startup even if staging tests are not detected.
- `AMPREALIZE_ENABLE_STAGING_STACK=0` – skip staging stack management (useful when you already have a remote staging environment wired up via `STAGING_API_URL`).
- `auto` (default) – enable when the test selection includes `tests/` (full suite) or any argument containing “staging”.

If you need to override the proxied URLs, export `STAGING_API_URL` / `STAGING_NGINX_URL` before running the script. The health checks reuse those values.
### Telemetry Warehouse (TimescaleDB) Setup

Tests that hit the PostgreSQL/TimescaleDB warehouse (for example
`tests/test_telemetry_warehouse_postgres.py`, `tests/load/test_streaming_pipeline_load.py`, and
`tests/test_trace_analysis_service.py` when `TelemetryClient` is backed by Postgres) expect the
`psycopg2` driver and the telemetry DSN to be available. Follow the checklist below before running
those suites:

1. **Install the telemetry extras** so `psycopg2-binary` is present (do not mix with the `psycopg`
   v3 driver, which lacks the extensions we rely on):
   ```bash
   pip install -e ".[dev,postgres,telemetry]"
   ```
2. **Start the TimescaleDB container** (port `6432`) along with the rest of the stack:
   ```bash
   podman compose -f infra/docker-compose.test.yml up -d postgres-telemetry-test
   ```
   The unified runner automatically checks the port, but starting the container up front avoids
   repeated retries during `pytest.importorskip("psycopg2")`.
3. **Verify the DSN**. By default `scripts/run_tests.sh` exports a telemetry DSN for user/database
   `telemetry_test` on port `6432` (see `AMPREALIZE_TELEMETRY_PG_DSN` in `scripts/run_tests.sh`).
   Override this variable if you target a remote Timescale instance.
4. **Ensure the schema exists.** `./scripts/run_tests.sh --check-only` calls
   `scripts/run_postgres_telemetry_migration.py` automatically when the `telemetry_events`
   hypertable is missing. Run the check after pulling new migrations or wiping volumes.
5. **Run the focused tests** once the driver and schema are ready:
   ```bash
   ./scripts/run_tests.sh tests/test_telemetry_warehouse_postgres.py -v
   AMPREALIZE_RUN_1K_STREAM_LOAD_TEST=1 ./scripts/run_tests.sh \
     tests/load/test_streaming_pipeline_load.py::test_sustained_1k_events_per_second -v
   ```
   The first command validates the warehouse (hypertables, retention policies, `_ensure_connection`
   autocommit sessions). The second reuses the same DSN for the 1k/sec streaming scenario—export the
   opt-in flag only when you have time and resources for the five-minute run.

These steps keep telemetry tests aligned with `behavior_align_storage_layers` by guaranteeing the
TimescaleDB contract matches what production runs.
---

## Container Management

### Start Test Containers

```bash
podman compose -f infra/docker-compose.test.yml up -d
```

### Check Container Status

```bash
podman ps --filter "name=amprealize"
```

### View Container Logs

```bash
# All containers
podman compose -f infra/docker-compose.test.yml logs -f

# Specific service
podman logs amprealize-postgres-behavior-test
```

### Restart Containers (When Resources Are High)

```bash
podman compose -f infra/docker-compose.test.yml restart
```

### Stop and Clean Up

```bash
# Stop containers
podman compose -f infra/docker-compose.test.yml down

# Stop and remove volumes (full reset)
podman compose -f infra/docker-compose.test.yml down -v
```

---

## Troubleshooting

### Retrieval Quality Snapshot Mode

The `tests/test_retrieval_quality.py` suite defaults to an offline snapshot so laptops without 32GB of RAM can run safely. The snapshot lives at `tests/data/retrieval_quality_snapshot.json` and records the baseline BAAI/bge-m3 vs. quantized all-MiniLM-L6-v2 nDCG@5 metrics. If you need to regenerate the snapshot (for example, after changing the behavior corpus or upgrading SentenceTransformer), follow these steps:

1. Ensure `sentence-transformers`, `numpy`, and `scikit-learn` are installed in your virtual environment.
2. Export `RETRIEVAL_QUALITY_USE_REAL_MODELS=true` so the tests and benchmarking script opt into live model evaluation.
3. Run the benchmarking helper to refresh the snapshot:
   ```bash
   python scripts/benchmark_embedding_models.py \
     --output tests/data/retrieval_quality_snapshot.json
   ```
4. Re-run `./scripts/run_tests.sh tests/test_retrieval_quality.py` to confirm the snapshot results keep the quantized model above the 85% quality threshold.

When the env var is unset (default), the tests read from the snapshot and skip the heavyweight model downloads. Set `RETRIEVAL_QUALITY_USE_REAL_MODELS=false` explicitly if you need to confirm snapshot-only execution in CI.

### System Crash / High Resource Usage

**Symptoms**: Laptop becomes unresponsive, fans spin up, tests hang

**Solutions**:
1. Stop test execution immediately (Ctrl+C)
2. Check resources: `./scripts/monitor_test_resources.sh`
3. Restart containers: `podman compose -f infra/docker-compose.test.yml restart`
4. Run tests serially: `./scripts/run_tests.sh tests/small_test.py`
5. If problem persists, restart Podman VM:
   ```bash
   podman machine stop
   podman machine start
   ```

### Connection Pool Exhaustion

**Symptoms**: `psycopg2.OperationalError: FATAL: remaining connection slots reserved`

**Solutions**:
1. Reduce parallel workers (use `-n 1` or serial)
2. Check `tests/conftest.py` connection limits (`MAX_CONNECTIONS_PER_SERVICE`)
3. Ensure tests properly close connections in fixtures
4. Restart PostgreSQL containers

### Tests Hang / Timeout

**Symptoms**: Tests run indefinitely without completing

**Solutions**:
1. Check for deadlocks in PostgreSQL logs
2. Verify connection timeouts are set (`connect_timeout=5`)
3. Look for missing `yield` or `try/finally` in fixtures
4. Increase timeout in `pytest.ini` if legitimately slow

### Container Not Accessible

**Symptoms**: `nc: connect to localhost port 6433 (tcp) failed: Connection refused`

**Solutions**:
1. Verify containers are running: `podman ps`
2. Check port mappings: `podman port <container-name>`
3. Restart container: `podman restart <container-name>`
4. Check Podman machine: `podman machine info`

### Database Schema Issues

**Symptoms**: `relation does not exist`, missing tables

**Solutions**:
1. Verify migrations ran: Check container startup logs
2. Manually run migrations:
   ```bash
   podman exec amprealize_behavior_test_db psql -U amprealize_behavior -d amprealize_behavior_test -f /migrations/001_init.sql
   ```
3. Reset database with fresh schema:
   ```bash
   podman compose -f infra/docker-compose.test.yml down -v
   podman compose -f infra/docker-compose.test.yml up -d
   ```

---

## Parallel Execution Guidelines

### When to Use Parallel Execution

✅ **Safe scenarios**:
- Mature, stable test suite
- Unit tests with mocked dependencies
- Tests confirmed to have proper isolation
- System resources are healthy (< 70% CPU/memory)
- Maximum 2 workers on local development machines

❌ **Avoid parallel execution**:
- Developing or debugging new tests
- System already under load
- Tests share mutable state
- Database connection issues
- Memory pressure warnings

### Parallel Execution Strategies

```bash
# Load-balanced by file (recommended)
# Tests from same file run on same worker, reducing connection churn
pytest -n 2 --dist=loadfile tests/

# Load-balanced by test
# More granular but higher connection overhead
pytest -n 2 --dist=load tests/

# Load-balanced by scope
# Groups tests by fixture scope
pytest -n 2 --dist=loadscope tests/
```

**Recommendation**: Always use `--dist=loadfile` for database-heavy tests.

---

## Writing Test-Safe Code

### Database Fixtures

Always ensure proper cleanup:

```python
@pytest.fixture
def postgres_service():
    """Create service with proper cleanup."""
    service = PostgresMyService(dsn=get_dsn())
    try:
        yield service
    finally:
        service.close()  # Always close connections
```

### Connection Management

Set timeouts and limits:

```python
dsn = (
    f"postgresql://{user}:{password}@{host}:{port}/{dbname}"
    f"?connect_timeout=5"  # 5-second connect timeout
    f"&options=-c%20statement_timeout=30s"  # 30-second query timeout
)
```

### Isolation Between Tests

Use `autouse` fixtures for cleanup:

```python
@pytest.fixture(autouse=True)
def isolate_test_resources():
    """Ensure clean state between tests."""
    yield
    time.sleep(0.05)  # Brief pause for connection cleanup
```

---

## Environment Variables Reference

The test runner script (`./scripts/run_tests.sh`) sets these automatically:

```bash
# BehaviorService
AMPREALIZE_PG_HOST_BEHAVIOR=localhost
AMPREALIZE_PG_PORT_BEHAVIOR=6433
AMPREALIZE_PG_USER_BEHAVIOR=amprealize_behavior
AMPREALIZE_PG_PASS_BEHAVIOR=behavior_test_pass
AMPREALIZE_PG_DB_BEHAVIOR=amprealize_behavior_test

# WorkflowService
AMPREALIZE_PG_HOST_WORKFLOW=localhost
AMPREALIZE_PG_PORT_WORKFLOW=6434
AMPREALIZE_PG_USER_WORKFLOW=amprealize_workflow
AMPREALIZE_PG_PASS_WORKFLOW=workflow_test_pass
AMPREALIZE_PG_DB_WORKFLOW=amprealize_workflow_test

# ActionService
AMPREALIZE_PG_HOST_ACTION=localhost
AMPREALIZE_PG_PORT_ACTION=6435
AMPREALIZE_PG_USER_ACTION=amprealize_action
AMPREALIZE_PG_PASS_ACTION=action_test_pass
AMPREALIZE_PG_DB_ACTION=amprealize_action_test

# RunService
AMPREALIZE_PG_HOST_RUN=localhost
AMPREALIZE_PG_PORT_RUN=6436
AMPREALIZE_PG_USER_RUN=amprealize_run
AMPREALIZE_PG_PASS_RUN=run_test_pass
AMPREALIZE_PG_DB_RUN=amprealize_run_test

# ComplianceService
AMPREALIZE_PG_HOST_COMPLIANCE=localhost
AMPREALIZE_PG_PORT_COMPLIANCE=6437
AMPREALIZE_PG_USER_COMPLIANCE=amprealize_compliance
AMPREALIZE_PG_PASS_COMPLIANCE=compliance_test_pass
AMPREALIZE_PG_DB_COMPLIANCE=amprealize_compliance_test

# Redis
REDIS_HOST=localhost
REDIS_PORT=6479
```

---

## CI/CD Considerations

For GitHub Actions or other CI environments:

```yaml
- name: Start test containers
  run: podman compose -f infra/docker-compose.test.yml up -d

- name: Wait for containers
  run: ./scripts/run_tests.sh --check-only

- name: Run tests
  run: ./scripts/run_tests.sh -n 4  # More workers in CI with better resources

- name: Upload coverage
  if: always()
  uses: actions/upload-artifact@v3
  with:
    name: coverage-report
    path: htmlcov/
```

---

## Maintenance

### Regular Tasks

1. **Update connection limits** if adding more services (`tests/conftest.py`)
2. **Review timeouts** if tests become slower (`pytest.ini`)
3. **Monitor test duration** and mark slow tests: `@pytest.mark.slow`
4. **Clean up test data** regularly to prevent bloat
5. **Update documentation** when changing test infrastructure

### Performance Optimization

```bash
# Profile test execution time
pytest --durations=10 tests/

# Identify slowest tests
pytest --durations=0 tests/ | sort -k1 -n

# Run only fast tests during development
pytest -m "not slow" tests/
```

---

## Additional Resources

- **Pytest documentation**: https://docs.pytest.org/
- **pytest-xdist (parallel)**: https://github.com/pytest-dev/pytest-xdist
- **pytest-timeout**: https://github.com/pytest-dev/pytest-timeout
- **Podman Compose**: https://github.com/containers/podman-compose

For questions or issues, refer to:
- `AGENTS.md` for agent behaviors
- `PRD.md` for system architecture
- `MCP_SERVER_DESIGN.md` for service contracts
- `ACTION_SERVICE_CONTRACT.md` for action parity expectations
