"""Tests for conversation_rate_limiter – multi-lane adaptive token bucket."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from amprealize.services.conversation_rate_limiter import (
    AGENT_LANE_CONFIGS,
    DEFAULT_LANE_CONFIGS,
    ConversationRateLimiter,
    Lane,
    LaneConfig,
    RateLimitExceeded,
    _TokenBucket,
    _make_bucket,
)

pytestmark = [pytest.mark.unit]


# ── _TokenBucket ──────────────────────────────────────────────────────────────


class TestTokenBucket:
    """Core bucket mechanics."""

    def test_fresh_bucket_at_capacity(self):
        bucket = _make_bucket(LaneConfig(capacity=10, refill_rate=1.0))
        assert bucket.peek_tokens() == 10

    def test_consume_one_token(self):
        bucket = _make_bucket(LaneConfig(capacity=5, refill_rate=1.0))
        allowed, wait = bucket.try_consume()
        assert allowed is True
        assert wait == 0.0
        assert bucket.peek_tokens() == pytest.approx(4, abs=0.1)

    def test_consume_until_empty(self):
        bucket = _make_bucket(LaneConfig(capacity=3, refill_rate=0.0))
        for _ in range(3):
            allowed, _ = bucket.try_consume()
            assert allowed is True
        allowed, wait = bucket.try_consume()
        assert allowed is False
        assert wait > 0  # should be 60.0 (infinite wait when refill_rate=0)

    def test_refill_over_time(self):
        bucket = _make_bucket(LaneConfig(capacity=2, refill_rate=10.0))  # 10 tokens/s

        # Drain
        bucket.try_consume()
        bucket.try_consume()
        allowed, _ = bucket.try_consume()
        assert allowed is False

        # Advance 0.5s → should refill up to capacity (2)
        bucket.last_refill = time.monotonic() - 0.5
        assert bucket.peek_tokens() == 2
        allowed, _ = bucket.try_consume()
        assert allowed is True

    def test_adaptive_backpressure_halves_refill(self):
        cfg = LaneConfig(
            capacity=10, refill_rate=4.0, adaptive_threshold=0.8, min_refill_rate=1.0,
        )
        bucket = _make_bucket(cfg)

        # Freeze time so micro-refills don't prevent threshold breach
        frozen = time.monotonic()
        with patch("amprealize.services.conversation_rate_limiter.time") as mock_time:
            mock_time.monotonic.return_value = frozen
            # Consume 9 tokens (90% usage > 80% threshold)
            for _ in range(9):
                bucket.try_consume()

        # After adapt triggered at 80%+ usage, refill_rate should be halved (2.0)
        assert bucket.refill_rate == 2.0
        assert bucket.back_pressure is True


class TestLaneConfig:
    def test_default_message_lane(self):
        cfg = DEFAULT_LANE_CONFIGS[Lane.MESSAGE]
        assert cfg.capacity == 30
        assert cfg.refill_rate == 2.0

    def test_agent_message_lane(self):
        cfg = AGENT_LANE_CONFIGS[Lane.MESSAGE]
        assert cfg.capacity == 60
        assert cfg.refill_rate == 5.0


# ── ConversationRateLimiter ───────────────────────────────────────────────────


class TestConversationRateLimiter:
    """Integration-level tests for the limiter."""

    def test_try_acquire_success(self):
        limiter = ConversationRateLimiter()
        allowed, wait = limiter.try_acquire("user-1", "conv-1", Lane.MESSAGE)
        assert allowed is True
        assert wait == 0.0

    def test_check_raises_when_exhausted(self):
        cfg = {lane: LaneConfig(capacity=2, refill_rate=0.0) for lane in Lane}
        limiter = ConversationRateLimiter(lane_configs=cfg)

        limiter.check("u1", "c1", Lane.MESSAGE)
        limiter.check("u1", "c1", Lane.MESSAGE)
        with pytest.raises(RateLimitExceeded) as exc_info:
            limiter.check("u1", "c1", Lane.MESSAGE)
        assert exc_info.value.lane == Lane.MESSAGE
        assert exc_info.value.wait_seconds > 0

    def test_different_users_independent(self):
        cfg = {lane: LaneConfig(capacity=1, refill_rate=0.0) for lane in Lane}
        limiter = ConversationRateLimiter(lane_configs=cfg)

        limiter.check("alice", "c1", Lane.SEARCH)
        limiter.check("bob", "c1", Lane.SEARCH)

        with pytest.raises(RateLimitExceeded):
            limiter.check("alice", "c1", Lane.SEARCH)
        with pytest.raises(RateLimitExceeded):
            limiter.check("bob", "c1", Lane.SEARCH)

    def test_different_lanes_independent(self):
        cfg = {lane: LaneConfig(capacity=1, refill_rate=0.0) for lane in Lane}
        limiter = ConversationRateLimiter(lane_configs=cfg)

        limiter.check("u1", "c1", Lane.MESSAGE)
        limiter.check("u1", "c1", Lane.REACTION)

        with pytest.raises(RateLimitExceeded):
            limiter.check("u1", "c1", Lane.MESSAGE)
        with pytest.raises(RateLimitExceeded):
            limiter.check("u1", "c1", Lane.REACTION)

    def test_different_conversations_independent(self):
        cfg = {lane: LaneConfig(capacity=1, refill_rate=0.0) for lane in Lane}
        limiter = ConversationRateLimiter(lane_configs=cfg)

        limiter.check("u1", "conv-A", Lane.MESSAGE)
        limiter.check("u1", "conv-B", Lane.MESSAGE)

        with pytest.raises(RateLimitExceeded):
            limiter.check("u1", "conv-A", Lane.MESSAGE)
        # conv-B is separate
        with pytest.raises(RateLimitExceeded):
            limiter.check("u1", "conv-B", Lane.MESSAGE)

    def test_peek_does_not_consume(self):
        cfg = {lane: LaneConfig(capacity=1, refill_rate=0.0) for lane in Lane}
        limiter = ConversationRateLimiter(lane_configs=cfg)

        assert limiter.peek("u1", "c1", Lane.MESSAGE) == 1.0
        assert limiter.peek("u1", "c1", Lane.MESSAGE) == 1.0  # still 1
        limiter.check("u1", "c1", Lane.MESSAGE)
        assert limiter.peek("u1", "c1", Lane.MESSAGE) == 0.0

    def test_reset_restores_capacity(self):
        cfg = {lane: LaneConfig(capacity=2, refill_rate=0.0) for lane in Lane}
        limiter = ConversationRateLimiter(lane_configs=cfg)

        limiter.check("u1", "c1", Lane.MESSAGE)
        limiter.check("u1", "c1", Lane.MESSAGE)
        with pytest.raises(RateLimitExceeded):
            limiter.check("u1", "c1", Lane.MESSAGE)

        limiter.reset("u1", "c1")
        limiter.check("u1", "c1", Lane.MESSAGE)  # should succeed

    def test_agent_config_applied(self):
        limiter = ConversationRateLimiter()
        # Agents get 60 capacity for MESSAGE
        for _ in range(60):
            allowed, _ = limiter.try_acquire("agent-x", "c1", Lane.MESSAGE, is_agent=True)
            assert allowed is True
        # 61st should fail
        allowed, wait = limiter.try_acquire("agent-x", "c1", Lane.MESSAGE, is_agent=True)
        assert allowed is False
        assert wait > 0

    def test_eviction_respects_max_keys(self):
        cfg = {lane: LaneConfig(capacity=5, refill_rate=1.0) for lane in Lane}
        limiter = ConversationRateLimiter(lane_configs=cfg, max_keys=10)

        # Fill up beyond max_keys
        for i in range(15):
            limiter.try_acquire(f"user-{i}", "c1", Lane.MESSAGE)

        # Limiter still works after eviction
        allowed, _ = limiter.try_acquire("user-0", "c1", Lane.MESSAGE)
        assert allowed is True


# ── RateLimitExceeded ─────────────────────────────────────────────────────────


class TestRateLimitExceeded:
    def test_str_representation(self):
        exc = RateLimitExceeded(lane=Lane.MESSAGE, wait_seconds=2.5)
        s = str(exc)
        assert "message" in s.lower()
        assert "2.5" in s

    def test_attributes(self):
        exc = RateLimitExceeded(lane=Lane.SEARCH, wait_seconds=1.0)
        assert exc.lane == Lane.SEARCH
        assert exc.wait_seconds == 1.0
