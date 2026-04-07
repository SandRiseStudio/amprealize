"""Amprealize Billing service wrapper - OSS Stub.

Full implementation in amprealize-enterprise.
Install amprealize-enterprise[billing] for Amprealize billing integration.
"""

try:
    from amprealize_enterprise.billing.service import (
        AmprealizeBillingService,
        AmprealizeBillingHooks,
    )
except ImportError:
    AmprealizeBillingService = None  # type: ignore[assignment,misc]
    AmprealizeBillingHooks = None  # type: ignore[assignment,misc]
