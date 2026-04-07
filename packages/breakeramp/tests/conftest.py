"""Pytest fixtures for breakeramp tests."""

import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from breakeramp import (
    BreakerAmpHooks,
    BreakerAmpService,
    Blueprint,
    ServiceSpec,
)
from breakeramp.executors.base import ContainerInfo, ContainerRunConfig, MachineInfo


class MockExecutor:
    """Mock executor for testing without container runtime."""

    def __init__(self):
        self.containers: Dict[str, ContainerInfo] = {}
        self._next_id = 1
        self.run_calls: List[ContainerRunConfig] = []
        self.stop_calls: List[str] = []
        self.remove_calls: List[str] = []
        self._machine_info = MachineInfo(
            name="test-machine",
            running=True,
            cpus=4,
            memory_mb=8192,
            disk_gb=100,
        )

    def run_container(self, config: ContainerRunConfig) -> str:
        """Mock running a container."""
        self.run_calls.append(config)
        container_id = f"mock-container-{self._next_id}"
        self._next_id += 1
        self.containers[container_id] = ContainerInfo(
            container_id=container_id,
            name=config.name,
            status="running",
            image=config.image,
        )
        return container_id

    def stop_container(self, container_id: str, timeout: int = 10) -> bool:
        """Mock stopping a container."""
        self.stop_calls.append(container_id)
        if container_id in self.containers:
            self.containers[container_id].status = "stopped"
            return True
        return False

    def remove_container(self, container_id: str, force: bool = False) -> bool:
        """Mock removing a container."""
        self.remove_calls.append(container_id)
        if container_id in self.containers:
            del self.containers[container_id]
            return True
        return False

    def list_containers(self, all_containers: bool = False) -> List[ContainerInfo]:
        """Mock listing containers."""
        if all_containers:
            return list(self.containers.values())
        return [c for c in self.containers.values() if c.status == "running"]

    def get_container_stats(self, container_id: str) -> Dict[str, Any]:
        """Mock getting container stats."""
        return {
            "cpu_percent": 5.0,
            "memory_usage_mb": 256,
            "memory_limit_mb": 1024,
            "net_input_bytes": 1000,
            "net_output_bytes": 2000,
        }

    def exec_in_container(
        self, container_id: str, command: List[str], **kwargs
    ) -> tuple[int, str, str]:
        """Mock executing command in container."""
        return (0, "mock output", "")

    def get_container_logs(
        self, container_id: str, tail: int = 100, follow: bool = False
    ) -> str:
        """Mock getting container logs."""
        return f"Mock logs for {container_id}"

    def get_container_status(self, container_id: str) -> str:
        """Mock getting container status."""
        if container_id in self.containers:
            return self.containers[container_id].status
        return "unknown"

    def get_machine_info(self) -> MachineInfo:
        """Mock getting machine info."""
        return self._machine_info

    def ensure_machine_running(self) -> bool:
        """Mock ensuring machine is running."""
        self._machine_info.running = True
        return True

    def start_machine(self) -> bool:
        """Mock starting machine."""
        self._machine_info.running = True
        return True


@pytest.fixture
def mock_executor():
    """Provide a mock executor for testing."""
    return MockExecutor()


@pytest.fixture
def temp_base_dir():
    """Provide a temporary base directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def service(mock_executor, temp_base_dir):
    """Provide an BreakerAmpService with mock executor."""
    return BreakerAmpService(
        executor=mock_executor,
        base_dir=temp_base_dir,
    )


@pytest.fixture
def service_with_hooks(mock_executor, temp_base_dir):
    """Provide an BreakerAmpService with tracked hooks."""
    actions: List[tuple] = []
    compliance_steps: List[tuple] = []
    metrics: List[tuple] = []

    def track_action(action_type: str, details: Dict[str, Any]) -> str:
        actions.append((action_type, details))
        return f"test-action-{len(actions)}"

    def track_compliance(step_type: str, details: Dict[str, Any]) -> None:
        compliance_steps.append((step_type, details))

    def track_metric(event_name: str, payload: Dict[str, Any]) -> None:
        metrics.append((event_name, payload))

    hooks = BreakerAmpHooks(
        on_action=track_action,
        on_compliance_step=track_compliance,
        on_metric=track_metric,
    )

    svc = BreakerAmpService(
        executor=mock_executor,
        hooks=hooks,
        base_dir=temp_base_dir,
    )

    # Return service with tracking info as tuple
    return svc, actions, compliance_steps, metrics


@pytest.fixture
def sample_blueprint() -> Blueprint:
    """Provide a sample blueprint for testing."""
    return Blueprint(
        name="test-blueprint",
        version="1.0.0",
        services={
            "postgres": ServiceSpec(
                image="postgres:16-alpine",
                ports=["5432:5432"],
                environment={"POSTGRES_PASSWORD": "testpass"},
                cpu_cores=1.0,
                memory_mb=512,
                bandwidth_mbps=10,
                module="datastores",
            ),
            "redis": ServiceSpec(
                image="redis:7-alpine",
                ports=["6379:6379"],
                cpu_cores=0.5,
                memory_mb=256,
                bandwidth_mbps=5,
                module="datastores",
            ),
        },
    )


@pytest.fixture
def sample_blueprint_file(temp_base_dir, sample_blueprint) -> Path:
    """Create a sample blueprint file and return its path."""
    # Use a separate subdirectory to avoid conflicts
    test_blueprints_dir = temp_base_dir / "test_blueprints"
    test_blueprints_dir.mkdir(parents=True, exist_ok=True)

    blueprint_path = test_blueprints_dir / "test-blueprint.yaml"
    import yaml
    with open(blueprint_path, "w") as f:
        yaml.dump(sample_blueprint.model_dump(), f)

    return blueprint_path
