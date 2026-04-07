"""Redis-backed rate limit storage for distributed rate limiting.

Implements token bucket, fixed window, and sliding window rate limiting
algorithms using Redis for distributed state across multiple instances.

Architecture:
- Token bucket: Uses Redis hash for bucket state + INCR for atomic updates
- Fixed window: Uses Redis string with TTL for request counts
- Sliding window: Uses Redis sorted set with timestamp scores

Key patterns:
- rate_limit:bucket:{scope}:{identifier} - token bucket state
- rate_limit:fixed:{rule_id}:{scope}:{identifier} - fixed window counter
- rate_limit:sliding:{rule_id}:{scope}:{identifier} - sliding window set

Usage:
    store = RateLimitStore()

    # Token bucket check
    allowed, remaining = store.check_token_bucket(
        scope="api", identifier="user123",
        burst_limit=100, refill_rate=10.0
    )

    # Fixed window check
    allowed, remaining = store.check_fixed_window(
        rule_id="rule1", scope="api", identifier="user123",
        max_requests=100, window_seconds=60
    )

Behaviors referenced:
- behavior_use_raze_for_logging: Operations logged to Raze
- behavior_externalize_configuration: Redis connection via settings
"""

import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple
import redis
from redis.connection import ConnectionPool

# Import settings for connection configuration
try:
    from amprealize.config.settings import settings
    SETTINGS_AVAILABLE = True
except ImportError:
    SETTINGS_AVAILABLE = False


