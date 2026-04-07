# Amprealize Billing

Provider-agnostic billing and subscription management for Amprealize.

## Features

- **Provider-agnostic design**: Swap between Stripe, PayPal, or mock providers
- **Subscription lifecycle**: Create, upgrade, downgrade, cancel, reactivate
- **Metered billing**: Track token usage with Redis-backed counters for scale
- **Payment methods**: CRUD operations for customer payment methods
- **Invoice management**: List, retrieve, and download invoices
- **Plan feature gates**: Enforce limits based on subscription tier
- **Webhook handling**: Process provider events with idempotency

## Installation

```bash
# Core package
pip install amprealize-billing

# With Stripe provider
pip install amprealize-billing[stripe]

# With Redis for usage aggregation
pip install amprealize-billing[redis]

# All extras
pip install amprealize-billing[all]
```

## Quick Start

```python
from billing import BillingService, BillingPlan
from billing.providers.mock import MockProvider

# Initialize with mock provider for development
provider = MockProvider()
service = BillingService(provider=provider)

# Create a customer
customer = service.create_customer(
    org_id="org-123",
    email="billing@example.com",
    name="Acme Corp",
)

# Create a subscription
subscription = service.create_subscription(
    customer_id=customer.id,
    plan=BillingPlan.TEAM,
    trial_days=14,
)

# Record usage
service.record_usage(
    subscription_id=subscription.id,
    metric="tokens",
    quantity=1500,
)

# Check if within quota
is_allowed = service.check_quota(
    subscription_id=subscription.id,
    metric="tokens",
    requested=1000,
)
```

## Provider Implementation

### Using Stripe

```python
from billing import BillingService
from billing.providers.stripe import StripeProvider

provider = StripeProvider(api_key="sk_test_...")
service = BillingService(provider=provider)
```

### Creating a Custom Provider

```python
from billing.providers.base import BillingProvider

class CustomProvider(BillingProvider):
    def create_customer(self, request):
        # Your implementation
        pass

    # Implement other required methods...
```

## Subscription Plans

| Plan | Price | Projects | Members | Agents | Tokens/Month |
|------|-------|----------|---------|--------|--------------|
| FREE | $0 | 3 | 5 | 1 | 100K |
| STARTER | $29/mo | 10 | 15 | 3 | 500K |
| TEAM | $99/mo | Unlimited | 50 | 10 | 2M |
| ENTERPRISE | Custom | Unlimited | Unlimited | Unlimited | Custom |

## Integration with Amprealize

When using within the Amprealize platform, use the wrapper that integrates with
ActionService, MetricsService, and Raze logging:

```python
from amprealize.billing import BillingService

# Automatically wired with Amprealize services
service = BillingService(provider=provider)
```

## Webhook Handling

```python
from billing.webhooks import WebhookHandler
from billing.providers.stripe import StripeProvider

handler = WebhookHandler(provider=StripeProvider(...))

# In your FastAPI route
@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    signature = request.headers.get("Stripe-Signature")

    event = handler.verify_and_parse(
        payload=payload,
        signature=signature,
        webhook_secret="whsec_...",
    )

    result = handler.handle_event(event)
    return {"status": "ok", "event_id": event.id}
```

## License

Apache-2.0
