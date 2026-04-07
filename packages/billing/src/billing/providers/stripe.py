"""
Stripe billing provider stub.

This module provides the Stripe integration interface with NotImplementedError
stubs. The actual implementation should be added when Stripe integration is needed.

To implement Stripe integration:
1. Add stripe to dependencies: pip install billing[stripe]
2. Implement each method following Stripe API patterns
3. Configure with your Stripe API key and webhook secret

Example usage (when implemented):
    from billing.providers.stripe import StripeBillingProvider

    provider = StripeBillingProvider(
        api_key="sk_live_xxx",
        webhook_secret="whsec_xxx",
    )

    customer = await provider.create_customer(
        CreateCustomerRequest(org_id="org_123", email="billing@acme.com")
    )
"""

from typing import Any, Dict, List, Optional

from billing.models import (
    BillingPlan,
    BillingPortalSession,
    CheckoutSession,
    CreateCheckoutRequest,
    CreateCustomerRequest,
    CreatePaymentMethodRequest,
    CreatePortalSessionRequest,
    CreateSubscriptionRequest,
    Customer,
    Invoice,
    PaymentMethod,
    RecordUsageRequest,
    Subscription,
    UpdateCustomerRequest,
    UpdateSubscriptionRequest,
    UsageAggregate,
    UsageMetric,
    WebhookEvent,
    WebhookEventResult,
)
from billing.providers.base import BillingProvider


