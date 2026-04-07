at# Agent Execution Architecture

> **Status**: Planning → Implementation
> **Author**: Architecture Review (2026-01-16)
> **Tracking**: BUILD_TIMELINE.md #155+

## Executive Summary

This document describes the rearchitecture of Amprealize's agent execution system from an inline API-based model to a queue-based worker architecture with BreakerAmp as the unified control plane.

### Goals

1. **Horizontal API Scaling** - API servers become stateless; execution moves to workers
2. **Execution Resilience** - Runs survive API restarts; workers can be scaled independently
3. **Tenant Isolation** - Per-org workspace pools with resource quotas
4. **Unified Control Plane** - BreakerAmp manages all workspace lifecycle

### Non-Goals (This Phase)

- Kubernetes deployment (staying with Podman)
- Multi-region deployment
- Real-time collaboration on agent outputs

---

## Current State (Problems)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    CURRENT ARCHITECTURE (Problems)                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐                     │
│  │    UI    │  │   API    │  │   MCP    │  │   CLI    │                     │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘                     │
│       └─────────────┴──────┬──────┴─────────────┘                            │
│                            ▼                                                 │
│                    ┌──────────────┐                                          │
│                    │  amprealize-api │                                          │
│                    │              │                                          │
│                    │ ⚠️ Agent execution runs INLINE                         │
│                    │ ⚠️ asyncio.create_task() - no backpressure             │
│                    │ ⚠️ API restart = lost executions                       │
│                    │ ⚠️ Can't scale API horizontally                        │
│                    └──────┬───────┘                                          │
│                           │                                                  │
│            ┌──────────────┼──────────────┐                                   │
│            ▼              ▼              ▼                                   │
│     ┌──────────┐   ┌──────────┐   ┌─────────────────┐                        │
│     │ amprealize  │   │  redis   │   │ workspace-agent │                        │
│     │   -db    │   │          │   │ ⚠️ Disabled     │                        │
│     └──────────┘   └──────────┘   │ ⚠️ macOS issues │                        │
│                                   └─────────────────┘                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Specific Issues

| Issue | Impact | Severity |
|-------|--------|----------|
| Agent execution in API process | Can't scale API; execution blocks requests | 🔴 Critical |
| No execution queue | No backpressure; can overload system | 🔴 Critical |
| workspace-agent disabled | Agents execute without isolation | 🔴 Critical |
| API restart loses runs | Poor reliability; user frustration | 🟠 High |
| No tenant workspace limits | Noisy neighbor; resource exhaustion | 🟠 High |
| No execution timeouts | Zombie runs consume resources | 🟡 Medium |

---