class RateLimitStore:
    """Redis-backed rate limit state storage."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        db: int = 1,  # Use separate DB from cache to avoid accidental eviction
        password: Optional[str] = None,
        max_connections: int = 50,
        key_prefix: str = "rate_limit"
    ):
        """Initialize Redis connection for rate limiting.

        Args:
            host: Redis hostname (default: from settings or localhost)
            port: Redis port (default: from settings or 6379)
            db: Redis database number (default: 1 - separate from cache)
            password: Redis password
            max_connections: Max connections in pool
            key_prefix: Prefix for all rate limit keys
        """
        import os

        # Resolve connection from settings if available
        if SETTINGS_AVAILABLE and host is None:
            redis_url = settings.cache.redis_url
            if redis_url.startswith('redis://'):
                url_parts = redis_url.replace('redis://', '').split('/')
                host_port = url_parts[0].split(':')
                self.host = host_port[0]
                self.port = int(host_port[1]) if len(host_port) > 1 else 6379
            else:
                self.host = 'localhost'
                self.port = 6379
        else:
            self.host = host or os.getenv('REDIS_HOST', 'localhost')
            self.port = int(port or os.getenv('REDIS_PORT', 6379))

        self.password = password or os.getenv('REDIS_PASSWORD')
        self.key_prefix = key_prefix

        self.pool = ConnectionPool(
            host=self.host,
            port=self.port,
            db=db,
            password=self.password,
            max_connections=max_connections,
            decode_responses=True,
        )

        self.client = redis.Redis(connection_pool=self.pool)

    def _make_key(self, *parts: str) -> str:
        """Generate rate limit key from parts."""
        return ":".join([self.key_prefix] + list(parts))

    def check_token_bucket(
        self,
        scope: str,
        identifier: str,
        burst_limit: int,
        refill_rate: float,
    ) -> Tuple[bool, int, datetime]:
        """Check and consume from token bucket.

        Atomic token bucket implementation using Redis Lua script.

        Args:
            scope: Rate limit scope (e.g., 'api', 'mcp', 'device_flow')
            identifier: Unique identifier (e.g., user_id, ip, api_key)
            burst_limit: Maximum tokens in bucket
            refill_rate: Tokens per second refill rate

        Returns:
            Tuple of (allowed, remaining_tokens, reset_time)
        """
        key = self._make_key("bucket", scope, identifier)
        now = time.time()

        # Lua script for atomic token bucket operation
        # Keys: [bucket_key]
        # Args: [now_timestamp, burst_limit, refill_rate]
        lua_script = """
        local key = KEYS[1]
        local now = tonumber(ARGV[1])
        local burst_limit = tonumber(ARGV[2])
        local refill_rate = tonumber(ARGV[3])

        -- Get current bucket state
        local tokens = tonumber(redis.call('HGET', key, 'tokens'))
        local last_refill = tonumber(redis.call('HGET', key, 'last_refill'))

        -- Initialize bucket if not exists
        if tokens == nil then
            tokens = burst_limit
            last_refill = now
        end

        -- Calculate refill since last check
        local elapsed = now - last_refill
        local refill_amount = elapsed * refill_rate
        tokens = math.min(burst_limit, tokens + refill_amount)

        -- Check if we can consume a token
        if tokens >= 1 then
            tokens = tokens - 1
            redis.call('HSET', key, 'tokens', tokens, 'last_refill', now)
            redis.call('EXPIRE', key, 3600)  -- Expire after 1 hour of inactivity
            return {1, math.floor(tokens)}
        else
            -- Update last_refill but don't consume
            redis.call('HSET', key, 'last_refill', now)
            redis.call('EXPIRE', key, 3600)
            return {0, 0}
        end
        """

        try:
            result = self.client.eval(lua_script, 1, key, now, burst_limit, refill_rate)
            allowed = bool(result[0])
            remaining = int(result[1])

            # Calculate reset time (when one token will be available)
            if remaining == 0:
                reset_time = datetime.utcnow() + timedelta(seconds=1.0 / refill_rate)
            else:
                reset_time = datetime.utcnow()

            return allowed, remaining, reset_time

        except redis.RedisError as e:
            # On Redis failure, allow request but log error
            print(f"Redis token bucket error: {e}")
            return True, burst_limit, datetime.utcnow()

    def check_fixed_window(
        self,
        rule_id: str,
        scope: str,
        identifier: str,
        max_requests: int,
        window_seconds: int,
    ) -> Tuple[bool, int, datetime]:
        """Check fixed window rate limit.

        Uses Redis string with TTL for simple counter per window.

        Args:
            rule_id: Rate limit rule identifier
            scope: Rate limit scope
            identifier: Unique identifier
            max_requests: Maximum requests per window
            window_seconds: Window duration in seconds

        Returns:
            Tuple of (allowed, remaining_requests, reset_time)
        """
        # Use window start time in key for alignment
        now = int(time.time())
        window_start = now - (now % window_seconds)
        key = self._make_key("fixed", rule_id, scope, identifier, str(window_start))

        try:
            # Atomic increment and TTL set
            pipe = self.client.pipeline()
            pipe.incr(key)
            pipe.expire(key, window_seconds + 1)  # Extra second buffer
            result = pipe.execute()

            count = result[0]
            allowed = count <= max_requests
            remaining = max(0, max_requests - count)

            # Reset time is end of current window
            reset_time = datetime.utcfromtimestamp(window_start + window_seconds)

            return allowed, remaining, reset_time

        except redis.RedisError as e:
            print(f"Redis fixed window error: {e}")
            return True, max_requests, datetime.utcnow() + timedelta(seconds=window_seconds)

    def check_sliding_window(
        self,
        rule_id: str,
        scope: str,
        identifier: str,
        max_requests: int,
        window_seconds: int,
    ) -> Tuple[bool, int, datetime]:
        """Check sliding window rate limit.

        Uses Redis sorted set with timestamps as scores for precise sliding window.

        Args:
            rule_id: Rate limit rule identifier
            scope: Rate limit scope
            identifier: Unique identifier
            max_requests: Maximum requests per window
            window_seconds: Window duration in seconds

        Returns:
            Tuple of (allowed, remaining_requests, reset_time)
        """
        key = self._make_key("sliding", rule_id, scope, identifier)
        now = time.time()
        window_start = now - window_seconds

        # Lua script for atomic sliding window operation
        lua_script = """
        local key = KEYS[1]
        local now = tonumber(ARGV[1])
        local window_start = tonumber(ARGV[2])
        local max_requests = tonumber(ARGV[3])
        local window_seconds = tonumber(ARGV[4])

        -- Remove expired entries
        redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)

        -- Count current requests in window
        local count = redis.call('ZCARD', key)

        if count < max_requests then
            -- Add new request with timestamp + unique suffix
            redis.call('ZADD', key, now, now .. ':' .. redis.call('INCR', key .. ':seq'))
            redis.call('EXPIRE', key, window_seconds + 1)
            redis.call('EXPIRE', key .. ':seq', window_seconds + 1)
            return {1, max_requests - count - 1}
        else
            -- Get oldest entry for reset time
            local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
            local reset_at = oldest[2] and (oldest[2] + window_seconds) or (now + 1)
            return {0, 0, reset_at}
        end
        """

        try:
            result = self.client.eval(
                lua_script, 1, key,
                now, window_start, max_requests, window_seconds
            )

            allowed = bool(result[0])
            remaining = int(result[1])

            if len(result) > 2:
                reset_time = datetime.utcfromtimestamp(float(result[2]))
            else:
                reset_time = datetime.utcnow()

            return allowed, remaining, reset_time

        except redis.RedisError as e:
            print(f"Redis sliding window error: {e}")
            return True, max_requests, datetime.utcnow() + timedelta(seconds=window_seconds)

    def get_user_usage(
        self,
        scope: str,
        identifier: str,
        window_seconds: int = 3600,
    ) -> Dict[str, Any]:
        """Get usage statistics for a user.

        Args:
            scope: Rate limit scope
            identifier: User identifier
            window_seconds: Time window for stats

        Returns:
            Dict with usage metrics
        """
        now = time.time()

        try:
            # Get token bucket state
            bucket_key = self._make_key("bucket", scope, identifier)
            bucket_tokens = self.client.hget(bucket_key, 'tokens')

            # Scan for sliding window keys
            pattern = self._make_key("sliding", "*", scope, identifier)
            sliding_keys = list(self.client.scan_iter(pattern, count=100))

            total_requests = 0
            for key in sliding_keys:
                count = self.client.zcount(key, now - window_seconds, now)
                total_requests += count

            return {
                "identifier": identifier,
                "scope": scope,
                "bucket_tokens": float(bucket_tokens) if bucket_tokens else None,
                "requests_last_hour": total_requests,
                "window_seconds": window_seconds,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except redis.RedisError as e:
            return {"error": str(e)}

    def reset_user_limits(self, scope: str, identifier: str) -> int:
        """Reset all rate limits for a user.

        Args:
            scope: Rate limit scope
            identifier: User identifier

        Returns:
            Number of keys deleted
        """
        patterns = [
            self._make_key("bucket", scope, identifier),
            self._make_key("fixed", "*", scope, identifier, "*"),
            self._make_key("sliding", "*", scope, identifier),
        ]

        deleted = 0
        try:
            for pattern in patterns:
                if "*" in pattern:
                    keys = list(self.client.scan_iter(pattern, count=1000))
                    if keys:
                        deleted += self.client.delete(*keys)
                else:
                    deleted += self.client.delete(pattern)
            return deleted
        except redis.RedisError as e:
            print(f"Redis reset error: {e}")
            return 0

    def ping(self) -> bool:
        """Check if Redis is responsive."""
        try:
            return self.client.ping()
        except redis.RedisError:
            return False

    def close(self):
        """Close Redis connection pool."""
        self.pool.disconnect()


# Singleton instance
_store_instance: Optional[RateLimitStore] = None


def get_rate_limit_store() -> RateLimitStore:
    """Get or create global rate limit store instance."""
    global _store_instance
    if _store_instance is None:
        _store_instance = RateLimitStore()
    return _store_instance
