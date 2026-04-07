"""Quota Service - Plan-based resource limits and enforcement.

The QuotaService manages resource quotas for organizations and users:
- Resolves effective limits based on plan tier
- Supports org-optional scope (orgs inherit plan, users default to free)
- Provides priority boost values for queue ordering
- Checks execution eligibility against current usage

Architecture:
    ┌─────────────────────────────────────────────────────────────┐
    │                      QuotaService                           │
    │  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐   │
    │  │ PlanResolver │  │  ScopeUtils  │  │   StateStore    │   │
    │  │ (DB/config)  │  │ (isolation)  │  │ (usage count)   │   │
    │  └──────────────┘  └──────────────┘  └─────────────────┘   │
    └─────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol, Tuple

logger = logging.getLogger(__name__)


@dataclass
class QuotaLimits:
    """Resource limits for a scope (tenant).

    Defines maximum resources a tenant can consume:
    - max_concurrent_workspaces: Parallel running workspaces
    - max_execution_seconds: Timeout per execution
    - max_workspace_memory: Container memory limit
    - max_workspace_cpu: Container CPU cores
    - priority_boost: Added to job priority for queue ordering
    """
    max_concurrent_workspaces: int = 1
    max_execution_seconds: int = 600  # 10 minutes
    max_workspace_memory: str = "512m"
    max_workspace_cpu: float = 1.0
    priority_boost: int = 0

    # Optional: daily/monthly limits
    max_executions_per_day: Optional[int] = None
    max_executions_per_month: Optional[int] = None

    # Optional: model token limits
    max_tokens_per_execution: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "max_concurrent_workspaces": self.max_concurrent_workspaces,
            "max_execution_seconds": self.max_execution_seconds,
            "max_workspace_memory": self.max_workspace_memory,
            "max_workspace_cpu": self.max_workspace_cpu,
            "priority_boost": self.priority_boost,
            "max_executions_per_day": self.max_executions_per_day,
            "max_executions_per_month": self.max_executions_per_month,
            "max_tokens_per_execution": self.max_tokens_per_execution,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QuotaLimits":
        """Create from dictionary."""
        return cls(
            max_concurrent_workspaces=data.get("max_concurrent_workspaces", 1),
            max_execution_seconds=data.get("max_execution_seconds", 600),
            max_workspace_memory=data.get("max_workspace_memory", "512m"),
            max_workspace_cpu=data.get("max_workspace_cpu", 1.0),
            priority_boost=data.get("priority_boost", 0),
            max_executions_per_day=data.get("max_executions_per_day"),
            max_executions_per_month=data.get("max_executions_per_month"),
            max_tokens_per_execution=data.get("max_tokens_per_execution"),
        )


# Plan tier definitions - can be overridden via environment or database
PLAN_LIMITS = {
    "free": QuotaLimits(
        max_concurrent_workspaces=1,
        max_execution_seconds=600,  # 10 minutes
        max_workspace_memory="512m",
        max_workspace_cpu=1.0,
        priority_boost=0,
        max_executions_per_day=10,
        max_executions_per_month=100,
    ),
    "pro": QuotaLimits(
        max_concurrent_workspaces=5,
        max_execution_seconds=3600,  # 1 hour
        max_workspace_memory="2g",
        max_workspace_cpu=2.0,
        priority_boost=2,
        max_executions_per_day=100,
        max_executions_per_month=1000,
    ),
    "enterprise": QuotaLimits(
        max_concurrent_workspaces=20,
        max_execution_seconds=14400,  # 4 hours
        max_workspace_memory="4g",
        max_workspace_cpu=4.0,
        priority_boost=5,
        max_executions_per_day=None,  # Unlimited
        max_executions_per_month=None,  # Unlimited
    ),
}


# =============================================================================
# Scope Resolution Utilities
# =============================================================================

def get_isolation_scope(user_id: str, org_id: Optional[str] = None) -> str:
    """Get the isolation scope key for a user/org.

    Organizations take precedence over users for scope:
    - With org_id: "org:{org_id}"
    - Without org_id: "user:{user_id}"

    Args:
        user_id: The user ID
        org_id: Optional organization ID

    Returns:
        Scope string for quota tracking
    """
    if org_id:
        return f"org:{org_id}"
    return f"user:{user_id}"


def parse_scope(scope: str) -> Tuple[str, str]:
    """Parse a scope string into type and ID.

    Args:
        scope: Scope string like "org:123" or "user:456"

    Returns:
        Tuple of (scope_type, scope_id)

    Raises:
        ValueError: If scope format is invalid
    """
    if ":" not in scope:
        raise ValueError(f"Invalid scope format: {scope}")
    scope_type, scope_id = scope.split(":", 1)
    if scope_type not in ("org", "user"):
        raise ValueError(f"Invalid scope type: {scope_type}")
    return scope_type, scope_id


def is_org_scope(scope: str) -> bool:
    """Check if scope is organization-level."""
    return scope.startswith("org:")


def is_user_scope(scope: str) -> bool:
    """Check if scope is user-level."""
    return scope.startswith("user:")


# =============================================================================
# Plan Resolver Protocol
# =============================================================================

class PlanResolver(Protocol):
    """Protocol for resolving plan tier from scope."""

    async def get_plan(self, scope: str) -> str:
        """Get the plan tier for a scope.

        Args:
            scope: Scope string like "org:123" or "user:456"

        Returns:
            Plan tier string: "free", "pro", or "enterprise"
        """
        ...


class EnvironmentPlanResolver:
    """Resolve plans from environment variables (for testing).

    Set plan via env vars:
    - AMPREALIZE_PLAN_ORG_123=pro
    - AMPREALIZE_PLAN_USER_456=enterprise
    - AMPREALIZE_DEFAULT_PLAN=free
    """

    def __init__(self, default_plan: str = "free"):
        self._default_plan = default_plan

    async def get_plan(self, scope: str) -> str:
        """Get plan from environment variables."""
        # Convert scope to env var name: org:123 -> AMPREALIZE_PLAN_ORG_123
        env_key = f"AMPREALIZE_PLAN_{scope.upper().replace(':', '_')}"
        plan = os.environ.get(env_key, self._default_plan)
        return plan if plan in PLAN_LIMITS else self._default_plan


class DatabasePlanResolver:
    """Resolve plans from database (production).

    Requires injection of database pool or connection factory.
    """

    def __init__(self, db_pool: Any):
        self._db = db_pool

    async def get_plan(self, scope: str) -> str:
        """Get plan from database lookup."""
        scope_type, scope_id = parse_scope(scope)

        if scope_type == "org":
            query = """
                SELECT subscription_tier FROM organizations
                WHERE id = $1 AND is_active = true
            """
        else:
            query = """
                SELECT subscription_tier FROM users
                WHERE id = $1 AND is_active = true
            """

        try:
            async with self._db.acquire() as conn:
                row = await conn.fetchrow(query, scope_id)
                if row and row["subscription_tier"]:
                    return row["subscription_tier"]
        except Exception as e:
            logger.warning(f"Failed to resolve plan for {scope}: {e}")

        return "free"


# =============================================================================
# Quota Service
# =============================================================================

class QuotaService:
    """Manages resource quotas for organizations and users.

    The QuotaService is the central authority for quota enforcement:
    1. Resolves the plan tier for a given scope
    2. Returns the corresponding QuotaLimits
    3. Checks if execution is allowed under current usage

    Example:
        quota_service = QuotaService()

        # Get limits for a scope
        limits = await quota_service.get_limits("user:123", org_id="org:456")

        # Check if execution is allowed
        can_exec = await quota_service.check_can_execute(
            user_id="user:123",
            org_id="org:456",
            current_count=2,
        )
    """

    def __init__(
        self,
        plan_resolver: Optional[PlanResolver] = None,
        plan_limits: Optional[Dict[str, QuotaLimits]] = None,
    ):
        """Initialize the quota service.

        Args:
            plan_resolver: Resolver for looking up plan tier
            plan_limits: Custom plan limit definitions
        """
        self._plan_resolver = plan_resolver or EnvironmentPlanResolver()
        self._plan_limits = plan_limits or PLAN_LIMITS

    async def get_plan(self, scope: str) -> str:
        """Get the plan tier for a scope.

        Args:
            scope: Scope string like "org:123" or "user:456"

        Returns:
            Plan tier string
        """
        return await self._plan_resolver.get_plan(scope)

    async def get_limits(
        self,
        user_id: str,
        org_id: Optional[str] = None,
    ) -> QuotaLimits:
        """Get effective limits for a user/org.

        Organization scope takes precedence over user scope.

        Args:
            user_id: The user ID
            org_id: Optional organization ID

        Returns:
            QuotaLimits for the effective scope
        """
        scope = get_isolation_scope(user_id, org_id)
        plan = await self.get_plan(scope)
        return self._plan_limits.get(plan, self._plan_limits["free"])

    async def get_limits_for_scope(self, scope: str) -> QuotaLimits:
        """Get limits for a scope string.

        Args:
            scope: Scope string like "org:123" or "user:456"

        Returns:
            QuotaLimits for the scope
        """
        plan = await self.get_plan(scope)
        return self._plan_limits.get(plan, self._plan_limits["free"])

    async def check_can_execute(
        self,
        user_id: str,
        org_id: Optional[str],
        current_count: int,
    ) -> bool:
        """Check if execution is allowed under current quota.

        Args:
            user_id: The user ID
            org_id: Optional organization ID
            current_count: Current number of active workspaces

        Returns:
            True if execution is allowed
        """
        limits = await self.get_limits(user_id, org_id)
        return current_count < limits.max_concurrent_workspaces

    async def get_priority_boost(
        self,
        user_id: str,
        org_id: Optional[str] = None,
    ) -> int:
        """Get priority boost for queue ordering.

        Higher values = higher priority in queue.

        Args:
            user_id: The user ID
            org_id: Optional organization ID

        Returns:
            Priority boost integer
        """
        limits = await self.get_limits(user_id, org_id)
        return limits.priority_boost

    def get_limits_sync(self, plan: str) -> QuotaLimits:
        """Get limits for a plan tier (synchronous).

        Args:
            plan: Plan tier string

        Returns:
            QuotaLimits for the plan
        """
        return self._plan_limits.get(plan, self._plan_limits["free"])


# =============================================================================
# Module Singleton
# =============================================================================

_quota_service: Optional[QuotaService] = None


def get_quota_service(
    plan_resolver: Optional[PlanResolver] = None,
    plan_limits: Optional[Dict[str, QuotaLimits]] = None,
) -> QuotaService:
    """Get or create the module-level QuotaService singleton.

    Args:
        plan_resolver: Optional plan resolver (used on first call)
        plan_limits: Optional custom plan limits (used on first call)

    Returns:
        QuotaService instance
    """
    global _quota_service
    if _quota_service is None:
        _quota_service = QuotaService(
            plan_resolver=plan_resolver,
            plan_limits=plan_limits,
        )
    return _quota_service


def reset_quota_service() -> None:
    """Reset the singleton (for testing)."""
    global _quota_service
    _quota_service = None