## Target Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         TARGET ARCHITECTURE                                      │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│   SURFACES                                                                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                                       │
│  │    UI    │  │   API    │  │   CLI    │  ◄─── HTTP surfaces via Gateway       │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘                                       │
│       │             │             │                                              │
│       └─────────────┴──────┬──────┘                                              │
│                            │                                                     │
│   ════════════════════════════════════════════════════════════════════════════  │
│                            │  Gateway Layer (HTTP only)                          │
│                            ▼                                                     │
│                    ┌───────────────┐                                             │
│                    │    Gateway    │  ◄─── Auth, Rate Limiting, Routing          │
│                    │   (nginx)     │       Tenant Context Injection              │
│                    └───────┬───────┘       WebSocket Upgrade Support             │
│                            │                                                     │
│  ┌──────────┐              │                                                     │
│  │   MCP    │──────────────┤  ◄─── MCP: subprocess/stdio (no gateway)           │
│  │ (stdio)  │              │       Direct in-process access to services         │
│  └──────────┘              │                                                     │
│                            │                                                     │
│   ════════════════════════════════════════════════════════════════════════════  │
│                            │  Application Layer (Stateless, Scalable)            │
│            ┌───────────────┼───────────────┐                                     │
│            ▼               ▼               ▼                                     │
│     ┌────────────┐  ┌────────────┐  ┌────────────┐                               │
│     │ amprealize-api│  │ amprealize-api│  │ amprealize-api│  ◄─── Horizontal scaling      │
│     │ (replica 1)│  │ (replica 2)│  │ (replica N)│      No agent execution here  │
│     └─────┬──────┘  └─────┬──────┘  └─────┬──────┘                               │
│           │               │               │                                      │
│           └───────────────┴───────┬───────┘                                      │
│                                   │ XADD (enqueue execution)                     │
│   ════════════════════════════════════════════════════════════════════════════  │
│                                   │  Message Queue Layer                         │
│                                   ▼                                              │
│     ┌─────────────────────────────────────────────────────────────────────┐     │
│     │              Redis Streams: amprealize:executions:{priority}            │     │
│     │                                                                       │     │
│     │  • Consumer groups for horizontal worker scaling                      │     │
│     │  • Priority queues (high/normal/low) with tenant boost               │     │
│     │  • Dead letter queue for failed executions                            │     │
│     │  • Backpressure via queue depth monitoring                            │     │
│     └───────────────────────────────┬───────────────────────────────────────┘     │
│                                     │ XREADGROUP (claim work)                    │
│   ════════════════════════════════════════════════════════════════════════════  │
│                                     │  Control Plane Layer (Singleton/HA)        │
│                                     ▼                                            │
│     ┌─────────────────────────────────────────────────────────────────────┐     │
│     │                     BREAKERAMP ORCHESTRATOR                          │     │
│     │  (Unified control plane for agent execution)                         │     │
│     │                                                                       │     │
│     │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │     │
│     │  │   Agent     │  │  Workspace  │  │  Resource   │  │  Compliance │ │     │
│     │  │  Scheduler  │  │  Manager    │  │  Quotas     │  │  Enforcer   │ │     │
│     │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘ │     │
│     │                                                                       │     │
│     │  • Receives agent execution requests via message queue                │     │
│     │  • Provisions isolated workspaces per tenant/run                      │     │
│     │  • Enforces resource quotas (CPU, memory, time)                       │     │
│     │  • Manages workspace lifecycle (create, monitor, destroy)             │     │
│     │  • Applies compliance policies (audit, data residency)                │     │
│     │  • Heartbeat monitoring for zombie detection                          │     │
│     └───────────────────────────┬───────────────────────────────────────────┘     │
│                                 │                                                │
│   ════════════════════════════════════════════════════════════════════════════  │
│                                 │  Execution Layer (Per-Tenant Isolation)        │
│            ┌────────────────────┼────────────────────┐                           │
│            ▼                    ▼                    ▼                           │
│   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐                 │
│   │ Tenant A Pool   │  │ Tenant B Pool   │  │ Tenant C Pool   │                 │
│   │ (org:tenant-a)  │  │ (org:tenant-b)  │  │ (user:user-123) │ ◄── org-optional│
│   │                 │  │                 │  │                 │                 │
│   │ ┌─────────────┐ │  │ ┌─────────────┐ │  │ ┌─────────────┐ │                 │
│   │ │ workspace-1 │ │  │ │ workspace-1 │ │  │ │ workspace-1 │ │                 │
│   │ │ (run-abc)   │ │  │ │ (run-xyz)   │ │  │ │ (run-123)   │ │                 │
│   │ │ podman ctr  │ │  │ │ podman ctr  │ │  │ │ podman ctr  │ │                 │
│   │ └─────────────┘ │  │ └─────────────┘ │  │ └─────────────┘ │                 │
│   │ ┌─────────────┐ │  │                 │  │ ┌─────────────┐ │                 │
│   │ │ workspace-2 │ │  │                 │  │ │ workspace-2 │ │                 │
│   │ │ (run-def)   │ │  │                 │  │ │ (run-456)   │ │                 │
│   │ └─────────────┘ │  │                 │  │ └─────────────┘ │                 │
│   │                 │  │                 │  │                 │                 │
│   │ Limits: 5 conc  │  │ Limits: 1 conc  │  │ Limits: 1 conc  │                 │
│   │ Timeout: 1hr    │  │ Timeout: 10min  │  │ Timeout: 10min  │ ◄── plan-based  │
│   │ Memory: 2GB     │  │ Memory: 512MB   │  │ Memory: 512MB   │                 │
│   └─────────────────┘  └─────────────────┘  └─────────────────┘                 │
│                                                                                  │
│   ════════════════════════════════════════════════════════════════════════════  │
│                                 │  Data Layer                                    │
│            ┌────────────────────┼────────────────────┐                           │
│            ▼                    ▼                    ▼                           │
│     ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                    │
│     │  PostgreSQL  │    │    Redis     │    │ TimescaleDB  │                    │
│     │  (amprealize)   │    │  (queues,    │    │ (telemetry)  │                    │
│     │              │    │   state)     │    │              │                    │
│     └──────────────┘    └──────────────┘    └──────────────┘                    │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Key Design Decisions

### 0. Gateway Layer (nginx)

**Decision**: Add nginx gateway for cross-cutting concerns

**Responsibilities**:
| Concern | Implementation |
|---------|----------------|
| **Authentication** | JWT validation, API key verification |
| **Rate Limiting** | Per-tenant limits (token bucket algorithm) |
| **Routing** | Load balance across API replicas (round-robin) |
| **Tenant Context** | Extract org_id/user_id from token, inject as headers |
| **WebSocket Upgrade** | Support for real-time collaboration (per COLLAB_SAAS_REQUIREMENTS.md) |
| **TLS Termination** | HTTPS → HTTP to backends |

**Why nginx over API-level middleware**:
- Rate limiting at edge prevents overload from reaching API pods
- Centralized auth reduces per-replica token validation overhead
- WebSocket upgrade handling is cleaner at gateway level
- Matches COLLAB_SAAS_REQUIREMENTS.md pattern for "100ms perceived latency"

**Configuration highlights**:
```nginx
upstream amprealize_api {
    least_conn;
    server amprealize-api-1:8080;
    server amprealize-api-2:8080;
    server amprealize-api-3:8080;
}

# Rate limiting zone per tenant (extracted from JWT sub claim)
limit_req_zone $jwt_claim_org_id zone=tenant_limit:10m rate=100r/s;

location /api/ {
    limit_req zone=tenant_limit burst=200 nodelay;
    proxy_pass http://amprealize_api;
    proxy_set_header X-Tenant-Id $jwt_claim_org_id;
    proxy_set_header X-User-Id $jwt_claim_sub;
}

# WebSocket support for real-time collaboration
location /ws/ {
    proxy_pass http://amprealize_api;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 3600s;  # 1 hour for long-lived connections
}
```

