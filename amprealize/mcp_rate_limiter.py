"""
MCP Rate Limiter - Request-level rate limiting for MCP tool invocations.

Implements per-client and per-tool throttling with configurable limits to prevent
abuse by automated agents per docs/contracts/MCP_SERVER_DESIGN.md §9.

Key Features:
- Token bucket algorithm for smooth rate limiting
- Per-client tracking (based on session_id)
- Per-tool limits for sensitive operations
- Configurable via environment variables
- Metrics and telemetry integration

Phase 5 Enhancements (MCP_AUTH_IMPLEMENTATION_PLAN.md):
- Redis backend for distributed rate limiting across instances
- Per-tenant (org) rate limiting based on subscription tier
- Daily quota tracking for free tier
- Async Redis operations for non-blocking performance

Behaviors referenced:
- behavior_lock_down_security_surface: Rate limiting for DoS prevention
- behavior_use_raze_for_logging: Structured logging of limit events
- behavior_externalize_configuration: Tier limits from config
"""

from __future__ import annotations
import asyncio
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


# ============================================================================
# Subscription Tier Configuration (Phase 5)
# ============================================================================

class SubscriptionTier(str, Enum):
    """Subscription tiers with different rate limits."""
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"
    UNLIMITED = "unlimited"  # For internal/system use


@dataclass
class TierLimits:
    """Rate limit configuration per subscription tier."""
    requests_per_minute: int
    burst_size: int
    daily_quota: Optional[int] = None  # None = unlimited
    user_requests_per_minute: Optional[int] = None  # Per-user within org

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requests_per_minute": self.requests_per_minute,
            "burst_size": self.burst_size,
            "daily_quota": self.daily_quota,
            "user_requests_per_minute": self.user_requests_per_minute,
        }


# Default tier configurations - can be overridden via environment
TIER_LIMITS: Dict[SubscriptionTier, TierLimits] = {
    SubscriptionTier.FREE: TierLimits(
        requests_per_minute=60,
        burst_size=15,
        daily_quota=1000,
        user_requests_per_minute=30,
    ),
    SubscriptionTier.PRO: TierLimits(
        requests_per_minute=300,
        burst_size=75,
        daily_quota=10000,
        user_requests_per_minute=100,
    ),
    SubscriptionTier.ENTERPRISE: TierLimits(
        requests_per_minute=1000,
        burst_size=250,
        daily_quota=None,  # Unlimited
        user_requests_per_minute=300,
    ),
    SubscriptionTier.UNLIMITED: TierLimits(
        requests_per_minute=10000,
        burst_size=2500,
        daily_quota=None,
        user_requests_per_minute=None,
    ),
}


def get_tier_limits(tier: SubscriptionTier) -> TierLimits:
    """Get limits for a tier with environment variable overrides."""
    base = TIER_LIMITS.get(tier, TIER_LIMITS[SubscriptionTier.FREE])

    tier_name = tier.value.upper()
    rpm = os.getenv(f"AMPREALIZE_RATELIMIT_{tier_name}_RPM")
    burst = os.getenv(f"AMPREALIZE_RATELIMIT_{tier_name}_BURST")
    daily = os.getenv(f"AMPREALIZE_RATELIMIT_{tier_name}_DAILY")

    return TierLimits(
        requests_per_minute=int(rpm) if rpm else base.requests_per_minute,
        burst_size=int(burst) if burst else base.burst_size,
        daily_quota=int(daily) if daily else base.daily_quota,
        user_requests_per_minute=base.user_requests_per_minute,
    )


# ============================================================================
# Distributed Rate Limit Result (Phase 5)
# ============================================================================

@dataclass
class DistributedRateLimitResult:
    """Result from distributed (Redis-backed) rate limit check."""
    allowed: bool
    remaining: int
    reset_at: int  # Unix timestamp
    retry_after: Optional[int] = None
    limit_type: str = "minute"  # "minute", "daily", "burst"
    tier: str = "free"

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "allowed": self.allowed,
            "remaining": self.remaining,
            "reset_at": self.reset_at,
            "limit_type": self.limit_type,
            "tier": self.tier,
        }
        if self.retry_after is not None:
            result["retry_after"] = self.retry_after
        return result

    def get_headers(self) -> Dict[str, str]:
        """Generate rate limit response headers."""
        headers = {
            "X-RateLimit-Remaining": str(max(0, self.remaining)),
            "X-RateLimit-Reset": str(self.reset_at),
            "X-RateLimit-Tier": self.tier,
        }
        if self.retry_after is not None:
            headers["Retry-After"] = str(self.retry_after)
        return headers


# ============================================================================
# Original Classes (Enhanced)
# ============================================================================


