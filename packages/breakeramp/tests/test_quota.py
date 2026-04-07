"""Tests for QuotaService and multi-tenant isolation."""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from breakeramp.quota import (
    QuotaService,
    QuotaLimits,
    PLAN_LIMITS,
    get_isolation_scope,
    parse_scope,
    is_org_scope,
    is_user_scope,
    EnvironmentPlanResolver,
    get_quota_service,
    reset_quota_service,
)


class TestQuotaLimits:
    """Tests for QuotaLimits dataclass."""

    def test_default_values(self):
        """Test default quota limits."""
        limits = QuotaLimits()

        assert limits.max_concurrent_workspaces == 1
        assert limits.max_execution_seconds == 600
        assert limits.max_workspace_memory == "512m"
        assert limits.max_workspace_cpu == 1.0
        assert limits.priority_boost == 0

    def test_custom_values(self):
        """Test custom quota limits."""
        limits = QuotaLimits(
            max_concurrent_workspaces=10,
            max_execution_seconds=3600,
            max_workspace_memory="4g",
            max_workspace_cpu=4.0,
            priority_boost=5,
        )

        assert limits.max_concurrent_workspaces == 10
        assert limits.priority_boost == 5

    def test_to_dict(self):
        """Test serialization to dict."""
        limits = QuotaLimits(
            max_concurrent_workspaces=5,
            priority_boost=2,
        )

        data = limits.to_dict()

        assert data["max_concurrent_workspaces"] == 5
        assert data["priority_boost"] == 2

    def test_from_dict(self):
        """Test deserialization from dict."""
        data = {
            "max_concurrent_workspaces": 10,
            "max_execution_seconds": 7200,
            "priority_boost": 3,
        }

        limits = QuotaLimits.from_dict(data)

        assert limits.max_concurrent_workspaces == 10
        assert limits.max_execution_seconds == 7200
        assert limits.priority_boost == 3


class TestPlanLimits:
    """Tests for predefined plan limits."""

    def test_free_tier(self):
        """Test free tier limits."""
        limits = PLAN_LIMITS["free"]

        assert limits.max_concurrent_workspaces == 1
        assert limits.max_execution_seconds == 600  # 10 minutes
        assert limits.max_workspace_memory == "512m"
        assert limits.priority_boost == 0

    def test_pro_tier(self):
        """Test pro tier limits."""
        limits = PLAN_LIMITS["pro"]

        assert limits.max_concurrent_workspaces == 5
        assert limits.max_execution_seconds == 3600  # 1 hour
        assert limits.max_workspace_memory == "2g"
        assert limits.priority_boost == 2

    def test_enterprise_tier(self):
        """Test enterprise tier limits."""
        limits = PLAN_LIMITS["enterprise"]

        assert limits.max_concurrent_workspaces == 20
        assert limits.max_execution_seconds == 14400  # 4 hours
        assert limits.max_workspace_memory == "4g"
        assert limits.priority_boost == 5


class TestScopeUtils:
    """Tests for scope resolution utilities."""

    def test_get_isolation_scope_with_org(self):
        """Test scope with organization."""
        scope = get_isolation_scope("user-123", org_id="org-456")
        assert scope == "org:org-456"

    def test_get_isolation_scope_without_org(self):
        """Test scope without organization."""
        scope = get_isolation_scope("user-123", org_id=None)
        assert scope == "user:user-123"

    def test_get_isolation_scope_empty_org(self):
        """Test scope with empty org string is treated as no org."""
        # Empty string should still be truthy in Python, so it uses org
        scope = get_isolation_scope("user-123", org_id="")
        # Empty string is falsy, so it falls back to user
        assert scope == "user:user-123"

    def test_parse_scope_org(self):
        """Test parsing org scope."""
        scope_type, scope_id = parse_scope("org:tenant-abc")

        assert scope_type == "org"
        assert scope_id == "tenant-abc"

    def test_parse_scope_user(self):
        """Test parsing user scope."""
        scope_type, scope_id = parse_scope("user:user-123")

        assert scope_type == "user"
        assert scope_id == "user-123"

    def test_parse_scope_invalid_format(self):
        """Test parsing invalid scope format."""
        with pytest.raises(ValueError, match="Invalid scope format"):
            parse_scope("invalid-scope")

    def test_parse_scope_invalid_type(self):
        """Test parsing invalid scope type."""
        with pytest.raises(ValueError, match="Invalid scope type"):
            parse_scope("team:team-123")

    def test_is_org_scope(self):
        """Test checking if scope is org-level."""
        assert is_org_scope("org:tenant-123") is True
        assert is_org_scope("user:user-123") is False

    def test_is_user_scope(self):
        """Test checking if scope is user-level."""
        assert is_user_scope("user:user-123") is True
        assert is_user_scope("org:tenant-123") is False


