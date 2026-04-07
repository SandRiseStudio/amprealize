# MCP Server Deployment Guide

This guide covers deploying Amprealize MCP (Model Context Protocol) servers to staging and production environments. MCP servers provide tool APIs for AI agents and IDE extensions.

## Overview

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Load Balancer                           │
│                    (nginx / AWS ALB / GCP LB)                   │
└──────────────────────────────┬──────────────────────────────────┘
                               │
           ┌───────────────────┼───────────────────┐
           │                   │                   │
    ┌──────▼──────┐     ┌──────▼──────┐     ┌──────▼──────┐
    │  MCP Pod 1  │     │  MCP Pod 2  │     │  MCP Pod 3  │
    │  (stdio)    │     │  (stdio)    │     │  (stdio)    │
    └──────┬──────┘     └──────┬──────┘     └──────┬──────┘
           │                   │                   │
           └───────────────────┼───────────────────┘
                               │
    ┌──────────────────────────┼──────────────────────────┐
    │              PostgreSQL Database Cluster            │
    │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐   │
    │  │Telemetry│ │Behavior │ │Workflow │ │ Action  │   │
    │  │  :5432  │ │  :5433  │ │  :5434  │ │  :5435  │   │
    │  └─────────┘ └─────────┘ └─────────┘ └─────────┘   │
    │  ┌─────────┐ ┌─────────┐                           │
    │  │   Run   │ │Compliance│                           │
    │  │  :5436  │ │  :5437  │                           │
    │  └─────────┘ └─────────┘                           │
    └─────────────────────────────────────────────────────┘
```

### MCP Server Capabilities

The Amprealize MCP server exposes **101 tools** across these namespaces:
- `behaviors.*` - Behavior retrieval, BCI generation
- `runs.*` - Run lifecycle management, progress tracking
- `actions.*` - Action registry, recording, replay
- `compliance.*` - Audit logging, policy validation
- `raze.*` - Structured logging, telemetry queries
- `breakeramp.*` - Environment orchestration, blueprints
- `metrics.*` - Telemetry aggregation, KPI tracking

### Transport Protocol

MCP uses **JSON-RPC 2.0 over stdio** for reliable, bidirectional communication:
- Client spawns MCP server as subprocess
- Messages are newline-delimited JSON
- No HTTP layer required (reduces overhead)
- Health checks via stdio health method

## Prerequisites

### Required Infrastructure

- **Docker/Podman**: Container runtime (rootless recommended)
- **PostgreSQL 14+**: 6 isolated databases (or RDS/Cloud SQL)
- **Redis 7+**: Caching and session storage
- **Python 3.11+**: MCP server runtime

### Environment Variables

```bash
# Database connections (one per service domain)
AMPREALIZE_PG_TELEMETRY_HOST=postgres-telemetry
AMPREALIZE_PG_TELEMETRY_PORT=5432
AMPREALIZE_PG_BEHAVIOR_HOST=postgres-behavior
AMPREALIZE_PG_BEHAVIOR_PORT=5433
AMPREALIZE_PG_WORKFLOW_HOST=postgres-workflow
AMPREALIZE_PG_WORKFLOW_PORT=5434
AMPREALIZE_PG_ACTION_HOST=postgres-action
AMPREALIZE_PG_ACTION_PORT=5435
AMPREALIZE_PG_RUN_HOST=postgres-run
AMPREALIZE_PG_RUN_PORT=5436
AMPREALIZE_PG_COMPLIANCE_HOST=postgres-compliance
AMPREALIZE_PG_COMPLIANCE_PORT=5437

# Credentials (injected at runtime)
AMPREALIZE_PG_USER=amprealize
AMPREALIZE_PG_PASS=<from-secrets-manager>

# Redis
AMPREALIZE_REDIS_URL=redis://redis:6379/0

# Embedding service (for behavior retrieval)
AMPREALIZE_EMBEDDING_ENABLED=true
AMPREALIZE_EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=<from-secrets-manager>

# Logging
AMPREALIZE_LOG_LEVEL=INFO
AMPREALIZE_LOG_FORMAT=json
```

## Staging Deployment

### Quick Start

```bash
# Clone repository
git clone https://github.com/SandRiseStudio/amprealize.git
cd amprealize

