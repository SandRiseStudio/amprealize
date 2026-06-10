"""Tests for BreakerAmp CLI helpers."""

import re
import subprocess
import json
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from breakeramp import cli as cli_module
from breakeramp.cli import _recover_podman_machine_start
from breakeramp.cli import _is_cloud_dsn, _check_context_blueprint_mismatch
from breakeramp.cli import (
    _get_environment_podman_machine,
    _select_podman_machine_for_environment,
)


runner = CliRunner()


def test_get_environment_podman_machine_returns_runtime_value() -> None:
    service = SimpleNamespace(
        environments={
            "development": SimpleNamespace(
                runtime=SimpleNamespace(provider="podman", podman_machine="amprealize-dev")
            )
        }
    )

    assert _get_environment_podman_machine(service, "development") == "amprealize-dev"


def test_get_environment_podman_machine_returns_none_for_missing_environment() -> None:
    service = SimpleNamespace(environments={})

    assert _get_environment_podman_machine(service, "development") is None


def test_select_podman_machine_prefers_environment_configured_name() -> None:
    selected = _select_podman_machine_for_environment(
        ["amprealize-test", "amprealize-dev"],
        preferred_name="amprealize-dev",
    )

    assert selected == "amprealize-dev"


def test_select_podman_machine_does_not_fallback_to_wrong_machine_when_preferred_missing() -> None:
    selected = _select_podman_machine_for_environment(
        ["amprealize-test"],
        preferred_name="amprealize-dev",
    )

    assert selected is None


def test_select_podman_machine_falls_back_only_when_no_environment_machine_configured() -> None:
    selected = _select_podman_machine_for_environment(
        ["custom-machine", "amprealize-test"],
        preferred_name=None,
    )

    assert selected == "amprealize-test"


def test_fresh_runs_nuke_before_live_display(monkeypatch) -> None:
    calls: list[object] = []
    display_state = {"entered": False}

    class FakeDisplay:
        def __init__(self, *args, **kwargs) -> None:
            calls.append("display_init")

        def __enter__(self):
            display_state["entered"] = True
            calls.append("display_enter")
            return self

        def __exit__(self, *args) -> None:
            calls.append("display_exit")
            display_state["entered"] = False

        def on_phase(self, phase: str, description: str, total_steps: int = 0) -> None:
            calls.append(("phase", phase))

        def on_step_done(self, step: str, **kwargs) -> None:
            calls.append(("done", step))

        def print_summary(self, amp_run_id: str = "") -> None:
            calls.append(("summary", amp_run_id))

    def fake_nuke(**kwargs) -> None:
        assert display_state["entered"] is False
        calls.append("nuke")

    def fake_plan(request):
        assert display_state["entered"] is True
        calls.append("plan")
        return SimpleNamespace(plan_id="plan-123")

    def fake_apply(request, progress):
        assert display_state["entered"] is True
        calls.append("apply")
        return SimpleNamespace(amp_run_id="run-123")

    fake_service = SimpleNamespace(plan=fake_plan, apply=fake_apply)

    monkeypatch.setattr(cli_module, "_apply_amprealize_context", lambda quiet=False: None)
    monkeypatch.setattr(cli_module, "get_service", lambda: fake_service)
    monkeypatch.setattr(cli_module, "nuke", fake_nuke)
    monkeypatch.setattr(cli_module, "LiveProgressDisplay", FakeDisplay)

    result = runner.invoke(
        cli_module.app,
        ["fresh", "development", "--force", "--skip-machine-stop", "--skip-resource-check"],
    )

    assert result.exit_code == 0
    assert calls.index("nuke") < calls.index("display_enter")
    assert "apply" in calls


def test_list_hides_stopped_runs_by_default(monkeypatch) -> None:
    fake_service = SimpleNamespace(
        list_environments=lambda reconcile=True, auto_cleanup=True: [
            {
                "amp_run_id": "amp-running-123456",
                "environment": "cloud-dev",
                "phase": "APPLIED",
                "created_at": "2026-04-27T00:00:00",
                "actual_status": "RUNNING",
                "container_count": 8,
                "running_count": 8,
            },
            {
                "amp_run_id": "amp-stopped-123456",
                "environment": "cloud-dev",
                "phase": "APPLIED",
                "created_at": "2026-04-26T00:00:00",
                "actual_status": "STOPPED",
                "container_count": 1,
                "running_count": 0,
            },
        ]
    )

    monkeypatch.setattr(cli_module, "get_service", lambda: fake_service)

    result = runner.invoke(cli_module.app, ["list"])
    clean_output = re.sub(r"\x1b\[[0-9;]*m", "", result.output)

    assert result.exit_code == 0
    assert "Current Environments" in clean_output
    # Run ID column may truncate with an ellipsis (narrow terminals).
    assert "amp-runn" in clean_output
    assert "amp-stopped" not in clean_output
    assert "Hidden 1 stopped historical run" in clean_output


