"""Parity tests for ActionService across CLI/REST/MCP surfaces.

Validates that ActionService operations produce consistent results
regardless of which surface invokes them (CLI, REST API, MCP tools).

Tests cover:
- CRUD operations: create_action, list_actions, get_action
- Replay operations: replay_actions, get_replay_status
- Error handling: ActionNotFoundError, ReplayNotFoundError
- Data integrity: checksums, timestamps, JSONB fields
"""

from __future__ import annotations

import os
from typing import Generator

try:
    import psycopg2  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - psycopg2 is optional for lint environments
    psycopg2 = None
import pytest

from amprealize.action_contracts import (
    Action,
    ActionCreateRequest,
    Actor,
    ReplayOptions,
    ReplayRequest,
)
from amprealize.action_service import (
    ActionService,
    ActionNotFoundError as MemoryActionNotFoundError,
    ReplayNotFoundError as MemoryReplayNotFoundError,
)
from amprealize.action_service_postgres import (
    ActionNotFoundError as PostgresActionNotFoundError,
    PostgresActionService,
    ReplayNotFoundError as PostgresReplayNotFoundError,
)


# Test constants
NONEXISTENT_ACTION_ID = "00000000-0000-0000-0000-000000000001"
NONEXISTENT_REPLAY_ID = "00000000-0000-0000-0000-000000000002"

TEST_ACTOR = Actor(id="test-user", role="engineer", surface="cli")


def _truncate_action_tables(dsn: str) -> None:
    """Remove all data from action tables to ensure test isolation."""
    from conftest import safe_truncate
    safe_truncate(dsn, ["replays", "actions"])


@pytest.fixture
def postgres_dsn() -> Generator[str, None, None]:
    """Discover PostgreSQL DSN from environment."""
    dsn = os.environ.get("AMPREALIZE_ACTION_PG_DSN")
    if not dsn:
        pytest.skip("AMPREALIZE_ACTION_PG_DSN not set; skipping PostgreSQL parity tests")
    yield dsn


@pytest.fixture
def action_service_postgres(postgres_dsn: str) -> Generator[PostgresActionService, None, None]:
    """Create a fresh PostgresActionService backed by PostgreSQL for each test."""
    _truncate_action_tables(postgres_dsn)
    service = PostgresActionService(dsn=postgres_dsn)

    try:
        yield service
    finally:
        _truncate_action_tables(postgres_dsn)


@pytest.fixture
def action_service_memory() -> Generator[ActionService, None, None]:
    """Create a fresh in-memory ActionService for each test."""
    service = ActionService()
    yield service


# ------------------------------------------------------------------
# CRUD Operation Tests
# ------------------------------------------------------------------


def test_create_action_postgres(action_service_postgres: PostgresActionService) -> None:
    """Test creating an action in PostgreSQL backend."""
    request = ActionCreateRequest(
        artifact_path="/tmp/test.py",
        summary="Test action creation",
        behaviors_cited=["behavior-1", "behavior-2"],
        metadata={"source": "pytest"},
    )

    action = action_service_postgres.create_action(request, TEST_ACTOR)

    assert action.action_id is not None
    assert action.artifact_path == "/tmp/test.py"
    assert action.summary == "Test action creation"
    assert action.behaviors_cited == ["behavior-1", "behavior-2"]
    assert action.metadata == {"source": "pytest"}
    assert action.actor.id == "test-user"
    assert action.actor.role == "engineer"
    assert action.actor.surface == "cli"
    assert action.replay_status == "NOT_STARTED"
    assert action.checksum != ""


def test_create_action_memory(action_service_memory: ActionService) -> None:
    """Test creating an action in in-memory backend."""
    request = ActionCreateRequest(
        artifact_path="/tmp/test.py",
        summary="Test action creation",
        behaviors_cited=["behavior-1", "behavior-2"],
        metadata={"source": "pytest"},
    )

    action = action_service_memory.create_action(request, TEST_ACTOR)

    assert action.action_id is not None
    assert action.artifact_path == "/tmp/test.py"
    assert action.summary == "Test action creation"
    assert action.behaviors_cited == ["behavior-1", "behavior-2"]
    assert action.metadata == {"source": "pytest"}
    assert action.actor.id == "test-user"
    assert action.replay_status == "NOT_STARTED"


