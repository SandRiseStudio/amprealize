"""Tests for AmpOrchestrator - unified workspace control plane."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from breakeramp.orchestrator import (
    AmpOrchestrator,
    OrchestratorError,
    OrchestratorHooks,
    PLAN_LIMITS,
    ProvisionError,
    QuotaExceededError,
    QuotaLimits,
    WorkspaceConfig,
    WorkspaceInfo,
    WorkspaceNotFoundError,
)
from breakeramp.runtime.podman import ContainerInfo, PodmanClient
from breakeramp.runtime.state import (
    InMemoryStateStore,
    StateStore,
    WorkspaceState,
    WorkspaceStatus,
)


class MockPodmanClient:
    """Mock Podman client for testing without container runtime."""

    def __init__(self):
        self.containers: Dict[str, ContainerInfo] = {}
        self._next_id = 1
        self.create_calls: List[Dict[str, Any]] = []
        self.exec_calls: List[Tuple[str, str]] = []
        self.remove_calls: List[str] = []
        self._available = True
        self._exec_results: Dict[str, Tuple[str, int]] = {}

    async def is_available(self) -> bool:
        return self._available

    async def version(self) -> Dict[str, Any]:
        return {"Version": "4.0.0", "ApiVersion": "1.0.0"}

    async def create_container(
        self,
        name: str,
        image: str,
        command: Optional[List[str]] = None,
        environment: Optional[Dict[str, str]] = None,
        memory_limit: Optional[str] = None,
        cpu_limit: Optional[float] = None,
        workdir: Optional[str] = None,
        labels: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> ContainerInfo:
        self.create_calls.append({
            "name": name,
            "image": image,
            "command": command,
            "environment": environment,
            "memory_limit": memory_limit,
            "cpu_limit": cpu_limit,
            "labels": labels,
        })
        container_id = f"mock-{self._next_id:012x}"
        self._next_id += 1
        info = ContainerInfo(
            id=container_id,
            name=name,
            status="running",
            labels=labels or {},
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.containers[name] = info
        return info

    async def exec_run(
        self,
        container_name: str,
        command: str,
        timeout: Optional[int] = None,
        workdir: Optional[str] = None,
        user: Optional[str] = None,
    ) -> Tuple[str, int]:
        self.exec_calls.append((container_name, command))
        # Return configured result or success
        if command in self._exec_results:
            return self._exec_results[command]
        return "", 0

    async def remove_container(
        self,
        container_name: str,
        force: bool = False,
    ) -> bool:
        self.remove_calls.append(container_name)
        if container_name in self.containers:
            del self.containers[container_name]
            return True
        return False

    async def get_container(self, container_name: str) -> Optional[ContainerInfo]:
        return self.containers.get(container_name)

    async def write_file(
        self,
        container_name: str,
        path: str,
        content: str,
        mode: int = 0o644,
    ) -> bool:
        return True

    async def read_file(
        self,
        container_name: str,
        path: str,
    ) -> Optional[str]:
        return "mock file content"

    async def close(self) -> None:
        pass


@pytest.fixture
def mock_podman():
    """Create a mock Podman client."""
    return MockPodmanClient()


@pytest.fixture
def mock_state_store():
    """Create an in-memory state store for testing."""
    return InMemoryStateStore()


@pytest.fixture
def orchestrator(mock_podman, mock_state_store):
    """Create an orchestrator with mock dependencies."""
    return AmpOrchestrator(
        podman=mock_podman,
        state=mock_state_store,
    )


class TestWorkspaceConfig:
    """Tests for WorkspaceConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = WorkspaceConfig(
            run_id="run-123",
            scope="org:tenant-abc",
        )
        assert config.memory_limit == "2g"
        assert config.cpu_limit == 2.0
        assert config.timeout_seconds == 3600
        assert config.image == "docker.io/library/python:3.11-slim"
        assert config.workdir == "/workspace"
        assert config.github_repo is None

    def test_custom_values(self):
        """Test custom configuration values."""
        config = WorkspaceConfig(
            run_id="run-123",
            scope="user:user-456",
            memory_limit="4g",
            cpu_limit=4.0,
            timeout_seconds=7200,
            github_repo="owner/repo",
            github_branch="develop",
            project_id="proj-abc",
        )
        assert config.memory_limit == "4g"
        assert config.cpu_limit == 4.0
        assert config.github_repo == "owner/repo"
        assert config.github_branch == "develop"


