#!/usr/bin/env python3
"""Replay telemetry warehouse projections from existing ``telemetry_events`` rows.

Use when upgrading observability schema, repairing missing ``observability_records``,
or backfilling typed projection tables. Reuses :meth:`PostgresTelemetryWarehouse._project_event`
so behavior matches live ingestion (idempotent inserts where applicable).

Environment / DSN resolution matches other telemetry scripts::

    export AMPREALIZE_TELEMETRY_PG_DSN=postgresql://...
    ./scripts/backfill_observability_records_from_telemetry_events.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
for _p in (SCRIPT_DIR, REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from _postgres_migration_utils import discover_dsn  # noqa: E402


def _parse_iso_or_none(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay observability/projections for rows in telemetry_events",
    )
    parser.add_argument("--dsn", help="PostgreSQL DSN (overrides AMPREALIZE_TELEMETRY_PG_DSN)")
    parser.add_argument(
        "--since",
        help="Inclusive lower bound on event_timestamp (ISO 8601)",
    )
    parser.add_argument(
        "--until",
        help="Inclusive upper bound on event_timestamp (ISO 8601)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max rows to replay in this invocation (default: all)",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Skip first N rows after ordering (pagination)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count rows that would be replayed for this page without writing",
    )
    args = parser.parse_args(argv)

    dsn = discover_dsn(args.dsn, "AMPREALIZE_TELEMETRY_PG_DSN")
    since = _parse_iso_or_none(args.since)
    until = _parse_iso_or_none(args.until)

    from amprealize.storage.postgres_telemetry import PostgresTelemetryWarehouse  # noqa: WPS433

    warehouse = PostgresTelemetryWarehouse(dsn, connect_timeout=int(os.environ.get("AMPREALIZE_PG_CONNECT_TIMEOUT", "10")))
    stats = warehouse.replay_event_projections_from_telemetry_table(
        since=since,
        until=until,
        limit=args.limit,
        offset=args.offset,
        dry_run=args.dry_run,
    )

    print(
        "replay_event_projections_from_telemetry_table:",
        stats,
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
