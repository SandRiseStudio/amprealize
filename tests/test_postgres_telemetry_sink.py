import sys
import types
from contextlib import contextmanager

import pytest

from amprealize.telemetry import (
    FileTelemetrySink,
    TelemetryClient,
    TelemetryEvent,
    create_sink_from_env,
)
from amprealize.storage.postgres_telemetry import PostgresTelemetrySink


class MockCursor:
    def __init__(self, connection):
        self._connection = connection
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        normalised = " ".join(sql.split())
        self._connection.executed.append((normalised, params))

    def close(self):
        self.closed = True


class MockConnection:
    def __init__(self):
        self.closed = 0
        self.autocommit = False
        self.executed = []

    def cursor(self):
        return MockCursor(self)

    def close(self):
        self.closed = 1


@pytest.fixture
def fake_psycopg2(monkeypatch):
    connection = MockConnection()

    psycopg2_module = types.ModuleType("psycopg2")
    setattr(psycopg2_module, "paramstyle", "pyformat")
    setattr(psycopg2_module, "Error", Exception)

    def connect(*args, **kwargs):
        return connection

    setattr(psycopg2_module, "connect", connect)

    extras_module = types.ModuleType("psycopg2.extras")
    setattr(extras_module, "Json", lambda payload: payload)

    monkeypatch.setitem(sys.modules, "psycopg2", psycopg2_module)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", extras_module)

    class FakePool:
        def __init__(self, dsn, service_name=None):
            self.dsn = dsn
            self.service_name = service_name

        @contextmanager
        def connection(self, autocommit=True):
            connection.autocommit = autocommit
            yield connection

    monkeypatch.setattr("amprealize.storage.postgres_pool.PostgresPool", FakePool)

    return connection


def _make_event(event_type, payload=None, **kwargs):
    return TelemetryEvent(
        event_id="00000000-0000-0000-0000-000000000000",
        timestamp="2025-01-01T00:00:00Z",
        event_type=event_type,
        actor={"id": "actor", "role": "STRATEGIST", "surface": "cli"},
        run_id=kwargs.get("run_id"),
        action_id=kwargs.get("action_id"),
        session_id=kwargs.get("session_id"),
        payload=payload or {},
    )


def test_plan_created_projects_behavior_usage(fake_psycopg2):
    sink = PostgresTelemetrySink("postgresql://localhost/test")

    event = _make_event(
        "plan_created",
        payload={
            "behavior_ids": ["beh-1", "beh-2"],
            "baseline_tokens": 120,
            "template_id": "tmp-9",
            "template_name": "Launch Checklist",
        },
        run_id="run-abc",
        session_id="session-123",
    )

    sink.write(event)

    sql_statements = [sql for sql, _ in fake_psycopg2.executed]
    params = [params for _, params in fake_psycopg2.executed]

    assert any("INSERT INTO telemetry_events" in sql for sql in sql_statements)
    assert any("INSERT INTO fact_behavior_usage" in sql for sql in sql_statements)

    behavior_insert_params = next(
        p for sql, p in fake_psycopg2.executed if "fact_behavior_usage" in sql
    )
    # run_id, template_id, template_name, behavior_ids, behavior_count, has_behaviors, baseline_tokens, actor_surface, actor_role, first_plan_timestamp
    assert behavior_insert_params[0] == "run-abc"
    assert behavior_insert_params[1] == "tmp-9"
    assert behavior_insert_params[3] == ["beh-1", "beh-2"]
    assert behavior_insert_params[4] == 2
    assert behavior_insert_params[5] is True
    assert behavior_insert_params[6] == 120


def test_execution_update_projects_token_and_status(fake_psycopg2):
    sink = PostgresTelemetrySink("postgresql://localhost/test")

    event = _make_event(
        "execution_update",
        payload={
            "template_id": "tmp-1",
            "output_tokens": 50,
            "baseline_tokens": 100,
            "token_savings_pct": 0.5,
            "status": "COMPLETED",
        },
        run_id="run-xyz",
    )

    sink.write(event)

    sql_statements = [sql for sql, _ in fake_psycopg2.executed]

    assert any("INSERT INTO fact_token_savings" in sql for sql in sql_statements)
    assert any("INSERT INTO fact_execution_status" in sql for sql in sql_statements)

    token_params = next(
        p for sql, p in fake_psycopg2.executed if "fact_token_savings" in sql
    )
    assert token_params[0] == "run-xyz"
    assert token_params[2] == 50
    assert token_params[3] == 100
    assert token_params[4] == pytest.approx(0.5)

    status_params = next(
        p for sql, p in fake_psycopg2.executed if "fact_execution_status" in sql
    )
    assert status_params[0] == "run-xyz"
    assert status_params[2] == "COMPLETED"


def test_compliance_event_projects_fact(fake_psycopg2):
    sink = PostgresTelemetrySink("postgresql://localhost/test")

    event = _make_event(
        "compliance_step_recorded",
        payload={
            "checklist_id": "check-1",
            "step_id": "step-a",
            "status": "COMPLETE",
            "coverage_score": 0.9,
            "behavior_ids": ["beh-1"],
        },
        run_id="run-123",
        session_id="sess-1",
    )

    sink.write(event)

    sql_statements = [sql for sql, _ in fake_psycopg2.executed]
    assert any("INSERT INTO fact_compliance_steps" in sql for sql in sql_statements)

    params = next(
        p for sql, p in fake_psycopg2.executed if "fact_compliance_steps" in sql
    )
    assert params[0] == "check-1"
    assert params[1] == "step-a"
    assert params[2] == "COMPLETE"
    assert params[3] == pytest.approx(0.9)
    assert params[4] == "run-123"
    assert params[6] == ["beh-1"]


def test_refresh_metric_views_executes_function(fake_psycopg2):
    sink = PostgresTelemetrySink("postgresql://localhost/test")
    sink.refresh_metric_views()

    assert any(
        sql == "SELECT refresh_prd_metric_views();" for sql, _ in fake_psycopg2.executed
    )


def test_create_sink_from_env_prefers_postgres(monkeypatch, fake_psycopg2, tmp_path):
    monkeypatch.setenv("AMPREALIZE_TELEMETRY_PG_DSN", "postgresql://localhost/test")

    sink = create_sink_from_env(default_path=tmp_path / "events.jsonl")
    assert isinstance(sink, PostgresTelemetrySink)


def test_create_sink_from_env_falls_back_to_file(monkeypatch, tmp_path):
    path = tmp_path / "telemetry.jsonl"
    monkeypatch.setenv("AMPREALIZE_TELEMETRY_PATH", str(path))
    monkeypatch.delenv("AMPREALIZE_TELEMETRY_PG_DSN", raising=False)

    sink = create_sink_from_env()
    assert isinstance(sink, FileTelemetrySink)
    assert path.parent.exists()

    telemetry = TelemetryClient(sink=sink)
    telemetry.emit_event(event_type="ping", payload={})
    assert path.read_text().strip() != ""
