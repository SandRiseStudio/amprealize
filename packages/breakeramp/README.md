# BreakerAmp

**Infrastructure-as-Code orchestration with blueprint-driven container management and compliance tracking.**

BreakerAmp provides a Terraform-like workflow (`plan → apply → destroy`) for containerized development environments, with built-in compliance gates, resource estimation, and lifecycle management.

## Features

- **Blueprint-driven infrastructure**: YAML/JSON blueprints define multi-service environments
- **Plan-before-apply workflow**: Preview resource requirements and cost estimates before provisioning
- **Podman-native execution**: Runs containers via Podman (Docker support planned)
- **Compliance hooks**: Optional integration points for audit trails and compliance checks
- **Resource management**: Memory, CPU, and bandwidth limits with enforcement
- **Lifecycle tracking**: Status monitoring, health checks, and teardown coordination

## Installation

```bash
# Core package
pip install breakeramp

# With CLI support
pip install breakeramp[cli]

# With FastAPI integration
pip install breakeramp[fastapi]

# Everything
pip install breakeramp[all]
```

## Quick Start

### As a Library

```python
from breakeramp import BreakerAmpService, PlanRequest, ApplyRequest
from breakeramp.executors import PodmanExecutor

# Create service with Podman executor
executor = PodmanExecutor()
service = BreakerAmpService(executor=executor)

# Plan an environment
plan = service.plan(PlanRequest(
    blueprint_id="postgres-dev",
    environment="development",
    lifetime="2h"
))

print(f"Estimated memory: {plan.environment_estimates.memory_footprint_mb}MB")
print(f"Estimated cost: ${plan.environment_estimates.cost_estimate:.2f}")

# Apply the plan
result = service.apply(ApplyRequest(plan_id=plan.plan_id))
print(f"Environment ready: {result.environment_outputs}")

# Clean up
service.destroy(DestroyRequest(amp_run_id=result.amp_run_id, reason="Done"))
```

### With Hooks (for integration with external services)

```python
from breakeramp import BreakerAmpService, BreakerAmpHooks
from breakeramp.executors import PodmanExecutor

def on_action(action_type: str, details: dict) -> str:
    """Called when BreakerAmp performs significant actions."""
    print(f"Action: {action_type} - {details}")
    return f"action-{uuid.uuid4()}"  # Return action ID for tracking

def on_compliance_step(step_type: str, details: dict) -> None:
    """Called for compliance/audit trail entries."""
    print(f"Compliance: {step_type} - {details}")

def on_metric(event_name: str, payload: dict) -> None:
    """Called for telemetry/metrics events."""
    print(f"Metric: {event_name} - {payload}")

hooks = BreakerAmpHooks(
    on_action=on_action,
    on_compliance_step=on_compliance_step,
    on_metric=on_metric,
)

service = BreakerAmpService(
    executor=PodmanExecutor(),
    hooks=hooks,
)
```

### Using the CLI

```bash
# Configure BreakerAmp in the current project
breakeramp configure --blueprints

# List available blueprints
breakeramp blueprints --json

# Plan an environment
breakeramp plan development --blueprint postgres-dev

# Apply the plan
breakeramp apply --plan-id <plan-id>

# Or use the day-to-day shortcut
breakeramp up development --blueprint postgres-dev

# Check status and service-level details
breakeramp status <amp-run-id>
breakeramp list
breakeramp services

# Restart one service by its displayed service name
breakeramp restart --env development postgres

# Preview safe cleanup
breakeramp cleanup --dry-run --json

# Destroy one environment
breakeramp destroy <amp-run-id> --reason "Cleanup" --interactive
```

### FastAPI Integration

```python
from fastapi import FastAPI
from breakeramp import BreakerAmpService
from breakeramp.executors import PodmanExecutor
from breakeramp.integrations.fastapi import create_breakeramp_routes

app = FastAPI()
service = BreakerAmpService(executor=PodmanExecutor())

# Mount BreakerAmp routes at /v1/breakeramp
app.include_router(
    create_breakeramp_routes(service),
    prefix="/v1/breakeramp",
    tags=["breakeramp"]
)
```

## Blueprints

Blueprints define the services in your environment:

```yaml
name: postgres-dev
version: "1.0"
services:
  postgres:
    image: postgres:16-alpine
    ports:
      - "5432:5432"
    environment:
      POSTGRES_USER: dev
      POSTGRES_PASSWORD: dev
      POSTGRES_DB: app
    cpu_cores: 1.0
    memory_mb: 512
    module: datastores

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    memory_mb: 256
    module: datastores
```

