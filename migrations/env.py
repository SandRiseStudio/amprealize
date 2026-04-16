"""Alembic environment configuration for Amprealize migrations.

This module configures Alembic to:
1. Load database URL from amprealize.config.settings or DATABASE_URL env var
2. Support multi-schema organization for modular monolith architecture
3. Support both online (connected) and offline (SQL script) migrations
4. Filter schemas by enabled modules (modular install system)

Behavior: behavior_migrate_postgres_schema

Schema Organization (Modular Monolith):
- auth: Users, sessions, API keys, OAuth tokens
- board: Boards, columns, work items, sprints
- behavior: Behavior definitions, effectiveness metrics
- execution: Runs, actions, audit logs
- workflow: Workflow definitions, templates
- consent: User consent records, scope management
- audit: WORM audit logs, hash chains

See docs/DATABASE_CONSOLIDATION_PLAN.md for architecture details.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text
from alembic import context

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Apply active context DSN(s) to environment so migrations use the correct DB.
try:
    from amprealize.context import apply_context_to_environment
    apply_context_to_environment()
except Exception:
    pass  # Best-effort; context system may not be available

# Prefer explicit DATABASE_URL (tests, CI, one-off upgrades) over settings import.
if os.environ.get("DATABASE_URL"):
    DATABASE_URL = os.environ["DATABASE_URL"]
else:
    try:
        from amprealize.config.settings import settings

        DATABASE_URL = settings.database.postgres_url
    except ImportError:
        DATABASE_URL = os.environ.get(
            "DATABASE_URL",
            "postgresql://amprealize_user:local_dev_pw@localhost:5432/amprealize",
        )

# This is the Alembic Config object
config = context.config

# Set database URL in config (overrides alembic.ini)
# Escape % for ConfigParser interpolation
config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Add your model's MetaData object here for 'autogenerate' support
# from amprealize.models import Base
# target_metadata = Base.metadata
target_metadata = None

# Schema configuration for modular monolith architecture
# These schemas will be created/managed by Alembic
MANAGED_SCHEMAS = [
    "auth",
    "board",
    "behavior",
    "execution",
    "workflow",
    "consent",
    "audit",
    "compliance",
]

# ---------------------------------------------------------------------------
# Module-gated schema filtering
# ---------------------------------------------------------------------------
# Map DB schemas to the module that owns them.  Schemas not listed here are
# always created (auth, board, consent, audit, compliance are core/goals).
_SCHEMA_TO_MODULE: dict[str, str] = {
    "behavior": "behaviors",
    "execution": "agents",
}


def _get_enabled_schemas() -> list[str]:
    """Return MANAGED_SCHEMAS filtered to only enabled modules.

    Falls back to all schemas when config is unavailable (first run, test,
    or when ``AMPREALIZE_MIGRATE_ALL=1`` is set).
    """
    if os.environ.get("AMPREALIZE_MIGRATE_ALL", ""):
        return MANAGED_SCHEMAS

    try:
        from amprealize.config.loader import get_config
        from amprealize.module_registry import get_enabled_modules

        cfg = get_config()
        enabled_names = {m.name for m in get_enabled_modules(cfg.modules)}
    except Exception:
        # Config not loaded yet (first run) — migrate everything
        return MANAGED_SCHEMAS

    return [
        s for s in MANAGED_SCHEMAS
        if s not in _SCHEMA_TO_MODULE
        or _SCHEMA_TO_MODULE[s] in enabled_names
    ]


def include_object(object, name, type_, reflected, compare_to):
    """Filter objects for autogenerate.

    Excludes certain tables from autogenerate comparisons.
    """
    # Exclude TimescaleDB internal tables
    if type_ == "table" and name.startswith("_timescaledb"):
        return False
    # Exclude Alembic's own table
    if type_ == "table" and name == "alembic_version":
        return False
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine,
    though an Engine is acceptable here as well. By skipping the Engine
    creation we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        include_schemas=True,
        version_table_schema="public",
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine and associate a
    connection with the context.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Create managed schemas if they don't exist (module-gated)
        # Use individual commits to handle concurrent creation
        for schema in _get_enabled_schemas():
            try:
                connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
                connection.commit()
            except Exception as e:
                # Schema might already exist from concurrent migration
                if "already exists" in str(e).lower() or "duplicate key" in str(e).lower():
                    connection.rollback()
                else:
                    raise

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            include_schemas=True,
            version_table_schema="public",
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