### 1. Redis Streams vs Kafka

**Decision**: Start with Redis Streams

| Factor | Redis Streams | Kafka |
|--------|--------------|-------|
| Complexity | Low | High |
| Throughput needed | 10K/sec | 100K+/sec |
| Operational overhead | Already have Redis | New infrastructure |
| Consumer groups | ✅ Supported | ✅ Supported |
| Message retention | Configurable | Configurable |

**Migration path**: If we exceed 10K executions/sec, migrate to Kafka. The `execution-queue` package abstracts the transport.

### 2. Execution Timeouts by Plan

**Decision**: Tier-based timeouts with heartbeat monitoring

| Plan | Max Execution Time | Max Concurrent | Workspace Memory |
|------|-------------------|----------------|------------------|
| Free | 10 minutes | 1 | 512MB |
| Pro | 1 hour | 5 | 2GB |
| Enterprise | 4 hours | 20 | 4GB |

**Implementation**:
- Workers send heartbeats every 30 seconds
- Orchestrator monitors last heartbeat
- Zombie detection: no heartbeat for 2 minutes → terminate
- Runs can resume from checkpoint if workspace still exists

### 3. Workspace-Agent Package Consolidation

**Decision**: Move valuable parts to BreakerAmp, delete gRPC service

| Component | Action | New Location |
|-----------|--------|--------------|
| `PodmanSocketClient` | Move | `breakeramp.runtime.podman` |
| `WorkspaceService` | Move | `breakeramp.orchestrator` |
| `StateStore` (Redis) | Move | `breakeramp.state` |
| Models | Move | `breakeramp.models` |
| gRPC server | Delete | - |
| gRPC client | Delete | - |
| Proto definitions | Delete | - |

The `amprealize/workspace_agent/` wrapper becomes a thin import from breakeramp.

### 4. Tenant Isolation (Orgs Optional)

**Decision**: Org-scoped isolation when org exists, user-scoped fallback

```python
def get_isolation_scope(user_id: str, org_id: Optional[str]) -> str:
    """Get the isolation scope for workspace provisioning."""
    if org_id:
        return f"org:{org_id}"
    return f"user:{user_id}"
```

**Quota enforcement**:
- With org: quotas from org's billing plan
- Without org: quotas from user's individual plan (default: free tier)

---

## Implementation Phases

### Phase 0: Gateway Layer (Week 0 - Parallel)

**Objective**: Add nginx gateway for auth, rate limiting, and WebSocket support

This phase runs in parallel with Phase 1 since it's infrastructure-level.

#### 0.1 Create Gateway Configuration

**File**: `config/nginx/amprealize.conf`

```nginx
# Rate limiting zones
limit_req_zone $http_x_tenant_id zone=tenant_api:10m rate=100r/s;
limit_req_zone $http_x_tenant_id zone=tenant_ws:10m rate=10r/s;

upstream amprealize_api {
    least_conn;
    server amprealize-api:8080;
    keepalive 32;
}

server {
    listen 80;
    listen 443 ssl;
    server_name api.amprealize.dev;

    # API endpoints with rate limiting
    location /api/ {
        limit_req zone=tenant_api burst=200 nodelay;

        proxy_pass http://amprealize_api;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Timeout for long-running requests (SSE, etc.)
        proxy_read_timeout 300s;
    }

    # WebSocket endpoints for real-time collaboration
    location /ws/ {
        limit_req zone=tenant_ws burst=20 nodelay;

        proxy_pass http://amprealize_api;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;

        # 1 hour timeout for collaboration sessions
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    # Health check endpoint (no rate limiting)
    location /health {
        proxy_pass http://amprealize_api/health;
    }
}
```

#### 0.2 Update Blueprint with Gateway

**File**: `packages/breakeramp/src/breakeramp/blueprints/local-test-suite.yaml`

Add `gateway` service to the `core` module.

#### 0.3 Auth Middleware Integration

The gateway extracts tenant context from JWT and passes as headers:
- `X-Tenant-Id`: org_id or user_id (isolation scope)
- `X-User-Id`: authenticated user
- `X-User-Plan`: billing plan for quota enforcement

API replicas trust these headers (gateway-authenticated).

#### Phase 0 Deliverables

- [x] `config/nginx/nginx.conf` configuration
- [x] Blueprint updated with `gateway` service
- [x] Rate limiting per tenant (100r/s API, 10r/s WS)
- [x] WebSocket upgrade support
- [x] SSE streaming support
- [x] Health check passthrough
- [x] Integration tests (26 tests)

**Status**: ✅ COMPLETE - Implemented 2026-01-16

---

### Phase 1: Execution Queue Foundation (Week 1) ✅ COMPLETE

**Status**: Implemented 2026-01-16. See BUILD_TIMELINE.md #155.

**Objective**: Decouple execution from API using Redis Streams

#### 1.1 Create `packages/execution-queue/`

```
packages/execution-queue/
├── pyproject.toml
├── README.md
└── src/execution_queue/
    ├── __init__.py
    ├── models.py          # ExecutionJob, ExecutionResult, Priority
    ├── publisher.py       # Enqueue jobs via XADD
    ├── consumer.py        # Consume jobs via XREADGROUP
    ├── backpressure.py    # Queue depth monitoring
    └── dead_letter.py     # Failed job handling
```

