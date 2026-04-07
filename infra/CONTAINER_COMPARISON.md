# Container Runtime Comparison: Docker Desktop vs Podman

## Quick Decision Matrix

| Consideration | Docker Desktop | Podman | Recommendation |
|--------------|----------------|---------|----------------|
| **Memory Usage (Idle)** | 2-4 GB | ~500 MB | ✅ Podman |
| **Disk Space** | ~10 GB | ~2 GB | ✅ Podman |
| **Setup Complexity** | Simple (GUI installer) | Moderate (CLI + machine init) | Docker Desktop |
| **GUI** | Included | Optional (Podman Desktop) | Docker Desktop |
| **Compose Support** | Native | Via podman-compose | Docker Desktop |
| **Security** | Requires root | Rootless by default | ✅ Podman |
| **Open Source** | Partially | Fully (Apache 2.0) | ✅ Podman |
| **Commercial Use** | May require license | Free | ✅ Podman |

## Recommendation

**Choose Podman if:**
- ✅ You want minimal resource usage (~75% less memory)
- ✅ Disk space is limited
- ✅ You prefer open-source solutions
- ✅ You're comfortable with CLI tools
- ✅ You want rootless containers

**Choose Docker Desktop if:**
- ✅ You prefer GUI management
- ✅ You need maximum compatibility
- ✅ You want zero setup complexity
- ✅ You already have Docker Desktop installed

## Installation Instructions

### Podman Setup (Recommended for Amprealize)
```bash
# 1. Install Podman
brew install podman podman-compose

# 2. Initialize machine
podman machine init --cpus 4 --memory 4096 --disk-size 50
podman machine start

# 3. Verify
podman --version
podman info

# 4. Run telemetry pipeline
cd /Users/nick/amprealize
podman-compose -f docker-compose.telemetry.yml up -d
```

### Docker Desktop Setup
```bash
# 1. Download from https://www.docker.com/products/docker-desktop
# 2. Install via GUI
# 3. Run telemetry pipeline
cd /Users/nick/amprealize
docker compose -f docker-compose.telemetry.yml up -d
```

## Resource Impact on Amprealize Telemetry Pipeline

### Docker Desktop
```
Base system usage:  2-4 GB RAM
Kafka container:    512 MB
Flink containers:   1 GB
Zookeeper:          256 MB
Kafka UI:           128 MB
--------------------------------
Total:              ~4-6 GB RAM
```

### Podman
```
Base system usage:  ~500 MB RAM
Kafka container:    512 MB
Flink containers:   1 GB
Zookeeper:          256 MB
Kafka UI:           128 MB
--------------------------------
Total:              ~2.4 GB RAM
```

**Savings: ~60% less RAM usage with Podman**

## Command Compatibility

Both systems use identical commands for Amprealize workflows:

```bash
# Starting pipeline (either works)
docker compose -f docker-compose.telemetry.yml up -d
podman-compose -f docker-compose.telemetry.yml up -d

# Checking status
docker ps | grep amprealize
podman ps | grep amprealize

# Viewing logs
docker logs amprealize-kafka
podman logs amprealize-kafka

# Validation
./scripts/validate_telemetry_pipeline.sh  # Auto-detects runtime
```

## Complete Documentation

- **Podman Setup**: [`deployment/PODMAN.md`](PODMAN.md) - Complete guide with troubleshooting
- **General Deployment**: [`deployment/README.md`](README.md) - Supports both runtimes
- **Quick Start**: [`deployment/QUICKSTART.md`](QUICKSTART.md) - Fast setup for both

## Migration from Docker Desktop to Podman

```bash
# 1. Stop Docker Desktop containers
docker compose -f docker-compose.telemetry.yml down

# 2. Install Podman
brew install podman podman-compose

# 3. Initialize Podman machine
podman machine init --cpus 4 --memory 4096
podman machine start

# 4. Start with Podman
podman-compose -f docker-compose.telemetry.yml up -d

# 5. Verify
podman ps
./scripts/validate_telemetry_pipeline.sh
```

## Support

For Podman-specific questions:
- Review [`deployment/PODMAN.md`](PODMAN.md)
- Check [Podman Documentation](https://docs.podman.io/)
- Visit [Podman Desktop](https://podman-desktop.io/)

For general pipeline issues:
- Review [`deployment/README.md`](README.md)
- Run validation: `./scripts/validate_telemetry_pipeline.sh`
