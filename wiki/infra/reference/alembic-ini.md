---
title: "Alembic Migration Configuration"
type: reference
source_files:
  - alembic.ini
source_hash: auto
last_updated: "2026-04-09"
applies_to:
  - dev
  - test
  - staging
  - prod
visibility: domain-knowledge
---

# Alembic Migration Configuration

Schema versioning and data migrations via Alembic. Supports both single-database (monolith) and federation (multi-database) architectures.

## Script Location & Naming

| Setting | Value |
|---------|-------|
| Scripts directory | `migrations/` |
| Template | `%%(year)d%%(month).2d%%(day).2d_%%(hour).2d%%(minute).2d_%%(slug)s` |
| Example | `20250115_143000_create_auth_service` |
| Slug max length | 80 characters |

## Configuration

| Setting | Value |
|---------|-------|
| Timezone | UTC |
| Version path separator | OS-specific (`os.pathsep`) |
| Prepend sys.path | `.` (allows relative imports) |
| Database URL | Loaded at runtime from `env.py` (never in alembic.ini) |

## Logging

| Logger | Level |
|--------|-------|
| Alembic | INFO (tracks revision history) |
| SQLAlchemy | WARN (major issues only) |
| Root | WARN |
| Output | stderr |
| Format | `[%(levelname)s] %(name)s: %(message)s` |

## Runtime Integration

- Database URL from environment (e.g., `AMPREALIZE_ALEMBIC_DATABASE_URL` set by `run_tests.sh`)
- Schema-per-service via `search_path` in DSNs
- Connection timeout: 5s
- Statement timeout: 30s
- Tracks applied revisions in `alembic_version` table

## Migration Safety

- Explicit schema creation in migration scripts
- Supports upgrade (forward) and downgrade (rollback) operations
- Version tracking via `alembic_version` table

## See Also

- [run_tests.sh Reference](run-tests-sh.md)
- [Docker Compose Test Stack](../architecture/docker-compose-test.md)
