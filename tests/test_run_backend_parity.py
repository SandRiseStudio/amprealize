"""Backend parity tests for RunService across SQLite and PostgreSQL.

Validates that RunService operations produce consistent results
regardless of which backend is used (SQLite or PostgreSQL).

Tests cover:
- CRUD operations: create_run, list_runs, get_run, delete_run
- Progress updates: update_run with status/progress/metadata changes
- Step operations: create_step, update_step, get_steps
- Completion operations: complete_run, cancel_run
- Error handling: RunNotFoundError for missing runs
- Data integrity: timestamps, JSONB fields, behavior_ids arrays
- CASCADE delete: run_steps deletion when parent run is deleted
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Generator

try:
    import psycopg2  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - psycopg2 is optional for lint environments
    psycopg2 = None
import pytest

from amprealize.action_contracts import Actor
from amprealize.run_contracts import (
    Run,
    RunCompletion,
    RunCreateRequest,
    RunProgressUpdate,
    RunStatus,
)
from amprealize.run_service import (
    RunService,
    RunNotFoundError as MemoryRunNotFoundError,
)
from amprealize.run_service_postgres import (
    PostgresRunService,
    RunNotFoundError as PostgresRunNotFoundError,
)


# Test constants
NONEXISTENT_RUN_ID = "00000000-0000-0000-0000-000000000001"

TEST_ACTOR = Actor(id="test-user", role="engineer", surface="cli")


def _truncate_run_tables(dsn: str) -> None:
    """Remove all data from run tables to ensure test isolation."""
    from conftest import safe_truncate
    safe_truncate(dsn, ["run_steps", "runs"])


def _seed_test_users(dsn: str) -> None:
    """Ensure test actor IDs exist in auth.users so FK constraints pass."""
    import psycopg2
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            for uid, email, name in [
                ("test-user", "test-user@example.com", "Test User"),
            ]:
                cur.execute(
                    """
                    INSERT INTO auth.users (id, email, display_name)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (uid, email, name),
                )
    finally:
        conn.close()


@pytest.fixture
def postgres_dsn() -> Generator[str, None, None]:
    """Discover PostgreSQL DSN from environment."""
    dsn = os.environ.get("AMPREALIZE_RUN_PG_DSN")
    if not dsn:
        pytest.skip("AMPREALIZE_RUN_PG_DSN not set; skipping PostgreSQL parity tests")
    yield dsn


@pytest.fixture
def run_service_postgres(postgres_dsn: str) -> Generator[PostgresRunService, None, None]:
    """Create a fresh PostgresRunService backed by PostgreSQL for each test."""
    _truncate_run_tables(postgres_dsn)
    _seed_test_users(postgres_dsn)
    service = PostgresRunService(dsn=postgres_dsn)

    try:
        yield service
    finally:
        service.close()