class RateLimitDecision(str, Enum):
    """Decision from rate limiter."""
    ALLOW = "allow"
    DENY = "deny"
    WARN = "warn"  # Allow but log warning (soft limit)


@dataclass
class RateLimitConfig:
    """Configuration for a rate limit rule."""
    name: str
    max_requests: int  # Maximum requests allowed in window
    window_seconds: int  # Time window for counting requests
    burst_limit: int  # Maximum burst (token bucket capacity)
    refill_rate: float  # Tokens per second
    soft_limit_pct: float = 0.8  # Warn at 80% of limit

    def __post_init__(self):
        if self.max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if self.burst_limit <= 0:
            raise ValueError("burst_limit must be positive")
        if self.refill_rate <= 0:
            raise ValueError("refill_rate must be positive")


@dataclass
class TokenBucket:
    """Token bucket for smooth rate limiting."""
    tokens: float
    last_update: float  # Unix timestamp
    capacity: int
    refill_rate: float  # Tokens per second

    def consume(self, count: int = 1) -> Tuple[bool, float]:
        """
        Attempt to consume tokens. Returns (success, remaining_tokens).
        Automatically refills based on elapsed time.
        """
        now = time.time()
        elapsed = now - self.last_update

        # Refill tokens based on elapsed time
        self.tokens = min(self.capacity, self.tokens + (elapsed * self.refill_rate))
        self.last_update = now

        if self.tokens >= count:
            self.tokens -= count
            return True, self.tokens
        else:
            return False, self.tokens


@dataclass
class ClientState:
    """Per-client rate limiting state."""
    client_id: str
    global_bucket: TokenBucket
    tool_buckets: Dict[str, TokenBucket] = field(default_factory=dict)
    request_count: int = 0
    first_request_time: float = field(default_factory=time.time)
    last_request_time: float = field(default_factory=time.time)
    violations: int = 0
    warnings: int = 0


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""
    decision: RateLimitDecision
    client_id: str
    tool_name: str
    remaining_tokens: float
    retry_after_seconds: Optional[float] = None
    message: str = ""
    rule_name: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision.value,
            "client_id": self.client_id,
            "tool_name": self.tool_name,
            "remaining_tokens": round(self.remaining_tokens, 2),
            "retry_after_seconds": self.retry_after_seconds,
            "message": self.message,
            "rule_name": self.rule_name,
        }


