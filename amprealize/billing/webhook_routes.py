"""Billing webhook routes - OSS Stub.

Full implementation in amprealize-enterprise.
Install amprealize-enterprise[billing] for webhook integration.
"""

try:
    from amprealize_enterprise.billing.webhook_routes import (
        create_webhook_router,
        create_amprealize_webhook_router,
        WebhookResponse,
        WebhookStatusResponse,
    )
except ImportError:
    create_webhook_router = None  # type: ignore[assignment]
    create_amprealize_webhook_router = None  # type: ignore[assignment]
    WebhookResponse = None  # type: ignore[assignment,misc]
    WebhookStatusResponse = None  # type: ignore[assignment,misc]