**Key interfaces**:

```python
# models.py
class Priority(Enum):
    HIGH = "high"      # Human-initiated, interactive
    NORMAL = "normal"  # Standard agent runs
    LOW = "low"        # Background/batch operations

@dataclass
class ExecutionJob:
    job_id: str
    run_id: str
    work_item_id: str
    agent_id: str
    priority: Priority
    # Tenant context (org optional)
    user_id: str
    org_id: Optional[str]
    project_id: str
    # Execution config
    model_override: Optional[str]
    timeout_seconds: int
    # Metadata
    submitted_at: datetime
    payload: Dict[str, Any]

# publisher.py
class ExecutionQueuePublisher:
    async def enqueue(self, job: ExecutionJob) -> str:
        """Enqueue job, returns stream message ID."""

    async def get_queue_depth(self, priority: Priority) -> int:
        """Get current queue depth for backpressure."""

# consumer.py
class ExecutionQueueConsumer:
    async def consume(self, handler: Callable[[ExecutionJob], Awaitable[None]]) -> None:
        """Consume jobs from queue, call handler for each."""

    async def ack(self, job_id: str) -> None:
        """Acknowledge job completion."""

    async def nack(self, job_id: str, reason: str) -> None:
        """Negative ack, move to dead letter queue."""
```

#### 1.2 Modify WorkItemExecutionService

**File**: `amprealize/work_item_execution_service.py`

**Before**:
```python
async def execute(self, request: ExecuteWorkItemRequest) -> ExecuteWorkItemResponse:
    # ... validation ...
    run = await self._run_service.create_run(...)
    asyncio.create_task(self._run_execution_loop(run))  # ← Problem
    return ExecuteWorkItemResponse(run_id=run.id, status="running")
```

**After**:
```python
async def execute(self, request: ExecuteWorkItemRequest) -> ExecuteWorkItemResponse:
    # ... validation ...
    run = await self._run_service.create_run(...)

    # Enqueue for worker processing
    job = ExecutionJob(
        job_id=str(uuid4()),
        run_id=run.id,
        work_item_id=request.work_item_id,
        agent_id=agent.id,
        priority=self._determine_priority(request),
        user_id=request.user_id,
        org_id=request.org_id,  # Optional
        project_id=request.project_id,
        model_override=request.model_override,
        timeout_seconds=await self._get_timeout(request.org_id, request.user_id),
        submitted_at=datetime.utcnow(),
        payload=request.payload,
    )
    await self._queue.enqueue(job)

    return ExecuteWorkItemResponse(run_id=run.id, status="queued")
```

#### 1.3 Create ExecutionWorker

**File**: `amprealize/execution_worker.py`

```python
class ExecutionWorker:
    """Worker process that consumes and executes agent runs."""

    def __init__(
        self,
        consumer: ExecutionQueueConsumer,
        orchestrator: AmpOrchestrator,
        run_service: RunService,
    ):
        self.consumer = consumer
        self.orchestrator = orchestrator
        self.run_service = run_service
        self._running = False

    async def start(self):
        """Start consuming from queue."""
        self._running = True
        await self.consumer.consume(self._handle_job)

    async def _handle_job(self, job: ExecutionJob):
        """Handle a single execution job."""
        try:
            # Update run status
            await self.run_service.update_status(job.run_id, "running")

            # Provision isolated workspace
            workspace = await self.orchestrator.provision_workspace(
                run_id=job.run_id,
                scope=get_isolation_scope(job.user_id, job.org_id),
                timeout_seconds=job.timeout_seconds,
            )

            # Execute agent loop
            loop = AgentExecutionLoop(
                run_id=job.run_id,
                workspace=workspace,
                # ... other deps ...
            )
            result = await loop.run()

            # Cleanup workspace
            await self.orchestrator.cleanup_workspace(
                run_id=job.run_id,
                retain_on_failure=result.failed,
            )

            # Update final status
            await self.run_service.complete(job.run_id, result)
            await self.consumer.ack(job.job_id)

        except Exception as e:
            await self.run_service.fail(job.run_id, str(e))
            await self.consumer.nack(job.job_id, str(e))
```

#### 1.4 Update Blueprint

**File**: `packages/breakeramp/src/breakeramp/blueprints/local-test-suite.yaml`

Add execution-worker service:

```yaml
  # ---------------------------------------------------------------------------
  # MODULE: WORKERS - Execution Workers
  # ---------------------------------------------------------------------------

  execution-worker:
    image: docker.io/library/python:3.11-slim-bookworm
    module: console  # Part of core dev environment
    depends_on:
      - amprealize-db
      - redis
    volumes:
      - "${AMPREALIZE_REPO_ROOT:-.}:/app"
      - "execution-worker-pip-cache:/root/.cache/pip"
      # Worker owns Podman socket for workspace provisioning
      - "${PODMAN_SOCKET_PATH:-/run/podman/podman.sock}:/run/podman/podman.sock:rw"
    workdir: /app
    command:
      - "sh"
      - "-c"
      - "pip install -e . -e ./packages/breakeramp -e ./packages/execution-queue && python -m amprealize.execution_worker"
    environment:
      REDIS_URL: "redis://redis:6379/0"
      DATABASE_URL: "${DATABASE_URL}"
      WORKER_CONCURRENCY: "5"
      WORKER_ID: "${HOSTNAME:-worker-1}"
    deploy:
      replicas: 1  # Scale up for production
    healthcheck:
      test: ["CMD-SHELL", "python -c 'import redis; r=redis.from_url(\"redis://redis:6379/0\"); r.ping()'"]
      interval: 10s
      timeout: 5s
      retries: 3
```