# Set staging secrets (env injection pattern)
export AMPREALIZE_PG_PASS_TELEMETRY=staging-telemetry-pass
export AMPREALIZE_PG_PASS_BEHAVIOR=staging-behavior-pass
export AMPREALIZE_PG_PASS_WORKFLOW=staging-workflow-pass
export AMPREALIZE_PG_PASS_ACTION=staging-action-pass
export AMPREALIZE_PG_PASS_RUN=staging-run-pass
export AMPREALIZE_PG_PASS_COMPLIANCE=staging-compliance-pass
export OPENAI_API_KEY=sk-staging-...

# Start staging stack
docker-compose -f docker-compose.staging.yml up -d

# Verify health
docker exec amprealize-mcp python -c "
import sys, json
sys.stdout.write(json.dumps({'jsonrpc':'2.0','method':'health','id':1}) + '\\n')
sys.stdout.flush()
" | head -1
```

### Staging Stack Components

The `docker-compose.staging.yml` includes:

| Service | Port | Purpose |
|---------|------|---------|
| postgres-telemetry | 5432 | Telemetry/logging warehouse |
| postgres-behavior | 5433 | Behavior embeddings/retrieval |
| postgres-workflow | 5434 | Workflow definitions |
| postgres-action | 5435 | Action registry/history |
| postgres-run | 5436 | Run lifecycle state |
| postgres-compliance | 5437 | Audit logs/policies |
| redis | 6379 | Session cache, rate limiting |
| amprealize-api | 8000 | REST API (internal) |
| amprealize-mcp | - | MCP server (stdio, no port) |
| nginx-staging | 80 | Reverse proxy (optional profile) |

### Verify Staging Deployment

```bash
# Check all containers are running
docker-compose -f docker-compose.staging.yml ps

# Check MCP health endpoint
docker exec amprealize-mcp python scripts/mcp_health_check.py

# Expected output:
# MCP Health Check: healthy
# Status: {"postgres_pools": {...}, "service_registry": {...}}

# Test tool invocation
docker exec amprealize-mcp python -c "
import json, sys
req = {'jsonrpc': '2.0', 'method': 'tools/list', 'id': 1}
sys.stdout.write(json.dumps(req) + '\\n')
" | python -c "import json, sys; print(len(json.load(sys.stdin).get('result', {}).get('tools', [])))"
# Expected: 101
```

## Production Deployment

### 1. Secrets Management

**AWS Secrets Manager** (recommended for production):

```bash
# Create secrets
aws secretsmanager create-secret \
  --name amprealize/prod/postgres-telemetry \
  --secret-string '{"username":"amprealize","password":"<strong-password>"}'

# Repeat for each database...
aws secretsmanager create-secret \
  --name amprealize/prod/openai-api-key \
  --secret-string '{"key":"sk-prod-..."}'
```

**Secrets Injection Script** (`scripts/inject_secrets.sh`):

```bash
#!/bin/bash
# Fetch secrets from AWS Secrets Manager and export as env vars

export AMPREALIZE_PG_PASS_TELEMETRY=$(aws secretsmanager get-secret-value \
  --secret-id amprealize/prod/postgres-telemetry \
  --query SecretString --output text | jq -r .password)

export AMPREALIZE_PG_PASS_BEHAVIOR=$(aws secretsmanager get-secret-value \
  --secret-id amprealize/prod/postgres-behavior \
  --query SecretString --output text | jq -r .password)

# ... repeat for all databases

export OPENAI_API_KEY=$(aws secretsmanager get-secret-value \
  --secret-id amprealize/prod/openai-api-key \
  --query SecretString --output text | jq -r .key)
```

**GCP Secret Manager** alternative:

```bash
export AMPREALIZE_PG_PASS_TELEMETRY=$(gcloud secrets versions access latest \
  --secret=amprealize-prod-postgres-telemetry)