class TestEnvironmentPlanResolver:
    """Tests for environment-based plan resolution."""

    def test_default_plan(self):
        """Test default plan is free."""
        resolver = EnvironmentPlanResolver()

        # Clear any existing env var
        env_key = "AMPREALIZE_PLAN_ORG_TEST123"
        if env_key in os.environ:
            del os.environ[env_key]

        import asyncio
        plan = asyncio.get_event_loop().run_until_complete(
            resolver.get_plan("org:test123")
        )

        assert plan == "free"

    def test_custom_default_plan(self):
        """Test custom default plan."""
        resolver = EnvironmentPlanResolver(default_plan="pro")

        import asyncio
        plan = asyncio.get_event_loop().run_until_complete(
            resolver.get_plan("org:unknown")
        )

        assert plan == "pro"

    def test_plan_from_env_var(self):
        """Test plan resolved from environment variable."""
        resolver = EnvironmentPlanResolver()

        # Set env var for this scope
        os.environ["AMPREALIZE_PLAN_ORG_TESTORG"] = "enterprise"

        try:
            import asyncio
            plan = asyncio.get_event_loop().run_until_complete(
                resolver.get_plan("org:testorg")
            )

            assert plan == "enterprise"
        finally:
            del os.environ["AMPREALIZE_PLAN_ORG_TESTORG"]


class TestQuotaService:
    """Tests for QuotaService."""

    @pytest.fixture
    def quota_service(self):
        """Create a quota service with mock resolver."""
        reset_quota_service()
        return QuotaService()

    @pytest.mark.asyncio
    async def test_get_limits_free_tier(self, quota_service):
        """Test getting limits for free tier."""
        limits = await quota_service.get_limits("user-123")

        assert limits.max_concurrent_workspaces == 1
        assert limits.priority_boost == 0

    @pytest.mark.asyncio
    async def test_get_limits_with_org(self, quota_service):
        """Test getting limits uses org scope when provided."""
        # Mock resolver to return pro for org
        async def mock_get_plan(scope: str) -> str:
            if scope.startswith("org:"):
                return "pro"
            return "free"

        quota_service._plan_resolver.get_plan = mock_get_plan

        limits = await quota_service.get_limits("user-123", org_id="org-456")

        assert limits.max_concurrent_workspaces == 5  # Pro tier
        assert limits.priority_boost == 2

    @pytest.mark.asyncio
    async def test_get_limits_for_scope(self, quota_service):
        """Test getting limits directly for a scope."""
        async def mock_get_plan(scope: str) -> str:
            if "enterprise" in scope:
                return "enterprise"
            return "free"

        quota_service._plan_resolver.get_plan = mock_get_plan

        limits = await quota_service.get_limits_for_scope("org:enterprise-tenant")

        assert limits.max_concurrent_workspaces == 20  # Enterprise tier

    @pytest.mark.asyncio
    async def test_check_can_execute_under_quota(self, quota_service):
        """Test execution allowed under quota."""
        can_exec = await quota_service.check_can_execute(
            user_id="user-123",
            org_id=None,
            current_count=0,
        )

        assert can_exec is True

    @pytest.mark.asyncio
    async def test_check_can_execute_at_quota(self, quota_service):
        """Test execution blocked at quota limit."""
        # Free tier has max 1 concurrent
        can_exec = await quota_service.check_can_execute(
            user_id="user-123",
            org_id=None,
            current_count=1,
        )

        assert can_exec is False

    @pytest.mark.asyncio
    async def test_check_can_execute_over_quota(self, quota_service):
        """Test execution blocked over quota."""
        can_exec = await quota_service.check_can_execute(
            user_id="user-123",
            org_id=None,
            current_count=5,
        )

        assert can_exec is False

    @pytest.mark.asyncio
    async def test_get_priority_boost_free(self, quota_service):
        """Test priority boost for free tier."""
        boost = await quota_service.get_priority_boost("user-123")

        assert boost == 0

    @pytest.mark.asyncio
    async def test_get_priority_boost_enterprise(self, quota_service):
        """Test priority boost for enterprise tier."""
        async def mock_get_plan(scope: str) -> str:
            return "enterprise"

        quota_service._plan_resolver.get_plan = mock_get_plan

        boost = await quota_service.get_priority_boost("user-123", org_id="org-ent")

        assert boost == 5

    def test_get_limits_sync(self, quota_service):
        """Test synchronous limit lookup by plan."""
        limits = quota_service.get_limits_sync("pro")

        assert limits.max_concurrent_workspaces == 5
        assert limits.priority_boost == 2

    def test_get_limits_sync_unknown_plan(self, quota_service):
        """Test synchronous limit lookup for unknown plan defaults to free."""
        limits = quota_service.get_limits_sync("unknown_plan")

        assert limits.max_concurrent_workspaces == 1


