"""Data contracts for API Rate Limiting - token bucket implementation and per-user limits."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class RateLimitType(str, Enum):
    """Types of rate limits."""
    FIXED_WINDOW = "fixed_window"
    SLIDING_WINDOW = "sliding_window"
    TOKEN_BUCKET = "token_bucket"
    LEAKY_BUCKET = "leaky_bucket"
    HYBRID = "hybrid"


class LimitScope(str, Enum):
    """Scope of rate limits."""
    USER = "user"
    IP_ADDRESS = "ip_address"
    API_KEY = "api_key"
    TENANT = "tenant"
    ENDPOINT = "endpoint"
    GLOBAL = "global"


@dataclass
class RateLimitRule:
    """Rate limiting rule configuration."""
    rule_id: str
    name: str
    limit_type: RateLimitType
    scope: LimitScope
    max_requests: int
    time_window_seconds: int
    burst_limit: Optional[int]  # For token bucket
    refill_rate: Optional[float]  # Tokens per second
    is_active: bool
    created_at: datetime
    priority: int = 0  # Lower number = higher priority

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "limit_type": self.limit_type.value,
            "scope": self.scope.value,
            "max_requests": self.max_requests,
            "time_window_seconds": self.time_window_seconds,
            "burst_limit": self.burst_limit,
            "refill_rate": self.refill_rate,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "priority": self.priority,
        }


@dataclass
class TokenBucket:
    """Token bucket state for rate limiting."""
    bucket_id: str
    user_identifier: str  # user_id, ip_address, etc.
    rule_id: str
    capacity: int
    tokens: float
    last_refill: datetime
    refill_rate: float  # tokens per second
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bucket_id": self.bucket_id,
            "user_identifier": self.user_identifier,
            "rule_id": self.rule_id,
            "capacity": self.capacity,
            "tokens": self.tokens,
            "last_refill": self.last_refill.isoformat(),
            "refill_rate": self.refill_rate,
            "is_active": self.is_active,
        }


@dataclass
class RequestRecord:
    """Record of a rate-limited request."""
    record_id: str
    user_identifier: str
    endpoint: str
    method: str
    timestamp: datetime
    response_status: int
    rule_applied: Optional[str]
    tokens_consumed: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "user_identifier": self.user_identifier,
            "endpoint": self.endpoint,
            "method": self.method,
            "timestamp": self.timestamp.isoformat(),
            "response_status": self.response_status,
            "rule_applied": self.rule_applied,
            "tokens_consumed": self.tokens_consumed,
        }


@dataclass
class RateLimitViolation:
    """Rate limit violation event."""
    violation_id: str
    user_identifier: str
    rule_id: str
    endpoint: str
    timestamp: datetime
    request_count: int
    limit_exceeded: int
    violation_type: str  # "hard_limit", "soft_limit", "burst_limit"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "violation_id": self.violation_id,
            "user_identifier": self.user_identifier,
            "rule_id": self.rule_id,
            "endpoint": self.endpoint,
            "timestamp": self.timestamp.isoformat(),
            "request_count": self.request_count,
            "limit_exceeded": self.limit_exceeded,
            "violation_type": self.violation_type,
        }


@dataclass
class RateLimitStatus:
    """Current rate limit status for a user."""
    user_identifier: str
    active_rules: List[RateLimitRule]
    current_usage: Dict[str, int]  # rule_id -> current requests
    remaining_quota: Dict[str, int]  # rule_id -> remaining requests
    reset_times: Dict[str, datetime]  # rule_id -> reset time
    bucket_status: Dict[str, TokenBucket]  # rule_id -> bucket status
    is_blocked: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_identifier": self.user_identifier,
            "active_rules": [rule.to_dict() for rule in self.active_rules],
            "current_usage": self.current_usage,
            "remaining_quota": self.remaining_quota,
            "reset_times": {k: v.isoformat() for k, v in self.reset_times.items()},
            "bucket_status": {k: v.to_dict() for k, v in self.bucket_status.items()},
            "is_blocked": self.is_blocked,
        }


@dataclass
class CreateRateLimitRuleRequest:
    """Request to create a new rate limit rule."""
    name: str
    limit_type: RateLimitType
    scope: LimitScope
    max_requests: int
    time_window_seconds: int
    burst_limit: Optional[int] = None
    refill_rate: Optional[float] = None
    priority: int = 0
    is_active: bool = True


@dataclass
class UpdateRateLimitRuleRequest:
    """Request to update a rate limit rule."""
    rule_id: str
    name: Optional[str] = None
    max_requests: Optional[int] = None
    time_window_seconds: Optional[int] = None
    burst_limit: Optional[int] = None
    refill_rate: Optional[float] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None


@dataclass
class RateLimitCheckRequest:
    """Request to check rate limit status."""
    user_identifier: str
    endpoint: str
    method: str = "GET"
    tokens_requested: float = 1.0


@dataclass
class RateLimitResponse:
    """Response from rate limit check."""
    allowed: bool
    remaining_quota: int
    reset_time: datetime
    rule_applied: Optional[str]
    violation: Optional[RateLimitViolation]
    retry_after_seconds: Optional[int] = None
    rate_limit_headers: Optional[Dict[str, str]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "remaining_quota": self.remaining_quota,
            "reset_time": self.reset_time.isoformat(),
            "rule_applied": self.rule_applied,
            "violation": self.violation.to_dict() if self.violation else None,
            "retry_after_seconds": self.retry_after_seconds,
            "rate_limit_headers": self.rate_limit_headers,
        }


@dataclass
class RateLimitMetrics:
    """Metrics for rate limiting performance."""
    timestamp: datetime
    total_requests: int
    allowed_requests: int
    blocked_requests: int
    violation_count: int
    active_users: int
    top_violators: List[Dict[str, Any]]
    endpoint_usage: Dict[str, int]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "total_requests": self.total_requests,
            "allowed_requests": self.allowed_requests,
            "blocked_requests": self.blocked_requests,
            "violation_count": self.violation_count,
            "active_users": self.active_users,
            "top_violators": self.top_violators,
            "endpoint_usage": self.endpoint_usage,
        }


@dataclass
class UserQuota:
    """User-specific quota configuration."""
    user_id: str
    daily_limit: int
    monthly_limit: int
    concurrent_requests: int
    endpoints: Dict[str, Dict[str, int]]  # endpoint -> method -> limit
    is_active: bool = True
    expires_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "daily_limit": self.daily_limit,
            "monthly_limit": self.monthly_limit,
            "concurrent_requests": self.concurrent_requests,
            "endpoints": self.endpoints,
            "is_active": self.is_active,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


@dataclass
class ExemptionRule:
    """Rule to exempt certain requests from rate limiting."""
    exemption_id: str
    name: str
    condition: Dict[str, Any]  # Matching conditions
    scope: LimitScope
    is_active: bool
    created_at: datetime
    priority: int = -1  # Higher priority than normal rules

    def to_dict(self) -> Dict[str, Any]:
        return {
            "exemption_id": self.exemption_id,
            "name": self.name,
            "condition": self.condition,
            "scope": self.scope.value,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "priority": self.priority,
        }