class TestQuotaLimits:
    """Tests for quota limits configuration."""

    def test_plan_limits_defined(self):
        """Test that plan limits are defined for all tiers."""
        assert "free" in PLAN_LIMITS
        assert "pro" in PLAN_LIMITS
        assert "enterprise" in PLAN_LIMITS

    def test_free_tier_limits(self):
        """Test free tier has restrictive limits."""
        free = PLAN_LIMITS["free"]
        assert free.max_concurrent_workspaces == 1
        assert free.max_execution_seconds == 600

    def test_enterprise_tier_limits(self):
        """Test enterprise tier has higher limits."""
        enterprise = PLAN_LIMITS["enterprise"]
        assert enterprise.max_concurrent_workspaces == 20  # Updated in quota.py
        assert enterprise.max_execution_seconds == 14400  # 4 hours


class TestOrchestratorProvisioning:
    """Tests for workspace provisioning."""

    @pytest.mark.asyncio
    async def test_provision_workspace_basic(self, orchestrator, mock_podman):
        """Test basic workspace provisioning."""
        config = WorkspaceConfig(
            run_id="run-123",
            scope="org:tenant-abc",
        )

        info = await orchestrator.provision_workspace(config)

        assert info.run_id == "run-123"
        assert info.scope == "org:tenant-abc"
        assert info.status == "running"
        assert "run-123" in info.container_name

        # Verify container was created
        assert len(mock_podman.create_calls) == 1

    @pytest.mark.asyncio
    async def test_provision_workspace_with_github_repo(self, orchestrator, mock_podman):
        """Test provisioning with GitHub repo cloning."""
        # Configure exec to return success for git clone
        mock_podman._exec_results["git clone --depth 1 --branch main https://github.com/owner/repo.git /workspace"] = ("Cloning...", 0)

        config = WorkspaceConfig(
            run_id="run-456",
            scope="org:tenant-abc",
            github_repo="owner/repo",
            github_branch="main",
        )

        info = await orchestrator.provision_workspace(config)

        assert info.run_id == "run-456"
        # Verify git clone was called
        assert any("git clone" in cmd for _, cmd in mock_podman.exec_calls)

    @pytest.mark.asyncio
    async def test_provision_workspace_with_labels(self, orchestrator, mock_podman):
        """Test that containers get proper labels."""
        config = WorkspaceConfig(
            run_id="run-789",
            scope="org:tenant-abc",
            project_id="proj-xyz",
            agent_id="agent-123",
        )

        await orchestrator.provision_workspace(config)

        # Container should be created with labels
        create_call = mock_podman.create_calls[0]
        assert create_call["name"] is not None

    @pytest.mark.asyncio
    async def test_quota_exceeded(self, orchestrator, mock_podman, mock_state_store):
        """Test that quota limits are enforced."""
        # Set a custom quota resolver that limits to 1 workspace
        orchestrator._quota_resolver = lambda scope: QuotaLimits(
            max_concurrent_workspaces=1,
        )

        # Provision first workspace
        config1 = WorkspaceConfig(run_id="run-1", scope="org:tenant-abc")
        await orchestrator.provision_workspace(config1)

        # Try to provision second - should fail
        config2 = WorkspaceConfig(run_id="run-2", scope="org:tenant-abc")
        with pytest.raises(QuotaExceededError) as exc_info:
            await orchestrator.provision_workspace(config2)

        assert exc_info.value.scope == "org:tenant-abc"
        assert exc_info.value.current == 1
        assert exc_info.value.limit == 1


class TestOrchestratorExecution:
    """Tests for command execution in workspaces."""

    @pytest.mark.asyncio
    async def test_exec_in_workspace(self, orchestrator, mock_podman):
        """Test executing commands in workspace."""
        # Provision first
        config = WorkspaceConfig(run_id="run-123", scope="org:tenant-abc")
        await orchestrator.provision_workspace(config)

        # Configure exec result
        mock_podman._exec_results["echo hello"] = ("hello\n", 0)

        output, exit_code = await orchestrator.exec_in_workspace(
            run_id="run-123",
            command="echo hello",
        )

        assert output == "hello\n"
        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_exec_in_nonexistent_workspace(self, orchestrator):
        """Test executing in non-existent workspace raises error."""
        with pytest.raises(WorkspaceNotFoundError) as exc_info:
            await orchestrator.exec_in_workspace(
                run_id="nonexistent",
                command="ls",
            )
        assert exc_info.value.run_id == "nonexistent"


