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

pytestmark = pytest.mark.unit


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


def test_reflection_candidate_event_projects_observability_record(fake_psycopg2):
    sink = PostgresTelemetrySink("postgresql://localhost/test")

    event = _make_event(
        "reflection.candidate_rejected",
        payload={
            "candidate_id": "cand-42",
            "rejection_reason": "Too vague",
            "reviewer_role": "teacher",
            "source_trace_ids": ["trace-abc"],
            "execution_observability": {
                "run_id": "run-42",
                "cycle_id": "cycle-42",
                "work_item_id": "GUIDEAI-1097",
                "project_id": "proj-42",
                "org_id": "org-42",
                "surface": "board",
            },
        },
        run_id="run-42",
    )

    sink.write(event)

    sql_statements = [sql for sql, _ in fake_psycopg2.executed]
    assert any("INSERT INTO observability_records" in sql for sql in sql_statements)

    params = next(
        p for sql, p in fake_psycopg2.executed if "INSERT INTO observability_records" in sql
    )
    assert params[2] == "behavior_candidate"
    assert params[3] == "reflection.candidate_rejected"
    assert params[4] == "denied"
    assert params[6] == "trace-abc"
    assert params[9] == "org-42"
    assert params[10] == "proj-42"
    assert params[13] == "run-42"
    assert params[15] == "GUIDEAI-1097"
    assert params[22] == "board"
    assert params[30] == "behavior_mining_feature"


def test_execution_gateway_started_projects_observability_record(fake_psycopg2):
    sink = PostgresTelemetrySink("postgresql://localhost/test")

    event = _make_event(
        "execution.gateway.started",
        payload={
            "run_id": "run-gw",
            "mode": "cloud_git",
            "execution_observability": {
                "run_id": "run-gw",
                "work_item_id": "WI-1",
                "project_id": "proj-1",
                "org_id": "org-1",
                "conversation_id": "conv-1",
            },
        },
        run_id="run-gw",
        session_id="conv-1",
    )

    sink.write(event)

    sql_statements = [sql for sql, _ in fake_psycopg2.executed]
    assert any("INSERT INTO observability_records" in sql for sql in sql_statements)

    params = next(
        p for sql, p in fake_psycopg2.executed if "INSERT INTO observability_records" in sql
    )
    assert params[2] == "event"
    assert params[3] == "execution.gateway.started"
    assert params[4] == "started"


def test_llm_generation_completed_projects_observability_and_generation_typed(fake_psycopg2):
    sink = PostgresTelemetrySink("postgresql://localhost/test")

    event = _make_event(
        "llm.generation.completed",
        payload={
            "operation": "astream",
            "status": "completed",
            "provider": "nvidia",
            "model_id": "nvidia-deepseek-v4-flash",
            "latency_ms": 1200,
            "input_tokens": 800,
            "output_tokens": 400,
            "cost_usd": 0.002,
            "execution_observability": {
                "trace_id": "chat:conv-9:user-msg-1",
                "span_id": "gen-span-1",
                "conversation_id": "conv-9",
            },
        },
        run_id=None,
        session_id="conv-9",
    )

    sink.write(event)

    sql_statements = [sql for sql, _ in fake_psycopg2.executed]
    assert any("INSERT INTO observability_records" in sql for sql in sql_statements)
    assert any("INSERT INTO observability_generations" in sql for sql in sql_statements)

    gen_params = next(
        p for sql, p in fake_psycopg2.executed if "INSERT INTO observability_generations" in sql
    )
    assert gen_params[2] == "chat:conv-9:user-msg-1"
    assert gen_params[3] == "gen-span-1"
    assert gen_params[7] == "nvidia-deepseek-v4-flash"
    assert gen_params[8] == 800
    assert gen_params[9] == 400


def test_behaviors_task_context_retrieved_projects_observability_record(fake_psycopg2):
    sink = PostgresTelemetrySink("postgresql://localhost/test")

    event = _make_event(
        "behaviors.task_context_retrieved",
        payload={
            "task_description": "what should I work on",
            "role": "Student",
            "behaviors_found": 0,
            "recommended_count": 0,
            "behavior_names": [],
        },
        session_id="conv-telemetry-1",
    )

    sink.write(event)

    obs = next(
        p for sql, p in fake_psycopg2.executed if "INSERT INTO observability_records" in sql
    )
    assert obs[2] == "event"
    assert obs[3] == "behaviors.task_context_retrieved"
    assert obs[4] == "completed"


