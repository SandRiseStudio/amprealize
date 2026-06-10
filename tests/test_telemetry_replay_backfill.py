"""Unit tests for replaying observability projections from ``telemetry_events`` stores."""

from __future__ import annotations

import json
import sys
import types
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

import pytest

from amprealize.storage.postgres_telemetry import (
    PostgresTelemetryWarehouse,
    telemetry_event_from_telemetry_events_row,
)
from amprealize.telemetry import TelemetryEvent

pytestmark = pytest.mark.unit


def test_telemetry_event_from_row_round_trip() -> None:
    payload = {"run_id": "r1", "execution_observability": {"project_id": "p1"}}
    row: Tuple[Any, ...] = (
        "550e8400-e29b-41d4-a716-446655440000",
        datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
        "execution.gateway.started",
        "u1",
        "STRATEGIST",
        "web",
        "r1",
        "act-1",
        "sess-1",
        json.dumps(payload),
    )
    event, ts, actor = telemetry_event_from_telemetry_events_row(row)
    assert event.event_type == "execution.gateway.started"
    assert event.run_id == "r1"
    assert event.payload.get("run_id") == "r1"
    assert actor["surface"] == "web"
    assert ts.year == 2025


def test_telemetry_event_from_row_accepts_dict_payload() -> None:
    row = (
        UUID("550e8400-e29b-41d4-a716-446655440000"),
        datetime(2025, 1, 1, tzinfo=timezone.utc),
        "execution.worker.completed",
        None,
        None,
        None,
        "run-x",
        None,
        None,
        {"execution_observability": {"trace_id": "t1"}},
    )
    event, _ts, _actor = telemetry_event_from_telemetry_events_row(row)
    assert event.event_id == "550e8400-e29b-41d4-a716-446655440000"
    assert event.payload["execution_observability"]["trace_id"] == "t1"


class ReplayMockCursor:
    def __init__(self, connection: "ReplayMockConnection") -> None:
        self._conn = connection
        self.closed = False

    def __enter__(self) -> "ReplayMockCursor":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def execute(self, sql: str, params: Optional[Sequence[Any]] = None) -> None:
        normalised = " ".join(sql.split())
        self._conn.executed.append((normalised, list(params) if params else []))
        self._conn.last_sql = normalised
        self._conn.last_params = list(params) if params else []

    def fetchall(self) -> List[Tuple[Any, ...]]:
        return list(self._conn.fetchall_queue.pop(0)) if self._conn.fetchall_queue else []

    def fetchone(self) -> Optional[Tuple[Any, ...]]:
        if self._conn.fetchone_queue:
            return self._conn.fetchone_queue.pop(0)
        return None

    def close(self) -> None:
        self.closed = True


class ReplayMockConnection:
    def __init__(self) -> None:
        self.autocommit = False
        self.executed: List[Tuple[str, List[Any]]] = []
        self.last_sql = ""
        self.last_params: List[Any] = []
        self.fetchall_queue: List[List[Tuple[Any, ...]]] = []
        self.fetchone_queue: List[Tuple[Any, ...]] = []

    def cursor(self) -> ReplayMockCursor:
        return ReplayMockCursor(self)

    def close(self) -> None:
        return None


@pytest.fixture
def replay_pool_mock(monkeypatch: pytest.MonkeyPatch) -> ReplayMockConnection:
    connection = ReplayMockConnection()
    one_row: Tuple[Any, ...] = (
        "00000000-0000-0000-0000-000000000099",
        datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        "execution.gateway.started",
        "actor",
        "STRATEGIST",
        "cli",
        "run-rp",
        None,
        None,
        json.dumps(
            {
                "run_id": "run-rp",
                "execution_observability": {
                    "project_id": "proj-1",
                    "work_item_id": "wi-1",
                },
            },
        ),
    )
    connection.fetchall_queue.append([one_row])

    class FakePool:
        def __init__(self, dsn: str, service_name: str | None = None) -> None:
            self.dsn = dsn

        @contextmanager
        def connection(self, autocommit: bool = True) -> Any:
            connection.autocommit = autocommit
            yield connection

    monkeypatch.setattr("amprealize.storage.postgres_pool.PostgresPool", FakePool)
    _install_minimal_psycopg2(monkeypatch)
    return connection


def _install_minimal_psycopg2(monkeypatch: pytest.MonkeyPatch) -> None:
    psycopg2_module = types.ModuleType("psycopg2")
    setattr(psycopg2_module, "paramstyle", "pyformat")
    setattr(psycopg2_module, "Error", Exception)
    extras_module = types.ModuleType("psycopg2.extras")
    setattr(extras_module, "Json", lambda payload: payload)
    monkeypatch.setitem(sys.modules, "psycopg2", psycopg2_module)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", extras_module)


def test_replay_event_projections_from_telemetry_table_runs_project(
    replay_pool_mock: ReplayMockConnection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warehouse = PostgresTelemetryWarehouse("postgresql://localhost/telemetry")
    stats = warehouse.replay_event_projections_from_telemetry_table(
        limit=10,
        offset=0,
        dry_run=False,
    )
    assert stats["matched"] == 1
    assert stats["processed"] == 1
    assert stats["dry_run"] == 0
    assert any("INSERT INTO observability_records" in s for s, _ in replay_pool_mock.executed)


def test_replay_event_projections_dry_run_uses_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = ReplayMockConnection()
    connection.fetchone_queue.append((2,))

    class FakePool:
        def __init__(self, _dsn: str, service_name: str | None = None) -> None:
            del service_name

        @contextmanager
        def connection(self, autocommit: bool = True) -> Any:
            yield connection

    monkeypatch.setattr("amprealize.storage.postgres_pool.PostgresPool", FakePool)
    _install_minimal_psycopg2(monkeypatch)

    warehouse = PostgresTelemetryWarehouse("postgresql://localhost/telemetry")
    stats = warehouse.replay_event_projections_from_telemetry_table(
        limit=5,
        offset=0,
        dry_run=True,
    )
    assert stats == {"matched": 2, "processed": 0, "dry_run": 1}


def test_replay_stored_event_projection_skips_telemetry_insert(
    replay_pool_mock: ReplayMockConnection,
) -> None:
    warehouse = PostgresTelemetryWarehouse("postgresql://localhost/telemetry")
    event = TelemetryEvent(
        event_id="00000000-0000-0000-0000-000000000001",
        timestamp="2025-01-01T00:00:00+00:00",
        event_type="execution.gateway.started",
        actor={"id": "a", "role": "R", "surface": "cli"},
        run_id="r1",
        action_id=None,
        session_id=None,
        payload={"run_id": "r1", "execution_observability": {"project_id": "p1"}},
    )
    ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    warehouse.replay_stored_event_projection(
        event,
        ts,
        {"id": "a", "role": "R", "surface": "cli"},
    )
    sqls = [s for s, _ in replay_pool_mock.executed]
    assert not any("INSERT INTO telemetry_events" in s for s in sqls)
    assert any("INSERT INTO observability_records" in s for s in sqls)
