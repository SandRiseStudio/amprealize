"""Workspace storage backend detection.

Detects which storage backend (Postgres, SQLite, or JSON) is in use
for a workspace, and reports migration applicability.

Part of E4 — T4.4.2: Backward-compat migration.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class StorageBackend(str, Enum):
    """Detected workspace storage backend."""

    POSTGRES = "postgres"
    SQLITE = "sqlite"
    JSON = "json"
    UNKNOWN = "unknown"


@dataclass
class StorageDetectionResult:
    """Result of workspace storage detection."""

    backend: StorageBackend
    path_or_dsn: Optional[str] = None
    has_feature_flags_table: bool = False
    has_activations_table: bool = False
    can_migrate: bool = True
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "backend": self.backend.value,
            "path_or_dsn": self.path_or_dsn,
            "has_feature_flags_table": self.has_feature_flags_table,
            "has_activations_table": self.has_activations_table,
            "can_migrate": self.can_migrate,
            "reason": self.reason,
        }


def detect_storage_backend(workspace_path: Optional[str] = None) -> StorageDetectionResult:
    """Detect which storage backend the workspace is using.

    Checks in order:
    1. ``AMPREALIZE_PG_DSN`` or similar env vars → Postgres
    2. ``.amprealize/amprealize.db`` file on disk → SQLite
    3. ``.amprealize/state.json`` or ``.amprealize/`` dir → JSON
    4. Otherwise → unknown (fresh workspace)
    """
    # Check for Postgres env vars
    pg_dsn = os.environ.get("AMPREALIZE_PG_DSN") or os.environ.get("DATABASE_URL")
    if pg_dsn:
        result = StorageDetectionResult(
            backend=StorageBackend.POSTGRES,
            path_or_dsn=pg_dsn,
        )
        _check_postgres_tables(result, pg_dsn)
        return result

    # Check for local file-based backends
    ws = Path(workspace_path) if workspace_path else Path.cwd()
    amprealize_dir = ws / ".amprealize"

    sqlite_path = amprealize_dir / "amprealize.db"
    if sqlite_path.exists():
        result = StorageDetectionResult(
            backend=StorageBackend.SQLITE,
            path_or_dsn=str(sqlite_path),
        )
        _check_sqlite_tables(result, sqlite_path)
        return result

    json_state = amprealize_dir / "state.json"
    if json_state.exists() or amprealize_dir.exists():
        return StorageDetectionResult(
            backend=StorageBackend.JSON,
            path_or_dsn=str(amprealize_dir),
            can_migrate=True,
            reason="JSON storage does not require schema migration",
        )

    return StorageDetectionResult(
        backend=StorageBackend.UNKNOWN,
        can_migrate=True,
        reason="Fresh workspace — no existing storage detected",
    )


def _check_postgres_tables(result: StorageDetectionResult, dsn: str) -> None:
    """Check if feature_flags and activations tables exist in Postgres."""
    try:
        from amprealize.storage.postgres_pool import PostgresPool

        pool = PostgresPool(dsn)
        with pool.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_name = 'feature_flags')"
                )
                result.has_feature_flags_table = cur.fetchone()[0]
                cur.execute(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_name = 'knowledge_pack_activations')"
                )
                result.has_activations_table = cur.fetchone()[0]
    except Exception:
        logger.debug("Could not check Postgres tables", exc_info=True)


def _check_sqlite_tables(result: StorageDetectionResult, db_path: Path) -> None:
    """Check if feature_flags and activations tables exist in SQLite."""
    try:
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        try:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('feature_flags', 'knowledge_pack_activations')"
            )
            existing = {row[0] for row in cur.fetchall()}
            result.has_feature_flags_table = "feature_flags" in existing
            result.has_activations_table = "knowledge_pack_activations" in existing
        finally:
            conn.close()
    except Exception:
        logger.debug("Could not check SQLite tables", exc_info=True)
