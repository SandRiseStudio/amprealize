"""Tests for MCP Rate Limiter.

These are pure unit tests that don't require infrastructure.
"""

import time
import pytest

pytestmark = pytest.mark.unit

from amprealize.mcp_rate_limiter import (
    MCPRateLimiter,
    RateLimitConfig,
    RateLimitDecision,
    RateLimitResult,
    TokenBucket,
)


class TestTokenBucket:
    """Tests for TokenBucket class."""

    def test_initial_state(self):
        """Test bucket is full initially."""
        bucket = TokenBucket(
            tokens=10,
            last_update=time.time(),
            capacity=10,
            refill_rate=1.0,
        )
        assert bucket.tokens == 10
        assert bucket.capacity == 10

    def test_consume_single_token(self):
        """Test consuming a single token."""
        bucket = TokenBucket(
            tokens=10,
            last_update=time.time(),
            capacity=10,
            refill_rate=1.0,
        )
        success, remaining = bucket.consume(1)
        assert success is True
        assert remaining == 9

    def test_consume_multiple_tokens(self):
        """Test consuming multiple tokens."""
        bucket = TokenBucket(
            tokens=10,
            last_update=time.time(),
            capacity=10,
            refill_rate=1.0,
        )
        success, remaining = bucket.consume(5)
        assert success is True
        assert remaining == 5

    def test_consume_more_than_available(self):
        """Test consuming more tokens than available."""
        bucket = TokenBucket(
            tokens=3,
            last_update=time.time(),
            capacity=10,
            refill_rate=1.0,
        )
        success, remaining = bucket.consume(5)
        assert success is False
        assert remaining >= 3  # May have slight refill

    def test_refill_over_time(self):
        """Test that tokens refill over time."""
        past = time.time() - 5  # 5 seconds ago
        bucket = TokenBucket(
            tokens=5,
            last_update=past,
            capacity=10,
            refill_rate=1.0,  # 1 token per second
        )
        # After 5 seconds, should have 5 + 5 = 10 tokens (capped at capacity)
        success, remaining = bucket.consume(1)
        assert success is True
        assert remaining == 9  # 10 - 1


class TestRateLimitConfig:
    """Tests for RateLimitConfig."""

    def test_valid_config(self):
        """Test valid config creation."""
        config = RateLimitConfig(
            name="test",
            max_requests=100,
            window_seconds=60,
            burst_limit=20,
            refill_rate=1.67,
        )
        assert config.name == "test"
        assert config.max_requests == 100

    def test_invalid_max_requests(self):
        """Test that zero/negative max_requests raises error."""
        with pytest.raises(ValueError):
            RateLimitConfig(
                name="test",
                max_requests=0,
                window_seconds=60,
                burst_limit=20,
                refill_rate=1.67,
            )

    def test_invalid_window(self):
        """Test that zero/negative window raises error."""
        with pytest.raises(ValueError):
            RateLimitConfig(
                name="test",
                max_requests=100,
                window_seconds=0,
                burst_limit=20,
                refill_rate=1.67,
            )


