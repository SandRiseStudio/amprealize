"""Config-driven storage backend factory.

Reads ``config.storage.backend`` and returns the appropriate pool instance.
"""

from __future__ import annotations

from typing import Union

from amprealize.config.loader import load_config
from amprealize.config.schema import AmprealizeConfig


def create_storage_pool(
    config: AmprealizeConfig | None = None,
    *,
    service_name: str = "default",
    schema: str | None = None,
) -> Union["PostgresPool", "SQLitePool"]:
    """Return a storage pool based on the active configuration.

    Parameters
    ----------
    config:
        Explicit config to use.  If *None* the config is loaded via
        :func:`amprealize.config.loader.load_config`.
    service_name:
        Logical service label forwarded to the pool constructor.
    schema:
        Database schema (PostgreSQL) — ignored for SQLite.
    """
    if config is None:
        config = load_config()

    backend = config.storage.backend

    if backend == "sqlite":
        from amprealize.storage.sqlite_pool import SQLitePool

        dsn = config.storage.sqlite.path
        return SQLitePool(dsn=dsn, service_name=service_name)

    if backend == "postgres":
        from amprealize.storage.postgres_pool import PostgresPool

        dsn = config.storage.postgres.dsn
        return PostgresPool(dsn=dsn, service_name=service_name, schema=schema)

    raise ValueError(
        f"Unsupported storage backend '{backend}'. "
        "Supported: 'sqlite', 'postgres'."
    )
