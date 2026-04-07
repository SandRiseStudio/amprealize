#!/usr/bin/env python3
"""Migrate WorkflowService data from SQLite to PostgreSQL.

This script reads workflow templates and run records from the legacy SQLite
backend and upserts them into the PostgreSQL schema introduced in
``schema/migrations/003_create_workflow_service.sql``.  It supports the Phase 3
backend parity effort described in ``PRD_NEXT_STEPS.md`` and aligns with
``behavior_align_storage_layers`` / ``behavior_unify_execution_records`` by
keeping execution records consistent across storage layers.

Usage::

    ./scripts/migrate_workflow_sqlite_to_postgres.py \
        --dsn postgresql://user:pass@localhost/db \
        --sqlite-path ~/.amprealize/workflows.db

When ``--dsn`` is omitted, the script falls back to ``AMPREALIZE_WORKFLOW_PG_DSN``.
When ``--sqlite-path`` is omitted, it uses the WorkflowService default
(``AMPREALIZE_WORKFLOW_DB_PATH`` or ``~/.amprealize/workflows.db``).
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from _postgres_migration_utils import discover_dsn

AMPREALIZE_WORKFLOW_DB_ENV = "AMPREALIZE_WORKFLOW_DB_PATH"
DEFAULT_SQLITE_PATH = Path.home() / ".amprealize" / "workflows.db"
AMPREALIZE_WORKFLOW_PG_DSN_ENV = "AMPREALIZE_WORKFLOW_PG_DSN"

try:
    import psycopg2  # type: ignore[import-not-found]
    from psycopg2.extras import Json, execute_values  # type: ignore[import-not-found]
except ImportError as exc:  # pragma: no cover - optional dependency
    raise SystemExit("❌ psycopg2 is not installed. Install with: pip install -e '.[postgres]'") from exc


def _resolve_sqlite_path(cli_path: Optional[Path]) -> Path:
    if cli_path is not None:
        return cli_path.expanduser().resolve()
    env_override = os.getenv(AMPREALIZE_WORKFLOW_DB_ENV)
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
    templates = conn.execute(
        """
        SELECT * FROM workflow_templates
        ORDER BY created_at
        """
    ).fetchall()
    runs = conn.execute(
        """
        SELECT * FROM workflow_runs
        ORDER BY started_at
        """
    ).fetchall()
    return templates, runs


def _prepare_template_payload(row: sqlite3.Row) -> Tuple:
    tags = json.loads(row["tags"] or "[]")
    template_data = json.loads(row["template_data"] or "{}")
    return (
        row["template_id"],
        row["name"],
        row["description"],
        row["role_focus"],
        row["version"],
        _parse_timestamp(row["created_at"]),
        row["created_by_id"],
        row["created_by_role"],
        row["created_by_surface"],
        Json(template_data),
        Json(tags),
    )


def _prepare_run_payload(row: sqlite3.Row) -> Tuple:
    run_data = json.loads(row["run_data"] or "{}")
    completed_at = _parse_timestamp(row["completed_at"])
    total_tokens = row["total_tokens"]
    if total_tokens is None:
        total_tokens = 0
    return (
        row["run_id"],
        row["template_id"],
        row["template_name"],
        row["role_focus"],
        row["status"],
        row["actor_id"],
        row["actor_role"],
        row["actor_surface"],
        _parse_timestamp(row["started_at"]),
        completed_at,
        int(total_tokens),
        Json(run_data),
    )


def migrate(
    sqlite_path: Path,
    dsn: str,
    *,
    connect_timeout: int,
    truncate: bool,
    chunk_size: int,
    dry_run: bool,
) -> None:
    _ensure_sqlite_exists(sqlite_path)
    sqlite_conn = _connect_sqlite(sqlite_path)
    templates, runs = _collect_sqlite_rows(sqlite_conn)

    print(f"📥 Loaded {len(templates)} workflow templates and {len(runs)} workflow runs from SQLite {sqlite_path}")

    if dry_run:
        print("ℹ️ Dry run complete; no changes applied to PostgreSQL.")
        sqlite_conn.close()
        return

    pg_conn = psycopg2.connect(dsn, connect_timeout=connect_timeout)
    pg_conn.autocommit = False

    try:
        with pg_conn.cursor() as cur:
            if truncate:
                print("🧹 Truncating existing PostgreSQL workflow tables…")
                cur.execute("DELETE FROM workflow_runs;")
                cur.execute("DELETE FROM workflow_templates;")

            template_payloads = [_prepare_template_payload(row) for row in templates]
            run_payloads = [_prepare_run_payload(row) for row in runs]

            if template_payloads:
                print(f"⬆️ Upserting {len(template_payloads)} workflow templates…")
                execute_values(
                    cur,
                    """
                    INSERT INTO workflow_templates (
                        template_id,
                        name,
                        description,
                        role_focus,
                        version,
                        created_at,
                        created_by_id,
                        created_by_role,
                        created_by_surface,
                        template_data,
                        tags
                    ) VALUES %s
                    ON CONFLICT (template_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        description = EXCLUDED.description,
                        role_focus = EXCLUDED.role_focus,
                        version = EXCLUDED.version,
                        created_at = EXCLUDED.created_at,
                        created_by_id = EXCLUDED.created_by_id,
                        created_by_role = EXCLUDED.created_by_role,
                        created_by_surface = EXCLUDED.created_by_surface,
                        template_data = EXCLUDED.template_data,
                        tags = EXCLUDED.tags
                    """,
                    template_payloads,
                    page_size=chunk_size,
                )

            if run_payloads:
                print(f"⬆️ Upserting {len(run_payloads)} workflow runs…")
                execute_values(
                    cur,
                    """
                    INSERT INTO workflow_runs (
                        run_id,
                        template_id,
                        template_name,
                        role_focus,
                        status,
                        actor_id,
                        actor_role,
                        actor_surface,
                        started_at,
                        completed_at,
                        total_tokens,
                        run_data
                    ) VALUES %s
                    ON CONFLICT (run_id) DO UPDATE SET
                        template_id = EXCLUDED.template_id,
                        template_name = EXCLUDED.template_name,
                        role_focus = EXCLUDED.role_focus,
                        status = EXCLUDED.status,
                        actor_id = EXCLUDED.actor_id,
                        actor_role = EXCLUDED.actor_role,
                        actor_surface = EXCLUDED.actor_surface,
                        started_at = EXCLUDED.started_at,
                        completed_at = EXCLUDED.completed_at,
                        total_tokens = EXCLUDED.total_tokens,
                        run_data = EXCLUDED.run_data
                    """,
                    run_payloads,
                    page_size=chunk_size,
                )

        pg_conn.commit()
    except Exception:
        pg_conn.rollback()
        raise
    finally:
        pg_conn.close()
        sqlite_conn.close()

    print("✅ Migration complete. PostgreSQL now mirrors the SQLite WorkflowService store.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migrate WorkflowService data from SQLite to PostgreSQL")
    parser.add_argument("--dsn", help="PostgreSQL DSN (overrides AMPREALIZE_WORKFLOW_PG_DSN)")
    parser.add_argument(
        "--sqlite-path",
        type=Path,
        help="Path to workflow SQLite DB (overrides AMPREALIZE_WORKFLOW_DB_PATH)",
    )
    parser.add_argument("--connect-timeout", type=int, default=10, help="PostgreSQL connection timeout in seconds")
    parser.add_argument("--chunk-size", type=int, default=500, help="Batch size for bulk inserts")
    parser.add_argument("--truncate", action="store_true", help="Delete existing workflow rows in PostgreSQL before migrating")
    parser.add_argument("--dry-run", action="store_true", help="Inspect SQLite counts without writing to PostgreSQL")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    sqlite_path = _resolve_sqlite_path(args.sqlite_path)
    dsn = discover_dsn(args.dsn, AMPREALIZE_WORKFLOW_PG_DSN_ENV)

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
