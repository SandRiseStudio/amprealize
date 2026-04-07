import json
from pathlib import Path

import pytest

from amprealize import cli


@pytest.fixture(autouse=True)
def reset_cli_state() -> None:
    cli._reset_action_state_for_testing()


def _run_cli(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    exit_code = cli.main(args)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def test_record_action_and_list_actions(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code, out, err = _run_cli(
        [
            "record-action",
            "--artifact",
            "docs/example.md",
            "--summary",
            "Record from CLI",
            "--behavior",
            "behavior_wire_cli_to_orchestrator",
            "--audit-log-event-id",
            "00000000-0000-4000-8000-000000000001",
        ],
        capsys,
    )
    assert exit_code == 0
    assert err == ""
    action_payload = json.loads(out)
    action_id = action_payload["action_id"]
    assert action_payload["audit_log_event_id"] == "00000000-0000-4000-8000-000000000001"

    exit_code, out, err = _run_cli(["list-actions", "--format", "json"], capsys)
    assert exit_code == 0
    assert err == ""
    actions = json.loads(out)
    assert [item["action_id"] for item in actions] == [action_id]
    assert actions[0]["audit_log_event_id"] == "00000000-0000-4000-8000-000000000001"


def test_record_action_merges_metadata(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps({"commands": ["pytest"], "commit": "abc123"}), encoding="utf-8")

    exit_code, out, err = _run_cli(
        [
            "record-action",
            "--artifact",
            "docs/example.md",
            "--summary",
            "Record with metadata",
            "--behavior",
            "behavior_update_docs_after_changes",
            "--metadata",
            "branch=main",
            "--metadata-file",
            str(metadata_path),
        ],
        capsys,
    )

    assert exit_code == 0
    assert err == ""
    payload = json.loads(out)
    assert payload["metadata"]["branch"] == "main"
    assert payload["metadata"]["commit"] == "abc123"
    assert payload["metadata"]["commands"] == ["pytest"]


def test_record_action_without_audit_log_defaults_to_none(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code, out, err = _run_cli(
        [
            "record-action",
            "--artifact",
            "docs/example.md",
            "--summary",
            "Record without audit log",
            "--behavior",
            "behavior_wire_cli_to_orchestrator",
        ],
        capsys,
    )

    assert exit_code == 0
    assert err == ""
    payload = json.loads(out)
    assert payload.get("audit_log_event_id") is None


def test_replay_actions_and_status(capsys: pytest.CaptureFixture[str]) -> None:
    action_ids: list[str] = []
    for index in range(2):
        exit_code, out, err = _run_cli(
            [
                "record-action",
                "--artifact",
                f"docs/example-{index}.md",
                "--summary",
                f"Replay target {index}",
                "--behavior",
                "behavior_wire_cli_to_orchestrator",
            ],
            capsys,
        )
        assert exit_code == 0
        assert err == ""
        action_ids.append(json.loads(out)["action_id"])

    exit_code, out, err = _run_cli(["replay-actions", *action_ids, "--format", "json"], capsys)
    assert exit_code == 0
    assert err == ""
    replay_payload = json.loads(out)
    assert replay_payload["status"] == "SUCCEEDED"
    replay_id = replay_payload["replay_id"]

    exit_code, out, err = _run_cli(["replay-status", replay_id, "--format", "json"], capsys)
    assert exit_code == 0
    assert err == ""
    status_payload = json.loads(out)
    assert status_payload["replay_id"] == replay_id

    exit_code, out, err = _run_cli(["get-action", action_ids[0]], capsys)
    assert exit_code == 0
    assert err == ""
    action_payload = json.loads(out)
    assert action_payload["replay_status"] == "SUCCEEDED"
