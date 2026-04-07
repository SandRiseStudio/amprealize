import json
from pathlib import Path

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


def test_agents_assign_and_status(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code, out, err = _run_cli(
        [
            "agents",
            "assign",
            "--run-id",
            "run-123",
            "--stage",
            "PLANNING",
            "--context",
            '{"task_type": "compliance", "severity": "HIGH"}',
            "--format",
            "json",
        ],
        capsys,
    )
    assert exit_code == 0
    assert err == ""
    assignment = json.loads(out)

    assert assignment["run_id"] == "run-123"
    assert assignment["stage"] == "PLANNING"
    assert assignment["active_agent"]["agent_id"] == "compliance"
    assert assignment["heuristics_applied"]["selected_agent_id"] == "compliance"

    exit_code, out, err = _run_cli(
        [
            "agents",
            "status",
            "--run-id",
            "run-123",
            "--format",
            "json",
        ],
        capsys,
    )
    assert exit_code == 0
    assert err == ""
    status_payload = json.loads(out)
    assert status_payload["assignment_id"] == assignment["assignment_id"]
    assert status_payload["active_agent"]["agent_id"] == "compliance"


def test_agents_switch_updates_history(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code, out, err = _run_cli(
        [
            "agents",
            "assign",
            "--run-id",
            "run-456",
            "--agent-id",
            "engineering",
            "--format",
            "json",
        ],
        capsys,
    )
    assert exit_code == 0
    assert err == ""
    assignment = json.loads(out)
    assignment_id = assignment["assignment_id"]

    exit_code, out, err = _run_cli(
        [
            "agents",
            "switch",
            assignment_id,
            "--target-agent-id",
            "product",
            "--reason",
            "handoff to product",
            "--stage",
            "REVIEW",
            "--format",
            "json",
        ],
        capsys,
    )
    assert exit_code == 0
    assert err == ""
    switched = json.loads(out)
    assert switched["assignment_id"] == assignment_id
    assert switched["active_agent"]["agent_id"] == "product"
    assert switched["stage"] == "REVIEW"

    history = switched["history"]
    assert len(history) == 1
    event = history[0]
    assert event["from_agent_id"] == "engineering"
    assert event["to_agent_id"] == "product"
    assert event["trigger_details"]["reason"] == "handoff to product"


def test_agents_assign_context_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    context_path = tmp_path / "context.json"
    context_path.write_text(json.dumps({"task_type": "security", "severity": "MEDIUM"}), encoding="utf-8")

    exit_code, out, err = _run_cli(
        [
            "agents",
            "assign",
            "--context-file",
            str(context_path),
            "--format",
            "json",
        ],
        capsys,
    )
    assert exit_code == 0
    assert err == ""
    assignment = json.loads(out)
    assert assignment["active_agent"]["agent_id"] == "security"
    assert assignment["metadata"]["task_type"] == "security"


def test_agents_status_requires_identifier(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code, out, err = _run_cli([
        "agents",
        "status",
    ], capsys)
    assert exit_code == 2
    assert out == ""
    assert "Provide --assignment-id or --run-id" in err
