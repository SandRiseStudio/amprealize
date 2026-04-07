"""Billing API routes - OSS Stub.

Full implementation in amprealize-enterprise.
Install amprealize-enterprise[billing] for billing API routes.
"""

try:
    from amprealize_enterprise.billing.api import (
        create_billing_router,
        CreateCustomerRequest,
        UpdateCustomerRequest,
        CustomerResponse,
        CreateSubscriptionRequest,
        UpdateSubscriptionRequest,
        SubscriptionResponse,
        RecordUsageRequest,
        UsageResponse,
        UsageSummaryResponse,
        InvoiceResponse,
        PlanResponse,
        LimitCheckResponse,
    )
except ImportError:
    create_billing_router = None  # type: ignore[assignment]
