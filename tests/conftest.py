"""Pytest configuration ensuring the repository root is importable.

Provides shared fixtures with proper resource management for Podman containers.
Behaviors: behavior_align_storage_layers, behavior_unify_execution_records
"""

from __future__ import annotations

import os
import re
import socket
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Generator, List, Optional
from unittest.mock import Mock, MagicMock

import pytest

# Load environment variables from .env file (for OPENAI_API_KEY, etc.)
try:
    from dotenv import load_dotenv
    REPO_ROOT = Path(__file__).resolve().parents[1]
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    REPO_ROOT = Path(__file__).resolve().parents[1]  # Define even if dotenv not available

from amprealize.action_contracts import Actor, utc_now_iso
from amprealize.behavior_service import (
    ApproveBehaviorRequest,
    BehaviorService,
    CreateBehaviorDraftRequest,
    SearchBehaviorsRequest,
)
from amprealize.storage.redis_cache import get_cache

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

for package_src in REPO_ROOT.glob("packages/*/src"):
    package_src_str = str(package_src)
    if package_src_str not in sys.path:
        sys.path.insert(0, package_src_str)

# Exclude interactive/manual scripts that have no pytest test functions
# and execute module-level code on import (blocking pytest collection)
collect_ignore = [
    "test_github_device_flow.py",
    "test_task_integration.py",
    "test_all_service_parity.py",
    "test_kafka_consume.py",
    "test_e2e_device_flow.py",
]


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register custom CLI flags used across the test suite."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Execute tests marked with @pytest.mark.integration that require live infrastructure.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Ensure custom markers are documented to avoid Pytest warnings."""
    config.addinivalue_line(
        "markers",
        "integration: tests that exercise live infrastructure and require --run-integration",
    )


# ============================================================================
# Heavy Dependency Mocking (Prevents Memory Exhaustion)
# ============================================================================

@pytest.fixture(scope="session", autouse=True)
def mock_sentence_transformer():
    """Mock SentenceTransformer to prevent loading heavy models in tests.

    Loading the actual model consumes ~500MB+ RAM per instance and takes
    30-60s. With 462 tests, this would exhaust system memory and cause crashes.

    This session-scoped fixture mocks the model globally for all tests.
    """
    # Mock the SentenceTransformer class before any imports
    mock_model = MagicMock()
    mock_model.encode.return_value = [[0.1] * 384]  # Fake embedding vector

    # Patch at module level
    sys.modules['sentence_transformers'] = MagicMock()
    sys.modules['sentence_transformers'].SentenceTransformer = lambda *args, **kwargs: mock_model

    yield mock_model

    # Cleanup
    if 'sentence_transformers' in sys.modules:
        del sys.modules['sentence_transformers']


@pytest.fixture(scope="session", autouse=True)
def mock_faiss():
    """Mock FAISS to prevent actual vector index operations in tests.

    FAISS operations can be memory-intensive with large indexes.
    """
    mock_faiss = MagicMock()
    mock_faiss.IndexFlatL2 = lambda dim: MagicMock()

    sys.modules['faiss'] = mock_faiss

    yield mock_faiss

    if 'faiss' in sys.modules:
        del sys.modules['faiss']


# ============================================================================
# Memory Management
# ============================================================================

@pytest.fixture(autouse=True)
def gc_collect_after_test():
    """Force garbage collection after each test to reduce memory pressure.

    On memory-constrained systems (8GB RAM), this prevents memory accumulation
    across 800+ tests that could lead to swap thrashing or OOM conditions.
    """
    import gc
    yield
    gc.collect()


# ============================================================================
# Database Connection Pool Management
# ============================================================================

# Limit concurrent connections per worker to prevent exhaustion
MAX_CONNECTIONS_PER_SERVICE = 5
CONNECTION_TIMEOUT = 5  # seconds
QUERY_TIMEOUT = 30  # seconds


def _modulith_search_path_schema(service_name: str) -> str | None:
    """When AMPREALIZE_TEST_PER_SERVICE_PG_DATABASES is unset/0, use one DB with per-domain search_path."""
    if os.getenv("AMPREALIZE_TEST_PER_SERVICE_PG_DATABASES") == "1":
        return None
    return {
        "BEHAVIOR": "behavior",
        "WORKFLOW": "workflow",
        "ACTION": "execution",
        "RUN": "execution",
        "COMPLIANCE": "compliance",
        "AUTH": "auth",
    }.get(service_name)


