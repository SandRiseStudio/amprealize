"""APIRateLimitingService - token bucket implementation and per-user limits."""

from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import logging
import uuid
import time
from collections import defaultdict, deque

from .api_rate_limiting_contracts import (
    RateLimitType, LimitScope, RateLimitRule, TokenBucket, RequestRecord,
    RateLimitViolation, RateLimitStatus, CreateRateLimitRuleRequest,
    UpdateRateLimitRuleRequest, RateLimitCheckRequest, RateLimitResponse,
    RateLimitMetrics, UserQuota, ExemptionRule
)
from .telemetry import TelemetryClient

# Optional Redis storage for distributed rate limiting
try:
    from amprealize.storage.rate_limit_store import get_rate_limit_store, RateLimitStore
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


class APIRateLimitingService:
    """API rate limiting service with token bucket and per-user limits.

    Supports two storage backends:
    - In-memory (default): For single-instance deployments
    - Redis: For distributed multi-instance deployments (recommended)

    Set use_redis=True for distributed rate limiting across instances.
    """

    def __init__(
        self,
        telemetry: Optional[TelemetryClient] = None,
        use_redis: bool = False,
        redis_store: Optional[Any] = None,
    ) -> None:
        """Initialize APIRateLimitingService.

        Args:
            telemetry: Telemetry client for metrics
            use_redis: If True, use Redis for distributed rate limiting
            redis_store: Optional pre-configured RateLimitStore instance
        """
        self._telemetry = telemetry or TelemetryClient.noop()
        self._use_redis = use_redis and REDIS_AVAILABLE
        self._redis_store = redis_store

        # In-memory state (fallback or for rule storage)
        self._rules: Dict[str, RateLimitRule] = {}
        self._token_buckets: Dict[str, TokenBucket] = {}
        self._request_records: deque = deque(maxlen=100000)  # Keep last 100k requests
        self._violations: List[RateLimitViolation] = []
        self._user_quotas: Dict[str, UserQuota] = {}
        self._exemptions: Dict[str, ExemptionRule] = {}
        self._user_usage: Dict[str, Dict[str, deque]] = defaultdict(lambda: defaultdict(deque))

        # Initialize Redis store if enabled
        if self._use_redis and self._redis_store is None:
            try:
                self._redis_store = get_rate_limit_store()
                self._logger.info("Rate limiting using Redis storage (distributed mode)")
            except Exception as e:
                self._logger.warning(f"Redis unavailable, falling back to in-memory: {e}")
                self._use_redis = False

        # Initialize default rules
        self._initialize_default_rules()

        self._logger = logging.getLogger(__name__)

        # Initialize default rules
        self._initialize_default_rules()

        self._logger = logging.getLogger(__name__)

    def create_rate_limit_rule(self, request: CreateRateLimitRuleRequest) -> RateLimitRule:
        """Create a new rate limit rule."""
        rule_id = str(uuid.uuid4())

        rule = RateLimitRule(
            rule_id=rule_id,
            name=request.name,
            limit_type=request.limit_type,
            scope=request.scope,
            max_requests=request.max_requests,
            time_window_seconds=request.time_window_seconds,
            burst_limit=request.burst_limit,
            refill_rate=request.refill_rate,
            is_active=request.is_active,
            created_at=datetime.utcnow(),
            priority=request.priority
        )

        self._rules[rule_id] = rule

        # Initialize token bucket if needed
        if request.limit_type == RateLimitType.TOKEN_BUCKET and request.burst_limit and request.refill_rate:
            self._initialize_token_bucket(rule_id, request.scope, request.burst_limit, request.refill_rate)

        self._emit_telemetry("rate_limit_rule_created", {
            "rule_id": rule_id,
            "name": request.name,
            "scope": request.scope.value,
            "max_requests": request.max_requests
        })

        return rule

    def update_rate_limit_rule(self, request: UpdateRateLimitRuleRequest) -> RateLimitRule:
        """Update an existing rate limit rule."""
        if request.rule_id not in self._rules:
            raise ValueError(f"Rate limit rule {request.rule_id} not found")

        rule = self._rules[request.rule_id]

        # Update fields if provided
        if request.name is not None:
            rule.name = request.name
        if request.max_requests is not None:
            rule.max_requests = request.max_requests
        if request.time_window_seconds is not None:
            rule.time_window_seconds = request.time_window_seconds
        if request.burst_limit is not None:
            rule.burst_limit = request.burst_limit
        if request.refill_rate is not None:
            rule.refill_rate = request.refill_rate
        if request.priority is not None:
            rule.priority = request.priority
        if request.is_active is not None:
            rule.is_active = request.is_active

        self._emit_telemetry("rate_limit_rule_updated", {
            "rule_id": request.rule_id,
            "updated_fields": [k for k, v in request.__dict__.items() if v is not None and k != 'rule_id']
        })

        return rule

    def check_rate_limit(self, request: RateLimitCheckRequest) -> RateLimitResponse:
        """Check if request is within rate limits."""
        start_time = time.time()

        # Check exemptions first
        if self._is_exempted(request):
            return RateLimitResponse(
                allowed=True,
                remaining_quota=999999,
                reset_time=datetime.utcnow() + timedelta(hours=1),
                rule_applied=None,
                violation=None,
                rate_limit_headers=self._build_rate_limit_headers(999999, 3600)
            )

        # Get applicable rules
        applicable_rules = self._get_applicable_rules(request)

        if not applicable_rules:
            return RateLimitResponse(
                allowed=True,
                remaining_quota=999999,
                reset_time=datetime.utcnow() + timedelta(hours=1),
                rule_applied=None,
                violation=None,
                rate_limit_headers=self._build_rate_limit_headers(999999, 3600)
            )

        # Check each rule
        for rule in sorted(applicable_rules, key=lambda r: r.priority):
            response = self._check_rule(request, rule)
            if not response.allowed:
                # Log violation
                self._log_violation(request, rule, response)
                return response

        # All checks passed - record the request
        self._record_request(request, applicable_rules[0] if applicable_rules else None)

        # Calculate headers
        primary_rule = applicable_rules[0] if applicable_rules else None
        remaining_quota = self._calculate_remaining_quota(request, primary_rule) if primary_rule else 999999
        reset_time = self._calculate_reset_time(request, primary_rule) if primary_rule else datetime.utcnow() + timedelta(hours=1)

        processing_time = (time.time() - start_time) * 1000
        self._emit_telemetry("rate_limit_check", {
            "user_identifier": request.user_identifier,
            "endpoint": request.endpoint,
            "processing_time_ms": processing_time,
            "rules_checked": len(applicable_rules)
        })

        return RateLimitResponse(
            allowed=True,
            remaining_quota=remaining_quota,
            reset_time=reset_time,
            rule_applied=primary_rule.rule_id if primary_rule else None,
            violation=None,
            rate_limit_headers=self._build_rate_limit_headers(remaining_quota, (reset_time - datetime.utcnow()).seconds)
        )

    def get_rate_limit_status(self, user_identifier: str) -> RateLimitStatus:
        """Get current rate limit status for a user."""
        # Get user's active rules
        user_rules = [
            rule for rule in self._rules.values()
            if (rule.is_active and
                (rule.scope == LimitScope.USER or
                 rule.scope == LimitScope.IP_ADDRESS or
                 rule.scope == LimitScope.GLOBAL))
        ]

        # Calculate current usage
        current_usage = {}
        remaining_quota = {}
        reset_times = {}
        bucket_status = {}

        for rule in user_rules:
            if rule.scope == LimitScope.USER and user_identifier:
                usage_key = f"{user_identifier}_{rule.rule_id}"
            elif rule.scope == LimitScope.IP_ADDRESS:
                usage_key = f"ip_{user_identifier}_{rule.rule_id}"
            else:  # GLOBAL
                usage_key = f"global_{rule.rule_id}"

            # Get current usage
            usage = self._get_current_usage(usage_key, rule.time_window_seconds)
            current_usage[rule.rule_id] = len(usage)
            remaining_quota[rule.rule_id] = max(0, rule.max_requests - len(usage))

            # Calculate reset time
            if usage:
                reset_times[rule.rule_id] = max(usage) + timedelta(seconds=rule.time_window_seconds)
            else:
                reset_times[rule.rule_id] = datetime.utcnow()

            # Get bucket status
            bucket_id = f"{usage_key}_bucket"
            if bucket_id in self._token_buckets:
                bucket_status[rule.rule_id] = self._token_buckets[bucket_id]

        # Check if user is blocked
        is_blocked = any(len(self._get_current_usage(f"{user_identifier}_{rule.rule_id}", rule.time_window_seconds)) >= rule.max_requests
                        for rule in user_rules)

        return RateLimitStatus(
            user_identifier=user_identifier,
            active_rules=user_rules,
            current_usage=current_usage,
            remaining_quota=remaining_quota,
            reset_times=reset_times,
            bucket_status=bucket_status,
            is_blocked=is_blocked
        )

    def create_user_quota(self, quota: UserQuota) -> None:
        """Create or update user-specific quota."""
        self._user_quotas[quota.user_id] = quota

        self._emit_telemetry("user_quota_created", {
            "user_id": quota.user_id,
            "daily_limit": quota.daily_limit,
            "monthly_limit": quota.monthly_limit
        })

    def add_exemption(self, exemption: ExemptionRule) -> None:
        """Add exemption rule to bypass rate limiting."""
        self._exemptions[exemption.exemption_id] = exemption

        self._emit_telemetry("exemption_added", {
            "exemption_id": exemption.exemption_id,
            "name": exemption.name
        })

    def get_rate_limit_metrics(self, hours: int = 24) -> RateLimitMetrics:
        """Get rate limiting performance metrics."""
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)

        # Filter recent records
        recent_records = [
            record for record in self._request_records
            if record.timestamp >= cutoff_time
        ]

        # Calculate metrics
        total_requests = len(recent_records)
        allowed_requests = sum(1 for record in recent_records if record.response_status == 200)
        blocked_requests = sum(1 for record in recent_records if record.response_status == 429)

        # Count violations
        recent_violations = [
            violation for violation in self._violations
            if violation.timestamp >= cutoff_time
        ]

        # Get active users
        active_users = len(set(record.user_identifier for record in recent_records))

        # Top violators
        violation_counts = defaultdict(int)
        for violation in recent_violations:
            violation_counts[violation.user_identifier] += 1

        top_violators = [
            {"user_id": user_id, "violations": count}
            for user_id, count in sorted(violation_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        ]

        # Endpoint usage
        endpoint_usage = defaultdict(int)
        for record in recent_records:
            endpoint_usage[record.endpoint] += 1

        return RateLimitMetrics(
            timestamp=datetime.utcnow(),
            total_requests=total_requests,
            allowed_requests=allowed_requests,
            blocked_requests=blocked_requests,
            violation_count=len(recent_violations),
            active_users=active_users,
            top_violators=top_violators,
            endpoint_usage=dict(endpoint_usage)
        )

    def get_rules(self, scope: Optional[LimitScope] = None, is_active: Optional[bool] = None) -> List[RateLimitRule]:
        """Get rate limit rules with optional filters."""
        rules = list(self._rules.values())

        if scope:
            rules = [rule for rule in rules if rule.scope == scope]

        if is_active is not None:
            rules = [rule for rule in rules if rule.is_active == is_active]

        return sorted(rules, key=lambda r: r.priority)

    def get_user_quotas(self) -> List[UserQuota]:
        """Get all user quotas."""
        return list(self._user_quotas.values())

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rate limit rule."""
        if rule_id in self._rules:
            del self._rules[rule_id]

            # Clean up associated token buckets
            buckets_to_remove = [bid for bid, bucket in self._token_buckets.items() if bucket.rule_id == rule_id]
            for bucket_id in buckets_to_remove:
                del self._token_buckets[bucket_id]

            return True
        return False

    def reset_user_limits(self, user_identifier: str) -> None:
        """Reset rate limits for a specific user (admin function)."""
        # Clear user's request history
        user_records = [record for record in self._request_records if record.user_identifier == user_identifier]
        for record in user_records:
            self._request_records.remove(record)

        # Clear violations
        self._violations = [v for v in self._violations if v.user_identifier != user_identifier]

        # Reset token buckets
        buckets_to_reset = [bid for bid, bucket in self._token_buckets.items() if bucket.user_identifier == user_identifier]
        for bucket_id in buckets_to_reset:
            bucket = self._token_buckets[bucket_id]
            bucket.tokens = bucket.capacity
            bucket.last_refill = datetime.utcnow()

        self._emit_telemetry("user_limits_reset", {
            "user_identifier": user_identifier,
            "reset_at": datetime.utcnow().isoformat()
        })

    def _initialize_default_rules(self) -> None:
        """Initialize default rate limit rules."""
        default_rules = [
            CreateRateLimitRuleRequest(
                name="Default User Limit",
                limit_type=RateLimitType.FIXED_WINDOW,
                scope=LimitScope.USER,
                max_requests=1000,
                time_window_seconds=3600,  # 1 hour
                priority=10
            ),
            CreateRateLimitRuleRequest(
                name="Default IP Limit",
                limit_type=RateLimitType.FIXED_WINDOW,
                scope=LimitScope.IP_ADDRESS,
                max_requests=5000,
                time_window_seconds=3600,  # 1 hour
                priority=20
            ),
            CreateRateLimitRuleRequest(
                name="API Token Bucket",
                limit_type=RateLimitType.TOKEN_BUCKET,
                scope=LimitScope.USER,
                max_requests=100,
                time_window_seconds=60,  # 1 minute
                burst_limit=20,
                refill_rate=2.0,  # 2 tokens per second
                priority=5
            )
        ]

        for rule_request in default_rules:
            self.create_rate_limit_rule(rule_request)

    def _initialize_token_bucket(self, rule_id: str, scope: LimitScope, capacity: int, refill_rate: float) -> None:
        """Initialize token bucket for a rule."""
        bucket_id = f"bucket_{rule_id}_{scope.value}"

        token_bucket = TokenBucket(
            bucket_id=bucket_id,
            user_identifier=scope.value,  # Will be updated per user
            rule_id=rule_id,
            capacity=capacity,
            tokens=capacity,
            last_refill=datetime.utcnow(),
            refill_rate=refill_rate
        )

        self._token_buckets[bucket_id] = token_bucket

    def _is_exempted(self, request: RateLimitCheckRequest) -> bool:
        """Check if request is exempted from rate limiting."""
        for exemption in self._exemptions.values():
            if not exemption.is_active:
                continue

            condition = exemption.condition

            # Check user ID exemption
            if "user_id" in condition and request.user_identifier == condition["user_id"]:
                return True

            # Check IP address exemption
            if "ip_address" in condition and request.user_identifier == condition["ip_address"]:
                return True

            # Check endpoint exemption
            if "endpoint" in condition:
                if isinstance(condition["endpoint"], str):
                    if request.endpoint == condition["endpoint"]:
                        return True
                elif isinstance(condition["endpoint"], list):
                    if request.endpoint in condition["endpoint"]:
                        return True

            # Check method exemption
            if "method" in condition and request.method == condition["method"]:
                return True

        return False

    def _get_applicable_rules(self, request: RateLimitCheckRequest) -> List[RateLimitRule]:
        """Get rules applicable to this request."""
        applicable_rules = []

        for rule in self._rules.values():
            if not rule.is_active:
                continue

            # Check scope applicability
            if rule.scope == LimitScope.USER:
                applicable_rules.append(rule)
            elif rule.scope == LimitScope.IP_ADDRESS:
                applicable_rules.append(rule)
            elif rule.scope == LimitScope.ENDPOINT:
                # Check if endpoint matches (simplified)
                applicable_rules.append(rule)
            elif rule.scope == LimitScope.GLOBAL:
                applicable_rules.append(rule)

        return sorted(applicable_rules, key=lambda r: r.priority)

    def _check_rule(self, request: RateLimitCheckRequest, rule: RateLimitRule) -> RateLimitResponse:
        """Check a specific rate limit rule.

        Uses Redis storage if enabled for distributed rate limiting,
        otherwise falls back to in-memory storage.
        """
        # Use Redis-backed methods when available
        if self._use_redis and self._redis_store:
            return self._check_rule_redis(request, rule)

        # Fall back to in-memory
        if rule.limit_type == RateLimitType.FIXED_WINDOW:
            return self._check_fixed_window(request, rule)
        elif rule.limit_type == RateLimitType.SLIDING_WINDOW:
            return self._check_sliding_window(request, rule)
        elif rule.limit_type == RateLimitType.TOKEN_BUCKET:
            return self._check_token_bucket(request, rule)
        else:
            # Default to allow for unsupported types
            return RateLimitResponse(
                allowed=True,
                remaining_quota=rule.max_requests,
                reset_time=datetime.utcnow() + timedelta(seconds=rule.time_window_seconds),
                rule_applied=rule.rule_id,
                violation=None
            )

    def _check_rule_redis(self, request: RateLimitCheckRequest, rule: RateLimitRule) -> RateLimitResponse:
        """Check rate limit using Redis storage."""
        scope = rule.scope.value
        identifier = request.user_identifier

        if rule.limit_type == RateLimitType.TOKEN_BUCKET:
            if not rule.burst_limit or not rule.refill_rate:
                return RateLimitResponse(
                    allowed=True,
                    remaining_quota=rule.max_requests,
                    reset_time=datetime.utcnow() + timedelta(seconds=rule.time_window_seconds),
                    rule_applied=rule.rule_id,
                    violation=None
                )
            allowed, remaining, reset_time = self._redis_store.check_token_bucket(
                scope=scope,
                identifier=identifier,
                burst_limit=rule.burst_limit,
                refill_rate=rule.refill_rate,
            )
        elif rule.limit_type == RateLimitType.SLIDING_WINDOW:
            allowed, remaining, reset_time = self._redis_store.check_sliding_window(
                rule_id=rule.rule_id,
                scope=scope,
                identifier=identifier,
                max_requests=rule.max_requests,
                window_seconds=rule.time_window_seconds,
            )
        else:  # FIXED_WINDOW or default
            allowed, remaining, reset_time = self._redis_store.check_fixed_window(
                rule_id=rule.rule_id,
                scope=scope,
                identifier=identifier,
                max_requests=rule.max_requests,
                window_seconds=rule.time_window_seconds,
            )

        retry_after = int((reset_time - datetime.utcnow()).total_seconds()) if not allowed else None

        return RateLimitResponse(
            allowed=allowed,
            remaining_quota=remaining,
            reset_time=reset_time,
            rule_applied=rule.rule_id,
            violation=None,
            retry_after_seconds=retry_after,
            rate_limit_headers=self._build_rate_limit_headers(remaining, rule.time_window_seconds) if allowed else None
        )

    def _check_fixed_window(self, request: RateLimitCheckRequest, rule: RateLimitRule) -> RateLimitResponse:
        """Check fixed window rate limit."""
        now = datetime.utcnow()
        window_start = now - timedelta(seconds=rule.time_window_seconds)

        # Count requests in current window
        user_key = f"{request.user_identifier}_{rule.rule_id}"
        usage = self._get_current_usage(user_key, rule.time_window_seconds)

        if len(usage) >= rule.max_requests:
            reset_time = max(usage) + timedelta(seconds=rule.time_window_seconds)
            return RateLimitResponse(
                allowed=False,
                remaining_quota=0,
                reset_time=reset_time,
                rule_applied=rule.rule_id,
                violation=None,
                retry_after_seconds=int((reset_time - now).total_seconds())
            )

        remaining = rule.max_requests - len(usage)
        reset_time = now + timedelta(seconds=rule.time_window_seconds)

        return RateLimitResponse(
            allowed=True,
            remaining_quota=remaining,
            reset_time=reset_time,
            rule_applied=rule.rule_id,
            violation=None
        )

    def _check_sliding_window(self, request: RateLimitCheckRequest, rule: RateLimitRule) -> RateLimitResponse:
        """Check sliding window rate limit."""
        # Simplified sliding window - in production, use more efficient data structures
        now = datetime.utcnow()
        window_start = now - timedelta(seconds=rule.time_window_seconds)

        user_key = f"{request.user_identifier}_{rule.rule_id}"
        usage = [ts for ts in self._user_usage[user_key][rule.rule_id] if ts >= window_start]

        if len(usage) >= rule.max_requests:
            return RateLimitResponse(
                allowed=False,
                remaining_quota=0,
                reset_time=now + timedelta(seconds=rule.time_window_seconds),
                rule_applied=rule.rule_id,
                violation=None,
                retry_after_seconds=rule.time_window_seconds
            )

        remaining = rule.max_requests - len(usage)

        return RateLimitResponse(
            allowed=True,
            remaining_quota=remaining,
            reset_time=now + timedelta(seconds=rule.time_window_seconds),
            rule_applied=rule.rule_id,
            violation=None
        )

    def _check_token_bucket(self, request: RateLimitCheckRequest, rule: RateLimitRule) -> RateLimitResponse:
        """Check token bucket rate limit."""
        if not rule.refill_rate or not rule.burst_limit:
            return RateLimitResponse(
                allowed=True,
                remaining_quota=rule.max_requests,
                reset_time=datetime.utcnow() + timedelta(seconds=rule.time_window_seconds),
                rule_applied=rule.rule_id,
                violation=None
            )

        bucket_id = f"bucket_{rule.rule_id}_{rule.scope.value}"
        user_bucket_id = f"{bucket_id}_{request.user_identifier}"

        # Get or create token bucket for this user
        if user_bucket_id not in self._token_buckets:
            self._token_buckets[user_bucket_id] = TokenBucket(
                bucket_id=user_bucket_id,
                user_identifier=request.user_identifier,
                rule_id=rule.rule_id,
                capacity=rule.burst_limit,
                tokens=rule.burst_limit,
                last_refill=datetime.utcnow(),
                refill_rate=rule.refill_rate
            )

        bucket = self._token_buckets[user_bucket_id]
        now = datetime.utcnow()

        # Refill tokens
        time_elapsed = (now - bucket.last_refill).total_seconds()
        tokens_to_add = time_elapsed * bucket.refill_rate
        bucket.tokens = min(bucket.capacity, bucket.tokens + tokens_to_add)
        bucket.last_refill = now

        # Check if enough tokens
        if bucket.tokens < request.tokens_requested:
            return RateLimitResponse(
                allowed=False,
                remaining_quota=int(bucket.tokens),
                reset_time=now + timedelta(seconds=1.0 / bucket.refill_rate),  # Time to get one token
                rule_applied=rule.rule_id,
                violation=None,
                retry_after_seconds=int(1.0 / bucket.refill_rate)
            )

        # Consume tokens
        bucket.tokens -= request.tokens_requested

        return RateLimitResponse(
            allowed=True,
            remaining_quota=int(bucket.tokens),
            reset_time=now + timedelta(seconds=1.0 / bucket.refill_rate),
            rule_applied=rule.rule_id,
            violation=None
        )

    def _get_current_usage(self, user_key: str, time_window: int) -> List[datetime]:
        """Get current usage within time window."""
        now = datetime.utcnow()
        cutoff = now - timedelta(seconds=time_window)

        # This is a simplified implementation
        # In production, you'd want more efficient data structures
        recent_records = [
            record.timestamp for record in self._request_records
            if (record.user_identifier == user_key.split('_')[0] and
                record.timestamp >= cutoff)
        ]

        return recent_records

    def _record_request(self, request: RateLimitCheckRequest, rule: Optional[RateLimitRule]) -> None:
        """Record a successful request."""
        record = RequestRecord(
            record_id=str(uuid.uuid4()),
            user_identifier=request.user_identifier,
            endpoint=request.endpoint,
            method=request.method,
            timestamp=datetime.utcnow(),
            response_status=200,
            rule_applied=rule.rule_id if rule else None,
            tokens_consumed=request.tokens_requested
        )

        self._request_records.append(record)

        # Also track in per-user usage
        if rule:
            user_key = f"{request.user_identifier}_{rule.rule_id}"
            self._user_usage[user_key][rule.rule_id].append(record.timestamp)

    def _log_violation(self, request: RateLimitCheckRequest, rule: RateLimitRule, response: RateLimitResponse) -> None:
        """Log a rate limit violation."""
        violation = RateLimitViolation(
            violation_id=str(uuid.uuid4()),
            user_identifier=request.user_identifier,
            rule_id=rule.rule_id,
            endpoint=request.endpoint,
            timestamp=datetime.utcnow(),
            request_count=rule.max_requests,
            limit_exceeded=rule.max_requests,
            violation_type="hard_limit"
        )

        self._violations.append(violation)

        # Keep only recent violations
        if len(self._violations) > 10000:
            self._violations = self._violations[-5000:]

        self._emit_telemetry("rate_limit_violation", {
            "user_identifier": request.user_identifier,
            "rule_id": rule.rule_id,
            "endpoint": request.endpoint
        })

    def _calculate_remaining_quota(self, request: RateLimitCheckRequest, rule: Optional[RateLimitRule]) -> int:
        """Calculate remaining quota for response headers."""
        if not rule:
            return 999999

        user_key = f"{request.user_identifier}_{rule.rule_id}"
        usage = self._get_current_usage(user_key, rule.time_window_seconds)
        return max(0, rule.max_requests - len(usage))

    def _calculate_reset_time(self, request: RateLimitCheckRequest, rule: Optional[RateLimitRule]) -> datetime:
        """Calculate reset time for response headers."""
        if not rule:
            return datetime.utcnow() + timedelta(hours=1)

        user_key = f"{request.user_identifier}_{rule.rule_id}"
        usage = self._get_current_usage(user_key, rule.time_window_seconds)

        if usage:
            return max(usage) + timedelta(seconds=rule.time_window_seconds)
        else:
            return datetime.utcnow() + timedelta(seconds=rule.time_window_seconds)

    def _build_rate_limit_headers(self, remaining: int, reset_seconds: int) -> Dict[str, str]:
        """Build standard rate limit headers."""
        return {
            "X-RateLimit-Limit": str(remaining + 100),  # Approximate total limit
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(int(time.time()) + reset_seconds),
            "Retry-After": str(reset_seconds)
        }

    def _emit_telemetry(self, event_type: str, data: Dict[str, Any]) -> None:
        """Emit telemetry event."""
        try:
            self._telemetry.emit_event(
                event_type=event_type,
                payload=data
            )
        except Exception as e:
            self._logger.warning(f"Failed to emit telemetry: {e}")

    def cleanup_old_data(self, days: int = 7) -> None:
        """Clean up old data to prevent memory leaks."""
        cutoff_date = datetime.utcnow() - timedelta(days=days)

        # Clean up old violations
        self._violations = [v for v in self._violations if v.timestamp >= cutoff_date]

        # Clean up old request records
        while self._request_records and self._request_records[0].timestamp < cutoff_date:
            self._request_records.popleft()

        # Clean up inactive token buckets
        inactive_buckets = [
            bid for bid, bucket in self._token_buckets.items()
            if not bucket.is_active or (datetime.utcnow() - bucket.last_refill).days > days
        ]
        for bucket_id in inactive_buckets:
            del self._token_buckets[bucket_id]

        self._emit_telemetry("rate_limit_cleanup", {
            "cleanup_date": cutoff_date.isoformat(),
            "violations_removed": len(self._violations),
            "buckets_cleaned": len(inactive_buckets)
        })
