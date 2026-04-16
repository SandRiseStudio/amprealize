"""Database backup and restore for BreakerAmp-managed PostgreSQL containers.

Uses pg_dump/pg_restore (logical backups) executed inside running containers
via `podman exec`. Designed for local development — portable, version-tolerant,
and survives Podman machine rebuilds.

Also supports cloud database backup/restore via direct DSN connection when
no local containers are running but DATABASE_URL is available (e.g., Neon).

Backup location: ~/.amprealize/backups/<timestamp>/
"""

import gzip
import os
import subprocess
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BACKUP_ROOT = Path.home() / ".amprealize" / "backups"
MAX_AUTO_BACKUPS = 5

# Container name patterns → (db_name, pg_user) for pg_dump
DEFAULT_DB_CONTAINERS: List[Dict[str, str]] = [
    {
        "container_pattern": "amprealize-db",
        "db_name": "amprealize",
        "pg_user": "amprealize",
        "label": "amprealize-db (main)",
    },
    {
        "container_pattern": "telemetry-db",
        "db_name": "telemetry",
        "pg_user": "telemetry",
        "label": "telemetry-db (TimescaleDB)",
    },
]

# Environment variables that may contain cloud DSNs
# Checked in order; first non-empty DSN is used
CLOUD_DSN_ENV_VARS = [
    "DATABASE_URL",
    "AMPREALIZE_PG_DSN",
    "AMPREALIZE_MAIN_PG_DSN",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_running_container(pattern: str) -> Optional[str]:
    """Find a running container whose name contains *pattern*."""
    try:
        result = subprocess.run(
            ["podman", "ps", "--format", "{{.Names}}", "--filter", f"name={pattern}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        for name in result.stdout.strip().splitlines():
            name = name.strip()
            if name:
                return name
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _ensure_backup_dir(tag: str = "auto") -> Path:
    """Create and return a timestamped backup directory.

    Returns e.g. ``~/.amprealize/backups/2025-07-15T10-30-00_auto/``
    """
    ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    backup_dir = BACKUP_ROOT / f"{ts}_{tag}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def _reset_database(
    container: str, db_name: str, pg_user: str,
) -> Optional[str]:
    """Drop and recreate a database so restore starts from a clean slate.

    Terminates active connections, drops the database, and recreates it
    with the original owner.  Connects to the ``postgres`` maintenance
    database as ``pg_user`` (who must have superuser or createdb privileges).

    Returns ``None`` on success, or an error string on failure.
    """
    # Terminate other connections so DROP DATABASE can proceed
    subprocess.run(
        [
            "podman", "exec", container,
            "psql", "-U", pg_user, "-d", "postgres", "-c",
            f"SELECT pg_terminate_backend(pid) "
            f"FROM pg_stat_activity "
            f"WHERE datname = '{db_name}' AND pid <> pg_backend_pid();",
        ],
        capture_output=True,
        timeout=15,
    )

    # Drop
    proc = subprocess.run(
        [
            "podman", "exec", container,
            "psql", "-U", pg_user, "-d", "postgres", "-c",
            f'DROP DATABASE IF EXISTS "{db_name}";',
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc.returncode != 0 and "ERROR" in (proc.stderr or ""):
        return f"DROP failed: {proc.stderr.strip()[:200]}"

    # Recreate with original owner
    proc = subprocess.run(
        [
            "podman", "exec", container,
            "psql", "-U", pg_user, "-d", "postgres", "-c",
            f'CREATE DATABASE "{db_name}" OWNER "{pg_user}";',
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc.returncode != 0:
        return f"CREATE failed: {proc.stderr.strip()[:200]}"

    return None


def _get_cloud_dsn() -> Optional[str]:
    """Return the first non-empty cloud DSN from environment variables."""
    for env_var in CLOUD_DSN_ENV_VARS:
        dsn = os.environ.get(env_var, "").strip()
        if dsn and _is_cloud_dsn(dsn):
            return dsn
    return None


def _is_cloud_dsn(dsn: str) -> bool:
    """Return True if the DSN hostname is not a local address."""
    try:
        host = (urlparse(dsn).hostname or "").lower()
        return bool(host) and host not in ("localhost", "127.0.0.1", "::1")
    except Exception:
        return False


def _parse_dsn(dsn: str) -> Dict[str, str]:
    """Parse a PostgreSQL DSN into components for pg_dump/psql commands."""
    parsed = urlparse(dsn)
    return {
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port or 5432),
        "dbname": (parsed.path or "/").lstrip("/") or "postgres",
        "user": parsed.username or "",
        "password": parsed.password or "",
    }


def _backup_cloud_database(
    dsn: str,
    dump_file: Path,
    label: str = "cloud",
) -> Dict[str, Any]:
    """Backup a cloud database via direct pg_dump connection.

    Returns ``{"ok": True/False, "message": str, "size_kb": float}``.
    """
    params = _parse_dsn(dsn)
    env = os.environ.copy()
    env["PGPASSWORD"] = params["password"]

    try:
        # pg_dump → gzip to file
        proc = subprocess.run(
            [
                "pg_dump",
                "-h", params["host"],
                "-p", params["port"],
                "-U", params["user"],
                "-d", params["dbname"],
                "--no-owner", "--no-acl", "--clean", "--if-exists",
            ],
            capture_output=True,
            timeout=600,  # 10 min ceiling for cloud latency
            env=env,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", errors="replace").strip()
            return {
                "ok": False,
                "message": f"{label}: pg_dump failed — {stderr[:300]}",
                "size_kb": 0,
            }

        dump_file.write_bytes(gzip.compress(proc.stdout))
        size_kb = dump_file.stat().st_size / 1024
        return {
            "ok": True,
            "message": f"{label} → {dump_file.name} ({size_kb:.1f} KB)",
            "size_kb": size_kb,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": f"{label}: pg_dump timed out", "size_kb": 0}
    except OSError as exc:
        return {"ok": False, "message": f"{label}: {exc}", "size_kb": 0}


def _restore_cloud_database(
    dsn: str,
    dump_file: Path,
    label: str = "cloud",
    truncate_schemas: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Restore a backup to a cloud database via direct psql connection.

    When *truncate_schemas* is provided, TRUNCATE TABLE ... CASCADE is run
    for all tables in those schemas before restoring. This avoids issues
    with foreign key constraints when restoring subsets of data.

    Returns ``{"ok": True/False, "message": str}``.
    """
    params = _parse_dsn(dsn)
    env = os.environ.copy()
    env["PGPASSWORD"] = params["password"]

    # Pre-truncate specified schemas if requested
    if truncate_schemas:
        for schema in truncate_schemas:
            try:
                # Get all tables in schema
                list_proc = subprocess.run(
                    [
                        "psql",
                        "-h", params["host"],
                        "-p", params["port"],
                        "-U", params["user"],
                        "-d", params["dbname"],
                        "-t", "-A", "-c",
                        f"SELECT tablename FROM pg_tables WHERE schemaname = '{schema}';",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    env=env,
                )
                tables = [t.strip() for t in list_proc.stdout.strip().split("\n") if t.strip()]
                if tables:
                    truncate_sql = ", ".join(f'"{schema}"."{t}"' for t in tables)
                    subprocess.run(
                        [
                            "psql",
                            "-h", params["host"],
                            "-p", params["port"],
                            "-U", params["user"],
                            "-d", params["dbname"],
                            "-c", f"TRUNCATE TABLE {truncate_sql} CASCADE;",
                        ],
                        capture_output=True,
                        timeout=120,
                        env=env,
                    )
            except Exception:
                pass  # Non-fatal — restore will handle it

    try:
        # gunzip | psql
        raw_sql = gzip.decompress(dump_file.read_bytes())
        proc = subprocess.run(
            [
                "psql",
                "-h", params["host"],
                "-p", params["port"],
                "-U", params["user"],
                "-d", params["dbname"],
            ],
            input=raw_sql,
            capture_output=True,
            timeout=600,
            env=env,
        )
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0 and "ERROR" in stderr:
            return {"ok": False, "message": f"{label}: restore failed — {stderr[:300]}"}
        return {"ok": True, "message": f"{label}: restored from {dump_file.name}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": f"{label}: restore timed out"}
    except (gzip.BadGzipFile, OSError) as exc:
        return {"ok": False, "message": f"{label}: {exc}"}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_backup(
    backup_path: Path,
    containers: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Pre-flight check: verify a backup is likely to restore successfully.

    Checks performed per database dump file:
    1. File exists and is non-empty
    2. File decompresses without gzip errors
    3. Decompressed SQL contains expected structural markers
       (CREATE/COPY statements)
    4. Target container is running and PostgreSQL is accepting connections

    Returns ``{"ok": True/False, "checks": [...], "errors": [...]}``.
    Call this *before* ``restore_databases`` to avoid dropping data
    when the backup is corrupt or incomplete.
    """
    targets = containers or DEFAULT_DB_CONTAINERS
    result: Dict[str, Any] = {"ok": True, "checks": [], "errors": []}

    if not backup_path.is_dir():
        result["ok"] = False
        result["errors"].append(f"Backup directory not found: {backup_path}")
        return result

    for target in targets:
        label = target["label"]
        dump_file = backup_path / f"{target['db_name']}.sql.gz"

        # 1. File exists and is non-empty
        if not dump_file.exists():
            result["checks"].append(f"{label}: dump file missing (skipped)")
            continue
        size = dump_file.stat().st_size
        if size == 0:
            result["ok"] = False
            result["errors"].append(f"{label}: dump file is 0 bytes")
            continue

        # 2. Decompress and inspect SQL content
        try:
            raw = gzip.decompress(dump_file.read_bytes())
        except (gzip.BadGzipFile, OSError) as exc:
            result["ok"] = False
            result["errors"].append(
                f"{label}: gzip decompression failed — {exc}"
            )
            continue

        if len(raw) < 100:
            result["ok"] = False
            result["errors"].append(
                f"{label}: decompressed SQL is only {len(raw)} bytes"
            )
            continue

        # 3. Look for structural SQL markers
        # Check first 64KB for speed — enough to find the header/schema section
        head = raw[:65536].decode("utf-8", errors="replace")
        has_structure = (
            "CREATE" in head or "COPY" in head or "INSERT" in head
        )
        if not has_structure:
            result["ok"] = False
            result["errors"].append(
                f"{label}: no CREATE/COPY/INSERT found in dump header — "
                f"file may be corrupt"
            )
            continue

        # 4. Target container is running and PG is accepting connections
        container = _find_running_container(target["container_pattern"])
        if not container:
            result["ok"] = False
            result["errors"].append(f"{label}: container not running")
            continue

        try:
            proc = subprocess.run(
                [
                    "podman", "exec", container,
                    "pg_isready", "-U", target["pg_user"],
                ],
                capture_output=True,
                timeout=10,
            )
            if proc.returncode != 0:
                result["ok"] = False
                result["errors"].append(
                    f"{label}: PostgreSQL not accepting connections"
                )
                continue
        except (subprocess.TimeoutExpired, FileNotFoundError):
            result["ok"] = False
            result["errors"].append(f"{label}: pg_isready check timed out")
            continue

        size_kb = size / 1024
        sql_mb = len(raw) / (1024 * 1024)
        result["checks"].append(
            f"{label}: OK ({size_kb:.0f} KB gz, {sql_mb:.1f} MB SQL, "
            f"container {container[:30]}… ready)"
        )

    return result


# ---------------------------------------------------------------------------
# Core: backup / restore / list / rotate
# ---------------------------------------------------------------------------

def backup_databases(
    tag: str = "auto",
    containers: Optional[List[Dict[str, str]]] = None,
    quiet: bool = False,
    allow_cloud: bool = True,
) -> Dict[str, Any]:
    """Dump every reachable database to ``~/.amprealize/backups/<ts>_<tag>/``.

    When *allow_cloud* is True (default) and no local containers are running,
    attempts to backup from cloud DSN (DATABASE_URL or similar) if available.

    Returns a dict with ``path``, ``databases`` (list of what was backed up),
    and ``errors`` (list of failures).
    """
    targets = containers or DEFAULT_DB_CONTAINERS
    backup_dir = _ensure_backup_dir(tag)

    result: Dict[str, Any] = {
        "path": str(backup_dir),
        "databases": [],
        "errors": [],
        "skipped": [],
        "cloud": False,
    }

    # Track if any container is running (for cloud fallback)
    any_container_running = False

    for target in targets:
        container = _find_running_container(target["container_pattern"])
        if not container:
            result["skipped"].append(
                f"{target['label']}: container not running"
            )
            continue

        any_container_running = True
        dump_file = backup_dir / f"{target['db_name']}.sql.gz"
        try:
            # pg_dump → gzip inside the container, stream to host file
            proc = subprocess.run(
                [
                    "podman", "exec", container,
                    "bash", "-c",
                    f"pg_dump -U {target['pg_user']} -d {target['db_name']}"
                    f" --no-owner --no-acl --clean --if-exists | gzip",
                ],
                capture_output=True,
                timeout=300,  # 5 min ceiling
            )
            if proc.returncode != 0:
                stderr = proc.stderr.decode("utf-8", errors="replace").strip()
                result["errors"].append(f"{target['label']}: {stderr}")
                continue

            dump_file.write_bytes(proc.stdout)
            size_kb = dump_file.stat().st_size / 1024
            result["databases"].append(
                f"{target['label']} → {dump_file.name} ({size_kb:.1f} KB)"
            )
        except subprocess.TimeoutExpired:
            result["errors"].append(f"{target['label']}: pg_dump timed out")
        except OSError as exc:
            result["errors"].append(f"{target['label']}: {exc}")

    # Cloud fallback: backup from DATABASE_URL when no containers are running
    if allow_cloud and not any_container_running:
        cloud_dsn = _get_cloud_dsn()
        if cloud_dsn:
            dump_file = backup_dir / "cloud.sql.gz"
            cloud_result = _backup_cloud_database(cloud_dsn, dump_file, label="cloud-db")
            if cloud_result["ok"]:
                result["databases"].append(cloud_result["message"])
                result["cloud"] = True
            else:
                result["errors"].append(cloud_result["message"])

    # Post-backup validation — verify what we just wrote is restorable
    # Skip validation for cloud backups (no container to validate against)
    if result["databases"] and not result["errors"] and not result.get("cloud"):
        check = validate_backup(backup_dir)
        if not check["ok"]:
            result["errors"].append(
                "Post-backup validation FAILED — backup may be unusable"
            )
            result["errors"].extend(check["errors"])
        else:
            result["validated"] = True

    return result


def restore_databases(
    backup_path: Path,
    containers: Optional[List[Dict[str, str]]] = None,
    auto_backup: bool = True,
    to_cloud: bool = False,
    cloud_dsn: Optional[str] = None,
) -> Dict[str, Any]:
    """Restore databases from a backup directory.

    Each ``<db_name>.sql.gz`` in *backup_path* is gunzipped and piped into
    ``psql`` inside the matching container.

    When *to_cloud* is True, restores to a cloud database instead of containers.
    Uses *cloud_dsn* if provided, otherwise reads from environment.

    When *auto_backup* is ``True`` (the default), a safety snapshot is taken
    before any database is dropped.  This ensures you can always recover the
    previous state even if the restore itself goes wrong.
    """
    targets = containers or DEFAULT_DB_CONTAINERS

    result: Dict[str, Any] = {
        "path": str(backup_path),
        "restored": [],
        "errors": [],
        "skipped": [],
        "safety_backup": None,
    }

    if not backup_path.is_dir():
        result["errors"].append(f"Backup directory not found: {backup_path}")
        return result

    # --- CLOUD RESTORE PATH ---
    if to_cloud:
        dsn = cloud_dsn or _get_cloud_dsn()
        if not dsn:
            result["errors"].append(
                "Cloud restore requested but no DSN available "
                "(set DATABASE_URL or pass --to-cloud-dsn)"
            )
            return result

        # Find the dump file — could be cloud.sql.gz or amprealize.sql.gz
        dump_file = backup_path / "cloud.sql.gz"
        if not dump_file.exists():
            dump_file = backup_path / "amprealize.sql.gz"
        if not dump_file.exists():
            # Try any .sql.gz file
            candidates = list(backup_path.glob("*.sql.gz"))
            if candidates:
                dump_file = candidates[0]
            else:
                result["errors"].append(
                    f"No .sql.gz files found in {backup_path}"
                )
                return result

        # Safety backup before cloud restore (if auto_backup and DSN is available)
        if auto_backup:
            safety = backup_databases(tag="pre-cloud-restore", allow_cloud=True, quiet=True)
            if safety["databases"]:
                result["safety_backup"] = safety["path"]

        cloud_result = _restore_cloud_database(dsn, dump_file, label="cloud-db")
        if cloud_result["ok"]:
            result["restored"].append(cloud_result["message"])
            result["cloud"] = True
        else:
            result["errors"].append(cloud_result["message"])
        return result

    # --- CONTAINER RESTORE PATH ---
    # Pre-flight: validate backup integrity before touching any database
    preflight = validate_backup(backup_path, targets)
    if not preflight["ok"]:
        result["errors"].append("Pre-flight validation failed — no databases were modified")
        result["errors"].extend(preflight["errors"])
        return result

    # Safety snapshot — capture current state before we drop anything
    if auto_backup:
        safety = backup_databases(tag="pre-restore", containers=targets, quiet=True)
        if safety["databases"]:
            result["safety_backup"] = safety["path"]
        # A safety backup failure is non-fatal (DB might be empty on first run)

    for target in targets:
        dump_file = backup_path / f"{target['db_name']}.sql.gz"
        if not dump_file.exists():
            result["skipped"].append(
                f"{target['label']}: no dump file ({dump_file.name})"
            )
            continue

        container = _find_running_container(target["container_pattern"])
        if not container:
            result["errors"].append(
                f"{target['label']}: container not running"
            )
            continue

        try:
            # Drop and recreate the database for a clean restore.
            # Without this, --clean DROP statements in the dump can fail
            # on foreign key dependencies and COPY hits duplicate keys.
            reset_err = _reset_database(
                container, target["db_name"], target["pg_user"],
            )
            if reset_err:
                result["errors"].append(f"{target['label']}: {reset_err}")
                continue

            dump_bytes = dump_file.read_bytes()
            proc = subprocess.run(
                [
                    "podman", "exec", "-i", container,
                    "bash", "-c",
                    f"gunzip | psql -U {target['pg_user']} -d {target['db_name']}",
                ],
                input=dump_bytes,
                capture_output=True,
                timeout=300,
            )
            stderr = proc.stderr.decode("utf-8", errors="replace").strip()
            if proc.returncode != 0 and "ERROR" in stderr:
                result["errors"].append(f"{target['label']}: {stderr[:300]}")
                continue

            result["restored"].append(target["label"])
        except subprocess.TimeoutExpired:
            result["errors"].append(f"{target['label']}: restore timed out")
        except OSError as exc:
            result["errors"].append(f"{target['label']}: {exc}")

    return result


def list_backups() -> List[Dict[str, Any]]:
    """Return metadata for each backup directory, newest first."""
    if not BACKUP_ROOT.exists():
        return []

    backups = []
    for entry in sorted(BACKUP_ROOT.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        dumps = list(entry.glob("*.sql.gz"))
        total_size = sum(f.stat().st_size for f in dumps)
        backups.append({
            "name": entry.name,
            "path": str(entry),
            "databases": [f.stem.replace(".sql", "") for f in dumps],
            "size_kb": round(total_size / 1024, 1),
            "created": entry.name.split("_")[0] if "_" in entry.name else entry.name,
            "tag": entry.name.split("_", 1)[1] if "_" in entry.name else "",
        })
    return backups


def rotate_backups(tag: str = "auto", keep: int = MAX_AUTO_BACKUPS) -> List[str]:
    """Remove oldest auto-backups beyond *keep* count.

    Only removes directories whose name ends with ``_<tag>``.
    Returns list of removed directory names.
    """
    if not BACKUP_ROOT.exists():
        return []

    matching = sorted(
        [d for d in BACKUP_ROOT.iterdir() if d.is_dir() and d.name.endswith(f"_{tag}")],
        reverse=True,  # newest first
    )

    removed = []
    for old in matching[keep:]:
        shutil.rmtree(old, ignore_errors=True)
        removed.append(old.name)
    return removed
