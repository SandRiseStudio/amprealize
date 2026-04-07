"""
Billing hooks for integration with external systems.

Hooks allow the billing package to remain standalone while enabling
integration with amprealize services (ActionService, ComplianceService, etc.)
without introducing dependencies.

Usage:
    from billing.hooks import BillingHooks, BillingEvent

    class AmprealizeBillingHooks(BillingHooks):
        async def on_subscription_created(self, event: BillingEvent) -> None:
            # Log to ActionService
            await action_service.record({
                "type": "billing.subscription.created",
                "data": event.data,
            })

    hooks = AmprealizeBillingHooks()
    service = BillingService(provider, hooks=hooks)
"""

from abc import ABC
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Union

from billing.models import (
    BillingPlan,
    Customer,
    Invoice,
    PaymentMethod,
    Subscription,
    SubscriptionStatus,
    UsageAggregate,
    UsageMetric,
    UsageRecord,
    WebhookEvent,
)


class BillingEventType(str, Enum):
    """Types of billing events that hooks can receive."""

    # Customer events
    CUSTOMER_CREATED = "billing.customer.created"
    CUSTOMER_UPDATED = "billing.customer.updated"
    CUSTOMER_DELETED = "billing.customer.deleted"

    # Subscription events
    SUBSCRIPTION_CREATED = "billing.subscription.created"
    SUBSCRIPTION_UPDATED = "billing.subscription.updated"
    SUBSCRIPTION_CANCELED = "billing.subscription.canceled"
    SUBSCRIPTION_REACTIVATED = "billing.subscription.reactivated"
    SUBSCRIPTION_PLAN_CHANGED = "billing.subscription.plan_changed"
    SUBSCRIPTION_TRIAL_ENDING = "billing.subscription.trial_ending"
    SUBSCRIPTION_PAST_DUE = "billing.subscription.past_due"

    # Payment events
    PAYMENT_METHOD_ADDED = "billing.payment_method.added"
    PAYMENT_METHOD_REMOVED = "billing.payment_method.removed"
    PAYMENT_METHOD_DEFAULT_CHANGED = "billing.payment_method.default_changed"
    PAYMENT_SUCCEEDED = "billing.payment.succeeded"
    PAYMENT_FAILED = "billing.payment.failed"

    # Invoice events
    INVOICE_CREATED = "billing.invoice.created"
    INVOICE_PAID = "billing.invoice.paid"
    INVOICE_PAYMENT_FAILED = "billing.invoice.payment_failed"

    # Usage events
    USAGE_RECORDED = "billing.usage.recorded"
    USAGE_LIMIT_WARNING = "billing.usage.limit_warning"
    USAGE_LIMIT_EXCEEDED = "billing.usage.limit_exceeded"

    # Webhook events
    WEBHOOK_RECEIVED = "billing.webhook.received"
    WEBHOOK_PROCESSED = "billing.webhook.processed"
    WEBHOOK_FAILED = "billing.webhook.failed"


