"""
Billing providers for different payment processors.

Available Providers:
    - MockBillingProvider: In-memory mock for testing
    - StripeBillingProvider: Stripe integration (requires `billing[stripe]`)

Create custom providers by implementing the BillingProvider protocol.
"""

from billing.providers.base import BillingProvider

__all__ = ["BillingProvider"]
