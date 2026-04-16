"""Alembic migrations environment for telemetry database (TimescaleDB).

Behavior: behavior_migrate_postgres_schema

This module configures Alembic to:
1. Connect to the TimescaleDB telemetry database
2. Run migrations for hypertables, continuous aggregates, and compression policies
"""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Apply active context DSN(s) to environment so telemetry migrations use the correct DB.
try:
    from amprealize.context import apply_context_to_environment
    apply_context_to_environment()
except Exception:
    pass  # Best-effort; context system may not be available

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for 'autogenerate' support (None = no autogenerate)
target_metadata = None


def get_url() -> str:
    """Get telemetry database URL from environment."""
    url = os.environ.get("TELEMETRY_DATABASE_URL")
    if url:
        return url

    # Fallback to individual env vars
    user = os.environ.get("AMPREALIZE_PG_USER_TELEMETRY", "telemetry")
    password = os.environ.get("AMPREALIZE_PG_PASS_TELEMETRY", "telemetry_dev")
    host = os.environ.get("AMPREALIZE_PG_HOST_TELEMETRY", "localhost")
    port = os.environ.get("AMPREALIZE_PG_PORT_TELEMETRY", "5433")
    database = os.environ.get("AMPREALIZE_PG_DB_TELEMETRY", "telemetry")

    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine.
    Calls to context.execute() emit the given string to the script output.
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we create an Engine and associate a connection with the context.
    """
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Enable TimescaleDB extension if not exists
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
        connection.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
        connection.commit()

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