def test_list_all_shows_stopped_runs(monkeypatch) -> None:
    fake_service = SimpleNamespace(
        list_environments=lambda reconcile=True, auto_cleanup=True: [
            {
                "amp_run_id": "amp-stopped-123456",
                "environment": "cloud-dev",
                "phase": "APPLIED",
                "created_at": "2026-04-26T00:00:00",
                "actual_status": "STOPPED",
                "container_count": 1,
                "running_count": 0,
            },
        ]
    )

    monkeypatch.setattr(cli_module, "get_service", lambda: fake_service)

    result = runner.invoke(cli_module.app, ["list", "--all"])

    assert result.exit_code == 0
    assert "All Environments" in result.output
    assert "amp-stop" in result.output
    assert "STOPPED" in result.output


def test_list_shows_managed_and_raw_podman_machines_by_default(monkeypatch) -> None:
    fake_service = SimpleNamespace(
        environments={
            "development": SimpleNamespace(
                runtime=SimpleNamespace(provider="podman", podman_machine="amprealize-dev"),
            ),
            "test": SimpleNamespace(
                runtime=SimpleNamespace(provider="podman", podman_machine="amprealize-test"),
            ),
        },
        executor=SimpleNamespace(
            list_machines=lambda: [
                SimpleNamespace(name="amprealize-dev", running=True, cpus=4, memory_mb=2048, disk_gb=20),
                SimpleNamespace(name="amprealize-test", running=False, cpus=2, memory_mb=2048, disk_gb=30),
                SimpleNamespace(name="other-machine", running=False, cpus=1, memory_mb=1024, disk_gb=10),
            ]
        ),
        list_environments=lambda reconcile=True, auto_cleanup=True: [
            {
                "amp_run_id": "amp-running-123456",
                "environment": "development",
                "phase": "APPLIED",
                "created_at": "2026-04-27T00:00:00",
                "actual_status": "RUNNING",
                "container_count": 8,
                "running_count": 8,
            },
        ],
    )

    monkeypatch.setattr(cli_module, "get_service", lambda: fake_service)

    result = runner.invoke(cli_module.app, ["list"])

    assert result.exit_code == 0
    assert "BreakerAmp-managed Podman machines" in result.output
    assert "Raw Podman machines" in result.output
    assert "amprealize-dev" in result.output
    assert "amprealize-test" in result.output
    assert "other-machine" in result.output


