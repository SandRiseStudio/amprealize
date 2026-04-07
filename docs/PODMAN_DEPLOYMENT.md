# Podman Deployment Guide

This guide covers deploying the Amprealize streaming pipeline with Podman containers, offering rootless operation, better security isolation, and native systemd integration compared to Docker.

## Prerequisites

### Install Podman

**macOS:**
```bash
brew install podman
podman machine init
podman machine start
```

**Linux (Fedora/RHEL):**
```bash
sudo dnf install podman podman-compose
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt-get install podman podman-compose
```

**Windows (WSL2):**
```powershell
winget install RedHat.Podman
```

### Verify Installation

```bash
podman --version
# Podman 4.9.0 or later recommended

podman-compose --version
# If not installed: pip install podman-compose
```

## Architecture Overview

The Amprealize streaming pipeline consists of:

- **3 Zookeeper nodes** - Coordination service (HA ensemble)
- **3 Kafka brokers** - Event streaming (12 partitions, replication=3)
- **1 Schema Registry** - Avro schema management
- **1 Flink Job Manager + 3 Task Managers** - Stream processing (parallelism=6)
- **1 TimescaleDB** - Time-series warehouse (hypertables + continuous aggregates)

**Target Throughput**: 10,000 events/sec
**Target Latency**: <30s end-to-end (Kafka → Flink → TimescaleDB → dashboards)

## Quick Start

### 1. Start Telemetry Warehouse

```bash
# Start TimescaleDB first (required dependency)
podman-compose -f docker-compose.telemetry.yml up -d postgres-telemetry

# Wait for initialization
sleep 10
```

### 2. Start Streaming Pipeline

```bash
# Automated orchestration with health checks
./scripts/start_streaming_pipeline.sh start

# The script auto-detects Podman and uses podman-compose
```

### 3. Verify Services

```bash
./scripts/start_streaming_pipeline.sh status

# Expected output:
# [INFO] Zookeeper Status:
#   ✓ zookeeper-1: Running
#   ✓ zookeeper-2: Running
#   ✓ zookeeper-3: Running
# [INFO] Kafka Status:
#   ✓ kafka-1: Running
#   ✓ kafka-2: Running
#   ✓ kafka-3: Running
# [INFO] Flink Status:
#   ✓ flink-jobmanager: Running
#   ✓ flink-taskmanager-1: Running
#   ✓ flink-taskmanager-2: Running
#   ✓ flink-taskmanager-3: Running
```

### 4. Deploy Flink Streaming Job

**Production Mode** (PyFlink streaming with exactly-once semantics):
```bash
podman exec -it amprealize-flink-jobmanager \
  python /opt/flink/jobs/telemetry_kpi_job.py \
  --mode prod \
  --kafka-servers kafka-1:9092,kafka-2:9092,kafka-3:9092 \
  --postgres-dsn "postgresql://amprealize:amprealize@postgres-telemetry:5432/amprealize_telemetry"
```

**Dev Mode** (kafka-python batch processing for local testing):
```bash
podman exec -it amprealize-flink-jobmanager \
  python /opt/flink/jobs/telemetry_kpi_job.py \
  --mode dev \
  --kafka-servers kafka-1:9092
```

### 5. Access Web UIs

- **Flink Dashboard**: http://localhost:8082
- **Schema Registry**: http://localhost:8081
- **Metabase Analytics**: http://localhost:3000 (start separately with `docker-compose.analytics-dashboard.yml`)

## Podman-Specific Advantages

### Rootless Containers

Podman runs containers without root privileges by default, improving security isolation:

```bash
# All containers run as your user (no sudo required)
podman ps

# Verify rootless operation
podman info | grep rootless
# rootless: true
```

### Pod Architecture

Podman organizes containers into **pods** (Kubernetes-compatible):

```bash
# List pods created by docker-compose.streaming.yml
podman pod ps

# Inspect pod networking
podman pod inspect amprealize-streaming
```

### Systemd Integration

Run streaming pipeline as a systemd service:

```bash
# Generate systemd unit
podman-compose -f docker-compose.streaming.yml systemd

# Enable auto-start on boot
systemctl --user enable pod-amprealize-streaming.service
systemctl --user start pod-amprealize-streaming.service
```

### SELinux Compatibility

Podman respects SELinux policies on Fedora/RHEL:

```bash
# Volume mounts use :Z suffix for proper labeling
# Already configured in docker-compose.streaming.yml
```

## Manual Deployment Steps

If you prefer manual control over the orchestration script:

### 1. Start Zookeeper Ensemble

```bash
podman-compose -f docker-compose.streaming.yml up -d zookeeper-1 zookeeper-2 zookeeper-3
sleep 15
```

### 2. Start Kafka Cluster

```bash
podman-compose -f docker-compose.streaming.yml up -d kafka-1 kafka-2 kafka-3
sleep 30
```

### 3. Initialize Kafka Topics

```bash
podman-compose -f docker-compose.streaming.yml up kafka-init
```

Expected topics (12 partitions, replication=3):
- `telemetry.events` - Raw event stream
- `telemetry.spans` - Distributed tracing spans
- `telemetry.kpis` - Projected KPI facts

### 4. Start Schema Registry

```bash
podman-compose -f docker-compose.streaming.yml up -d schema-registry
sleep 10
```

### 5. Start Flink Cluster

```bash
podman-compose -f docker-compose.streaming.yml up -d flink-jobmanager
sleep 10
podman-compose -f docker-compose.streaming.yml up -d flink-taskmanager-1 flink-taskmanager-2 flink-taskmanager-3
sleep 20
```

## Configuration

### Environment Variables

