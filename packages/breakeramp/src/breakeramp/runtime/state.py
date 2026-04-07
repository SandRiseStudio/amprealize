"""State store abstraction for workspace orchestration.

Provides pluggable backends for persisting workspace state:
- InMemoryStateStore: For testing and single-instance deployments
- RedisStateStore: For distributed/production deployments

Migrated from workspace-agent to consolidate in BreakerAmp.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class WorkspaceStatus(str, Enum):
    """Status of a workspace container."""
    PROVISIONING = "provisioning"
    READY = "ready"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    CLEANING = "cleaning"


@dataclass
class WorkspaceState:
    """Runtime state of a provisioned workspace.

    Stored in Redis/memory for tracking active workspaces.
    """
    run_id: str
    container_id: str
    container_name: str
    status: WorkspaceStatus
    scope: str  # "org:{org_id}" or "user:{user_id}"

    # Timestamps
    created_at: str  # ISO format
    last_heartbeat: Optional[str] = None  # ISO format

    # Configuration
    workspace_path: str = "/workspace"
    memory_limit: str = "2g"
    cpu_limit: float = 2.0
    timeout_seconds: int = 3600

    # Optional context
    project_id: Optional[str] = None
    agent_id: Optional[str] = None
    github_repo: Optional[str] = None

    # Metadata
    labels: Dict[str, str] = field(default_factory=dict)
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkspaceState":
        """Create from dictionary."""
        status = data.get("status", "ready")
        if isinstance(status, str):
            status = WorkspaceStatus(status)
        data["status"] = status
        return cls(**data)

    def to_json(self) -> str:
        """Serialize to JSON."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, json_str: str) -> "WorkspaceState":
        """Deserialize from JSON."""
        return cls.from_dict(json.loads(json_str))


class StateStore(ABC):
    """Abstract base class for workspace state storage."""

    @abstractmethod
    async def get(self, run_id: str) -> Optional[WorkspaceState]:
        """Get workspace state by run ID."""
        pass

    @abstractmethod
    async def set(self, state: WorkspaceState) -> None:
        """Store workspace state."""
        pass

    @abstractmethod
    async def delete(self, run_id: str) -> bool:
        """Delete workspace state. Returns True if deleted."""
        pass

    @abstractmethod
    async def list_all(self) -> List[WorkspaceState]:
        """List all workspaces."""
        pass

    @abstractmethod
    async def list_by_scope(self, scope: str) -> List[WorkspaceState]:
        """List workspaces by scope (tenant isolation)."""
        pass

    @abstractmethod
    async def list_by_status(self, status: WorkspaceStatus) -> List[WorkspaceState]:
        """List workspaces by status."""
        pass

    @abstractmethod
    async def count_by_scope(self, scope: str) -> int:
        """Count workspaces for a scope (for quota enforcement)."""
        pass

    @abstractmethod
    async def find_stale(self, max_idle_seconds: int) -> List[WorkspaceState]:
        """Find workspaces with stale heartbeats (zombies)."""
        pass

    @abstractmethod
    async def update_heartbeat(self, run_id: str, timestamp: datetime) -> bool:
        """Update heartbeat timestamp. Returns True if updated."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if state store is healthy."""
        pass


class InMemoryStateStore(StateStore):
    """In-memory state store for testing and single-instance deployments.

    Warning: State is lost on restart. Use RedisStateStore for production.
    """

    def __init__(self) -> None:
        self._workspaces: Dict[str, WorkspaceState] = {}

    async def get(self, run_id: str) -> Optional[WorkspaceState]:
        return self._workspaces.get(run_id)

    async def set(self, state: WorkspaceState) -> None:
        self._workspaces[state.run_id] = state

    async def delete(self, run_id: str) -> bool:
        if run_id in self._workspaces:
            del self._workspaces[run_id]
            return True
        return False

    async def list_all(self) -> List[WorkspaceState]:
        return list(self._workspaces.values())

    async def list_by_scope(self, scope: str) -> List[WorkspaceState]:
        return [w for w in self._workspaces.values() if w.scope == scope]

    async def list_by_status(self, status: WorkspaceStatus) -> List[WorkspaceState]:
        return [w for w in self._workspaces.values() if w.status == status]

    async def count_by_scope(self, scope: str) -> int:
        return len([w for w in self._workspaces.values() if w.scope == scope])

    async def find_stale(self, max_idle_seconds: int) -> List[WorkspaceState]:
        """Find workspaces with stale heartbeats."""
        stale = []
        now = datetime.now(timezone.utc)

        for w in self._workspaces.values():
            if w.last_heartbeat:
                try:
                    last_hb = datetime.fromisoformat(w.last_heartbeat.replace('Z', '+00:00'))
                    if (now - last_hb).total_seconds() > max_idle_seconds:
                        stale.append(w)
                except Exception:
                    pass
            elif w.status == WorkspaceStatus.RUNNING:
                # No heartbeat but running = stale
                stale.append(w)

        return stale

    async def update_heartbeat(self, run_id: str, timestamp: datetime) -> bool:
        if run_id in self._workspaces:
            self._workspaces[run_id].last_heartbeat = timestamp.isoformat()
            return True
        return False

    async def health_check(self) -> bool:
        return True


