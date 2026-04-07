#!/usr/bin/env python3
"""Migrate BehaviorService data from SQLite to PostgreSQL.

This script reads the existing SQLite behavior store (used by the current
BehaviorService runtime) and upserts the records into the PostgreSQL schema
introduced in ``schema/migrations/002_create_behavior_service.sql``. It is a
one-shot tooling companion for the Phase 3 backend migration plan documented in
``PRD_NEXT_STEPS.md`` and aligns with
``behavior_align_storage_layers`` / ``behavior_unify_execution_records`` by
keeping the SQLite and PostgreSQL stores in sync prior to cutover.

Usage::

    ./scripts/migrate_behavior_sqlite_to_postgres.py \
        --dsn postgresql://user:pass@localhost/db \
        --sqlite-path ~/.amprealize/data/behaviors.db

When ``--dsn`` is omitted, the script falls back to
``AMPREALIZE_BEHAVIOR_PG_DSN``. When ``--sqlite-path`` is omitted, it reuses the
BehaviorService default resolution (``AMPREALIZE_BEHAVIOR_DB_PATH`` or
``~/.amprealize/data/behaviors.db``).
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

from _postgres_migration_utils import discover_dsn

AMPREALIZE_BEHAVIOR_DB_ENV = "AMPREALIZE_BEHAVIOR_DB_PATH"
DEFAULT_SQLITE_PATH = Path.home() / ".amprealize" / "data" / "behaviors.db"
AMPREALIZE_BEHAVIOR_PG_DSN_ENV = "AMPREALIZE_BEHAVIOR_PG_DSN"

try:
    import psycopg2  # type: ignore[import-not-found]
    from psycopg2.extras import Json, execute_values  # type: ignore[import-not-found]
except ImportError as exc:  # pragma: no cover - optional dependency
    raise SystemExit(
        "❌ psycopg2 is not installed. Install with: pip install -e '.[postgres]'"
    ) from exc


def _resolve_sqlite_path(cli_path: Optional[Path]) -> Path:
    if cli_path is not None:
        return cli_path.expanduser().resolve()
    env_override = os.getenv(AMPREALIZE_BEHAVIOR_DB_ENV)
    if env_override:
        return Path(env_override).expanduser().resolve()
    return DEFAULT_SQLITE_PATH


def _ensure_sqlite_exists(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"❌ SQLite database not found at {path}")


def _connect_sqlite(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _parse_timestamp(raw: Optional[str]) -> Optional[datetime]:
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"Unable to parse timestamp '{raw}'") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _collect_sqlite_rows(conn: sqlite3.Connection) -> Tuple[List[sqlite3.Row], List[sqlite3.Row]]:
    behaviors = conn.execute("SELECT * FROM behaviors").fetchall()
    versions = conn.execute(
        """
        SELECT * FROM behavior_versions
        ORDER BY behavior_id, version
        """
    ).fetchall()
    return behaviors, versions


def _prepare_behavior_payload(row: sqlite3.Row) -> Tuple:
    return (
        row["behavior_id"],
        row["name"],
        row["description"],
        Json(json.loads(row["tags"] or "[]")),
        _parse_timestamp(row["created_at"]),
        _parse_timestamp(row["updated_at"]),
        row["latest_version"],
        row["status"],
    )


def _prepare_version_payload(row: sqlite3.Row) -> Tuple:
    trigger_keywords = json.loads(row["trigger_keywords"] or "[]")
    examples = json.loads(row["examples"] or "[]")
    metadata = json.loads(row["metadata"] or "{}")
    embedding_blob: Optional[bytes]
    if row["embedding"] is None:
        embedding_blob = None
    elif isinstance(row["embedding"], bytes):
        embedding_blob = row["embedding"]
    else:
        embedding_blob = bytes(row["embedding"])
    return (
        row["behavior_id"],
        row["version"],
        row["instruction"],
        row["role_focus"],
        row["status"],
        Json(trigger_keywords),
        Json(examples),
        Json(metadata),
        _parse_timestamp(row["effective_from"]),
        _parse_timestamp(row["effective_to"]),
        row["created_by"],
        row["approval_action_id"],
        row["embedding_checksum"],
        embedding_blob,
    )


def migrate(sqlite_path: Path, dsn: str, *, connect_timeout: int, truncate: bool, chunk_size: int, dry_run: bool) -> None:
    _ensure_sqlite_exists(sqlite_path)
    sqlite_conn = _connect_sqlite(sqlite_path)
    behaviors, versions = _collect_sqlite_rows(sqlite_conn)

    print(f"📥 Loaded {len(behaviors)} behaviors and {len(versions)} behavior versions from SQLite {sqlite_path}")

    if dry_run:
        print("ℹ️ Dry run complete; no changes applied to PostgreSQL.")
        return

    pg_conn = psycopg2.connect(dsn, connect_timeout=connect_timeout)
    pg_conn.autocommit = False

    try:
        with pg_conn.cursor() as cur:
            if truncate:
                print("🧹 Truncating existing PostgreSQL behavior tables…")
                cur.execute("DELETE FROM behavior_versions;")
                cur.execute("DELETE FROM behaviors;")

            behavior_payloads = [_prepare_behavior_payload(row) for row in behaviors]
            version_payloads = [_prepare_version_payload(row) for row in versions]

            if behavior_payloads:
                print(f"⬆️ Upserting {len(behavior_payloads)} behavior rows…")
                execute_values(
                    cur,
                    """
                    INSERT INTO behaviors (
                        behavior_id,
                        name,
                        description,
                        tags,
                        created_at,
                        updated_at,
                        latest_version,
                        status
                    ) VALUES %s
                    ON CONFLICT (behavior_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        description = EXCLUDED.description,
                        tags = EXCLUDED.tags,
                        created_at = EXCLUDED.created_at,
                        updated_at = EXCLUDED.updated_at,
                        latest_version = EXCLUDED.latest_version,
                        status = EXCLUDED.status
                    """,
                    behavior_payloads,
                    page_size=chunk_size,
                )

            if version_payloads:
                print(f"⬆️ Upserting {len(version_payloads)} behavior version rows…")
                execute_values(
                    cur,
                    """
                    INSERT INTO behavior_versions (
                        behavior_id,
                        version,
                        instruction,
                        role_focus,
                        status,
                        trigger_keywords,
                        examples,
                        metadata,
                        effective_from,
                        effective_to,
                        created_by,
                        approval_action_id,
                        embedding_checksum,
                        embedding
                    ) VALUES %s
                    ON CONFLICT (behavior_id, version) DO UPDATE SET
                        instruction = EXCLUDED.instruction,
                        role_focus = EXCLUDED.role_focus,
                        status = EXCLUDED.status,
                        trigger_keywords = EXCLUDED.trigger_keywords,
                        examples = EXCLUDED.examples,
                        metadata = EXCLUDED.metadata,
                        effective_from = EXCLUDED.effective_from,
                        effective_to = EXCLUDED.effective_to,
                        created_by = EXCLUDED.created_by,
                        approval_action_id = EXCLUDED.approval_action_id,
                        embedding_checksum = EXCLUDED.embedding_checksum,
                        embedding = EXCLUDED.embedding
                    """,
                    version_payloads,
                    page_size=chunk_size,
                )

        pg_conn.commit()
    except Exception:
        pg_conn.rollback()
        raise
    finally:
        pg_conn.close()
        sqlite_conn.close()

    print("✅ Migration complete. PostgreSQL now mirrors the SQLite BehaviorService store.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migrate BehaviorService data from SQLite to PostgreSQL")
    parser.add_argument("--dsn", help="PostgreSQL DSN (overrides AMPREALIZE_BEHAVIOR_PG_DSN)")
    parser.add_argument(
        "--sqlite-path",
        type=Path,
        help="Path to behaviors SQLite DB (overrides AMPREALIZE_BEHAVIOR_DB_PATH)",
    )
    parser.add_argument("--connect-timeout", type=int, default=10, help="PostgreSQL connection timeout in seconds")
    parser.add_argument("--chunk-size", type=int, default=500, help="Batch size for bulk inserts")
    parser.add_argument("--truncate", action="store_true", help="Delete existing behavior rows in PostgreSQL before migrating")
    parser.add_argument("--dry-run", action="store_true", help="Inspect SQLite counts without writing to PostgreSQL")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    sqlite_path = _resolve_sqlite_path(args.sqlite_path)
    dsn = discover_dsn(args.dsn, AMPREALIZE_BEHAVIOR_PG_DSN_ENV)

    migrate(
        sqlite_path,
        dsn,
        connect_timeout=args.connect_timeout,
        truncate=args.truncate,
        chunk_size=args.chunk_size,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
