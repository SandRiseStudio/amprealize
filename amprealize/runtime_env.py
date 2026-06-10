"""Shared .env loading for API, CLI, and tests.

When ``AMPREALIZE_TEST_INFRA_MODE=breakeramp``, database URL env keys are not
merged from ``.env`` so ``run_tests.sh`` / BreakerAmp localhost DSNs are not
overwritten by Neon (or other cloud) entries in the developer's ``.env``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

_SKIP_DOTENV_DB_KEYS = frozenset(
    ("DATABASE_URL", "DATABASE__POSTGRES_URL", "AMPREALIZE_ALEMBIC_DATABASE_URL")
)


def merge_dotenv_skipping_database_keys(env_path: Path) -> None:
    """Set env vars from ``env_path`` except database DSN / URL keys."""
    try:
        from dotenv import dotenv_values
    except ImportError:
        return

    for key, val in (dotenv_values(env_path) or {}).items():
        if not key or val is None:
            continue
        if key in _SKIP_DOTENV_DB_KEYS or (
            key.startswith("AMPREALIZE_") and key.endswith("_PG_DSN")
        ):
            continue
        if key not in os.environ:
            os.environ[key] = str(val)


def load_dotenv_files(
    paths: Iterable[Path],
    *,
    breakeramp_skip_db_keys: bool | None = None,
) -> None:
    """Load each existing path with ``load_dotenv`` or selective merge.

    If ``breakeramp_skip_db_keys`` is None, it defaults to whether
    ``AMPREALIZE_TEST_INFRA_MODE == \"breakeramp\"``.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    if breakeramp_skip_db_keys is None:
        breakeramp_skip_db_keys = os.environ.get("AMPREALIZE_TEST_INFRA_MODE") == "breakeramp"

    for path in paths:
        if not path.is_file():
            continue
        if breakeramp_skip_db_keys:
            merge_dotenv_skipping_database_keys(path)
        else:
            load_dotenv(path)
