# Resource Management Guide

## Current Resource Usage (as of 2025-10-29)

| Resource | Size | Impact | Can Remove? |
|----------|------|--------|-------------|
| HuggingFace models (~/.cache/huggingface) | **4.3 GB** | High | ⚠️ Yes, but will re-download |
| Podman images | **~2.1 GB** | High | ⚠️ Partial (keep timescaledb:latest-pg16, redis:7-alpine) |
| Python venv (.venv) | 894 MB | Low | ❌ No (needed for development) |
| Extension node_modules | 82 MB | Low | ⚠️ Yes (can reinstall) |
| Project data (data/) | 7 MB | Minimal | ❌ No (contains your data) |
| Python cache (__pycache__) | ~4,520 files | Minimal | ✅ Yes (regenerates automatically) |

## Quick Cleanup Commands

### Option 1: Light Cleanup (~100 MB, SAFE)
```bash
# Remove stopped containers
podman container prune -f

# Remove Python cache
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -name "*.pyc" -delete

# Remove dangling images
podman image prune -f
```

### Option 2: Moderate Cleanup (~1-2 GB)
```bash
# Stop non-essential containers (keep behavior DB running)
podman stop amprealize-postgres-telemetry amprealize-postgres-workflow \
  amprealize-postgres-action amprealize-postgres-run amprealize-postgres-compliance \
  amprealize-redis

# Remove analytics infrastructure (not needed for Phase 3)
podman stop amprealize-metabase amprealize-kafka amprealize-zookeeper amprealize-kafka-ui 2>/dev/null || true
podman rm amprealize-metabase amprealize-kafka amprealize-zookeeper amprealize-kafka-ui 2>/dev/null || true
podman rmi metabase/metabase:v0.48.0 confluentinc/cp-kafka:7.5.0 \
  confluentinc/cp-zookeeper:7.5.0 provectuslabs/kafka-ui:latest \
  dpage/pgadmin4:latest 2>/dev/null || true
```

### Option 3: Aggressive Cleanup (~4-5 GB)
```bash
# CAUTION: Removes HuggingFace models (will re-download on next use)
rm -rf ~/.cache/huggingface

# This frees the most space but requires ~60 seconds download time
# next time you run semantic search
```

## What You Need for Phase 3 (Performance Optimization)

**Essential containers:**
- ✅ `amprealize-postgres-behavior` (running) - stores behaviors and embeddings
- ✅ `amprealize-redis` (optional) - for result caching

**Can stop/remove:**
- ❌ `amprealize-postgres-telemetry` - not needed for Phase 3
- ❌ `amprealize-postgres-workflow` - not needed for Phase 3
- ❌ `amprealize-postgres-action` - not needed for Phase 3
- ❌ `amprealize-postgres-run` - not needed for Phase 3
- ❌ `amprealize-postgres-compliance` - not needed for Phase 3
- ❌ Analytics stack (Metabase, Kafka, Zookeeper) - not needed for Phase 3

**Essential Python packages (keep venv):**
- sentence-transformers (for embedding generation)
- faiss-cpu (for FAISS index)
- psycopg2 (for PostgreSQL)
- Basic dependencies

## Recommended Cleanup for Phase 3 Work

Run the interactive script:
```bash
./scripts/cleanup_resources.sh
```

Or manually execute:
```bash
# 1. Stop unnecessary Postgres containers
podman stop amprealize-postgres-telemetry amprealize-postgres-workflow \
  amprealize-postgres-action amprealize-postgres-run amprealize-postgres-compliance

# 2. Remove stopped containers
podman container prune -f

# 3. Remove analytics infrastructure
podman stop amprealize-metabase amprealize-kafka amprealize-zookeeper amprealize-kafka-ui 2>/dev/null || true
podman rm amprealize-metabase amprealize-kafka amprealize-zookeeper amprealize-kafka-ui 2>/dev/null || true

# 4. Remove large unused images
podman rmi metabase/metabase:v0.48.0 \
  confluentinc/cp-kafka:7.5.0 \
  confluentinc/cp-zookeeper:7.5.0 \
  provectuslabs/kafka-ui:latest \
  dpage/pgadmin4:latest \
  flink:1.18-scala_2.12-java11 2>/dev/null || true

# 5. Clean Python cache
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -name "*.pyc" -delete
```

**Expected savings: ~2-3 GB**

## Restarting Containers Later

When you need them again:
```bash
# Start behavior database
podman start amprealize-postgres-behavior

# Start Redis cache
podman start amprealize-redis

# Recreate analytics (if needed)
podman-compose -f docker-compose.analytics-dashboard.yml up -d

# Recreate other services (if needed)
podman-compose -f docker-compose.postgres.yml up -d
```

## Monitoring Resource Usage

Check current usage anytime:
```bash
# Disk usage
du -sh ~/.cache/huggingface ~/.amprealize .venv data

# Container status
podman ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Size}}"

# Image sizes
podman images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"

# Python cache count
find . -name "*.pyc" -o -name "__pycache__" -type d | wc -l
```

## Should I Remove HuggingFace Models?

**Keep if:**
- You'll continue working on semantic search features
- You have reasonable disk space (>10 GB free)
- You don't want to wait 60 seconds for re-download

**Remove if:**
- You're critically low on disk space (<5 GB free)
- You won't work on semantic features for a while
- You're okay with one-time re-download later

The BAAI/bge-m3 model (2.27 GB compressed, 4.3 GB uncompressed) can be safely removed and will re-download automatically when needed.