class StripeBillingProvider(BillingProvider):
    """Stripe implementation of BillingProvider.

    This is a stub implementation. All methods raise NotImplementedError
    until actual Stripe integration is implemented.

    To implement, you'll need:
    - stripe Python SDK (pip install stripe)
    - Stripe API key (sk_live_xxx or sk_test_xxx)
    - Webhook signing secret (whsec_xxx)
    - Price IDs for each plan configured in Stripe Dashboard

    Attributes:
        api_key: Stripe API key
        webhook_secret: Stripe webhook signing secret
        price_ids: Mapping of BillingPlan to Stripe price IDs
    """

    def __init__(
        self,
        api_key: str,
        webhook_secret: str,
        price_ids: Optional[Dict[BillingPlan, Dict[str, str]]] = None,
    ):
        """Initialize Stripe provider.

        Args:
            api_key: Stripe API key (sk_live_xxx or sk_test_xxx).
            webhook_secret: Stripe webhook signing secret (whsec_xxx).
            price_ids: Optional mapping of plan -> interval -> Stripe price ID.
                       Example: {BillingPlan.STARTER: {"monthly": "price_xxx"}}
        """
        self._api_key = api_key
        self._webhook_secret = webhook_secret
        self._price_ids = price_ids or {}

        # Validate we have stripe SDK available
        try:
            import stripe  # noqa: F401
        except ImportError:
            raise ImportError(
                "Stripe SDK not installed. Install with: pip install billing[stripe]"
            )

    @property
    def name(self) -> str:
        return "stripe"

    @property
    def is_test_mode(self) -> bool:
        return self._api_key.startswith("sk_test_")

    def get_price_id_for_plan(
        self,
        plan: BillingPlan,
        interval: str = "monthly",
    ) -> Optional[str]:
        """Get Stripe price ID for a plan."""
        plan_prices = self._price_ids.get(plan, {})
        return plan_prices.get(interval)

    # =========================================================================
    # Customer Operations
    # =========================================================================

    async def create_customer(self, request: CreateCustomerRequest) -> Customer:
        """Create a Stripe customer.

        TODO: Implement with:
            import stripe
            stripe.api_key = self._api_key

            stripe_customer = stripe.Customer.create(
                email=request.email,
                name=request.name,
                metadata={"org_id": request.org_id, "user_id": request.user_id},
                address={...} if request.address_line1 else None,
            )

            return Customer(
                provider_customer_id=stripe_customer.id,
                ...
            )
        """
        raise NotImplementedError(
            "Stripe customer creation not yet implemented. "
            "See docstring for implementation guidance."
        )

    async def get_customer(self, customer_id: str) -> Optional[Customer]:
        """Retrieve customer from local storage and optionally sync with Stripe."""
        raise NotImplementedError("Stripe get_customer not yet implemented")

    async def get_customer_by_provider_id(
        self,
        provider_customer_id: str,
    ) -> Optional[Customer]:
        """Retrieve customer by Stripe customer ID."""
        raise NotImplementedError("Stripe get_customer_by_provider_id not yet implemented")

    async def update_customer(
        self,
        customer_id: str,
        request: UpdateCustomerRequest,
    ) -> Customer:
        """Update customer in Stripe.

        TODO: Implement with:
            stripe.Customer.modify(
                provider_customer_id,
                email=request.email,
                name=request.name,
                ...
            )
        """
        raise NotImplementedError("Stripe update_customer not yet implemented")

    async def delete_customer(self, customer_id: str) -> bool:
        """Delete customer in Stripe.

        TODO: Implement with:
            stripe.Customer.delete(provider_customer_id)
        """
        raise NotImplementedError("Stripe delete_customer not yet implemented")

    # =========================================================================
    # Subscription Operations
    # =========================================================================

    async def create_subscription(
        self,
        request: CreateSubscriptionRequest,
    ) -> Subscription:
        """Create a Stripe subscription.

        TODO: Implement with:
            price_id = self.get_price_id_for_plan(request.plan, request.billing_interval)

            stripe_sub = stripe.Subscription.create(
                customer=provider_customer_id,
                items=[{"price": price_id}],
                trial_period_days=request.trial_days,
                metadata=request.metadata,
            )

            return Subscription(
                provider_subscription_id=stripe_sub.id,
                provider_price_id=price_id,
                status=_map_stripe_status(stripe_sub.status),
                ...
            )
        """
        raise NotImplementedError("Stripe create_subscription not yet implemented")

    async def get_subscription(self, subscription_id: str) -> Optional[Subscription]:
        """Retrieve subscription."""
        raise NotImplementedError("Stripe get_subscription not yet implemented")

    async def get_subscriptions_for_customer(
        self,
        customer_id: str,
        include_canceled: bool = False,
    ) -> List[Subscription]:
        """List subscriptions for a customer.

        TODO: Implement with:
            stripe.Subscription.list(customer=provider_customer_id)
        """
        raise NotImplementedError("Stripe get_subscriptions_for_customer not yet implemented")

    async def update_subscription(
        self,
        subscription_id: str,
        request: UpdateSubscriptionRequest,
    ) -> Subscription:
        """Update subscription in Stripe.

        TODO: Implement plan changes with proration handling.
        """
        raise NotImplementedError("Stripe update_subscription not yet implemented")

    async def cancel_subscription(
        self,
        subscription_id: str,
        cancel_immediately: bool = False,
        reason: Optional[str] = None,
    ) -> Subscription:
        """Cancel subscription in Stripe.

        TODO: Implement with:
            if cancel_immediately:
                stripe.Subscription.cancel(provider_subscription_id)
            else:
                stripe.Subscription.modify(
                    provider_subscription_id,
                    cancel_at_period_end=True,
                )
        """
        raise NotImplementedError("Stripe cancel_subscription not yet implemented")

    async def reactivate_subscription(self, subscription_id: str) -> Subscription:
        """Reactivate a subscription scheduled for cancellation."""
        raise NotImplementedError("Stripe reactivate_subscription not yet implemented")

    # =========================================================================
    # Payment Method Operations
    # =========================================================================

    async def attach_payment_method(
        self,
        request: CreatePaymentMethodRequest,
    ) -> PaymentMethod:
        """Attach a payment method to a Stripe customer.

        TODO: Implement with:
            stripe.PaymentMethod.attach(
                request.provider_payment_method_id,
                customer=provider_customer_id,
            )

            if request.set_as_default:
                stripe.Customer.modify(
                    provider_customer_id,
                    invoice_settings={"default_payment_method": pm_id},
                )
        """
        raise NotImplementedError("Stripe attach_payment_method not yet implemented")

    async def get_payment_methods(self, customer_id: str) -> List[PaymentMethod]:
        """List payment methods for a customer.

        TODO: Implement with:
            stripe.PaymentMethod.list(customer=provider_customer_id, type="card")
        """
        raise NotImplementedError("Stripe get_payment_methods not yet implemented")

    async def set_default_payment_method(
        self,
        customer_id: str,
        payment_method_id: str,
    ) -> PaymentMethod:
        """Set default payment method in Stripe."""
        raise NotImplementedError("Stripe set_default_payment_method not yet implemented")

    async def detach_payment_method(self, payment_method_id: str) -> bool:
        """Detach payment method from customer.

        TODO: Implement with:
            stripe.PaymentMethod.detach(provider_payment_method_id)
        """
        raise NotImplementedError("Stripe detach_payment_method not yet implemented")

    # =========================================================================
    # Invoice Operations
    # =========================================================================

    async def get_invoice(self, invoice_id: str) -> Optional[Invoice]:
        """Retrieve invoice."""
        raise NotImplementedError("Stripe get_invoice not yet implemented")

    async def get_invoices_for_customer(
        self,
        customer_id: str,
        limit: int = 10,
        starting_after: Optional[str] = None,
    ) -> List[Invoice]:
        """List invoices for a customer.

        TODO: Implement with:
            stripe.Invoice.list(
                customer=provider_customer_id,
                limit=limit,
                starting_after=starting_after,
            )
        """
        raise NotImplementedError("Stripe get_invoices_for_customer not yet implemented")

    async def get_upcoming_invoice(self, subscription_id: str) -> Optional[Invoice]:
        """Preview upcoming invoice.

        TODO: Implement with:
            stripe.Invoice.upcoming(subscription=provider_subscription_id)
        """
        raise NotImplementedError("Stripe get_upcoming_invoice not yet implemented")

    # =========================================================================
    # Usage Operations
    # =========================================================================

    async def record_usage(self, request: RecordUsageRequest) -> None:
        """Record metered usage in Stripe.

        For metered billing, you'll need:
        1. Subscription item ID for the metered price
        2. stripe.SubscriptionItem.create_usage_record()

        For hybrid approach (Redis + Stripe), aggregate locally then
        report to Stripe periodically.
        """
        raise NotImplementedError("Stripe record_usage not yet implemented")

    async def get_usage(
        self,
        subscription_id: str,
        metric: UsageMetric,
    ) -> UsageAggregate:
        """Get usage aggregate for a metric.

        TODO: Implement with:
            stripe.SubscriptionItem.list_usage_record_summaries(
                subscription_item_id
            )
        """
        raise NotImplementedError("Stripe get_usage not yet implemented")

    async def get_all_usage(
        self,
        subscription_id: str,
    ) -> Dict[UsageMetric, UsageAggregate]:
        """Get all usage aggregates."""
        raise NotImplementedError("Stripe get_all_usage not yet implemented")

    # =========================================================================
    # Checkout Operations
    # =========================================================================

    async def create_checkout_session(
        self,
        request: CreateCheckoutRequest,
    ) -> CheckoutSession:
        """Create a Stripe Checkout session.

        TODO: Implement with:
            price_id = self.get_price_id_for_plan(request.plan, request.billing_interval)

            session = stripe.checkout.Session.create(
                customer=provider_customer_id,  # or customer_email if new
                mode="subscription",
                line_items=[{"price": price_id, "quantity": 1}],
                success_url=request.success_url,
                cancel_url=request.cancel_url,
                subscription_data={"trial_period_days": request.trial_days},
            )

            return CheckoutSession(
                provider_session_id=session.id,
                url=session.url,
                ...
            )
        """
        raise NotImplementedError("Stripe create_checkout_session not yet implemented")

    async def get_checkout_session(self, session_id: str) -> Optional[CheckoutSession]:
        """Retrieve checkout session."""
        raise NotImplementedError("Stripe get_checkout_session not yet implemented")

    # =========================================================================
    # Portal Operations
    # =========================================================================

    async def create_portal_session(
        self,
        request: CreatePortalSessionRequest,
    ) -> BillingPortalSession:
        """Create a Stripe Customer Portal session.

        TODO: Implement with:
            session = stripe.billing_portal.Session.create(
                customer=provider_customer_id,
                return_url=request.return_url,
            )

            return BillingPortalSession(
                provider_session_id=session.id,
                url=session.url,
                ...
            )
        """
        raise NotImplementedError("Stripe create_portal_session not yet implemented")

    # =========================================================================
    # Webhook Operations
    # =========================================================================

    async def verify_webhook(
        self,
        payload: bytes,
        signature: str,
    ) -> WebhookEvent:
        """Verify and parse a Stripe webhook.

        TODO: Implement with:
            import stripe

            event = stripe.Webhook.construct_event(
                payload,
                signature,
                self._webhook_secret,
            )

            return WebhookEvent(
                provider="stripe",
                provider_event_id=event.id,
                type=_map_stripe_event_type(event.type),
                data=event.data.object,
            )
        """
        raise NotImplementedError("Stripe verify_webhook not yet implemented")

    async def process_webhook(self, event: WebhookEvent) -> WebhookEventResult:
        """Process a verified Stripe webhook.

        TODO: Implement handlers for:
        - customer.* events
        - subscription.* events
        - invoice.* events
        - payment_intent.* events
        - checkout.session.* events
        """
        raise NotImplementedError("Stripe process_webhook not yet implemented")