class TestMCPRateLimiter:
    """Tests for MCPRateLimiter."""

    def test_disabled_allows_all(self):
        """Test that disabled rate limiter allows all requests."""
        limiter = MCPRateLimiter(enabled=False)
        result = limiter.check("client1", "behaviors.get")
        assert result.decision == RateLimitDecision.ALLOW
        assert result.remaining_tokens == float("inf")

    def test_basic_allow(self):
        """Test that requests within limits are allowed."""
        limiter = MCPRateLimiter(enabled=True)
        result = limiter.check("client1", "behaviors.get")
        assert result.decision == RateLimitDecision.ALLOW
        assert result.remaining_tokens > 0

    def test_auth_tool_rate_limiting(self):
        """Test that auth tools have stricter limits."""
        limiter = MCPRateLimiter(
            enabled=True,
            global_config=RateLimitConfig(
                name="global",
                max_requests=100,
                window_seconds=60,
                burst_limit=100,
                refill_rate=1.67,
                soft_limit_pct=0.0,  # Disable soft limit warning
            ),
            auth_config=RateLimitConfig(
                name="auth",
                max_requests=2,
                window_seconds=60,
                burst_limit=2,
                refill_rate=0.033,
                soft_limit_pct=0.0,  # Disable soft limit warning
            ),
        )

        # Use auth.logout which is in AUTH_TOOLS but not HIGH_RISK_TOOLS
        # First two should pass
        result1 = limiter.check("client1", "auth.logout")
        result2 = limiter.check("client1", "auth.logout")
        assert result1.decision == RateLimitDecision.ALLOW
        assert result2.decision == RateLimitDecision.ALLOW

        # Third should be denied
        result3 = limiter.check("client1", "auth.logout")
        assert result3.decision == RateLimitDecision.DENY
        assert result3.retry_after_seconds is not None and result3.retry_after_seconds > 0

    def test_different_clients_independent(self):
        """Test that different clients have independent limits."""
        limiter = MCPRateLimiter(
            enabled=True,
            global_config=RateLimitConfig(
                name="global",
                max_requests=100,
                window_seconds=60,
                burst_limit=100,
                refill_rate=1.67,
                soft_limit_pct=0.0,  # Disable soft limit warning
            ),
            auth_config=RateLimitConfig(
                name="auth",
                max_requests=1,
                window_seconds=60,
                burst_limit=1,
                refill_rate=0.017,
                soft_limit_pct=0.0,  # Disable soft limit warning
            ),
        )

        # Use auth.logout which is in AUTH_TOOLS but not HIGH_RISK_TOOLS
        # Client 1 uses their limit
        result1 = limiter.check("client1", "auth.logout")
        assert result1.decision == RateLimitDecision.ALLOW

        # Client 1 is now rate limited
        result2 = limiter.check("client1", "auth.logout")
        assert result2.decision == RateLimitDecision.DENY

        # Client 2 still has their own limit
        result3 = limiter.check("client2", "auth.logout")
        assert result3.decision == RateLimitDecision.ALLOW

    def test_tool_categories(self):
        """Test that tools are correctly categorized."""
        limiter = MCPRateLimiter(enabled=True)

        # Auth tools
        assert "auth.deviceLogin" in limiter.AUTH_TOOLS
        assert "auth.logout" in limiter.AUTH_TOOLS

        # Write tools
        assert "behaviors.createDraft" in limiter.WRITE_TOOLS
        assert "runs.create" in limiter.WRITE_TOOLS

        # High risk tools
        assert "auth.deviceLogin" in limiter.HIGH_RISK_TOOLS
        assert "config.update" in limiter.HIGH_RISK_TOOLS

    def test_global_limit_enforced(self):
        """Test that global limit is enforced across all tools."""
        limiter = MCPRateLimiter(
            enabled=True,
            global_config=RateLimitConfig(
                name="global",
                max_requests=3,
                window_seconds=60,
                burst_limit=3,
                refill_rate=0.05,
            ),
        )

        # Mix of tools should hit global limit
        limiter.check("client1", "behaviors.get")
        limiter.check("client1", "runs.list")
        limiter.check("client1", "workflows.list")

        # Fourth request should be denied by global limit
        result = limiter.check("client1", "behaviors.search")
        assert result.decision == RateLimitDecision.DENY
        assert result.rule_name == "global"

    def test_get_client_status(self):
        """Test getting client status."""
        limiter = MCPRateLimiter(enabled=True)

        # Make some requests
        limiter.check("client1", "behaviors.get")
        limiter.check("client1", "behaviors.get")

        status = limiter.get_client_status("client1")
        assert status is not None
        assert status["client_id"] == "client1"
        assert "global" in status
        assert "tools" in status
        assert status["stats"]["request_count"] == 2

    def test_get_client_status_unknown(self):
        """Test getting status for unknown client."""
        limiter = MCPRateLimiter(enabled=True)
        status = limiter.get_client_status("unknown_client")
        assert status is None

    def test_get_metrics(self):
        """Test getting limiter metrics."""
        limiter = MCPRateLimiter(enabled=True)

        limiter.check("client1", "behaviors.get")
        limiter.check("client2", "behaviors.get")

        metrics = limiter.get_metrics()
        assert metrics["checks_total"] == 2
        assert metrics["allows_total"] == 2
        assert metrics["active_clients"] == 2
        assert metrics["enabled"] is True
        assert "config" in metrics

    def test_reset_client(self):
        """Test resetting client state."""
        limiter = MCPRateLimiter(enabled=True)

        limiter.check("client1", "behaviors.get")
        assert limiter.get_client_status("client1") is not None

        result = limiter.reset_client("client1")
        assert result is True
        assert limiter.get_client_status("client1") is None

    def test_reset_unknown_client(self):
        """Test resetting unknown client."""
        limiter = MCPRateLimiter(enabled=True)
        result = limiter.reset_client("unknown")
        assert result is False

    def test_set_enabled(self):
        """Test enabling/disabling rate limiting."""
        limiter = MCPRateLimiter(enabled=True)
        assert limiter._enabled is True

        limiter.set_enabled(False)
        assert limiter._enabled is False

        result = limiter.check("client1", "behaviors.get")
        assert result.decision == RateLimitDecision.ALLOW

    def test_cleanup_stale_clients(self):
        """Test cleaning up stale clients."""
        limiter = MCPRateLimiter(enabled=True)

        # Add client
        limiter.check("client1", "behaviors.get")

        # Artificially age the client
        limiter._clients["client1"].last_request_time = time.time() - 7200  # 2 hours ago

        # Cleanup with 1 hour max age
        removed = limiter.cleanup_stale_clients(max_age_seconds=3600)
        assert removed == 1
        assert limiter.get_client_status("client1") is None

    def test_soft_limit_warning(self):
        """Test soft limit warning when approaching limit."""
        limiter = MCPRateLimiter(
            enabled=True,
            global_config=RateLimitConfig(
                name="global",
                max_requests=10,
                window_seconds=60,
                burst_limit=10,
                refill_rate=0.17,
                soft_limit_pct=0.8,  # Warn at 80%
            ),
        )

        # Use 8 tokens (80% of limit)
        for _ in range(8):
            limiter.check("client1", "behaviors.get")

        # Next request should trigger warning
        result = limiter.check("client1", "behaviors.get")
        assert result.decision == RateLimitDecision.WARN
        assert "Approaching rate limit" in result.message

    def test_result_to_dict(self):
        """Test RateLimitResult serialization."""
        result = RateLimitResult(
            decision=RateLimitDecision.DENY,
            client_id="client1",
            tool_name="auth.deviceLogin",
            remaining_tokens=0.5,
            retry_after_seconds=30.0,
            message="Rate limit exceeded",
            rule_name="auth",
        )

        d = result.to_dict()
        assert d["decision"] == "deny"
        assert d["client_id"] == "client1"
        assert d["remaining_tokens"] == 0.5
        assert d["retry_after_seconds"] == 30.0


