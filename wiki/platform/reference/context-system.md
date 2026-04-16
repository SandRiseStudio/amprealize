---
title: "Context System"
type: reference
last_updated: 2026-04-14
applies_to:
  - dev
  - test
  - staging
  - prod
tags:
  - context-system
  - configuration
  - database
  - multi-backend
---

# Context System

The context system manages named database configurations so you can switch between
local Postgres, Neon cloud, SQLite, and in-memory backends without editing `.env` files.

## Core Concepts

| Concept | Description |
|---------|-------------|
| **Context** | A named configuration: storage backend + connection details |
| **Active context** | The one currently wired into the environment (`DATABASE_URL`, per-service DSNs) |
| **Storage backend** | `postgres`, `sqlite`, or `memory` |
| **Service DSN map** | Per-service schema isolation — each service can have its own DSN env var |

## Data Model

```python
@dataclass
class ContextInfo:
    name: str              # e.g. "local", "neon", "sqlite-dev"
    storage: str           # "postgres" | "sqlite" | "memory"
    port: Optional[int]    # TCP port for Postgres contexts
    valid: bool            # True if connection test passed
    port_conflict: bool    # True if another context shares the port
```

## Key Functions

| Function | Signature | Purpose |
|----------|-----------|---------|
| `get_current_context()` | `→ (name, ConfigType)` | Return active context name + full config dict |
| `get_context_name()` | `→ str` | Return just the active context name |
| `list_contexts()` | `→ List[ContextInfo]` | List all registered contexts with validation |
| `use_context(name)` | `→ None` | Switch to a named context |
| `add_context(name, ...)` | `→ None` | Register a new context (postgres, sqlite, or memory) |
| `remove_context(name)` | `→ None` | Delete a context by name |
| `check_port_conflicts()` | `→ List[ContextInfo]` | Detect port collisions between Postgres contexts |
| `validate_context_connection()` | `→ bool` | Test socket/file connectivity for active context |
| `apply_context_to_environment()` | `→ None` | Wire context DSN into `os.environ` |

## Service DSN Routing

Each service can have its own DSN environment variable, enabling per-service schema isolation:

```
AMPREALIZE_AUTH_PG_DSN        → auth service
AMPREALIZE_BOARD_PG_DSN       → board service
AMPREALIZE_BEHAVIOR_PG_DSN    → behavior service
AMPREALIZE_EXECUTION_PG_DSN   → execution/run service
AMPREALIZE_COMPLIANCE_PG_DSN  → compliance service
DATABASE_URL                  → default fallback
```

When `apply_context_to_environment()` is called, the active context's DSN is written
into **all** configured environment variables so that every service resolves correctly.

## Config File

Contexts are stored in `~/.amprealize/config.yaml` (v2 format):

```yaml
version: 2
active_context: neon
contexts:
  local:
    storage: postgres
    host: localhost
    port: 5432
    database: amprealize
    user: postgres
    password: postgres
  neon:
    storage: postgres
    dsn: postgresql://user:pass@host/db?sslmode=require
  dev-sqlite:
    storage: sqlite
    path: ~/.amprealize/data/dev.db
```

Automatic migration from v1 (flat config) to v2 (multi-context) happens on first access.

## CLI Commands

```bash
amprealize context list              # Show all contexts with status
amprealize context use <name>        # Switch active context
amprealize context add <name> ...    # Register new context
amprealize context remove <name>     # Delete context
amprealize context validate          # Test active connection
```