def test_list_actions_postgres(action_service_postgres: PostgresActionService) -> None:
    """Test listing actions in PostgreSQL backend."""
    # Create multiple actions
    for i in range(3):
        request = ActionCreateRequest(
            artifact_path=f"/tmp/test_{i}.py",
            summary=f"Action {i}",
            behaviors_cited=["behavior-1"],
            metadata={"index": i},
        )
        action_service_postgres.create_action(request, TEST_ACTOR)

    actions = action_service_postgres.list_actions()

    assert len(actions) == 3
    assert actions[0].summary == "Action 0"
    assert actions[1].summary == "Action 1"
    assert actions[2].summary == "Action 2"
    # Verify chronological order
    assert actions[0].timestamp < actions[1].timestamp < actions[2].timestamp


def test_list_actions_memory(action_service_memory: ActionService) -> None:
    """Test listing actions in in-memory backend."""
    # Create multiple actions
    for i in range(3):
        request = ActionCreateRequest(
            artifact_path=f"/tmp/test_{i}.py",
            summary=f"Action {i}",
            behaviors_cited=["behavior-1"],
            metadata={"index": i},
        )
        action_service_memory.create_action(request, TEST_ACTOR)

    actions = action_service_memory.list_actions()

    assert len(actions) == 3
    assert actions[0].summary == "Action 0"
    assert actions[1].summary == "Action 1"
    assert actions[2].summary == "Action 2"


def test_get_action_postgres(action_service_postgres: PostgresActionService) -> None:
    """Test retrieving a single action from PostgreSQL backend."""
    request = ActionCreateRequest(
        artifact_path="/tmp/retrieve.py",
        summary="Retrieve this action",
        behaviors_cited=["behavior-1"],
        metadata={"test": "get"},
    )
    created = action_service_postgres.create_action(request, TEST_ACTOR)

    retrieved = action_service_postgres.get_action(created.action_id)

    assert retrieved.action_id == created.action_id
    assert retrieved.artifact_path == "/tmp/retrieve.py"
    assert retrieved.summary == "Retrieve this action"
    assert retrieved.behaviors_cited == ["behavior-1"]
    assert retrieved.metadata == {"test": "get"}


def test_get_action_memory(action_service_memory: ActionService) -> None:
    """Test retrieving a single action from in-memory backend."""
    request = ActionCreateRequest(
        artifact_path="/tmp/retrieve.py",
        summary="Retrieve this action",
        behaviors_cited=["behavior-1"],
        metadata={"test": "get"},
    )
    created = action_service_memory.create_action(request, TEST_ACTOR)

    retrieved = action_service_memory.get_action(created.action_id)

    assert retrieved.action_id == created.action_id
    assert retrieved.artifact_path == "/tmp/retrieve.py"
    assert retrieved.summary == "Retrieve this action"


def test_get_action_not_found_postgres(action_service_postgres: PostgresActionService) -> None:
    """Test ActionNotFoundError when action doesn't exist in PostgreSQL."""
    with pytest.raises(PostgresActionNotFoundError, match="not found"):
        action_service_postgres.get_action(NONEXISTENT_ACTION_ID)


def test_get_action_not_found_memory(action_service_memory: ActionService) -> None:
    """Test ActionNotFoundError when action doesn't exist in memory."""
    with pytest.raises(MemoryActionNotFoundError, match="not found"):
        action_service_memory.get_action(NONEXISTENT_ACTION_ID)


# ------------------------------------------------------------------
# Replay Operation Tests
# ------------------------------------------------------------------


def test_replay_actions_postgres(action_service_postgres: PostgresActionService) -> None:
    """Test replaying actions in PostgreSQL backend."""
    # Create actions to replay
    action_ids = []
    for i in range(3):
        request = ActionCreateRequest(
            artifact_path=f"/tmp/replay_{i}.py",
            summary=f"Replay action {i}",
            behaviors_cited=["behavior-1"],
            metadata={"replay_test": True},
        )
        action = action_service_postgres.create_action(request, TEST_ACTOR)
        action_ids.append(action.action_id)

    # Replay actions
    replay_request = ReplayRequest(
        action_ids=action_ids,
        strategy="SEQUENTIAL",
        options=ReplayOptions(skip_existing=False, dry_run=False),
    )
    status = action_service_postgres.replay_actions(replay_request, TEST_ACTOR)

    assert status.replay_id is not None
    assert status.status == "SUCCEEDED"
    assert status.progress == 1.0
    assert len(status.logs) > 0
    assert len(status.failed_action_ids) == 0

    # Verify actions were updated
    for action_id in action_ids:
        action = action_service_postgres.get_action(action_id)
        assert action.replay_status == "SUCCEEDED"


