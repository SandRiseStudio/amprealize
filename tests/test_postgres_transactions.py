"""Transaction management regression tests for PostgresActionService."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Generator

import pytest

from amprealize.action_contracts import ActionCreateRequest, Actor
from amprealize.action_service_postgres import PostgresActionService

try:  # pragma: no cover - psycopg2 optional in lint environments
    import psycopg2  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - handled via pytest skip
    psycopg2 = None  # type: ignore[assignment]


TEST_ACTOR = Actor(id="txn-user", role="ENGINEER", surface="cli")


def _truncate_action_tables(dsn: str) -> None:
    from conftest import safe_truncate
    safe_truncate(dsn, ["replays", "actions"])


@pytest.fixture
def postgres_dsn() -> Generator[str, None, None]:
    dsn = os.environ.get("AMPREALIZE_ACTION_PG_DSN")
    if not dsn:
        pytest.skip("AMPREALIZE_ACTION_PG_DSN not set; skipping PostgreSQL transaction tests")
    yield dsn


@pytest.fixture
def action_service_postgres(postgres_dsn: str) -> Generator[PostgresActionService, None, None]:
    _truncate_action_tables(postgres_dsn)
    service = PostgresActionService(dsn=postgres_dsn)
    try:
        yield service
    finally:
        _truncate_action_tables(postgres_dsn)


def test_transaction_retries_deadlock(
    action_service_postgres: PostgresActionService, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeDeadlock(Exception):
        pgcode = "40P01"

    service = action_service_postgres
    call_counter = {"count": 0}

    original_connection = service._connection

    def flaky_connection(*, autocommit: bool = True):
        call_counter["count"] += 1
        if call_counter["count"] == 1:
            raise FakeDeadlock("deadlock detected")
        return original_connection(autocommit=autocommit)

    monkeypatch.setattr("amprealize.action_service_postgres.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(service, "_connection", flaky_connection, raising=False)

    request = ActionCreateRequest(
        artifact_path="/tmp/deadlock.py",
        summary="Deadlock retry",
        behaviors_cited=["behavior_unify_execution_records"],
        metadata={"source": "pytest"},
    )

    action = service.create_action(request, TEST_ACTOR)

    assert action.action_id
    assert call_counter["count"] == 2


def test_transaction_failure_rolls_back(action_service_postgres: PostgresActionService) -> None:
    class Boom(Exception):
        pass

    artifact_path = "/tmp/rollback_tx.py"

    def failing_executor(conn: Any) -> None:
        from psycopg2.extras import Json

        with conn.cursor() as cur:  # type: ignore[misc]
            cur.execute(
                """
                INSERT INTO actions (
                    action_id, timestamp, actor_id, actor_role, actor_surface,
                    artifact_path, summary, behaviors_cited, metadata,
                    related_run_id, audit_log_event_id, checksum, replay_status
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s
                );
                """,
                (
                    str(uuid.uuid4()),
                    datetime.now(timezone.utc),
                    "rollback-user",
                    "ENGINEER",
                    "cli",
                    artifact_path,
                    "Rollback test",
                    Json([]),
                    Json({}),
                    None,
                    None,
                    f"checksum-{uuid.uuid4()}",
                    "NOT_STARTED",
                ),
            )
            raise Boom("explode before commit")

    with pytest.raises(Boom):
        action_service_postgres._run_transaction(  # type: ignore[attr-defined]
            "transaction.test",
            actor=None,
            metadata={"test": True},
            executor=failing_executor,
        )

    with action_service_postgres._connection() as conn:  # type: ignore[attr-defined]
        with conn.cursor() as cur:  # type: ignore[misc]
            cur.execute(
                "SELECT COUNT(*) FROM actions WHERE artifact_path = %s;",
                (artifact_path,),
            )
            remaining = cur.fetchone()[0]

    assert remaining == 0
