from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from amprealize.breakeramp import BreakerAmpService


pytestmark = pytest.mark.unit  # All tests in this module are unit tests


@pytest.fixture()
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home_dir = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home_dir)
    return home_dir


@pytest.fixture()
def breakeramp_service(fake_home: Path) -> BreakerAmpService:
    return BreakerAmpService(
        action_service=MagicMock(),
        compliance_service=MagicMock(),
        metrics_service=MagicMock(),
    )


def test_configure_scaffolds_manifest_and_blueprints(
    breakeramp_service: BreakerAmpService, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config" / "breakeramp"

    result = breakeramp_service.configure(
        config_dir=config_dir,
        include_blueprints=True,
    )

    env_file = config_dir / "environments.yaml"
    assert env_file.exists()
    assert env_file.read_text(encoding="utf-8").strip() != ""

    blueprints_dir = config_dir / "blueprints"
    assert blueprints_dir.exists()
    packaged_names = {path.name for path in breakeramp_service.pkg_blueprints_dir.glob("*.yaml")}
    copied_names = {path.name for path in blueprints_dir.glob("*.yaml")}
    assert packaged_names.issubset(copied_names)
    assert result["environment_status"] == "created"
    assert blueprints_dir.is_dir()

    cloud_dev = yaml.safe_load((blueprints_dir / "cloud-dev.yaml").read_text(encoding="utf-8"))
    assert "telemetry-db" in cloud_dev["services"]
    assert cloud_dev["services"]["telemetry-db"]["ports"] == ["${AMPREALIZE_PG_PORT_TELEMETRY:-5433}:5432"]  # gitleaks:allow
    api_env = cloud_dev["services"]["amprealize-api"]["environment"]
    worker_env = cloud_dev["services"]["execution-worker"]["environment"]
    mcp_env = cloud_dev["services"]["amprealize-mcp"]["environment"]
    assert "telemetry-db" in cloud_dev["services"]["amprealize-api"]["depends_on"]
    assert "telemetry-db" in cloud_dev["services"]["execution-worker"]["depends_on"]
    assert "telemetry-db" in cloud_dev["services"]["amprealize-mcp"]["depends_on"]
    assert ".[postgres]" in " ".join(cloud_dev["services"]["execution-worker"]["command"])
    assert ".[postgres]" in "\n".join(cloud_dev["services"]["amprealize-api"]["command"])
    assert ".[postgres]" in " ".join(cloud_dev["services"]["amprealize-mcp"]["command"])
    post_start = cloud_dev["services"]["amprealize-api"]["post_start_commands"]
    assert post_start[0]["command"][-1].endswith("python -m alembic -c alembic.telemetry.ini upgrade head")
    assert api_env["DATABASE_URL"] == "${BREAKERAMP_CLOUD_DATABASE_URL}"  # gitleaks:allow
    assert api_env["TELEMETRY_DATABASE_URL"] == "${BREAKERAMP_CLOUD_TELEMETRY_DATABASE_URL}"  # gitleaks:allow
    assert api_env["AMPREALIZE_TELEMETRY_PG_DSN"] == "${BREAKERAMP_CLOUD_TELEMETRY_PG_DSN}"  # gitleaks:allow
    assert api_env["AMPREALIZE_TELEMETRY_ENABLED"] == "${AMPREALIZE_TELEMETRY_ENABLED:-true}"  # gitleaks:allow
    assert api_env["AMPREALIZE_METRICS_PG_DSN"] == "${BREAKERAMP_CLOUD_METRICS_PG_DSN}"  # gitleaks:allow
    assert worker_env["DATABASE_URL"] == "${BREAKERAMP_CLOUD_DATABASE_URL}"  # gitleaks:allow
    assert worker_env["AMPREALIZE_TELEMETRY_PG_DSN"] == "${BREAKERAMP_CLOUD_TELEMETRY_PG_DSN}"  # gitleaks:allow
    assert worker_env["AMPREALIZE_METRICS_PG_DSN"] == "${BREAKERAMP_CLOUD_METRICS_PG_DSN}"  # gitleaks:allow
    assert mcp_env["DATABASE_URL"] == "${BREAKERAMP_CLOUD_DATABASE_URL}"  # gitleaks:allow
    assert mcp_env["AMPREALIZE_TELEMETRY_ENABLED"] == "${AMPREALIZE_TELEMETRY_ENABLED:-true}"  # gitleaks:allow
    assert api_env["AMPREALIZE_DATADOG_OTLP_ENDPOINT"] == "${AMPREALIZE_DATADOG_OTLP_ENDPOINT:-}"  # gitleaks:allow
    assert api_env["AMPREALIZE_DATADOG_API_KEY"] == "${AMPREALIZE_DATADOG_API_KEY:-}"  # gitleaks:allow
    assert api_env["AMPREALIZE_LANGFUSE_PUBLIC_KEY"] == "${AMPREALIZE_LANGFUSE_PUBLIC_KEY:-}"  # gitleaks:allow
    assert api_env["AMPREALIZE_LANGFUSE_SECRET_KEY"] == "${AMPREALIZE_LANGFUSE_SECRET_KEY:-}"  # gitleaks:allow
    assert api_env["AMPREALIZE_LANGFUSE_HOST"] == "${AMPREALIZE_LANGFUSE_HOST:-}"  # gitleaks:allow
    assert worker_env["AMPREALIZE_LANGFUSE_HOST"] == "${AMPREALIZE_LANGFUSE_HOST:-}"  # gitleaks:allow
    assert mcp_env["AMPREALIZE_DATADOG_OTLP_ENDPOINT"] == "${AMPREALIZE_DATADOG_OTLP_ENDPOINT:-}"  # gitleaks:allow

    environments = yaml.safe_load(env_file.read_text(encoding="utf-8"))["environments"]
    assert environments["local-postgres"]["infrastructure"]["blueprint_id"] == "local-dev"
    assert environments["neon"]["infrastructure"]["blueprint_id"] == "cloud-dev"
    assert environments["self-hosted-observability"]["active_modules"] == ["core", "console", "whiteboard", "monitoring"]
    assert environments["managed-enterprise-observability"]["infrastructure"]["blueprint_id"] == "cloud-dev"


def test_configure_respects_force_flag(breakeramp_service: BreakerAmpService, tmp_path: Path) -> None:
    config_dir = tmp_path / "config" / "breakeramp"
    breakeramp_service.configure(config_dir=config_dir, include_blueprints=False)

    # Without force, should skip (not raise)
    result = breakeramp_service.configure(config_dir=config_dir)
    assert result["environment_status"] == "skipped"

    # With force, should overwrite
    result = breakeramp_service.configure(config_dir=config_dir, force=True)
    assert result["environment_status"] == "overwritten"
