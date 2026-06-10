"""Tests for optional OTLP / async export (GUIDEAI-1195)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, List

import pytest

pytestmark = pytest.mark.unit

from amprealize.observability_export_config import (
    ObservabilityExportConfig,
    normalize_otlp_grpc_endpoint,
    parse_otlp_headers_raw,
    parse_otlp_protocol,
)
from amprealize.observability_export_runtime import (
    get_or_create_export_runtime,
    reset_export_runtime_for_tests,
    telemetry_event_span_attributes,
)
from amprealize.telemetry import (
    InMemoryTelemetrySink,
    ObservabilityExportForwardingSink,
    TelemetryEvent,
    create_sink_from_env,
)


def _sample_event(**kwargs: Any) -> TelemetryEvent:
    payload = kwargs.pop("payload", {})
    return TelemetryEvent(
        event_id=kwargs.get("event_id", "e1"),
        timestamp=kwargs.get("timestamp", "2026-05-05T12:00:00+00:00"),
        event_type=kwargs.get("event_type", "test.event"),
        actor=kwargs.get("actor", {"id": "a1", "role": "Student", "surface": "api"}),
        run_id=kwargs.get("run_id"),
        action_id=kwargs.get("action_id"),
        session_id=kwargs.get("session_id"),
        payload=payload,
    )


@pytest.fixture(autouse=True)
def _reset_export_singleton() -> Any:
    reset_export_runtime_for_tests()
    yield
    reset_export_runtime_for_tests()


def test_parse_otlp_protocol() -> None:
    assert parse_otlp_protocol(None) == "http"
    assert parse_otlp_protocol("") == "http"
    assert parse_otlp_protocol("grpc") == "grpc"
    assert parse_otlp_protocol("GRPC") == "grpc"
    assert parse_otlp_protocol("http") == "http"
    assert parse_otlp_protocol("garbage") == "http"


def test_normalize_otlp_grpc_endpoint() -> None:
    assert normalize_otlp_grpc_endpoint("") == ""
    assert normalize_otlp_grpc_endpoint("localhost:4317") == "localhost:4317"
    assert normalize_otlp_grpc_endpoint("http://127.0.0.1:4317") == "127.0.0.1:4317"
    assert normalize_otlp_grpc_endpoint("grpc://collector.internal/path") == "collector.internal:4317"


def test_config_from_env_otlp_grpc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMPREALIZE_OTLP_PROTOCOL", "grpc")
    monkeypatch.setenv("AMPREALIZE_OTLP_ENDPOINT", "http://localhost:4317")
    monkeypatch.setenv("AMPREALIZE_OTLP_GRPC_INSECURE", "true")
    cfg = ObservabilityExportConfig.from_env()
    assert cfg.otlp_protocol == "grpc"
    assert cfg.otlp_grpc_insecure is True
    assert normalize_otlp_grpc_endpoint(cfg.otlp_endpoint) == "localhost:4317"


def test_parse_otlp_headers_json_and_kv() -> None:
    assert parse_otlp_headers_raw('{"Authorization":"Bearer x"}') == {"Authorization": "Bearer x"}
    assert parse_otlp_headers_raw("a=b, c=d") == {"a": "b", "c": "d"}


def test_telemetry_event_span_attributes_truncates_payload() -> None:
    big = "x" * 5000
    ev = _sample_event(payload={"huge": big, "execution_observability": {"trace_id": "abc"}})
    attrs = telemetry_event_span_attributes(ev)
    assert len(attrs["amprealize.payload.json"]) <= 4000
    assert attrs["amprealize.execution_observability.trace_id"] == "abc"


def test_telemetry_event_span_attributes_max_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("amprealize.observability_export_runtime._MAX_ATTRIBUTES", 4)
    ev = _sample_event(payload={"x": 1})
    attrs = telemetry_event_span_attributes(ev)
    assert attrs.get("amprealize.export.truncated_attributes") == "true"
    assert len(attrs) <= 5


def test_forwarding_sink_write_and_shutdown() -> None:
    inner = InMemoryTelemetrySink()
    enqueued: List[TelemetryEvent] = []

    class _FakeRt:
        def enqueue(self, e: TelemetryEvent) -> None:
            enqueued.append(e)

        def shutdown(self, timeout: float = 5.0) -> None:
            pass

    sink = ObservabilityExportForwardingSink(inner, _FakeRt())
    ev = _sample_event()
    sink.write(ev)
    assert len(inner.events) == 1
    assert len(enqueued) == 1
    sink.close()


def test_get_or_create_export_runtime_disabled() -> None:
    cfg = ObservabilityExportConfig(
        enabled=False,
        otlp_endpoint=None,
        otlp_headers={},
        otlp_service_name="amprealize",
        otlp_protocol="http",
        otlp_grpc_insecure=True,
        batch_max_events=10,
        flush_interval_sec=1.0,
        datadog_logs_intake_url=None,
        datadog_api_key=None,
        langfuse_host=None,
        langfuse_public_key=None,
        langfuse_secret_key=None,
    )
    assert get_or_create_export_runtime(cfg) is None


def test_export_runtime_dispatches_without_otlp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMPREALIZE_EXPORT_ENABLED", "true")
    monkeypatch.delenv("AMPREALIZE_OTLP_ENDPOINT", raising=False)
    monkeypatch.setenv("AMPREALIZE_EXPORT_FLUSH_INTERVAL_SEC", "0.05")
    cfg = ObservabilityExportConfig.from_env()
    rt = get_or_create_export_runtime(cfg)
    assert rt is not None
    rt.enqueue(_sample_event())
    time.sleep(0.2)
    assert rt.stats()["export_dispatched"] >= 1


def test_create_sink_from_env_wraps_when_export_enabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AMPREALIZE_TELEMETRY_ENABLED", "true")
    monkeypatch.delenv("AMPREALIZE_TELEMETRY_PG_DSN", raising=False)
    monkeypatch.setenv("AMPREALIZE_TELEMETRY_PATH", str(tmp_path / "events.jsonl"))
    monkeypatch.setenv("AMPREALIZE_EXPORT_ENABLED", "true")
    monkeypatch.delenv("AMPREALIZE_OTLP_ENDPOINT", raising=False)

    sink = create_sink_from_env()
    assert isinstance(sink, ObservabilityExportForwardingSink)
    ev = _sample_event()
    sink.write(ev)
    p = tmp_path / "events.jsonl"
    assert p.exists()
    assert p.read_text(encoding="utf-8").strip()
    sink.close()


def test_create_sink_from_env_no_wrap_when_export_off(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AMPREALIZE_TELEMETRY_ENABLED", "true")
    monkeypatch.delenv("AMPREALIZE_TELEMETRY_PG_DSN", raising=False)
    monkeypatch.setenv("AMPREALIZE_TELEMETRY_PATH", str(tmp_path / "events.jsonl"))
    monkeypatch.setenv("AMPREALIZE_EXPORT_ENABLED", "false")

    sink = create_sink_from_env()
    assert not isinstance(sink, ObservabilityExportForwardingSink)
    sink.write(_sample_event())
