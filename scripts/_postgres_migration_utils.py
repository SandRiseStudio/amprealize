"""Shared helpers for running PostgreSQL schema migrations."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable, List, Optional


def discover_dsn(cli_dsn: Optional[str], env_var: str) -> str:
    """Resolve the PostgreSQL DSN from CLI arguments or environment."""

    dsn = cli_dsn or os.environ.get(env_var)
    if not dsn:
        raise SystemExit(
            f"❌ Missing PostgreSQL DSN. Provide --dsn or set {env_var}"
        )
    return dsn


def load_migration(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"❌ Migration file not found: {path}")
    return path.read_text(encoding="utf-8")


def split_sql_statements(sql: str) -> List[str]:
    """Split SQL script into executable statements.

    Handles single quotes, double quotes, and dollar-quoted bodies so we do not
    accidentally split inside PL/pgSQL functions.
    """

    statements: List[str] = []
    current: List[str] = []
    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False
    dollar_quote: Optional[str] = None
    length = len(sql)
    i = 0

    while i < length:
        ch = sql[i]

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
                current.append("\n")
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and i + 1 < length and sql[i + 1] == "/":
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue

        if dollar_quote is not None:
            if sql.startswith(dollar_quote, i):
                current.append(dollar_quote)
                i += len(dollar_quote)
                dollar_quote = None
                continue
            current.append(ch)
            i += 1
            continue

        if not in_single and not in_double and dollar_quote is None:
            if ch == "-" and i + 1 < length and sql[i + 1] == "-":
                in_line_comment = True
                i += 2
                continue

            if ch == "/" and i + 1 < length and sql[i + 1] == "*":
                in_block_comment = True
                i += 2
                continue

        if not in_single and not in_double and ch == "$":
            j = i + 1
            while j < length and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            if j < length and sql[j] == "$":
                dollar_quote = sql[i : j + 1]
                current.append(dollar_quote)
                i = j + 1
                continue

        if ch == "'" and not in_double:
            in_single = not in_single
            current.append(ch)
            i += 1
            continue

        if ch == '"' and not in_single:
            in_double = not in_double
            current.append(ch)
            i += 1
            continue

        if ch == ";" and not in_single and not in_double and dollar_quote is None:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current.clear()
            i += 1
            continue

        current.append(ch)
        i += 1

    final = "".join(current).strip()
    if final:
        statements.append(final)

    return statements


def execute_statements(dsn: str, statements: Iterable[str], *, connect_timeout: Optional[int]) -> None:
    try:
        import psycopg2  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise SystemExit(
            "❌ psycopg2 is not installed. Install with: pip install -e '.[postgres]'"
        ) from exc

    connection = psycopg2.connect(dsn, connect_timeout=connect_timeout)
    connection.autocommit = False

    try:
        with connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