class TestOrchestratorHeartbeat:
    """Tests for heartbeat and zombie detection."""

    @pytest.mark.asyncio
    async def test_send_heartbeat(self, orchestrator, mock_state_store):
        """Test that heartbeat updates state."""
        # Provision workspace
        config = WorkspaceConfig(run_id="run-123", scope="org:tenant-abc")
        await orchestrator.provision_workspace(config)

        # Get initial state
        state_before = await mock_state_store.get("run-123")
        heartbeat_before = state_before.last_heartbeat

        # Wait a tiny bit and send heartbeat
        await asyncio.sleep(0.01)
        result = await orchestrator.send_heartbeat("run-123")

        assert result is True

        # Verify heartbeat was updated
        state_after = await mock_state_store.get("run-123")
        assert state_after.last_heartbeat > heartbeat_before

    @pytest.mark.asyncio
    async def test_cleanup_zombies(self, orchestrator, mock_podman, mock_state_store):
        """Test that stale workspaces are cleaned up."""
        # Provision workspace
        config = WorkspaceConfig(run_id="run-zombie", scope="org:tenant-abc")
        await orchestrator.provision_workspace(config)

        # Manually set the heartbeat to be stale
        state = await mock_state_store.get("run-zombie")
        state.last_heartbeat = (
            datetime.now(timezone.utc) - timedelta(minutes=10)
        ).isoformat()
        await mock_state_store.set(state)

        # Cleanup zombies with 5 minute threshold
        cleaned = await orchestrator.cleanup_zombies(max_idle_seconds=300)

        assert "run-zombie" in cleaned
        assert len(mock_podman.remove_calls) == 1


class TestOrchestratorCleanup:
    """Tests for workspace cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_workspace(self, orchestrator, mock_podman):
        """Test normal workspace cleanup."""
        # Provision first
        config = WorkspaceConfig(run_id="run-123", scope="org:tenant-abc")
        info = await orchestrator.provision_workspace(config)

        # Cleanup
        await orchestrator.cleanup_workspace("run-123")

        # Verify container was removed
        assert info.container_name in mock_podman.remove_calls

        # Verify state was removed
        state = await orchestrator._get_state()
        assert await state.get("run-123") is None

    @pytest.mark.asyncio
    async def test_cleanup_nonexistent_workspace(self, orchestrator):
        """Test cleanup of non-existent workspace is graceful."""
        # Should not raise
        await orchestrator.cleanup_workspace("nonexistent")


class TestOrchestratorHooks:
    """Tests for telemetry/compliance hooks."""

    @pytest.mark.asyncio
    async def test_provision_hook_called(self, mock_podman, mock_state_store):
        """Test that provision hook is called."""
        hook_called = []

        def on_provisioned(config, info):
            hook_called.append(("provision", config.run_id))

        hooks = OrchestratorHooks(on_workspace_provisioned=on_provisioned)
        orchestrator = AmpOrchestrator(
            podman=mock_podman,
            state=mock_state_store,
            hooks=hooks,
        )

        config = WorkspaceConfig(run_id="run-123", scope="org:tenant-abc")
        await orchestrator.provision_workspace(config)

        assert ("provision", "run-123") in hook_called

    @pytest.mark.asyncio
    async def test_cleanup_hook_called(self, mock_podman, mock_state_store):
        """Test that cleanup hook is called."""
        hook_called = []

        def on_cleaned(run_id):
            hook_called.append(("cleanup", run_id))

        hooks = OrchestratorHooks(on_workspace_cleaned=on_cleaned)
        orchestrator = AmpOrchestrator(
            podman=mock_podman,
            state=mock_state_store,
            hooks=hooks,
        )

        # Provision then cleanup
        config = WorkspaceConfig(run_id="run-123", scope="org:tenant-abc")
        await orchestrator.provision_workspace(config)
        await orchestrator.cleanup_workspace("run-123")

        assert ("cleanup", "run-123") in hook_called


class TestOrchestratorFileOperations:
    """Tests for file read/write operations."""

    @pytest.mark.asyncio
    async def test_write_file(self, orchestrator, mock_podman):
        """Test writing file to workspace."""
        config = WorkspaceConfig(run_id="run-123", scope="org:tenant-abc")
        await orchestrator.provision_workspace(config)

        # This should not raise
        await orchestrator.write_file(
            run_id="run-123",
            path="/workspace/test.txt",
            content="hello world",
        )

    @pytest.mark.asyncio
    async def test_read_file(self, orchestrator, mock_podman):
        """Test reading file from workspace."""
        config = WorkspaceConfig(run_id="run-123", scope="org:tenant-abc")
        await orchestrator.provision_workspace(config)

        content = await orchestrator.read_file(
            run_id="run-123",
            path="/workspace/test.txt",
        )

        assert content == "mock file content"


class TestOrchestratorSingleton:
    """Tests for singleton pattern."""

    def test_get_orchestrator_returns_same_instance(self):
        """Test that get_orchestrator returns singleton."""
        from breakeramp import get_orchestrator

        # Reset for test
        import breakeramp.orchestrator
        breakeramp.orchestrator._default_orchestrator = None

        orch1 = get_orchestrator()
        orch2 = get_orchestrator()

        assert orch1 is orch2

        # Clean up
        breakeramp.orchestrator._default_orchestrator = None