#### Phase 1 Deliverables

- [x] `packages/execution-queue/` package with publisher/consumer
- [x] `WorkItemExecutionService` publishes to queue
- [x] `amprealize/execution_worker.py` consumes and executes
- [x] Blueprint updated with `execution-worker` service
- [x] Runs survive API restarts
- [x] Integration tests for queue flow

---

### Phase 2: BreakerAmp Workspace Orchestration (Week 2)

**Objective**: Consolidate workspace management into BreakerAmp

#### 2.1 Move Podman Client to BreakerAmp

**From**: `packages/workspace-agent/src/workspace_agent/podman_client.py`
**To**: `packages/breakeramp/src/breakeramp/runtime/podman.py`

Keep the same implementation, update imports.

#### 2.2 Create AmpOrchestrator

**File**: `packages/breakeramp/src/breakeramp/orchestrator.py`

```python
@dataclass
class WorkspaceConfig:
    """Configuration for an agent workspace."""
    run_id: str
    scope: str  # "org:{org_id}" or "user:{user_id}"

    # Resource limits (from tenant plan)
    memory_limit: str = "2g"
    cpu_limit: float = 2.0
    timeout_seconds: int = 3600

    # Optional: GitHub repo to clone
    github_repo: Optional[str] = None
    github_token: Optional[str] = None
    github_branch: str = "main"

@dataclass
class WorkspaceInfo:
    """Runtime info about a provisioned workspace."""
    run_id: str
    container_id: str
    container_name: str
    status: str
    created_at: datetime
    workspace_path: str

class AmpOrchestrator:
    """Unified control plane for agent workspace management.

    Replaces:
    - workspace-agent gRPC service
    - AmprealizeWorkspaceClient wrapper
    - Manual Podman commands
    """

    def __init__(
        self,
        podman: PodmanClient,
        state: StateStore,
        hooks: Optional[BreakerAmpHooks] = None,
    ):
        self.podman = podman
        self.state = state
        self.hooks = hooks or BreakerAmpHooks()

    async def provision_workspace(self, config: WorkspaceConfig) -> WorkspaceInfo:
        """Provision an isolated container workspace for agent execution."""

        # Check quota
        await self._enforce_quota(config.scope)

        # Create container
        container = await self.podman.create_container(
            name=f"workspace-{config.run_id}",
            image="ghcr.io/amprealize/agent-runtime:latest",
            memory_limit=config.memory_limit,
            cpu_limit=config.cpu_limit,
            labels={
                "amprealize.run_id": config.run_id,
                "amprealize.scope": config.scope,
            },
        )

        # Clone repo if specified
        if config.github_repo:
            await self.podman.exec_run(
                container.id,
                f"git clone --branch {config.github_branch} "
                f"https://x-access-token:{config.github_token}@github.com/{config.github_repo} "
                "/workspace/repo"
            )

        # Record state
        info = WorkspaceInfo(
            run_id=config.run_id,
            container_id=container.id,
            container_name=container.name,
            status="ready",
            created_at=datetime.utcnow(),
            workspace_path="/workspace/repo",
        )
        await self.state.set(config.run_id, info)

        # Hook for telemetry
        await self.hooks.on_workspace_provisioned(config, info)

        return info

    async def exec_in_workspace(
        self,
        run_id: str,
        command: str,
        timeout: Optional[int] = None,
    ) -> Tuple[str, int]:
        """Execute command in workspace container."""
        info = await self.state.get(run_id)
        if not info:
            raise WorkspaceNotFoundError(run_id)

        return await self.podman.exec_run(
            info.container_id,
            command,
            timeout=timeout,
        )

    async def cleanup_workspace(
        self,
        run_id: str,
        retain_on_failure: bool = True,
        retention_hours: int = 24,
    ) -> None:
        """Cleanup workspace container."""
        info = await self.state.get(run_id)
        if not info:
            return  # Already cleaned up

        if retain_on_failure and info.status == "failed":
            # Keep for debugging, set TTL
            await self.state.set_ttl(run_id, retention_hours * 3600)
            return

        # Remove container
        await self.podman.remove_container(info.container_id)
        await self.state.delete(run_id)

        # Hook for telemetry
        await self.hooks.on_workspace_cleaned(run_id)

    async def send_heartbeat(self, run_id: str) -> None:
        """Update heartbeat timestamp for zombie detection."""
        await self.state.update_heartbeat(run_id, datetime.utcnow())

    async def cleanup_zombies(self, max_idle_seconds: int = 120) -> List[str]:
        """Find and terminate zombie workspaces."""
        zombies = await self.state.find_stale(max_idle_seconds)
        for info in zombies:
            logger.warning(f"Terminating zombie workspace: {info.run_id}")
            await self.podman.remove_container(info.container_id, force=True)
            await self.state.delete(info.run_id)
        return [z.run_id for z in zombies]

    async def _enforce_quota(self, scope: str) -> None:
        """Check tenant quota before provisioning."""
        current = await self.state.count_by_scope(scope)
        limit = await self._get_scope_limit(scope)

        if current >= limit:
            raise QuotaExceededError(
                f"Workspace limit reached for {scope}: {current}/{limit}"
            )
```

