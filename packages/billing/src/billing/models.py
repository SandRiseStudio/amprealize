"""
Billing models for provider-agnostic subscription management.

Defines all data models used across the billing system:
- Plans and subscription tiers with feature limits
- Customer and subscription entities
- Payment methods and invoices
- Usage tracking and aggregation

All models use Pydantic v2 with strict validation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


# =============================================================================
# Enums
# =============================================================================


class BillingPlan(str, Enum):
    """Subscription plan tiers.

    Each tier has associated limits and pricing defined in PLAN_LIMITS.
    """
    FREE = "free"
    STARTER = "starter"
    TEAM = "team"
    ENTERPRISE = "enterprise"


class SubscriptionStatus(str, Enum):
    """Subscription lifecycle status."""
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    UNPAID = "unpaid"
    INCOMPLETE = "incomplete"
    INCOMPLETE_EXPIRED = "incomplete_expired"
    PAUSED = "paused"


class PaymentMethodType(str, Enum):
    """Payment method types."""
    CARD = "card"
    BANK_ACCOUNT = "bank_account"
    SEPA_DEBIT = "sepa_debit"
    ACH_DEBIT = "ach_debit"
    PAYPAL = "paypal"
    LINK = "link"


class InvoiceStatus(str, Enum):
    """Invoice payment status."""
    DRAFT = "draft"
    OPEN = "open"
    PAID = "paid"
    VOID = "void"
    UNCOLLECTIBLE = "uncollectible"


class UsageMetric(str, Enum):
    """Tracked usage metrics for metered billing."""
    TOKENS = "tokens"
    API_CALLS = "api_calls"
    STORAGE_BYTES = "storage_bytes"
    COMPUTE_SECONDS = "compute_seconds"
    RUNS = "runs"
    AGENTS = "agents"
    PROJECTS = "projects"
    MEMBERS = "members"


class WebhookEventType(str, Enum):
    """Webhook event types from billing providers."""
    # Customer events
    CUSTOMER_CREATED = "customer.created"
    CUSTOMER_UPDATED = "customer.updated"
    CUSTOMER_DELETED = "customer.deleted"

    # Subscription events
    SUBSCRIPTION_CREATED = "subscription.created"
    SUBSCRIPTION_UPDATED = "subscription.updated"
    SUBSCRIPTION_DELETED = "subscription.deleted"
    SUBSCRIPTION_TRIAL_WILL_END = "subscription.trial_will_end"
    SUBSCRIPTION_PAST_DUE = "subscription.past_due"

    # Invoice events
    INVOICE_CREATED = "invoice.created"
    INVOICE_PAID = "invoice.paid"
    INVOICE_PAYMENT_FAILED = "invoice.payment_failed"
    INVOICE_FINALIZED = "invoice.finalized"

    # Payment events
    PAYMENT_INTENT_SUCCEEDED = "payment_intent.succeeded"
    PAYMENT_INTENT_FAILED = "payment_intent.failed"
    PAYMENT_METHOD_ATTACHED = "payment_method.attached"
    PAYMENT_METHOD_DETACHED = "payment_method.detached"

    # Checkout events
    CHECKOUT_SESSION_COMPLETED = "checkout.session.completed"
    CHECKOUT_SESSION_EXPIRED = "checkout.session.expired"


# =============================================================================
# Plan Configuration
# =============================================================================


class PlanLimits(BaseModel):
    """Resource limits for a subscription plan."""

    max_projects: int = Field(..., description="Maximum number of projects")
    max_members: int = Field(..., description="Maximum team members")
    max_agents: int = Field(..., description="Maximum active agents")
    monthly_tokens: int = Field(..., description="Monthly token allowance")
    monthly_api_calls: int = Field(..., description="Monthly API call limit")
    storage_bytes: int = Field(..., description="Storage limit in bytes")

    # Feature flags
    sso_enabled: bool = Field(default=False, description="SSO support")
    custom_branding: bool = Field(default=False, description="Custom branding")
    priority_support: bool = Field(default=False, description="Priority support")
    audit_logs: bool = Field(default=False, description="Audit log retention")
    dedicated_support: bool = Field(default=False, description="Dedicated success manager")


# Plan limits configuration
PLAN_LIMITS: Dict[BillingPlan, PlanLimits] = {
    BillingPlan.FREE: PlanLimits(
        max_projects=3,
        max_members=5,
        max_agents=1,
        monthly_tokens=100_000,
        monthly_api_calls=10_000,
        storage_bytes=1 * 1024 * 1024 * 1024,  # 1 GB
        sso_enabled=False,
        custom_branding=False,
        priority_support=False,
        audit_logs=False,
        dedicated_support=False,
    ),
    BillingPlan.STARTER: PlanLimits(
        max_projects=10,
        max_members=15,
        max_agents=3,
        monthly_tokens=500_000,
        monthly_api_calls=50_000,
        storage_bytes=10 * 1024 * 1024 * 1024,  # 10 GB
        sso_enabled=False,
        custom_branding=False,
        priority_support=False,
        audit_logs=True,
        dedicated_support=False,
    ),
    BillingPlan.TEAM: PlanLimits(
        max_projects=-1,  # Unlimited
        max_members=50,
        max_agents=10,
        monthly_tokens=2_000_000,
        monthly_api_calls=200_000,
        storage_bytes=100 * 1024 * 1024 * 1024,  # 100 GB
        sso_enabled=True,
        custom_branding=True,
        priority_support=True,
        audit_logs=True,
        dedicated_support=False,
    ),
    BillingPlan.ENTERPRISE: PlanLimits(
        max_projects=-1,  # Unlimited
        max_members=-1,   # Unlimited
        max_agents=-1,    # Unlimited
        monthly_tokens=-1,  # Unlimited (or custom)
        monthly_api_calls=-1,  # Unlimited
        storage_bytes=-1,  # Unlimited
        sso_enabled=True,
        custom_branding=True,
        priority_support=True,
        audit_logs=True,
        dedicated_support=True,
    ),
}


# Plan pricing in cents (USD)
PLAN_PRICING: Dict[BillingPlan, Dict[str, int]] = {
    BillingPlan.FREE: {
        "monthly": 0,
        "yearly": 0,
    },
    BillingPlan.STARTER: {
        "monthly": 2900,  # $29/month
        "yearly": 29000,  # $290/year (2 months free)
    },
    BillingPlan.TEAM: {
        "monthly": 9900,  # $99/month
        "yearly": 99000,  # $990/year (2 months free)
    },
    BillingPlan.ENTERPRISE: {
        "monthly": 0,  # Custom pricing
        "yearly": 0,
    },
}


def get_plan_limits(plan: BillingPlan) -> PlanLimits:
    """Get limits for a billing plan."""
    return PLAN_LIMITS[plan]


def get_plan_price(plan: BillingPlan, interval: str = "monthly") -> int:
    """Get price in cents for a billing plan."""
    return PLAN_PRICING.get(plan, {}).get(interval, 0)


# =============================================================================
# Base Models
# =============================================================================


def _generate_id(prefix: str) -> str:
    """Generate a prefixed unique ID."""
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class TimestampMixin(BaseModel):
    """Mixin for created_at/updated_at timestamps."""

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# Customer Models
# =============================================================================


class Customer(TimestampMixin):
    """A billable customer entity.

    Customers can be either organizations or individual users (XOR constraint).
    Maps to a customer record in the billing provider (e.g., Stripe Customer).
    """

    id: str = Field(default_factory=lambda: _generate_id("cus"))

    # Owner - exactly one must be set
    org_id: Optional[str] = Field(default=None, description="Organization ID if org-level billing")
    user_id: Optional[str] = Field(default=None, description="User ID if user-level billing")

    # Provider mapping
    provider_customer_id: Optional[str] = Field(
        default=None,
        description="External provider customer ID (e.g., Stripe cus_xxx)"
    )

    # Customer details
    email: str = Field(..., description="Billing email address")
    name: Optional[str] = Field(default=None, description="Customer display name")

    # Tax information
    tax_id: Optional[str] = Field(default=None, description="Tax ID (VAT, EIN, etc.)")
    tax_exempt: bool = Field(default=False, description="Tax exempt status")

    # Billing address
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = Field(default="US", description="ISO 3166-1 alpha-2 country code")

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_owner(self) -> "Customer":
        """Ensure exactly one of org_id or user_id is set."""
        if self.org_id and self.user_id:
            raise ValueError("Customer cannot have both org_id and user_id")
        if not self.org_id and not self.user_id:
            raise ValueError("Customer must have either org_id or user_id")
        return self

    class Config:
        from_attributes = True


class CreateCustomerRequest(BaseModel):
    """Request to create a new customer."""

    org_id: Optional[str] = None
    user_id: Optional[str] = None
    email: str
    name: Optional[str] = None
    tax_id: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: str = "US"
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_owner(self) -> "CreateCustomerRequest":
        """Ensure exactly one of org_id or user_id is set."""
        if self.org_id and self.user_id:
            raise ValueError("Cannot set both org_id and user_id")
        if not self.org_id and not self.user_id:
            raise ValueError("Must set either org_id or user_id")
        return self


class UpdateCustomerRequest(BaseModel):
    """Request to update customer details."""

    email: Optional[str] = None
    name: Optional[str] = None
    tax_id: Optional[str] = None
    tax_exempt: Optional[bool] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


# =============================================================================
# Subscription Models
# =============================================================================


class Subscription(TimestampMixin):
    """A subscription to a billing plan.

    Tracks the subscription lifecycle including trials, billing periods,
    and cancellation.
    """

    id: str = Field(default_factory=lambda: _generate_id("sub"))
    customer_id: str = Field(..., description="Customer who owns this subscription")

    # Provider mapping
    provider_subscription_id: Optional[str] = Field(
        default=None,
        description="External provider subscription ID (e.g., Stripe sub_xxx)"
    )
    provider_price_id: Optional[str] = Field(
        default=None,
        description="External provider price ID (e.g., Stripe price_xxx)"
    )

    # Plan details
    plan: BillingPlan = Field(default=BillingPlan.FREE)
    status: SubscriptionStatus = Field(default=SubscriptionStatus.ACTIVE)
    billing_interval: str = Field(default="monthly", description="monthly or yearly")

    # Pricing
    unit_amount: int = Field(default=0, description="Price in cents")
    currency: str = Field(default="usd", description="ISO 4217 currency code")

    # Billing period
    current_period_start: datetime = Field(default_factory=datetime.utcnow)
    current_period_end: datetime = Field(
        default_factory=lambda: datetime.utcnow() + timedelta(days=30)
    )

    # Trial
    trial_start: Optional[datetime] = None
    trial_end: Optional[datetime] = None

    # Cancellation
    cancel_at_period_end: bool = Field(default=False)
    canceled_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    cancellation_reason: Optional[str] = None

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        """Check if subscription allows access."""
        return self.status in (
            SubscriptionStatus.ACTIVE,
            SubscriptionStatus.TRIALING,
            SubscriptionStatus.PAST_DUE,  # Grace period
        )

    @property
    def is_trialing(self) -> bool:
        """Check if subscription is in trial period."""
        return self.status == SubscriptionStatus.TRIALING

    @property
    def days_until_renewal(self) -> int:
        """Days until next billing period."""
        delta = self.current_period_end - datetime.utcnow()
        return max(0, delta.days)

    def get_limits(self) -> PlanLimits:
        """Get the plan limits for this subscription."""
        return get_plan_limits(self.plan)

    class Config:
        from_attributes = True


class CreateSubscriptionRequest(BaseModel):
    """Request to create a new subscription."""

    customer_id: str
    plan: BillingPlan = BillingPlan.FREE
    billing_interval: str = "monthly"
    trial_days: Optional[int] = Field(default=None, ge=0, le=90)
    coupon_code: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UpdateSubscriptionRequest(BaseModel):
    """Request to update a subscription."""

    plan: Optional[BillingPlan] = None
    billing_interval: Optional[str] = None
    cancel_at_period_end: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = None


class CancelSubscriptionRequest(BaseModel):
    """Request to cancel a subscription."""

    cancel_immediately: bool = Field(
        default=False,
        description="If True, cancel immediately. If False, cancel at period end."
    )
    reason: Optional[str] = Field(default=None, max_length=500)
    feedback: Optional[str] = Field(default=None, max_length=2000)


# =============================================================================
# Payment Method Models
# =============================================================================


class CardDetails(BaseModel):
    """Credit/debit card details."""

    brand: str = Field(..., description="Card brand (visa, mastercard, etc.)")
    last4: str = Field(..., min_length=4, max_length=4)
    exp_month: int = Field(..., ge=1, le=12)
    exp_year: int = Field(..., ge=2024)
    funding: Optional[str] = Field(default=None, description="credit, debit, prepaid, unknown")
    country: Optional[str] = Field(default=None, description="Card country")


class BankAccountDetails(BaseModel):
    """Bank account details."""

    bank_name: str
    last4: str = Field(..., min_length=4, max_length=4)
    routing_number_last4: Optional[str] = None
    account_type: str = Field(default="checking", description="checking or savings")
    country: str = "US"


class PaymentMethod(TimestampMixin):
    """A payment method attached to a customer."""

    id: str = Field(default_factory=lambda: _generate_id("pm"))
    customer_id: str

    # Provider mapping
    provider_payment_method_id: Optional[str] = Field(
        default=None,
        description="External provider payment method ID"
    )

    type: PaymentMethodType
    is_default: bool = Field(default=False)

    # Type-specific details (only one populated based on type)
    card: Optional[CardDetails] = None
    bank_account: Optional[BankAccountDetails] = None

    # Billing details
    billing_name: Optional[str] = None
    billing_email: Optional[str] = None
    billing_phone: Optional[str] = None

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True


class CreatePaymentMethodRequest(BaseModel):
    """Request to attach a payment method."""

    customer_id: str
    provider_payment_method_id: str = Field(
        ...,
        description="Payment method ID from provider (created client-side)"
    )
    set_as_default: bool = Field(default=True)


# =============================================================================
# Invoice Models
# =============================================================================


class InvoiceLineItem(BaseModel):
    """A line item on an invoice."""

    id: str = Field(default_factory=lambda: _generate_id("ili"))
    description: str
    quantity: int = 1
    unit_amount: int = Field(..., description="Amount in cents")
    amount: int = Field(..., description="Total amount in cents (quantity * unit_amount)")
    currency: str = "usd"

    # For metered billing
    metric: Optional[UsageMetric] = None
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None


class Invoice(TimestampMixin):
    """An invoice for a billing period."""

    id: str = Field(default_factory=lambda: _generate_id("inv"))
    customer_id: str
    subscription_id: Optional[str] = None

    # Provider mapping
    provider_invoice_id: Optional[str] = None

    # Invoice details
    number: Optional[str] = Field(default=None, description="Invoice number for display")
    status: InvoiceStatus = InvoiceStatus.DRAFT
    currency: str = "usd"

    # Amounts (in cents)
    subtotal: int = 0
    tax: int = 0
    total: int = 0
    amount_due: int = 0
    amount_paid: int = 0
    amount_remaining: int = 0

    # Line items
    line_items: List[InvoiceLineItem] = Field(default_factory=list)

    # Billing period
    period_start: datetime = Field(default_factory=datetime.utcnow)
    period_end: datetime = Field(default_factory=lambda: datetime.utcnow() + timedelta(days=30))

    # Due date and payment
    due_date: Optional[datetime] = None
    paid_at: Optional[datetime] = None

    # URLs
    hosted_invoice_url: Optional[str] = None
    invoice_pdf_url: Optional[str] = None

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True


# =============================================================================
# Usage Models
# =============================================================================


class UsageRecord(TimestampMixin):
    """A single usage record for metered billing."""

    id: str = Field(default_factory=lambda: _generate_id("usg"))
    subscription_id: str

    # What was used
    metric: UsageMetric
    quantity: int = Field(..., ge=0, description="Usage quantity")

    # When it was used
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Context
    action_id: Optional[str] = Field(default=None, description="Associated action ID")
    run_id: Optional[str] = Field(default=None, description="Associated run ID")

    # Idempotency
    idempotency_key: Optional[str] = Field(
        default=None,
        description="Unique key to prevent duplicate recording"
    )

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True


class RecordUsageRequest(BaseModel):
    """Request to record usage."""

    subscription_id: str
    metric: UsageMetric
    quantity: int = Field(..., ge=1)
    timestamp: Optional[datetime] = None
    action_id: Optional[str] = None
    run_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UsageAggregate(BaseModel):
    """Aggregated usage for a metric over a time period."""

    subscription_id: str
    metric: UsageMetric

    # Period
    period_start: datetime
    period_end: datetime

    # Aggregated values
    total_quantity: int = 0
    record_count: int = 0

    # Limits
    limit: int = Field(default=-1, description="Limit for this metric (-1 = unlimited)")
    remaining: int = Field(default=-1, description="Remaining quota (-1 = unlimited)")
    percentage_used: float = Field(default=0.0, ge=0.0, le=100.0)

    # Timestamps
    first_usage_at: Optional[datetime] = None
    last_usage_at: Optional[datetime] = None


class UsageSummary(BaseModel):
    """Complete usage summary for a subscription."""

    subscription_id: str
    customer_id: str
    plan: BillingPlan

    # Current billing period
    period_start: datetime
    period_end: datetime

    # Usage by metric
    usage: Dict[UsageMetric, UsageAggregate] = Field(default_factory=dict)

    # Overall status
    any_limit_exceeded: bool = False
    limits_approaching: List[UsageMetric] = Field(default_factory=list)


# =============================================================================
# Webhook Models
# =============================================================================


class WebhookEvent(BaseModel):
    """A webhook event from a billing provider."""

    id: str = Field(default_factory=lambda: _generate_id("evt"))

    # Provider details
    provider: str = Field(..., description="Provider name (stripe, paypal, etc.)")
    provider_event_id: str = Field(..., description="Event ID from provider")

    # Event details
    type: WebhookEventType
    data: Dict[str, Any] = Field(default_factory=dict)

    # Processing
    processed: bool = False
    processed_at: Optional[datetime] = None
    error: Optional[str] = None

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        from_attributes = True


class WebhookEventResult(BaseModel):
    """Result of processing a webhook event."""

    event_id: str
    success: bool
    message: Optional[str] = None
    actions_taken: List[str] = Field(default_factory=list)


# =============================================================================
# Checkout Models
# =============================================================================


class CheckoutSession(BaseModel):
    """A checkout session for collecting payment."""

    id: str = Field(default_factory=lambda: _generate_id("cs"))
    customer_id: Optional[str] = None

    # Provider mapping
    provider_session_id: Optional[str] = None

    # Session details
    mode: str = Field(default="subscription", description="subscription, payment, setup")
    status: str = Field(default="open", description="open, complete, expired")

    # URLs
    success_url: str
    cancel_url: str
    url: Optional[str] = Field(default=None, description="Hosted checkout URL")

    # Plan
    plan: Optional[BillingPlan] = None
    billing_interval: str = "monthly"

    # Timestamps
    expires_at: datetime = Field(
        default_factory=lambda: datetime.utcnow() + timedelta(hours=24)
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CreateCheckoutRequest(BaseModel):
    """Request to create a checkout session."""

    customer_id: Optional[str] = None
    org_id: Optional[str] = None
    user_id: Optional[str] = None

    plan: BillingPlan
    billing_interval: str = "monthly"

    success_url: str
    cancel_url: str

    trial_days: Optional[int] = None
    coupon_code: Optional[str] = None

    metadata: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Portal Models
# =============================================================================


class BillingPortalSession(BaseModel):
    """A customer portal session for managing billing."""

    id: str = Field(default_factory=lambda: _generate_id("bps"))
    customer_id: str

    # Provider mapping
    provider_session_id: Optional[str] = None

    # URLs
    url: str = Field(..., description="Portal URL to redirect customer to")
    return_url: str = Field(..., description="URL to return to after portal")

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CreatePortalSessionRequest(BaseModel):
    """Request to create a billing portal session."""

    customer_id: str
    return_url: str


# =============================================================================
# Exports
# =============================================================================


__all__ = [
    # Enums
    "BillingPlan",
    "SubscriptionStatus",
    "PaymentMethodType",
    "InvoiceStatus",
    "UsageMetric",
    "WebhookEventType",
    # Plan config
    "PlanLimits",
    "PLAN_LIMITS",
    "PLAN_PRICING",
    "get_plan_limits",
    "get_plan_price",
    # Customer
    "Customer",
    "CreateCustomerRequest",
    "UpdateCustomerRequest",
    # Subscription
    "Subscription",
    "CreateSubscriptionRequest",
    "UpdateSubscriptionRequest",
    "CancelSubscriptionRequest",
    # Payment Method
    "CardDetails",
    "BankAccountDetails",
    "PaymentMethod",
    "CreatePaymentMethodRequest",
    # Invoice
    "InvoiceLineItem",
    "Invoice",
    # Usage
    "UsageRecord",
    "RecordUsageRequest",
    "UsageAggregate",
    "UsageSummary",
    # Webhook
    "WebhookEvent",
    "WebhookEventResult",
    # Checkout
    "CheckoutSession",
    "CreateCheckoutRequest",
    # Portal
    "BillingPortalSession",
    "CreatePortalSessionRequest",
]
