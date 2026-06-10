# Observability rollout and operations

This runbook covers self-hosted (OSS) **telemetry warehouse** + **observability** enablement, optional **OTLP export**, and **repair backfills** after schema upgrades. It supports **GUIDEAI-1196** / goal **GUIDEAI-1189**.

## Test coverage map (GUIDEAI-1237)

| Area | Primary tests |
|------|----------------|
| Postgres sink + fact/observability projection | `tests/test_postgres_telemetry_sink.py` |
| Replay / backfill from `telemetry_events` | `tests/test_telemetry_replay_backfill.py` |
| Trace facade / context | `tests/test_observability_tracing_*.py`, `tests/test_observability_attributes.py` |
| Trace HTTP API | `tests/test_observability_trace_api.py`, `tests/test_observability_access.py` |
| OTLP export runtime | `tests/test_observability_export_runtime.py` |
| MCP / REST instrumentation | `tests/test_mcp_tool_telemetry.py`, `tests/test_api_http_telemetry_middleware.py` |
| Postgres warehouse (live DB, CI) | `tests/test_observability_telemetry_integration.py` (`pytest --run-integration`; job `observability-telemetry-integration` in `.github/workflows/ci.yml`) |

Normative event matrix: `docs/contracts/TELEMETRY_SCHEMA.md`. Add targeted integration tests when wiring new `event_type` branches in `PostgresTelemetryWarehouse._project_event`.

## Prerequisites

- PostgreSQL or Timescale with the telemetry schema applied. Use `scripts/run_postgres_telemetry_migration.py` and Alembic **`migrations_telemetry`** (see `docs/MIGRATION_GUIDE.md` if present, and `migrations_telemetry/versions/*observability*`).
- `AMPREALIZE_TELEMETRY_PG_DSN` set to the **telemetry** database (not the main app DB unless intentionally combined).

## Rollout order

1. **Network / secrets**: set `AMPREALIZE_TELEMETRY_PG_DSN`; avoid committing secrets (`behavior_prevent_secret_leaks`).
2. **Schema**: apply base telemetry warehouse migration, then **`migrations_telemetry`** through head (`telemetry_observability_analytics` adds `observability_span_tree`, run/conversation summaries, indexes).
3. **Runtime**: configure sinks via `create_sink_from_env` / `AMPREALIZE_EXPORT_*` per [`OTLP export`](../contracts/OTLP_EXPORT.md) when exporting to collectors or vendors.
4. **Verification**: REST trace routes + web trace explorer; warehouse SQL (below).

## Verification checklist

| Check | How |
|-------|-----|
| Events landing | `SELECT COUNT(*) FROM telemetry_events;` |
| Canonical rows | `SELECT COUNT(*) FROM observability_records;` |
| Analytics views | `./scripts/smoke_observability_warehouse.sh` |
| OTLP (optional) | Follow OTLP doc + collector logs |
| API | Governed trace endpoints per `docs/contracts/` trace contracts |
| Warehouse integration (CI) | Job **`observability-telemetry-integration`** in `.github/workflows/ci.yml` runs `pytest tests/test_observability_telemetry_integration.py --run-integration` against the telemetry Postgres service (Alembic `alembic.telemetry.ini upgrade head`). |

## Replay / backfill (`telemetry_events` → projections)

If **`telemetry_events`** existed before observability typed tables/views, or projections were skipped during an outage, replay **without duplicating** append-only telemetry inserts:

```bash
export AMPREALIZE_TELEMETRY_PG_DSN=postgresql://...
./scripts/backfill_observability_records_from_telemetry_events.py --dry-run
./scripts/backfill_observability_records_from_telemetry_events.py --limit 5000 --offset 0
```

Options: `--since`, `--until` (ISO 8601), `--limit`, `--offset`, `--dry-run`.

Implementation calls `PostgresTelemetryWarehouse.replay_event_projections_from_telemetry_table()`, which reuses `_project_event` (same logic as live ingestion). Rows use **`ON CONFLICT DO NOTHING`** where defined so replays are safe.

## Managed-enterprise warehouse SQL

For **`enterprise_warehouse.*`** views (Looker / BI parity), see [`docs/analytics/observability_warehouse_views.sql`](../analytics/observability_warehouse_views.sql).

## Tests

- Replay helpers (mocked): `pytest tests/test_telemetry_replay_backfill.py -q`
- Sink projections (mocked): `pytest tests/test_postgres_telemetry_sink.py -q`
- **Telemetry Postgres integration** (opt-in): requires telemetry DB + migrations + `--run-integration`:
  `pytest tests/test_observability_telemetry_integration.py --run-integration -q`
  (`pytest.mark.telemetry_pg_only` skips monolith Alembic when this file is run alone.)

See also [`docs/TESTING_GUIDE.md`](TESTING_GUIDE.md) — Observability testing section.