#### 2.3 Update amprealize/workspace_agent/ Wrapper

**File**: `amprealize/workspace_agent/__init__.py`

Simplify to just re-export from breakeramp:

```python
"""Amprealize workspace agent - re-exports from BreakerAmp.

This module provides backward compatibility. New code should import
directly from breakeramp.orchestrator.
"""

from breakeramp.orchestrator import (
    AmpOrchestrator,
    WorkspaceConfig,
    WorkspaceInfo,
    WorkspaceNotFoundError,
    QuotaExceededError,
)
from breakeramp.runtime.podman import PodmanClient

# Convenience function for getting global orchestrator
_orchestrator: Optional[AmpOrchestrator] = None

def get_orchestrator() -> AmpOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        from breakeramp.state import RedisStateStore
        _orchestrator = AmpOrchestrator(
            podman=PodmanClient(),
            state=RedisStateStore(os.environ.get("REDIS_URL", "redis://localhost:6379/0")),
        )
    return _orchestrator

# Aliases for backward compatibility
get_workspace_client = get_orchestrator
AmprealizeWorkspaceClient = AmpOrchestrator
```

#### 2.4 Delete Deprecated Files

Removed from `packages/workspace-agent/`:
- ~~`grpc_server.py`~~ ✅ Removed
- ~~`grpc_client.py`~~ ✅ Removed
- ~~`grpc_generated/`~~ ✅ Removed

Removed:
- ~~`proto/workspace/v1/workspace_agent.proto`~~ ✅ Removed

> **Note**: The `packages/workspace-agent/` package still exists and provides:
> - `podman_client.py` - Low-level Podman socket client
> - `service.py` - WorkspaceService for direct usage
> - `state.py` - State store abstractions
> - `models.py`, `hooks.py`, `cli.py` - Supporting modules
>
> This package is retained for backward compatibility and standalone usage.
> New code should use `breakeramp.orchestrator.AmpOrchestrator` which provides
> the unified control plane with quota enforcement and compliance hooks.

#### Phase 2 Deliverables

- [x] `breakeramp.runtime.podman` module (moved from workspace-agent)
- [x] `breakeramp.runtime.state` module (StateStore abstractions)
- [x] `breakeramp.orchestrator.AmpOrchestrator` class
- [x] `amprealize/workspace_agent/` simplified to re-exports from breakeramp
- [x] `amprealize/execution_worker.py` integrated with AmpOrchestrator
- [x] Tests for orchestrator and runtime modules
- [x] gRPC code removed (`grpc_server.py`, `grpc_client.py`, `grpc_generated/`, proto files)
- [x] Workers use AmpOrchestrator directly

**Status**: ✅ COMPLETE - Implemented 2026-01-16

---

### Phase 3: Tenant Isolation & Quotas (Week 3)

**Objective**: Enforce per-tenant limits with org-optional support

#### 3.1 Quota Service

**File**: `amprealize/services/quota_service.py`

```python
@dataclass
class QuotaLimits:
    """Resource limits for a scope (org or user)."""
    max_concurrent_workspaces: int
    max_execution_seconds: int
    max_workspace_memory: str
    max_workspace_cpu: float
    priority_boost: int  # Added to job priority

# Default limits by plan
PLAN_LIMITS = {
    "free": QuotaLimits(
        max_concurrent_workspaces=1,
        max_execution_seconds=600,  # 10 minutes
        max_workspace_memory="512m",
        max_workspace_cpu=1.0,
        priority_boost=0,
    ),
    "pro": QuotaLimits(
        max_concurrent_workspaces=5,
        max_execution_seconds=3600,  # 1 hour
        max_workspace_memory="2g",
        max_workspace_cpu=2.0,
        priority_boost=2,
    ),
    "enterprise": QuotaLimits(
        max_concurrent_workspaces=20,
        max_execution_seconds=14400,  # 4 hours
        max_workspace_memory="4g",
        max_workspace_cpu=4.0,
        priority_boost=5,
    ),
}

class QuotaService:
    """Manages resource quotas for orgs and users."""

    async def get_limits(
        self,
        user_id: str,
        org_id: Optional[str] = None,
    ) -> QuotaLimits:
        """Get effective limits for execution."""
        if org_id:
            plan = await self._get_org_plan(org_id)
        else:
            plan = await self._get_user_plan(user_id)

        return PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])

    async def check_can_execute(
        self,
        user_id: str,
        org_id: Optional[str],
        state: StateStore,
    ) -> bool:
        """Check if execution is allowed under current quota."""
        limits = await self.get_limits(user_id, org_id)
        scope = get_isolation_scope(user_id, org_id)
        current = await state.count_by_scope(scope)
        return current < limits.max_concurrent_workspaces
```

#### 3.2 Priority Queue with Tenant Boost

**File**: `packages/execution-queue/src/execution_queue/publisher.py`