def test_execution_llm_completed_projects_observability_and_generation(fake_psycopg2):
    sink = PostgresTelemetrySink("postgresql://localhost/test")

    event = _make_event(
        "execution.llm.completed",
        payload={
            "phase": "planning",
            "model_id": "gpt-4",
            "input_tokens": 10,
            "output_tokens": 20,
            "cost_usd": 0.01,
            "duration_ms": 150,
            "execution_observability": {
                "run_id": "run-llm",
                "work_item_id": "WI-9",
            },
        },
        run_id="run-llm",
    )

    sink.write(event)

    sql_statements = [sql for sql, _ in fake_psycopg2.executed]
    assert any("INSERT INTO observability_records" in sql for sql in sql_statements)
    assert any(
        "INSERT INTO observability_generations" in sql for sql in sql_statements
    )

    obs_params = next(
        p for sql, p in fake_psycopg2.executed if "INSERT INTO observability_records" in sql
    )
    assert obs_params[2] == "generation"
    assert obs_params[3] == "execution.llm.completed"

    gen_params = next(
        p for sql, p in fake_psycopg2.executed if "INSERT INTO observability_generations" in sql
    )
    assert gen_params[4] == "run-llm"
    assert gen_params[7] == "gpt-4"
    assert gen_params[8] == 10
    assert gen_params[9] == 20


def test_execution_worker_started_projects_observability_record(fake_psycopg2):
    sink = PostgresTelemetrySink("postgresql://localhost/test")

    event = _make_event(
        "execution.worker.started",
        payload={
            "execution_observability": {
                "run_id": "run-w",
                "trace_id": "trace-w",
                "span_id": "span-w",
                "work_item_id": "WI-W",
            },
        },
        run_id="run-w",
    )

    sink.write(event)

    params = next(
        p for sql, p in fake_psycopg2.executed if "INSERT INTO observability_records" in sql
    )
    assert params[2] == "event"
    assert params[3] == "execution.worker.started"
    assert params[4] == "started"


def test_execution_phase_completed_projects_observability_record(fake_psycopg2):
    sink = PostgresTelemetrySink("postgresql://localhost/test")

    event = _make_event(
        "execution.phase.completed",
        payload={
            "phase": "planning",
            "status": "completed",
            "execution_observability": {
                "run_id": "run-p",
                "trace_id": "trace-p",
                "span_id": "span-p",
            },
        },
        run_id="run-p",
    )

    sink.write(event)

    params = next(
        p for sql, p in fake_psycopg2.executed if "INSERT INTO observability_records" in sql
    )
    assert params[2] == "event"
    assert params[3] == "execution.phase.completed"
    assert params[4] == "completed"


def test_execution_tool_completed_projects_observability_and_tool_call(fake_psycopg2):
    sink = PostgresTelemetrySink("postgresql://localhost/test")

    event = _make_event(
        "execution.tool.completed",
        payload={
            "tool_name": "list_files",
            "call_id": "call-1",
            "phase": "act",
            "elapsed_ms": 42,
            "inputs": {"path": "/tmp"},
            "output_preview": "ok",
            "execution_observability": {
                "run_id": "run-t",
                "trace_id": "trace-t",
                "span_id": "span-t",
            },
        },
        run_id="run-t",
    )

    sink.write(event)

    sql_statements = [sql for sql, _ in fake_psycopg2.executed]
    assert any("INSERT INTO observability_records" in sql for sql in sql_statements)
    assert any("INSERT INTO observability_tool_calls" in sql for sql in sql_statements)

    obs = next(
        p for sql, p in fake_psycopg2.executed if "INSERT INTO observability_records" in sql
    )
    assert obs[2] == "tool_call"
    assert obs[3] == "execution.tool.completed"
    assert obs[4] == "completed"

    tool_params = next(
        p for sql, p in fake_psycopg2.executed if "INSERT INTO observability_tool_calls" in sql
    )
    assert tool_params[6] == "list_files"
    assert tool_params[7] == "call-1"
    assert tool_params[8] == 42.0