# =============================================================================
# Stripe Status Mapping Helpers (for implementation reference)
# =============================================================================

# Stripe subscription status -> our SubscriptionStatus
_STRIPE_STATUS_MAP = {
    "trialing": "trialing",
    "active": "active",
    "past_due": "past_due",
    "canceled": "canceled",
    "unpaid": "unpaid",
    "incomplete": "incomplete",
    "incomplete_expired": "incomplete_expired",
    "paused": "paused",
}

# Stripe event types -> our WebhookEventType
_STRIPE_EVENT_MAP = {
    "customer.created": "customer.created",
    "customer.updated": "customer.updated",
    "customer.deleted": "customer.deleted",
    "customer.subscription.created": "subscription.created",
    "customer.subscription.updated": "subscription.updated",
    "customer.subscription.deleted": "subscription.deleted",
    "customer.subscription.trial_will_end": "subscription.trial_will_end",
    "invoice.created": "invoice.created",
    "invoice.paid": "invoice.paid",
    "invoice.payment_failed": "invoice.payment_failed",
    "invoice.finalized": "invoice.finalized",
    "payment_intent.succeeded": "payment_intent.succeeded",
    "payment_intent.payment_failed": "payment_intent.failed",
    "payment_method.attached": "payment_method.attached",
    "payment_method.detached": "payment_method.detached",
    "checkout.session.completed": "checkout.session.completed",
    "checkout.session.expired": "checkout.session.expired",
}


__all__ = ["StripeBillingProvider"]
