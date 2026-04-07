#!/usr/bin/env python3
"""Generate a dry-run readiness report for PostgreSQL migrations.

This helper inspects the BehaviorService and WorkflowService migration assets
and produces a structured summary that can be stored alongside Phase 3 rollout
artifacts. It does **not** execute any writes; instead it:

1. Loads the schema migration SQL and counts the statements that will run.
2. Locates the source SQLite databases (if present) and reports their row counts.
3. Emits recommended dry-run commands so operators can execute the migrations
   with ``--dry-run`` or full mode when ready.

Use this script ahead of the Phase 3 production cutover to capture baseline
metrics (row counts, file sizes, etc.) and to ensure every required input is in
place before running the full migrations.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, cast

from _postgres_migration_utils import load_migration, split_sql_statements

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BEHAVIOR_MIGRATION = REPO_ROOT / "schema" / "migrations" / "002_create_behavior_service.sql"
DEFAULT_WORKFLOW_MIGRATION = REPO_ROOT / "schema" / "migrations" / "003_create_workflow_service.sql"

DEFAULT_BEHAVIOR_SQLITE = Path.home() / ".amprealize" / "data" / "behaviors.db"
DEFAULT_WORKFLOW_SQLITE = Path.home() / ".amprealize" / "workflows.db"

BEHAVIOR_SQLITE_ENV = "AMPREALIZE_BEHAVIOR_DB_PATH"
WORKFLOW_SQLITE_ENV = "AMPREALIZE_WORKFLOW_DB_PATH"
BEHAVIOR_DSN_ENV = "AMPREALIZE_BEHAVIOR_PG_DSN"
WORKFLOW_DSN_ENV = "AMPREALIZE_WORKFLOW_PG_DSN"


@dataclass
class ServiceConfig:
    name: str
    migration_path: Path
    sqlite_default: Path
    sqlite_env: str
    dsn_env: str
    count_queries: Dict[str, str]


SERVICES: Dict[str, ServiceConfig] = {
    "behavior": ServiceConfig(
        name="BehaviorService",
        migration_path=DEFAULT_BEHAVIOR_MIGRATION,
        sqlite_default=DEFAULT_BEHAVIOR_SQLITE,
        sqlite_env=BEHAVIOR_SQLITE_ENV,
        dsn_env=BEHAVIOR_DSN_ENV,
        count_queries={
            "behaviors": "SELECT COUNT(*) FROM behaviors",
            "behavior_versions": "SELECT COUNT(*) FROM behavior_versions",
        },
    ),
    "workflow": ServiceConfig(
        name="WorkflowService",
        migration_path=DEFAULT_WORKFLOW_MIGRATION,
        sqlite_default=DEFAULT_WORKFLOW_SQLITE,
        sqlite_env=WORKFLOW_SQLITE_ENV,
        dsn_env=WORKFLOW_DSN_ENV,
        count_queries={
            "workflow_templates": "SELECT COUNT(*) FROM workflow_templates",
            "workflow_runs": "SELECT COUNT(*) FROM workflow_runs",
        },
    ),
}


def _resolve_sqlite_path(override: Optional[Path], env_var: str, fallback: Path) -> Path:
    if override is not None:
        return override.expanduser().resolve()
    env_value = os.getenv(env_var)
    if env_value:
        return Path(env_value).expanduser().resolve()
    return fallback


def _sqlite_row_counts(path: Path, queries: Dict[str, str]) -> Dict[str, Optional[int]]:
    results: Dict[str, Optional[int]] = {name: None for name in queries}
    if not path.exists():
        return results

    connection = sqlite3.connect(str(path))
    try:
        cursor = connection.cursor()
        for label, sql in queries.items():
            try:
                row = cursor.execute(sql).fetchone()
            except sqlite3.OperationalError as exc:
                results[label] = None
                print(f"⚠️  Unable to execute query '{label}' on {path}: {exc}")
                continue
            if row is None:
                results[label] = 0
            else:
                value = row[0]
                if value is None:
                    results[label] = 0
                else:
                    results[label] = int(value)
        return results
    finally:
        connection.close()


def _schema_summary(path: Path, include_statements: bool) -> Dict[str, Any]:
    sql = load_migration(path)
    statements = split_sql_statements(sql)
    summary: Dict[str, object] = {
        "migration_path": str(path),
        "statement_count": len(statements),
    }
    if include_statements:
        summary["statements"] = statements
    return summary


def _command_string(script: str, dsn: Optional[str], sqlite_path: Optional[Path] = None, dry_run: bool = True) -> str:
    pieces: List[str] = [script]
    if dsn:
        pieces.extend(["--dsn", dsn])
    else:
        pieces.extend(["--dsn", "<postgresql-dsn>"])
    if sqlite_path is not None:
        pieces.extend(["--sqlite-path", str(sqlite_path)])
    if dry_run:
        pieces.append("--dry-run")
    return " ".join(pieces)


def _service_report(
    service: ServiceConfig,
    *,
    sqlite_override: Optional[Path],
    dsn_override: Optional[str],
    include_statements: bool,
) -> Dict[str, Any]:
    sqlite_path = _resolve_sqlite_path(sqlite_override, service.sqlite_env, service.sqlite_default)
    sqlite_exists = sqlite_path.exists()
    sqlite_size = sqlite_path.stat().st_size if sqlite_exists else None
    counts = _sqlite_row_counts(sqlite_path, service.count_queries)

    dsn = dsn_override or os.getenv(service.dsn_env)

    command_prefix = service.name.lower().replace("service", "")

    report: Dict[str, Any] = {
        "service": service.name,
        "schema": _schema_summary(service.migration_path, include_statements),
        "data": {
            "sqlite_path": str(sqlite_path),
            "sqlite_exists": sqlite_exists,
            "sqlite_size_bytes": sqlite_size,
            "row_counts": counts,
        },
        "commands": {
            "schema_dry_run": _command_string(
                script=f"./scripts/run_postgres_{command_prefix}_migration.py",
                dsn=dsn,
                dry_run=True,
            ),
            "data_dry_run": _command_string(
                script=f"./scripts/migrate_{command_prefix}_sqlite_to_postgres.py",
                dsn=dsn,
                sqlite_path=sqlite_path,
                dry_run=True,
            ),
            "data_apply": _command_string(
                script=f"./scripts/migrate_{command_prefix}_sqlite_to_postgres.py",
                dsn=dsn,
                sqlite_path=sqlite_path,
                dry_run=False,
            ),
        },
    }

    if not sqlite_exists:
        report["warnings"] = [
            f"SQLite database not found at {sqlite_path}. Create a checkpoint before running dry-run."
        ]

    return report


def _render_markdown(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# PostgreSQL Migration Dry-Run Report")
    lines.append("")
    lines.append(f"Generated: {report['generated_at']}")
    lines.append("")

    services = cast(Dict[str, Dict[str, Any]], report["services"])
    for service in services.values():
        lines.append(f"## {service['service']}")
        lines.append("")
        schema = cast(Dict[str, Any], service["schema"])
        data = cast(Dict[str, Any], service["data"])

        lines.append("### Schema")
        lines.append(f"- Migration file: `{schema['migration_path']}`")
        lines.append(f"- Statement count: {schema['statement_count']}")
        lines.append("")

        lines.append("### Data Snapshot")
        lines.append(f"- SQLite path: `{data['sqlite_path']}`")
        lines.append(f"- SQLite exists: {data['sqlite_exists']}")
        if data["sqlite_size_bytes"] is not None:
            lines.append(f"- SQLite file size: {data['sqlite_size_bytes']} bytes")
        if data["row_counts"]:
            lines.append("- Row counts:")
            row_counts = cast(Dict[str, Optional[int]], data["row_counts"])
            for table, count in row_counts.items():
                lines.append(f"  - {table}: {count if count is not None else 'N/A'}")
        lines.append("")

        commands = cast(Dict[str, str], service["commands"])
        lines.append("### Recommended Commands")
        lines.append("```bash")
        lines.append(commands["schema_dry_run"])
        lines.append(commands["data_dry_run"])
        lines.append("# Full migration (no --dry-run)")
        lines.append(commands["data_apply"])
        lines.append("```")
        lines.append("")

        warnings = cast(Optional[List[str]], service.get("warnings"))
        if warnings:
            lines.append("### Warnings")
            for warning in warnings:
                lines.append(f"- {warning}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def generate_report(args: argparse.Namespace) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "services": {},
    }

    behavior = _service_report(
        SERVICES["behavior"],
        sqlite_override=args.behavior_sqlite_path,
        dsn_override=args.behavior_dsn,
        include_statements=args.include_statements,
    )
    workflow = _service_report(
        SERVICES["workflow"],
        sqlite_override=args.workflow_sqlite_path,
        dsn_override=args.workflow_dsn,
        include_statements=args.include_statements,
    )

    services = cast(Dict[str, Any], report["services"])
    services["behavior"] = behavior
    services["workflow"] = workflow

    return report


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate PostgreSQL migration dry-run readiness report")
    parser.add_argument("--behavior-sqlite-path", type=Path, help="Override BehaviorService SQLite path")
    parser.add_argument("--workflow-sqlite-path", type=Path, help="Override WorkflowService SQLite path")
    parser.add_argument("--behavior-dsn", help="Explicit BehaviorService PostgreSQL DSN")
    parser.add_argument("--workflow-dsn", help="Explicit WorkflowService PostgreSQL DSN")
    parser.add_argument(
        "--format",
        choices=["json", "markdown", "both"],
        default="json",
        help="Output format",
    )
    parser.add_argument("--output-json", type=Path, help="Path to write JSON report")
    parser.add_argument("--output-markdown", type=Path, help="Path to write Markdown report")
    parser.add_argument(
        "--include-statements",
        action="store_true",
        help="Include raw SQL statements in the schema section",
    )
    parsed_args = parser.parse_args(list(argv) if argv is not None else None)
    return parsed_args


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    report = generate_report(args)

    if args.format in {"json", "both"}:
        json_payload = json.dumps(report, indent=2, sort_keys=True)
        if args.output_json:
            args.output_json.write_text(json_payload + "\n", encoding="utf-8")
            print(f"📝 JSON report written to {args.output_json}")
        else:
            print(json_payload)

    if args.format in {"markdown", "both"}:
        markdown_payload = _render_markdown(report)
        if args.output_markdown:
            args.output_markdown.write_text(markdown_payload, encoding="utf-8")
            print(f"📝 Markdown report written to {args.output_markdown}")
        else:
            print(markdown_payload)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
