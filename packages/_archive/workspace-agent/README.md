# workspace-agent

Standalone workspace management service for isolated agent execution containers.

> **Note**: For new development, prefer `breakeramp.orchestrator.AmpOrchestrator` which provides
> unified control plane with quota enforcement, compliance hooks, and multi-tenant support.
> This package is retained for backward compatibility and standalone/lightweight usage.

## Overview

`workspace-agent` manages isolated container workspaces for agent code execution. It:
- Provisions podman containers for each agent run
- Clones GitHub repositories into containers
- Executes commands within containers
- Handles cleanup based on execution outcome

## Architecture

```
┌─────────────────┐         ┌─────────────────────┐
│  Amprealize API    │  HTTP   │  BreakerAmp         │  ◄── Preferred (unified control plane)
│  (stateless)    │ ──────► │  AmpOrchestrator    │
└─────────────────┘         └─────────────────────┘
                                     │
         - OR -                      │ Uses
                                     ▼
┌─────────────────┐         ┌─────────────────────┐
│  Direct Usage   │ ──────► │  workspace-agent    │  ◄── Lightweight alternative
└─────────────────┘         │  WorkspaceService   │
                            └─────────────────────┘
                                     │
                                     ▼
                            ┌─────────────────────┐
                            │  Podman Socket      │
                            │  (host)             │
                            └─────────────────────┘
                                     │
                            ┌────────┼────────┐
                            ▼        ▼        ▼
                        ┌───────┐ ┌───────┐ ┌───────┐
                        │ws-123 │ │ws-456 │ │ws-789 │
                        │(agent)│ │(agent)│ │(agent)│
                        └───────┘ └───────┘ └───────┘
```

## Installation

```bash
# Core functionality
pip install workspace-agent

# With Redis state store
pip install workspace-agent[redis]

# Everything (includes optional dependencies)
pip install workspace-agent[all]
```

## Usage

### With BreakerAmp (Recommended for Amprealize)

```python
from breakeramp.orchestrator import AmpOrchestrator, WorkspaceConfig
from breakeramp.runtime.podman import PodmanClient
from breakeramp.runtime.state import RedisStateStore

# Initialize orchestrator with quota and compliance support
orchestrator = AmpOrchestrator(
    podman=PodmanClient(),
    state=RedisStateStore("redis://localhost:6379/0"),
)

# Provision a workspace with tenant isolation
config = WorkspaceConfig(
    run_id="run-123",
    scope="org:acme-corp",  # or "user:user-123" for personal
    github_repo="owner/repo",
    github_token="ghp_xxx",
)
info = await orchestrator.provision_workspace(config)

# Execute commands
output, exit_code = await orchestrator.exec_in_workspace(run_id="run-123", command="ls -la")

# Cleanup
await orchestrator.cleanup_workspace(run_id="run-123")
```

### Direct Usage (Lightweight)

```python
from workspace_agent import WorkspaceService, WorkspaceConfig
from workspace_agent.state import RedisStateStore

# Initialize with Redis state
state_store = RedisStateStore("redis://localhost:6379/0")
service = WorkspaceService(state_store=state_store)

# Provision a workspace
config = WorkspaceConfig(
    run_id="run-123",
    project_id="proj-abc",
    github_repo="owner/repo",
    github_token="ghp_xxx",
)
info = await service.provision(config)

# Execute commands
output, exit_code = await service.exec(run_id="run-123", command="ls -la")

# Cleanup
await service.cleanup(run_id="run-123", success=True)
```

## API Reference

### WorkspaceService Methods

- `provision(config: WorkspaceConfig) -> WorkspaceInfo` - Create workspace container
- `get_workspace(run_id: str) -> WorkspaceInfo` - Get workspace status
- `exec(run_id, command, cwd, timeout) -> Tuple[str, int]` - Execute command
- `read_file(run_id, file_path, start_line, end_line) -> str` - Read file content
- `write_file(run_id, file_path, content) -> None` - Write file content
- `list_dir(run_id, dir_path) -> List[str]` - List directory entries
- `cleanup(run_id, success) -> None` - Remove workspace
- `cleanup_expired() -> int` - Clean up stale workspaces
- `list_workspaces() -> List[WorkspaceInfo]` - List all workspaces
- `get_stats() -> Stats` - Get resource statistics

## Configuration

Environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `WORKSPACE_AGENT_REDIS_URL` | Redis connection URL | (in-memory if not set) |
| `PODMAN_SOCKET_PATH` | Podman socket URI | auto-discovered |
| `WORKSPACE_DEFAULT_IMAGE` | Default container image | `python:3.11-slim` |
| `WORKSPACE_DEFAULT_MEMORY` | Default memory limit | `2g` |
| `WORKSPACE_DEFAULT_CPU` | Default CPU limit | `2.0` |
| `WORKSPACE_CLEANUP_INTERVAL` | Background cleanup interval | `300` (5 min) |

## Relationship with BreakerAmp

This package provides the low-level workspace management primitives. For production
deployments within Amprealize, use `breakeramp.orchestrator.AmpOrchestrator` which adds:

- **Quota enforcement**: Per-tenant resource limits (concurrent workspaces, memory, CPU)
- **Compliance hooks**: Audit logging, data residency enforcement
- **Queue integration**: Works with `execution-queue` for horizontal scaling
- **Heartbeat monitoring**: Automatic zombie workspace detection and cleanup

## License

MIT