class MCPRateLimiter:
    """
    MCP Server rate limiter with per-client and per-tool throttling.

    Default limits (configurable via environment):
    - Global: 100 requests/minute per client
    - Auth tools: 10 requests/minute
    - Write tools: 30 requests/minute
    - Read tools: 60 requests/minute

    Environment variables:
    - MCP_RATE_LIMIT_ENABLED: Enable/disable (default: true)
    - MCP_RATE_LIMIT_GLOBAL_MAX: Global max requests (default: 100)
    - MCP_RATE_LIMIT_GLOBAL_WINDOW: Window in seconds (default: 60)
    - MCP_RATE_LIMIT_AUTH_MAX: Auth tool max requests (default: 10)
    - MCP_RATE_LIMIT_WRITE_MAX: Write tool max requests (default: 30)
    - MCP_RATE_LIMIT_READ_MAX: Read tool max requests (default: 60)
    """

    # Tool categories for differentiated rate limiting
    AUTH_TOOLS = {
        "auth.deviceLogin",
        "auth.authStatus",
        "auth.refreshToken",
        "auth.logout",
        "auth.ensureGrant",
        "auth.listGrants",
        "auth.revoke",
        "auth.status",
    }

    WRITE_TOOLS = {
        "behaviors.createDraft",
        "behaviors.update",
        "behaviors.approve",
        "workflows.create",
        "workflows.update",
        "workflows.delete",
        "runs.create",
        "runs.updateStatus",
        "actions.create",
        "compliance.recordStep",
        "tasks.create",
        "tasks.updateStatus",
        "breakeramp.apply",
        "breakeramp.destroy",
        "config.update",
        "reflections.submitTrace",
    }

    # All other tools are considered READ tools

    # High-risk tools that should be more aggressively rate limited
    HIGH_RISK_TOOLS = {
        "auth.deviceLogin",
        "config.update",
        "behaviors.approve",
        "breakeramp.destroy",
    }

    def __init__(
        self,
        enabled: Optional[bool] = None,
        global_config: Optional[RateLimitConfig] = None,
        auth_config: Optional[RateLimitConfig] = None,
        write_config: Optional[RateLimitConfig] = None,
        read_config: Optional[RateLimitConfig] = None,
        high_risk_config: Optional[RateLimitConfig] = None,
    ) -> None:
        """Initialize rate limiter with configurable limits."""
        self._enabled = enabled if enabled is not None else self._env_bool("MCP_RATE_LIMIT_ENABLED", True)
        self._lock = Lock()
        self._clients: Dict[str, ClientState] = {}

        # Metrics
        self._metrics = {
            "checks_total": 0,
            "allows_total": 0,
            "denies_total": 0,
            "warnings_total": 0,
            "clients_seen": 0,
        }

        # Configure limits from environment or defaults
        self._global_config = global_config or RateLimitConfig(
            name="global",
            max_requests=self._env_int("MCP_RATE_LIMIT_GLOBAL_MAX", 100),
            window_seconds=self._env_int("MCP_RATE_LIMIT_GLOBAL_WINDOW", 60),
            burst_limit=self._env_int("MCP_RATE_LIMIT_GLOBAL_BURST", 20),
            refill_rate=self._env_float("MCP_RATE_LIMIT_GLOBAL_REFILL", 1.67),  # ~100/min
        )

        self._auth_config = auth_config or RateLimitConfig(
            name="auth",
            max_requests=self._env_int("MCP_RATE_LIMIT_AUTH_MAX", 10),
            window_seconds=60,
            burst_limit=self._env_int("MCP_RATE_LIMIT_AUTH_BURST", 5),
            refill_rate=0.17,  # ~10/min
        )

        self._write_config = write_config or RateLimitConfig(
            name="write",
            max_requests=self._env_int("MCP_RATE_LIMIT_WRITE_MAX", 30),
            window_seconds=60,
            burst_limit=self._env_int("MCP_RATE_LIMIT_WRITE_BURST", 10),
            refill_rate=0.5,  # ~30/min
        )

        self._read_config = read_config or RateLimitConfig(
            name="read",
            max_requests=self._env_int("MCP_RATE_LIMIT_READ_MAX", 60),
            window_seconds=60,
            burst_limit=self._env_int("MCP_RATE_LIMIT_READ_BURST", 15),
            refill_rate=1.0,  # ~60/min
        )

        self._high_risk_config = high_risk_config or RateLimitConfig(
            name="high_risk",
            max_requests=self._env_int("MCP_RATE_LIMIT_HIGH_RISK_MAX", 5),
            window_seconds=60,
            burst_limit=2,
            refill_rate=0.08,  # ~5/min
        )

        logger.info(
            f"MCPRateLimiter initialized: enabled={self._enabled}, "
            f"global={self._global_config.max_requests}/min, "
            f"auth={self._auth_config.max_requests}/min, "
            f"write={self._write_config.max_requests}/min, "
            f"read={self._read_config.max_requests}/min, "
            f"high_risk={self._high_risk_config.max_requests}/min"
        )

    @staticmethod
    def _env_bool(key: str, default: bool) -> bool:
        """Get boolean from environment."""
        val = os.environ.get(key, "").lower()
        if val in ("true", "1", "yes", "on"):
            return True
        elif val in ("false", "0", "no", "off"):
            return False
        return default

    @staticmethod
    def _env_int(key: str, default: int) -> int:
        """Get integer from environment."""
        try:
            return int(os.environ.get(key, str(default)))
        except ValueError:
            return default

    @staticmethod
    def _env_float(key: str, default: float) -> float:
        """Get float from environment."""
        try:
            return float(os.environ.get(key, str(default)))
        except ValueError:
            return default

    def _get_tool_config(self, tool_name: str) -> RateLimitConfig:
        """Get rate limit config for a tool based on its category."""
        if tool_name in self.HIGH_RISK_TOOLS:
            return self._high_risk_config
        elif tool_name in self.AUTH_TOOLS:
            return self._auth_config
        elif tool_name in self.WRITE_TOOLS:
            return self._write_config
        else:
            return self._read_config

    def _get_or_create_client(self, client_id: str) -> ClientState:
        """Get or create client state with proper locking."""
        if client_id not in self._clients:
            now = time.time()
            self._clients[client_id] = ClientState(
                client_id=client_id,
                global_bucket=TokenBucket(
                    tokens=self._global_config.burst_limit,
                    last_update=now,
                    capacity=self._global_config.burst_limit,
                    refill_rate=self._global_config.refill_rate,
                ),
            )
            self._metrics["clients_seen"] += 1
            logger.debug(f"Created rate limit state for client: {client_id}")
        return self._clients[client_id]

    def _get_or_create_tool_bucket(
        self, client_state: ClientState, tool_name: str
    ) -> TokenBucket:
        """Get or create tool-specific bucket."""
        if tool_name not in client_state.tool_buckets:
            config = self._get_tool_config(tool_name)
            now = time.time()
            client_state.tool_buckets[tool_name] = TokenBucket(
                tokens=config.burst_limit,
                last_update=now,
                capacity=config.burst_limit,
                refill_rate=config.refill_rate,
            )
        return client_state.tool_buckets[tool_name]

    def check(self, client_id: str, tool_name: str) -> RateLimitResult:
        """
        Check if a request should be allowed.

        Args:
            client_id: Unique client identifier (session_id, user_id, etc.)
            tool_name: MCP tool being invoked

        Returns:
            RateLimitResult with decision and metadata
        """
        self._metrics["checks_total"] += 1

        # Fast path: rate limiting disabled
        if not self._enabled:
            return RateLimitResult(
                decision=RateLimitDecision.ALLOW,
                client_id=client_id,
                tool_name=tool_name,
                remaining_tokens=float("inf"),
                message="Rate limiting disabled",
            )

        with self._lock:
            client = self._get_or_create_client(client_id)
            tool_config = self._get_tool_config(tool_name)
            tool_bucket = self._get_or_create_tool_bucket(client, tool_name)

            # Check global limit first
            global_ok, global_remaining = client.global_bucket.consume(1)

            if not global_ok:
                self._metrics["denies_total"] += 1
                client.violations += 1
                retry_after = (1.0 - global_remaining) / self._global_config.refill_rate

                logger.warning(
                    f"Rate limit DENIED: client={client_id}, tool={tool_name}, "
                    f"rule=global, remaining={global_remaining:.2f}"
                )

                return RateLimitResult(
                    decision=RateLimitDecision.DENY,
                    client_id=client_id,
                    tool_name=tool_name,
                    remaining_tokens=global_remaining,
                    retry_after_seconds=max(1.0, retry_after),
                    message=f"Global rate limit exceeded. Retry after {retry_after:.1f}s",
                    rule_name="global",
                )

            # Check tool-specific limit
            tool_ok, tool_remaining = tool_bucket.consume(1)

            if not tool_ok:
                # Refund global token since tool limit blocked
                client.global_bucket.tokens = min(
                    client.global_bucket.capacity,
                    client.global_bucket.tokens + 1
                )

                self._metrics["denies_total"] += 1
                client.violations += 1
                retry_after = (1.0 - tool_remaining) / tool_config.refill_rate

                logger.warning(
                    f"Rate limit DENIED: client={client_id}, tool={tool_name}, "
                    f"rule={tool_config.name}, remaining={tool_remaining:.2f}"
                )

                return RateLimitResult(
                    decision=RateLimitDecision.DENY,
                    client_id=client_id,
                    tool_name=tool_name,
                    remaining_tokens=tool_remaining,
                    retry_after_seconds=max(1.0, retry_after),
                    message=f"Tool rate limit exceeded for {tool_config.name}. Retry after {retry_after:.1f}s",
                    rule_name=tool_config.name,
                )

            # Check for soft limit warning (only if soft limits are enabled)
            global_pct = client.global_bucket.tokens / client.global_bucket.capacity
            tool_pct = tool_bucket.tokens / tool_bucket.capacity

            # Warning triggers when remaining percentage drops below (1 - soft_limit_pct)
            # e.g., soft_limit_pct=0.8 means warn when 80% consumed (20% remaining)
            # soft_limit_pct=0.0 disables warnings
            global_warn = self._global_config.soft_limit_pct > 0 and global_pct < (1 - self._global_config.soft_limit_pct)
            tool_warn = tool_config.soft_limit_pct > 0 and tool_pct < (1 - tool_config.soft_limit_pct)

            if global_warn or tool_warn:
                self._metrics["warnings_total"] += 1
                client.warnings += 1

                logger.info(
                    f"Rate limit WARNING: client={client_id}, tool={tool_name}, "
                    f"global_remaining={global_remaining:.2f}, tool_remaining={tool_remaining:.2f}"
                )

                return RateLimitResult(
                    decision=RateLimitDecision.WARN,
                    client_id=client_id,
                    tool_name=tool_name,
                    remaining_tokens=min(global_remaining, tool_remaining),
                    message="Approaching rate limit",
                    rule_name=tool_config.name if tool_pct < global_pct else "global",
                )

            # All checks passed
            self._metrics["allows_total"] += 1
            client.request_count += 1
            client.last_request_time = time.time()

            return RateLimitResult(
                decision=RateLimitDecision.ALLOW,
                client_id=client_id,
                tool_name=tool_name,
                remaining_tokens=min(global_remaining, tool_remaining),
            )

    def get_client_status(self, client_id: str) -> Optional[Dict[str, Any]]:
        """Get current rate limit status for a client."""
        with self._lock:
            if client_id not in self._clients:
                return None

            client = self._clients[client_id]
            now = time.time()

            # Calculate current token levels
            global_tokens = min(
                client.global_bucket.capacity,
                client.global_bucket.tokens +
                (now - client.global_bucket.last_update) * client.global_bucket.refill_rate
            )

            tool_status = {}
            for tool_name, bucket in client.tool_buckets.items():
                tokens = min(
                    bucket.capacity,
                    bucket.tokens + (now - bucket.last_update) * bucket.refill_rate
                )
                tool_status[tool_name] = {
                    "tokens": round(tokens, 2),
                    "capacity": bucket.capacity,
                    "pct_remaining": round(tokens / bucket.capacity * 100, 1),
                }

            return {
                "client_id": client_id,
                "global": {
                    "tokens": round(global_tokens, 2),
                    "capacity": client.global_bucket.capacity,
                    "pct_remaining": round(global_tokens / client.global_bucket.capacity * 100, 1),
                },
                "tools": tool_status,
                "stats": {
                    "request_count": client.request_count,
                    "violations": client.violations,
                    "warnings": client.warnings,
                    "first_request": datetime.fromtimestamp(client.first_request_time).isoformat(),
                    "last_request": datetime.fromtimestamp(client.last_request_time).isoformat(),
                },
            }

    def get_metrics(self) -> Dict[str, Any]:
        """Get rate limiter metrics for monitoring."""
        with self._lock:
            return {
                **self._metrics,
                "active_clients": len(self._clients),
                "enabled": self._enabled,
                "config": {
                    "global": {
                        "max_requests": self._global_config.max_requests,
                        "window_seconds": self._global_config.window_seconds,
                        "burst_limit": self._global_config.burst_limit,
                    },
                    "auth": {
                        "max_requests": self._auth_config.max_requests,
                        "burst_limit": self._auth_config.burst_limit,
                    },
                    "write": {
                        "max_requests": self._write_config.max_requests,
                        "burst_limit": self._write_config.burst_limit,
                    },
                    "read": {
                        "max_requests": self._read_config.max_requests,
                        "burst_limit": self._read_config.burst_limit,
                    },
                    "high_risk": {
                        "max_requests": self._high_risk_config.max_requests,
                        "burst_limit": self._high_risk_config.burst_limit,
                    },
                },
            }

    def reset_client(self, client_id: str) -> bool:
        """Reset rate limit state for a client (admin operation)."""
        with self._lock:
            if client_id in self._clients:
                del self._clients[client_id]
                logger.info(f"Reset rate limit state for client: {client_id}")
                return True
            return False

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable rate limiting."""
        self._enabled = enabled
        logger.info(f"Rate limiting {'enabled' if enabled else 'disabled'}")

    def cleanup_stale_clients(self, max_age_seconds: int = 3600) -> int:
        """Remove clients that haven't made requests in max_age_seconds."""
        now = time.time()
        removed = 0

        with self._lock:
            stale_clients = [
                client_id for client_id, state in self._clients.items()
                if now - state.last_request_time > max_age_seconds
            ]

            for client_id in stale_clients:
                del self._clients[client_id]
                removed += 1

        if removed > 0:
            logger.info(f"Cleaned up {removed} stale rate limit clients")

        return removed

