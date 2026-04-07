#!/usr/bin/env python3
"""Apply Alembic migrations to the database URL in the environment.

Uses DATABASE_URL, AMPREALIZE_ALEMBIC_DATABASE_URL, or AMPREALIZE_ALEMBIC_DATABASE_URL.
Intended for
local tests (scripts/run_tests.sh) and CI instead of legacy raw SQL files.

Usage:
    DATABASE_URL=postgresql://... python scripts/run_alembic_migrations.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


def main() -> int:
    dsn = (
        os.environ.get("AMPREALIZE_ALEMBIC_DATABASE_URL")
        or os.environ.get("AMPREALIZE_ALEMBIC_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
    )
    if not dsn:
        print(
            "error: set DATABASE_URL, AMPREALIZE_ALEMBIC_DATABASE_URL, or AMPREALIZE_ALEMBIC_DATABASE_URL",
            file=sys.stderr,
        )
        return 1
    if not ALEMBIC_INI.is_file():
        print(f"error: missing {ALEMBIC_INI}", file=sys.stderr)
        return 1

    env = os.environ.copy()
    env["DATABASE_URL"] = dsn

    cmd = [
        sys.executable,
        "-m",
        "alembic",
        "-c",
        str(ALEMBIC_INI),
        "upgrade",
        "head",
    ]
    return subprocess.call(cmd, cwd=str(REPO_ROOT), env=env)


if __name__ == "__main__":
    raise SystemExit(main())
