"""State store abstraction for workspace service.

Provides pluggable backends for persisting workspace state:
- InMemoryStateStore: For testing and single-instance deployments
- RedisStateStore: For distributed/production deployments
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, List, Optional

from workspace_agent.models import WorkspaceInfo, WorkspaceStatus

logger = logging.getLogger(__name__)


class StateStore(ABC):
    """Abstract base class for workspace state storage."""

    @abstractmethod
    async def get(self, run_id: str) -> Optional[WorkspaceInfo]:
        """Get workspace info by run ID."""
        pass

    @abstractmethod
    async def set(self, info: WorkspaceInfo) -> None:
        """Store workspace info."""
        pass

    @abstractmethod
    async def delete(self, run_id: str) -> bool:
        """Delete workspace info. Returns True if deleted."""
        pass

    @abstractmethod
    async def list_all(self) -> List[WorkspaceInfo]:
        """List all workspaces."""
        pass

    @abstractmethod
    async def list_by_status(self, status: WorkspaceStatus) -> List[WorkspaceInfo]:
        """List workspaces by status."""
        pass

    @abstractmethod
    async def list_expired(self, before: datetime) -> List[WorkspaceInfo]:
        """List workspaces with cleanup_at before the given time."""
        pass

    @abstractmethod
    async def count(self) -> int:
        """Count total workspaces."""
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
        self._workspaces: Dict[str, WorkspaceInfo] = {}

    async def get(self, run_id: str) -> Optional[WorkspaceInfo]:
        return self._workspaces.get(run_id)

    async def set(self, info: WorkspaceInfo) -> None:
        self._workspaces[info.run_id] = info

    async def delete(self, run_id: str) -> bool:
        if run_id in self._workspaces:
            del self._workspaces[run_id]
            return True
        return False

    async def list_all(self) -> List[WorkspaceInfo]:
        return list(self._workspaces.values())

    async def list_by_status(self, status: WorkspaceStatus) -> List[WorkspaceInfo]:
        return [w for w in self._workspaces.values() if w.status == status]

    async def list_expired(self, before: datetime) -> List[WorkspaceInfo]:
        expired = []
        before_iso = before.isoformat()
        for w in self._workspaces.values():
            if w.cleanup_at and w.cleanup_at < before_iso:
                expired.append(w)
        return expired

    async def count(self) -> int:
        return len(self._workspaces)

    async def health_check(self) -> bool:
        return True


class RedisStateStore(StateStore):
    """Redis-backed state store for distributed deployments.

    Uses a hash per workspace with JSON serialization.
    Key pattern: workspace:{run_id}

    Example:
        store = RedisStateStore("redis://localhost:6379/0")
        await store.set(workspace_info)
        info = await store.get("run-123")
    """

    KEY_PREFIX = "workspace:"
    INDEX_KEY = "workspace:index"  # Set of all run_ids
    STATUS_INDEX_PREFIX = "workspace:status:"  # Sets by status

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        key_prefix: str = "workspace:",
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """Initialize Redis state store.

        Args:
            redis_url: Redis connection URL
            key_prefix: Prefix for all keys
            ttl_seconds: Optional TTL for keys (auto-expiry)
        """
        self._redis_url = redis_url
        self._key_prefix = key_prefix
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
        """Generate Redis key for a run ID."""
        return f"{self._key_prefix}{run_id}"

    def _status_index_key(self, status: WorkspaceStatus) -> str:
        """Generate status index key."""
        return f"{self.STATUS_INDEX_PREFIX}{status.value}"

    async def get(self, run_id: str) -> Optional[WorkspaceInfo]:
        client = await self._get_client()
        data = await client.get(self._key(run_id))
        if data:
            try:
                return WorkspaceInfo.from_redis_dict(json.loads(data))
            except Exception as e:
                logger.error(f"Failed to deserialize workspace {run_id}: {e}")
                return None
        return None

    async def set(self, info: WorkspaceInfo) -> None:
        client = await self._get_client()
        key = self._key(info.run_id)
        data = json.dumps(info.to_redis_dict())

        # Get old status for index update
        old_info = await self.get(info.run_id)
        old_status = old_info.status if old_info else None

        # Set the data
        if self._ttl_seconds:
            await client.setex(key, self._ttl_seconds, data)
        else:
            await client.set(key, data)

        # Update indexes
        await client.sadd(self.INDEX_KEY, info.run_id)

        # Update status index
        if old_status and old_status != info.status:
            await client.srem(self._status_index_key(old_status), info.run_id)
        await client.sadd(self._status_index_key(info.status), info.run_id)

    async def delete(self, run_id: str) -> bool:
        client = await self._get_client()

        # Get status for index cleanup
        info = await self.get(run_id)

        # Delete the key
        deleted = await client.delete(self._key(run_id))

        # Update indexes
        await client.srem(self.INDEX_KEY, run_id)
        if info:
            await client.srem(self._status_index_key(info.status), run_id)

        return deleted > 0

    async def list_all(self) -> List[WorkspaceInfo]:
        client = await self._get_client()
        run_ids = await client.smembers(self.INDEX_KEY)

        workspaces = []
        for run_id in run_ids:
            info = await self.get(run_id)
            if info:
                workspaces.append(info)
        return workspaces

    async def list_by_status(self, status: WorkspaceStatus) -> List[WorkspaceInfo]:
        client = await self._get_client()
        run_ids = await client.smembers(self._status_index_key(status))

        workspaces = []
        for run_id in run_ids:
            info = await self.get(run_id)
            if info and info.status == status:
                workspaces.append(info)
        return workspaces

    async def list_expired(self, before: datetime) -> List[WorkspaceInfo]:
        # For expired workspaces, we need to scan CLEANUP_PENDING status
        pending = await self.list_by_status(WorkspaceStatus.CLEANUP_PENDING)

        before_iso = before.isoformat()
        expired = []
        for w in pending:
            if w.cleanup_at and w.cleanup_at < before_iso:
                expired.append(w)
        return expired

    async def count(self) -> int:
        client = await self._get_client()
        return await client.scard(self.INDEX_KEY)

    async def health_check(self) -> bool:
        try:
            client = await self._get_client()
            await client.ping()
            return True
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return False

    async def close(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None