def wait_for_port(host: str, port: int, timeout: float = 10.0, interval: float = 0.5) -> bool:
    """Return True when a TCP port is reachable before the timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=interval):
                return True
        except OSError:
            time.sleep(interval)
    return False


def get_postgres_dsn(service_name: str) -> str | None:
    """Build PostgreSQL DSN from environment variables.

    Supports both full DSN or individual components.
    Priority: AMPREALIZE_{SERVICE}_PG_DSN > individual components

    Args:
        service_name: Service identifier (e.g., 'BEHAVIOR', 'RUN', 'WORKFLOW')

    Returns:
        Full PostgreSQL connection string or None if not configured
    """
    # Check for full DSN first
    dsn_var = f"AMPREALIZE_{service_name}_PG_DSN"
    if dsn := os.environ.get(dsn_var):
        return dsn

    # Build from components
    host = os.environ.get(f"AMPREALIZE_PG_HOST_{service_name}")
    port = os.environ.get(f"AMPREALIZE_PG_PORT_{service_name}")
    user = os.environ.get(f"AMPREALIZE_PG_USER_{service_name}")
    password = os.environ.get(f"AMPREALIZE_PG_PASS_{service_name}")
    dbname = os.environ.get(f"AMPREALIZE_PG_DB_{service_name}", f"amprealize_{service_name.lower()}_test")

    if not all([host, port, user, password]):
        return None

    schema = _modulith_search_path_schema(service_name)
    if schema:
        opts = (
            f"-c%20search_path%3D{schema}%2Cpublic%20"
            f"-c%20statement_timeout%3D{QUERY_TIMEOUT}s"
        )
    else:
        opts = f"-c%20statement_timeout%3D{QUERY_TIMEOUT}s"

    return (
        f"postgresql://{user}:{password}@{host}:{port}/{dbname}"
        f"?connect_timeout={CONNECTION_TIMEOUT}"
        f"&options={opts}"
    )


# ============================================================================
# Production Database Safety Guard
# ============================================================================
# These functions prevent test fixtures from accidentally truncating production
# data. Every TRUNCATE in tests/ must go through safe_truncate().

# Database names that are known production databases and must NEVER be truncated.
# Short names that must never be used as the *database* name for test TRUNCATE targets.
# Note: a local dev DB may still be named `amprealize`; only unambiguous prod-style names here.
_PRODUCTION_DB_NAMES = frozenset({"amprealize", "telemetry"})

# Hostnames that point to production containers.
_PRODUCTION_HOSTNAMES = frozenset({"amprealize-db"})

# Hostnames that are acceptable for destructive test helpers.
# Intentionally narrow: safe_truncate should only ever target local test DBs.
_LOCAL_TEST_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1", "host.containers.internal"})


def _mask_dsn_password(dsn: str) -> str:
    """Replace password in a DSN with '***' for safe logging."""
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", dsn)


def assert_test_database(dsn: str) -> None:
    """Validate that a DSN points to a test database, never production.

    Raises RuntimeError if the DSN appears to target a production database.
    This is the primary safety gate preventing test fixtures from wiping
    production data via TRUNCATE.

    Args:
        dsn: PostgreSQL connection string to validate.

    Raises:
        RuntimeError: If the DSN targets a known production database.
    """
    # Mock DSNs used by smoke/load test fixtures are always safe
    if "mock" in dsn.lower():
        return

    override_enabled = os.environ.get("AMPREALIZE_TEST_SAFETY_OVERRIDE") == "1"

    parsed = urllib.parse.urlparse(dsn)
    dbname = parsed.path.lstrip("/").split("?")[0]  # strip leading / and query params
    hostname = parsed.hostname or ""

    masked = _mask_dsn_password(dsn)

    # Even with the explicit override, destructive test helpers must remain local.
    # This prevents pytest runs from truncating an active cloud context such as Neon.
    if override_enabled and hostname not in _LOCAL_TEST_HOSTNAMES:
        raise RuntimeError(
            f"\n{'='*72}\n"
            f"SAFETY GUARD: Refusing to use remote/cloud database for test truncation!\n"
            f"  DSN:    {masked}\n"
            f"  Host:   {hostname or '(missing)'}\n"
            f"  Reason: AMPREALIZE_TEST_SAFETY_OVERRIDE only permits LOCAL hosts.\n"
            f"\n"
            f"To fix:\n"
            f"  - Use breakeramp test infrastructure (localhost / host.containers.internal)\n"
            f"  - Or switch away from the active cloud context before running destructive tests\n"
            f"{'='*72}"
        )

    # Block known production hostnames (breakeramp container names)
    if hostname in _PRODUCTION_HOSTNAMES:
        raise RuntimeError(
            f"\n{'='*72}\n"
            f"SAFETY GUARD: Refusing to use production database host!\n"
            f"  DSN:    {masked}\n"
            f"  Host:   {hostname}\n"
            f"  Reason: '{hostname}' is a known production container hostname.\n"
            f"\n"
            f"To fix:\n"
            f"  - Use a test-specific DSN (host=localhost, port=6433-6440)\n"
            f"  - Or set AMPREALIZE_TEST_SAFETY_OVERRIDE=1 if intentional\n"
            f"{'='*72}"
        )

    # Block known production database names
    if dbname in _PRODUCTION_DB_NAMES and not override_enabled:
        raise RuntimeError(
            f"\n{'='*72}\n"
            f"SAFETY GUARD: Refusing to use production database!\n"
            f"  DSN:      {masked}\n"
            f"  Database: {dbname}\n"
            f"  Reason:   '{dbname}' is a known production database name.\n"
            f"\n"
            f"To fix:\n"
            f"  - Rename the test database to '{dbname}_test'\n"
            f"  - Or set AMPREALIZE_TEST_SAFETY_OVERRIDE=1 if intentional\n"
            f"{'='*72}"
        )


def safe_truncate(
    dsn: str,
    tables: List[str],
    *,
    schema: Optional[str] = None,
) -> List[str]:
    """Truncate tables in a test database with production safety checks.

    This is the ONLY approved way to TRUNCATE tables in test fixtures.
    It validates the DSN targets a test database before executing any SQL.

    Args:
        dsn: PostgreSQL connection string (must pass assert_test_database).
        tables: List of table names to truncate.
        schema: Optional schema prefix (e.g., 'board'). If provided, each
                table name is prefixed with '{schema}.'.

    Returns:
        List of table names that were actually truncated (tables that exist).
    """
    import psycopg2

    assert_test_database(dsn)

    qualified = [f"{schema}.{t}" if schema else t for t in tables]

    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            existing = []
            for table_name in qualified:
                cur.execute("SELECT to_regclass(%s)", (table_name,))
                result = cur.fetchone()
                if result and result[0]:
                    existing.append(result[0] if isinstance(result[0], str) else table_name)

            if existing:
                cur.execute(
                    "TRUNCATE " + ", ".join(existing) + " RESTART IDENTITY CASCADE"
                )
        conn.commit()

    return existing


def check_redis_available() -> bool:
    """Check if Redis is accessible for testing."""
    try:
        import redis
        host = os.environ.get("REDIS_HOST", "localhost")
        port = int(os.environ.get("REDIS_PORT", "6379"))
        password = os.environ.get("REDIS_PASSWORD")

        client = redis.Redis(
            host=host,
            port=port,
            password=password,
            socket_connect_timeout=CONNECTION_TIMEOUT,
            socket_timeout=CONNECTION_TIMEOUT,
            decode_responses=True,
        )
        client.ping()
        client.close()
        return True
    except Exception:
        return False


# ============================================================================
# Resource Management Fixtures
# ============================================================================

@pytest.fixture(scope="session", autouse=True)
def check_test_environment(request):
    """Validate test environment before running any tests.

    Ensures Podman containers are running and accessible.
    Fails fast if critical infrastructure is missing.

    Skips check for tests marked with 'unit' or 'load' marker, or tests in tests/load/ or tests/smoke/.
    """
    # Skip infrastructure check for unit tests, load tests, and smoke tests
    marker_expr = request.config.getoption("-m", default="")
    if marker_expr in ("unit", "load", "smoke"):
        return

    # Skip when every collected test is marked @pytest.mark.unit (no -m flag needed)
    try:
        items = request.session.items
    except Exception:
        items = None
    if items and all(item.get_closest_marker("unit") is not None for item in items):
        return

    # Skip for any tests in tests/load/ or tests/smoke/ directory (they have their own infrastructure requirements)
    import pathlib
    for arg in request.config.args:
        if "tests/load/" in str(arg) or "/load/" in str(arg):
            return
        if "tests/smoke/" in str(arg) or "/smoke/" in str(arg):
            return

    mode = os.getenv("AMPREALIZE_TEST_INFRA_MODE", "legacy")

    # Define expected connection details based on env vars or defaults
    # Note: These defaults match the legacy docker-compose.test.yml ports
    # In BreakerAmp mode, these should be set by the orchestrator
    pg_host = os.getenv("AMPREALIZE_PG_HOST_BEHAVIOR", "localhost")
    pg_port = int(os.getenv("AMPREALIZE_PG_PORT_BEHAVIOR", "6433"))
    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", "6479"))

    if mode == "breakeramp":
        print(f"\n[Fixture] Mode: breakeramp. Verifying connectivity...")

        # We check one Postgres service as a proxy for all
        if not wait_for_port(pg_host, pg_port, timeout=15):
             pytest.fail(f"Infrastructure Error: Could not connect to Postgres at {pg_host}:{pg_port}. "
                         "In 'breakeramp' mode, the orchestrator must provision resources before tests run.")

        if not wait_for_port(redis_host, redis_port, timeout=15):
             pytest.fail(f"Infrastructure Error: Could not connect to Redis at {redis_host}:{redis_port}.")

        print("[Fixture] Connectivity verified.")
        return

    missing_services = []

    if os.getenv("AMPREALIZE_TEST_PER_SERVICE_PG_DATABASES") == "1":
        pg_services = ["BEHAVIOR", "WORKFLOW", "ACTION", "RUN", "COMPLIANCE"]
    else:
        # Modular monolith: one Postgres; DSNs share the behavior host/db with search_path
        pg_services = ["BEHAVIOR"]

    for service in pg_services:
        if not get_postgres_dsn(service):
            missing_services.append(f"PostgreSQL ({service})")

    if not check_redis_available():
        missing_services.append("Redis")

    if missing_services:
        pytest.exit(
            f"Test infrastructure not available: {', '.join(missing_services)}\n"
            f"Start with: podman compose -f infra/docker-compose.test.yml up -d\n"
            f"Or run: ./scripts/run_tests.sh",
            returncode=1,
        )


@pytest.fixture(scope="session", autouse=True)
def validate_all_dsns(request):
    """Validate every AMPREALIZE_*_PG_DSN env var targets a test database.

    Runs once at session start. If ANY DSN points to a known production
    database, the entire test session is aborted immediately. This prevents
    test fixtures from accidentally wiping production data via TRUNCATE.
    """
    marker_expr = request.config.getoption("-m", default="")
    if marker_expr == "unit":
        return
    try:
        _items = request.session.items
    except Exception:
        _items = None
    if _items and all(item.get_closest_marker("unit") is not None for item in _items):
        return

    offending: List[str] = []

    for key, value in sorted(os.environ.items()):
        if not key.startswith("AMPREALIZE_") or not key.endswith("_PG_DSN"):
            continue
        if not value or "mock" in value.lower():
            continue
        try:
            assert_test_database(value)
        except RuntimeError as exc:
            offending.append(f"  {key}: {_mask_dsn_password(value)}\n    → {exc}")

    if offending:
        pytest.exit(
            f"\n{'='*72}\n"
            f"SAFETY GUARD: Aborting test session — production DSNs detected!\n"
            f"\n"
            + "\n".join(offending) + "\n"
            f"\n"
            f"Fix: Ensure all AMPREALIZE_*_PG_DSN env vars point to test databases.\n"
            f"{'='*72}",
            returncode=1,
        )


# ---------------------------------------------------------------------------
# Transaction-rollback isolation (opt-in)
# ---------------------------------------------------------------------------
# Instead of TRUNCATE-based cleanup, tests decorated with
# @pytest.mark.usefixtures("transactional_db") or that request this fixture
# will wrap every PostgresPool.connection() call in a SAVEPOINT that is rolled
# back after the test. This is faster and guarantees zero leftover state,
# *provided* the test itself never calls conn.commit() (which releases SAVEPOINTs).
# ---------------------------------------------------------------------------

@pytest.fixture()
def transactional_db(monkeypatch):
    """Wrap all PostgresPool connections in SAVEPOINTs that are rolled back.

    Usage:
        def test_something(transactional_db):
            ...  # any DB writes are automatically undone after the test

    Limitations:
        - Tests must NOT call conn.commit() directly (it releases SAVEPOINTs).
        - Not suitable for tests that verify commit/rollback/transaction behaviour.
    """
    import uuid
    from contextlib import contextmanager
    from amprealize.storage.postgres_pool import PostgresPool

    _original_connection = PostgresPool.connection
    _savepoints: list = []

    @contextmanager
    def _savepoint_connection(self, *, autocommit: bool = True):
        with _original_connection(self, autocommit=False) as conn:
            sp_name = f"test_sp_{uuid.uuid4().hex[:12]}"
            _savepoints.append(sp_name)
            conn.cursor().execute(f"SAVEPOINT {sp_name}")
            try:
                yield conn
            finally:
                try:
                    conn.cursor().execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
                except Exception:
                    pass  # connection may already be in error state

    monkeypatch.setattr(PostgresPool, "connection", _savepoint_connection)
    yield
    # monkeypatch auto-restores the original method


@pytest.fixture(autouse=True)
def isolate_test_resources():
    """Ensure each test has isolated resources.

    Adds small delay between tests to allow connection cleanup.
    Prevents connection pool exhaustion from rapid test execution.
    """
    yield
    # Brief pause to allow connections to close properly
    time.sleep(0.05)


# ============================================================================
# PostgreSQL Service Fixtures
# ============================================================================

@pytest.fixture(scope="session")
def postgres_dsn_behavior(request) -> str:
    """PostgreSQL DSN for BehaviorService."""
    marker_expr = request.config.getoption("-m", default="")
    if marker_expr == "unit":
        return "postgresql://mock:mock@localhost:5432/mock"

    # Skip for load tests which mock services
    for arg in request.config.args:
        if "tests/load/" in str(arg) or "/load/" in str(arg):
             return "postgresql://mock:mock@localhost:5432/mock"

    dsn = get_postgres_dsn("BEHAVIOR")
    if not dsn:
        pytest.skip("BehaviorService PostgreSQL not configured")
    return dsn


@pytest.fixture(scope="session")
def postgres_dsn_workflow() -> str:
    """PostgreSQL DSN for WorkflowService."""
    dsn = get_postgres_dsn("WORKFLOW")
    if not dsn:
        pytest.skip("WorkflowService PostgreSQL not configured")
    return dsn


@pytest.fixture(scope="session")
def postgres_dsn_action() -> str:
    """PostgreSQL DSN for ActionService."""
    dsn = get_postgres_dsn("ACTION")
    if not dsn:
        pytest.skip("ActionService PostgreSQL not configured")
    return dsn


@pytest.fixture(scope="session")
def postgres_dsn_run() -> str:
    """PostgreSQL DSN for RunService."""
    dsn = get_postgres_dsn("RUN")
    if not dsn:
        pytest.skip("RunService PostgreSQL not configured")
    return dsn


@pytest.fixture(scope="session")
def postgres_dsn_compliance() -> str:
    """PostgreSQL DSN for ComplianceService."""
    dsn = get_postgres_dsn("COMPLIANCE")
    if not dsn:
        pytest.skip("ComplianceService PostgreSQL not configured")
    return dsn


@pytest.fixture(scope="session")
def postgres_dsn_auth() -> str:
    """PostgreSQL DSN for Auth."""
    dsn = get_postgres_dsn("AUTH")
    if not dsn:
        pytest.skip("Auth PostgreSQL not configured")
    return dsn


# ============================================================================
# Helper Functions
# ============================================================================

def _is_smoke_test_run(request_or_config) -> bool:
    """Detect if this test run is for smoke tests (which have their own infrastructure)."""
    # Get config from either request or config object
    config = getattr(request_or_config, 'config', request_or_config)

    # Check marker expression
    marker_expr = config.getoption("-m", default="")
    if marker_expr == "smoke":
        return True

    # Check test file paths
    for arg in config.args:
        if "tests/smoke/" in str(arg) or "/smoke/" in str(arg) or "smoke" in str(arg):
            return True

    return False


def _is_load_test_run(request_or_config) -> bool:
    """Detect if this test run is for load tests (which have minimal infrastructure)."""
    config = getattr(request_or_config, 'config', request_or_config)

    # Check marker expression
    marker_expr = config.getoption("-m", default="")
    if marker_expr == "load":
        return True

    # Check test file paths
    for arg in config.args:
        if "tests/load/" in str(arg) or "/load/" in str(arg):
            return True

    return False


def _is_minimal_infrastructure_run(request_or_config) -> bool:
    """Detect if this test run uses minimal infrastructure (skip full schema init)."""
    return _is_smoke_test_run(request_or_config) or _is_load_test_run(request_or_config)


# ============================================================================
# Database Schema Initialization
# ============================================================================

def _build_alembic_database_url_from_behavior_env() -> str | None:
    host = os.environ.get("AMPREALIZE_PG_HOST_BEHAVIOR")
    port = os.environ.get("AMPREALIZE_PG_PORT_BEHAVIOR")
    user = os.environ.get("AMPREALIZE_PG_USER_BEHAVIOR")
    password = os.environ.get("AMPREALIZE_PG_PASS_BEHAVIOR")
    dbname = os.environ.get("AMPREALIZE_PG_DB_BEHAVIOR")
    if not all([host, port, user, password, dbname]):
        return None
    uq = urllib.parse.quote(user, safe="")
    pq = urllib.parse.quote(password, safe="")
    return (
        f"postgresql://{uq}:{pq}@{host}:{port}/{dbname}"
        f"?connect_timeout={CONNECTION_TIMEOUT}"
    )


def _resolve_alembic_database_url() -> str | None:
    for key in (
        "AMPREALIZE_ALEMBIC_DATABASE_URL",
        "AMPREALIZE_ALEMBIC_DATABASE_URL",
        "DATABASE_URL",
    ):
        if v := os.environ.get(key):
            return v
    return _build_alembic_database_url_from_behavior_env()


def _run_legacy_per_service_migration_scripts() -> None:
    import subprocess

    migrations = [
        ("BEHAVIOR", "scripts/run_postgres_behavior_migration.py"),
        ("WORKFLOW", "scripts/run_postgres_workflow_migration.py"),
        ("ACTION", "scripts/run_postgres_action_migration.py"),
        ("RUN", "scripts/run_postgres_run_migration.py"),
        ("COMPLIANCE", "scripts/run_postgres_compliance_migration.py"),
        ("AUTH", "scripts/run_postgres_auth_migration.py"),
    ]

    for service_name, script_path in migrations:
        host = os.environ.get(f"AMPREALIZE_PG_HOST_{service_name}")
        port = os.environ.get(f"AMPREALIZE_PG_PORT_{service_name}")
        user = os.environ.get(f"AMPREALIZE_PG_USER_{service_name}")
        password = os.environ.get(f"AMPREALIZE_PG_PASS_{service_name}")
        dbname = os.environ.get(f"AMPREALIZE_PG_DB_{service_name}")

        if not all([host, port, user, password, dbname]):
            continue

        dsn = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"

        script = REPO_ROOT / script_path
        if not script.exists():
            continue

        try:
            env = os.environ.copy()
            env[f"AMPREALIZE_{service_name}_PG_DSN"] = dsn

            subprocess.run(
                [sys.executable, str(script)],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
                env=env,
            )
        except subprocess.CalledProcessError as e:
            out = ((e.stderr or "") + (e.stdout or "")).lower()
            if "migration file not found" in out:
                continue
            if "already exists" not in out:
                combined = "\n".join(
                    x for x in (e.stderr, e.stdout) if x
                ).strip() or "(no output)"
                pytest.exit(
                    f"Failed to initialize {service_name} schema:\n{combined}",
                    returncode=1,
                )


@pytest.fixture(scope="session", autouse=True)
def initialize_test_schemas(request):
    """Ensure Postgres schemas exist once per session (Alembic or legacy SQL scripts).

    Skips smoke/load tests and when ``AMPREALIZE_ALEMBIC_SCHEMA_READY=1`` (e.g. after
    ``scripts/run_tests.sh`` applied Alembic). Default layout is a single modular-monolith
    database; set ``AMPREALIZE_TEST_PER_SERVICE_PG_DATABASES=1`` for legacy per-service Postgres.
    """
    if _is_minimal_infrastructure_run(request):
        return

    try:
        _items = request.session.items
    except Exception:
        _items = None
    if _items and all(item.get_closest_marker("unit") is not None for item in _items):
        return

    if os.getenv("AMPREALIZE_TEST_INFRA_MODE", "legacy") == "breakeramp":
        return

    if os.getenv("AMPREALIZE_ALEMBIC_SCHEMA_READY") == "1":
        return

    import subprocess

    if os.getenv("AMPREALIZE_TEST_PER_SERVICE_PG_DATABASES") == "1":
        _run_legacy_per_service_migration_scripts()
        return

    url = _resolve_alembic_database_url()
    if not url:
        return

    alembic_script = REPO_ROOT / "scripts" / "run_alembic_migrations.py"
    if not alembic_script.is_file():
        return

    try:
        subprocess.run(
            [sys.executable, str(alembic_script)],
            env={**os.environ, "DATABASE_URL": url},
            check=True,
            timeout=300,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        combined = "\n".join(x for x in (e.stderr, e.stdout) if x).strip() or "(no output)"
        pytest.exit(
            f"Alembic upgrade failed:\n{combined}",
            returncode=1,
        )


@pytest.fixture(scope="session", autouse=True)
def seed_launch_behavior(request) -> None:
    """Ensure at least one approved launch behavior exists for API parity tests."""
    marker_expr = request.config.getoption("-m", default="")
    if marker_expr == "unit":
        return

    # Skip for smoke/load tests - they have their own infrastructure
    if _is_minimal_infrastructure_run(request):
        return

    try:
        _items = request.session.items
    except Exception:
        _items = None
    if _items and all(item.get_closest_marker("unit") is not None for item in _items):
        return

    # Get DSN - skip if not configured
    postgres_dsn_behavior = get_postgres_dsn("BEHAVIOR")
    if not postgres_dsn_behavior:
        return

    if "mock" in postgres_dsn_behavior:
        return

    service = BehaviorService(dsn=postgres_dsn_behavior)
    probe = SearchBehaviorsRequest(query="launch", status="APPROVED", limit=1)
    existing = service.search_behaviors(probe)
    if existing:
        try:
            get_cache().invalidate_service("retriever")
        except Exception:
            pass
        return

    actor = Actor(id="tests", role="ENGINEER", surface="tests")
    draft = service.create_behavior_draft(
        CreateBehaviorDraftRequest(
            name="behavior_launch_plan_seed",
            description="Seed behavior that teaches Amprealize how to plan a launch.",
            instruction=(
                "Outline launch goals, dependencies, comms, and validation steps. "
                "Keep the plan concise and reference reusable playbooks."
            ),
            role_focus="STRATEGIST",
            trigger_keywords=["launch", "plan", "strategy"],
            tags=["launch", "plan", "strategy"],
            metadata={
                "citation_label": "Launch Playbook",
                "seed": "tests",
            },
        ),
        actor,
    )

    service.approve_behavior(
        ApproveBehaviorRequest(
            behavior_id=draft.behavior_id,
            version=draft.version,
            effective_from=utc_now_iso(),
        ),
        actor,
    )

    try:
        cache = get_cache()
        cache.invalidate_service("behavior")
        cache.invalidate_service("retriever")
    except Exception:
        pass


# ============================================================================
# Redis Fixtures
# ============================================================================

@pytest.fixture
def redis_client() -> Generator:
    """Provide Redis client with proper cleanup."""
    if not check_redis_available():
        pytest.skip("Redis not available")

    import redis

    host = os.environ.get("REDIS_HOST", "localhost")
    port = int(os.environ.get("REDIS_PORT", "6379"))

    client = redis.Redis(
        host=host,
        port=port,
        socket_connect_timeout=CONNECTION_TIMEOUT,
        socket_timeout=CONNECTION_TIMEOUT,
        decode_responses=True,
    )

    try:
        yield client
    finally:
        # Clean up test keys
        try:
            for key in client.scan_iter("test:*"):
                client.delete(key)
        except Exception:
            pass
        finally:
            client.close()
