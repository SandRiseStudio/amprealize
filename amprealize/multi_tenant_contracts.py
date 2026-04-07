"""Data contracts for Multi-Tenant Support - tenant isolation and row-level security."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class TenantStatus(str, Enum):
    """Tenant status states."""
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"
    PENDING = "pending"


class SecurityLevel(str, Enum):
    """Security level for tenant data isolation."""
    BASIC = "basic"
    STANDARD = "standard"
    ENTERPRISE = "enterprise"
    GOVERNMENT = "government"


@dataclass
class Tenant:
    """Multi-tenant organization entity."""
    tenant_id: str
    name: str
    domain: str
    status: TenantStatus
    security_level: SecurityLevel
    created_at: datetime
    settings: Dict[str, Any]
    limits: Dict[str, Any]  # API rate limits, storage quotas, etc.
    billing_plan: str
    contact_email: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "name": self.name,
            "domain": self.domain,
            "status": self.status.value,
            "security_level": self.security_level.value,
            "created_at": self.created_at.isoformat(),
            "settings": self.settings,
            "limits": self.limits,
            "billing_plan": self.billing_plan,
            "contact_email": self.contact_email,
        }


@dataclass
class TenantUser:
    """User within a tenant context."""
    user_id: str
    tenant_id: str
    email: str
    role: str  # admin, user, viewer, etc.
    permissions: List[str]
    created_at: datetime
    last_login: Optional[datetime]
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "email": self.email,
            "role": self.role,
            "permissions": self.permissions,
            "created_at": self.created_at.isoformat(),
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "is_active": self.is_active,
        }


@dataclass
class RowLevelSecurityPolicy:
    """Row-level security policy for data isolation."""
    policy_id: str
    tenant_id: str
    table_name: str
    policy_name: str
    condition: str  # SQL condition for tenant isolation
    is_active: bool
    created_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "tenant_id": self.tenant_id,
            "table_name": self.table_name,
            "policy_name": self.policy_name,
            "condition": self.condition,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class TenantResource:
    """Resource usage tracking for tenant."""
    resource_id: str
    tenant_id: str
    resource_type: str  # api_calls, storage_bytes, compute_hours, etc.
    usage_amount: float
    limit_amount: float
    period_start: datetime
    period_end: datetime
    last_updated: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "tenant_id": self.tenant_id,
            "resource_type": self.resource_type,
            "usage_amount": self.usage_amount,
            "limit_amount": self.limit_amount,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "last_updated": self.last_updated.isoformat(),
        }


@dataclass
class CreateTenantRequest:
    """Request to create a new tenant."""
    name: str
    domain: str
    contact_email: str
    billing_plan: str
    security_level: SecurityLevel = SecurityLevel.STANDARD
    settings: Optional[Dict[str, Any]] = None
    limits: Optional[Dict[str, Any]] = None


@dataclass
class UpdateTenantRequest:
    """Request to update tenant settings."""
    tenant_id: str
    name: Optional[str] = None
    contact_email: Optional[str] = None
    billing_plan: Optional[str] = None
    security_level: Optional[SecurityLevel] = None
    settings: Optional[Dict[str, Any]] = None
    limits: Optional[Dict[str, Any]] = None
    status: Optional[TenantStatus] = None


@dataclass
class CreateUserRequest:
    """Request to create a tenant user."""
    tenant_id: str
    email: str
    role: str
    permissions: List[str]


@dataclass
class RowLevelSecurityPolicyRequest:
    """Request to create/update RLS policy."""
    tenant_id: str
    table_name: str
    policy_name: str
    condition: str
    is_active: bool = True


@dataclass
class ResourceUsageUpdateRequest:
    """Request to update resource usage."""
    tenant_id: str
    resource_type: str
    usage_amount: float


@dataclass
class TenantAuditLog:
    """Audit log for tenant activities."""
    log_id: str
    tenant_id: str
    user_id: str
    action: str
    resource_type: str
    resource_id: str
    details: Dict[str, Any]
    timestamp: datetime
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "log_id": self.log_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
        }


@dataclass
class TenantMetrics:
    """Metrics for tenant performance and usage."""
    tenant_id: str
    total_users: int
    active_users: int
    api_calls_today: int
    storage_used_gb: float
    storage_limit_gb: float
    last_activity: datetime
    security_score: float
    compliance_status: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "total_users": self.total_users,
            "active_users": self.active_users,
            "api_calls_today": self.api_calls_today,
            "storage_used_gb": self.storage_used_gb,
            "storage_limit_gb": self.storage_limit_gb,
            "last_activity": self.last_activity.isoformat(),
            "security_score": self.security_score,
            "compliance_status": self.compliance_status,
        }


@dataclass
class TenantQuota:
    """Tenant resource quotas and limits."""
    tenant_id: str
    quotas: Dict[str, float]  # resource_type -> limit
    current_usage: Dict[str, float]  # resource_type -> usage
    reset_period: str  # daily, weekly, monthly
    last_reset: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "quotas": self.quotas,
            "current_usage": self.current_usage,
            "reset_period": self.reset_period,
            "last_reset": self.last_reset.isoformat(),
        }

    def is_within_limit(self, resource_type: str, additional_usage: float = 0.0) -> bool:
        """Check if usage is within quota limit."""
        current = self.current_usage.get(resource_type, 0.0)
        limit = self.quotas.get(resource_type, float('inf'))
        return (current + additional_usage) <= limit

    def get_usage_percentage(self, resource_type: str) -> float:
        """Get usage as percentage of quota."""
        current = self.current_usage.get(resource_type, 0.0)
        limit = self.quotas.get(resource_type, 1.0)
        return (current / limit) * 100 if limit > 0 else 0.0