Override defaults via `.env` file or export:

```bash
# Kafka Configuration
export KAFKA_HEAP_OPTS="-Xms2G -Xmx2G"
export KAFKA_NUM_PARTITIONS=12
export KAFKA_REPLICATION_FACTOR=3

# Flink Configuration
export FLINK_PARALLELISM=6
export FLINK_TASKMANAGER_SLOTS=3
export FLINK_CHECKPOINT_INTERVAL=60000  # 60s

# PostgreSQL Configuration
export AMPREALIZE_PG_POOL_MIN_SIZE=5
export AMPREALIZE_PG_POOL_MAX_SIZE=20
export AMPREALIZE_PG_POOL_TIMEOUT=30000

# Telemetry Sink Configuration
export KAFKA_TELEMETRY_BATCH_SIZE=1000
export KAFKA_TELEMETRY_LINGER_MS=100
export KAFKA_TELEMETRY_COMPRESSION="gzip"
```

### Runtime Selection

Force specific container runtime:

```bash
# Force Podman
export CONTAINER_RUNTIME=podman
export COMPOSE_TOOL=podman-compose
./scripts/start_streaming_pipeline.sh start

# Or use Docker (fallback)
export CONTAINER_RUNTIME=docker
export COMPOSE_TOOL=docker-compose
./scripts/start_streaming_pipeline.sh start
```

## Monitoring & Troubleshooting

### View Logs

```bash
# All services
podman-compose -f docker-compose.streaming.yml logs -f

# Specific service
podman-compose -f docker-compose.streaming.yml logs -f kafka-1
podman-compose -f docker-compose.streaming.yml logs -f flink-jobmanager

# Follow Flink job output
podman exec -it amprealize-flink-jobmanager tail -f /opt/flink/log/flink-*-jobmanager-*.log
```

### Resource Usage

```bash
# Per-container stats
podman stats

# Pod-level stats
podman pod stats
```

### Health Checks

```bash
# Kafka broker health
podman exec -it amprealize-kafka-1 kafka-broker-api-versions --bootstrap-server localhost:9092

# Flink job status
curl http://localhost:8082/jobs

# Schema Registry
curl http://localhost:8081/subjects
```

### Common Issues

#### Port Conflicts

```bash
# Check if ports are already bound
ss -tuln | grep -E '8081|8082|19092|19093|19094'

# If conflicts exist, update docker-compose.streaming.yml port mappings
```

#### Memory Limits

Ensure Podman has sufficient resources:

```bash
# macOS: Increase podman machine memory
podman machine stop
podman machine set --memory 24576  # 24GB
podman machine start

# Linux: Check cgroup limits
cat /sys/fs/cgroup/memory/memory.limit_in_bytes
```

#### Container Restarts

```bash
# Inspect exit reason
podman logs amprealize-kafka-1

# Check restart policy
podman inspect amprealize-kafka-1 | grep -A5 RestartPolicy
```

## Cleanup

### Stop Services

```bash
./scripts/start_streaming_pipeline.sh stop
```

### Remove Volumes

```bash
podman-compose -f docker-compose.streaming.yml down -v
```

### Prune All Resources

```bash
# Remove stopped containers
podman container prune -f

# Remove unused volumes
podman volume prune -f

# Remove unused images
podman image prune -a -f
```

## Production Considerations

### Persistent Storage

The compose file mounts volumes for:
- Kafka data: `kafka-1-data`, `kafka-2-data`, `kafka-3-data`
- Zookeeper data: `zookeeper-1-data`, `zookeeper-2-data`, `zookeeper-3-data`
- Flink checkpoints: `flink-checkpoints`, `flink-savepoints`

Back up these volumes regularly:

```bash
podman volume inspect kafka-1-data
# Copy mountpoint to backup location
```

### High Availability

For production, consider:
- **External Zookeeper**: Dedicated cluster outside Podman (e.g., AWS MSK)
- **Managed Kafka**: Confluent Cloud or AWS MSK
- **Flink on Kubernetes**: Deploy Flink via K8s CRD for auto-scaling

### Security Hardening

```bash
# Enable TLS for Kafka
# Update docker-compose.streaming.yml with SSL configuration

# Restrict network access
podman network create amprealize-private --internal
# Update compose file to use private network
```

### Metrics & Alerting

Integrate with Prometheus + Grafana:

```bash
# Expose JMX metrics from Kafka/Flink
# Configure Prometheus scrape targets
# Import Kafka/Flink Grafana dashboards
```

## Migration from Docker

Podman is Docker-compatible, so migration is straightforward:

```bash
# 1. Alias podman to docker (optional)
alias docker=podman
alias docker-compose=podman-compose

# 2. Use existing docker-compose.yml files as-is
podman-compose -f docker-compose.streaming.yml up -d

# 3. Import Docker volumes (if needed)
docker save image:tag | podman load
```

## References

- [Podman Documentation](https://docs.podman.io/)
- [podman-compose GitHub](https://github.com/containers/podman-compose)
- [Amprealize Streaming Architecture](STREAMING_PIPELINE_ARCHITECTURE.md)
- [Flink Job Specification](../deployment/flink/telemetry_kpi_job.py)
- [PRD Sprint 3 Requirements](../PRD.md#sprint-3)

---

**Next Steps:**
- Test Flink job deployment: `podman exec -it amprealize-flink-jobmanager python /opt/flink/jobs/telemetry_kpi_job.py --mode prod`
- Set up Metabase dashboards: `podman-compose -f docker-compose.analytics-dashboard.yml up -d`
- Run load tests to validate 10k events/sec target
- Configure systemd auto-start for production environments
