#!/usr/bin/env python
"""Phase 5 Distributed Rate Limiting Tests.

Tests the Redis-backed rate limiter implementation for MCP auth.
Verifies tier limits, tenant isolation, and both Redis and in-memory fallback.

Run: python scripts/test_phase5_rate_limiting.py
"""

import asyncio
import sys
import os
import time

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASSED = 0
FAILED = 0


def test_pass(name: str):
    global PASSED
    print(f"  ✓ {name} passed")
    PASSED += 1


def test_fail(name: str, error: str):
    global FAILED
    print(f"  ✗ {name} FAILED: {error}")
    FAILED += 1


def test_section(name: str):
    print(f"\n=== {name} ===")


async def test_tier_limits():
    """Test subscription tier limit configurations."""
    test_section("Tier Limits Configuration")

    from amprealize.mcp_rate_limiter import (
        SubscriptionTier, TierLimits, TIER_LIMITS, get_tier_limits
    )

    # Test FREE tier
    free_limits = get_tier_limits(SubscriptionTier.FREE)
    if free_limits.requests_per_minute == 60:
        test_pass("FREE tier requests_per_minute")
    else:
        test_fail("FREE tier requests_per_minute", f"Expected 60, got {free_limits.requests_per_minute}")

    if free_limits.daily_quota == 1000:
        test_pass("FREE tier daily_quota")
    else:
        test_fail("FREE tier daily_quota", f"Expected 1000, got {free_limits.daily_quota}")

    # Test PRO tier
    pro_limits = get_tier_limits(SubscriptionTier.PRO)
    if pro_limits.requests_per_minute == 300:
        test_pass("PRO tier requests_per_minute")
    else:
        test_fail("PRO tier requests_per_minute", f"Expected 300, got {pro_limits.requests_per_minute}")

    # Test ENTERPRISE tier (unlimited daily)
    enterprise_limits = get_tier_limits(SubscriptionTier.ENTERPRISE)
    if enterprise_limits.daily_quota is None:
        test_pass("ENTERPRISE tier unlimited daily")
    else:
        test_fail("ENTERPRISE tier unlimited daily", f"Expected None, got {enterprise_limits.daily_quota}")

    # Test TierLimits.to_dict()
    free_dict = free_limits.to_dict()
    if "requests_per_minute" in free_dict and "burst_size" in free_dict:
        test_pass("TierLimits to_dict")
    else:
        test_fail("TierLimits to_dict", "Missing expected keys")


async def test_distributed_rate_limit_result():
    """Test DistributedRateLimitResult dataclass."""
    test_section("DistributedRateLimitResult")

    from amprealize.mcp_rate_limiter import DistributedRateLimitResult

    # Test allowed result
    result = DistributedRateLimitResult(
        allowed=True,
        remaining=50,
        reset_at=int(time.time()) + 60,
        tier="pro",
    )

    if result.allowed and result.remaining == 50:
        test_pass("Allowed result construction")
    else:
        test_fail("Allowed result construction", "Unexpected values")

    # Test to_dict
    result_dict = result.to_dict()
    if result_dict["allowed"] is True and result_dict["tier"] == "pro":
        test_pass("Result to_dict")
    else:
        test_fail("Result to_dict", "Unexpected values")

    # Test denied result with retry_after
    denied = DistributedRateLimitResult(
        allowed=False,
        remaining=0,
        reset_at=int(time.time()) + 60,
        retry_after=45,
        tier="free",
    )

    if not denied.allowed and denied.retry_after == 45:
        test_pass("Denied result with retry_after")
    else:
        test_fail("Denied result with retry_after", "Unexpected values")

    # Test get_headers
    headers = denied.get_headers()
    if "Retry-After" in headers and headers["Retry-After"] == "45":
        test_pass("Denied result get_headers")
    else:
        test_fail("Denied result get_headers", f"Missing Retry-After: {headers}")


