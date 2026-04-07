import json
from pathlib import Path

import pytest

from amprealize import cli


@pytest.fixture(autouse=True)
def reset_cli_state() -> None:
    cli._reset_action_state_for_testing()


def _write_events(path: Path, events: list[dict]) -> None:
    payload = "\n".join(json.dumps(event) for event in events)
    path.write_text(payload + "\n", encoding="utf-8")


def _run_cli(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    exit_code = cli.main(args)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def test_project_kpi_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    events_path = tmp_path / "events.jsonl"
    _write_events(
        events_path,
        [
            {
                "event_id": "evt-1",
                "timestamp": "2025-10-16T00:00:00Z",
                "event_type": "plan_created",
                "actor": {"id": "user-1", "role": "STRATEGIST", "surface": "cli"},
                "payload": {
                    "run_id": "run-1",
                    "template_id": "template-1",
                    "template_name": "Demo Workflow",
                    "behavior_ids": ["behavior-a"],
                    "baseline_tokens": 1000,
                },
            },
            {
                "event_id": "evt-2",
                "timestamp": "2025-10-16T00:01:00Z",
                "event_type": "execution_update",
                "payload": {
                    "run_id": "run-1",
                    "template_id": "template-1",
                    "status": "COMPLETED",
                    "output_tokens": 700,
                    "baseline_tokens": 1000,
                    "token_savings_pct": 0.3,
                    "behaviors_cited": ["behavior-a"],
                },
            },
        ],
    )

    exit_code, out, err = _run_cli(
        ["analytics", "project-kpi", "--input", str(events_path), "--format", "json"],
        capsys,
    )

    assert exit_code == 0
    assert err == ""
    payload = json.loads(out)
    assert payload["summary"]["total_runs"] == 1
    assert payload["summary"]["behavior_reuse_pct"] == 100.0
    assert payload["summary"]["task_completion_rate_pct"] == 100.0
    assert len(payload["fact_behavior_usage"]) == 1


def test_project_kpi_table_output_and_facts_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    events_path = tmp_path / "events.jsonl"
    facts_path = tmp_path / "projection.json"
    _write_events(
        events_path,
        [
            {
                "event_id": "evt-1",
                "timestamp": "2025-10-16T00:00:00Z",
                "event_type": "plan_created",
                "actor": {"id": "user-1", "role": "STRATEGIST", "surface": "cli"},
                "payload": {
                    "run_id": "run-1",
                    "template_id": "template-1",
                    "template_name": "Demo Workflow",
                    "behavior_ids": [],
                    "baseline_tokens": 0,
                },
            }
        ],
    )

    exit_code, out, err = _run_cli(
        [
            "analytics",
            "project-kpi",
            "--input",
            str(events_path),
            "--format",
            "table",
            "--facts-output",
            str(facts_path),
        ],
        capsys,
    )

    assert exit_code == 0
    assert "PRD KPI Summary" in out
    assert "Fact row counts" in out
    assert "Projection JSON written" in err

    facts_payload = json.loads(facts_path.read_text(encoding="utf-8"))
    assert facts_payload["summary"]["total_runs"] == 1
    assert len(facts_payload["fact_behavior_usage"]) == 1


def test_project_kpi_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    events_path = tmp_path / "missing.jsonl"

    exit_code, out, err = _run_cli(
        ["analytics", "project-kpi", "--input", str(events_path)],
        capsys,
    )

    assert exit_code == 2
    assert out == ""
    assert "Telemetry input not found" in err
