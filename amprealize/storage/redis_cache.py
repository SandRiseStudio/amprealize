"""Redis cache layer for amprealize services.

Provides TTL-based caching for stable data (approved behaviors, workflow templates)
to reduce database load and improve P95 latency from ~700ms to <100ms.

Architecture:
- Key pattern: {service}:{operation}:{params_hash}
- TTL defaults: Centralized in config.settings.CacheTTLConfig
- Strategy: Longer TTLs (30min) with explicit invalidation on writes
- Eviction: allkeys-lru (set in redis config)
- Invalidation: Manual on write operations via invalidate_* methods

Usage:
    cache = RedisCache(host='localhost', port=6379)

    # Read-through cache with centralized TTL
    from amprealize.config.settings import settings
    data = cache.get('behavior:list:status=APPROVED')
    if data is None:
        data = expensive_database_query()
        cache.set('behavior:list:status=APPROVED', data, ttl=settings.cache_ttl.behavior_list_ttl)

    # Explicit invalidation on write
    cache.invalidate_behavior()  # Clears all behavior:* keys
    cache.delete('behavior:list:*')  # Pattern-based invalidation
"""

import json
import hashlib
import os
from typing import Any, Dict, List, Optional, Union
from uuid import UUID
from datetime import datetime, date
import redis
from redis.connection import ConnectionPool

# Import settings for multi-environment configuration
try:
    from amprealize.config.settings import settings
    SETTINGS_AVAILABLE = True
except ImportError:
    SETTINGS_AVAILABLE = False


class CacheJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles UUID and datetime objects."""

    def default(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)



class RedisCache:
    """Redis-backed cache with TTL support and pattern-based invalidation."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        db: int = 0,
        password: Optional[str] = None,
        max_connections: int = 50,
    ):
        """Initialize Redis connection pool.

        Args:
            host: Redis hostname (default: from settings or localhost)
            port: Redis port (default: from settings or 6379)
            db: Redis database number (default: 0)
            password: Redis password (default: from settings or None)
            max_connections: Max connections in pool
        """
        # Resolve connection parameters from settings or environment
        if SETTINGS_AVAILABLE and host is None:
            # Parse redis_url from settings (format: redis://host:port/db or redis://host:port)
            redis_url = settings.cache.redis_url  # type: ignore[possibly-unbound]
            if redis_url.startswith('redis://'):
                # Simple URL parsing (for production, consider using urllib.parse)
                url_parts = redis_url.replace('redis://', '').split('/')
                host_port = url_parts[0].split(':')
                self.host = host_port[0]
                self.port = int(host_port[1]) if len(host_port) > 1 else 6379
                db = int(url_parts[1]) if len(url_parts) > 1 else 0
            else:
                self.host = 'localhost'
                self.port = 6379
        else:
            # Fallback to parameters or legacy environment variables
            self.host = host or os.getenv('REDIS_HOST', 'localhost')
            self.port = int(port or os.getenv('REDIS_PORT', 6379))

        self.password = password or os.getenv('REDIS_PASSWORD')

        self.pool = ConnectionPool(
            host=self.host,
            port=self.port,
            db=db,
            password=self.password,
            max_connections=max_connections,
            decode_responses=True,  # Auto-decode bytes to str
        )

        self.client = redis.Redis(connection_pool=self.pool)

    def _make_key(self, service: str, operation: str, params: Optional[Dict[str, Any]] = None) -> str:
        """Generate cache key from service, operation, and params.

        Args:
            service: Service name (e.g., 'behavior', 'workflow')
            operation: Operation name (e.g., 'list', 'get')
            params: Optional parameters dict for key uniqueness

        Returns:
            Cache key like 'behavior:list:abc123' where abc123 is params hash
        """
        if params:
            # Sort params for consistent hashing
            params_str = json.dumps(params, sort_keys=True)
            params_hash = hashlib.md5(params_str.encode()).hexdigest()[:8]
            return f"{service}:{operation}:{params_hash}"
        return f"{service}:{operation}"

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value (JSON-decoded) or None if miss
        """
        try:
            value = self.client.get(key)
            if value is None:
                return None
            return json.loads(value)
        except (redis.RedisError, json.JSONDecodeError) as exc:
            # Log error but don't crash - cache miss is safe
            print(f"Redis GET error for key {key}: {exc}")
            return None

    def set(self, key: str, value: Any, ttl: int = 300) -> bool:
        """Set value in cache with TTL.

        Args:
            key: Cache key
            value: Value to cache (will be JSON-encoded)
            ttl: Time-to-live in seconds (default: 5min)

        Returns:
            True if successful, False on error
        """
        try:
            json_value = json.dumps(value, cls=CacheJSONEncoder)
            self.client.setex(key, ttl, json_value)
            return True
        except (redis.RedisError, TypeError) as exc:
            print(f"Redis SET error for key {key}: {exc}")
            return False

    def delete(self, pattern: str) -> int:
        """Delete keys matching pattern.

        Args:
            pattern: Redis key pattern with wildcards (* and ?)
                     Example: 'behavior:list:*' deletes all list cache entries

        Returns:
            Number of keys deleted
        """
        try:
            keys = self.client.keys(pattern)
            if keys:
                return self.client.delete(*keys)
            return 0
        except redis.RedisError as exc:
            print(f"Redis DELETE error for pattern {pattern}: {exc}")
            return 0

    def invalidate_service(self, service: str) -> int:
        """Invalidate all cache entries for a service.

        Args:
            service: Service name (e.g., 'behavior', 'workflow')

        Returns:
            Number of keys deleted
        """
        return self.delete(f"{service}:*")

    def invalidate_behavior(self, behavior_id: Optional[str] = None) -> int:
        """Invalidate behavior cache entries.

        Call on: create_behavior_draft, update_behavior_draft,
                 approve_behavior, deprecate_behavior, delete_behavior_draft

        Args:
            behavior_id: If provided, invalidate specific behavior; otherwise all

        Returns:
            Number of keys deleted
        """
        if behavior_id:
            # Invalidate specific behavior and list caches
            count = self.delete(f"behavior:get:{behavior_id}:*")
            count += self.delete("behavior:list:*")
            count += self.delete("behavior:search:*")
            return count
        return self.delete("behavior:*")

    def invalidate_workflow(self, template_id: Optional[str] = None) -> int:
        """Invalidate workflow cache entries.

        Call on: create_template, update_template, delete_template

        Args:
            template_id: If provided, invalidate specific template; otherwise all

        Returns:
            Number of keys deleted
        """
        if template_id:
            count = self.delete(f"workflow:get:{template_id}:*")
            count += self.delete("workflow:list:*")
            return count
        return self.delete("workflow:*")

    def invalidate_compliance(self, checklist_id: Optional[str] = None) -> int:
        """Invalidate compliance cache entries.

        Call on: create_checklist, update_checklist, add_step, complete_step

        Args:
            checklist_id: If provided, invalidate specific checklist; otherwise all

        Returns:
            Number of keys deleted
        """
        if checklist_id:
            count = self.delete(f"compliance:get:{checklist_id}:*")
            count += self.delete("compliance:list:*")
            return count
        return self.delete("compliance:*")

    def invalidate_action(self, action_id: Optional[str] = None) -> int:
        """Invalidate action cache entries.

        Call on: record_action, update_action, delete_action

        Args:
            action_id: If provided, invalidate specific action; otherwise all

        Returns:
            Number of keys deleted
        """
        if action_id:
            count = self.delete(f"action:get:{action_id}:*")
            count += self.delete("action:list:*")
            return count
        return self.delete("action:*")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dict with keys: hits, misses, keys, memory_used_mb
        """
        try:
            info = self.client.info('stats')
            keyspace = self.client.info('keyspace')
            memory = self.client.info('memory')

            # Extract db0 keys if exists
            db_keys = 0
            if 'db0' in keyspace:
                db_keys = keyspace['db0']['keys']

            return {
                'hits': info.get('keyspace_hits', 0),
                'misses': info.get('keyspace_misses', 0),
                'keys': db_keys,
                'memory_used_mb': memory.get('used_memory', 0) / (1024 * 1024),
                'hit_rate': self._calculate_hit_rate(
                    info.get('keyspace_hits', 0),
                    info.get('keyspace_misses', 0)
                ),
            }
        except redis.RedisError as exc:
            print(f"Redis STATS error: {exc}")
            return {'error': str(exc)}

    @staticmethod
    def _calculate_hit_rate(hits: int, misses: int) -> float:
        """Calculate cache hit rate percentage."""
        total = hits + misses
        if total == 0:
            return 0.0
        return (hits / total) * 100

    def ping(self) -> bool:
        """Check if Redis is responsive.

        Returns:
            True if Redis responds to PING, False otherwise
        """
        try:
            return self.client.ping()
        except redis.RedisError:
            return False

    def close(self):
        """Close Redis connection pool."""
        self.pool.disconnect()