```python
async def enqueue(self, job: ExecutionJob) -> str:
    """Enqueue job with tenant-aware priority."""

    # Get tenant boost
    limits = await self.quota_service.get_limits(job.user_id, job.org_id)
    effective_priority = job.priority.value + limits.priority_boost

    # Select queue based on effective priority
    queue_name = self._get_queue_for_priority(effective_priority)

    # Add to Redis stream
    return await self.redis.xadd(
        queue_name,
        {
            "job_id": job.job_id,
            "run_id": job.run_id,
            "payload": job.model_dump_json(),
        },
    )
```

#### 3.3 Scope-Aware State Store

**File**: `packages/breakeramp/src/breakeramp/state.py`

```python
class RedisStateStore(StateStore):
    """Redis-backed state store with scope support."""

    def _key(self, run_id: str) -> str:
        return f"workspace:{run_id}"

    def _scope_index_key(self, scope: str) -> str:
        return f"workspace:scope:{scope}"

    async def set(self, run_id: str, info: WorkspaceInfo) -> None:
        """Store workspace info and update scope index."""
        await self.redis.hset(self._key(run_id), mapping=info.model_dump())
        await self.redis.sadd(self._scope_index_key(info.scope), run_id)

    async def count_by_scope(self, scope: str) -> int:
        """Count active workspaces for a scope."""
        return await self.redis.scard(self._scope_index_key(scope))

    async def list_by_scope(self, scope: str) -> List[WorkspaceInfo]:
        """List all workspaces for a scope."""
        run_ids = await self.redis.smembers(self._scope_index_key(scope))
        return [await self.get(rid) for rid in run_ids]
```

#### Phase 3 Deliverables

- [x] `QuotaService` with plan-based limits (`packages/breakeramp/src/breakeramp/quota.py`)
- [x] Org-optional scope resolution (`get_isolation_scope()`, `parse_scope()`)
- [x] Priority boost based on plan (`enqueue_with_quota_boost()` in publisher)
- [x] Scope-indexed workspace state (RedisStateStore with scope indices)
- [x] Quota enforcement in orchestrator (`_enforce_quota()` using QuotaService)
- [x] Tests for multi-tenant isolation (`tests/test_quota.py` - 35 tests)

---

### Phase 4: Horizontal Scaling & Hardening (Week 4)

**Objective**: Production-ready multi-worker deployment

#### 4.1 Consumer Groups

**File**: `packages/execution-queue/src/execution_queue/consumer.py`

```python
class ExecutionQueueConsumer:
    def __init__(
        self,
        redis_url: str,
        group_name: str = "execution-workers",
        consumer_name: Optional[str] = None,
    ):
        self.redis = redis.from_url(redis_url)
        self.group_name = group_name
        self.consumer_name = consumer_name or f"worker-{uuid4().hex[:8]}"

    async def start(self):
        """Initialize consumer group if needed."""
        for queue in ["amprealize:executions:high", "amprealize:executions:normal", "amprealize:executions:low"]:
            try:
                await self.redis.xgroup_create(queue, self.group_name, id="0", mkstream=True)
            except redis.ResponseError as e:
                if "BUSYGROUP" not in str(e):
                    raise

    async def consume(self, handler: Callable) -> None:
        """Consume jobs using XREADGROUP."""
        while True:
            # Read from high priority first, then normal, then low
            for queue in ["amprealize:executions:high", "amprealize:executions:normal", "amprealize:executions:low"]:
                messages = await self.redis.xreadgroup(
                    self.group_name,
                    self.consumer_name,
                    {queue: ">"},
                    count=1,
                    block=1000,
                )

                if messages:
                    for stream, items in messages:
                        for msg_id, data in items:
                            job = ExecutionJob.model_validate_json(data["payload"])
                            await handler(job)
                            await self.redis.xack(stream, self.group_name, msg_id)
                    break  # Processed a job, restart from high priority
```

#### 4.2 Heartbeat and Zombie Detection

**File**: `amprealize/execution_worker.py`

```python
class ExecutionWorker:
    async def _handle_job(self, job: ExecutionJob):
        """Handle job with heartbeat monitoring."""

        # Start heartbeat task
        heartbeat_task = asyncio.create_task(
            self._send_heartbeats(job.run_id, interval=30)
        )

        try:
            # ... execute agent ...
            pass
        finally:
            heartbeat_task.cancel()

    async def _send_heartbeats(self, run_id: str, interval: int):
        """Send periodic heartbeats."""
        while True:
            await self.orchestrator.send_heartbeat(run_id)
            await asyncio.sleep(interval)

class ZombieReaper:
    """Background task that cleans up zombie workspaces."""

    async def run(self, orchestrator: AmpOrchestrator, interval: int = 60):
        """Periodically check for and terminate zombies."""
        while True:
            zombies = await orchestrator.cleanup_zombies(max_idle_seconds=120)
            if zombies:
                logger.warning(f"Reaped {len(zombies)} zombie workspaces: {zombies}")
            await asyncio.sleep(interval)
```

#### 4.3 Recovery on Worker Restart

**File**: `amprealize/execution_worker.py`

```python
async def recover_pending(self):
    """Recover pending messages from dead workers on startup."""

    for queue in ["amprealize:executions:high", "amprealize:executions:normal", "amprealize:executions:low"]:
        # Get pending messages for any consumer in our group
        pending = await self.redis.xpending_range(
            queue,
            self.group_name,
            min="-",
            max="+",
            count=100,
        )

        for entry in pending:
            # If message has been pending > 5 minutes, claim it
            if entry.time_since_delivered > 300000:  # 5 min in ms
                await self.redis.xclaim(
                    queue,
                    self.group_name,
                    self.consumer_name,
                    min_idle_time=300000,
                    message_ids=[entry.message_id],
                )
                logger.info(f"Claimed orphaned job: {entry.message_id}")
```

