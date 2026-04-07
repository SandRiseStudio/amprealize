"""SQLite schema migrations for local/OSS mode.

Each migration is a Python module exposing:
    VERSION: int    — sequential migration number
    NAME: str       — short descriptive name
    SQL: str        — DDL to execute (multiple statements, separated by ';')

The :class:`~amprealize.storage.sqlite_pool.SQLitePool` ``apply_migration``
method runs ``executescript(SQL)`` then records the version in ``_migrations``.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING, List, Tuple

if TYPE_CHECKING:
    from amprealize.storage.sqlite_pool import SQLitePool


def discover_migrations() -> List[Tuple[int, str, str]]:
    """Return ``(version, name, sql)`` tuples sorted by version.

    Scans this package for modules whose names start with ``m`` and that
    export ``VERSION``, ``NAME``, and ``SQL`` attributes.
    """
    migrations: List[Tuple[int, str, str]] = []
    package_path = __path__  # type: ignore[name-defined]
    for finder, module_name, _ispkg in pkgutil.iter_modules(package_path):
        if not module_name.startswith("m"):
            continue
        mod = importlib.import_module(f"{__name__}.{module_name}")
        version = getattr(mod, "VERSION", None)
        name = getattr(mod, "NAME", None)
        sql = getattr(mod, "SQL", None)
        if version is not None and name is not None and sql is not None:
            migrations.append((int(version), str(name), str(sql)))
    migrations.sort(key=lambda t: t[0])
    return migrations


def run_migrations(pool: "SQLitePool") -> List[Tuple[int, str]]:
    """Apply all pending migrations and return those that were applied.

    Returns a list of ``(version, name)`` tuples for newly applied migrations.
    """
    applied = set(pool.get_applied_migrations())
    all_migrations = discover_migrations()
    newly_applied: List[Tuple[int, str]] = []
    for version, name, sql in all_migrations:
        if version in applied:
            continue
        pool.apply_migration(version, name, sql)
        newly_applied.append((version, name))
    return newly_applied