class RedisStateStore(StateStore):
    """Redis-backed state store for distributed deployments.

    Key patterns:
    - workspace:{run_id} - Individual workspace state (hash)
    - workspace:scope:{scope} - Set of run_ids by scope
    - workspace:status:{status} - Set of run_ids by status

    Example:
        store = RedisStateStore("redis://localhost:6379/0")
        await store.set(workspace_state)
        state = await store.get("run-123")
    """

    KEY_PREFIX = "breakeramp:workspace:"
    SCOPE_INDEX_PREFIX = "breakeramp:workspace:scope:"
    STATUS_INDEX_PREFIX = "breakeramp:workspace:status:"

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """Initialize Redis state store.

        Args:
            redis_url: Redis connection URL
            ttl_seconds: Optional TTL for keys (auto-expiry)
        """
        self._redis_url = redis_url
        self._ttl_seconds = ttl_seconds
        self._client = None

    async def _get_client(self):
        """Get or create Redis client (lazy initialization)."""
        if self._client is None:
            try:
                import redis.asyncio as redis
                self._client = redis.from_url(
                    self._redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                )
            except ImportError:
                raise RuntimeError("redis package required: pip install redis")
        return self._client

    def _key(self, run_id: str) -> str:
        """Get the key for a workspace."""
        return f"{self.KEY_PREFIX}{run_id}"

    def _scope_key(self, scope: str) -> str:
        """Get the index key for a scope."""
        return f"{self.SCOPE_INDEX_PREFIX}{scope}"

    def _status_key(self, status: WorkspaceStatus) -> str:
        """Get the index key for a status."""
        return f"{self.STATUS_INDEX_PREFIX}{status.value}"

    async def get(self, run_id: str) -> Optional[WorkspaceState]:
        client = await self._get_client()
        data = await client.get(self._key(run_id))
        if data:
            return WorkspaceState.from_json(data)
        return None

    async def set(self, state: WorkspaceState) -> None:
        client = await self._get_client()

        # Get old state to update indices
        old_state = await self.get(state.run_id)

        async with client.pipeline() as pipe:
            # Store state
            if self._ttl_seconds:
                pipe.setex(self._key(state.run_id), self._ttl_seconds, state.to_json())
            else:
                pipe.set(self._key(state.run_id), state.to_json())

            # Update scope index
            if old_state and old_state.scope != state.scope:
                pipe.srem(self._scope_key(old_state.scope), state.run_id)
            pipe.sadd(self._scope_key(state.scope), state.run_id)

            # Update status index
            if old_state and old_state.status != state.status:
                pipe.srem(self._status_key(old_state.status), state.run_id)
            pipe.sadd(self._status_key(state.status), state.run_id)

            await pipe.execute()

    async def delete(self, run_id: str) -> bool:
        client = await self._get_client()

        # Get state to clean up indices
        state = await self.get(run_id)
        if not state:
            return False

        async with client.pipeline() as pipe:
            pipe.delete(self._key(run_id))
            pipe.srem(self._scope_key(state.scope), run_id)
            pipe.srem(self._status_key(state.status), run_id)
            await pipe.execute()

        return True

    async def list_all(self) -> List[WorkspaceState]:
        client = await self._get_client()

        # Scan for all workspace keys
        states = []
        async for key in client.scan_iter(match=f"{self.KEY_PREFIX}*"):
            # Skip index keys
            if ":scope:" in key or ":status:" in key:
                continue
            data = await client.get(key)
            if data:
                states.append(WorkspaceState.from_json(data))

        return states

    async def list_by_scope(self, scope: str) -> List[WorkspaceState]:
        client = await self._get_client()
        run_ids = await client.smembers(self._scope_key(scope))

        states = []
        for run_id in run_ids:
            state = await self.get(run_id)
            if state:
                states.append(state)

        return states

    async def list_by_status(self, status: WorkspaceStatus) -> List[WorkspaceState]:
        client = await self._get_client()
        run_ids = await client.smembers(self._status_key(status))

        states = []
        for run_id in run_ids:
            state = await self.get(run_id)
            if state:
                states.append(state)

        return states

    async def count_by_scope(self, scope: str) -> int:
        client = await self._get_client()
        return await client.scard(self._scope_key(scope))

    async def find_stale(self, max_idle_seconds: int) -> List[WorkspaceState]:
        """Find workspaces with stale heartbeats."""
        running = await self.list_by_status(WorkspaceStatus.RUNNING)
        stale = []
        now = datetime.now(timezone.utc)

        for w in running:
            if w.last_heartbeat:
                try:
                    last_hb = datetime.fromisoformat(w.last_heartbeat.replace('Z', '+00:00'))
                    if (now - last_hb).total_seconds() > max_idle_seconds:
                        stale.append(w)
                except Exception:
                    stale.append(w)  # Can't parse = stale
            else:
                # No heartbeat but running = stale
                stale.append(w)

        return stale

    async def update_heartbeat(self, run_id: str, timestamp: datetime) -> bool:
        state = await self.get(run_id)
        if not state:
            return False

        state.last_heartbeat = timestamp.isoformat()
        await self.set(state)
        return True

    async def health_check(self) -> bool:
        try:
            client = await self._get_client()
            await client.ping()
            return True
        except Exception:
            return False

    async def close(self) -> None:
        """Close the Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None
