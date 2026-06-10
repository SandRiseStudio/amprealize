"""Contract tests for BreakerAmp's command surface."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from breakeramp import cli as cli_module
from breakeramp.executors.podman import PodmanExecutor


runner = CliRunner()

_BREAKERAMP_PKG = Path(__file__).resolve().parents[1]
_AMPREALIZE_ROOT = Path(__file__).resolve().parents[3]


def test_help_lists_primary_command_surface() -> None:
    result = runner.invoke(cli_module.app, ["--help"])

    assert result.exit_code == 0
    for command in [
        "up",
        "list",
        "services",
        "restart",
        "wait-health",
        "status",
        "resources",
        "cleanup",
        "fresh",
    ]:
        assert command in result.output


def test_docs_classify_primary_advanced_and_support_commands() -> None:
    readme = (_BREAKERAMP_PKG / "README.md").read_text()
    work_guide = (_AMPREALIZE_ROOT / "docs" / "WORK_MANAGEMENT_GUIDE.md").read_text()

    assert "| Primary | `up`, `list`, `services`, `restart`, `status`, `resources`, `cleanup`, `fresh` |" in readme
    assert "| Advanced | `plan`, `apply`, `destroy`, `nuke`, `backup`, `restore`, `run-tests`, `plan-for-tests` |" in readme
    assert "| Support | `blueprints`, `configure`, `validate`, `version`, `backups`, `stop`, `wait-health` |" in readme
    assert "#### BreakerAmp Command Matrix" in work_guide


def test_resources_json_includes_recommendation(monkeypatch) -> None:
    class FakeExecutor:
        def get_resource_insights(self, machine_name=None, verbose=False):
            return {
                "resources": {"memory_used_mb": 900, "memory_total_mb": 1000},
                "insights": {
                    "memory": {
                        "level": "WARNING",
                        "message": "memory nearing capacity",
                    }
                },
                "summary": "memory nearing capacity",
            }

    monkeypatch.setattr(cli_module, "PodmanExecutor", FakeExecutor)

    result = runner.invoke(cli_module.app, ["resources", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["recommendation"].startswith("Capacity action recommended")
    assert "cleanup --dry-run" in payload["recommendation"]


def test_resource_recommendation_routes_failing_containers_to_services() -> None:
    recommendation = cli_module._resource_recommendation({
        "insights": {
            "memory": {"level": "OVER_PROVISIONED", "message": "memory significantly over-provisioned"},
            "disk": {"level": "OVER_PROVISIONED", "message": "disk significantly over-provisioned"},
            "containers": {"level": "CRITICAL", "message": "containers failing - intervention needed"},
            "overall": {"level": "OK", "message": "minor issues detected"},
        }
    })

    assert recommendation.startswith("Service action recommended")
    assert "breakeramp services --all" in recommendation
    assert "cleanup --dry-run" not in recommendation


def test_resource_recommendation_routes_capacity_pressure_to_cleanup() -> None:
    recommendation = cli_module._resource_recommendation({
        "insights": {
            "memory": {"level": "CRITICAL", "message": "memory nearly full - action required"},
            "containers": {"level": "GOOD", "message": "containers running normally"},
        }
    })

    assert recommendation.startswith("Capacity action recommended")
    assert "cleanup --dry-run" in recommendation
    assert "memory pressure" in recommendation


def test_resource_recommendation_marks_over_provisioning_optional() -> None:
    recommendation = cli_module._resource_recommendation({
        "insights": {
            "memory": {"level": "OVER_PROVISIONED", "message": "memory significantly over-provisioned"},
            "disk": {"level": "OVER_PROVISIONED", "message": "disk significantly over-provisioned"},
            "containers": {"level": "GOOD", "message": "containers running normally"},
        }
    })

    assert recommendation.startswith("Optimization optional")
    assert "No cleanup is required" in recommendation


def test_podman_resource_insights_imports_analyzer(monkeypatch) -> None:
    executor = PodmanExecutor()

    monkeypatch.setattr(
        executor,
        "get_machine_resources",
        lambda machine_name=None: {"memory_used_mb": 100, "memory_total_mb": 1000},
    )
    monkeypatch.setattr(
        executor,
        "list_container_name_state_map",
        lambda: {},
    )

    resource_data = executor.get_resource_insights()

    assert "summary" in resource_data
    assert "insights" in resource_data


def test_podman_disk_usage_handles_list_shaped_system_df() -> None:
    executor = PodmanExecutor()
    executor._run_podman = lambda *args, **kwargs: SimpleNamespace(
        returncode=0,
        stdout=json.dumps(
            [
                {
                    "Type": "Images",
                    "Images": [{"Size": 1024 * 1024, "Reclaimable": 512 * 1024}],
                },
                {
                    "Type": "Containers",
                    "Containers": [{"Size": 2 * 1024 * 1024, "RWSize": 256 * 1024}],
                },
                {
                    "Type": "Volumes",
                    "Volumes": [{"Size": 3 * 1024 * 1024, "Reclaimable": 1024 * 1024}],
                },
            ]
        ),
    )

    disk_usage = executor.get_disk_usage()

    assert disk_usage["total_mb"] == 6
    assert disk_usage["reclaimable_mb"] == 1.75


def test_status_json_is_machine_readable(monkeypatch) -> None:
    fake_response = SimpleNamespace(
        model_dump_json=lambda indent=2: json.dumps(
            {
                "amp_run_id": "amp-run-123",
                "phase": "APPLIED",
                "progress_pct": 100,
                "checks": [{"name": "amprealize-api", "status": "running"}],
            },
            indent=indent,
        )
    )
    fake_service = SimpleNamespace(status=lambda run_id: fake_response)

    monkeypatch.setattr(cli_module, "get_service", lambda: fake_service)

    result = runner.invoke(cli_module.app, ["status", "amp-run-123", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["amp_run_id"] == "amp-run-123"
    assert payload["checks"][0]["name"] == "amprealize-api"


def test_cleanup_dry_run_json_has_actionable_sections(monkeypatch) -> None:
    class FakeExecutor:
        def smart_cleanup(self, **kwargs):
            assert kwargs["dry_run"] is True
            return {
                "dead_containers": [{"name": "amp-old-api", "status": "Exited"}],
                "anonymous_volumes": ["1234567890abcdef"],  # pragma: allowlist secret
                "preserved_volumes": ["amprealize_db_data"],
                "unused_images": [],
                "build_cache_cleared": False,
                "errors": [],
            }

    monkeypatch.setattr(cli_module, "PodmanExecutor", FakeExecutor)

    result = runner.invoke(cli_module.app, ["cleanup", "--dry-run", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert payload["dead_containers"][0]["name"] == "amp-old-api"
    assert payload["anonymous_volumes"] == ["1234567890abcdef"]  # pragma: allowlist secret
    assert payload["preserved_volumes"] == ["amprealize_db_data"]
    assert payload["stale_state"] == {"environments": [], "manifests": [], "snapshots": []}


def test_nuke_dry_run_json_has_destructive_sections(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state_dir = tmp_path / ".amprealize" / "breakeramp" / "environments"
    state_dir.mkdir(parents=True)
    (state_dir / "amp-run.json").write_text("{}")

    class FakeExecutor:
        def resolve_connection_for_machine(self, machine_name: str):
            return None

    def fake_run(args: list[str], **kwargs):
        command = " ".join(args)
        if "machine list" in command and "{{.Running}}" in command:
            return SimpleNamespace(returncode=0, stdout="amprealize-dev\ttrue\n", stderr="")
        if "machine list" in command and "{{.VMType}}" in command:
            return SimpleNamespace(returncode=0, stdout="amprealize-dev\tapplehv\ttrue\n", stderr="")
        if "ps -a" in command:
            return SimpleNamespace(
                returncode=0,
                stdout="abc123\tamp-12345678-1234-1234-1234-123456789abc-amprealize-api\tUp 5 minutes\n",
                stderr="",
            )
        if "network ls" in command:
            return SimpleNamespace(returncode=0, stdout="podman\namp-12345678-1234-1234-1234-123456789abc-network\n", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(cli_module, "PodmanExecutor", FakeExecutor)
    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runner.invoke(
        cli_module.app,
        ["nuke", "--dry-run", "--json", "--no-processes", "--no-stop-machine", "--skip-backup"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert payload["summary"]["containers_total"] == 1
    assert payload["summary"]["networks"] == 1
    assert payload["summary"]["state_files"] == 1
    assert "progress.description" not in result.output
