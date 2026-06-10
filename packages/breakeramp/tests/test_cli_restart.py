"""Tests for BreakerAmp restart CLI service targeting."""

import json
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from breakeramp import cli


class _FakeService:
    def __init__(self, environments_dir: Path) -> None:
        self.environments_dir = environments_dir


def _write_environment(
    path: Path,
    run_id: str,
    outputs: dict,
    phase: str = "APPLIED",
    environment: str = "cloud-dev",
) -> Path:
    env_path = path / f"{run_id}.json"
    env_path.write_text(
        json.dumps(
            {
                "amp_run_id": run_id,
                "environment": environment,
                "phase": phase,
                "blueprint_id": environment,
                "runtime": {},
                "blueprint_name": "cloud-dev",
                "environment_outputs": outputs,
            }
        )
    )
    return env_path


def test_resolve_service_name_matches_fresh_display_name() -> None:
    outputs = {
        "amprealize-api": {"container_id": "api-container"},
        "web-console": {"container_id": "web-container"},
    }

    assert cli._resolve_service_name("amprealize-api", outputs) == "amprealize-api"
    assert cli._resolve_service_name("web-console", outputs) == "web-console"
    assert cli._resolve_service_name("missing", outputs) is None


def test_restart_positional_target_can_be_service_name(
    tmp_path: Path,
    monkeypatch,
) -> None:
    environments_dir = tmp_path / "environments"
    environments_dir.mkdir()
    _write_environment(
        environments_dir,
        "amp-run-123",
        {
            "redis": {"container_id": "redis-container"},
            "amprealize-api": {"container_id": "api-container"},
            "web-console": {"container_id": "web-container"},
        },
    )

    calls: list[list[str]] = []

    def fake_run(args: list[str], **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(cli, "get_service", lambda: _FakeService(environments_dir))
    monkeypatch.setattr("subprocess.run", fake_run)

    result = CliRunner().invoke(cli.app, ["restart", "amprealize-api"])

    assert result.exit_code == 0
    assert "Restarted 1 service" in result.output
    assert "amprealize-api" in result.output
    assert ["podman", "container", "exists", "api-container"] in calls
    assert ["podman", "start", "api-container"] in calls
    assert ["podman", "start", "redis-container"] not in calls


def test_restart_unknown_positional_target_lists_available_services(
    tmp_path: Path,
    monkeypatch,
) -> None:
    environments_dir = tmp_path / "environments"
    environments_dir.mkdir()
    _write_environment(
        environments_dir,
        "amp-run-123",
        {
            "gateway": {"container_id": "gateway-container"},
            "whiteboard-sync": {"container_id": "whiteboard-container"},
        },
    )

    monkeypatch.setattr(cli, "get_service", lambda: _FakeService(environments_dir))

    result = CliRunner().invoke(cli.app, ["restart", "amprealize-api"])

    assert result.exit_code == 1
    assert "Environment or service 'amprealize-api' not found" in result.output
    assert "gateway" in result.output
    assert "whiteboard-sync" in result.output


def test_restart_service_name_errors_when_multiple_environments_match(
    tmp_path: Path,
    monkeypatch,
) -> None:
    environments_dir = tmp_path / "environments"
    environments_dir.mkdir()
    outputs = {"amprealize-api": {"container_id": "api-container"}}
    _write_environment(environments_dir, "amp-dev-run", outputs, environment="dev")
    _write_environment(environments_dir, "amp-test-run", outputs, environment="test")

    monkeypatch.setattr(cli, "get_service", lambda: _FakeService(environments_dir))

    result = CliRunner().invoke(cli.app, ["restart", "amprealize-api"])

    assert result.exit_code == 1
    assert "exists in multiple environments" in result.output
    assert "--env <environment>" in result.output
    assert "amp-dev-run" in result.output
    assert "amp-test-run" in result.output


def test_restart_service_name_uses_environment_selector(
    tmp_path: Path,
    monkeypatch,
) -> None:
    environments_dir = tmp_path / "environments"
    environments_dir.mkdir()
    _write_environment(
        environments_dir,
        "amp-dev-run",
        {"amprealize-api": {"container_id": "dev-api-container"}},
        environment="dev",
    )
    _write_environment(
        environments_dir,
        "amp-test-run",
        {"amprealize-api": {"container_id": "test-api-container"}},
        environment="test",
    )

    calls: list[list[str]] = []

    def fake_run(args: list[str], **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(cli, "get_service", lambda: _FakeService(environments_dir))
    monkeypatch.setattr("subprocess.run", fake_run)

    result = CliRunner().invoke(cli.app, ["restart", "--env", "test", "amprealize-api"])

    assert result.exit_code == 0
    assert ["podman", "container", "exists", "test-api-container"] in calls
    assert ["podman", "start", "test-api-container"] in calls
    assert ["podman", "start", "dev-api-container"] not in calls


def test_restart_wait_invokes_stack_poll(
    tmp_path: Path,
    monkeypatch,
) -> None:
    environments_dir = tmp_path / "environments"
    environments_dir.mkdir()
    _write_environment(
        environments_dir,
        "amp-run-123",
        {
            "amprealize-api": {"container_id": "api-container"},
        },
    )

    monkeypatch.setattr(cli, "get_service", lambda: _FakeService(environments_dir))
    monkeypatch.setattr("subprocess.run", lambda *a, **k: SimpleNamespace(returncode=0, stderr="", stdout=""))

    calls: list[dict] = []

    def fake_wait(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "attempts": 1, "elapsed_s": 0.1, "last_error": None}

    monkeypatch.setattr(cli, "_run_stack_wait_poll", fake_wait)

    result = CliRunner().invoke(cli.app, ["restart", "amprealize-api", "--wait"])

    assert result.exit_code == 0
    assert any(c.get("strict") is False for c in calls)
    assert "Stack healthy" in result.output or "✓ Stack healthy" in result.output