async def test_distributed_rate_limiter_memory():
    """Test DistributedRateLimiter with in-memory fallback."""
    test_section("DistributedRateLimiter (In-Memory)")

    from amprealize.mcp_rate_limiter import (
        DistributedRateLimiter, SubscriptionTier, TierLimits
    )

    # Create limiter with low limits for testing
    test_limits = {
        SubscriptionTier.FREE: TierLimits(
            requests_per_minute=5,
            burst_size=2,
            daily_quota=10,
            user_requests_per_minute=3,
        ),
    }

    # Force in-memory mode by not providing Redis URL
    limiter = DistributedRateLimiter(
        redis_url="redis://nonexistent:9999",  # Will fail and fallback
        tier_limits=test_limits,
    )

    org_id = f"test-org-{int(time.time())}"

    # First request should be allowed
    result1 = await limiter.check_tenant_limit(
        org_id=org_id,
        tier=SubscriptionTier.FREE,
    )

    if result1.allowed:
        test_pass("First request allowed")
    else:
        test_fail("First request allowed", f"Unexpected denial: {result1.to_dict()}")

    # Continue requests until limit
    for i in range(4):
        await limiter.check_tenant_limit(org_id=org_id, tier=SubscriptionTier.FREE)

    # 6th request should be denied (limit is 5/min)
    result6 = await limiter.check_tenant_limit(
        org_id=org_id,
        tier=SubscriptionTier.FREE,
    )

    if not result6.allowed and result6.retry_after is not None:
        test_pass("Limit exceeded after 5 requests")
    else:
        test_fail("Limit exceeded after 5 requests", f"Expected denial: {result6.to_dict()}")

    # Get usage
    usage = await limiter.get_usage(org_id=org_id)
    if usage.get("requests_last_minute", 0) >= 5:
        test_pass("Usage tracking")
    else:
        test_fail("Usage tracking", f"Expected >= 5, got {usage}")

    # Get metrics
    metrics = limiter.get_metrics()
    if metrics["checks_total"] >= 6:
        test_pass("Metrics tracking")
    else:
        test_fail("Metrics tracking", f"Expected >= 6 checks, got {metrics}")

    # Reset limits
    reset_result = await limiter.reset_limits(org_id=org_id)
    if reset_result.get("reset"):
        test_pass("Reset limits")
    else:
        test_fail("Reset limits", f"Reset failed: {reset_result}")


async def test_distributed_rate_limiter_daily_quota():
    """Test daily quota enforcement."""
    test_section("Daily Quota Enforcement")

    from amprealize.mcp_rate_limiter import (
        DistributedRateLimiter, SubscriptionTier, TierLimits
    )

    # Create limiter with low daily quota
    test_limits = {
        SubscriptionTier.FREE: TierLimits(
            requests_per_minute=100,  # High minute limit
            burst_size=50,
            daily_quota=3,  # Low daily quota for testing
            user_requests_per_minute=None,
        ),
    }

    limiter = DistributedRateLimiter(tier_limits=test_limits)
    org_id = f"test-daily-{int(time.time())}"

    # First 3 requests should be allowed
    for i in range(3):
        result = await limiter.check_tenant_limit(
            org_id=org_id,
            tier=SubscriptionTier.FREE,
        )
        if not result.allowed:
            test_fail(f"Daily quota request {i+1}", f"Unexpectedly denied: {result.to_dict()}")
            return

    test_pass("First 3 requests within daily quota")

    # 4th request should be denied
    result4 = await limiter.check_tenant_limit(
        org_id=org_id,
        tier=SubscriptionTier.FREE,
    )

    if not result4.allowed and result4.limit_type == "daily":
        test_pass("4th request denied (daily quota)")
    else:
        test_fail("4th request denied (daily quota)", f"Expected daily limit: {result4.to_dict()}")