#### 4.4 Metrics and Monitoring

**File**: `amprealize/execution_worker.py`

```python
from prometheus_client import Counter, Gauge, Histogram

JOBS_PROCESSED = Counter(
    "amprealize_execution_jobs_processed_total",
    "Total execution jobs processed",
    ["status", "scope"],
)
JOBS_IN_PROGRESS = Gauge(
    "amprealize_execution_jobs_in_progress",
    "Currently executing jobs",
    ["worker_id"],
)
JOB_DURATION = Histogram(
    "amprealize_execution_job_duration_seconds",
    "Time spent executing jobs",
    ["scope"],
    buckets=[10, 60, 300, 600, 1800, 3600],
)
QUEUE_DEPTH = Gauge(
    "amprealize_execution_queue_depth",
    "Number of jobs waiting in queue",
    ["priority"],
)
```

#### Phase 4 Deliverables

- [x] Consumer groups for horizontal scaling (XREADGROUP in `consumer.py`)
- [x] Heartbeat monitoring and zombie reaper (`zombie_reaper.py`)
- [x] Pending message recovery on restart (XAUTOCLAIM in `consumer.py`)
- [x] Prometheus metrics exported (`execution_metrics.py`)
- [x] Grafana dashboard for execution monitoring (`deployment/config/grafana/dashboards/execution-monitoring.json`)
- [x] Documentation and runbooks
- [x] gRPC code removed (`grpc_server.py`, `grpc_client.py`, `grpc_generated/`, `workspace_agent.proto`)
- [ ] Load test: 100 concurrent across 10 tenants (optional - deferred to post-production validation)

**Status**: ✅ COMPLETE - Implemented 2026-01-16. Load test deferred (optional for initial production).

---

## Migration Plan

### Step 1: Deploy Queue Infrastructure (Day 1-2)

1. Add `execution-queue` package to requirements
2. Deploy with queue disabled (feature flag)
3. Verify Redis streams work in staging

### Step 2: Shadow Mode (Day 3-4)

1. Enable queue publishing alongside direct execution
2. Workers consume but don't execute (log only)
3. Verify job flow matches expectations

### Step 3: Worker Execution (Day 5-6)

1. Enable worker execution
2. Disable direct API execution
3. Monitor for issues

### Step 4: Remove Legacy Code (Day 7)

1. Remove `asyncio.create_task()` path
2. Remove workspace-agent gRPC service
3. Update documentation

---

## Rollback Plan

If issues arise:

1. **Feature flag**: `EXECUTION_MODE=direct` reverts to API-inline execution
2. **Queue drain**: Workers stop consuming; API drains queue
3. **State cleanup**: Redis workspace state can be cleared safely

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| API restart impact | Loses all running executions | Zero impact |
| Execution throughput | ~10 concurrent (API limited) | 100+ concurrent |
| Tenant isolation | None | Full scope isolation |
| Zombie cleanup | Manual | Automatic (<2 min) |
| Queue backpressure | None | Rejects at 1000 pending |

---

## Open Questions

1. **Should workers run in containers or on host?**
   - Recommendation: In containers for dev, on host for production (better Podman socket access)

2. **How to handle checkpoint/resume for long runs?**
   - Future: Store execution state snapshots; implement `resume_from_checkpoint()`

3. **Should we support WebSocket for real-time execution updates?**
   - Current: SSE from API polling run status
   - Future: Workers publish to Redis pub/sub, API streams to clients

---

## Alignment with COLLAB_SAAS_REQUIREMENTS.md

This architecture supports the SaaS collaboration requirements:

| Requirement | How This Architecture Supports It |
|-------------|-----------------------------------|
| **< 100ms collaboration latency** | Gateway layer handles WebSocket upgrades with 1hr timeout; stateless API scales horizontally |
| **1000+ concurrent agents** | Execution layer with per-tenant workspace pools; queue-based backpressure prevents overload |
| **Agent presence at scale** | Workers can publish presence updates to Redis pub/sub; API broadcasts to WebSocket clients |
| **Dual-user paradigm** | Tenant isolation supports both org-scoped (teams) and user-scoped (personal) workspaces |
| **Cross-surface parity** | Gateway provides consistent auth/rate-limiting for HTTP surfaces (UI/API/CLI); MCP uses subprocess/stdio with in-process auth |
| **WebSocket reconnection < 500ms** | Gateway maintains connection; API replicas are stateless so any can handle reconnect |

---

## References

- [COLLAB_SAAS_REQUIREMENTS.md](docs/COLLAB_SAAS_REQUIREMENTS.md) - Real-time collaboration requirements
- [BreakerAmp Package](packages/breakeramp/)
- [local-test-suite.yaml](packages/breakeramp/src/breakeramp/blueprints/local-test-suite.yaml)
- [Redis Streams Documentation](https://redis.io/docs/data-types/streams/)
- [BUILD_TIMELINE.md](BUILD_TIMELINE.md) - Entry #155+