```

### 2. TLS Configuration

For production, enable TLS between all components:

**PostgreSQL SSL** (`postgresql.conf`):
```ini
ssl = on
ssl_cert_file = '/certs/server.crt'
ssl_key_file = '/certs/server.key'
ssl_ca_file = '/certs/ca.crt'
```

**Connection strings with SSL**:
```bash
export AMPREALIZE_PG_TELEMETRY_DSN="postgresql://amprealize:${PASS}@host:5432/telemetry?sslmode=verify-full"
```

**NGINX TLS termination** (`nginx-prod.conf`):
```nginx
server {
    listen 443 ssl http2;
    server_name api.amprealize.dev;

    ssl_certificate /etc/letsencrypt/live/api.amprealize.dev/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.amprealize.dev/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;

    location / {
        proxy_pass http://amprealize_api;
        # ... proxy headers
    }
}
```

### 3. Horizontal Scaling

MCP servers are stateless - scale horizontally for throughput:

**docker-compose.prod.yml** (scaling excerpt):
```yaml
services:
  amprealize-mcp:
    image: ghcr.io/amprealize/mcp:${VERSION:-latest}
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: '2'
          memory: 4G
        reservations:
          cpus: '1'
          memory: 2G
    healthcheck:
      test: ["CMD", "python", "scripts/mcp_health_check.py"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
```

**Kubernetes Deployment** (`k8s/mcp-deployment.yaml`):
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: amprealize-mcp
  labels:
    app: amprealize-mcp
spec:
  replicas: 3
  selector:
    matchLabels:
      app: amprealize-mcp
  template:
    metadata:
      labels:
        app: amprealize-mcp
    spec:
      containers:
      - name: mcp
        image: ghcr.io/amprealize/mcp:latest
        resources:
          requests:
            memory: "2Gi"
            cpu: "1000m"
          limits:
            memory: "4Gi"
            cpu: "2000m"
        livenessProbe:
          exec:
            command: ["python", "scripts/mcp_health_check.py"]
          initialDelaySeconds: 60
          periodSeconds: 30
        readinessProbe:
          exec:
            command: ["python", "scripts/mcp_health_check.py"]
          initialDelaySeconds: 30
          periodSeconds: 10
        envFrom:
        - secretRef:
            name: amprealize-secrets
```

### 4. Database Connection Pooling

Use PgBouncer for connection pooling in production:

**pgbouncer.ini** (already in `deployment/config/`):
```ini
[databases]
telemetry = host=postgres-telemetry port=5432 dbname=amprealize_telemetry
behavior = host=postgres-behavior port=5433 dbname=amprealize_behavior
workflow = host=postgres-workflow port=5434 dbname=amprealize_workflow
action = host=postgres-action port=5435 dbname=amprealize_action
run = host=postgres-run port=5436 dbname=amprealize_run
compliance = host=postgres-compliance port=5437 dbname=amprealize_compliance

[pgbouncer]
listen_port = 6432
listen_addr = 0.0.0.0
auth_type = scram-sha-256
pool_mode = transaction
max_client_conn = 1000
default_pool_size = 20
min_pool_size = 5
reserve_pool_size = 5
```

### 5. Manual Canary Rollout

For manual canary deployments:

```bash
# Step 1: Deploy canary instance (10% traffic)
docker-compose -f docker-compose.prod.yml up -d --scale amprealize-mcp=1 amprealize-mcp-canary

# Step 2: Monitor for 30 minutes
watch -n 30 'docker exec amprealize-mcp-canary python scripts/mcp_health_check.py'

# Step 3: Check error rates
curl -s localhost:8000/metrics | grep mcp_error_rate

# Step 4: If healthy, promote to full rollout
docker-compose -f docker-compose.prod.yml up -d --scale amprealize-mcp=3 --no-recreate
docker-compose -f docker-compose.prod.yml rm -f amprealize-mcp-canary

# Step 5: If issues, rollback
docker-compose -f docker-compose.prod.yml up -d --scale amprealize-mcp=3 amprealize-mcp:previous
```

## Health Checks

### Health Endpoint

The MCP server exposes a `health` method via JSON-RPC:

```bash
# Via stdio
echo '{"jsonrpc":"2.0","method":"health","id":1}' | python -m amprealize.mcp_server

# Response:
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "status": "healthy",
    "postgres_pools": {
      "telemetry": {"active": 2, "idle": 8, "size": 10, "healthy": true},
      "behavior": {"active": 1, "idle": 9, "size": 10, "healthy": true}
    },
    "service_registry": {
      "initialized_services": ["BehaviorService", "ActionService"],
      "total_registered": 6
    },
    "tools": {
      "total_manifests": 101,
      "namespaces": ["behaviors", "runs", "actions", "compliance", "raze", "breakeramp"]
    },
    "process": {
      "memory_mb": 256.5,
      "cpu_percent": 12.3,
      "uptime_seconds": 3600
    }
  }
}
```

### Docker Health Check

The `deployment/Dockerfile.mcp` includes:

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python scripts/mcp_health_check.py || exit 1
```

### Monitoring Integration

**Prometheus metrics** (via `/metrics` endpoint on amprealize-api):
- `mcp_requests_total{method="tools/call"}` - Total tool invocations
- `mcp_request_duration_seconds` - Request latency histogram
- `mcp_errors_total{type="validation"}` - Error counts by type
- `mcp_postgres_pool_active` - Active DB connections
- `mcp_tools_available` - Tool manifest count

**Grafana dashboard** (import `deployment/config/grafana/mcp-dashboard.json`):
- Request rate and latency
- Error rate by tool namespace
- Database pool utilization
- Memory and CPU usage

## Troubleshooting

### Common Issues

#### MCP Server Won't Start

```bash
# Check logs
docker logs amprealize-mcp 2>&1 | tail -50

# Verify database connectivity
docker exec amprealize-mcp python -c "
from amprealize.db.postgres_pool import PostgresPool
import asyncio
asyncio.run(PostgresPool.get_pool_stats())
"

# Check environment variables
docker exec amprealize-mcp env | grep AMPREALIZE
```

#### Health Check Failures

```bash
# Run health check manually with verbose output
docker exec amprealize-mcp python scripts/mcp_health_check.py --verbose

# Check individual database pools
docker exec amprealize-mcp python -c "
import asyncio
from amprealize.db.postgres_pool import PostgresPool
for db in ['telemetry', 'behavior', 'workflow', 'action', 'run', 'compliance']:
    stats = asyncio.run(PostgresPool.get_pool_stats(db))
    print(f'{db}: {stats}')
"
```

#### Tool Invocation Errors

```bash
# Test specific tool
docker exec amprealize-mcp python -c "
import json, sys
req = {'jsonrpc': '2.0', 'method': 'tools/call', 'params': {'name': 'behaviors.list', 'arguments': {}}, 'id': 1}
sys.stdout.write(json.dumps(req) + '\\n')
" | python -c "import json, sys; print(json.dumps(json.load(sys.stdin), indent=2))"
```

### Log Analysis

```bash
# Aggregate MCP logs (JSON format)
docker logs amprealize-mcp 2>&1 | jq -c 'select(.level == "ERROR")'

# Count errors by type
docker logs amprealize-mcp 2>&1 | jq -r '.error_type // "unknown"' | sort | uniq -c | sort -rn
```

## Backup and Recovery

### Database Backups

```bash
# Backup all databases
for db in telemetry behavior workflow action run compliance; do
  pg_dump -h postgres-$db -U amprealize -d amprealize_$db -Fc > backup_$db_$(date +%Y%m%d).dump
done

# Restore
pg_restore -h postgres-telemetry -U amprealize -d amprealize_telemetry backup_telemetry_20250101.dump
```

### Disaster Recovery

1. **RTO Target**: 15 minutes (container restart + cache warm-up)
2. **RPO Target**: 0 (PostgreSQL synchronous replication in production)

**Recovery Steps**:
```bash
# 1. Restore from backup
./scripts/restore_databases.sh

# 2. Restart MCP services
docker-compose -f docker-compose.prod.yml restart amprealize-mcp

# 3. Verify health
docker exec amprealize-mcp python scripts/mcp_health_check.py

# 4. Warm caches
curl -X POST localhost:8000/v1/cache/warm
```

## Related Documentation

- [PODMAN_DEPLOYMENT.md](./PODMAN_DEPLOYMENT.md) - Streaming pipeline deployment
- [SECRETS_MANAGEMENT_PLAN.md](./SECRETS_MANAGEMENT_PLAN.md) - Credential rotation procedures
- [MCP_SERVER_DESIGN.md](contracts/MCP_SERVER_DESIGN.md) - MCP architecture and tool catalog
- [environments.yaml](../environments.yaml) - Environment configuration reference

---

*Following `behavior_update_docs_after_changes` (Student): Created MCP production deployment guide.*

_Last Updated: 2025-01-13_