def test_execution_tool_business_outcome_projects_outcome_typed(fake_psycopg2):
    sink = PostgresTelemetrySink("postgresql://localhost/test")

    event = _make_event(
        "execution.tool.business_outcome",
        payload={
            "call_id": "call-2",
            "outcome_type": "work_item_created",
            "outcome_ref": "WI-NEW",
            "resource_type": "work_item",
            "resource_id": "WI-NEW",
            "execution_observability": {"run_id": "run-o", "trace_id": "tr-o", "span_id": "sp-o"},
        },
        run_id="run-o",
    )

    sink.write(event)

    assert any(
        "INSERT INTO observability_outcomes" in sql for sql, _ in fake_psycopg2.executed
    )
    out = next(
        p for sql, p in fake_psycopg2.executed if "INSERT INTO observability_outcomes" in sql
    )
    assert out[6] == "work_item_created"
    assert out[7] == "WI-NEW"
    assert out[8] == "work_item"
    assert out[9] == "WI-NEW"

    obs = next(
        p for sql, p in fake_psycopg2.executed if "INSERT INTO observability_records" in sql
    )
    assert obs[2] == "outcome"
    assert obs[3] == "execution.tool.business_outcome"


def test_llm_generation_failed_projects_generation_typed(fake_psycopg2):
    sink = PostgresTelemetrySink("postgresql://localhost/test")

    event = _make_event(
        "llm.generation.failed",
        payload={
            "model_id": "claude-3",
            "provider": "anthropic",
            "latency_ms": 200,
            "error_class": "RateLimitError",
            "execution_observability": {
                "run_id": "run-g",
                "trace_id": "trace-g",
                "span_id": "span-g",
            },
        },
        run_id="run-g",
    )

    sink.write(event)

    gen = next(
        p for sql, p in fake_psycopg2.executed if "INSERT INTO observability_generations" in sql
    )
    assert gen[6] == "anthropic"
    assert gen[7] == "claude-3"
    assert gen[14] == "failed"
    assert gen[15] == "RateLimitError"


def test_chat_trace_started_projects_trace_kind(fake_psycopg2):
    sink = PostgresTelemetrySink("postgresql://localhost/test")

    event = _make_event(
        "chat.trace.started",
        payload={
            "execution_observability": {"run_id": "run-tr", "trace_id": "tr-root", "span_id": "sp-root"},
        },
        run_id="run-tr",
    )

    sink.write(event)

    obs = next(
        p for sql, p in fake_psycopg2.executed if "INSERT INTO observability_records" in sql
    )
    assert obs[2] == "trace"
    assert obs[3] == "chat.trace.started"


def test_chat_span_completed_projects_span_kind(fake_psycopg2):
    sink = PostgresTelemetrySink("postgresql://localhost/test")

    event = _make_event(
        "chat.span.completed",
        payload={
            "span_name": "fetch",
            "status": "completed",
            "execution_observability": {"run_id": "run-c", "trace_id": "tr-c", "span_id": "sp-c"},
        },
        run_id="run-c",
    )

    sink.write(event)

    obs = next(
        p for sql, p in fake_psycopg2.executed if "INSERT INTO observability_records" in sql
    )
    assert obs[2] == "span"
    assert obs[3] == "chat.span.completed"
    assert obs[4] == "completed"


def test_conversation_reply_generated_projects_event_kind(fake_psycopg2):
    sink = PostgresTelemetrySink("postgresql://localhost/test")

    event = _make_event(
        "conversation_reply.generated",
        payload={
            "execution_observability": {"run_id": "run-rep", "trace_id": "tr-rep", "span_id": "sp-rep"},
        },
        run_id="run-rep",
    )

    sink.write(event)

    obs = next(
        p for sql, p in fake_psycopg2.executed if "INSERT INTO observability_records" in sql
    )
    assert obs[2] == "event"
    assert obs[3] == "conversation_reply.generated"
    assert obs[4] == "completed"


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
