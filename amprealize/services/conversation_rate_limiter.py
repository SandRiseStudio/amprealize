"""Adaptive multi-lane token bucket rate limiter for the messaging system (AMPREALIZE-593).

Provides per-user, per-conversation rate limiting across multiple *lanes*:

- **message**:  Text sends (user & agent)
- **reaction**: Emoji adds
- **typing**:   Typing-indicator pings
- **search**:   Full-text search queries

Each lane has its own token bucket with independent capacity and refill rate.
The limiter is *adaptive*: when sustained traffic exceeds a configurable threshold
the bucket refill rate is halved (back-pressure) and restored once traffic drops.

Agent-to-agent amplification is handled by a companion :class:`CircuitBreaker`
which detects runaway ping-pong loops and temporarily blocks further agent posts.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class Lane(str, Enum):
    MESSAGE = "message"
    REACTION = "reaction"
    TYPING = "typing"
    SEARCH = "search"


@dataclass(frozen=True)
class LaneConfig:
    """Configuration for a single rate-limit lane."""

    capacity: int
    """Maximum burst size (tokens)."""

    refill_rate: float
    """Tokens added per second."""

    adaptive_threshold: float = 0.8
    """When usage exceeds this fraction of capacity, engage back-pressure."""

    min_refill_rate: float = 0.0
    """Refill rate floor during back-pressure (0 = derive from refill_rate / 4)."""


# Sensible defaults per lane
DEFAULT_LANE_CONFIGS: Dict[Lane, LaneConfig] = {
    Lane.MESSAGE: LaneConfig(capacity=30, refill_rate=2.0),       # 30 burst, ~2/s sustained
    Lane.REACTION: LaneConfig(capacity=20, refill_rate=4.0),      # quick emoji taps
    Lane.TYPING: LaneConfig(capacity=10, refill_rate=1.0),        # typing events
    Lane.SEARCH: LaneConfig(capacity=10, refill_rate=0.5),        # expensive FTS queries
}

# Agent-specific overrides (generally more generous for automated senders)
AGENT_LANE_CONFIGS: Dict[Lane, LaneConfig] = {
    Lane.MESSAGE: LaneConfig(capacity=60, refill_rate=5.0),
    Lane.REACTION: LaneConfig(capacity=10, refill_rate=2.0),
    Lane.TYPING: LaneConfig(capacity=5, refill_rate=0.5),
    Lane.SEARCH: LaneConfig(capacity=5, refill_rate=0.25),
}


# ---------------------------------------------------------------------------
# Token bucket
# ---------------------------------------------------------------------------


@dataclass
class _TokenBucket:
    capacity: int
    tokens: float
    refill_rate: float
    base_refill_rate: float
    min_refill_rate: float
    adaptive_threshold: float
    last_refill: float = field(default_factory=time.monotonic)
    back_pressure: bool = False

    # --- public API ---

    def try_consume(self, cost: int = 1) -> Tuple[bool, float]:
        """Attempt to consume *cost* tokens.

        Returns:
            ``(allowed, wait_seconds)`` — if not allowed, *wait_seconds* is the
            estimated time until enough tokens are available.
        """
        self._refill()
        self._adapt()

        if self.tokens >= cost:
            self.tokens -= cost
            return True, 0.0

        deficit = cost - self.tokens
        wait = deficit / self.refill_rate if self.refill_rate > 0 else 60.0
        return False, wait

    def peek_tokens(self) -> float:
        self._refill()
        return self.tokens

    # --- internals ---

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_refill
        if elapsed <= 0:
            return
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    def _adapt(self) -> None:
        usage_ratio = 1.0 - (self.tokens / self.capacity) if self.capacity else 1.0
        if usage_ratio >= self.adaptive_threshold and not self.back_pressure:
            self.back_pressure = True
            floor = self.min_refill_rate or (self.base_refill_rate / 4.0)
            self.refill_rate = max(floor, self.base_refill_rate * 0.5)
            logger.debug("back-pressure ON: refill_rate → %.2f", self.refill_rate)
        elif usage_ratio < self.adaptive_threshold * 0.5 and self.back_pressure:
            self.back_pressure = False
            self.refill_rate = self.base_refill_rate
            logger.debug("back-pressure OFF: refill_rate → %.2f", self.refill_rate)


# ---------------------------------------------------------------------------
# Per-key rate limiter
# ---------------------------------------------------------------------------


def _make_bucket(cfg: LaneConfig) -> _TokenBucket:
    return _TokenBucket(
        capacity=cfg.capacity,
        tokens=float(cfg.capacity),
        refill_rate=cfg.refill_rate,
        base_refill_rate=cfg.refill_rate,
        min_refill_rate=cfg.min_refill_rate,
        adaptive_threshold=cfg.adaptive_threshold,
    )


class RateLimitExceeded(Exception):
    """Raised when a request is rejected by the rate limiter."""

    def __init__(self, lane: Lane, wait_seconds: float) -> None:
        self.lane = lane
        self.wait_seconds = wait_seconds
        super().__init__(
            f"Rate limit exceeded for lane={lane.value}; retry after {wait_seconds:.1f}s"
        )


class ConversationRateLimiter:
    """Multi-lane, adaptive token-bucket rate limiter keyed on (actor, conversation).

    Usage::

        limiter = ConversationRateLimiter()

        # Before sending a message:
        limiter.check("user-123", "conv-abc", Lane.MESSAGE)
        # → raises RateLimitExceeded if over budget

        # Or non-throwing:
        allowed, wait = limiter.try_acquire("user-123", "conv-abc", Lane.MESSAGE)
    """

    def __init__(
        self,
        lane_configs: Optional[Dict[Lane, LaneConfig]] = None,
        agent_lane_configs: Optional[Dict[Lane, LaneConfig]] = None,
        max_keys: int = 50_000,
    ) -> None:
        self._user_configs = lane_configs or dict(DEFAULT_LANE_CONFIGS)
        self._agent_configs = agent_lane_configs or dict(AGENT_LANE_CONFIGS)
        self._buckets: Dict[str, _TokenBucket] = {}
        self._max_keys = max_keys

    # --- public API ---

    def try_acquire(
        self,
        actor_id: str,
        conversation_id: str,
        lane: Lane,
        *,
        is_agent: bool = False,
        cost: int = 1,
    ) -> Tuple[bool, float]:
        """Non-throwing token acquisition.

        Returns:
            ``(allowed, wait_seconds)``
        """
        bucket = self._get_or_create(actor_id, conversation_id, lane, is_agent)
        return bucket.try_consume(cost)

    def check(
        self,
        actor_id: str,
        conversation_id: str,
        lane: Lane,
        *,
        is_agent: bool = False,
        cost: int = 1,
    ) -> None:
        """Acquire a token or raise :class:`RateLimitExceeded`."""
        allowed, wait = self.try_acquire(
            actor_id, conversation_id, lane, is_agent=is_agent, cost=cost,
        )
        if not allowed:
            raise RateLimitExceeded(lane, wait)

    def peek(
        self,
        actor_id: str,
        conversation_id: str,
        lane: Lane,
        *,
        is_agent: bool = False,
    ) -> float:
        """Return remaining tokens without consuming."""
        bucket = self._get_or_create(actor_id, conversation_id, lane, is_agent)
        return bucket.peek_tokens()

    def reset(self, actor_id: str, conversation_id: str) -> None:
        """Reset all lane buckets for a given actor+conversation pair."""
        prefix = f"{actor_id}:{conversation_id}:"
        to_del = [k for k in self._buckets if k.startswith(prefix)]
        for k in to_del:
            del self._buckets[k]

    # --- internals ---

    def _get_or_create(
        self,
        actor_id: str,
        conversation_id: str,
        lane: Lane,
        is_agent: bool,
    ) -> _TokenBucket:
        key = f"{actor_id}:{conversation_id}:{lane.value}"
        bucket = self._buckets.get(key)
        if bucket is None:
            self._maybe_evict()
            configs = self._agent_configs if is_agent else self._user_configs
            cfg = configs.get(lane, DEFAULT_LANE_CONFIGS[lane])
            bucket = _make_bucket(cfg)
            self._buckets[key] = bucket
        return bucket

    def _maybe_evict(self) -> None:
        """Evict oldest buckets when nearing capacity."""
        if len(self._buckets) >= self._max_keys:
            # Sort by last_refill ascending, evict bottom 10%
            evict_count = max(1, self._max_keys // 10)
            by_age = sorted(self._buckets.items(), key=lambda kv: kv[1].last_refill)
            for k, _ in by_age[:evict_count]:
                del self._buckets[k]
