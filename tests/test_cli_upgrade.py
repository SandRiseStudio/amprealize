"""Tests for the ``amprealize upgrade`` CLI command (edition transitions)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from pytest import CaptureFixture, MonkeyPatch

from amprealize import cli
from amprealize.edition import Edition, _VALID_TRANSITIONS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_cli(args: list[str], capsys: CaptureFixture[str]) -> tuple[int, str, str]:
    try:
        exit_code = cli.main(args)
    except SystemExit as exc:
        exit_code = exc.code if isinstance(exc.code, int) else 1
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def _extract_json(text: str) -> dict:
    """Extract the first JSON object from mixed text output."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("{"):
            return json.loads(stripped)
    # Try multiline JSON block
    import re
    m = re.search(r"\{[^}]+\}", text, re.DOTALL)
    if m:
        return json.loads(m.group())
    raise ValueError(f"No JSON found in output: {text[:200]}")


# ---------------------------------------------------------------------------
# Same-edition no-op
# ---------------------------------------------------------------------------


def test_upgrade_same_edition_is_noop(capsys: CaptureFixture[str]) -> None:
    """Upgrading to the already-running edition exits 0 with nothing-to-do."""
    rc, out, _ = _run_cli(["upgrade", "--to", "oss"], capsys)
    assert rc == 0
    assert "nothing to do" in out.lower() or "Already running" in out


def test_upgrade_same_edition_json(capsys: CaptureFixture[str]) -> None:
    rc, out, _ = _run_cli(["upgrade", "--to", "oss", "--format", "json"], capsys)
    assert rc == 0
    data = _extract_json(out)
    assert data["status"] == "no_change"
    assert data["edition"] == "oss"


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------


def test_upgrade_dry_run_shows_plan(capsys: CaptureFixture[str]) -> None:
    """--dry-run shows planned steps without applying."""
    with patch("amprealize.edition.detect_edition", return_value=Edition.OSS):
        with patch.dict("sys.modules", {"amprealize_enterprise": __import__("types")}):
            rc, out, _ = _run_cli(
                ["upgrade", "--to", "enterprise_starter", "--dry-run"], capsys
            )
    assert rc == 0
    assert "Dry run" in out or "dry_run" in out
    assert "run_enterprise_migrations" in out or "switch_edition" in out


def test_upgrade_dry_run_json(capsys: CaptureFixture[str]) -> None:
    with patch("amprealize.edition.detect_edition", return_value=Edition.OSS):
        with patch.dict("sys.modules", {"amprealize_enterprise": __import__("types")}):
            rc, out, _ = _run_cli(
                ["upgrade", "--to", "enterprise_starter", "--dry-run", "--format", "json"],
                capsys,
            )
    assert rc == 0
    # JSON is mixed with banner text — extract the JSON block
    json_lines = []
    capture = False
    for line in out.splitlines():
        stripped = line.strip()
        if stripped.startswith("{"):
            capture = True
        if capture:
            json_lines.append(line)
        if capture and stripped.startswith("}"):
            break
    data = json.loads("\n".join(json_lines))
    assert data["status"] == "dry_run"
    assert data["current"] == "oss"
    assert data["target"] == "enterprise_starter"
    assert "switch_edition" in data["steps"]


def test_upgrade_dry_run_skip_backup_removes_step(capsys: CaptureFixture[str]) -> None:
    with patch("amprealize.edition.detect_edition", return_value=Edition.OSS):
        with patch.dict("sys.modules", {"amprealize_enterprise": __import__("types")}):
            rc, out, _ = _run_cli(
                [
                    "upgrade", "--to", "enterprise_starter",
                    "--dry-run", "--skip-backup", "--format", "json",
                ],
                capsys,
            )
    assert rc == 0
    json_lines = []
    capture = False
    for line in out.splitlines():
        stripped = line.strip()
        if stripped.startswith("{"):
            capture = True
        if capture:
            json_lines.append(line)
        if capture and stripped.startswith("}"):
            break
    data = json.loads("\n".join(json_lines))
    assert "backup_database" not in data["steps"]


# ---------------------------------------------------------------------------
# Invalid edition
# ---------------------------------------------------------------------------


def test_upgrade_unknown_edition(capsys: CaptureFixture[str]) -> None:
    rc, _, err = _run_cli(["upgrade", "--to", "platinum"], capsys)
    # argparse rejects invalid choices before reaching the handler
    assert rc != 0


# ---------------------------------------------------------------------------
# Downgrade blocked without --force
# ---------------------------------------------------------------------------


def test_downgrade_blocked_without_force(capsys: CaptureFixture[str]) -> None:
    """Downgrade from Starter→OSS requires --force."""
    with patch(
        "amprealize.edition.detect_edition",
        return_value=Edition.ENTERPRISE_STARTER,
    ):
        rc, out, err = _run_cli(["upgrade", "--to", "oss"], capsys)
    assert rc == 1
    combined = out + err
    assert "downgrade" in combined.lower() or "--force" in combined


def test_downgrade_blocked_json(capsys: CaptureFixture[str]) -> None:
    with patch(
        "amprealize.edition.detect_edition",
        return_value=Edition.ENTERPRISE_STARTER,
    ):
        rc, out, err = _run_cli(
            ["upgrade", "--to", "oss", "--format", "json"], capsys
        )
    assert rc == 1
    # JSON may be in stdout or stderr depending on handler
    combined = out + err
    assert "downgrade_requires_force" in combined


# ---------------------------------------------------------------------------
# Enterprise package not installed
# ---------------------------------------------------------------------------


def test_upgrade_blocks_if_enterprise_package_missing(
    capsys: CaptureFixture[str],
) -> None:
    """Upgrade to enterprise fails if amprealize_enterprise isn't installed."""
    with patch("amprealize.edition.detect_edition", return_value=Edition.OSS):
        # Ensure amprealize_enterprise import fails
        import sys
        sys.modules.pop("amprealize_enterprise", None)
        with patch.dict("sys.modules", {"amprealize_enterprise": None}):
            rc, out, err = _run_cli(
                ["upgrade", "--to", "enterprise_starter"], capsys
            )
    assert rc == 1
    combined = out + err
    assert "amprealize-enterprise" in combined or "enterprise_package_missing" in combined


# ---------------------------------------------------------------------------
# Successful upgrade (end-to-end with mocks)
# ---------------------------------------------------------------------------


def test_upgrade_oss_to_starter_e2e(
    capsys: CaptureFixture[str], tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Full upgrade path OSS→Starter with mocked enterprise module."""
    # Point edition state file to tmp
    state_dir = tmp_path / ".amprealize"
    monkeypatch.setattr("amprealize.cli.Path.home", lambda: tmp_path)

    # Mock detect_edition to return OSS initially
    with patch("amprealize.edition.detect_edition", return_value=Edition.OSS):
        # Mock enterprise package as importable
        import types
        fake_enterprise = types.ModuleType("amprealize_enterprise")
        fake_migrations = types.ModuleType("amprealize_enterprise.migrations")
        fake_migrations.run_enterprise_migrations = lambda dry_run=False: None  # type: ignore[attr-defined]
        with patch.dict("sys.modules", {
            "amprealize_enterprise": fake_enterprise,
            "amprealize_enterprise.migrations": fake_migrations,
        }):
            # Skip backup (no DATABASE_URL), skip subprocess calls
            monkeypatch.delenv("DATABASE_URL", raising=False)
            rc, out, err = _run_cli(
                ["upgrade", "--to", "enterprise_starter", "--skip-backup"],
                capsys,
            )

    assert rc == 0
    combined = out + err
    assert "enterprise_starter" in combined

    # Verify the edition state file was written
    edition_file = state_dir / "edition"
    assert edition_file.exists()
    assert edition_file.read_text() == "enterprise_starter"


def test_upgrade_starter_to_premium_e2e(
    capsys: CaptureFixture[str], tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Upgrade Starter→Premium."""
    monkeypatch.setattr("amprealize.cli.Path.home", lambda: tmp_path)

    with patch(
        "amprealize.edition.detect_edition",
        return_value=Edition.ENTERPRISE_STARTER,
    ):
        import types
        fake_enterprise = types.ModuleType("amprealize_enterprise")
        fake_migrations = types.ModuleType("amprealize_enterprise.migrations")
        fake_migrations.run_enterprise_migrations = lambda dry_run=False: None  # type: ignore[attr-defined]
        with patch.dict("sys.modules", {
            "amprealize_enterprise": fake_enterprise,
            "amprealize_enterprise.migrations": fake_migrations,
        }):
            monkeypatch.delenv("DATABASE_URL", raising=False)
            rc, out, _ = _run_cli(
                ["upgrade", "--to", "enterprise_premium", "--skip-backup"],
                capsys,
            )

    assert rc == 0
    assert "enterprise_premium" in out
    edition_file = tmp_path / ".amprealize" / "edition"
    assert edition_file.read_text() == "enterprise_premium"


def test_downgrade_with_force_succeeds(
    capsys: CaptureFixture[str], tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Downgrade Starter→OSS with --force proceeds."""
    monkeypatch.setattr("amprealize.cli.Path.home", lambda: tmp_path)

    with patch(
        "amprealize.edition.detect_edition",
        return_value=Edition.ENTERPRISE_STARTER,
    ):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        rc, out, _ = _run_cli(
            ["upgrade", "--to", "oss", "--force", "--skip-backup"],
            capsys,
        )

    assert rc == 0
    edition_file = tmp_path / ".amprealize" / "edition"
    assert edition_file.read_text() == "oss"


# ---------------------------------------------------------------------------
# Transition table coverage
# ---------------------------------------------------------------------------


def test_all_valid_transitions_have_both_directions() -> None:
    """Every forward transition has a matching reverse transition."""
    for (from_ed, to_ed) in _VALID_TRANSITIONS:
        reverse = (to_ed, from_ed)
        assert reverse in _VALID_TRANSITIONS, (
            f"Missing reverse transition for {from_ed.value} → {to_ed.value}"
        )


def test_features_gained_lost_are_symmetric() -> None:
    """Features gained in upgrade == features lost in downgrade."""
    for (from_ed, to_ed), transition in _VALID_TRANSITIONS.items():
        reverse = _VALID_TRANSITIONS.get((to_ed, from_ed))
        if reverse is None:
            continue
        assert set(transition.features_gained) == set(reverse.features_lost), (
            f"{from_ed.value}→{to_ed.value}: gained={transition.features_gained} "
            f"but reverse lost={reverse.features_lost}"
        )


def test_data_preserved_for_all_transitions() -> None:
    """All defined transitions preserve data (no destructive migrations)."""
    for key, transition in _VALID_TRANSITIONS.items():
        assert transition.data_preserved, (
            f"{key[0].value}→{key[1].value} has data_preserved=False"
        )