def test_replay_actions_memory(action_service_memory: ActionService) -> None:
    """Test replaying actions in in-memory backend."""
    # Create actions to replay
    action_ids = []
    for i in range(3):
        request = ActionCreateRequest(
            artifact_path=f"/tmp/replay_{i}.py",
            summary=f"Replay action {i}",
            behaviors_cited=["behavior-1"],
            metadata={"replay_test": True},
        )
        action = action_service_memory.create_action(request, TEST_ACTOR)
        action_ids.append(action.action_id)

    # Replay actions
    replay_request = ReplayRequest(
        action_ids=action_ids,
        strategy="SEQUENTIAL",
        options=ReplayOptions(skip_existing=False, dry_run=False),
    )
    status = action_service_memory.replay_actions(replay_request, TEST_ACTOR)

    assert status.replay_id is not None
    assert status.status == "SUCCEEDED"
    assert status.progress == 1.0
    assert len(status.failed_action_ids) == 0


def test_replay_actions_skip_existing_postgres(action_service_postgres: PostgresActionService) -> None:
    """Test replay with skip_existing option in PostgreSQL."""
    # Create and replay an action
    request = ActionCreateRequest(
        artifact_path="/tmp/skip_test.py",
        summary="Skip existing test",
        behaviors_cited=["behavior-1"],
        metadata={},
    )
    action = action_service_postgres.create_action(request, TEST_ACTOR)

    # First replay
    replay_request = ReplayRequest(
        action_ids=[action.action_id],
        strategy="SEQUENTIAL",
        options=ReplayOptions(skip_existing=False, dry_run=False),
    )
    action_service_postgres.replay_actions(replay_request, TEST_ACTOR)

    # Second replay with skip_existing=True
    replay_request2 = ReplayRequest(
        action_ids=[action.action_id],
        strategy="SEQUENTIAL",
        options=ReplayOptions(skip_existing=True, dry_run=False),
    )
    status2 = action_service_postgres.replay_actions(replay_request2, TEST_ACTOR)

    assert status2.status == "SUCCEEDED"
    # Action should still be SUCCEEDED (not re-replayed)
    action = action_service_postgres.get_action(action.action_id)
    assert action.replay_status == "SUCCEEDED"


def test_replay_actions_dry_run_postgres(action_service_postgres: PostgresActionService) -> None:
    """Test replay with dry_run option in PostgreSQL."""
    request = ActionCreateRequest(
        artifact_path="/tmp/dry_run.py",
        summary="Dry run test",
        behaviors_cited=["behavior-1"],
        metadata={},
    )
    action = action_service_postgres.create_action(request, TEST_ACTOR)

    # Dry run replay
    replay_request = ReplayRequest(
        action_ids=[action.action_id],
        strategy="SEQUENTIAL",
        options=ReplayOptions(skip_existing=False, dry_run=True),
    )
    status = action_service_postgres.replay_actions(replay_request, TEST_ACTOR)

    assert status.replay_id is not None
    assert status.progress == 0.0  # Dry run doesn't progress

    # Action should remain NOT_STARTED
    action = action_service_postgres.get_action(action.action_id)
    assert action.replay_status == "NOT_STARTED"


def test_get_replay_status_postgres(action_service_postgres: PostgresActionService) -> None:
    """Test retrieving replay status from PostgreSQL."""
    # Create action and replay
    request = ActionCreateRequest(
        artifact_path="/tmp/status_test.py",
        summary="Status test",
        behaviors_cited=["behavior-1"],
        metadata={},
    )
    action = action_service_postgres.create_action(request, TEST_ACTOR)

    replay_request = ReplayRequest(
        action_ids=[action.action_id],
        strategy="SEQUENTIAL",
        options=ReplayOptions(skip_existing=False, dry_run=False),
    )
    original_status = action_service_postgres.replay_actions(replay_request, TEST_ACTOR)

    # Retrieve status
    retrieved_status = action_service_postgres.get_replay_status(original_status.replay_id)

    assert retrieved_status.replay_id == original_status.replay_id
    assert retrieved_status.status == "SUCCEEDED"
    assert retrieved_status.progress == 1.0


def test_get_replay_status_memory(action_service_memory: ActionService) -> None:
    """Test retrieving replay status from in-memory backend."""
    # Create action and replay
    request = ActionCreateRequest(
        artifact_path="/tmp/status_test.py",
        summary="Status test",
        behaviors_cited=["behavior-1"],
        metadata={},
    )
    action = action_service_memory.create_action(request, TEST_ACTOR)

    replay_request = ReplayRequest(
        action_ids=[action.action_id],
        strategy="SEQUENTIAL",
        options=ReplayOptions(skip_existing=False, dry_run=False),
    )
    original_status = action_service_memory.replay_actions(replay_request, TEST_ACTOR)

    # Retrieve status
    retrieved_status = action_service_memory.get_replay_status(original_status.replay_id)

    assert retrieved_status.replay_id == original_status.replay_id
    assert retrieved_status.status == "SUCCEEDED"


