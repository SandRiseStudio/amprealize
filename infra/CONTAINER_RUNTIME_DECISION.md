# Container Runtime Standardization Decision

**Date:** 2025-10-23
**Status:** ✅ Implemented
**Decision:** Standardize on Podman as Amprealize's primary container runtime

## Context

Amprealize deployment previously supported both Docker Desktop and Podman as container runtimes. To simplify operations, reduce resource overhead, and align with lightweight infrastructure goals, we are standardizing on **Podman**.

## Decision

**Amprealize uses Podman** as the standard container runtime for:
- Local development
- CI/CD pipelines
- Production deployments
- Analytics infrastructure (already in use)

## Rationale

### Why Podman?

1. **Already in Use**
   - Analytics dashboard deployment uses `podman-compose`
   - Metabase runs via `docker-compose.analytics-dashboard.yml` with Podman
   - Team already familiar with Podman workflows

2. **Lightweight & Daemonless**
   - No background daemon required (~500 MB vs Docker Desktop's 2-4 GB idle)
   - Containers run as child processes, not via daemon
   - Faster startup, lower resource consumption

3. **Rootless Security**
   - Run containers without root privileges
   - Better isolation and security posture
   - Aligns with least-privilege principle

4. **Docker CLI Compatibility**
   - Drop-in replacement: `alias docker=podman`
   - Same commands, same workflows
   - Existing Docker Compose files work with `podman-compose`

5. **Kubernetes-Native**
   - Generate Kubernetes YAML directly: `podman generate kube`
   - Seamless transition to K8s/OpenShift
   - Pod-based architecture mirrors K8s pods

6. **Systemd Integration**
   - Native systemd service generation
   - Automatic restart policies
   - Better production daemon management

## Implementation

### Files Updated

- ✅ `.github/workflows/ci.yml` - Updated deployment comments to reference Podman
- ✅ `deployment/CICD_DEPLOYMENT_GUIDE.md` - Added Podman section with examples
- ✅ `BUILD_TIMELINE.md` #84 - Documented Podman as standard container runtime

### Existing Podman Infrastructure

- ✅ `deployment/PODMAN.md` - Comprehensive Podman setup guide
- ✅ `deployment/CONTAINER_COMPARISON.md` - Docker vs Podman comparison
- ✅ `deployment/QUICKSTART.md` - Includes Podman quick start
- ✅ `deployment/README.md` - Documents both runtimes
- ✅ `docker-compose.analytics-dashboard.yml` - Works with podman-compose
- ✅ `docker-compose.telemetry.yml` - Works with podman-compose
- ✅ `scripts/validate_telemetry_pipeline.sh` - Auto-detects Podman/Docker

## Migration Path

For developers currently using Docker Desktop:

```bash
# 1. Stop Docker Desktop containers
docker-compose -f docker-compose.analytics-dashboard.yml down

# 2. Install Podman (macOS)
brew install podman podman-compose

# 3. Initialize Podman machine
podman machine init --cpus 4 --memory 4096 --disk-size 50
podman machine start

# 4. Create docker alias (optional for compatibility)
alias docker=podman
alias docker-compose=podman-compose

# 5. Restart services with Podman
podman-compose -f docker-compose.analytics-dashboard.yml up -d
```

## CI/CD Integration

GitHub Actions workflow (`.github/workflows/ci.yml`) now references Podman:

```yaml
# Build Podman images
podman build -t amprealize-api:latest .

# Push to container registry (GHCR, Quay.io)
podman tag amprealize-api:latest ghcr.io/nas4146/amprealize-api:latest
podman push ghcr.io/nas4146/amprealize-api:latest

# Deploy with Podman Compose
podman-compose up -d
```

## Production Deployment

### Podman Pod Architecture

```bash
# Generate Kubernetes-compatible manifests
podman generate kube amprealize-api > deployment/k8s/api-deployment.yaml

# Deploy to Kubernetes/OpenShift directly
kubectl apply -f deployment/k8s/api-deployment.yaml

# Or use Podman systemd services for bare-metal
podman generate systemd --name amprealize-api > /etc/systemd/system/amprealize-api.service
systemctl enable --now amprealize-api
```

### Container Registry

**Recommended:** GitHub Container Registry (GHCR) or Quay.io
- Both support Podman natively
- Free for public repositories
- Good integration with GitHub Actions

```bash
# GHCR example
podman login ghcr.io
podman push ghcr.io/nas4146/amprealize-api:latest
```

## Backwards Compatibility

**Compose Files Remain Compatible:**
- `docker-compose.*.yml` files work with both Docker and Podman
- Standard Compose spec v3 syntax
- No breaking changes for existing deployments

**For Teams Using Docker Desktop:**
- Can continue using Docker if needed
- CI/CD defaults to Podman but tolerates Docker
- Migration encouraged but not forced

## Documentation Updates

All documentation now prioritizes Podman while acknowledging Docker compatibility:

- Primary examples use `podman` commands
- Docker alternatives noted where relevant
- Migration guides provided for Docker users

## Benefits Realized

✅ **Resource Savings**: ~1.5-3.5 GB memory reduction per developer
✅ **Security Improvement**: Rootless containers by default
✅ **Consistency**: Same runtime for dev, CI, and production
✅ **Kubernetes Readiness**: Pod architecture maps directly to K8s
✅ **Operational Simplicity**: No daemon management overhead

## Related Documents

- [`deployment/PODMAN.md`](PODMAN.md) - Podman setup guide
- [`deployment/CICD_DEPLOYMENT_GUIDE.md`](CICD_DEPLOYMENT_GUIDE.md) - CI/CD with Podman
- [`deployment/CONTAINER_COMPARISON.md`](CONTAINER_COMPARISON.md) - Feature comparison
- [`BUILD_TIMELINE.md`](../BUILD_TIMELINE.md) #52, #84 - Podman implementation history

## Behaviors Applied

- ✅ `behavior_orchestrate_cicd` - CI/CD pipeline with Podman
- ✅ `behavior_update_docs_after_changes` - Documentation updated
- ✅ `behavior_externalize_configuration` - Container configs standardized

_Last Updated: 2025-10-23_