class TestMultiTenantIsolation:
    """Tests for multi-tenant isolation scenarios."""

    @pytest.mark.asyncio
    async def test_different_orgs_separate_scopes(self):
        """Test that different orgs get separate scopes."""
        scope_a = get_isolation_scope("user-1", org_id="org-alpha")
        scope_b = get_isolation_scope("user-1", org_id="org-beta")

        assert scope_a != scope_b
        assert scope_a == "org:org-alpha"
        assert scope_b == "org:org-beta"

    @pytest.mark.asyncio
    async def test_same_user_different_contexts(self):
        """Test same user in different contexts gets different scopes."""
        # User in org context
        scope_org = get_isolation_scope("user-123", org_id="org-456")

        # Same user in personal context
        scope_personal = get_isolation_scope("user-123", org_id=None)

        assert scope_org != scope_personal
        assert scope_org == "org:org-456"
        assert scope_personal == "user:user-123"

    @pytest.mark.asyncio
    async def test_org_plan_applies_to_all_users(self):
        """Test that org plan applies to all users in org."""
        quota_service = QuotaService()

        async def mock_get_plan(scope: str) -> str:
            if scope == "org:pro-org":
                return "pro"
            return "free"

        quota_service._plan_resolver.get_plan = mock_get_plan

        # Different users in same org should get same limits
        limits_user1 = await quota_service.get_limits("user-1", org_id="pro-org")
        limits_user2 = await quota_service.get_limits("user-2", org_id="pro-org")

        assert limits_user1.max_concurrent_workspaces == limits_user2.max_concurrent_workspaces
        assert limits_user1.priority_boost == limits_user2.priority_boost

    @pytest.mark.asyncio
    async def test_user_plan_when_no_org(self):
        """Test that user plan applies when not in org context."""
        quota_service = QuotaService()

        async def mock_get_plan(scope: str) -> str:
            if scope == "user:premium-user":
                return "pro"
            return "free"

        quota_service._plan_resolver.get_plan = mock_get_plan

        limits = await quota_service.get_limits("premium-user", org_id=None)

        assert limits.max_concurrent_workspaces == 5  # Pro tier


class TestQuotaServiceSingleton:
    """Tests for module-level singleton."""

    def test_get_quota_service_returns_same_instance(self):
        """Test singleton returns same instance."""
        reset_quota_service()

        service1 = get_quota_service()
        service2 = get_quota_service()

        assert service1 is service2

    def test_reset_clears_singleton(self):
        """Test reset creates new instance."""
        reset_quota_service()

        service1 = get_quota_service()
        reset_quota_service()
        service2 = get_quota_service()

        assert service1 is not service2
