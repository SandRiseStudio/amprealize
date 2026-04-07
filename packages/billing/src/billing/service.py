"""
BillingService - Main orchestration layer for billing operations.

The BillingService coordinates between:
- BillingProvider: External payment processor (Stripe, mock, etc.)
- BillingHooks: Integration callbacks for logging, notifications, etc.
- UsageAggregator: Redis-based usage tracking (optional, for scale)

Usage:
    from billing import BillingService
    from billing.providers.mock import MockBillingProvider

    provider = MockBillingProvider()
    service = BillingService(provider)

    # Create customer and subscription
    customer = await service.create_customer(org_id="org_123", email="billing@acme.com")
    subscription = await service.create_subscription(customer.id, BillingPlan.STARTER)

    # Record usage
    await service.record_usage(subscription.id, UsageMetric.TOKENS, 1000)

    # Check limits
    if await service.check_limit(subscription.id, UsageMetric.TOKENS, 500):
        # Proceed with operation
        pass
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from billing.hooks import (
    BillingEvent,
    BillingEventType,
    BillingHooks,
    NoOpHooks,
)
from billing.models import (
    BillingPlan,
    BillingPortalSession,
    CancelSubscriptionRequest,
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
    SubscriptionStatus,
    UpdateCustomerRequest,
    UpdateSubscriptionRequest,
    UsageAggregate,
    UsageMetric,
    UsageSummary,
    WebhookEvent,
    WebhookEventResult,
    get_plan_limits,
)
from billing.providers.base import (
    BillingProvider,
    BillingProviderError,
    UsageLimitExceededError,
)


# Warning threshold for usage (e.g., warn at 80%)
USAGE_WARNING_THRESHOLD = 0.8


class BillingService:
    """High-level billing service for subscription and usage management.

    This service wraps a BillingProvider and adds:
    - Hook callbacks for integration with external systems
    - Usage limit checking and warnings
    - Convenience methods for common operations
    - Consistent error handling

    Attributes:
        provider: The billing provider implementation
        hooks: Hook callbacks for events
    """

    def __init__(
        self,
        provider: BillingProvider,
        hooks: Optional[BillingHooks] = None,
    ):
        """Initialize billing service.

        Args:
            provider: BillingProvider implementation (Stripe, mock, etc.)
            hooks: Optional hook callbacks for integration
        """
        self.provider = provider
        self.hooks = hooks or NoOpHooks()

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    async def _emit_event(
        self,
        event_type: BillingEventType,
        *,
        customer: Optional[Customer] = None,
        subscription: Optional[Subscription] = None,
        invoice: Optional[Invoice] = None,
        payment_method: Optional[PaymentMethod] = None,
        data: Optional[Dict[str, Any]] = None,
        previous_value: Optional[Any] = None,
        new_value: Optional[Any] = None,
        provider_event_id: Optional[str] = None,
    ) -> None:
        """Emit an event to hooks."""
        event = BillingEvent(
            type=event_type,
            customer_id=customer.id if customer else (
                subscription.customer_id if subscription else None
            ),
            subscription_id=subscription.id if subscription else None,
            invoice_id=invoice.id if invoice else None,
            payment_method_id=payment_method.id if payment_method else None,
            org_id=customer.org_id if customer else None,
            user_id=customer.user_id if customer else None,
            data=data or {},
            previous_value=previous_value,
            new_value=new_value,
            provider=self.provider.name,
            provider_event_id=provider_event_id,
        )

        # Call generic handler first
        await self.hooks.on_event(event)

        # Then call specific handler
        handler_map = {
            BillingEventType.CUSTOMER_CREATED: self.hooks.on_customer_created,
            BillingEventType.CUSTOMER_UPDATED: self.hooks.on_customer_updated,
            BillingEventType.CUSTOMER_DELETED: self.hooks.on_customer_deleted,
            BillingEventType.SUBSCRIPTION_CREATED: self.hooks.on_subscription_created,
            BillingEventType.SUBSCRIPTION_UPDATED: self.hooks.on_subscription_updated,
            BillingEventType.SUBSCRIPTION_CANCELED: self.hooks.on_subscription_canceled,
            BillingEventType.SUBSCRIPTION_REACTIVATED: self.hooks.on_subscription_reactivated,
            BillingEventType.SUBSCRIPTION_PLAN_CHANGED: self.hooks.on_subscription_plan_changed,
            BillingEventType.SUBSCRIPTION_TRIAL_ENDING: self.hooks.on_subscription_trial_ending,
            BillingEventType.SUBSCRIPTION_PAST_DUE: self.hooks.on_subscription_past_due,
            BillingEventType.PAYMENT_METHOD_ADDED: self.hooks.on_payment_method_added,
            BillingEventType.PAYMENT_METHOD_REMOVED: self.hooks.on_payment_method_removed,
            BillingEventType.PAYMENT_METHOD_DEFAULT_CHANGED: self.hooks.on_payment_method_default_changed,
            BillingEventType.PAYMENT_SUCCEEDED: self.hooks.on_payment_succeeded,
            BillingEventType.PAYMENT_FAILED: self.hooks.on_payment_failed,
            BillingEventType.INVOICE_CREATED: self.hooks.on_invoice_created,
            BillingEventType.INVOICE_PAID: self.hooks.on_invoice_paid,
            BillingEventType.INVOICE_PAYMENT_FAILED: self.hooks.on_invoice_payment_failed,
            BillingEventType.USAGE_RECORDED: self.hooks.on_usage_recorded,
            BillingEventType.USAGE_LIMIT_WARNING: self.hooks.on_usage_limit_warning,
            BillingEventType.USAGE_LIMIT_EXCEEDED: self.hooks.on_usage_limit_exceeded,
            BillingEventType.WEBHOOK_RECEIVED: self.hooks.on_webhook_received,
            BillingEventType.WEBHOOK_PROCESSED: self.hooks.on_webhook_processed,
            BillingEventType.WEBHOOK_FAILED: self.hooks.on_webhook_failed,
        }

        handler = handler_map.get(event_type)
        if handler:
            await handler(event)

    # =========================================================================
    # Customer Operations
    # =========================================================================

    async def create_customer(
        self,
        *,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
        email: str,
        name: Optional[str] = None,
        **kwargs: Any,
    ) -> Customer:
        """Create a new billing customer.

        Args:
            org_id: Organization ID (mutually exclusive with user_id)
            user_id: User ID (mutually exclusive with org_id)
            email: Billing email address
            name: Display name
            **kwargs: Additional customer fields (address, tax_id, etc.)

        Returns:
            Created Customer
        """
        request = CreateCustomerRequest(
            org_id=org_id,
            user_id=user_id,
            email=email,
            name=name,
            **kwargs,
        )

        customer = await self.provider.create_customer(request)

        await self._emit_event(
            BillingEventType.CUSTOMER_CREATED,
            customer=customer,
            data={"email": email},
        )

        return customer

    async def get_customer(self, customer_id: str) -> Optional[Customer]:
        """Get a customer by ID."""
        return await self.provider.get_customer(customer_id)

    async def get_or_create_customer(
        self,
        *,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
        email: str,
        **kwargs: Any,
    ) -> Customer:
        """Get existing customer or create a new one.

        Looks up customer by org_id or user_id first, creates if not found.
        """
        # Try to find existing customer
        if org_id:
            customer = await self.provider.get_customer_by_org(org_id)
            if customer:
                return customer
        elif user_id:
            customer = await self.provider.get_customer_by_user(user_id)
            if customer:
                return customer

        # Create new customer
        return await self.create_customer(
            org_id=org_id,
            user_id=user_id,
            email=email,
            **kwargs,
        )

    async def update_customer(
        self,
        customer_id: str,
        **kwargs: Any,
    ) -> Customer:
        """Update customer details."""
        request = UpdateCustomerRequest(**kwargs)
        customer = await self.provider.update_customer(customer_id, request)

        await self._emit_event(
            BillingEventType.CUSTOMER_UPDATED,
            customer=customer,
            data=kwargs,
        )

        return customer

    async def delete_customer(self, customer_id: str) -> bool:
        """Delete a customer."""
        customer = await self.provider.get_customer(customer_id)
        result = await self.provider.delete_customer(customer_id)

        if result and customer:
            await self._emit_event(
                BillingEventType.CUSTOMER_DELETED,
                customer=customer,
            )

        return result

    # =========================================================================
    # Subscription Operations
    # =========================================================================

    async def create_subscription(
        self,
        customer_id: str,
        plan: BillingPlan = BillingPlan.FREE,
        billing_interval: str = "monthly",
        trial_days: Optional[int] = None,
        **kwargs: Any,
    ) -> Subscription:
        """Create a subscription for a customer.

        Args:
            customer_id: Customer to subscribe
            plan: Billing plan tier
            billing_interval: 'monthly' or 'yearly'
            trial_days: Optional trial period
            **kwargs: Additional subscription metadata

        Returns:
            Created Subscription
        """
        request = CreateSubscriptionRequest(
            customer_id=customer_id,
            plan=plan,
            billing_interval=billing_interval,
            trial_days=trial_days,
            metadata=kwargs.get("metadata", {}),
        )

        subscription = await self.provider.create_subscription(request)
        customer = await self.provider.get_customer(customer_id)

        await self._emit_event(
            BillingEventType.SUBSCRIPTION_CREATED,
            customer=customer,
            subscription=subscription,
            data={
                "plan": plan.value,
                "billing_interval": billing_interval,
                "trial_days": trial_days,
            },
        )

        return subscription

    async def get_subscription(self, subscription_id: str) -> Optional[Subscription]:
        """Get a subscription by ID."""
        return await self.provider.get_subscription(subscription_id)

    async def get_active_subscription(self, customer_id: str) -> Optional[Subscription]:
        """Get the active subscription for a customer.

        Returns the most recent active subscription if multiple exist.
        """
        subscriptions = await self.provider.get_subscriptions_for_customer(
            customer_id,
            include_canceled=False,
        )

        # Return first active subscription
        for sub in subscriptions:
            if sub.is_active:
                return sub

        return None

    async def change_plan(
        self,
        subscription_id: str,
        new_plan: BillingPlan,
        billing_interval: Optional[str] = None,
    ) -> Subscription:
        """Change the plan for a subscription (upgrade/downgrade).

        Args:
            subscription_id: Subscription to modify
            new_plan: New billing plan
            billing_interval: Optionally change billing interval

        Returns:
            Updated Subscription
        """
        old_subscription = await self.provider.get_subscription(subscription_id)
        if not old_subscription:
            raise BillingProviderError(
                f"Subscription not found: {subscription_id}",
                code="subscription_not_found",
            )

        old_plan = old_subscription.plan

        request = UpdateSubscriptionRequest(
            plan=new_plan,
            billing_interval=billing_interval,
        )

        subscription = await self.provider.update_subscription(subscription_id, request)
        customer = await self.provider.get_customer(subscription.customer_id)

        await self._emit_event(
            BillingEventType.SUBSCRIPTION_PLAN_CHANGED,
            customer=customer,
            subscription=subscription,
            previous_value=old_plan.value,
            new_value=new_plan.value,
            data={
                "old_plan": old_plan.value,
                "new_plan": new_plan.value,
                "billing_interval": billing_interval or subscription.billing_interval,
            },
        )

        return subscription

    async def cancel_subscription(
        self,
        subscription_id: str,
        cancel_immediately: bool = False,
        reason: Optional[str] = None,
    ) -> Subscription:
        """Cancel a subscription.

        Args:
            subscription_id: Subscription to cancel
            cancel_immediately: If True, cancel now. If False, cancel at period end.
            reason: Optional cancellation reason

        Returns:
            Updated Subscription
        """
        subscription = await self.provider.cancel_subscription(
            subscription_id,
            cancel_immediately=cancel_immediately,
            reason=reason,
        )
        customer = await self.provider.get_customer(subscription.customer_id)

        await self._emit_event(
            BillingEventType.SUBSCRIPTION_CANCELED,
            customer=customer,
            subscription=subscription,
            data={
                "cancel_immediately": cancel_immediately,
                "reason": reason,
            },
        )

        return subscription

    async def reactivate_subscription(self, subscription_id: str) -> Subscription:
        """Reactivate a subscription scheduled for cancellation."""
        subscription = await self.provider.reactivate_subscription(subscription_id)
        customer = await self.provider.get_customer(subscription.customer_id)

        await self._emit_event(
            BillingEventType.SUBSCRIPTION_REACTIVATED,
            customer=customer,
            subscription=subscription,
        )

        return subscription

    # =========================================================================
    # Payment Method Operations
    # =========================================================================

    async def add_payment_method(
        self,
        customer_id: str,
        provider_payment_method_id: str,
        set_as_default: bool = True,
    ) -> PaymentMethod:
        """Add a payment method to a customer.

        The payment method should be created client-side (e.g., via Stripe Elements).
        """
        request = CreatePaymentMethodRequest(
            customer_id=customer_id,
            provider_payment_method_id=provider_payment_method_id,
            set_as_default=set_as_default,
        )

        payment_method = await self.provider.attach_payment_method(request)

        await self._emit_event(
            BillingEventType.PAYMENT_METHOD_ADDED,
            payment_method=payment_method,
            data={"set_as_default": set_as_default},
        )

        return payment_method

    async def get_payment_methods(self, customer_id: str) -> List[PaymentMethod]:
        """Get all payment methods for a customer."""
        return await self.provider.get_payment_methods(customer_id)

    async def set_default_payment_method(
        self,
        customer_id: str,
        payment_method_id: str,
    ) -> PaymentMethod:
        """Set a payment method as default."""
        payment_method = await self.provider.set_default_payment_method(
            customer_id,
            payment_method_id,
        )

        await self._emit_event(
            BillingEventType.PAYMENT_METHOD_DEFAULT_CHANGED,
            payment_method=payment_method,
        )

        return payment_method

    async def remove_payment_method(self, payment_method_id: str) -> bool:
        """Remove a payment method."""
        result = await self.provider.detach_payment_method(payment_method_id)

        if result:
            await self._emit_event(
                BillingEventType.PAYMENT_METHOD_REMOVED,
                data={"payment_method_id": payment_method_id},
            )

        return result

    # =========================================================================
    # Invoice Operations
    # =========================================================================

    async def get_invoices(
        self,
        customer_id: str,
        limit: int = 10,
    ) -> List[Invoice]:
        """Get invoices for a customer."""
        return await self.provider.get_invoices_for_customer(customer_id, limit=limit)

    async def get_upcoming_invoice(self, subscription_id: str) -> Optional[Invoice]:
        """Preview the next invoice for a subscription."""
        return await self.provider.get_upcoming_invoice(subscription_id)

    # =========================================================================
    # Usage Operations
    # =========================================================================

    async def record_usage(
        self,
        subscription_id: str,
        metric: UsageMetric,
        quantity: int,
        *,
        action_id: Optional[str] = None,
        run_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        check_limit: bool = True,
    ) -> None:
        """Record metered usage for a subscription.

        Args:
            subscription_id: Subscription to record usage for
            metric: Usage metric type
            quantity: Amount of usage
            action_id: Optional associated action ID
            run_id: Optional associated run ID
            idempotency_key: Optional key to prevent duplicates
            check_limit: Whether to check limits before recording

        Raises:
            UsageLimitExceededError: If limit would be exceeded
        """
        # Check current usage if requested
        if check_limit:
            current = await self.provider.get_usage(subscription_id, metric)
            if current.limit > 0:
                new_total = current.total_quantity + quantity

                # Check for exceeded
                if new_total > current.limit:
                    await self._emit_event(
                        BillingEventType.USAGE_LIMIT_EXCEEDED,
                        data={
                            "metric": metric.value,
                            "current": current.total_quantity,
                            "limit": current.limit,
                            "attempted": quantity,
                            "excess": new_total - current.limit,
                        },
                    )
                    raise UsageLimitExceededError(
                        f"Usage limit exceeded for {metric.value}",
                        metric=metric,
                        current=current.total_quantity,
                        limit=current.limit,
                    )

                # Check for warning threshold
                percentage = new_total / current.limit
                if percentage >= USAGE_WARNING_THRESHOLD and current.percentage_used < USAGE_WARNING_THRESHOLD * 100:
                    await self._emit_event(
                        BillingEventType.USAGE_LIMIT_WARNING,
                        data={
                            "metric": metric.value,
                            "current": new_total,
                            "limit": current.limit,
                            "percentage": percentage * 100,
                        },
                    )

        # Record the usage
        request = RecordUsageRequest(
            subscription_id=subscription_id,
            metric=metric,
            quantity=quantity,
            action_id=action_id,
            run_id=run_id,
            idempotency_key=idempotency_key,
        )

        await self.provider.record_usage(request)

        await self._emit_event(
            BillingEventType.USAGE_RECORDED,
            data={
                "metric": metric.value,
                "quantity": quantity,
                "action_id": action_id,
                "run_id": run_id,
            },
        )

    async def check_limit(
        self,
        subscription_id: str,
        metric: UsageMetric,
        quantity: int = 1,
    ) -> bool:
        """Check if usage is within limits.

        Args:
            subscription_id: Subscription to check
            metric: Usage metric type
            quantity: Amount of additional usage to check

        Returns:
            True if usage is within limits, False otherwise
        """
        current = await self.provider.get_usage(subscription_id, metric)

        if current.limit < 0:  # Unlimited
            return True

        return (current.total_quantity + quantity) <= current.limit

    async def get_usage(
        self,
        subscription_id: str,
        metric: UsageMetric,
    ) -> UsageAggregate:
        """Get current usage for a metric."""
        return await self.provider.get_usage(subscription_id, metric)

    async def get_usage_summary(self, subscription_id: str) -> UsageSummary:
        """Get complete usage summary for a subscription."""
        subscription = await self.provider.get_subscription(subscription_id)
        if not subscription:
            raise BillingProviderError(
                f"Subscription not found: {subscription_id}",
                code="subscription_not_found",
            )

        usage = await self.provider.get_all_usage(subscription_id)

        # Check for exceeded limits
        any_exceeded = False
        limits_approaching = []

        for metric, aggregate in usage.items():
            if aggregate.limit > 0:
                if aggregate.total_quantity > aggregate.limit:
                    any_exceeded = True
                elif aggregate.percentage_used >= USAGE_WARNING_THRESHOLD * 100:
                    limits_approaching.append(metric)

        return UsageSummary(
            subscription_id=subscription_id,
            customer_id=subscription.customer_id,
            plan=subscription.plan,
            period_start=subscription.current_period_start,
            period_end=subscription.current_period_end,
            usage=usage,
            any_limit_exceeded=any_exceeded,
            limits_approaching=limits_approaching,
        )

    # =========================================================================
    # Checkout & Portal Operations
    # =========================================================================

    async def create_checkout_session(
        self,
        *,
        plan: BillingPlan,
        success_url: str,
        cancel_url: str,
        customer_id: Optional[str] = None,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
        billing_interval: str = "monthly",
        trial_days: Optional[int] = None,
    ) -> CheckoutSession:
        """Create a hosted checkout session.

        Args:
            plan: Plan to subscribe to
            success_url: URL to redirect after success
            cancel_url: URL to redirect after cancel
            customer_id: Existing customer ID (optional)
            org_id: Organization ID for new customer
            user_id: User ID for new customer
            billing_interval: 'monthly' or 'yearly'
            trial_days: Optional trial period

        Returns:
            CheckoutSession with hosted URL
        """
        request = CreateCheckoutRequest(
            customer_id=customer_id,
            org_id=org_id,
            user_id=user_id,
            plan=plan,
            billing_interval=billing_interval,
            success_url=success_url,
            cancel_url=cancel_url,
            trial_days=trial_days,
        )

        return await self.provider.create_checkout_session(request)

    async def create_portal_session(
        self,
        customer_id: str,
        return_url: str,
    ) -> BillingPortalSession:
        """Create a customer billing portal session.

        The portal allows customers to:
        - View and pay invoices
        - Update payment methods
        - Change or cancel subscriptions

        Args:
            customer_id: Customer to create portal for
            return_url: URL to return to after portal

        Returns:
            BillingPortalSession with portal URL
        """
        request = CreatePortalSessionRequest(
            customer_id=customer_id,
            return_url=return_url,
        )

        return await self.provider.create_portal_session(request)

    # =========================================================================
    # Webhook Operations
    # =========================================================================

    async def handle_webhook(
        self,
        payload: bytes,
        signature: str,
    ) -> WebhookEventResult:
        """Handle an incoming webhook from the billing provider.

        This method:
        1. Verifies the webhook signature
        2. Parses the event
        3. Processes the event
        4. Emits hooks

        Args:
            payload: Raw webhook payload bytes
            signature: Webhook signature header

        Returns:
            WebhookEventResult indicating success/failure
        """
        await self._emit_event(
            BillingEventType.WEBHOOK_RECEIVED,
            data={"signature": signature[:20] + "..."},
        )

        try:
            # Verify and parse
            event = await self.provider.verify_webhook(payload, signature)

            # Process
            result = await self.provider.process_webhook(event)

            await self._emit_event(
                BillingEventType.WEBHOOK_PROCESSED,
                provider_event_id=event.provider_event_id,
                data={
                    "event_type": event.type.value,
                    "actions_taken": result.actions_taken,
                },
            )

            return result

        except Exception as e:
            await self._emit_event(
                BillingEventType.WEBHOOK_FAILED,
                data={
                    "error": str(e),
                },
            )
            raise

    # =========================================================================
    # Entitlement Checking
    # =========================================================================

    async def check_feature(
        self,
        subscription_id: str,
        feature: str,
    ) -> bool:
        """Check if a subscription has access to a feature.

        Args:
            subscription_id: Subscription to check
            feature: Feature name (e.g., 'sso_enabled', 'priority_support')

        Returns:
            True if feature is enabled, False otherwise
        """
        subscription = await self.provider.get_subscription(subscription_id)
        if not subscription or not subscription.is_active:
            return False

        limits = subscription.get_limits()
        return getattr(limits, feature, False)

    async def get_entitlements(self, subscription_id: str) -> Dict[str, Any]:
        """Get all entitlements for a subscription.

        Returns a dictionary of feature flags and limits.
        """
        subscription = await self.provider.get_subscription(subscription_id)
        if not subscription:
            return {}

        limits = subscription.get_limits()
        return {
            "plan": subscription.plan.value,
            "status": subscription.status.value,
            "is_active": subscription.is_active,
            "is_trialing": subscription.is_trialing,
            "limits": {
                "max_projects": limits.max_projects,
                "max_members": limits.max_members,
                "max_agents": limits.max_agents,
                "monthly_tokens": limits.monthly_tokens,
                "monthly_api_calls": limits.monthly_api_calls,
                "storage_bytes": limits.storage_bytes,
            },
            "features": {
                "sso_enabled": limits.sso_enabled,
                "custom_branding": limits.custom_branding,
                "priority_support": limits.priority_support,
                "audit_logs": limits.audit_logs,
                "dedicated_support": limits.dedicated_support,
            },
        }


__all__ = ["BillingService", "USAGE_WARNING_THRESHOLD"]
