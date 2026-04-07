"""MultiTenantService - tenant isolation and row-level security service."""

from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import logging
import uuid
import re

from .multi_tenant_contracts import (
    TenantStatus, SecurityLevel, Tenant, TenantUser, RowLevelSecurityPolicy,
    TenantResource, CreateTenantRequest, UpdateTenantRequest, CreateUserRequest,
    RowLevelSecurityPolicyRequest, ResourceUsageUpdateRequest, TenantAuditLog,
    TenantMetrics, TenantQuota
)
from .telemetry import TelemetryClient


class MultiTenantService:
    """Multi-tenant support service with isolation and security policies."""

    def __init__(self, telemetry: Optional[TelemetryClient] = None) -> None:
        """Initialize MultiTenantService."""
        self._telemetry = telemetry or TelemetryClient.noop()
        self._tenants: Dict[str, Tenant] = {}
        self._users: Dict[str, TenantUser] = {}
        self._policies: Dict[str, RowLevelSecurityPolicy] = {}
        self._resources: Dict[str, TenantResource] = {}
        self._audit_logs: List[TenantAuditLog] = []
        self._quotas: Dict[str, TenantQuota] = {}

        self._logger = logging.getLogger(__name__)

    def create_tenant(self, request: CreateTenantRequest) -> Tenant:
        """Create a new tenant with isolation policies."""
        # Validate domain uniqueness
        if self._domain_exists(request.domain):
            raise ValueError(f"Domain {request.domain} already exists")

        # Generate tenant ID
        tenant_id = str(uuid.uuid4())

        # Set default limits based on billing plan
        default_limits = self._get_default_limits(request.billing_plan, request.security_level)

        tenant = Tenant(
            tenant_id=tenant_id,
            name=request.name,
            domain=request.domain,
            status=TenantStatus.PENDING,
            security_level=request.security_level,
            created_at=datetime.utcnow(),
            settings=request.settings or {},
            limits=default_limits,
            billing_plan=request.billing_plan,
            contact_email=request.contact_email
        )

        self._tenants[tenant_id] = tenant

        # Create default RLS policies
        self._create_default_policies(tenant_id)

        # Initialize tenant quota
        quota = TenantQuota(
            tenant_id=tenant_id,
            quotas=default_limits.copy(),
            current_usage={resource: 0.0 for resource in default_limits.keys()},
            reset_period="monthly",
            last_reset=datetime.utcnow()
        )
        self._quotas[tenant_id] = quota

        self._emit_telemetry("tenant_created", {
            "tenant_id": tenant_id,
            "name": request.name,
            "domain": request.domain,
            "billing_plan": request.billing_plan,
            "security_level": request.security_level.value
        })

        return tenant

    def update_tenant(self, request: UpdateTenantRequest) -> Tenant:
        """Update tenant settings and status."""
        if request.tenant_id not in self._tenants:
            raise ValueError(f"Tenant {request.tenant_id} not found")

        tenant = self._tenants[request.tenant_id]

        # Update fields if provided
        if request.name is not None:
            tenant.name = request.name
        if request.contact_email is not None:
            tenant.contact_email = request.contact_email
        if request.billing_plan is not None:
            tenant.billing_plan = request.billing_plan
            # Update limits when plan changes
            tenant.limits = self._get_default_limits(request.billing_plan, tenant.security_level)
        if request.security_level is not None:
            tenant.security_level = request.security_level
        if request.settings is not None:
            tenant.settings.update(request.settings)
        if request.limits is not None:
            tenant.limits.update(request.limits)
        if request.status is not None:
            tenant.status = request.status

        self._emit_telemetry("tenant_updated", {
            "tenant_id": request.tenant_id,
            "updated_fields": [k for k, v in request.__dict__.items() if v is not None and k != 'tenant_id']
        })

        return tenant

    def create_user(self, request: CreateUserRequest) -> TenantUser:
        """Create a new user within a tenant."""
        if request.tenant_id not in self._tenants:
            raise ValueError(f"Tenant {request.tenant_id} not found")

        # Check if email already exists in this tenant
        for user in self._users.values():
            if user.tenant_id == request.tenant_id and user.email == request.email:
                raise ValueError(f"User with email {request.email} already exists in tenant")

        user_id = str(uuid.uuid4())
        user = TenantUser(
            user_id=user_id,
            tenant_id=request.tenant_id,
            email=request.email,
            role=request.role,
            permissions=request.permissions,
            created_at=datetime.utcnow(),
            last_login=None,
            is_active=True
        )

        self._users[user_id] = user

        self._log_audit(request.tenant_id, user_id, "user_created", "user", user_id, {
            "email": request.email,
            "role": request.role
        })

        return user

    def create_rls_policy(self, request: RowLevelSecurityPolicyRequest) -> RowLevelSecurityPolicy:
        """Create a row-level security policy for tenant isolation."""
        if request.tenant_id not in self._tenants:
            raise ValueError(f"Tenant {request.tenant_id} not found")

        policy_id = str(uuid.uuid4())
        policy = RowLevelSecurityPolicy(
            policy_id=policy_id,
            tenant_id=request.tenant_id,
            table_name=request.table_name,
            policy_name=request.policy_name,
            condition=request.condition,
            is_active=request.is_active,
            created_at=datetime.utcnow()
        )

        self._policies[policy_id] = policy

        self._emit_telemetry("rls_policy_created", {
            "policy_id": policy_id,
            "tenant_id": request.tenant_id,
            "table_name": request.table_name,
            "policy_name": request.policy_name
        })

        return policy

    def update_resource_usage(self, request: ResourceUsageUpdateRequest) -> bool:
        """Update resource usage for a tenant."""
        if request.tenant_id not in self._tenants:
            raise ValueError(f"Tenant {request.tenant_id} not found")

        tenant = self._tenants[request.tenant_id]

        # Find or create resource tracking
        resource_key = f"{request.tenant_id}_{request.resource_type}"
        if resource_key not in self._resources:
            # Create new resource tracking
            self._resources[resource_key] = TenantResource(
                resource_id=resource_key,
                tenant_id=request.tenant_id,
                resource_type=request.resource_type,
                usage_amount=0.0,
                limit_amount=tenant.limits.get(request.resource_type, 0.0),
                period_start=datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0),
                period_end=datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0) + timedelta(days=32),
                last_updated=datetime.utcnow()
            )

        resource = self._resources[resource_key]
        resource.usage_amount += request.usage_amount
        resource.last_updated = datetime.utcnow()

        # Check for quota violations
        quota = self._quotas.get(request.tenant_id)
        if quota and not quota.is_within_limit(request.resource_type, request.usage_amount):
            self._emit_telemetry("quota_exceeded", {
                "tenant_id": request.tenant_id,
                "resource_type": request.resource_type,
                "current_usage": quota.current_usage.get(request.resource_type, 0.0),
                "limit": quota.quotas.get(request.resource_type, 0.0)
            })
            return False

        # Update quota tracking
        if quota:
            quota.current_usage[request.resource_type] = resource.usage_amount

        return True

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        """Get tenant by ID."""
        return self._tenants.get(tenant_id)

    def get_tenant_by_domain(self, domain: str) -> Optional[Tenant]:
        """Get tenant by domain."""
        for tenant in self._tenants.values():
            if tenant.domain == domain:
                return tenant
        return None

    def list_tenants(self, status: Optional[TenantStatus] = None) -> List[Tenant]:
        """List tenants with optional status filter."""
        tenants = list(self._tenants.values())
        if status:
            tenants = [t for t in tenants if t.status == status]
        return tenants

    def get_user(self, user_id: str) -> Optional[TenantUser]:
        """Get user by ID."""
        return self._users.get(user_id)

    def get_users_by_tenant(self, tenant_id: str) -> List[TenantUser]:
        """Get all users for a tenant."""
        return [u for u in self._users.values() if u.tenant_id == tenant_id]

    def get_rls_policies(self, tenant_id: str, table_name: Optional[str] = None) -> List[RowLevelSecurityPolicy]:
        """Get RLS policies for a tenant."""
        policies = [p for p in self._policies.values() if p.tenant_id == tenant_id and p.is_active]
        if table_name:
            policies = [p for p in policies if p.table_name == table_name]
        return policies

    def get_tenant_quota(self, tenant_id: str) -> Optional[TenantQuota]:
        """Get tenant quota information."""
        return self._quotas.get(tenant_id)

    def get_tenant_metrics(self, tenant_id: str) -> Optional[TenantMetrics]:
        """Get comprehensive tenant metrics."""
        if tenant_id not in self._tenants:
            return None

        tenant = self._tenants[tenant_id]
        users = self.get_users_by_tenant(tenant_id)
        active_users = sum(1 for u in users if u.is_active)

        # Calculate API calls from resources
        api_calls = 0
        storage_used = 0.0

        for resource in self._resources.values():
            if resource.tenant_id == tenant_id:
                if resource.resource_type == "api_calls":
                    api_calls = int(resource.usage_amount)
                elif resource.resource_type == "storage_bytes":
                    storage_used = resource.usage_amount / (1024**3)  # Convert to GB

        storage_limit = tenant.limits.get("storage_bytes", 0.0) / (1024**3)  # Convert to GB

        # Calculate security score based on user activity and policy compliance
        security_score = self._calculate_security_score(tenant_id)

        return TenantMetrics(
            tenant_id=tenant_id,
            total_users=len(users),
            active_users=active_users,
            api_calls_today=api_calls,
            storage_used_gb=storage_used,
            storage_limit_gb=storage_limit,
            last_activity=max([u.last_login for u in users if u.last_login] or [tenant.created_at]),
            security_score=security_score,
            compliance_status="compliant" if security_score >= 0.8 else "needs_attention"
        )

    def suspend_tenant(self, tenant_id: str, reason: str) -> bool:
        """Suspend a tenant (emergency use)."""
        if tenant_id not in self._tenants:
            return False

        tenant = self._tenants[tenant_id]
        tenant.status = TenantStatus.SUSPENDED

        self._log_audit(tenant_id, "system", "tenant_suspended", "tenant", tenant_id, {
            "reason": reason,
            "suspended_at": datetime.utcnow().isoformat()
        })

        self._emit_telemetry("tenant_suspended", {
            "tenant_id": tenant_id,
            "reason": reason
        })

        return True

    def reactivate_tenant(self, tenant_id: str) -> bool:
        """Reactivate a suspended tenant."""
        if tenant_id not in self._tenants:
            return False

        tenant = self._tenants[tenant_id]
        tenant.status = TenantStatus.ACTIVE

        self._log_audit(tenant_id, "system", "tenant_reactivated", "tenant", tenant_id, {
            "reactivated_at": datetime.utcnow().isoformat()
        })

        self._emit_telemetry("tenant_reactivated", {
            "tenant_id": tenant_id
        })

        return True

    def get_audit_logs(self, tenant_id: str, limit: int = 100) -> List[TenantAuditLog]:
        """Get audit logs for a tenant."""
        logs = [log for log in self._audit_logs if log.tenant_id == tenant_id]
        return sorted(logs, key=lambda x: x.timestamp, reverse=True)[:limit]

    def _domain_exists(self, domain: str) -> bool:
        """Check if domain already exists."""
        return any(tenant.domain == domain for tenant in self._tenants.values())

    def _get_default_limits(self, billing_plan: str, security_level: SecurityLevel) -> Dict[str, float]:
        """Get default resource limits based on plan and security level."""
        base_limits = {
            "api_calls": 10000 if billing_plan == "basic" else 100000 if billing_plan == "professional" else 1000000,
            "storage_bytes": 10 * 1024**3 if billing_plan == "basic" else 100 * 1024**3 if billing_plan == "professional" else 1024 * 1024**3,
            "concurrent_users": 5 if billing_plan == "basic" else 50 if billing_plan == "professional" else 500,
            "retention_days": 30 if billing_plan == "basic" else 90 if billing_plan == "professional" else 365
        }

        # Adjust for security level
        if security_level == SecurityLevel.GOVERNMENT:
            base_limits["api_calls"] *= 0.5  # Reduced limits for higher security
            base_limits["retention_days"] = 2555  # 7 years for government

        return base_limits

    def _create_default_policies(self, tenant_id: str) -> None:
        """Create default RLS policies for a new tenant."""
        default_tables = ["behaviors", "workflows", "runs", "compliance_checklists"]

        for table in default_tables:
            condition = f"tenant_id = '{tenant_id}'"
            policy = RowLevelSecurityPolicy(
                policy_id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                table_name=table,
                policy_name=f"tenant_isolation_{table}",
                condition=condition,
                is_active=True,
                created_at=datetime.utcnow()
            )
            self._policies[policy.policy_id] = policy

    def _calculate_security_score(self, tenant_id: str) -> float:
        """Calculate security score for tenant based on various factors."""
        users = self.get_users_by_tenant(tenant_id)
        if not users:
            return 0.5

        # Base score
        score = 0.3

        # User security factors
        active_users = sum(1 for u in users if u.is_active)
        score += min(0.2, active_users * 0.05)  # Reward having active users

        # Recent activity factor
        recent_logins = sum(1 for u in users if u.last_login and
                          (datetime.utcnow() - u.last_login).days <= 30)
        score += min(0.2, recent_logins * 0.1)  # Reward recent activity

        # Policy compliance
        policies = self.get_rls_policies(tenant_id)
        score += min(0.3, len(policies) * 0.1)  # Reward having RLS policies

        return min(1.0, score)

    def _log_audit(self, tenant_id: str, user_id: str, action: str,
                   resource_type: str, resource_id: str, details: Dict[str, Any]) -> None:
        """Log an audit event."""
        log_entry = TenantAuditLog(
            log_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            timestamp=datetime.utcnow()
        )
        self._audit_logs.append(log_entry)

    def _emit_telemetry(self, event_type: str, data: Dict[str, Any]) -> None:
        """Emit telemetry event."""
        try:
            self._telemetry.emit_event(
                event_type=event_type,
                payload=data
            )
        except Exception as e:
            self._logger.warning(f"Failed to emit telemetry: {e}")

    def get_tenant_statistics(self) -> Dict[str, Any]:
        """Get overall tenant statistics."""
        total_tenants = len(self._tenants)
        active_tenants = len([t for t in self._tenants.values() if t.status == TenantStatus.ACTIVE])
        total_users = len(self._users)
        total_policies = len(self._policies)

        # Resource usage totals
        total_api_calls = sum(r.usage_amount for r in self._resources.values() if r.resource_type == "api_calls")
        total_storage = sum(r.usage_amount for r in self._resources.values() if r.resource_type == "storage_bytes")

        return {
            "total_tenants": total_tenants,
            "active_tenants": active_tenants,
            "total_users": total_users,
            "total_policies": total_policies,
            "total_api_calls": int(total_api_calls),
            "total_storage_gb": total_storage / (1024**3),
            "suspension_rate": (total_tenants - active_tenants) / total_tenants if total_tenants > 0 else 0
        }
