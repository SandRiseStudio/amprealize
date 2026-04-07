"""Raze Alembic Environment Configuration.

This is a standalone Alembic environment for the raze logging package.
It manages the log_events TimescaleDB hypertable and related structures.

The environment is designed to work independently of amprealize's main
database migrations while using the same PostgreSQL instance.
"""
from logging.config import fileConfig
import os
from typing import TYPE_CHECKING

from alembic import context
from sqlalchemy import engine_from_config, pool, text

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

# This is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# No SQLAlchemy metadata - Raze uses raw SQL for TimescaleDB features
target_metadata = None


def get_database_url() -> str:
    """Get database URL from environment variables.

    Priority:
    1. RAZE_DATABASE_URL (package-specific)
    2. AMPREALIZE_DATABASE_URL (shared with amprealize)
    3. DATABASE_URL (generic fallback)

    Returns:
        Database URL string

    Raises:
        ValueError: If no database URL is configured
    """
    url = (
        os.environ.get("RAZE_DATABASE_URL")
        or os.environ.get("AMPREALIZE_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
    )
    if not url:
        raise ValueError(
            "Database URL not configured. Set RAZE_DATABASE_URL, "
            "AMPREALIZE_DATABASE_URL, or DATABASE_URL environment variable."
        )
    return url


def include_object(
    object: object,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: object | None,
) -> bool:
    """Filter objects for autogenerate.

    Raze only manages objects with the 'raze_' prefix or 'log_events' table.
    This prevents conflicts with amprealize's main schema.
    """
    if type_ == "table":
        # Include log_events (main table) and any raze_* tables
        return name == "log_events" or (name is not None and name.startswith("raze_"))
    elif type_ == "index":
        # Include indexes on raze tables
        return name is not None and (
            name.startswith("idx_log_events") or name.startswith("idx_raze_")
        )
    # Include all other object types (views, etc.)
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine,
    though an Engine is acceptable here as well. By skipping the Engine
    creation we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        # Use separate version table to isolate from main amprealize migrations
        version_table="raze_alembic_version",
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine and associate a
    connection with the context.
    """
    # Override URL from environment
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            # Use non-transactional DDL for TimescaleDB operations
            transaction_per_migration=True,
            # Use separate version table to isolate from main amprealize migrations
            version_table="raze_alembic_version",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
