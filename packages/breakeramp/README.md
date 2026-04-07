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
# Bootstrap configuration in current directory
breakeramp bootstrap --include-blueprints

# List available blueprints
breakeramp blueprints

# Plan an environment
breakeramp plan --blueprint postgres-dev --env development

# Apply the plan
breakeramp apply --plan-id <plan-id>

# Check status
breakeramp status <amp-run-id>

# Destroy environment
breakeramp destroy <amp-run-id> --reason "Cleanup"
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
