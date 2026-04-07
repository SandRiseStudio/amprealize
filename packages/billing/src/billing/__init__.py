"""
Billing - Provider-agnostic subscription and usage management.

A standalone package for managing subscriptions, payments, and metered billing
across multiple billing providers (Stripe, PayPal, custom, etc.).

Quick Start:
    from billing import BillingService, BillingPlan
    from billing.providers.mock import MockBillingProvider

    provider = MockBillingProvider()
    service = BillingService(provider)

    # Create a customer
    customer = await service.create_customer(
        org_id="org_123",
        email="billing@acme.com"
    )

    # Create a subscription
    subscription = await service.create_subscription(
        customer_id=customer.id,
        plan=BillingPlan.STARTER
    )

    # Record usage
    await service.record_usage(
        subscription_id=subscription.id,
        metric=UsageMetric.TOKENS,
        quantity=1500
    )

For production use with Stripe:
    from billing.providers.stripe import StripeBillingProvider

    provider = StripeBillingProvider(
        api_key="sk_live_xxx",
        webhook_secret="whsec_xxx"
    )
    service = BillingService(provider)
"""

from billing.models import (
    # Enums
    BillingPlan,
    SubscriptionStatus,
    PaymentMethodType,
    InvoiceStatus,
    UsageMetric,
    WebhookEventType,
    # Plan config
    PlanLimits,
    PLAN_LIMITS,
    PLAN_PRICING,
    get_plan_limits,
    get_plan_price,
    # Customer
    Customer,
    CreateCustomerRequest,
    UpdateCustomerRequest,
    # Subscription
    Subscription,
    CreateSubscriptionRequest,
    UpdateSubscriptionRequest,
    CancelSubscriptionRequest,
    # Payment Method
    CardDetails,
    BankAccountDetails,
    PaymentMethod,
    CreatePaymentMethodRequest,
    # Invoice
    InvoiceLineItem,
    Invoice,
    # Usage
    UsageRecord,
    RecordUsageRequest,
    UsageAggregate,
    UsageSummary,
    # Webhook
    WebhookEvent,
    WebhookEventResult,
    # Checkout
    CheckoutSession,
    CreateCheckoutRequest,
    # Portal
    BillingPortalSession,
    CreatePortalSessionRequest,
)

# Service
from billing.service import BillingService

# Hooks
from billing.hooks import (
    BillingHooks,
    BillingEvent,
    BillingEventType,
    NoOpHooks,
)

# Providers
from billing.providers.base import (
    BillingProvider,
    BillingProviderError,
    UsageLimitExceededError,
)
from billing.providers.mock import MockBillingProvider
from billing.providers.stripe import StripeBillingProvider

# Webhooks
from billing.webhooks import (
    WebhookHandler,
    WebhookResult,
    WebhookHandlerStatus,
    create_webhook_handler,
)

__version__ = "0.1.0"

__all__ = [
    # Version
    "__version__",
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
    # Service
    "BillingService",
    # Hooks
    "BillingHooks",
    "BillingEvent",
    "BillingEventType",
    "NoOpHooks",
    # Providers
    "BillingProvider",
    "BillingProviderError",
    "UsageLimitExceededError",
    "MockBillingProvider",
    "StripeBillingProvider",
    # Webhooks
    "WebhookHandler",
    "WebhookResult",
    "WebhookHandlerStatus",
    "create_webhook_handler",
]