def test_get_replay_status_not_found_postgres(action_service_postgres: PostgresActionService) -> None:
    """Test ReplayNotFoundError when replay doesn't exist in PostgreSQL."""
    with pytest.raises(PostgresReplayNotFoundError, match="not found"):
        action_service_postgres.get_replay_status(NONEXISTENT_REPLAY_ID)


def test_get_replay_status_not_found_memory(action_service_memory: ActionService) -> None:
    """Test ReplayNotFoundError when replay doesn't exist in memory."""
    with pytest.raises(MemoryReplayNotFoundError, match="not found"):
        action_service_memory.get_replay_status(NONEXISTENT_REPLAY_ID)


def test_replay_missing_actions_postgres(action_service_postgres: PostgresActionService) -> None:
    """Test replaying non-existent actions raises ActionNotFoundError in PostgreSQL."""
    replay_request = ReplayRequest(
        action_ids=[NONEXISTENT_ACTION_ID],
        strategy="SEQUENTIAL",
        options=ReplayOptions(skip_existing=False, dry_run=False),
    )

    with pytest.raises(PostgresActionNotFoundError, match="Cannot replay missing actions"):
        action_service_postgres.replay_actions(replay_request, TEST_ACTOR)


def test_replay_missing_actions_memory(action_service_memory: ActionService) -> None:
    """Test replaying non-existent actions raises ActionNotFoundError in memory."""
    replay_request = ReplayRequest(
        action_ids=[NONEXISTENT_ACTION_ID],
        strategy="SEQUENTIAL",
        options=ReplayOptions(skip_existing=False, dry_run=False),
    )

    with pytest.raises(MemoryActionNotFoundError, match="Cannot replay missing actions"):
        action_service_memory.replay_actions(replay_request, TEST_ACTOR)


# ------------------------------------------------------------------
# Data Integrity Tests
# ------------------------------------------------------------------


def test_checksum_generation_postgres(action_service_postgres: PostgresActionService) -> None:
    """Test automatic checksum generation in PostgreSQL."""
    request = ActionCreateRequest(
        artifact_path="/tmp/checksum.py",
        summary="Checksum test",
        behaviors_cited=["behavior-1"],
        metadata={},
        checksum=None,  # Let service generate checksum
    )
    action = action_service_postgres.create_action(request, TEST_ACTOR)

    assert action.checksum != ""
    assert len(action.checksum) == 64  # SHA-256 hex digest length


def test_explicit_checksum_postgres(action_service_postgres: PostgresActionService) -> None:
    """Test providing explicit checksum in PostgreSQL."""
    explicit_checksum = "a" * 64
    request = ActionCreateRequest(
        artifact_path="/tmp/explicit.py",
        summary="Explicit checksum",
        behaviors_cited=["behavior-1"],
        metadata={},
        checksum=explicit_checksum,
    )
    action = action_service_postgres.create_action(request, TEST_ACTOR)

    assert action.checksum == explicit_checksum


def test_related_run_id_postgres(action_service_postgres: PostgresActionService) -> None:
    """Test storing related_run_id in PostgreSQL."""
    run_id = "run-12345"
    request = ActionCreateRequest(
        artifact_path="/tmp/run_test.py",
        summary="Run linkage test",
        behaviors_cited=["behavior-1"],
        metadata={},
        related_run_id=run_id,
    )
    action = action_service_postgres.create_action(request, TEST_ACTOR)

    assert action.related_run_id == run_id

    # Verify retrieval
    retrieved = action_service_postgres.get_action(action.action_id)
    assert retrieved.related_run_id == run_id


def test_audit_log_event_id_postgres(action_service_postgres: PostgresActionService) -> None:
    """Test storing audit_log_event_id in PostgreSQL."""
    audit_id = "audit-67890"
    request = ActionCreateRequest(
        artifact_path="/tmp/audit_test.py",
        summary="Audit linkage test",
        behaviors_cited=["behavior-1"],
        metadata={},
        audit_log_event_id=audit_id,
    )
    action = action_service_postgres.create_action(request, TEST_ACTOR)

    assert action.audit_log_event_id == audit_id

    # Verify retrieval
    retrieved = action_service_postgres.get_action(action.action_id)
    assert retrieved.audit_log_event_id == audit_id