## Environment Configuration

Define environments in `environments.yaml` at your project root:

```yaml
environments:
  development:
    description: Local development environment
    default_compliance_tier: standard
    default_lifetime: 90m
    runtime:
      provider: podman
      auto_start: true
    infrastructure:
      blueprint_id: local-test-suite

  staging:
    description: Staging environment
    default_compliance_tier: strict
    default_lifetime: 4h
    runtime:
      provider: podman
      memory_limit_mb: 4096
```

### Validation

Validate your environment configuration:

```bash
breakeramp validate environments.yaml
```

See `examples/environments.yaml.example` for a complete template with all options.

`local-test-suite` includes `amprealize-api`, `amprealize-mcp`, `gateway`, and `web-console` for a full local Amprealize development stack.

## Command Surface

Use this taxonomy when choosing commands:

| Category | Primary Commands | Notes |
|---|---|---|
| Configure | `configure`, `validate`, `blueprints`, `version` | `configure` is the standalone setup command. |
| Lifecycle | `up`, `list`, `services`, `restart`, `status`, `stop`, `destroy`, `plan`, `apply` | Humans usually start with `up`, `list`, `services`, and `restart`; scripts should prefer JSON-capable commands. |
| Capacity | `resources` | Includes an explicit recommendation in human and JSON output. |
| Hygiene | `cleanup` | Use `cleanup --dry-run --json` before executing cleanup in automation. |
| Disaster/Rebuild | `fresh`, `nuke` | High-risk commands; back up first and use explicit confirmation for scripts. |
| Data Safety | `backup`, `backups`, `restore` | `fresh` and `nuke` auto-back up running PostgreSQL databases unless skipped. |
| Test Environments | `plan-for-tests`, `run-tests` | For BreakerAmp-managed test infrastructure. |

Recommended human workflow:

```bash
breakeramp up cloud-dev
breakeramp list
breakeramp services
breakeramp restart --env cloud-dev amprealize-api
breakeramp resources
breakeramp cleanup --dry-run
breakeramp fresh cloud-dev
```

Recommended agent/script workflow:

```bash
breakeramp list --json
breakeramp services --json
breakeramp status <run-id> --json
breakeramp resources --json
breakeramp cleanup --dry-run --json
```

Command classifications:

| Classification | Commands |
|---|---|
| Primary | `up`, `list`, `services`, `restart`, `status`, `resources`, `cleanup`, `fresh` |
| Advanced | `plan`, `apply`, `destroy`, `nuke`, `backup`, `restore`, `run-tests`, `plan-for-tests` |
| Support | `blueprints`, `configure`, `validate`, `version`, `backups`, `stop`, `wait-health` |

`destroy --force` is intended for non-interactive scripts that already have a specific run ID. `destroy --interactive` is intended for humans who want a confirmation prompt before removing an environment.

## Executors

BreakerAmp uses an executor abstraction for container runtime operations:

```python
from breakeramp.executors import Executor, PodmanExecutor

# Use the default Podman executor
executor = PodmanExecutor()

# Or create a custom executor implementing the Executor protocol
class CustomExecutor(Executor):
    def run_container(self, image: str, **kwargs) -> str: ...
    def stop_container(self, container_id: str) -> None: ...
    def remove_container(self, container_id: str) -> None: ...
    def exec_in_container(self, container_id: str, command: list[str]) -> str: ...
    def get_logs(self, container_id: str) -> str: ...
    def inspect_container(self, container_id: str) -> dict: ...
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    BreakerAmpService                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │   plan()    │  │   apply()   │  │     destroy()       │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│                    BreakerAmpHooks                          │
│  on_action() │ on_compliance_step() │ on_metric()          │
├─────────────────────────────────────────────────────────────┤
│                       Executor                              │
│  ┌─────────────────┐  ┌─────────────────────────────────┐  │
│  │ PodmanExecutor  │  │    (Future: DockerExecutor)     │  │
│  └─────────────────┘  └─────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## License

MIT License - see [LICENSE](LICENSE) for details.

## Contributing

Contributions are welcome! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

## Related Projects

- [Amprealize](https://github.com/SandRiseStudio/amprealize) - AI-assisted development platform (uses BreakerAmp for environment orchestration)
- [Raze](https://github.com/Nas4146/raze) - Structured logging with centralized storage
