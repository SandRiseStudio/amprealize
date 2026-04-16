"""Tests for BreakerAmp CLI helpers."""

import subprocess
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