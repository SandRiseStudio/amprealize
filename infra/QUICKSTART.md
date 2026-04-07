# Phase 1 Telemetry Pipeline - Quick Start Guide

## 🎯 What We Built
Local development telemetry pipeline (Kafka → Flink → **DuckDB**) for processing Amprealize events into PRD KPI facts.
- **Phase 1**: DuckDB (embedded, zero-cost, local development)
- **Phase 2**: PostgreSQL + TimescaleDB (production, free open-source)
- **Legacy**: Snowflake (paid service, optional support)

## 🚀 Quick Start

### 0. Choose Container Runtime

**Docker Desktop** (Traditional)
- Full-featured but heavier (~2-4 GB memory)
- Install: https://www.docker.com/products/docker-desktop

**Podman** (Recommended - Lighter Weight)
- Daemonless, lighter footprint (~500 MB memory)
- Install: `brew install podman podman-compose`
- Setup: See [`PODMAN.md`](PODMAN.md) for complete guide

### 1. Install Dependencies
```bash
# Install optional telemetry dependencies
pip install -e ".[telemetry]"
```

### 2. Start Infrastructure

#### With Docker Desktop:
```bash
# Start Kafka + Flink cluster
docker compose -f docker-compose.telemetry.yml up -d

# Verify services
docker ps | grep amprealize
```

#### With Podman (Lighter Weight):
```bash
# Initialize Podman machine (first time only)
podman machine init --cpus 4 --memory 4096
podman machine start

# Start services
podman-compose -f docker-compose.telemetry.yml up -d

# Verify services
podman ps | grep amprealize
```

### 3. Configure Warehouse (Default: DuckDB)
```bash
# Copy config template
cp deployment/config/telemetry.dev.env deployment/config/telemetry.local.env

# DuckDB requires no additional config (uses embedded database at data/telemetry.duckdb)
# For PostgreSQL/Snowflake, edit telemetry.local.env with credentials

# Load environment
set -a; source deployment/config/telemetry.local.env; set +a
```

### 4. Start Flink Job
```bash
# Run in separate terminal
python deployment/flink/telemetry_kpi_job.py
```

### 5. Validate End-to-End
```bash
# Run smoke test
./scripts/validate_telemetry_pipeline.sh
```

## 📊 Monitoring Endpoints

- **Kafka UI**: http://localhost:8080 (browse topics/messages)
- **Flink Dashboard**: http://localhost:8081 (job status/metrics)
- **DuckDB**: Query fact tables with `duckdb data/telemetry.duckdb` (CLI) or Python client

## 🧪 Emit Test Events

### Via CLI (when implemented)
```bash
amprealize telemetry emit \
  --event-type execution_update \
  --run-id test-001 \
  --payload '{"status": "SUCCESS", "output_tokens": 120}' \
  --sink kafka
```

### Via Python
```python
from amprealize.telemetry import TelemetryClient, KafkaTelemetrySink

sink = KafkaTelemetrySink(bootstrap_servers="localhost:9092")
client = TelemetryClient(sink=sink)

client.emit_event(
    event_type="execution_update",
    actor={"id": "user-123", "role": "STRATEGIST", "surface": "CLI"},
    run_id="run-001",
    payload={"status": "SUCCESS", "behaviors_cited": ["behavior_123"]}
)
```

## 📁 Key Files

| File | Purpose |
|------|---------|
| `docker-compose.telemetry.yml` | Infrastructure (Kafka, Flink, UI) |
| `deployment/flink/telemetry_kpi_job.py` | Streaming processor |
| `deployment/config/telemetry.dev.env` | Configuration template |
| `scripts/validate_telemetry_pipeline.sh` | E2E smoke test |
| `deployment/README.md` | Full documentation |
| `amprealize/telemetry.py` | Telemetry client + sinks |

## 🔧 Troubleshooting

### Kafka not accepting events
```bash
# Verify topic exists
docker exec amprealize-kafka kafka-topics --bootstrap-server localhost:9092 --list

# Tail messages
docker exec amprealize-kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic telemetry.events --from-beginning
```

### Flink job fails
```bash
# Check logs
docker logs amprealize-flink-jobmanager
docker logs amprealize-flink-taskmanager

# Restart
docker compose -f docker-compose.telemetry.yml restart
```

## 📋 Next Steps

### Immediate (Complete Phase 1 - DuckDB)
- [ ] Run validation script and verify output
- [ ] Emit test events via Python client
- [ ] Confirm events flow Kafka → Flink → DuckDB
- [ ] Query fact tables: `duckdb data/telemetry.duckdb "SELECT * FROM fact_behavior_usage LIMIT 10;"`

### Phase 2 (Production Deployment - PostgreSQL)
- [ ] Provision managed Kafka (Confluent Cloud / AWS MSK)
- [ ] Deploy Flink on Kubernetes
- [ ] Configure PostgreSQL + TimescaleDB warehouse (free open-source)
- [ ] Add monitoring (Datadog/Prometheus)
- [ ] Set up CI/CD automation

### Phase 3 (Analytics Dashboards)
- [ ] Provision Metabase/Looker workspace
- [ ] Build 4 executive KPI tiles
- [ ] Create drill-down views
- [ ] Add compliance evidence explorer

## 🤝 Support

- Full docs: [`deployment/README.md`](../deployment/README.md)
- Dashboard plan: [`docs/analytics/prd_kpi_dashboard_plan.md`](../docs/analytics/prd_kpi_dashboard_plan.md)
- Schema (DuckDB): [`docs/analytics/prd_metrics_schema_duckdb.sql`](../docs/analytics/prd_metrics_schema_duckdb.sql)
- Behaviors: `behavior_instrument_metrics_pipeline`, `behavior_orchestrate_cicd`
