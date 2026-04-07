import json
from pathlib import Path

import pytest

from amprealize import cli

# Mark all tests in this module as unit tests - no infrastructure required
pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def reset_cli_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cli._reset_action_state_for_testing()
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")


def _run_cli(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    import sys
    from unittest.mock import patch

    # Patch sys.argv so that cli.main() sees the arguments
    with patch.object(sys, "argv", ["amprealize"] + args):
        exit_code = cli.main()

    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def test_breakeramp_bootstrap_creates_workspace(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"

    exit_code, out, err = _run_cli(
        [
            "breakeramp",
            "bootstrap",
            "--directory",
            str(workspace),
            "--include-blueprints",
        ],
        capsys,
    )

    assert exit_code == 0
    assert err == ""
    payload = json.loads(out)
    env_file = Path(payload["environment_file"])
    assert env_file.exists()
    assert env_file.is_file()

    # Blueprints are placed in <target_dir>/blueprints/ (not config/breakeramp/blueprints)
    blueprints_dir = workspace / "blueprints"
    assert blueprints_dir.exists()
    assert payload["blueprints"]
    assert all(entry["status"] in {"copied", "overwritten", "skipped"} for entry in payload["blueprints"])


def test_resolve_output_format_respects_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyStream:
        def __init__(self, is_tty: bool) -> None:
            self._is_tty = is_tty

        def isatty(self) -> bool:
            return self._is_tty

    monkeypatch.setattr(cli.sys, "stdout", DummyStream(True))
    assert cli._resolve_output_format(None) == "summary"

    monkeypatch.setattr(cli.sys, "stdout", DummyStream(False))
    assert cli._resolve_output_format(None) == "json"
    assert cli._resolve_output_format("json") == "json"


def test_save_breakeramp_snapshot_persists_payload(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "BREAKERAMP_SNAPSHOT_DIR", tmp_path)
    payload = {"demo": True}
    snapshot_path = cli._save_breakeramp_snapshot("plan", payload)
    assert snapshot_path.exists()
    saved = json.loads(snapshot_path.read_text())
    assert saved == payload
