"""
Webhook handling for billing provider events.

This module provides a provider-agnostic webhook handling layer that:
- Verifies webhook signatures (via provider)
- Routes events to appropriate handlers
- Emits hook callbacks for integration
- Maintains idempotency for event processing

Usage:
    from billing.webhooks import WebhookHandler
    from billing.providers.stripe import StripeBillingProvider

    provider = StripeBillingProvider(api_key="sk_test_...")
    handler = WebhookHandler(provider, hooks=my_hooks)

    # In FastAPI route:
    result = await handler.handle_webhook(payload, signature, secret)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

from billing.hooks import (
    BillingEvent,
    BillingEventType,
    BillingHooks,
    NoOpHooks,
)
from billing.models import (
    Customer,
    Invoice,
    InvoiceStatus,
    PaymentMethod,
    Subscription,
    SubscriptionStatus,
    WebhookEvent,
    WebhookEventResult,
    WebhookEventType,
)
from billing.providers.base import BillingProvider, BillingProviderError


logger = logging.getLogger(__name__)


# =============================================================================
# Webhook Result Types
# =============================================================================


class WebhookHandlerStatus(str, Enum):
    """Status of webhook processing."""
    SUCCESS = "success"
    IGNORED = "ignored"
    FAILED = "failed"
    DUPLICATE = "duplicate"


@dataclass
class WebhookResult:
    """Result of webhook processing.

    Attributes:
        status: Processing status
        event_id: Provider's event ID
        event_type: Type of webhook event
        message: Human-readable message
        data: Any extracted/processed data
        error: Error details if failed
    """
    status: WebhookHandlerStatus
    event_id: str
    event_type: str
    message: str = ""
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    processed_at: datetime = field(default_factory=datetime.utcnow)

    def is_success(self) -> bool:
        """Check if webhook was processed successfully."""
        return self.status in (WebhookHandlerStatus.SUCCESS, WebhookHandlerStatus.IGNORED)


# =============================================================================
# Webhook Signature Verification
# =============================================================================


class SignatureVerificationError(Exception):
    """Raised when webhook signature verification fails."""
    pass


class WebhookSignatureVerifier(ABC):
    """Abstract base class for webhook signature verification."""

    @abstractmethod
    def verify(
        self,
        payload: bytes,
        signature: str,
        secret: str,
        timestamp: Optional[str] = None,
    ) -> bool:
        """Verify webhook signature.

        Args:
            payload: Raw request body
            signature: Signature header value
            secret: Webhook secret for verification
            timestamp: Optional timestamp header

        Returns:
            True if signature is valid

        Raises:
            SignatureVerificationError: If verification fails
        """
        ...


class StripeSignatureVerifier(WebhookSignatureVerifier):
    """Stripe webhook signature verification.

    Stripe uses HMAC-SHA256 with a timestamp-prefixed payload:
    1. Extract timestamp and signatures from header
    2. Construct signed_payload = timestamp + "." + payload
    3. Compute HMAC with secret
    4. Compare with provided signature(s)
    """

    # Maximum age of webhook event in seconds
    TOLERANCE = 300  # 5 minutes

    def verify(
        self,
        payload: bytes,
        signature: str,
        secret: str,
        timestamp: Optional[str] = None,
    ) -> bool:
        """Verify Stripe webhook signature."""
        try:
            # Parse signature header: "t=timestamp,v1=sig1,v1=sig2,..."
            elements = dict(
                item.split("=", 1)
                for item in signature.split(",")
            )
        except (ValueError, AttributeError) as e:
            raise SignatureVerificationError(f"Invalid signature header format: {e}")

        # Extract timestamp
        if "t" not in elements:
            raise SignatureVerificationError("Missing timestamp in signature")

        try:
            event_timestamp = int(elements["t"])
        except ValueError:
            raise SignatureVerificationError("Invalid timestamp format")

        # Check timestamp tolerance
        now = int(datetime.utcnow().timestamp())
        if abs(now - event_timestamp) > self.TOLERANCE:
            raise SignatureVerificationError(
                f"Webhook timestamp too old: {now - event_timestamp}s ago"
            )

        # Extract signatures (there can be multiple v1 signatures during rotation)
        signatures = [
            v for k, v in (item.split("=", 1) for item in signature.split(","))
            if k == "v1"
        ]

        if not signatures:
            raise SignatureVerificationError("No v1 signatures found")

        # Compute expected signature
        signed_payload = f"{event_timestamp}.".encode() + payload
        expected_sig = hmac.new(
            secret.encode(),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()

        # Compare with any of the provided signatures
        for sig in signatures:
            if hmac.compare_digest(expected_sig, sig):
                return True

        raise SignatureVerificationError("Signature verification failed")


class MockSignatureVerifier(WebhookSignatureVerifier):
    """Mock signature verifier for testing.

    Always returns True unless secret is 'invalid'.
    """

    def verify(
        self,
        payload: bytes,
        signature: str,
        secret: str,
        timestamp: Optional[str] = None,
    ) -> bool:
        """Mock signature verification."""
        if secret == "invalid":
            raise SignatureVerificationError("Invalid secret for testing")
        return True


# =============================================================================
# Idempotency Tracking
# =============================================================================


class IdempotencyStore(ABC):
    """Abstract store for tracking processed webhook events."""

    @abstractmethod
    async def has_processed(self, event_id: str) -> bool:
        """Check if an event has already been processed."""
        ...

    @abstractmethod
    async def mark_processed(
        self,
        event_id: str,
        result: WebhookResult,
    ) -> None:
        """Mark an event as processed."""
        ...

    @abstractmethod
    async def get_result(self, event_id: str) -> Optional[WebhookResult]:
        """Get the result of a previously processed event."""
        ...


class InMemoryIdempotencyStore(IdempotencyStore):
    """In-memory idempotency store for testing.

    Note: Not suitable for production - use Redis or database storage.
    """

    def __init__(self, max_size: int = 10000):
        self._processed: Dict[str, WebhookResult] = {}
        self._max_size = max_size

    async def has_processed(self, event_id: str) -> bool:
        return event_id in self._processed

    async def mark_processed(
        self,
        event_id: str,
        result: WebhookResult,
    ) -> None:
        # Simple LRU-like eviction
        if len(self._processed) >= self._max_size:
            # Remove oldest entry
            oldest = next(iter(self._processed))
            del self._processed[oldest]

        self._processed[event_id] = result

    async def get_result(self, event_id: str) -> Optional[WebhookResult]:
        return self._processed.get(event_id)


# =============================================================================
# Webhook Handler
# =============================================================================


# Event handler type
EventHandler = Callable[
    [WebhookEvent, BillingProvider, BillingHooks],
    Coroutine[Any, Any, WebhookResult],
]


class WebhookHandler:
    """Provider-agnostic webhook handler.

    Routes incoming webhooks to appropriate handlers based on event type,
    ensuring idempotency and proper integration via hooks.

    Attributes:
        provider: BillingProvider for fetching entity details
        hooks: BillingHooks for integration callbacks
        verifier: Signature verification implementation
        idempotency_store: Store for tracking processed events
        handlers: Registered event handlers
    """

    def __init__(
        self,
        provider: BillingProvider,
        hooks: Optional[BillingHooks] = None,
        verifier: Optional[WebhookSignatureVerifier] = None,
        idempotency_store: Optional[IdempotencyStore] = None,
    ):
        """Initialize webhook handler.

        Args:
            provider: BillingProvider for entity lookups
            hooks: Optional hooks for integration
            verifier: Signature verifier (defaults to mock)
            idempotency_store: Store for idempotency (defaults to in-memory)
        """
        self.provider = provider
        self.hooks = hooks or NoOpHooks()
        self.verifier = verifier or MockSignatureVerifier()
        self.idempotency_store = idempotency_store or InMemoryIdempotencyStore()

        # Register default handlers
        self._handlers: Dict[WebhookEventType, EventHandler] = {}
        self._register_default_handlers()

    def _register_default_handlers(self) -> None:
        """Register default event handlers."""
        # Customer events
        self.register_handler(WebhookEventType.CUSTOMER_CREATED, self._handle_customer_created)
        self.register_handler(WebhookEventType.CUSTOMER_UPDATED, self._handle_customer_updated)
        self.register_handler(WebhookEventType.CUSTOMER_DELETED, self._handle_customer_deleted)

        # Subscription events
        self.register_handler(WebhookEventType.SUBSCRIPTION_CREATED, self._handle_subscription_created)
        self.register_handler(WebhookEventType.SUBSCRIPTION_UPDATED, self._handle_subscription_updated)
        self.register_handler(WebhookEventType.SUBSCRIPTION_DELETED, self._handle_subscription_canceled)
        self.register_handler(WebhookEventType.SUBSCRIPTION_TRIAL_WILL_END, self._handle_subscription_trial_ending)
        self.register_handler(WebhookEventType.SUBSCRIPTION_PAST_DUE, self._handle_subscription_past_due)

        # Invoice events
        self.register_handler(WebhookEventType.INVOICE_CREATED, self._handle_invoice_created)
        self.register_handler(WebhookEventType.INVOICE_PAID, self._handle_invoice_paid)
        self.register_handler(WebhookEventType.INVOICE_PAYMENT_FAILED, self._handle_invoice_payment_failed)

        # Payment events
        self.register_handler(WebhookEventType.PAYMENT_INTENT_SUCCEEDED, self._handle_payment_succeeded)
        self.register_handler(WebhookEventType.PAYMENT_INTENT_FAILED, self._handle_payment_failed)
        self.register_handler(WebhookEventType.PAYMENT_METHOD_ATTACHED, self._handle_payment_method_attached)
        self.register_handler(WebhookEventType.PAYMENT_METHOD_DETACHED, self._handle_payment_method_detached)

    def register_handler(
        self,
        event_type: WebhookEventType,
        handler: EventHandler,
    ) -> None:
        """Register a custom handler for an event type.

        Args:
            event_type: Type of event to handle
            handler: Async handler function
        """
        self._handlers[event_type] = handler

    async def handle_webhook(
        self,
        payload: bytes,
        signature: str,
        secret: str,
        timestamp: Optional[str] = None,
    ) -> WebhookResult:
        """Process an incoming webhook.

        Args:
            payload: Raw request body
            signature: Signature header from provider
            secret: Webhook secret for verification
            timestamp: Optional timestamp header

        Returns:
            WebhookResult with processing status
        """
        # Parse payload
        try:
            data = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as e:
            return WebhookResult(
                status=WebhookHandlerStatus.FAILED,
                event_id="unknown",
                event_type="unknown",
                message="Invalid JSON payload",
                error=str(e),
            )

        # Extract event ID and type
        event_id = data.get("id", "unknown")
        event_type_str = data.get("type", "unknown")

        # Verify signature
        try:
            self.verifier.verify(payload, signature, secret, timestamp)
        except SignatureVerificationError as e:
            logger.warning(f"Webhook signature verification failed: {e}")
            return WebhookResult(
                status=WebhookHandlerStatus.FAILED,
                event_id=event_id,
                event_type=event_type_str,
                message="Signature verification failed",
                error=str(e),
            )

        # Check idempotency
        if await self.idempotency_store.has_processed(event_id):
            existing = await self.idempotency_store.get_result(event_id)
            return WebhookResult(
                status=WebhookHandlerStatus.DUPLICATE,
                event_id=event_id,
                event_type=event_type_str,
                message="Event already processed",
                data=existing.data if existing else None,
            )

        # Parse event type
        try:
            event_type = WebhookEventType(event_type_str)
        except ValueError:
            logger.info(f"Unhandled webhook event type: {event_type_str}")
            result = WebhookResult(
                status=WebhookHandlerStatus.IGNORED,
                event_id=event_id,
                event_type=event_type_str,
                message=f"Event type not handled: {event_type_str}",
            )
            await self.idempotency_store.mark_processed(event_id, result)
            return result

        # Create WebhookEvent
        event = WebhookEvent(
            id=event_id,
            type=event_type,
            data=data.get("data", {}).get("object", {}),
            created=datetime.fromtimestamp(data.get("created", 0)),
            api_version=data.get("api_version"),
            livemode=data.get("livemode", False),
        )

        # Emit webhook received hook
        await self.hooks.emit(BillingEvent(
            type=BillingEventType.WEBHOOK_RECEIVED,
            data={"event_id": event_id, "event_type": event_type_str},
        ))

        # Get handler
        handler = self._handlers.get(event_type)
        if not handler:
            logger.info(f"No handler registered for: {event_type}")
            result = WebhookResult(
                status=WebhookHandlerStatus.IGNORED,
                event_id=event_id,
                event_type=event_type_str,
                message=f"No handler for event type: {event_type_str}",
            )
            await self.idempotency_store.mark_processed(event_id, result)
            return result

        # Process event
        try:
            result = await handler(event, self.provider, self.hooks)
            await self.idempotency_store.mark_processed(event_id, result)

            # Emit webhook processed hook
            await self.hooks.emit(BillingEvent(
                type=BillingEventType.WEBHOOK_PROCESSED,
                data={
                    "event_id": event_id,
                    "event_type": event_type_str,
                    "status": result.status.value,
                },
            ))

            return result

        except Exception as e:
            logger.exception(f"Error processing webhook {event_id}: {e}")

            # Emit webhook failed hook
            await self.hooks.emit(BillingEvent(
                type=BillingEventType.WEBHOOK_FAILED,
                data={
                    "event_id": event_id,
                    "event_type": event_type_str,
                    "error": str(e),
                },
            ))

            result = WebhookResult(
                status=WebhookHandlerStatus.FAILED,
                event_id=event_id,
                event_type=event_type_str,
                message="Handler error",
                error=str(e),
            )
            # Don't mark as processed on failure - allow retry
            return result

    # =========================================================================
    # Customer Handlers
    # =========================================================================

    async def _handle_customer_created(
        self,
        event: WebhookEvent,
        provider: BillingProvider,
        hooks: BillingHooks,
    ) -> WebhookResult:
        """Handle customer.created event."""
        customer_data = event.data
        customer_id = customer_data.get("id")

        await hooks.emit(BillingEvent(
            type=BillingEventType.CUSTOMER_CREATED,
            customer_id=customer_id,
            data=customer_data,
        ))

        return WebhookResult(
            status=WebhookHandlerStatus.SUCCESS,
            event_id=event.id,
            event_type=event.type.value,
            message=f"Customer created: {customer_id}",
            data={"customer_id": customer_id},
        )

    async def _handle_customer_updated(
        self,
        event: WebhookEvent,
        provider: BillingProvider,
        hooks: BillingHooks,
    ) -> WebhookResult:
        """Handle customer.updated event."""
        customer_data = event.data
        customer_id = customer_data.get("id")

        await hooks.emit(BillingEvent(
            type=BillingEventType.CUSTOMER_UPDATED,
            customer_id=customer_id,
            data=customer_data,
        ))

        return WebhookResult(
            status=WebhookHandlerStatus.SUCCESS,
            event_id=event.id,
            event_type=event.type.value,
            message=f"Customer updated: {customer_id}",
            data={"customer_id": customer_id},
        )

    async def _handle_customer_deleted(
        self,
        event: WebhookEvent,
        provider: BillingProvider,
        hooks: BillingHooks,
    ) -> WebhookResult:
        """Handle customer.deleted event."""
        customer_data = event.data
        customer_id = customer_data.get("id")

        await hooks.emit(BillingEvent(
            type=BillingEventType.CUSTOMER_DELETED,
            customer_id=customer_id,
            data=customer_data,
        ))

        return WebhookResult(
            status=WebhookHandlerStatus.SUCCESS,
            event_id=event.id,
            event_type=event.type.value,
            message=f"Customer deleted: {customer_id}",
            data={"customer_id": customer_id},
        )

    # =========================================================================
    # Subscription Handlers
    # =========================================================================

    async def _handle_subscription_created(
        self,
        event: WebhookEvent,
        provider: BillingProvider,
        hooks: BillingHooks,
    ) -> WebhookResult:
        """Handle subscription.created event."""
        sub_data = event.data
        subscription_id = sub_data.get("id")
        customer_id = sub_data.get("customer")

        await hooks.emit(BillingEvent(
            type=BillingEventType.SUBSCRIPTION_CREATED,
            customer_id=customer_id,
            subscription_id=subscription_id,
            data=sub_data,
        ))

        return WebhookResult(
            status=WebhookHandlerStatus.SUCCESS,
            event_id=event.id,
            event_type=event.type.value,
            message=f"Subscription created: {subscription_id}",
            data={"subscription_id": subscription_id, "customer_id": customer_id},
        )

    async def _handle_subscription_updated(
        self,
        event: WebhookEvent,
        provider: BillingProvider,
        hooks: BillingHooks,
    ) -> WebhookResult:
        """Handle subscription.updated event."""
        sub_data = event.data
        subscription_id = sub_data.get("id")
        customer_id = sub_data.get("customer")
        status = sub_data.get("status")

        # Determine specific event type based on changes
        event_type = BillingEventType.SUBSCRIPTION_UPDATED

        # Check if plan changed
        previous_attributes = event.data.get("previous_attributes", {})
        if "items" in previous_attributes or "plan" in previous_attributes:
            event_type = BillingEventType.SUBSCRIPTION_PLAN_CHANGED

        await hooks.emit(BillingEvent(
            type=event_type,
            customer_id=customer_id,
            subscription_id=subscription_id,
            data=sub_data,
        ))

        return WebhookResult(
            status=WebhookHandlerStatus.SUCCESS,
            event_id=event.id,
            event_type=event.type.value,
            message=f"Subscription updated: {subscription_id} (status: {status})",
            data={
                "subscription_id": subscription_id,
                "customer_id": customer_id,
                "status": status,
            },
        )

    async def _handle_subscription_canceled(
        self,
        event: WebhookEvent,
        provider: BillingProvider,
        hooks: BillingHooks,
    ) -> WebhookResult:
        """Handle subscription.deleted (canceled) event."""
        sub_data = event.data
        subscription_id = sub_data.get("id")
        customer_id = sub_data.get("customer")

        await hooks.emit(BillingEvent(
            type=BillingEventType.SUBSCRIPTION_CANCELED,
            customer_id=customer_id,
            subscription_id=subscription_id,
            data=sub_data,
        ))

        return WebhookResult(
            status=WebhookHandlerStatus.SUCCESS,
            event_id=event.id,
            event_type=event.type.value,
            message=f"Subscription canceled: {subscription_id}",
            data={"subscription_id": subscription_id, "customer_id": customer_id},
        )

    async def _handle_subscription_trial_ending(
        self,
        event: WebhookEvent,
        provider: BillingProvider,
        hooks: BillingHooks,
    ) -> WebhookResult:
        """Handle subscription.trial_will_end event."""
        sub_data = event.data
        subscription_id = sub_data.get("id")
        customer_id = sub_data.get("customer")
        trial_end = sub_data.get("trial_end")

        await hooks.emit(BillingEvent(
            type=BillingEventType.SUBSCRIPTION_TRIAL_ENDING,
            customer_id=customer_id,
            subscription_id=subscription_id,
            data={"trial_end": trial_end, **sub_data},
        ))

        return WebhookResult(
            status=WebhookHandlerStatus.SUCCESS,
            event_id=event.id,
            event_type=event.type.value,
            message=f"Trial ending for subscription: {subscription_id}",
            data={
                "subscription_id": subscription_id,
                "customer_id": customer_id,
                "trial_end": trial_end,
            },
        )

    async def _handle_subscription_past_due(
        self,
        event: WebhookEvent,
        provider: BillingProvider,
        hooks: BillingHooks,
    ) -> WebhookResult:
        """Handle subscription past due event."""
        sub_data = event.data
        subscription_id = sub_data.get("id")
        customer_id = sub_data.get("customer")

        await hooks.emit(BillingEvent(
            type=BillingEventType.SUBSCRIPTION_PAST_DUE,
            customer_id=customer_id,
            subscription_id=subscription_id,
            data=sub_data,
        ))

        return WebhookResult(
            status=WebhookHandlerStatus.SUCCESS,
            event_id=event.id,
            event_type=event.type.value,
            message=f"Subscription past due: {subscription_id}",
            data={"subscription_id": subscription_id, "customer_id": customer_id},
        )

    # =========================================================================
    # Invoice Handlers
    # =========================================================================

    async def _handle_invoice_created(
        self,
        event: WebhookEvent,
        provider: BillingProvider,
        hooks: BillingHooks,
    ) -> WebhookResult:
        """Handle invoice.created event."""
        invoice_data = event.data
        invoice_id = invoice_data.get("id")
        customer_id = invoice_data.get("customer")
        subscription_id = invoice_data.get("subscription")

        await hooks.emit(BillingEvent(
            type=BillingEventType.INVOICE_CREATED,
            customer_id=customer_id,
            subscription_id=subscription_id,
            invoice_id=invoice_id,
            data=invoice_data,
        ))

        return WebhookResult(
            status=WebhookHandlerStatus.SUCCESS,
            event_id=event.id,
            event_type=event.type.value,
            message=f"Invoice created: {invoice_id}",
            data={
                "invoice_id": invoice_id,
                "customer_id": customer_id,
                "subscription_id": subscription_id,
            },
        )

    async def _handle_invoice_paid(
        self,
        event: WebhookEvent,
        provider: BillingProvider,
        hooks: BillingHooks,
    ) -> WebhookResult:
        """Handle invoice.paid event."""
        invoice_data = event.data
        invoice_id = invoice_data.get("id")
        customer_id = invoice_data.get("customer")
        subscription_id = invoice_data.get("subscription")
        amount_paid = invoice_data.get("amount_paid", 0)

        await hooks.emit(BillingEvent(
            type=BillingEventType.INVOICE_PAID,
            customer_id=customer_id,
            subscription_id=subscription_id,
            invoice_id=invoice_id,
            data={"amount_paid": amount_paid, **invoice_data},
        ))

        # Also emit payment succeeded
        await hooks.emit(BillingEvent(
            type=BillingEventType.PAYMENT_SUCCEEDED,
            customer_id=customer_id,
            subscription_id=subscription_id,
            invoice_id=invoice_id,
            data={"amount": amount_paid},
        ))

        return WebhookResult(
            status=WebhookHandlerStatus.SUCCESS,
            event_id=event.id,
            event_type=event.type.value,
            message=f"Invoice paid: {invoice_id} (amount: {amount_paid})",
            data={
                "invoice_id": invoice_id,
                "customer_id": customer_id,
                "amount_paid": amount_paid,
            },
        )

    async def _handle_invoice_payment_failed(
        self,
        event: WebhookEvent,
        provider: BillingProvider,
        hooks: BillingHooks,
    ) -> WebhookResult:
        """Handle invoice.payment_failed event."""
        invoice_data = event.data
        invoice_id = invoice_data.get("id")
        customer_id = invoice_data.get("customer")
        subscription_id = invoice_data.get("subscription")
        attempt_count = invoice_data.get("attempt_count", 0)

        await hooks.emit(BillingEvent(
            type=BillingEventType.INVOICE_PAYMENT_FAILED,
            customer_id=customer_id,
            subscription_id=subscription_id,
            invoice_id=invoice_id,
            data={"attempt_count": attempt_count, **invoice_data},
        ))

        # Also emit payment failed
        await hooks.emit(BillingEvent(
            type=BillingEventType.PAYMENT_FAILED,
            customer_id=customer_id,
            subscription_id=subscription_id,
            invoice_id=invoice_id,
            data={
                "error": "Invoice payment failed",
                "attempt_count": attempt_count,
            },
        ))

        return WebhookResult(
            status=WebhookHandlerStatus.SUCCESS,
            event_id=event.id,
            event_type=event.type.value,
            message=f"Invoice payment failed: {invoice_id} (attempt {attempt_count})",
            data={
                "invoice_id": invoice_id,
                "customer_id": customer_id,
                "attempt_count": attempt_count,
            },
        )

    # =========================================================================
    # Payment Handlers
    # =========================================================================

    async def _handle_payment_succeeded(
        self,
        event: WebhookEvent,
        provider: BillingProvider,
        hooks: BillingHooks,
    ) -> WebhookResult:
        """Handle payment_intent.succeeded event."""
        payment_data = event.data
        payment_id = payment_data.get("id")
        customer_id = payment_data.get("customer")
        amount = payment_data.get("amount", 0)

        await hooks.emit(BillingEvent(
            type=BillingEventType.PAYMENT_SUCCEEDED,
            customer_id=customer_id,
            data={"payment_id": payment_id, "amount": amount},
        ))

        return WebhookResult(
            status=WebhookHandlerStatus.SUCCESS,
            event_id=event.id,
            event_type=event.type.value,
            message=f"Payment succeeded: {payment_id} (amount: {amount})",
            data={"payment_id": payment_id, "amount": amount},
        )

    async def _handle_payment_failed(
        self,
        event: WebhookEvent,
        provider: BillingProvider,
        hooks: BillingHooks,
    ) -> WebhookResult:
        """Handle payment_intent.failed event."""
        payment_data = event.data
        payment_id = payment_data.get("id")
        customer_id = payment_data.get("customer")
        error = payment_data.get("last_payment_error", {})

        await hooks.emit(BillingEvent(
            type=BillingEventType.PAYMENT_FAILED,
            customer_id=customer_id,
            data={
                "payment_id": payment_id,
                "error": error.get("message", "Unknown error"),
            },
        ))

        return WebhookResult(
            status=WebhookHandlerStatus.SUCCESS,
            event_id=event.id,
            event_type=event.type.value,
            message=f"Payment failed: {payment_id}",
            error=error.get("message"),
            data={"payment_id": payment_id, "error": error},
        )

    async def _handle_payment_method_attached(
        self,
        event: WebhookEvent,
        provider: BillingProvider,
        hooks: BillingHooks,
    ) -> WebhookResult:
        """Handle payment_method.attached event."""
        pm_data = event.data
        payment_method_id = pm_data.get("id")
        customer_id = pm_data.get("customer")
        pm_type = pm_data.get("type")

        await hooks.emit(BillingEvent(
            type=BillingEventType.PAYMENT_METHOD_ADDED,
            customer_id=customer_id,
            payment_method_id=payment_method_id,
            data={"type": pm_type},
        ))

        return WebhookResult(
            status=WebhookHandlerStatus.SUCCESS,
            event_id=event.id,
            event_type=event.type.value,
            message=f"Payment method attached: {payment_method_id}",
            data={
                "payment_method_id": payment_method_id,
                "customer_id": customer_id,
                "type": pm_type,
            },
        )

    async def _handle_payment_method_detached(
        self,
        event: WebhookEvent,
        provider: BillingProvider,
        hooks: BillingHooks,
    ) -> WebhookResult:
        """Handle payment_method.detached event."""
        pm_data = event.data
        payment_method_id = pm_data.get("id")
        # Note: customer may be null after detach

        await hooks.emit(BillingEvent(
            type=BillingEventType.PAYMENT_METHOD_REMOVED,
            payment_method_id=payment_method_id,
            data=pm_data,
        ))

        return WebhookResult(
            status=WebhookHandlerStatus.SUCCESS,
            event_id=event.id,
            event_type=event.type.value,
            message=f"Payment method detached: {payment_method_id}",
            data={"payment_method_id": payment_method_id},
        )


# =============================================================================
# Factory Functions
# =============================================================================


def create_webhook_handler(
    provider: BillingProvider,
    hooks: Optional[BillingHooks] = None,
    provider_type: str = "mock",
    idempotency_store: Optional[IdempotencyStore] = None,
) -> WebhookHandler:
    """Factory function to create a webhook handler with appropriate verifier.

    Args:
        provider: BillingProvider instance
        hooks: Optional BillingHooks for integration
        provider_type: Provider type ('stripe', 'mock')
        idempotency_store: Optional idempotency store

    Returns:
        Configured WebhookHandler
    """
    if provider_type == "stripe":
        verifier = StripeSignatureVerifier()
    else:
        verifier = MockSignatureVerifier()

    return WebhookHandler(
        provider=provider,
        hooks=hooks,
        verifier=verifier,
        idempotency_store=idempotency_store,
    )
