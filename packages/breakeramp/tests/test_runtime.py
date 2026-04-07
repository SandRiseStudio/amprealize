"""Tests for runtime module - state stores and podman client."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from breakeramp.runtime.state import (
    InMemoryStateStore,
    RedisStateStore,
    StateStore,
    WorkspaceState,
    WorkspaceStatus,
)


def make_workspace_state(
    run_id: str = "run-123",
    container_id: str = "abc123",
    container_name: str = "amprealize-ws-run-123",
    scope: str = "org:tenant-a",
    status: WorkspaceStatus = WorkspaceStatus.RUNNING,
    workspace_path: str = "/workspace",
    timeout_seconds: int = 3600,
) -> WorkspaceState:
    """Helper to create WorkspaceState with defaults."""
    now = datetime.now(timezone.utc).isoformat()
    return WorkspaceState(
        run_id=run_id,
        container_id=container_id,
        container_name=container_name,
        status=status,
        scope=scope,
        created_at=now,
        last_heartbeat=now,
        workspace_path=workspace_path,
        timeout_seconds=timeout_seconds,
    )


class TestWorkspaceState:
    """Tests for WorkspaceState dataclass."""

    def test_create_state(self):
        """Test creating a workspace state."""
        state = make_workspace_state()

        assert state.run_id == "run-123"
        assert state.status == WorkspaceStatus.RUNNING
        assert state.created_at is not None
        assert state.last_heartbeat is not None

    def test_state_serialization(self):
        """Test state can be serialized to dict."""
        state = make_workspace_state()

        data = state.to_dict()

        assert data["run_id"] == "run-123"
        assert data["container_id"] == "abc123"
        assert data["status"] == "running"

    def test_state_deserialization(self):
        """Test state can be created from dict."""
        data = {
            "run_id": "run-123",
            "container_id": "abc123",
            "container_name": "amprealize-ws-run-123",
            "scope": "org:tenant-abc",
            "workspace_path": "/workspace",
            "timeout_seconds": 3600,
            "status": "running",
            "created_at": "2025-01-01T00:00:00+00:00",
            "last_heartbeat": "2025-01-01T00:00:00+00:00",
        }

        state = WorkspaceState.from_dict(data)

        assert state.run_id == "run-123"
        assert state.status == WorkspaceStatus.RUNNING


class TestInMemoryStateStore:
    """Tests for in-memory state store."""

    @pytest.fixture
    def store(self):
        return InMemoryStateStore()

    @pytest.mark.asyncio
    async def test_set_and_get(self, store):
        """Test storing and retrieving state."""
        state = make_workspace_state()

        await store.set(state)
        retrieved = await store.get("run-123")

        assert retrieved is not None
        assert retrieved.run_id == "run-123"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, store):
        """Test getting non-existent state returns None."""
        result = await store.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete(self, store):
        """Test deleting state."""
        state = make_workspace_state()

        await store.set(state)
        await store.delete("run-123")

        result = await store.get("run-123")
        assert result is None

    @pytest.mark.asyncio
    async def test_count_by_scope(self, store):
        """Test counting workspaces by scope."""
        # Add workspaces for different scopes
        for i in range(3):
            state = make_workspace_state(
                run_id=f"run-tenant-a-{i}",
                container_id=f"abc{i}",
                container_name=f"amprealize-ws-run-{i}",
                scope="org:tenant-a",
            )
            await store.set(state)

        for i in range(2):
            state = make_workspace_state(
                run_id=f"run-tenant-b-{i}",
                container_id=f"xyz{i}",
                container_name=f"amprealize-ws-run-b-{i}",
                scope="org:tenant-b",
            )
            await store.set(state)

        count_a = await store.count_by_scope("org:tenant-a")
        count_b = await store.count_by_scope("org:tenant-b")
        count_c = await store.count_by_scope("org:tenant-c")

        assert count_a == 3
        assert count_b == 2
        assert count_c == 0

    @pytest.mark.asyncio
    async def test_list_by_scope(self, store):
        """Test listing workspaces by scope."""
        state1 = make_workspace_state(
            run_id="run-1",
            container_id="abc1",
            container_name="amprealize-ws-run-1",
            scope="org:tenant-a",
        )
        state2 = make_workspace_state(
            run_id="run-2",
            container_id="abc2",
            container_name="amprealize-ws-run-2",
            scope="org:tenant-a",
        )

        await store.set(state1)
        await store.set(state2)

        states = await store.list_by_scope("org:tenant-a")

        assert len(states) == 2
        run_ids = {s.run_id for s in states}
        assert run_ids == {"run-1", "run-2"}

    @pytest.mark.asyncio
    async def test_find_stale(self, store):
        """Test finding stale workspaces."""
        # Fresh workspace
        fresh = make_workspace_state(
            run_id="run-fresh",
            container_id="abc1",
            container_name="amprealize-ws-fresh",
        )
        await store.set(fresh)

        # Stale workspace
        stale = make_workspace_state(
            run_id="run-stale",
            container_id="abc2",
            container_name="amprealize-ws-stale",
        )
        stale.last_heartbeat = (
            datetime.now(timezone.utc) - timedelta(minutes=10)
        ).isoformat()
        await store.set(stale)

        # Find stale with 5 minute threshold
        stale_states = await store.find_stale(max_idle_seconds=300)

        assert len(stale_states) == 1
        assert stale_states[0].run_id == "run-stale"

    @pytest.mark.asyncio
    async def test_update_heartbeat(self, store):
        """Test updating heartbeat."""
        state = make_workspace_state()
        await store.set(state)

        old_heartbeat = state.last_heartbeat
        await asyncio.sleep(0.01)

        new_time = datetime.now(timezone.utc)
        await store.update_heartbeat("run-123", new_time)

        updated = await store.get("run-123")
        assert updated.last_heartbeat != old_heartbeat

    @pytest.mark.asyncio
    async def test_health_check(self, store):
        """Test health check returns True."""
        result = await store.health_check()
        assert result is True


class TestRedisStateStore:
    """Tests for Redis state store (requires mocking)."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client with pipeline support."""
        mock = AsyncMock()
        mock.get = AsyncMock(return_value=None)
        mock.set = AsyncMock(return_value=True)
        mock.delete = AsyncMock(return_value=1)
        mock.sadd = AsyncMock(return_value=1)
        mock.srem = AsyncMock(return_value=1)
        mock.scard = AsyncMock(return_value=0)
        mock.smembers = AsyncMock(return_value=set())
        mock.keys = AsyncMock(return_value=[])
        mock.ping = AsyncMock(return_value=True)
        mock.close = AsyncMock()

        # Mock pipeline context manager
        mock_pipeline = AsyncMock()
        mock_pipeline.set = MagicMock()
        mock_pipeline.sadd = MagicMock()
        mock_pipeline.execute = AsyncMock(return_value=[True, 1])
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock(return_value=None)
        mock.pipeline = MagicMock(return_value=mock_pipeline)

        return mock

    @pytest.mark.asyncio
    async def test_set_and_get(self, mock_redis):
        """Test storing and retrieving state with mocked Redis."""
        store = RedisStateStore.__new__(RedisStateStore)
        store._client = mock_redis  # Set the internal client
        store._ttl_seconds = None  # No TTL for this test

        state = make_workspace_state()

        await store.set(state)

        # Verify pipeline was used
        mock_redis.pipeline.assert_called_once()
        pipeline = mock_redis.pipeline.return_value
        pipeline.set.assert_called_once()
        call_args = str(pipeline.set.call_args)
        assert "breakeramp:workspace:run-123" in call_args

    @pytest.mark.asyncio
    async def test_count_by_scope(self, mock_redis):
        """Test counting by scope with mocked Redis."""
        mock_redis.scard.return_value = 5

        store = RedisStateStore.__new__(RedisStateStore)
        store._client = mock_redis  # Set the internal client

        count = await store.count_by_scope("org:tenant-a")

        assert count == 5
        mock_redis.scard.assert_called_with("breakeramp:workspace:scope:org:tenant-a")

    @pytest.mark.asyncio
    async def test_health_check_success(self, mock_redis):
        """Test health check when Redis is available."""
        store = RedisStateStore.__new__(RedisStateStore)
        store._client = mock_redis  # Set the internal client

        result = await store.health_check()

        assert result is True
        mock_redis.ping.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_failure(self, mock_redis):
        """Test health check when Redis is unavailable."""
        mock_redis.ping.side_effect = Exception("Connection refused")

        store = RedisStateStore.__new__(RedisStateStore)
        store._client = mock_redis  # Set the internal client

        result = await store.health_check()

        assert result is False
