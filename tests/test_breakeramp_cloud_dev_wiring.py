import os
from pathlib import Path

import pytest

from amprealize.context import apply_context_to_environment
from breakeramp.cli import _set_cloud_container_database_env


pytestmark = pytest.mark.unit


def test_apply_context_to_environment_uses_main_dsn_when_telemetry_not_explicit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
version: 2
current_context: neon
contexts:
  neon:
    storage:
      backend: postgres
      postgres:
        dsn: postgresql://main_user:main_pass@cloud.example.com/amprealize  # pragma: allowlist secret
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr("amprealize.context.USER_CONFIG_PATH", config_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TELEMETRY_DATABASE_URL", raising=False)
    monkeypatch.delenv("AMPREALIZE_TELEMETRY_PG_DSN", raising=False)

    # ``apply_context_to_environment(force=True)`` mutates the global process env.
    # Snapshot and restore so later tests are not poisoned with synthetic cloud.example.com DSNs.
    env_snapshot = os.environ.copy()
    try:
        context_name = apply_context_to_environment(force=True)

        assert context_name == "neon"
        assert os.environ["DATABASE_URL"] == "postgresql://main_user:main_pass@cloud.example.com/amprealize"  # pragma: allowlist secret
        assert "TELEMETRY_DATABASE_URL" not in os.environ
        assert "AMPREALIZE_TELEMETRY_PG_DSN" not in os.environ
    finally:
        os.environ.clear()
        os.environ.update(env_snapshot)


def test_cloud_container_database_env_rewrites_loopback_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://main_user:main_pass@ep.example.com/neondb?sslmode=require")  # pragma: allowlist secret
    monkeypatch.setenv(
        "AMPREALIZE_TELEMETRY_PG_DSN",
        "postgresql://telemetry:telemetry_dev@localhost:5433/telemetry}}",  # pragma: allowlist secret
    )
    monkeypatch.delenv("TELEMETRY_DATABASE_URL", raising=False)
    monkeypatch.delenv("AMPREALIZE_METRICS_PG_DSN", raising=False)

    _set_cloud_container_database_env()

    assert os.environ["BREAKERAMP_CLOUD_DATABASE_URL"] == os.environ["DATABASE_URL"]
    assert (
        os.environ["BREAKERAMP_CLOUD_TELEMETRY_PG_DSN"]
        == "postgresql://telemetry:telemetry_dev@host.containers.internal:5433/telemetry"  # pragma: allowlist secret
    )
    assert (
        os.environ["BREAKERAMP_CLOUD_TELEMETRY_DATABASE_URL"]
        == "postgresql://telemetry:telemetry_dev@host.containers.internal:5433/telemetry"  # pragma: allowlist secret
    )
    assert (
        os.environ["BREAKERAMP_CLOUD_METRICS_PG_DSN"]
        == "postgresql://telemetry:telemetry_dev@host.containers.internal:5433/telemetry"  # pragma: allowlist secret
    )


def test_cloud_container_database_env_defaults_to_local_telemetry_when_context_has_no_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://main_user:main_pass@ep.example.com/neondb?sslmode=require")  # pragma: allowlist secret
    monkeypatch.delenv("AMPREALIZE_TELEMETRY_PG_DSN", raising=False)
    monkeypatch.delenv("TELEMETRY_DATABASE_URL", raising=False)
    monkeypatch.delenv("AMPREALIZE_METRICS_PG_DSN", raising=False)

    _set_cloud_container_database_env()

    assert os.environ["BREAKERAMP_CLOUD_DATABASE_URL"] == os.environ["DATABASE_URL"]
    assert (
        os.environ["BREAKERAMP_CLOUD_TELEMETRY_PG_DSN"]
        == "postgresql://telemetry:telemetry_dev@telemetry-db:5432/telemetry"  # pragma: allowlist secret
    )
    assert (
        os.environ["BREAKERAMP_CLOUD_TELEMETRY_DATABASE_URL"]
        == "postgresql://telemetry:telemetry_dev@telemetry-db:5432/telemetry"  # pragma: allowlist secret
    )
    assert (
        os.environ["BREAKERAMP_CLOUD_METRICS_PG_DSN"]
        == "postgresql://telemetry:telemetry_dev@telemetry-db:5432/telemetry"  # pragma: allowlist secret
    )