class TestMCPRateLimiterIntegration:
    """Integration tests for MCP rate limiter."""

    def test_realistic_usage_pattern(self):
        """Test a realistic usage pattern."""
        limiter = MCPRateLimiter(enabled=True)

        client_id = "claude_desktop:1.0.0:12345"

        # Typical session: authenticate, list behaviors, get details
        results = []
        results.append(limiter.check(client_id, "auth.authStatus"))
        results.append(limiter.check(client_id, "behaviors.list"))
        results.append(limiter.check(client_id, "behaviors.get"))
        results.append(limiter.check(client_id, "behaviors.get"))
        results.append(limiter.check(client_id, "bci.retrieve"))

        # All should be allowed
        for r in results:
            assert r.decision in (RateLimitDecision.ALLOW, RateLimitDecision.WARN)

        # Check metrics
        metrics = limiter.get_metrics()
        assert metrics["checks_total"] == 5
        assert metrics["allows_total"] >= 4  # Some may be warnings

    def test_burst_protection(self):
        """Test that burst limits protect against rapid requests."""
        limiter = MCPRateLimiter(
            enabled=True,
            write_config=RateLimitConfig(
                name="write",
                max_requests=30,
                window_seconds=60,
                burst_limit=5,  # Only 5 burst
                refill_rate=0.5,
                soft_limit_pct=0.0,  # Disable soft warnings
            ),
        )

        # Rapid burst of write operations
        results = []
        for i in range(10):
            results.append(limiter.check("client1", "behaviors.createDraft"))

        # First 5 should pass (burst limit), rest denied
        allows = sum(1 for r in results if r.decision == RateLimitDecision.ALLOW)
        denies = sum(1 for r in results if r.decision == RateLimitDecision.DENY)
        warnings = sum(1 for r in results if r.decision == RateLimitDecision.WARN)

        # Should have some allows and some denies (burst protects)
        assert allows + warnings <= 6  # Burst limit with possible 1 warning
        assert denies >= 4  # Most should be denied after burst
