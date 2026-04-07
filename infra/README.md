# Telemetry Pipeline Deployment

> **Owner:** Engineering + DevOps
> **Last Updated:** 2025-10-16
> **Status:** Phase 1 (Local Development) Complete

## Overview
This directory contains infrastructure-as-code for deploying the Amprealize telemetry pipeline that processes events from CLI, VS Code, API, and MCP surfaces into PRD KPI fact tables.

## Architecture

```
┌─────────────┐      ┌──────────┐      ┌─────────┐      ┌────────────────┐
│ Telemetry   │─────>│  Kafka   │─────>│  Flink  │─────>│    DuckDB      │
│ Clients     │ JSONL│ Broker   │Stream│ KPI Job │Facts │  (Phase 1)     │
│ CLI/VS Code │      │  (topic) │      │Projector│      │  PostgreSQL    │
└─────────────┘      └──────────┘      └─────────┘      │  (Phase 2)     │
                                                         │  Snowflake*    │
                                                         └────────────────┘
```

### Components
- **Kafka** - Message broker for `telemetry.events` topic
- **Flink** - Stream processor running `TelemetryKPIProjector`
- **Warehouse** - Fact table storage (configurable):
  - **DuckDB** (Phase 1) - Embedded columnar database, zero-cost, local development
  - **PostgreSQL + TimescaleDB** (Phase 2) - Free open-source, production-ready
  - **Snowflake** (Legacy) - Paid service, optional support
- **Telemetry Clients** - Emit events via `TelemetryClient`

## Quick Start (Local Development)

### Prerequisites
- **Container Runtime**: Docker Desktop, Podman, or Podman Desktop (recommended for lighter weight - see [`PODMAN.md`](PODMAN.md))
- Python 3.11+ with Amprealize installed
- **No cloud accounts required for Phase 1** (DuckDB is embedded, zero-cost)

> **💡 Podman Users:** See [`PODMAN.md`](PODMAN.md) for Podman-specific setup (lighter weight alternative to Docker Desktop)

### 1. Start Infrastructure

#### Option A: Docker Desktop
```bash
# Start Kafka + Flink cluster
docker compose -f docker-compose.telemetry.yml up -d

# Verify services are running
docker ps | grep amprealize
```

#### Option B: Podman (Lighter Weight)
```bash
# Start services with Podman
podman-compose -f docker-compose.telemetry.yml up -d

# Verify services
podman ps | grep amprealize
```

See [`PODMAN.md`](PODMAN.md) for complete Podman installation and setup instructions.

### 2. Configure Environment

```bash
# Copy and customize dev config
cp deployment/config/telemetry.dev.env deployment/config/telemetry.local.env

# Default uses DuckDB (no credentials needed)
# For PostgreSQL/Snowflake, edit telemetry.local.env with credentials
vim deployment/config/telemetry.local.env

# Load environment
set -a; source deployment/config/telemetry.local.env; set +a
```

### 3. Deploy Flink Job

```bash
# Install dependencies (DuckDB is default)
pip install -e ".[telemetry]"

# Or explicitly install all warehouse backends
pip install -e ".[telemetry,postgres]"  # Adds PostgreSQL support

# Start streaming job (runs in foreground)
python deployment/flink/telemetry_kpi_job.py
```

### 4. Validate Pipeline

```bash
# Run end-to-end smoke test
./scripts/validate_telemetry_pipeline.sh
```

## Emit Telemetry Events

### Via CLI
```bash
amprealize telemetry emit \
  --event-type execution_update \
  --run-id test-run-001 \
  --payload '{"status": "SUCCESS", "output_tokens": 120, "baseline_tokens": 200}' \
  --sink kafka \
  --kafka-servers localhost:9092
```

### Via Python
```python
from amprealize.telemetry import TelemetryClient, KafkaTelemetrySink

sink = KafkaTelemetrySink(bootstrap_servers="localhost:9092")
client = TelemetryClient(sink=sink)

client.emit(
    event_type="execution_update",
    actor={"id": "user-123", "role": "STRATEGIST"},
    run_id="run-001",
    payload={"status": "SUCCESS", "behaviors_cited": ["behavior_123"]}
)
```

## Monitoring

- **Kafka UI**: http://localhost:8080 (browse topics, messages)
- **Flink Dashboard**: http://localhost:8081 (job status, metrics)
- **DuckDB**: Query fact tables with CLI or Python client

```bash
# Query DuckDB via CLI
duckdb data/telemetry.duckdb "SELECT * FROM fact_behavior_usage ORDER BY event_timestamp DESC LIMIT 10;"

# Or via Python
python -c "import duckdb; conn = duckdb.connect('data/telemetry.duckdb'); print(conn.execute('SELECT COUNT(*) FROM fact_behavior_usage').fetchone())"
```

