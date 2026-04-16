---
title: "Getting Started"
type: howto
last_updated: 2026-04-14
applies_to:
  - dev
tags:
  - getting-started
  - installation
  - quickstart
---

# Getting Started

Get Amprealize running locally in under 5 minutes. This guide covers the OSS edition;
see [Editions](../reference/editions.md) for enterprise features.

## Prerequisites

- Python 3.11+
- Git
- One of: PostgreSQL 15+, SQLite 3, or Neon cloud account

## 1. Clone and install

```bash
git clone https://github.com/amprealize/amprealize.git
cd amprealize
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## 2. Configure a context

Choose your storage backend:

**SQLite (simplest)**
```bash
amprealize context add dev-sqlite --storage sqlite --path ~/.amprealize/data/dev.db
amprealize context use dev-sqlite
```

**Local PostgreSQL**
```bash
amprealize context add local --storage postgres \
  --host localhost --port 5432 --database amprealize \
  --user postgres --password postgres
amprealize context use local
```

**Neon cloud**
```bash
amprealize context add neon --storage postgres \
  --dsn "postgresql://user:pass@host/db?sslmode=require"
amprealize context use neon
```

Verify connectivity:
```bash
amprealize context validate
amprealize context list
```

See [Context System](../reference/context-system.md) for full reference.

## 3. Set up environment

```bash
cp .env.example .env
# Edit .env — set DATABASE_URL if not using context system
```

Install pre-commit hooks:
```bash
./scripts/install_hooks.sh
```

## 4. Run database migrations

```bash
alembic upgrade head
```

## 5. Start the server

```bash
uvicorn amprealize.api:app --reload --port 8000
```

The API is now available at `http://localhost:8000/docs`.

## 6. Initialize MCP

```bash
amprealize mcp init
amprealize mcp doctor  # Verify MCP health
```

MCP tools are now available in VS Code Copilot Chat.

## 7. Try it out

```bash
# Create a behavior
amprealize behaviors create --name "behavior_hello_world" \
  --description "Demo behavior"

# List behaviors
amprealize behaviors list

# Run a health check
amprealize compliance validate
```

## Next Steps

- [Environment Setup](environment-setup.md) — detailed dev environment configuration
- [Running Tests](run-tests.md) — run the test suite
- [Surfaces](../reference/surfaces.md) — explore all 5 access surfaces
- [MCP Tool Families](../reference/mcp-tools.md) — browse 64+ MCP tools
