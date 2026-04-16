---
title: "Environment Setup"
type: howto
last_updated: 2026-04-14
applies_to:
  - dev
  - test
tags:
  - environment
  - configuration
  - venv
  - pre-commit
  - context-system
---

# Environment Setup

Detailed guide for configuring a development environment. For the quick path,
see [Getting Started](getting-started.md).

## Python Virtual Environment

```bash
python -m venv .venv
source .venv/bin/activate    # macOS/Linux
# .venv\Scripts\activate     # Windows

pip install -e ".[dev]"      # Installs core + dev extras (pytest, ruff, pre-commit)
```

## Environment Variables

Copy the example and edit:

```bash
cp .env.example .env
```

Key variables:

| Variable | Purpose | Default |
|----------|---------|---------|
| `DATABASE_URL` | Fallback DB connection | `sqlite:///~/.amprealize/data/dev.db` |
| `AMPREALIZE_AUTH_PG_DSN` | Auth service DSN | Falls back to `DATABASE_URL` |
| `AMPREALIZE_BEHAVIOR_PG_DSN` | Behavior service DSN | Falls back to `DATABASE_URL` |
| `AMPREALIZE_EXECUTION_PG_DSN` | Run/execution service DSN | Falls back to `DATABASE_URL` |
| `SECRET_KEY` | JWT signing key | Generated on first run |
| `AMPREALIZE_LOG_LEVEL` | Raze log level | `INFO` |

When using the context system, `apply_context_to_environment()` sets all DSN variables
automatically — you may not need to set them in `.env` at all.

## Context System Setup

Register and switch between backends:

```bash
# Register contexts
amprealize context add local --storage postgres --host localhost --port 5432 \
  --database amprealize --user postgres --password postgres

amprealize context add neon --storage postgres \
  --dsn "postgresql://user:pass@host/db?sslmode=require"

amprealize context add test-sqlite --storage sqlite \
  --path ~/.amprealize/data/test.db

# Switch
amprealize context use local
amprealize context validate
```

See [Context System](../reference/context-system.md) for full reference.

## Pre-commit Hooks

Install the hooks that run linting, formatting, and secret scanning before every commit:

```bash
./scripts/install_hooks.sh
# Or manually:
pre-commit install
```

Hooks include:
- **ruff** — Python linting and formatting
- **gitleaks** — Secret scanning
- **trailing-whitespace** — Whitespace cleanup

Run manually:
```bash
pre-commit run --all-files
```

## Database Migrations

```bash
alembic upgrade head                  # Apply all pending migrations
alembic heads                         # Verify single migration head
alembic revision -m "description"     # Create new migration
alembic downgrade -1                  # Roll back last migration
```

See `behavior_migrate_postgres_schema` in AGENTS.md for migration best practices.

## Standalone Packages

Two packages live under `packages/` and can be installed independently:

| Package | Purpose | Install |
|---------|---------|---------|
| **Raze** | Structured logging + telemetry | `pip install -e ./packages/raze[cli,fastapi]` |
| **BreakerAmp** | Environment/container orchestration | `pip install -e ./packages/breakeramp[cli,fastapi]` |

## VS Code Extension

```bash
cd extension
npm install
npm run compile
# Press F5 in VS Code to launch Extension Development Host
```

## Web Console

```bash
cd web-console
npm install
npm run dev       # Starts on http://localhost:5173
```

## Directory Structure

```
amprealize/
├── amprealize/          # Core Python package (services, CLI, API, MCP)
├── packages/            # Standalone packages (Raze, BreakerAmp)
├── extension/           # VS Code extension (TypeScript)
├── web-console/         # React SPA
├── mcp/                 # MCP tool schemas + handlers
├── migrations/          # Alembic migrations
├── tests/               # pytest test suite
├── scripts/             # Utility scripts
├── docs/                # Documentation + contracts
├── wiki/                # Wiki system (4 domains)
├── infra/               # Infrastructure configs
└── schema/              # JSON schemas
```