## Configuration Reference

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka broker endpoints | `localhost:9092` |
| `KAFKA_TOPIC_TELEMETRY_EVENTS` | Topic name | `telemetry.events` |
| `WAREHOUSE_TYPE` | Warehouse backend | `duckdb` |
| `DUCKDB_PATH` | DuckDB file path (Phase 1) | `data/telemetry.duckdb` |
| `POSTGRES_HOST` | PostgreSQL host (Phase 2) | `localhost` |
| `POSTGRES_PORT` | PostgreSQL port | `5432` |
| `POSTGRES_DATABASE` | PostgreSQL database | `amprealize` |
| `POSTGRES_USER` | PostgreSQL username | Required (Phase 2) |
| `POSTGRES_PASSWORD` | PostgreSQL password | Required (Phase 2) |
| `SNOWFLAKE_ACCOUNT` | Snowflake account URL (Legacy) | Optional |
| `SNOWFLAKE_USER` | Snowflake username (Legacy) | Optional |
| `SNOWFLAKE_PASSWORD` | Snowflake password (Legacy) | Optional |
| `SNOWFLAKE_DATABASE` | Database name (Legacy) | `AMPREALIZE_DEV` |
| `SNOWFLAKE_SCHEMA` | Schema name (Legacy) | `prd_metrics` |
| `SNOWFLAKE_SCHEMA` | Schema name | `prd_metrics` |
| `PROJECTION_BATCH_SIZE` | Events per batch | `1000` |
| `PROJECTION_FLUSH_INTERVAL_MS` | Max wait time (ms) | `60000` |

## Troubleshooting

### Kafka not accepting events
```bash
# Check topic exists
kafka-topics --bootstrap-server localhost:9092 --list

# Create topic manually if needed
kafka-topics --bootstrap-server localhost:9092 --create \
  --topic telemetry.events --partitions 3 --replication-factor 1

# Tail messages (Docker)
docker exec amprealize-kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic telemetry.events --from-beginning

# Tail messages (Podman)
podman exec amprealize-kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic telemetry.events --from-beginning
```

### Flink job not starting
```bash
# Check logs (Docker)
docker logs amprealize-flink-jobmanager
docker logs amprealize-flink-taskmanager

# Check logs (Podman)
podman logs amprealize-flink-jobmanager
podman logs amprealize-flink-taskmanager

# Restart Flink cluster (Docker)
docker compose -f docker-compose.telemetry.yml restart flink-jobmanager flink-taskmanager

# Restart Flink cluster (Podman)
podman-compose -f docker-compose.telemetry.yml restart flink-jobmanager flink-taskmanager
```

### Podman-specific issues
See [`PODMAN.md`](PODMAN.md) for Podman troubleshooting, including:
- Machine initialization issues
- Volume mount permissions
- Network configuration
- Resource allocation

### Flink job not starting
```bash
# Check logs
docker logs amprealize-flink-jobmanager
docker logs amprealize-flink-taskmanager

# Restart Flink cluster
docker compose -f docker-compose.telemetry.yml restart flink-jobmanager flink-taskmanager
```

### Warehouse connection errors

**DuckDB (Phase 1)**
```bash
# Test DuckDB connection
python -c "import duckdb; conn = duckdb.connect('data/telemetry.duckdb'); print('OK')"

# Verify file exists and is writable
ls -lh data/telemetry.duckdb
```

**PostgreSQL (Phase 2)**
```bash
# Test PostgreSQL connection
python -c "import psycopg2; conn = psycopg2.connect(host='localhost', port=5432, database='amprealize', user='$POSTGRES_USER', password='$POSTGRES_PASSWORD'); print('OK')"

# Verify credentials
echo $POSTGRES_HOST
echo $POSTGRES_USER
```

**Snowflake (Legacy)**
```bash
# Test Snowflake connection
python -c "import snowflake.connector; print('OK')"

# Verify credentials
echo $SNOWFLAKE_ACCOUNT
echo $SNOWFLAKE_USER
```

## Production Deployment (Phase 2)

Phase 2 will migrate from Docker Compose to production infrastructure:

- **Kafka**: Confluent Cloud or AWS MSK
- **Flink**: Kubernetes deployment or AWS Kinesis Data Analytics
- **Warehouse**: PostgreSQL + TimescaleDB (free open-source, production-ready)
- **Monitoring**: Datadog/Prometheus + Grafana dashboards
- **Monitoring**: Datadog/Prometheus integration
- **CI/CD**: Automated deployment via GitHub Actions

See `docs/analytics/prd_kpi_dashboard_plan.md` for full roadmap.

## Related Documentation

- [`docs/analytics/prd_kpi_dashboard_plan.md`](../docs/analytics/prd_kpi_dashboard_plan.md) - Dashboard implementation plan
- [`docs/analytics/prd_metrics_schema_duckdb.sql`](../docs/analytics/prd_metrics_schema_duckdb.sql) - **DuckDB schema DDL (Phase 1)**
- [`TELEMETRY_SCHEMA.md`](../docs/contracts/TELEMETRY_SCHEMA.md) - Event schema specification
- [`amprealize/analytics/telemetry_kpi_projector.py`](../amprealize/analytics/telemetry_kpi_projector.py) - Projection logic
- [`PODMAN.md`](PODMAN.md) - Lightweight container runtime alternative
- [`CONTAINER_COMPARISON.md`](CONTAINER_COMPARISON.md) - Docker Desktop vs Podman

## Support

For questions or issues:
- Review validation script output: `./scripts/validate_telemetry_pipeline.sh`
- Check Kafka UI: http://localhost:8080
- Check Flink Dashboard: http://localhost:8081
- Reference `AGENTS.md` behaviors: `behavior_instrument_metrics_pipeline`, `behavior_orchestrate_cicd`
