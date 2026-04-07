import json
from pathlib import Path
from typing import Any

import pytest

from amprealize import cli


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def reset_cli_state() -> None:
    cli._reset_action_state_for_testing()


def _run_cli(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    exit_code = cli.main(args)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def test_telemetry_emit_file_sink_custom_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    events_path = tmp_path / "custom-events.jsonl"

    exit_code, out, err = _run_cli(
        [
            "telemetry",
            "emit",
            "--event-type",
            "test_event",
            "--payload",
            "{\"foo\": \"bar\"}",
            "--sink",
            "file",
            "--telemetry-path",
            str(events_path),
        ],
        capsys,
    )

    assert exit_code == 0
    assert err == ""
    payload = json.loads(out)
    assert payload["event_type"] == "test_event"
    assert events_path.exists()

    written_lines = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert written_lines[0]["event_type"] == "test_event"
    assert written_lines[0]["payload"] == {"foo": "bar"}


def test_telemetry_emit_kafka_requires_servers(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)
    monkeypatch.delenv("KAFKA_TOPIC_TELEMETRY_EVENTS", raising=False)

    exit_code, out, err = _run_cli(
        [
            "telemetry",
            "emit",
            "--event-type",
            "kafka_missing",
            "--sink",
            "kafka",
        ],
        capsys,
    )

    assert exit_code == 2
    assert out == ""
    assert "requires --kafka-servers" in err


def test_telemetry_emit_kafka_uses_env_defaults(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    recorded: dict[str, Any] = {}

    class DummyKafkaSink:
        def __init__(self, bootstrap_servers: str, topic: str = "telemetry.events", **kwargs: Any) -> None:
            recorded["bootstrap"] = bootstrap_servers
            recorded["topic"] = topic

        def write(self, event: Any) -> None:
            recorded["event_type"] = event.event_type
            recorded["payload"] = event.payload

    monkeypatch.setattr(cli, "KafkaTelemetrySink", DummyKafkaSink)
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")
    monkeypatch.setenv("KAFKA_TOPIC_TELEMETRY_EVENTS", "custom.telemetry.events")

    exit_code, out, err = _run_cli(
        [
            "telemetry",
            "emit",
            "--event-type",
            "kafka_env",
            "--payload",
            "{\"status\": \"SUCCESS\"}",
            "--sink",
            "kafka",
        ],
        capsys,
    )

    assert exit_code == 0
    assert err == ""
    assert recorded["bootstrap"] == "localhost:19092"
    assert recorded["topic"] == "custom.telemetry.events"
    assert recorded["event_type"] == "kafka_env"
    assert recorded["payload"] == {"status": "SUCCESS"}
