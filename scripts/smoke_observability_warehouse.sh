#!/usr/bin/env bash
#
# Smoke-check observability warehouse objects on the telemetry Postgres DSN.
# Requires: psql (libpq), running database with migrations applied
# (see migrations_telemetry and run_postgres_telemetry_migration.py).
#
# Usage:
#   export AMPREALIZE_TELEMETRY_PG_DSN=postgresql://user:pass@host:5432/telemetry  # pragma: allowlist secret
#   ./scripts/smoke_observability_warehouse.sh
#
set -euo pipefail

if ! command -v psql &>/dev/null; then
  echo "psql not found. Install PostgreSQL client (e.g. brew install libpq && brew link --force libpq)"
  exit 1
fi

if [[ -z "${AMPREALIZE_TELEMETRY_PG_DSN:-}" ]]; then
  echo "Set AMPREALIZE_TELEMETRY_PG_DSN to a postgres URL"
  exit 1
fi

DSN="${AMPREALIZE_TELEMETRY_PG_DSN}"
echo "=== Observability warehouse smoke (read-only) ==="
echo "DSN: ${DSN//:*@/:***@}"
echo ""

psql "${DSN}" -v ON_ERROR_STOP=1 <<'SQL'
SELECT
  to_regclass('public.telemetry_events') IS NOT NULL AS telemetry_events_table,
  to_regclass('public.observability_records') IS NOT NULL AS observability_records_table,
  EXISTS (SELECT 1 FROM pg_views WHERE schemaname = 'public' AND viewname = 'observability_span_tree') AS span_tree_view,
  EXISTS (SELECT 1 FROM pg_views WHERE schemaname = 'public' AND viewname = 'observability_run_summary') AS run_summary_view,
  EXISTS (SELECT 1 FROM pg_views WHERE schemaname = 'public' AND viewname = 'observability_conversation_summary') AS conversation_summary_view;
SELECT COUNT(*) AS telemetry_event_rows FROM telemetry_events;
SELECT COUNT(*) AS observability_record_rows FROM observability_records;
SQL

echo ""
echo "OK: smoke completed"
