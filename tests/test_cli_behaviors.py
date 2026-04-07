import json
import os
from pathlib import Path

try:
    import psycopg2  # type: ignore[import-not-found]
except ImportError:
    psycopg2 = None

from pytest import CaptureFixture, MonkeyPatch, fixture

from amprealize import cli


@fixture(autouse=True)
def reset_cli_state(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    # Use test PostgreSQL database from environment if available
    # Falls back to SQLite if not configured
    test_behavior_dsn = os.getenv("AMPREALIZE_BEHAVIOR_PG_DSN")
    if not test_behavior_dsn:
        # Build DSN from test environment variables (set by run_tests.sh)
        host = os.getenv("AMPREALIZE_PG_HOST_BEHAVIOR", "localhost")
        port = os.getenv("AMPREALIZE_PG_PORT_BEHAVIOR", "6433")
        user = os.getenv("AMPREALIZE_PG_USER_BEHAVIOR", "amprealize_behavior")
        password = os.getenv("AMPREALIZE_PG_PASS_BEHAVIOR", "behavior_test_pass")
        db = os.getenv("AMPREALIZE_PG_DB_BEHAVIOR", "amprealize_behavior")
        test_behavior_dsn = f"postgresql://{user}:{password}@{host}:{port}/{db}"

    monkeypatch.setenv("AMPREALIZE_BEHAVIOR_PG_DSN", test_behavior_dsn)
    monkeypatch.setenv("AMPREALIZE_BEHAVIOR_DB_PATH", str(tmp_path / "behaviors.db"))
    cli._reset_action_state_for_testing()

    # Clean PostgreSQL tables if using PostgreSQL backend
    if test_behavior_dsn and test_behavior_dsn.startswith("postgresql://"):
        try:
            from conftest import safe_truncate
            safe_truncate(test_behavior_dsn, ["behavior_versions", "behaviors"])
        except Exception:
            # If truncation fails, tests may see stale data but will continue
            pass


def _filter_progress_bar_output(stderr: str) -> str:
    """Filter out progress bar output from sentence-transformers/tqdm.

    Progress bars write to stderr but are not errors. They contain patterns like:
    - "Batches: 100%|..."
    - ANSI escape sequences for cursor movement
    - Percentage indicators
    """
    import re
    lines = stderr.split('\n')
    filtered = []
    for line in lines:
        # Skip progress bar lines (contain percentage or batch indicators)
        if re.search(r'Batches?:?\s*\d*%|\|.*\||\[\d+/\d+\]', line):
            continue
        # Skip ANSI escape sequences used by progress bars
        if re.search(r'\x1b\[[0-9;]*[mK]', line):
            continue
        # Skip empty lines that result from progress bar cleanup
        if line.strip() == '':
            continue
        filtered.append(line)
    return '\n'.join(filtered)


def _run_cli(args: list[str], capsys: CaptureFixture[str]) -> tuple[int, str, str]:
    exit_code = cli.main(args)
    captured = capsys.readouterr()
    # Filter progress bar output from stderr (not actual errors)
    filtered_err = _filter_progress_bar_output(captured.err)
    return exit_code, captured.out, filtered_err


def test_behaviors_create_update_and_query(capsys: CaptureFixture[str]) -> None:
    exit_code, out, err = _run_cli(
        [
            "behaviors",
            "create",
            "--name",
            "behavior_test_cli",
            "--description",
            "Initial description",
            "--instruction",
            "Follow the initial draft",
            "--role",
            "STRATEGIST",
            "--tag",
            "cli",
            "--keyword",
            "testing",
            "--format",
            "json",
        ],
        capsys,
    )
    assert exit_code == 0
    assert err == ""
    payload = json.loads(out)
    behavior = payload["behavior"]
    versions = payload["versions"]
    assert behavior["name"] == "behavior_test_cli"
    assert versions[0]["status"] == "DRAFT"
    behavior_id = behavior["behavior_id"]

    exit_code, out, err = _run_cli(
        [
            "behaviors",
            "update",
            behavior_id,
            "--version",
            "1.0.0",
            "--description",
            "Updated description",
            "--tag",
            "cli",
            "--tag",
            "updated",
            "--keyword",
            "testing",
            "--keyword",
            "cli",
            "--format",
            "json",
        ],
        capsys,
    )
    assert exit_code == 0
    assert err == ""
    updated_payload = json.loads(out)
    assert updated_payload["behavior"]["description"] == "Updated description"
    updated_versions = updated_payload["versions"]
    assert updated_versions[0]["trigger_keywords"] == ["testing", "cli"]
    assert set(updated_versions[0]["metadata"].keys()) == set()

    exit_code, out, err = _run_cli(
        ["behaviors", "list", "--format", "json"],
        capsys,
    )
    assert exit_code == 0
    assert err == ""
    listing = json.loads(out)
    assert any(item["behavior"]["behavior_id"] == behavior_id for item in listing)

    exit_code, out, err = _run_cli(
        [
            "behaviors",
            "search",
            "--query",
            "behavior_test_cli",
            "--format",
            "json",
        ],
        capsys,
    )
    assert exit_code == 0
    assert err == ""
    search_results = json.loads(out)
    assert search_results
    assert search_results[0]["behavior"]["behavior_id"] == behavior_id

    exit_code, out, err = _run_cli(
        [
            "behaviors",
            "get",
            behavior_id,
            "--format",
            "json",
        ],
        capsys,
    )
    assert exit_code == 0
    assert err == ""
    detail = json.loads(out)
    assert detail["behavior"]["behavior_id"] == behavior_id
    assert len(detail["versions"]) == 1


def test_behaviors_submit_approve_deprecate_and_delete(capsys: CaptureFixture[str]) -> None:
    exit_code, out, err = _run_cli(
        [
            "behaviors",
            "create",
            "--name",
            "behavior_lifecycle_cli",
            "--description",
            "Lifecycle behavior",
            "--instruction",
            "Draft behavior instructions",
            "--role",
            "STRATEGIST",
            "--format",
            "json",
        ],
        capsys,
    )
    assert exit_code == 0
    assert err == ""
    payload = json.loads(out)
    behavior_id = payload["behavior"]["behavior_id"]

    exit_code, out, err = _run_cli(
        [
            "behaviors",
            "submit",
            behavior_id,
            "--version",
            "1.0.0",
            "--format",
            "json",
        ],
        capsys,
    )
    assert exit_code == 0
    assert err == ""
    submitted = json.loads(out)
    assert submitted["versions"][0]["status"] == "IN_REVIEW"

    exit_code, out, err = _run_cli(
        [
            "behaviors",
            "approve",
            behavior_id,
            "--version",
            "1.0.0",
            "--effective-from",
            "2024-01-01T00:00:00Z",
            "--format",
            "json",
        ],
        capsys,
    )
    assert exit_code == 0
    assert err == ""
    approved = json.loads(out)
    assert approved["versions"][0]["status"] == "APPROVED"

    exit_code, out, err = _run_cli(
        [
            "behaviors",
            "deprecate",
            behavior_id,
            "--version",
            "1.0.0",
            "--effective-to",
            "2025-01-01T00:00:00Z",
            "--format",
            "json",
        ],
        capsys,
    )
    assert exit_code == 0
    assert err == ""
    deprecated = json.loads(out)
    assert deprecated["versions"][0]["status"] == "DEPRECATED"

    exit_code, out, err = _run_cli(
        [
            "behaviors",
            "get",
            behavior_id,
            "--version",
            "1.0.0",
            "--format",
            "json",
        ],
        capsys,
    )
    assert exit_code == 0
    assert err == ""
    detail = json.loads(out)
    assert detail["versions"][0]["status"] == "DEPRECATED"

    exit_code, out, err = _run_cli(
        [
            "behaviors",
            "create",
            "--name",
            "behavior_to_delete",
            "--description",
            "Temporary draft",
            "--instruction",
            "Temporary instruction",
            "--role",
            "STRATEGIST",
            "--format",
            "json",
        ],
        capsys,
    )
    assert exit_code == 0
    delete_target = json.loads(out)["behavior"]["behavior_id"]

    exit_code, out, err = _run_cli(
        [
            "behaviors",
            "delete-draft",
            delete_target,
            "--version",
            "1.0.0",
        ],
        capsys,
    )
    assert exit_code == 0
    assert err == ""
    assert f"Deleted draft version 1.0.0 for behavior {delete_target}" in out

    exit_code, out, err = _run_cli(
        ["behaviors", "list", "--format", "json", "--status", "DRAFT"],
        capsys,
    )
    assert exit_code == 0
    remaining = json.loads(out)
    assert all(item["behavior"]["behavior_id"] != delete_target for item in remaining)