@dataclass
class BillingEvent:
    """A billing event to be processed by hooks.

    Events are emitted by the BillingService and delivered to registered hooks.
    They provide structured data about billing operations for audit logging,
    notifications, and integration purposes.
    """

    type: BillingEventType
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Entity references
    customer_id: Optional[str] = None
    subscription_id: Optional[str] = None
    invoice_id: Optional[str] = None
    payment_method_id: Optional[str] = None

    # Organization/user context
    org_id: Optional[str] = None
    user_id: Optional[str] = None

    # Event-specific data
    data: Dict[str, Any] = field(default_factory=dict)

    # Before/after for change events
    previous_value: Optional[Any] = None
    new_value: Optional[Any] = None

    # Metadata
    provider: Optional[str] = None
    provider_event_id: Optional[str] = None
    idempotency_key: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary for serialization."""
        return {
            "type": self.type.value,
            "timestamp": self.timestamp.isoformat(),
            "customer_id": self.customer_id,
            "subscription_id": self.subscription_id,
            "invoice_id": self.invoice_id,
            "payment_method_id": self.payment_method_id,
            "org_id": self.org_id,
            "user_id": self.user_id,
            "data": self.data,
            "previous_value": self.previous_value,
            "new_value": self.new_value,
            "provider": self.provider,
            "provider_event_id": self.provider_event_id,
            "idempotency_key": self.idempotency_key,
        }


# Type alias for async hook functions
HookFn = Callable[[BillingEvent], Coroutine[Any, Any, None]]


class BillingHooks(ABC):
    """Abstract base class for billing hooks.

    Implement this class to integrate billing events with your application.
    All methods have default no-op implementations, so you only need to
    override the hooks you care about.

    Example:
        class MyBillingHooks(BillingHooks):
            def __init__(self, action_service, notification_service):
                self.action_service = action_service
                self.notification_service = notification_service

            async def on_subscription_created(self, event: BillingEvent) -> None:
                # Log to audit trail
                await self.action_service.record(event.to_dict())

                # Send welcome email
                await self.notification_service.send_email(
                    event.data.get("email"),
                    template="welcome",
                )
    """

    # =========================================================================
    # Customer Hooks
    # =========================================================================

    async def on_customer_created(self, event: BillingEvent) -> None:
        """Called when a new customer is created."""
        pass

    async def on_customer_updated(self, event: BillingEvent) -> None:
        """Called when customer details are updated."""
        pass

    async def on_customer_deleted(self, event: BillingEvent) -> None:
        """Called when a customer is deleted."""
        pass

    # =========================================================================
    # Subscription Hooks
    # =========================================================================

    async def on_subscription_created(self, event: BillingEvent) -> None:
        """Called when a new subscription is created."""
        pass

    async def on_subscription_updated(self, event: BillingEvent) -> None:
        """Called when subscription details change."""
        pass

    async def on_subscription_canceled(self, event: BillingEvent) -> None:
        """Called when a subscription is canceled."""
        pass

    async def on_subscription_reactivated(self, event: BillingEvent) -> None:
        """Called when a canceled subscription is reactivated."""
        pass

    async def on_subscription_plan_changed(self, event: BillingEvent) -> None:
        """Called when subscription plan is upgraded/downgraded.

        event.previous_value contains the old plan.
        event.new_value contains the new plan.
        """
        pass

    async def on_subscription_trial_ending(self, event: BillingEvent) -> None:
        """Called when a trial period is about to end (typically 3 days before)."""
        pass

    async def on_subscription_past_due(self, event: BillingEvent) -> None:
        """Called when a subscription becomes past due."""
        pass

    # =========================================================================
    # Payment Method Hooks
    # =========================================================================

    async def on_payment_method_added(self, event: BillingEvent) -> None:
        """Called when a payment method is attached to a customer."""
        pass

    async def on_payment_method_removed(self, event: BillingEvent) -> None:
        """Called when a payment method is detached."""
        pass

    async def on_payment_method_default_changed(self, event: BillingEvent) -> None:
        """Called when the default payment method changes."""
        pass

    # =========================================================================
    # Payment Hooks
    # =========================================================================

    async def on_payment_succeeded(self, event: BillingEvent) -> None:
        """Called when a payment succeeds."""
        pass

    async def on_payment_failed(self, event: BillingEvent) -> None:
        """Called when a payment fails.

        Use this to trigger dunning flows, send notifications, etc.
        """
        pass

    # =========================================================================
    # Invoice Hooks
    # =========================================================================

    async def on_invoice_created(self, event: BillingEvent) -> None:
        """Called when an invoice is created."""
        pass

    async def on_invoice_paid(self, event: BillingEvent) -> None:
        """Called when an invoice is paid."""
        pass

    async def on_invoice_payment_failed(self, event: BillingEvent) -> None:
        """Called when invoice payment fails."""
        pass

    # =========================================================================
    # Usage Hooks
    # =========================================================================

    async def on_usage_recorded(self, event: BillingEvent) -> None:
        """Called when usage is recorded.

        Note: For high-volume usage, consider batching or sampling
        to avoid overwhelming downstream systems.
        """
        pass

    async def on_usage_limit_warning(self, event: BillingEvent) -> None:
        """Called when usage approaches a limit (e.g., 80% of quota).

        event.data contains:
            - metric: The usage metric
            - current: Current usage
            - limit: Usage limit
            - percentage: Percentage of limit used
        """
        pass

    async def on_usage_limit_exceeded(self, event: BillingEvent) -> None:
        """Called when a usage limit is exceeded.

        event.data contains:
            - metric: The usage metric
            - current: Current usage
            - limit: Usage limit
            - excess: Amount over limit
        """
        pass

    # =========================================================================
    # Webhook Hooks
    # =========================================================================

    async def on_webhook_received(self, event: BillingEvent) -> None:
        """Called when a webhook is received from a provider.

        Useful for logging all incoming webhooks for debugging.
        """
        pass

    async def on_webhook_processed(self, event: BillingEvent) -> None:
        """Called after a webhook is successfully processed."""
        pass

    async def on_webhook_failed(self, event: BillingEvent) -> None:
        """Called when webhook processing fails.

        event.data contains:
            - error: Error message
            - webhook_type: Original webhook type
        """
        pass

    # =========================================================================
    # Generic Event Handler
    # =========================================================================

    async def on_event(self, event: BillingEvent) -> None:
        """Called for all events before specific handlers.

        Override this for centralized event processing (e.g., logging all events).
        """
        pass


class CompositeHooks(BillingHooks):
    """Combines multiple hook implementations.

    Use this to compose different hook handlers together.

    Example:
        hooks = CompositeHooks([
            LoggingHooks(logger),
            NotificationHooks(email_service),
            AnalyticsHooks(analytics),
        ])

        service = BillingService(provider, hooks=hooks)
    """

    def __init__(self, hooks: List[BillingHooks]):
        self._hooks = hooks

    async def _call_all(self, method_name: str, event: BillingEvent) -> None:
        """Call a method on all registered hooks."""
        for hook in self._hooks:
            method = getattr(hook, method_name, None)
            if method:
                try:
                    await method(event)
                except Exception:
                    # Log but don't fail on hook errors
                    pass

    async def on_event(self, event: BillingEvent) -> None:
        await self._call_all("on_event", event)

    # Customer hooks
    async def on_customer_created(self, event: BillingEvent) -> None:
        await self._call_all("on_customer_created", event)

    async def on_customer_updated(self, event: BillingEvent) -> None:
        await self._call_all("on_customer_updated", event)

    async def on_customer_deleted(self, event: BillingEvent) -> None:
        await self._call_all("on_customer_deleted", event)

    # Subscription hooks
    async def on_subscription_created(self, event: BillingEvent) -> None:
        await self._call_all("on_subscription_created", event)

    async def on_subscription_updated(self, event: BillingEvent) -> None:
        await self._call_all("on_subscription_updated", event)

    async def on_subscription_canceled(self, event: BillingEvent) -> None:
        await self._call_all("on_subscription_canceled", event)

    async def on_subscription_reactivated(self, event: BillingEvent) -> None:
        await self._call_all("on_subscription_reactivated", event)

    async def on_subscription_plan_changed(self, event: BillingEvent) -> None:
        await self._call_all("on_subscription_plan_changed", event)

    async def on_subscription_trial_ending(self, event: BillingEvent) -> None:
        await self._call_all("on_subscription_trial_ending", event)

    async def on_subscription_past_due(self, event: BillingEvent) -> None:
        await self._call_all("on_subscription_past_due", event)

    # Payment method hooks
    async def on_payment_method_added(self, event: BillingEvent) -> None:
        await self._call_all("on_payment_method_added", event)

    async def on_payment_method_removed(self, event: BillingEvent) -> None:
        await self._call_all("on_payment_method_removed", event)

    async def on_payment_method_default_changed(self, event: BillingEvent) -> None:
        await self._call_all("on_payment_method_default_changed", event)

    # Payment hooks
    async def on_payment_succeeded(self, event: BillingEvent) -> None:
        await self._call_all("on_payment_succeeded", event)

    async def on_payment_failed(self, event: BillingEvent) -> None:
        await self._call_all("on_payment_failed", event)

    # Invoice hooks
    async def on_invoice_created(self, event: BillingEvent) -> None:
        await self._call_all("on_invoice_created", event)

    async def on_invoice_paid(self, event: BillingEvent) -> None:
        await self._call_all("on_invoice_paid", event)

    async def on_invoice_payment_failed(self, event: BillingEvent) -> None:
        await self._call_all("on_invoice_payment_failed", event)

    # Usage hooks
    async def on_usage_recorded(self, event: BillingEvent) -> None:
        await self._call_all("on_usage_recorded", event)

    async def on_usage_limit_warning(self, event: BillingEvent) -> None:
        await self._call_all("on_usage_limit_warning", event)

    async def on_usage_limit_exceeded(self, event: BillingEvent) -> None:
        await self._call_all("on_usage_limit_exceeded", event)

    # Webhook hooks
    async def on_webhook_received(self, event: BillingEvent) -> None:
        await self._call_all("on_webhook_received", event)

    async def on_webhook_processed(self, event: BillingEvent) -> None:
        await self._call_all("on_webhook_processed", event)

    async def on_webhook_failed(self, event: BillingEvent) -> None:
        await self._call_all("on_webhook_failed", event)


class NoOpHooks(BillingHooks):
    """No-operation hooks implementation.

    Used as the default when no hooks are configured.
    """
    pass


__all__ = [
    "BillingEventType",
    "BillingEvent",
    "BillingHooks",
    "CompositeHooks",
    "NoOpHooks",
]
