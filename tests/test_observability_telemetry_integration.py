"""PostgreSQL telemetry warehouse integration tests (GUIDEAI-1238).

Requires:

- ``pytest --run-integration``
- Reachable telemetry DB: ``AMPREALIZE_TELEMETRY_PG_DSN`` **or**
  ``AMPREALIZE_PG_HOST_TELEMETRY`` / ``PORT`` / ``USER`` / ``PASS`` / ``DB_*``
- Schema applied (warehouse migration + ``migrations_telemetry`` through observability views).

Follows ``behavior_design_test_strategy`` (Student): opt-in gate + safety guard on DSN.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

import pytest

pytest.importorskip("psycopg2")

from amprealize.storage.postgres_telemetry import PostgresTelemetryWarehouse
from amprealize.telemetry import TelemetryEvent

pytestmark = [
    pytest.mark.telemetry_pg_only,
    pytest.mark.integration,
    pytest.mark.postgres,
]


def _skip_unless_run_integration(request: pytest.FixtureRequest) -> None:
    if not request.config.getoption("--run-integration"):
        pytest.skip("Integration tests require pytest --run-integration")


def _telemetry_dsn_or_skip() -> str:
    from tests.conftest import assert_test_database, get_postgres_dsn

    dsn = os.environ.get("AMPREALIZE_TELEMETRY_PG_DSN") or get_postgres_dsn("TELEMETRY")
    if not dsn:
        pytest.skip(
            "Configure AMPREALIZE_TELEMETRY_PG_DSN or AMPREALIZE_PG_*_TELEMETRY "
            "(see infra/docker-compose.test.yml postgres-telemetry-test, port 6432)",
        )
    assert_test_database(dsn)
    try:
        import psycopg2

        conn = psycopg2.connect(dsn, connect_timeout=5)
        conn.close()
    except Exception as exc:  # pragma: no cover - environment-specific
        pytest.skip(f"Telemetry PostgreSQL unreachable: {exc}")
    return dsn


@pytest.fixture
def telemetry_pg_dsn(request: pytest.FixtureRequest) -> str:
    _skip_unless_run_integration(request)
    return _telemetry_dsn_or_skip()


def _gateway_payload(project_id: str, run_id: str) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "mode": "cloud_git",
        "execution_observability": {
            "run_id": run_id,
            "work_item_id": "WI-int",
            "project_id": project_id,
            "org_id": "org-int",
            "conversation_id": "conv-int",
        },
    }


def _cleanup_telemetry_rows(dsn: str, event_id: str) -> None:
    import psycopg2

    with psycopg2.connect(dsn) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("DELETE FROM observability_records WHERE record_id = %s", (event_id,))
            cur.execute("DELETE FROM telemetry_events WHERE event_id = %s", (event_id,))


def test_write_gateway_event_inserts_observability_record(telemetry_pg_dsn: str) -> None:
    """Live sink path: telemetry_events + observability_records for gateway events."""

    warehouse = PostgresTelemetryWarehouse(telemetry_pg_dsn)
    eid = str(uuid.uuid4())
    ts_str = datetime.now(timezone.utc).isoformat()
    run_id = f"run-int-{uuid.uuid4().hex[:8]}"
    ev = TelemetryEvent(
        event_id=eid,
        timestamp=ts_str,
        event_type="execution.gateway.started",
        actor={"id": "integration-user", "role": "STRATEGIST", "surface": "cli"},
        run_id=run_id,
        action_id=None,
        session_id="conv-int",
        payload=_gateway_payload("proj-int", run_id),
    )

    try:
        warehouse.write_event(ev)
        import psycopg2

        with psycopg2.connect(telemetry_pg_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM telemetry_events WHERE event_id = %s",
                    (eid,),
                )
                assert int(cur.fetchone()[0]) == 1
                cur.execute(
                    "SELECT COUNT(*) FROM observability_records WHERE record_id = %s",
                    (eid,),
                )
                assert int(cur.fetchone()[0]) == 1
    finally:
        _cleanup_telemetry_rows(telemetry_pg_dsn, eid)


def test_replay_restores_observability_after_delete(telemetry_pg_dsn: str) -> None:
    """replay_stored_event_projection repairs missing observability rows (idempotent PK)."""

    warehouse = PostgresTelemetryWarehouse(telemetry_pg_dsn)
    eid = str(uuid.uuid4())
    ts_str = datetime.now(timezone.utc).isoformat()
    run_id = f"run-replay-{uuid.uuid4().hex[:8]}"
    ev = TelemetryEvent(
        event_id=eid,
        timestamp=ts_str,
        event_type="execution.gateway.started",
        actor={"id": "integration-user", "role": "STRATEGIST", "surface": "cli"},
        run_id=run_id,
        action_id=None,
        session_id="conv-int",
        payload=_gateway_payload("proj-replay", run_id),
    )

    try:
        warehouse.write_event(ev)
        import psycopg2

        with psycopg2.connect(telemetry_pg_dsn) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT event_timestamp FROM telemetry_events WHERE event_id = %s",
                    (eid,),
                )
                row = cur.fetchone()
                assert row is not None
                ts_db = row[0]
                cur.execute("DELETE FROM observability_records WHERE record_id = %s", (eid,))

        with psycopg2.connect(telemetry_pg_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM observability_records WHERE record_id = %s",
                    (eid,),
                )
                assert int(cur.fetchone()[0]) == 0

        actor_map = dict(ev.actor)
        warehouse.replay_stored_event_projection(ev, ts_db, actor_map)

        with psycopg2.connect(telemetry_pg_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM observability_records WHERE record_id = %s",
                    (eid,),
                )
                assert int(cur.fetchone()[0]) == 1
    finally:
        _cleanup_telemetry_rows(telemetry_pg_dsn, eid)


def test_batch_replay_dry_run_counts_page(telemetry_pg_dsn: str) -> None:
    """replay_event_projections_from_telemetry_table dry_run respects limit/offset window."""

    warehouse = PostgresTelemetryWarehouse(telemetry_pg_dsn)
    ids: list[str] = []
    try:
        for _ in range(2):
            eid = str(uuid.uuid4())
            ids.append(eid)
            ts_str = datetime.now(timezone.utc).isoformat()
            run_id = f"run-batch-{uuid.uuid4().hex[:8]}"
            ev = TelemetryEvent(
                event_id=eid,
                timestamp=ts_str,
                event_type="execution.gateway.started",
                actor={"id": "integration-user", "role": "STRATEGIST", "surface": "cli"},
                run_id=run_id,
                action_id=None,
                session_id="conv-int",
                payload=_gateway_payload("proj-batch", run_id),
            )
            warehouse.write_event(ev)

        stats = warehouse.replay_event_projections_from_telemetry_table(
            limit=1,
            offset=0,
            dry_run=True,
        )
        assert stats["dry_run"] == 1
        assert stats["matched"] == 1
        assert stats["processed"] == 0
    finally:
        for eid in ids:
            _cleanup_telemetry_rows(telemetry_pg_dsn, eid)
