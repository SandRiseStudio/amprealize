from pathlib import Path
from unittest.mock import MagicMock

import pytest

from amprealize.breakeramp import BreakerAmpService


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


def test_configure_respects_force_flag(breakeramp_service: BreakerAmpService, tmp_path: Path) -> None:
    config_dir = tmp_path / "config" / "breakeramp"
    breakeramp_service.configure(config_dir=config_dir, include_blueprints=False)

    # Without force, should skip (not raise)
    result = breakeramp_service.configure(config_dir=config_dir)
    assert result["environment_status"] == "skipped"

    # With force, should overwrite
    result = breakeramp_service.configure(config_dir=config_dir, force=True)
    assert result["environment_status"] == "overwritten"