def test_services_lists_running_environment_services(tmp_path: Path, monkeypatch) -> None:
    environments_dir = tmp_path / "environments"
    environments_dir.mkdir()
    run_id = "amp-running-123456"
    (environments_dir / f"{run_id}.json").write_text(json.dumps({
        "amp_run_id": run_id,
        "environment": "cloud-dev",
        "runtime": {},
        "environment_outputs": {
            "amprealize-api": {"container_id": "api-container"},
            "web-console": {"container_id": "web-container"},
        },
    }))

    fake_service = SimpleNamespace(
        environments_dir=environments_dir,
        list_environments=lambda reconcile=True, auto_cleanup=True: [
            {
                "amp_run_id": run_id,
                "environment": "cloud-dev",
                "actual_status": "RUNNING",
            }
        ],
    )

    class FakeExecutor:
        def __init__(self, connection=None) -> None:
            self.connection = connection

        def inspect_container(self, container_id: str):
            return SimpleNamespace(
                container_id=container_id,
                name=f"{run_id}-amprealize-api" if container_id == "api-container" else f"{run_id}-web-console",
                status="running",
                image="amprealize/test:latest",
                ports={"8000/tcp": "8000"} if container_id == "api-container" else {"3000/tcp": "3000"},
            )

    monkeypatch.setattr(cli_module, "get_service", lambda: fake_service)
    monkeypatch.setattr(cli_module, "PodmanExecutor", FakeExecutor)

    result = runner.invoke(cli_module.app, ["services", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    service_names = {row["service"] for row in payload}
    assert service_names == {"amprealize-api", "web-console"}
    api_row = next(row for row in payload if row["service"] == "amprealize-api")
    assert api_row["ports"] == {"8000/tcp": "8000"}
    assert api_row["restart_command"] == f"breakeramp restart {run_id} -s amprealize-api"


def test_services_filters_by_environment_and_hides_stopped_by_default(
    tmp_path: Path,
    monkeypatch,
) -> None:
    environments_dir = tmp_path / "environments"
    environments_dir.mkdir()
    running_id = "amp-running-123456"
    stopped_id = "amp-stopped-123456"
    for run_id, env_name in [(running_id, "dev"), (stopped_id, "test")]:
        (environments_dir / f"{run_id}.json").write_text(json.dumps({
            "amp_run_id": run_id,
            "environment": env_name,
            "runtime": {},
            "environment_outputs": {
                "amprealize-api": {"container_id": f"{env_name}-api-container"},
            },
        }))

    fake_service = SimpleNamespace(
        environments_dir=environments_dir,
        list_environments=lambda reconcile=True, auto_cleanup=True: [
            {"amp_run_id": running_id, "environment": "dev", "actual_status": "RUNNING"},
            {"amp_run_id": stopped_id, "environment": "test", "actual_status": "STOPPED"},
        ],
    )

    class FakeExecutor:
        def __init__(self, connection=None) -> None:
            self.connection = connection

        def inspect_container(self, container_id: str):
            return SimpleNamespace(
                container_id=container_id,
                name=container_id,
                status="running",
                image="amprealize/test:latest",
                ports={},
            )

    monkeypatch.setattr(cli_module, "get_service", lambda: fake_service)
    monkeypatch.setattr(cli_module, "PodmanExecutor", FakeExecutor)

    result = runner.invoke(cli_module.app, ["services", "--env", "test"])
    clean_output = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    assert result.exit_code == 0
    assert "No running services found for environment 'test'" in clean_output

    result_all = runner.invoke(cli_module.app, ["services", "--env", "test", "--all", "--json"])
    assert result_all.exit_code == 0
    payload = json.loads(result_all.output)
    assert payload[0]["environment"] == "test"
    assert payload[0]["service"] == "amprealize-api"


def test_nuke_removes_state_by_default_and_reports_failed_container_rm(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state_dir = tmp_path / ".amprealize" / "breakeramp"
    for subdir in ("environments", "manifests", "snapshots"):
        path = state_dir / subdir
        path.mkdir(parents=True, exist_ok=True)
        (path / f"{subdir}.json").write_text("{}")

    class FakeExecutor:
        def resolve_connection_for_machine(self, machine_name: str):
            return None

    calls: list[list[str]] = []

    def fake_run(args: list[str], **kwargs):
        calls.append(args)
        command = " ".join(args)
        if "machine list" in command:
            return SimpleNamespace(returncode=0, stdout="amprealize-dev\ttrue\n", stderr="")
        if "ps -a" in command:
            return SimpleNamespace(
                returncode=0,
                stdout="abc123\tamp-12345678-1234-1234-1234-123456789abc-execution-worker\tExited (137)\n",
                stderr="",
            )
        if "rm -f abc123" in command:
            return SimpleNamespace(returncode=125, stdout="", stderr="container still exists")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(cli_module, "PodmanExecutor", FakeExecutor)
    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runner.invoke(
        cli_module.app,
        [
            "nuke",
            "--force",
            "--no-stop-machine",
            "--no-processes",
            "--no-networks",
            "--skip-backup",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["containers"] == []
    assert "Failed to remove amp-12345678-1234-1234-1234-123456789abc-execution-worker: container still exists" in payload["errors"]
    assert len(payload["state_files"]) == 3
    assert not any((state_dir / subdir / f"{subdir}.json").exists() for subdir in ("environments", "manifests", "snapshots"))


def test_recover_podman_machine_start_recreates_machine(monkeypatch) -> None:
    calls: list[object] = []

    class FakeExecutor:
        def inspect_machine(self, name: str):
            calls.append(("inspect", name))
            return {
                "Resources": {"CPUs": 4, "Memory": 2048, "DiskSize": 20},
                "SSH": {"Port": 51975},
            }

        def stop_machine(self, name: str) -> None:
            calls.append(("stop", name))

        def remove_machine(self, name: str, force: bool = False) -> bool:
            calls.append(("remove", name, force))
            return True

        def init_machine(self, name: str, cpus=None, memory_mb=None, disk_gb=None) -> None:
            calls.append(("init", name, cpus, memory_mb, disk_gb))

        def start_machine(self, name: str) -> None:
            calls.append(("start", name))

    fake_service = SimpleNamespace(executor=FakeExecutor())

    import breakeramp.executors.podman as podman_module

    monkeypatch.setattr(podman_module, "PodmanExecutor", FakeExecutor)

    subprocess_calls: list[list[str]] = []

    def fake_run(cmd, capture_output=True, text=True):
        subprocess_calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert _recover_podman_machine_start(fake_service, "amprealize-dev", quiet=True) is True
    assert ("remove", "amprealize-dev", True) in calls
    assert ("init", "amprealize-dev", 4, 2048, 20) in calls
    assert ("start", "amprealize-dev") in calls
    assert any(cmd[:2] == ["pkill", "-f"] for cmd in subprocess_calls)


# ---------------------------------------------------------------------------
# _is_cloud_dsn
# ---------------------------------------------------------------------------

def test_is_cloud_dsn_localhost() -> None:
    assert _is_cloud_dsn("postgresql://user:pass@localhost:5432/db") is False


def test_is_cloud_dsn_127() -> None:
    assert _is_cloud_dsn("postgresql://user:pass@127.0.0.1:5432/db") is False


def test_is_cloud_dsn_ipv6_loopback() -> None:
    assert _is_cloud_dsn("postgresql://user:pass@[::1]:5432/db") is False


def test_is_cloud_dsn_empty() -> None:
    assert _is_cloud_dsn("") is False


def test_is_cloud_dsn_neon() -> None:
    assert _is_cloud_dsn("postgresql://user:pass@ep-cool-rain-123456.us-east-2.aws.neon.tech/db") is True


def test_is_cloud_dsn_supabase() -> None:
    assert _is_cloud_dsn("postgresql://user:pass@db.xyzabc.supabase.co:5432/postgres") is True


def test_is_cloud_dsn_custom_host() -> None:
    assert _is_cloud_dsn("postgresql://user:pass@my-rds-host.amazonaws.com:5432/db") is True


# ---------------------------------------------------------------------------
# _check_context_blueprint_mismatch
# ---------------------------------------------------------------------------

def _make_service_with_envs(envs: dict) -> SimpleNamespace:
    """Build a minimal fake service with an environments dict."""
    return SimpleNamespace(environments=envs)


def test_mismatch_returns_none_when_no_context() -> None:
    service = _make_service_with_envs({})
    assert _check_context_blueprint_mismatch(None, "development", service) is None


def test_mismatch_returns_none_when_local_dsn(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    service = _make_service_with_envs({
        "development": SimpleNamespace(infrastructure=SimpleNamespace(blueprint_id="local-dev")),
        "cloud-dev": SimpleNamespace(infrastructure=SimpleNamespace(blueprint_id="cloud-dev")),
    })
    assert _check_context_blueprint_mismatch("local", "development", service) is None


def test_mismatch_detects_cloud_dsn_with_local_blueprint(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@ep-cool-rain.neon.tech/db")
    service = _make_service_with_envs({
        "development": SimpleNamespace(infrastructure=SimpleNamespace(blueprint_id="local-dev")),
        "cloud-dev": SimpleNamespace(infrastructure=SimpleNamespace(blueprint_id="cloud-dev")),
    })
    result = _check_context_blueprint_mismatch("neon", "development", service)
    assert result is not None
    warning_msg, suggested = result
    assert suggested == "cloud-dev"
    assert "neon" in warning_msg.lower() or "neon" in warning_msg


def test_mismatch_returns_none_when_already_cloud_dev(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@ep-cool-rain.neon.tech/db")
    service = _make_service_with_envs({
        "cloud-dev": SimpleNamespace(infrastructure=SimpleNamespace(blueprint_id="cloud-dev")),
    })
    assert _check_context_blueprint_mismatch("neon", "cloud-dev", service) is None


def test_mismatch_respects_blueprint_override(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@ep-cool-rain.neon.tech/db")
    service = _make_service_with_envs({
        "development": SimpleNamespace(infrastructure=SimpleNamespace(blueprint_id="local-dev")),
        "cloud-dev": SimpleNamespace(infrastructure=SimpleNamespace(blueprint_id="cloud-dev")),
    })
    # Explicit --blueprint cloud-dev override → no mismatch
    assert _check_context_blueprint_mismatch("neon", "development", service, blueprint_override="cloud-dev") is None


def test_mismatch_returns_none_when_no_cloud_dev_env(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@ep-cool-rain.neon.tech/db")
    service = _make_service_with_envs({
        "development": SimpleNamespace(infrastructure=SimpleNamespace(blueprint_id="local-dev")),
    })
    # No cloud-dev env to suggest → no mismatch reported
    assert _check_context_blueprint_mismatch("neon", "development", service) is None


def test_orphan_amp_run_ids_strips_leading_slash_before_stack_regex() -> None:
    """Podman sometimes prefixes Names with ``/``; orphan detection must still match."""
    from breakeramp.cli import _orphan_amp_run_ids_from_podman

    run_id = "amp-036907d8-f496-41f9-80d2-a022cecc6851"

    class FakeExecutor:
        connection = None

        def list_container_name_state_map(self):
            return {f"/{run_id}-amprealize-api": "running"}

    service = SimpleNamespace(executor=FakeExecutor())
    assert _orphan_amp_run_ids_from_podman(service) == [run_id]
