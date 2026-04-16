---
title: "pyproject.toml — Project Metadata & Dependencies"
type: reference
source_files:
  - pyproject.toml
source_hash: auto
last_updated: "2026-04-09"
applies_to:
  - dev
  - test
  - staging
  - prod
visibility: domain-knowledge
---

# pyproject.toml — Project Metadata & Dependencies

Python 3.10+ project configured with setuptools. Monorepo with local packages (raze, breakeramp) as editable installs.

## Project Metadata

| Field | Value |
|-------|-------|
| Name | `amprealize` |
| Version | `0.1.0` |
| Python | ≥ 3.10 |
| License | Apache-2.0 |
| Homepage | https://breakeramp.dev |
| Source | https://github.com/SandRiseStudio/amprealize |

## Core Dependencies

| Category | Packages |
|----------|----------|
| API | FastAPI 0.110+, Uvicorn 0.30+ |
| Database | SQLAlchemy 2.0+, psycopg2-binary 2.9+, Alembic 1.13+ |
| Cache/MQ | Redis 5.0+, Kafka-Python 2.0+ |
| Auth | PyJWT 2.8+, bcrypt 4.1+ |
| Cloud | boto3 1.28+ (S3/MinIO) |
| Config | Pydantic 2.5+, PyYAML 6.0+ |
| Container | Podman 5.0+ |
| LLM | OpenAI 1.0+, Anthropic 0.40+ |

## Optional Extras

| Extra | Key Packages | Use Case |
|-------|-------------|----------|
| `dev` | pytest, pytest-cov, pytest-asyncio, pytest-xdist, flake8, mypy | Development & testing |
| `telemetry` | kafka-python, duckdb, pytz | Telemetry backend |
| `postgres` | sqlalchemy, psycopg2, prometheus_client, alembic | PostgreSQL support |
| `semantic` | sentence-transformers, faiss-cpu | Semantic search |
| `ml` | torch, scipy (includes semantic) | Heavy ML workloads |
| `redis` | redis | Redis client |
| `breakeramp` | breakeramp[cli] 0.1.0+ | Environment management |
| `enterprise` | amprealize-enterprise ~0.1.0 | Enterprise features |

## Entry Points

| Script | Description |
|--------|-------------|
| `amprealize` | Main CLI |
| `amprealize-mcp-server` | MCP server |

## See Also

- [Alembic Configuration](alembic-ini.md)
- [Docker Image Build](../architecture/docker-compose-test.md)
