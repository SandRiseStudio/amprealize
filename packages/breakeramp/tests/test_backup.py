"""Tests for backup / restore / validate logic.

These tests mock subprocess and filesystem operations to avoid needing
running Podman containers or real databases.
"""

import gzip
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from breakeramp.backup import (
    BACKUP_ROOT,
    DEFAULT_DB_CONTAINERS,
    _find_running_container,
    _ensure_backup_dir,
    _reset_database,
    validate_backup,
    backup_databases,
    restore_databases,
    list_backups,
    rotate_backups,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_SQL = b"""\
--
-- PostgreSQL database dump
--

SET statement_timeout = 0;
DROP TABLE IF EXISTS public.users;
CREATE TABLE public.users (id serial PRIMARY KEY, name text);
COPY public.users (id, name) FROM stdin;
1\tAlice
2\tBob
\\.
"""


@pytest.fixture()
def backup_dir(tmp_path):
    """A temporary backup directory with valid gzipped dumps."""
    bd = tmp_path / "2026-01-01T00-00-00_test"
    bd.mkdir()
    for target in DEFAULT_DB_CONTAINERS:
        (bd / f"{target['db_name']}.sql.gz").write_bytes(
            gzip.compress(SAMPLE_SQL)
        )
    return bd


@pytest.fixture()
def empty_backup_dir(tmp_path):
    """Backup dir with zero-byte dump files."""
    bd = tmp_path / "2026-01-01T00-00-00_empty"
    bd.mkdir()
    for target in DEFAULT_DB_CONTAINERS:
        (bd / f"{target['db_name']}.sql.gz").write_bytes(b"")
    return bd


@pytest.fixture()
def corrupt_backup_dir(tmp_path):
    """Backup dir with invalid gzip data."""
    bd = tmp_path / "2026-01-01T00-00-00_corrupt"
    bd.mkdir()
    for target in DEFAULT_DB_CONTAINERS:
        (bd / f"{target['db_name']}.sql.gz").write_bytes(b"not gzip")
    return bd


# ---------------------------------------------------------------------------
# _find_running_container
# ---------------------------------------------------------------------------

class TestFindRunningContainer:
    @patch("breakeramp.backup.subprocess.run")
    def test_finds_container(self, mock_run):
        mock_run.return_value = MagicMock(stdout="my-db-container\n")
        assert _find_running_container("db") == "my-db-container"

    @patch("breakeramp.backup.subprocess.run")
    def test_returns_none_when_empty(self, mock_run):
        mock_run.return_value = MagicMock(stdout="")
        assert _find_running_container("db") is None

    @patch("breakeramp.backup.subprocess.run", side_effect=FileNotFoundError)
    def test_returns_none_on_error(self, mock_run):
        assert _find_running_container("db") is None


# ---------------------------------------------------------------------------
# _reset_database
# ---------------------------------------------------------------------------

class TestResetDatabase:
    @patch("breakeramp.backup.subprocess.run")
    def test_success_returns_none(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        assert _reset_database("ctr", "mydb", "myuser") is None
        # Should have 3 calls: terminate, drop, create
        assert mock_run.call_count == 3

    @patch("breakeramp.backup.subprocess.run")
    def test_drop_failure(self, mock_run):
        # First call (terminate) OK, second call (drop) fails
        ok = MagicMock(returncode=0, stderr="")
        fail = MagicMock(returncode=1, stderr="ERROR: cannot drop")
        mock_run.side_effect = [ok, fail]
        err = _reset_database("ctr", "mydb", "myuser")
        assert err is not None
        assert "DROP failed" in err

    @patch("breakeramp.backup.subprocess.run")
    def test_create_failure(self, mock_run):
        ok = MagicMock(returncode=0, stderr="")
        fail = MagicMock(returncode=1, stderr="ERROR: create fail")
        mock_run.side_effect = [ok, ok, fail]
        err = _reset_database("ctr", "mydb", "myuser")
        assert err is not None
        assert "CREATE failed" in err

    @patch("breakeramp.backup.subprocess.run")
    def test_connects_to_postgres_db_as_pg_user(self, mock_run):
        """Verify we connect to 'postgres' DB as pg_user, not as role 'postgres'."""
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        _reset_database("ctr", "mydb", "appuser")
        for c in mock_run.call_args_list:
            args = c[0][0]
            # Every psql call should use -U appuser -d postgres
            if "psql" in args:
                assert "-U" in args
                u_idx = args.index("-U")
                assert args[u_idx + 1] == "appuser"
                assert "-d" in args
                d_idx = args.index("-d")
                assert args[d_idx + 1] == "postgres"


# ---------------------------------------------------------------------------
# validate_backup
# ---------------------------------------------------------------------------

class TestValidateBackup:
    @patch("breakeramp.backup.subprocess.run")
    @patch("breakeramp.backup._find_running_container", return_value="ctr")
    def test_valid_backup(self, mock_find, mock_run, backup_dir):
        mock_run.return_value = MagicMock(returncode=0)  # pg_isready
        result = validate_backup(backup_dir)
        assert result["ok"] is True
        assert len(result["errors"]) == 0
        assert len(result["checks"]) == len(DEFAULT_DB_CONTAINERS)

    def test_missing_directory(self, tmp_path):
        result = validate_backup(tmp_path / "nonexistent")
        assert result["ok"] is False
        assert "not found" in result["errors"][0]

    @patch("breakeramp.backup._find_running_container", return_value="ctr")
    def test_empty_file_rejected(self, mock_find, empty_backup_dir):
        result = validate_backup(empty_backup_dir)
        assert result["ok"] is False
        assert any("0 bytes" in e for e in result["errors"])

    @patch("breakeramp.backup._find_running_container", return_value="ctr")
    def test_corrupt_gzip_rejected(self, mock_find, corrupt_backup_dir):
        result = validate_backup(corrupt_backup_dir)
        assert result["ok"] is False
        assert any("decompression failed" in e for e in result["errors"])

    @patch("breakeramp.backup.subprocess.run")
    @patch("breakeramp.backup._find_running_container", return_value="ctr")
    def test_no_sql_markers_rejected(self, mock_find, mock_run, tmp_path):
        bd = tmp_path / "2026-01-01T00-00-00_bad"
        bd.mkdir()
        for target in DEFAULT_DB_CONTAINERS:
            (bd / f"{target['db_name']}.sql.gz").write_bytes(
                gzip.compress(b"-- just a comment, nothing useful\n" * 100)
            )
        result = validate_backup(bd)
        assert result["ok"] is False
        assert any("no CREATE/COPY/INSERT" in e for e in result["errors"])

    @patch("breakeramp.backup._find_running_container", return_value=None)
    def test_container_not_running(self, mock_find, backup_dir):
        result = validate_backup(backup_dir)
        assert result["ok"] is False
        assert any("container not running" in e for e in result["errors"])

    @patch("breakeramp.backup.subprocess.run")
    @patch("breakeramp.backup._find_running_container", return_value="ctr")
    def test_pg_not_ready(self, mock_find, mock_run, backup_dir):
        mock_run.return_value = MagicMock(returncode=2)  # pg_isready fail
        result = validate_backup(backup_dir)
        assert result["ok"] is False
        assert any("not accepting connections" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# backup_databases
# ---------------------------------------------------------------------------

class TestBackupDatabases:
    @patch("breakeramp.backup.validate_backup")
    @patch("breakeramp.backup._find_running_container", return_value="ctr")
    @patch("breakeramp.backup.subprocess.run")
    @patch("breakeramp.backup.BACKUP_ROOT")
    def test_success_includes_validation(
        self, mock_root, mock_run, mock_find, mock_validate, tmp_path
    ):
        mock_root.__truediv__ = lambda self, x: tmp_path / x
        mock_root.mkdir = MagicMock()
        # pg_dump succeeds, returns gzipped SQL
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=gzip.compress(SAMPLE_SQL),
            stderr=b"",
        )
        mock_validate.return_value = {"ok": True, "checks": ["ok"], "errors": []}

        result = backup_databases(tag="test")
        assert len(result["databases"]) == len(DEFAULT_DB_CONTAINERS)
        assert result.get("validated") is True
        mock_validate.assert_called_once()

    @patch("breakeramp.backup.validate_backup")
    @patch("breakeramp.backup._find_running_container", return_value="ctr")
    @patch("breakeramp.backup.subprocess.run")
    @patch("breakeramp.backup.BACKUP_ROOT")
    def test_validation_failure_shows_error(
        self, mock_root, mock_run, mock_find, mock_validate, tmp_path
    ):
        mock_root.__truediv__ = lambda self, x: tmp_path / x
        mock_root.mkdir = MagicMock()
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=gzip.compress(SAMPLE_SQL),
            stderr=b"",
        )
        mock_validate.return_value = {
            "ok": False,
            "checks": [],
            "errors": ["bad dump"],
        }

        result = backup_databases(tag="test")
        assert "Post-backup validation FAILED" in result["errors"][0]
        assert result.get("validated") is None


# ---------------------------------------------------------------------------
# restore_databases
# ---------------------------------------------------------------------------

class TestRestoreDatabases:
    @patch("breakeramp.backup.backup_databases")
    @patch("breakeramp.backup.subprocess.run")
    @patch("breakeramp.backup._find_running_container", return_value="ctr")
    @patch("breakeramp.backup.validate_backup")
    def test_preflight_failure_aborts(
        self, mock_validate, mock_find, mock_run, mock_backup, backup_dir
    ):
        mock_validate.return_value = {
            "ok": False,
            "checks": [],
            "errors": ["corrupt dump"],
        }
        result = restore_databases(backup_dir)
        assert "Pre-flight validation failed" in result["errors"][0]
        # No subprocess calls for restore (only validate may call some)
        mock_backup.assert_not_called()

    @patch("breakeramp.backup.backup_databases")
    @patch("breakeramp.backup.subprocess.run")
    @patch("breakeramp.backup._find_running_container", return_value="ctr")
    @patch("breakeramp.backup.validate_backup")
    def test_auto_backup_taken_before_restore(
        self, mock_validate, mock_find, mock_run, mock_backup, backup_dir
    ):
        mock_validate.return_value = {"ok": True, "checks": [], "errors": []}
        mock_run.return_value = MagicMock(returncode=0, stderr=b"")
        mock_backup.return_value = {
            "databases": ["db1"],
            "path": "/tmp/safety",
            "errors": [],
        }

        result = restore_databases(backup_dir, auto_backup=True)
        mock_backup.assert_called_once()
        assert result["safety_backup"] == "/tmp/safety"

    @patch("breakeramp.backup.backup_databases")
    @patch("breakeramp.backup.subprocess.run")
    @patch("breakeramp.backup._find_running_container", return_value="ctr")
    @patch("breakeramp.backup.validate_backup")
    def test_auto_backup_skippable(
        self, mock_validate, mock_find, mock_run, mock_backup, backup_dir
    ):
        mock_validate.return_value = {"ok": True, "checks": [], "errors": []}
        mock_run.return_value = MagicMock(returncode=0, stderr=b"")

        result = restore_databases(backup_dir, auto_backup=False)
        mock_backup.assert_not_called()
        assert result["safety_backup"] is None

    @patch("breakeramp.backup.backup_databases")
    @patch("breakeramp.backup._reset_database", return_value=None)
    @patch("breakeramp.backup.subprocess.run")
    @patch("breakeramp.backup._find_running_container", return_value="ctr")
    @patch("breakeramp.backup.validate_backup")
    def test_successful_restore(
        self, mock_validate, mock_find, mock_run, mock_reset, mock_backup,
        backup_dir,
    ):
        mock_validate.return_value = {"ok": True, "checks": [], "errors": []}
        mock_run.return_value = MagicMock(returncode=0, stderr=b"")
        mock_backup.return_value = {"databases": ["db"], "path": "/s", "errors": []}

        result = restore_databases(backup_dir)
        assert len(result["restored"]) == len(DEFAULT_DB_CONTAINERS)
        assert len(result["errors"]) == 0

    @patch("breakeramp.backup.backup_databases")
    @patch("breakeramp.backup._reset_database", return_value="DROP failed: busy")
    @patch("breakeramp.backup.subprocess.run")
    @patch("breakeramp.backup._find_running_container", return_value="ctr")
    @patch("breakeramp.backup.validate_backup")
    def test_reset_failure_reported(
        self, mock_validate, mock_find, mock_run, mock_reset, mock_backup,
        backup_dir,
    ):
        mock_validate.return_value = {"ok": True, "checks": [], "errors": []}
        mock_backup.return_value = {"databases": ["db"], "path": "/s", "errors": []}

        result = restore_databases(backup_dir)
        assert len(result["errors"]) == len(DEFAULT_DB_CONTAINERS)
        assert all("DROP failed" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# list_backups / rotate_backups
# ---------------------------------------------------------------------------

class TestListBackups:
    @patch("breakeramp.backup.BACKUP_ROOT")
    def test_empty_when_no_dir(self, mock_root, tmp_path):
        mock_root.exists.return_value = False
        assert list_backups() == []

    @patch("breakeramp.backup.BACKUP_ROOT")
    def test_returns_sorted(self, mock_root, tmp_path):
        root = tmp_path / "backups"
        root.mkdir()
        d1 = root / "2026-01-01T00-00-00_a"
        d2 = root / "2026-01-02T00-00-00_b"
        d1.mkdir()
        d2.mkdir()
        (d1 / "amprealize.sql.gz").write_bytes(gzip.compress(b"x"))
        (d2 / "amprealize.sql.gz").write_bytes(gzip.compress(b"x"))

        mock_root.exists.return_value = True
        mock_root.iterdir.return_value = [d1, d2]

        backups = list_backups()
        assert len(backups) == 2
        # Newest first
        assert backups[0]["tag"] == "b"


class TestRotateBackups:
    @patch("breakeramp.backup.BACKUP_ROOT")
    def test_removes_oldest(self, mock_root, tmp_path):
        root = tmp_path / "backups"
        root.mkdir()
        dirs = []
        for i in range(7):
            d = root / f"2026-01-0{i+1}T00-00-00_auto"
            d.mkdir()
            (d / "amprealize.sql.gz").write_bytes(b"x")
            dirs.append(d)

        mock_root.exists.return_value = True
        mock_root.iterdir.return_value = dirs

        removed = rotate_backups(tag="auto", keep=5)
        assert len(removed) == 2