# ============================================================================
# Distributed Rate Limiter (Phase 5: Redis-backed)
# ============================================================================

class DistributedRateLimiter:
    """Redis-backed distributed rate limiter for MCP with tenant awareness.

    Provides per-org and per-user rate limiting with subscription tier support.
    Falls back to in-memory limiting when Redis is unavailable.

    Key patterns:
    - mcp:ratelimit:org:{org_id}:minute - Per-org minute window
    - mcp:ratelimit:org:{org_id}:daily:{date} - Per-org daily quota
    - mcp:ratelimit:user:{user_id}:minute - Per-user minute window
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        tier_limits: Optional[Dict[SubscriptionTier, TierLimits]] = None,
        key_prefix: Optional[str] = None,
    ):
        """Initialize distributed rate limiter.

        Args:
            redis_url: Redis connection URL. If None, tries env vars.
            tier_limits: Override default tier limits.
        """
        self._tier_limits = tier_limits or TIER_LIMITS
        self._redis_client: Optional["aioredis.Redis"] = None
        self._use_redis = False
        self._redis_url = redis_url
        self._key_prefix = (
            key_prefix
            or os.getenv("AMPREALIZE_MCP_RATE_LIMIT_KEY_PREFIX")
            or "mcp:ratelimit"
        ).rstrip(":")

        # In-memory fallback state
        self._memory_counters: Dict[str, Dict[str, Any]] = {}
        self._memory_lock = Lock()

        # Metrics
        self._metrics = {
            "checks_total": 0,
            "redis_checks": 0,
            "memory_checks": 0,
            "denies_total": 0,
            "redis_errors": 0,
        }

    def _redis_key(self, *parts: str) -> str:
        """Build a Redis key using the configured prefix."""
        return ":".join([self._key_prefix, *parts])

    async def _ensure_redis(self) -> bool:
        """Lazily initialize Redis connection."""
        if self._redis_client is not None:
            return self._use_redis

        try:
            import redis.asyncio as aioredis

            url = self._redis_url or os.getenv("AMPREALIZE_REDIS_URL") or os.getenv("REDIS_URL")
            if not url:
                host = os.getenv("REDIS_HOST", "localhost")
                port = os.getenv("REDIS_PORT", "6379")
                db = os.getenv("REDIS_RATE_LIMIT_DB", "1")
                password = os.getenv("REDIS_PASSWORD", "")

                if password:
                    url = f"redis://:{password}@{host}:{port}/{db}"
                else:
                    url = f"redis://{host}:{port}/{db}"

            self._redis_client = aioredis.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )

            # Test connection
            await self._redis_client.ping()
            self._use_redis = True
            logger.info(f"Distributed rate limiter connected to Redis")
            return True

        except ImportError:
            logger.warning("redis package not installed, using in-memory fallback")
            return False
        except Exception as e:
            logger.warning(f"Redis connection failed, using in-memory fallback: {e}")
            self._metrics["redis_errors"] += 1
            return False

    def _get_tier_limits(self, tier: SubscriptionTier) -> TierLimits:
        """Get limits for a tier, checking instance overrides first."""
        # Use instance-level tier_limits if provided, otherwise global with env overrides
        if self._tier_limits is not TIER_LIMITS and tier in self._tier_limits:
            return self._tier_limits[tier]
        return get_tier_limits(tier)

    async def check_tenant_limit(
        self,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
        service_principal_id: Optional[str] = None,
        tier: SubscriptionTier = SubscriptionTier.FREE,
        tool_name: Optional[str] = None,
    ) -> DistributedRateLimitResult:
        """Check and consume rate limit for a tenant.

        Args:
            org_id: Organization ID for tenant-level limiting
            user_id: User ID for per-user limiting
            service_principal_id: SP ID for service-to-service calls
            tier: Subscription tier for limit configuration
            tool_name: Optional tool name for tool-specific limits

        Returns:
            DistributedRateLimitResult with allowed status and metadata
        """
        self._metrics["checks_total"] += 1
        limits = self._get_tier_limits(tier)
        now = int(time.time())

        # Determine identifier
        if org_id:
            identifier = f"org:{org_id}"
        elif user_id:
            identifier = f"user:{user_id}"
        elif service_principal_id:
            identifier = f"sp:{service_principal_id}"
        else:
            identifier = "anon:default"
            limits = TierLimits(requests_per_minute=10, burst_size=3, daily_quota=50)

        # Try Redis first
        redis_available = await self._ensure_redis()

        # Check daily quota first (if applicable)
        if limits.daily_quota is not None:
            daily_result = await self._check_daily_quota(
                identifier, limits, now, tier.value, redis_available
            )
            if not daily_result.allowed:
                self._metrics["denies_total"] += 1
                return daily_result

        # Check per-minute limit
        minute_result = await self._check_minute_limit(
            identifier, limits, now, tier.value, redis_available
        )
        if not minute_result.allowed:
            self._metrics["denies_total"] += 1
            return minute_result

        # Check per-user limit within org (fair sharing)
        if org_id and user_id and limits.user_requests_per_minute:
            user_limits = TierLimits(
                requests_per_minute=limits.user_requests_per_minute,
                burst_size=limits.burst_size // 4,
                daily_quota=None,
            )
            user_result = await self._check_minute_limit(
                f"user:{user_id}:in:{org_id}",
                user_limits,
                now,
                tier.value,
                redis_available,
            )
            if not user_result.allowed:
                user_result.limit_type = "user_minute"
                self._metrics["denies_total"] += 1
                return user_result

        return minute_result

    async def _check_minute_limit(
        self,
        identifier: str,
        limits: TierLimits,
        now: int,
        tier: str,
        use_redis: bool,
    ) -> DistributedRateLimitResult:
        """Check per-minute sliding window limit."""
        if use_redis and self._redis_client:
            self._metrics["redis_checks"] += 1
            return await self._check_minute_redis(identifier, limits, now, tier)
        else:
            self._metrics["memory_checks"] += 1
            return self._check_minute_memory(identifier, limits, now, tier)

    async def _check_minute_redis(
        self,
        identifier: str,
        limits: TierLimits,
        now: int,
        tier: str,
    ) -> DistributedRateLimitResult:
        """Check minute limit using Redis sliding window."""
        key = self._redis_key(identifier, "minute")
        window_start = now - 60

        lua_script = """
        local key = KEYS[1]
        local now = tonumber(ARGV[1])
        local window_start = tonumber(ARGV[2])
        local max_requests = tonumber(ARGV[3])

        redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)
        local count = redis.call('ZCARD', key)

        if count < max_requests then
            local member = now .. ':' .. redis.call('INCR', key .. ':seq')
            redis.call('ZADD', key, now, member)
            redis.call('EXPIRE', key, 120)
            redis.call('EXPIRE', key .. ':seq', 120)
            return {1, max_requests - count - 1, 0}
        else
            local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
            local retry_after = 60
            if oldest and oldest[2] then
                retry_after = math.ceil(tonumber(oldest[2]) + 60 - now)
                if retry_after < 1 then retry_after = 1 end
            end
            return {0, 0, retry_after}
        end
        """

        try:
            result = await self._redis_client.eval(
                lua_script, 1, key,
                now, window_start, limits.requests_per_minute
            )

            return DistributedRateLimitResult(
                allowed=bool(result[0]),
                remaining=int(result[1]),
                reset_at=now + 60,
                retry_after=int(result[2]) if not result[0] else None,
                limit_type="minute",
                tier=tier,
            )

        except Exception as e:
            logger.error(f"Redis rate limit error: {e}")
            self._metrics["redis_errors"] += 1
            # Fail open
            return DistributedRateLimitResult(
                allowed=True,
                remaining=limits.requests_per_minute,
                reset_at=now + 60,
                tier=tier,
            )

    def _check_minute_memory(
        self,
        identifier: str,
        limits: TierLimits,
        now: int,
        tier: str,
    ) -> DistributedRateLimitResult:
        """Check minute limit using in-memory sliding window."""
        key = f"minute:{identifier}"
        window_start = now - 60

        with self._memory_lock:
            if key not in self._memory_counters:
                self._memory_counters[key] = {"requests": [], "last_cleanup": now}

            counter = self._memory_counters[key]
            counter["requests"] = [ts for ts in counter["requests"] if ts > window_start]
            count = len(counter["requests"])

            if count < limits.requests_per_minute:
                counter["requests"].append(now)
                return DistributedRateLimitResult(
                    allowed=True,
                    remaining=limits.requests_per_minute - count - 1,
                    reset_at=now + 60,
                    tier=tier,
                )
            else:
                oldest = min(counter["requests"]) if counter["requests"] else now
                retry_after = max(1, oldest + 60 - now)

                return DistributedRateLimitResult(
                    allowed=False,
                    remaining=0,
                    reset_at=now + retry_after,
                    retry_after=retry_after,
                    limit_type="minute",
                    tier=tier,
                )

    async def _check_daily_quota(
        self,
        identifier: str,
        limits: TierLimits,
        now: int,
        tier: str,
        use_redis: bool,
    ) -> DistributedRateLimitResult:
        """Check daily quota limit."""
        if limits.daily_quota is None:
            return DistributedRateLimitResult(
                allowed=True,
                remaining=999999,
                reset_at=self._get_day_end(now),
                tier=tier,
            )

        if use_redis and self._redis_client:
            return await self._check_daily_redis(identifier, limits, now, tier)
        else:
            return self._check_daily_memory(identifier, limits, now, tier)

    async def _check_daily_redis(
        self,
        identifier: str,
        limits: TierLimits,
        now: int,
        tier: str,
    ) -> DistributedRateLimitResult:
        """Check daily quota using Redis."""
        day_key = now // 86400
        key = self._redis_key(identifier, "daily", str(day_key))

        try:
            pipe = self._redis_client.pipeline()
            pipe.incr(key)
            pipe.expire(key, 90000)  # 25 hours
            results = await pipe.execute()

            count = results[0]
            remaining = max(0, limits.daily_quota - count)
            day_end = self._get_day_end(now)

            if count > limits.daily_quota:
                return DistributedRateLimitResult(
                    allowed=False,
                    remaining=0,
                    reset_at=day_end,
                    retry_after=day_end - now,
                    limit_type="daily",
                    tier=tier,
                )

            return DistributedRateLimitResult(
                allowed=True,
                remaining=remaining,
                reset_at=day_end,
                tier=tier,
            )

        except Exception as e:
            logger.error(f"Redis daily quota error: {e}")
            self._metrics["redis_errors"] += 1
            return DistributedRateLimitResult(
                allowed=True,
                remaining=limits.daily_quota,
                reset_at=self._get_day_end(now),
                tier=tier,
            )

    def _check_daily_memory(
        self,
        identifier: str,
        limits: TierLimits,
        now: int,
        tier: str,
    ) -> DistributedRateLimitResult:
        """Check daily quota using in-memory counter."""
        day_key = now // 86400
        key = f"daily:{identifier}:{day_key}"

        with self._memory_lock:
            if key not in self._memory_counters:
                self._memory_counters[key] = {"count": 0, "day": day_key}

            counter = self._memory_counters[key]
            if counter["day"] != day_key:
                counter["count"] = 0
                counter["day"] = day_key

            counter["count"] += 1
            remaining = max(0, limits.daily_quota - counter["count"])
            day_end = self._get_day_end(now)

            if counter["count"] > limits.daily_quota:
                return DistributedRateLimitResult(
                    allowed=False,
                    remaining=0,
                    reset_at=day_end,
                    retry_after=day_end - now,
                    limit_type="daily",
                    tier=tier,
                )

            return DistributedRateLimitResult(
                allowed=True,
                remaining=remaining,
                reset_at=day_end,
                tier=tier,
            )

    def _get_day_end(self, now: int) -> int:
        """Get timestamp for end of current day (UTC)."""
        return ((now // 86400) + 1) * 86400

    async def get_usage(
        self,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get current usage statistics."""
        now = int(time.time())

        if org_id:
            identifier = f"org:{org_id}"
        elif user_id:
            identifier = f"user:{user_id}"
        else:
            return {"error": "org_id or user_id required"}

        redis_available = await self._ensure_redis()

        if redis_available and self._redis_client:
            return await self._get_usage_redis(identifier, now)
        else:
            return self._get_usage_memory(identifier, now)

    async def _get_usage_redis(self, identifier: str, now: int) -> Dict[str, Any]:
        """Get usage from Redis."""
        minute_key = self._redis_key(identifier, "minute")
        day_key = now // 86400
        daily_key = self._redis_key(identifier, "daily", str(day_key))

        try:
            pipe = self._redis_client.pipeline()
            pipe.zcard(minute_key)
            pipe.get(daily_key)
            results = await pipe.execute()

            return {
                "identifier": identifier,
                "requests_last_minute": results[0] or 0,
                "requests_today": int(results[1]) if results[1] else 0,
                "timestamp": now,
                "backend": "redis",
            }
        except Exception as e:
            return {"error": str(e)}

    def _get_usage_memory(self, identifier: str, now: int) -> Dict[str, Any]:
        """Get usage from memory."""
        minute_key = f"minute:{identifier}"
        day_key = now // 86400
        daily_key = f"daily:{identifier}:{day_key}"

        minute_count = 0
        daily_count = 0

        with self._memory_lock:
            if minute_key in self._memory_counters:
                window_start = now - 60
                minute_count = len([
                    ts for ts in self._memory_counters[minute_key].get("requests", [])
                    if ts > window_start
                ])

            if daily_key in self._memory_counters:
                daily_count = self._memory_counters[daily_key].get("count", 0)

        return {
            "identifier": identifier,
            "requests_last_minute": minute_count,
            "requests_today": daily_count,
            "timestamp": now,
            "backend": "memory",
        }

    async def reset_limits(
        self,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Reset rate limits for an org or user (admin operation)."""
        if org_id:
            identifier = f"org:{org_id}"
        elif user_id:
            identifier = f"user:{user_id}"
        else:
            return {"error": "org_id or user_id required"}

        redis_available = await self._ensure_redis()

        if redis_available and self._redis_client:
            return await self._reset_redis(identifier)
        else:
            return self._reset_memory(identifier)

    async def _reset_redis(self, identifier: str) -> Dict[str, Any]:
        """Reset limits in Redis."""
        pattern = self._redis_key(identifier, "*")

        try:
            keys = []
            async for key in self._redis_client.scan_iter(pattern, count=100):
                keys.append(key)

            if keys:
                await self._redis_client.delete(*keys)

            return {"reset": True, "keys_deleted": len(keys), "backend": "redis"}
        except Exception as e:
            return {"error": str(e)}

    def _reset_memory(self, identifier: str) -> Dict[str, Any]:
        """Reset limits in memory."""
        deleted = 0

        with self._memory_lock:
            keys_to_delete = [k for k in self._memory_counters if identifier in k]
            for k in keys_to_delete:
                del self._memory_counters[k]
                deleted += 1

        return {"reset": True, "keys_deleted": deleted, "backend": "memory"}

    def get_metrics(self) -> Dict[str, Any]:
        """Get rate limiter metrics."""
        return {
            **self._metrics,
            "redis_available": self._use_redis,
            "tier_limits": {
                tier.value: limits.to_dict()
                for tier, limits in self._tier_limits.items()
            },
        }

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis_client:
            await self._redis_client.close()
            self._redis_client = None
            self._use_redis = False


# Singleton instance for distributed rate limiter
_distributed_limiter: Optional[DistributedRateLimiter] = None


def get_distributed_rate_limiter() -> DistributedRateLimiter:
    """Get or create global distributed rate limiter instance."""
    global _distributed_limiter
    if _distributed_limiter is None:
        _distributed_limiter = DistributedRateLimiter()
    return _distributed_limiter