@pytest.fixture
def run_service_sqlite() -> Generator[RunService, None, None]:
    """Create a fresh RunService backed by SQLite for each test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_runs.db"
        service = RunService(db_path=db_path)
        yield service


# ------------------------------------------------------------------
# Parity Tests - Run CRUD Operations
# ------------------------------------------------------------------
def test_create_run_parity(run_service_sqlite: RunService, run_service_postgres: PostgresRunService) -> None:
    """Both backends should create a run with identical fields."""
    request = RunCreateRequest(
        actor=TEST_ACTOR,
        workflow_id="wf_123",
        workflow_name="Test Workflow",
        template_id="tpl_456",
        template_name="Test Template",
        behavior_ids=["beh_001", "beh_002"],
        initial_message="Starting test run",
        total_steps=5,
        metadata={"environment": "test"},
    )

    run_sqlite = run_service_sqlite.create_run(request)
    run_postgres = run_service_postgres.create_run(request)

    # Validate structure
    assert run_sqlite.status == RunStatus.PENDING
    assert run_postgres.status == RunStatus.PENDING
    assert run_sqlite.actor.id == TEST_ACTOR.id
    assert run_postgres.actor.id == TEST_ACTOR.id
    assert run_sqlite.workflow_id == "wf_123"
    assert run_postgres.workflow_id == "wf_123"
    assert run_sqlite.template_id == "tpl_456"
    assert run_postgres.template_id == "tpl_456"
    assert run_sqlite.behavior_ids == ["beh_001", "beh_002"]
    assert run_postgres.behavior_ids == ["beh_001", "beh_002"]
    assert run_sqlite.progress_pct == 0.0
    assert run_postgres.progress_pct == 0.0
    assert run_sqlite.message == "Starting test run"
    assert run_postgres.message == "Starting test run"
    assert run_sqlite.metadata == {"environment": "test", "execution": {"total_steps": 5}}
    assert run_postgres.metadata == {"environment": "test", "execution": {"total_steps": 5}}


def test_get_run_not_found(run_service_sqlite: RunService, run_service_postgres: PostgresRunService) -> None:
    """Both backends should raise RunNotFoundError for missing runs."""
    with pytest.raises(MemoryRunNotFoundError):
        run_service_sqlite.get_run(NONEXISTENT_RUN_ID)

    with pytest.raises(PostgresRunNotFoundError):
        run_service_postgres.get_run(NONEXISTENT_RUN_ID)


def test_list_runs_empty(run_service_sqlite: RunService, run_service_postgres: PostgresRunService) -> None:
    """Both backends should return empty list when no runs exist."""
    assert run_service_sqlite.list_runs() == []
    assert run_service_postgres.list_runs() == []


def test_list_runs_with_filters(run_service_sqlite: RunService, run_service_postgres: PostgresRunService) -> None:
    """Both backends should filter runs by status, workflow_id, template_id."""
    request1 = RunCreateRequest(
        actor=TEST_ACTOR,
        workflow_id="wf_1",
        template_id="tpl_1",
        behavior_ids=["beh_001"],
    )
    request2 = RunCreateRequest(
        actor=TEST_ACTOR,
        workflow_id="wf_2",
        template_id="tpl_2",
        behavior_ids=["beh_002"],
    )

    run1_sqlite = run_service_sqlite.create_run(request1)
    run2_sqlite = run_service_sqlite.create_run(request2)
    run1_postgres = run_service_postgres.create_run(request1)
    run2_postgres = run_service_postgres.create_run(request2)

    # Filter by workflow_id
    assert len(run_service_sqlite.list_runs(workflow_id="wf_1")) == 1
    assert len(run_service_postgres.list_runs(workflow_id="wf_1")) == 1

    # Filter by template_id
    assert len(run_service_sqlite.list_runs(template_id="tpl_2")) == 1
    assert len(run_service_postgres.list_runs(template_id="tpl_2")) == 1

    # Filter by status
    assert len(run_service_sqlite.list_runs(status=RunStatus.PENDING)) == 2
    assert len(run_service_postgres.list_runs(status=RunStatus.PENDING)) == 2


def test_delete_run_cascades_to_steps(run_service_sqlite: RunService, run_service_postgres: PostgresRunService) -> None:
    """Both backends should CASCADE delete run_steps when run is deleted."""
    request = RunCreateRequest(
        actor=TEST_ACTOR,
        workflow_id="wf_123",
        behavior_ids=["beh_001"],
    )

    # SQLite test
    run_sqlite = run_service_sqlite.create_run(request)
    update_sqlite = RunProgressUpdate(
        status=RunStatus.RUNNING,
        step_id="step_001",
        step_name="Initialize",
        step_status=RunStatus.RUNNING,
    )
    run_service_sqlite.update_run(run_sqlite.run_id, update_sqlite)
    updated_sqlite = run_service_sqlite.get_run(run_sqlite.run_id)
    assert len(updated_sqlite.steps) == 1

    run_service_sqlite.delete_run(run_sqlite.run_id)
    with pytest.raises(MemoryRunNotFoundError):
        run_service_sqlite.get_run(run_sqlite.run_id)

    # PostgreSQL test
    run_postgres = run_service_postgres.create_run(request)
    update_postgres = RunProgressUpdate(
        status=RunStatus.RUNNING,
        step_id="step_001",
        step_name="Initialize",
        step_status=RunStatus.RUNNING,
    )
    run_service_postgres.update_run(run_postgres.run_id, update_postgres)
    updated_postgres = run_service_postgres.get_run(run_postgres.run_id)
    assert len(updated_postgres.steps) == 1

    run_service_postgres.delete_run(run_postgres.run_id)
    with pytest.raises(PostgresRunNotFoundError):
        run_service_postgres.get_run(run_postgres.run_id)


# ------------------------------------------------------------------
# Parity Tests - Run Progress Updates
# ------------------------------------------------------------------
def test_update_run_status_to_running(run_service_sqlite: RunService, run_service_postgres: PostgresRunService) -> None:
    """Both backends should auto-populate started_at when status changes to RUNNING."""
    request = RunCreateRequest(
        actor=TEST_ACTOR,
        workflow_id="wf_123",
        behavior_ids=["beh_001"],
    )

    run_sqlite = run_service_sqlite.create_run(request)
    run_postgres = run_service_postgres.create_run(request)

    update = RunProgressUpdate(status=RunStatus.RUNNING, progress_pct=10.0)

    updated_sqlite = run_service_sqlite.update_run(run_sqlite.run_id, update)
    updated_postgres = run_service_postgres.update_run(run_postgres.run_id, update)

    assert updated_sqlite.status == RunStatus.RUNNING
    assert updated_postgres.status == RunStatus.RUNNING
    assert updated_sqlite.started_at is not None
    assert updated_postgres.started_at is not None
    assert updated_sqlite.progress_pct == 10.0
    assert updated_postgres.progress_pct == 10.0


def test_update_run_progress_increments(run_service_sqlite: RunService, run_service_postgres: PostgresRunService) -> None:
    """Both backends should update progress_pct correctly."""
    request = RunCreateRequest(
        actor=TEST_ACTOR,
        workflow_id="wf_123",
        behavior_ids=["beh_001"],
    )

    run_sqlite = run_service_sqlite.create_run(request)
    run_postgres = run_service_postgres.create_run(request)

    # Progress from 0 → 25 → 50 → 75
    for pct in [25.0, 50.0, 75.0]:
        update = RunProgressUpdate(progress_pct=pct)
        run_sqlite = run_service_sqlite.update_run(run_sqlite.run_id, update)
        run_postgres = run_service_postgres.update_run(run_postgres.run_id, update)
        assert run_sqlite.progress_pct == pct
        assert run_postgres.progress_pct == pct


def test_update_run_with_metadata_merge(run_service_sqlite: RunService, run_service_postgres: PostgresRunService) -> None:
    """Both backends should merge metadata updates."""
    request = RunCreateRequest(
        actor=TEST_ACTOR,
        workflow_id="wf_123",
        behavior_ids=["beh_001"],
        metadata={"env": "test"},
    )

    run_sqlite = run_service_sqlite.create_run(request)
    run_postgres = run_service_postgres.create_run(request)

    update = RunProgressUpdate(metadata={"step_count": 3, "env": "production"})

    updated_sqlite = run_service_sqlite.update_run(run_sqlite.run_id, update)
    updated_postgres = run_service_postgres.update_run(run_postgres.run_id, update)

    # Metadata should be merged (env overwritten, step_count added)
    assert updated_sqlite.metadata["step_count"] == 3
    assert updated_postgres.metadata["step_count"] == 3
    assert updated_sqlite.metadata["env"] == "production"
    assert updated_postgres.metadata["env"] == "production"


def test_update_run_with_token_metrics(run_service_sqlite: RunService, run_service_postgres: PostgresRunService) -> None:
    """Both backends should store tokens_generated and tokens_baseline in metadata."""
    request = RunCreateRequest(
        actor=TEST_ACTOR,
        workflow_id="wf_123",
        behavior_ids=["beh_001"],
    )

    run_sqlite = run_service_sqlite.create_run(request)
    run_postgres = run_service_postgres.create_run(request)

    update = RunProgressUpdate(tokens_generated=500, tokens_baseline=1000)

    updated_sqlite = run_service_sqlite.update_run(run_sqlite.run_id, update)
    updated_postgres = run_service_postgres.update_run(run_postgres.run_id, update)

    assert updated_sqlite.metadata["tokens"]["generated"] == 500
    assert updated_postgres.metadata["tokens"]["generated"] == 500
    assert updated_sqlite.metadata["tokens"]["baseline"] == 1000
    assert updated_postgres.metadata["tokens"]["baseline"] == 1000


# ------------------------------------------------------------------
# Parity Tests - Run Completion
# ------------------------------------------------------------------
def test_complete_run_success(run_service_sqlite: RunService, run_service_postgres: PostgresRunService) -> None:
    """Both backends should set completed_at, duration_ms, progress_pct=100 on COMPLETED."""
    request = RunCreateRequest(
        actor=TEST_ACTOR,
        workflow_id="wf_123",
        behavior_ids=["beh_001"],
    )

    run_sqlite = run_service_sqlite.create_run(request)
    run_postgres = run_service_postgres.create_run(request)

    # Start runs
    run_service_sqlite.update_run(run_sqlite.run_id, RunProgressUpdate(status=RunStatus.RUNNING))
    run_service_postgres.update_run(run_postgres.run_id, RunProgressUpdate(status=RunStatus.RUNNING))

    # Complete runs
    completion = RunCompletion(
        status=RunStatus.COMPLETED,
        message="Success!",
        outputs={"result": "done"},
    )

    completed_sqlite = run_service_sqlite.complete_run(run_sqlite.run_id, completion)
    completed_postgres = run_service_postgres.complete_run(run_postgres.run_id, completion)

    assert completed_sqlite.status == RunStatus.COMPLETED
    assert completed_postgres.status == RunStatus.COMPLETED
    assert completed_sqlite.progress_pct == 100.0
    assert completed_postgres.progress_pct == 100.0
    assert completed_sqlite.completed_at is not None
    assert completed_postgres.completed_at is not None
    assert completed_sqlite.duration_ms is not None
    assert completed_postgres.duration_ms is not None
    assert completed_sqlite.outputs == {"result": "done"}
    assert completed_postgres.outputs == {"result": "done"}


def test_complete_run_failed(run_service_sqlite: RunService, run_service_postgres: PostgresRunService) -> None:
    """Both backends should set error field and status=FAILED."""
    request = RunCreateRequest(
        actor=TEST_ACTOR,
        workflow_id="wf_123",
        behavior_ids=["beh_001"],
    )

    run_sqlite = run_service_sqlite.create_run(request)
    run_postgres = run_service_postgres.create_run(request)

    completion = RunCompletion(
        status=RunStatus.FAILED,
        message="Run failed",
        error="Division by zero",
    )

    completed_sqlite = run_service_sqlite.complete_run(run_sqlite.run_id, completion)
    completed_postgres = run_service_postgres.complete_run(run_postgres.run_id, completion)

    assert completed_sqlite.status == RunStatus.FAILED
    assert completed_postgres.status == RunStatus.FAILED
    assert completed_sqlite.error == "Division by zero"
    assert completed_postgres.error == "Division by zero"


def test_cancel_run(run_service_sqlite: RunService, run_service_postgres: PostgresRunService) -> None:
    """Both backends should cancel a run with status=CANCELLED."""
    request = RunCreateRequest(
        actor=TEST_ACTOR,
        workflow_id="wf_123",
        behavior_ids=["beh_001"],
    )

    run_sqlite = run_service_sqlite.create_run(request)
    run_postgres = run_service_postgres.create_run(request)

    cancelled_sqlite = run_service_sqlite.cancel_run(run_sqlite.run_id, reason="User requested cancellation")
    cancelled_postgres = run_service_postgres.cancel_run(run_postgres.run_id, reason="User requested cancellation")

    assert cancelled_sqlite.status == RunStatus.CANCELLED
    assert cancelled_postgres.status == RunStatus.CANCELLED
    assert cancelled_sqlite.message == "User requested cancellation"
    assert cancelled_postgres.message == "User requested cancellation"


# ------------------------------------------------------------------
# Parity Tests - Run Steps
# ------------------------------------------------------------------
def test_create_step_via_update_run(run_service_sqlite: RunService, run_service_postgres: PostgresRunService) -> None:
    """Both backends should create steps when step_id is provided in RunProgressUpdate."""
    request = RunCreateRequest(
        actor=TEST_ACTOR,
        workflow_id="wf_123",
        behavior_ids=["beh_001"],
    )

    run_sqlite = run_service_sqlite.create_run(request)
    run_postgres = run_service_postgres.create_run(request)

    update = RunProgressUpdate(
        status=RunStatus.RUNNING,
        step_id="step_001",
        step_name="Initialize",
        step_status=RunStatus.RUNNING,
        progress_pct=20.0,
        metadata={"action": "setup"},
    )

    updated_sqlite = run_service_sqlite.update_run(run_sqlite.run_id, update)
    updated_postgres = run_service_postgres.update_run(run_postgres.run_id, update)

    # Validate steps were created
    assert len(updated_sqlite.steps) == 1
    assert len(updated_postgres.steps) == 1
    assert updated_sqlite.steps[0].step_id == "step_001"
    assert updated_postgres.steps[0].step_id == "step_001"
    assert updated_sqlite.steps[0].name == "Initialize"
    assert updated_postgres.steps[0].name == "Initialize"
    assert updated_sqlite.steps[0].status == RunStatus.RUNNING
    assert updated_postgres.steps[0].status == RunStatus.RUNNING
    assert updated_sqlite.steps[0].progress_pct == 20.0
    assert updated_postgres.steps[0].progress_pct == 20.0


def test_update_step_status_to_completed(run_service_sqlite: RunService, run_service_postgres: PostgresRunService) -> None:
    """Both backends should update existing step status and set completed_at."""
    request = RunCreateRequest(
        actor=TEST_ACTOR,
        workflow_id="wf_123",
        behavior_ids=["beh_001"],
    )

    run_sqlite = run_service_sqlite.create_run(request)
    run_postgres = run_service_postgres.create_run(request)

    # Create step
    create_update = RunProgressUpdate(
        step_id="step_001",
        step_name="Process",
        step_status=RunStatus.RUNNING,
    )
    run_service_sqlite.update_run(run_sqlite.run_id, create_update)
    run_service_postgres.update_run(run_postgres.run_id, create_update)

    # Complete step
    complete_update = RunProgressUpdate(
        step_id="step_001",
        step_status=RunStatus.COMPLETED,
        progress_pct=100.0,
    )
    updated_sqlite = run_service_sqlite.update_run(run_sqlite.run_id, complete_update)
    updated_postgres = run_service_postgres.update_run(run_postgres.run_id, complete_update)

    assert updated_sqlite.steps[0].status == RunStatus.COMPLETED
    assert updated_postgres.steps[0].status == RunStatus.COMPLETED
    assert updated_sqlite.steps[0].completed_at is not None
    assert updated_postgres.steps[0].completed_at is not None


def test_multiple_steps_ordered(run_service_sqlite: RunService, run_service_postgres: PostgresRunService) -> None:
    """Both backends should return steps ordered by started_at."""
    request = RunCreateRequest(
        actor=TEST_ACTOR,
        workflow_id="wf_123",
        behavior_ids=["beh_001"],
    )

    run_sqlite = run_service_sqlite.create_run(request)
    run_postgres = run_service_postgres.create_run(request)

    # Create 3 steps in sequence
    for i in range(1, 4):
        update = RunProgressUpdate(
            step_id=f"step_00{i}",
            step_name=f"Step {i}",
            step_status=RunStatus.RUNNING,
        )
        run_service_sqlite.update_run(run_sqlite.run_id, update)
        run_service_postgres.update_run(run_postgres.run_id, update)

    final_sqlite = run_service_sqlite.get_run(run_sqlite.run_id)
    final_postgres = run_service_postgres.get_run(run_postgres.run_id)

    # Steps should be ordered
    assert len(final_sqlite.steps) == 3
    assert len(final_postgres.steps) == 3
    assert final_sqlite.steps[0].step_id == "step_001"
    assert final_postgres.steps[0].step_id == "step_001"
    assert final_sqlite.steps[2].step_id == "step_003"
    assert final_postgres.steps[2].step_id == "step_003"