# Singleton instance for global cache access
_cache_instance: Optional[RedisCache] = None


def get_cache() -> RedisCache:
    """Get or create global cache instance.

    Returns:
        Shared RedisCache instance
    """
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = RedisCache()
    return _cache_instance


def get_ttl(service: str, operation: str) -> int:
    """Get TTL for a service/operation from centralized config.

    Falls back to sensible defaults if settings unavailable.

    Args:
        service: Service name (behavior, workflow, compliance, action, metrics)
        operation: Operation type (list, get, search)

    Returns:
        TTL in seconds
    """
    # Default fallbacks (used if settings not available)
    defaults = {
        'behavior': {'list': 1800, 'get': 1800, 'search': 1800},
        'workflow': {'list': 1800, 'get': 1800},
        'compliance': {'list': 900, 'get': 900},
        'action': {'list': 1800, 'get': 1800},
        'metrics': {'default': 30},
        'embedding': {'default': 3600},
    }

    if not SETTINGS_AVAILABLE:
        service_defaults = defaults.get(service, {'default': 1800})
        return service_defaults.get(operation, service_defaults.get('default', 1800))

    # Map service/operation to settings attribute
    ttl_map = {
        ('behavior', 'list'): settings.cache_ttl.behavior_list_ttl,
        ('behavior', 'get'): settings.cache_ttl.behavior_approved_ttl,
        ('behavior', 'search'): settings.cache_ttl.behavior_search_ttl,
        ('workflow', 'list'): settings.cache_ttl.workflow_list_ttl,
        ('workflow', 'get'): settings.cache_ttl.workflow_template_ttl,
        ('compliance', 'list'): settings.cache_ttl.compliance_list_ttl,
        ('compliance', 'get'): settings.cache_ttl.compliance_checklist_ttl,
        ('action', 'list'): settings.cache_ttl.action_list_ttl,
        ('action', 'get'): settings.cache_ttl.action_get_ttl,
        ('metrics', 'default'): settings.cache_ttl.metrics_ttl,
        ('embedding', 'default'): settings.cache_ttl.embedding_ttl,
    }

    return ttl_map.get((service, operation), defaults.get(service, {'default': 1800}).get(operation, 1800))