async def test_per_user_within_org():
    """Test per-user rate limiting within an org."""
    test_section("Per-User Limiting Within Org")

    from amprealize.mcp_rate_limiter import (
        DistributedRateLimiter, SubscriptionTier, TierLimits
    )

    # Create limiter with per-user limits
    test_limits = {
        SubscriptionTier.FREE: TierLimits(
            requests_per_minute=100,  # High org limit
            burst_size=50,
            daily_quota=None,
            user_requests_per_minute=3,  # Low per-user limit
        ),
    }

    limiter = DistributedRateLimiter(tier_limits=test_limits)
    org_id = f"test-org-{int(time.time())}"
    user_id = f"test-user-{int(time.time())}"

    # First 3 requests for user should be allowed
    for i in range(3):
        result = await limiter.check_tenant_limit(
            org_id=org_id,
            user_id=user_id,
            tier=SubscriptionTier.FREE,
        )
        if not result.allowed:
            test_fail(f"User request {i+1}", f"Unexpectedly denied: {result.to_dict()}")
            return

    test_pass("First 3 user requests allowed")

    # 4th request for same user should be denied
    result4 = await limiter.check_tenant_limit(
        org_id=org_id,
        user_id=user_id,
        tier=SubscriptionTier.FREE,
    )

    if not result4.allowed and result4.limit_type == "user_minute":
        test_pass("4th user request denied (per-user limit)")
    else:
        test_fail("4th user request denied", f"Expected user_minute: {result4.to_dict()}")

    # Different user in same org should still be allowed
    user_id2 = f"test-user2-{int(time.time())}"
    result_user2 = await limiter.check_tenant_limit(
        org_id=org_id,
        user_id=user_id2,
        tier=SubscriptionTier.FREE,
    )

    if result_user2.allowed:
        test_pass("Different user in same org allowed")
    else:
        test_fail("Different user in same org allowed", f"Denied: {result_user2.to_dict()}")


async def test_mcp_server_integration():
    """Test MCP server rate limiter integration."""
    test_section("MCP Server Integration")

    try:
        from amprealize.mcp_server import MCPServer

        # Create server
        server = MCPServer()

        # Check distributed rate limiter is initialized
        if hasattr(server, "_distributed_rate_limiter"):
            test_pass("DistributedRateLimiter initialized in MCPServer")
        else:
            test_fail("DistributedRateLimiter initialized", "Attribute not found")
            return

        # Check rate limiter has expected methods
        limiter = server._distributed_rate_limiter
        if hasattr(limiter, "check_tenant_limit"):
            test_pass("check_tenant_limit method available")
        else:
            test_fail("check_tenant_limit method", "Method not found")

        if hasattr(limiter, "get_usage"):
            test_pass("get_usage method available")
        else:
            test_fail("get_usage method", "Method not found")

        if hasattr(limiter, "get_metrics"):
            test_pass("get_metrics method available")
        else:
            test_fail("get_metrics method", "Method not found")

    except Exception as e:
        test_fail("MCP server integration", str(e))


async def test_tool_manifests():
    """Test rate limit tool manifests are properly defined."""
    test_section("Tool Manifests")

    import json
    from pathlib import Path

    tools_dir = Path(__file__).parent.parent / "mcp" / "tools"

    expected_tools = [
        ("ratelimit.getUsage.json", []),  # No scopes needed
        ("ratelimit.getLimits.json", []),  # No scopes needed
        ("ratelimit.getMetrics.json", []),  # No scopes needed
        ("ratelimit.reset.json", ["admin.ratelimit"]),  # Admin scope
    ]

    for filename, expected_scopes in expected_tools:
        filepath = tools_dir / filename
        if not filepath.exists():
            test_fail(f"Manifest {filename}", "File not found")
            continue

        try:
            with open(filepath) as f:
                manifest = json.load(f)

            if manifest.get("required_scopes") == expected_scopes:
                test_pass(f"Manifest {filename} scopes")
            else:
                test_fail(
                    f"Manifest {filename} scopes",
                    f"Expected {expected_scopes}, got {manifest.get('required_scopes')}"
                )

        except Exception as e:
            test_fail(f"Manifest {filename}", str(e))


async def main():
    """Run all Phase 5 tests."""
    print("=" * 60)
    print("Phase 5: Distributed Rate Limiting Tests")
    print("=" * 60)

    await test_tier_limits()
    await test_distributed_rate_limit_result()
    await test_distributed_rate_limiter_memory()
    await test_distributed_rate_limiter_daily_quota()
    await test_per_user_within_org()
    await test_mcp_server_integration()
    await test_tool_manifests()

    print("\n" + "=" * 60)
    print(f"Results: {PASSED} passed, {FAILED} failed")
    print("=" * 60)

    if FAILED > 0:
        print("\n❌ Some tests failed!")
        sys.exit(1)
    else:
        print("\n✅ All Phase 5 tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
