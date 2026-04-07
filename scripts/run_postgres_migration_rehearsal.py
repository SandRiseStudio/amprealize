#!/usr/bin/env python3
"""Run PostgreSQL migration rehearsal in dry-run mode.

This helper orchestrates the BehaviorService and WorkflowService migration
scripts in `--dry-run` mode so we can confirm all prerequisites are present and
capture duration metrics ahead of the production cutover.

Outputs a JSON and/or Markdown report summarizing:

* Command executed for each step
* Exit status and duration
* Stdout/stderr snippets (first/last lines)
* Warnings when SQLite checkpoints are missing

Examples
--------

```
python scripts/run_postgres_migration_rehearsal.py \
    --behavior-dsn postgresql://user:pass@localhost:5432/amprealize_dev \
    --workflow-dsn postgresql://user:pass@localhost:5432/amprealize_dev \
    --format both \
    --output-json reports/rehearsal.json \
    --output-markdown reports/rehearsal.md
```
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, cast

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_BEHAVIOR_SQLITE = Path.home() / ".amprealize" / "data" / "behaviors.db"
DEFAULT_WORKFLOW_SQLITE = Path.home() / ".amprealize" / "workflows.db"


@dataclass
class StepResult:
    name: str
    command: List[str]
    duration_seconds: float
    returncode: int
    stdout: str
    stderr: str
    skipped: bool = False
    warning: Optional[str] = None

    def summary(self) -> Dict[str, object]:
        payload = asdict(self)
        # Trim very long output to keep reports readable
        for key in ("stdout", "stderr"):
            value = payload.get(key)
            if isinstance(value, str) and len(value) > 2000:
                payload[key] = value[:1000] + "\n...\n" + value[-1000:]
        return payload


@dataclass
class ServiceConfig:
    label: str
    schema_script: Path
    data_script: Path
    sqlite_env: str
    sqlite_default: Path


SERVICES = {
    "behavior": ServiceConfig(
        label="BehaviorService",
        schema_script=REPO_ROOT / "scripts" / "run_postgres_behavior_migration.py",
        data_script=REPO_ROOT / "scripts" / "migrate_behavior_sqlite_to_postgres.py",
        sqlite_env="AMPREALIZE_BEHAVIOR_DB_PATH",
        sqlite_default=DEFAULT_BEHAVIOR_SQLITE,
    ),
    "workflow": ServiceConfig(
        label="WorkflowService",
        schema_script=REPO_ROOT / "scripts" / "run_postgres_workflow_migration.py",
        data_script=REPO_ROOT / "scripts" / "migrate_workflow_sqlite_to_postgres.py",
        sqlite_env="AMPREALIZE_WORKFLOW_DB_PATH",
        sqlite_default=DEFAULT_WORKFLOW_SQLITE,
    ),
}


def _resolve_sqlite(path_override: Optional[Path], env_var: str, fallback: Path) -> Path:
    if path_override is not None:
        return path_override.expanduser().resolve()
    env_value = os.getenv(env_var)
    if env_value:
        return Path(env_value).expanduser().resolve()
    return fallback


def _run_command(command: Sequence[str]) -> StepResult:
    start = time.perf_counter()
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    duration = time.perf_counter() - start
    return StepResult(
        name=" ".join(command[:2]),
        command=list(command),
        duration_seconds=round(duration, 3),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _figure_dsn(cli_dsn: Optional[str], env_name: str) -> Optional[str]:
    if cli_dsn:
        return cli_dsn
    return os.getenv(env_name)


def _schema_step(service_key: str, dsn: Optional[str]) -> Sequence[str]:
    script = SERVICES[service_key].schema_script
    command = [sys.executable, str(script)]
    if dsn:
        command.extend(["--dsn", dsn])
    command.append("--dry-run")
    return command


def _data_step(service_key: str, dsn: Optional[str], sqlite_path: Path) -> Sequence[str]:
    script = SERVICES[service_key].data_script
    command = [sys.executable, str(script)]
    if dsn:
        command.extend(["--dsn", dsn])
    command.extend(["--sqlite-path", str(sqlite_path)])
    command.append("--dry-run")
    return command


def generate_report(args: argparse.Namespace) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "services": {},
    }

    for key, config in SERVICES.items():
        dsn = _figure_dsn(getattr(args, f"{key}_dsn"), f"AMPREALIZE_{key.upper()}_PG_DSN")
        sqlite_override = getattr(args, f"{key}_sqlite_path")
        sqlite_path = _resolve_sqlite(sqlite_override, config.sqlite_env, config.sqlite_default)

        service_payload: Dict[str, Any] = {
            "label": config.label,
            "schema_step": None,
            "data_step": None,
            "warnings": [],
        }

        schema_command = _schema_step(key, dsn)
        schema_result = _run_command(schema_command)
        service_payload["schema_step"] = schema_result.summary()
        if schema_result.returncode != 0:
            warnings_list = cast(List[str], service_payload.setdefault("warnings", []))
            warnings_list.append(
                f"Schema dry-run exited with code {schema_result.returncode}."
            )

        if not sqlite_path.exists():
            warning = f"SQLite database not found at {sqlite_path}. Skipping data dry-run."
            warnings_list = cast(List[str], service_payload.setdefault("warnings", []))
            warnings_list.append(warning)
            data_result = StepResult(
                name=f"{config.label} data dry-run",
                command=list(_data_step(key, dsn, sqlite_path)),
                duration_seconds=0.0,
                returncode=0,
                stdout="",
                stderr="",
                skipped=True,
                warning=warning,
            )
        else:
            data_command = _data_step(key, dsn, sqlite_path)
            data_result = _run_command(data_command)
            if data_result.returncode != 0:
                warnings_list = cast(List[str], service_payload.setdefault("warnings", []))
                warnings_list.append(
                    f"Data dry-run exited with code {data_result.returncode}."
                )
        service_payload["data_step"] = data_result.summary()

        services = cast(Dict[str, Any], report["services"])
        services[key] = service_payload

    return report


def _render_markdown(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# PostgreSQL Migration Dry-Run Rehearsal")
    lines.append("")
    lines.append(f"Generated: {report['generated_at']}")
    lines.append("")

    services = cast(Dict[str, Dict[str, Any]], report["services"])
    for payload in services.values():
        lines.append(f"## {payload['label']}")
        lines.append("")

        schema = cast(Dict[str, Any], payload["schema_step"])
        lines.append("### Schema Dry-Run")
        lines.append(f"- Command: `{ ' '.join(schema['command']) }`")
        lines.append(f"- Duration: {schema['duration_seconds']}s")
        lines.append(f"- Exit code: {schema['returncode']}")
        if schema["stderr"]:
            lines.append("- stderr:")
            lines.append(textwrap.indent(schema["stderr"].strip(), "  "))
        lines.append("")

        data = cast(Dict[str, Any], payload["data_step"])
        lines.append("### Data Dry-Run")
        if data["skipped"]:
            lines.append("- Status: Skipped (SQLite database missing)")
        else:
            lines.append(f"- Command: `{ ' '.join(data['command']) }`")
            lines.append(f"- Duration: {data['duration_seconds']}s")
            lines.append(f"- Exit code: {data['returncode']}")
            if data["stderr"]:
                lines.append("- stderr:")
                lines.append(textwrap.indent(data["stderr"].strip(), "  "))
        if data["warning"]:
            lines.append(f"- Warning: {data['warning']}")
        lines.append("")

        warnings = cast(List[str], payload.get("warnings") or [])
        if warnings:
            lines.append("### Warnings")
            for item in warnings:
                lines.append(f"- {item}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run PostgreSQL migration dry-run rehearsal")
    parser.add_argument("--behavior-dsn", help="BehaviorService PostgreSQL DSN (overrides env)")
    parser.add_argument("--workflow-dsn", help="WorkflowService PostgreSQL DSN (overrides env)")
    parser.add_argument("--behavior-sqlite-path", type=Path, help="Override BehaviorService SQLite path")
    parser.add_argument("--workflow-sqlite-path", type=Path, help="Override WorkflowService SQLite path")
    parser.add_argument(
        "--format",
        choices=["json", "markdown", "both"],
        default="json",
        help="Report format",
    )
    parser.add_argument("--output-json", type=Path, help="File path for JSON output")
    parser.add_argument("--output-markdown", type=Path, help="File path for Markdown output")
    parser.add_argument(
        "--ci",
        action="store_true",
        help="Fail with exit code 1 if any step returns non-zero",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    return args


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    report = generate_report(args)

    if args.format in {"json", "both"}:
        payload = json.dumps(report, indent=2, sort_keys=True)
        if args.output_json:
            args.output_json.parent.mkdir(parents=True, exist_ok=True)
            args.output_json.write_text(payload + "\n", encoding="utf-8")
            print(f"📝 JSON report written to {args.output_json}")
        else:
            print(payload)

    if args.format in {"markdown", "both"}:
        markdown = _render_markdown(report)
        if args.output_markdown:
            args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
            args.output_markdown.write_text(markdown, encoding="utf-8")
            print(f"📝 Markdown report written to {args.output_markdown}")
        else:
            print(markdown)

    failed = False
    if args.ci:
        services = cast(Dict[str, Dict[str, Any]], report["services"])
        for payload in services.values():
            step = cast(Dict[str, Any], payload["schema_step"])
            if step["returncode"] != 0:
                failed = True
            data_step = cast(Dict[str, Any], payload["data_step"])
            if data_step["returncode"] != 0 and not data_step["skipped"]:
                failed = True
        if failed:
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
