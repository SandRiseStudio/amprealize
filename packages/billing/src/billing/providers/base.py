"""
Base billing provider protocol.

Defines the abstract interface that all billing providers must implement.
This allows the BillingService to work with any payment processor
(Stripe, PayPal, Braintree, custom, etc.) without coupling to a specific vendor.
"""

from abc import ABC, abstractmethod
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


class BillingProvider(ABC):
    """Abstract base class for billing providers.

    All billing providers must implement this interface. The BillingService
    delegates provider-specific operations to the configured provider.

    Example implementation:
        class MyBillingProvider(BillingProvider):
            async def create_customer(self, request: CreateCustomerRequest) -> Customer:
                # Create customer in external system
                external_id = await my_api.create_customer(request.email)
                return Customer(
                    org_id=request.org_id,
                    user_id=request.user_id,
                    email=request.email,
                    provider_customer_id=external_id,
                )
    """

    # =========================================================================
    # Provider Metadata
    # =========================================================================

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name (e.g., 'stripe', 'paypal', 'mock')."""
        ...

    @property
    def is_test_mode(self) -> bool:
        """Whether provider is in test/sandbox mode."""
        return False

    # =========================================================================
    # Customer Operations
    # =========================================================================

    @abstractmethod
    async def create_customer(self, request: CreateCustomerRequest) -> Customer:
        """Create a new customer in the billing provider.

        Args:
            request: Customer creation request with email and owner (org/user).

        Returns:
            Created Customer with provider_customer_id populated.

        Raises:
            BillingProviderError: If creation fails.
        """
        ...

    @abstractmethod
    async def get_customer(self, customer_id: str) -> Optional[Customer]:
        """Retrieve a customer by ID.

        Args:
            customer_id: Internal customer ID.

        Returns:
            Customer if found, None otherwise.
        """
        ...

    @abstractmethod
    async def get_customer_by_provider_id(self, provider_customer_id: str) -> Optional[Customer]:
        """Retrieve a customer by their provider ID.

        Args:
            provider_customer_id: External provider customer ID (e.g., Stripe cus_xxx).

        Returns:
            Customer if found, None otherwise.
        """
        ...

    @abstractmethod
    async def update_customer(
        self,
        customer_id: str,
        request: UpdateCustomerRequest
    ) -> Customer:
        """Update customer details.

        Args:
            customer_id: Internal customer ID.
            request: Fields to update.

        Returns:
            Updated Customer.

        Raises:
            BillingProviderError: If customer not found or update fails.
        """
        ...

    @abstractmethod
    async def delete_customer(self, customer_id: str) -> bool:
        """Delete a customer.

        Note: This may fail if the customer has active subscriptions.

        Args:
            customer_id: Internal customer ID.

        Returns:
            True if deleted, False if not found.

        Raises:
            BillingProviderError: If deletion fails (e.g., active subscriptions).
        """
        ...

    async def get_customer_by_org(self, org_id: str) -> Optional[Customer]:
        """Find customer by organization ID.

        Default implementation returns None. Override for providers that
        support organization-based lookup.
        """
        return None

    async def get_customer_by_user(self, user_id: str) -> Optional[Customer]:
        """Find customer by user ID.

        Default implementation returns None. Override for providers that
        support user-based lookup.
        """
        return None

    # =========================================================================
    # Subscription Operations
    # =========================================================================

    @abstractmethod
    async def create_subscription(
        self,
        request: CreateSubscriptionRequest
    ) -> Subscription:
        """Create a new subscription for a customer.

        Args:
            request: Subscription creation request with customer_id and plan.

        Returns:
            Created Subscription.

        Raises:
            BillingProviderError: If creation fails.
        """
        ...

    @abstractmethod
    async def get_subscription(self, subscription_id: str) -> Optional[Subscription]:
        """Retrieve a subscription by ID.

        Args:
            subscription_id: Internal subscription ID.

        Returns:
            Subscription if found, None otherwise.
        """
        ...

    @abstractmethod
    async def get_subscriptions_for_customer(
        self,
        customer_id: str,
        include_canceled: bool = False,
    ) -> List[Subscription]:
        """Get all subscriptions for a customer.

        Args:
            customer_id: Internal customer ID.
            include_canceled: Whether to include canceled subscriptions.

        Returns:
            List of subscriptions, may be empty.
        """
        ...

    @abstractmethod
    async def update_subscription(
        self,
        subscription_id: str,
        request: UpdateSubscriptionRequest,
    ) -> Subscription:
        """Update a subscription (e.g., change plan).

        Args:
            subscription_id: Internal subscription ID.
            request: Fields to update.

        Returns:
            Updated Subscription.

        Raises:
            BillingProviderError: If subscription not found or update fails.
        """
        ...

    @abstractmethod
    async def cancel_subscription(
        self,
        subscription_id: str,
        cancel_immediately: bool = False,
        reason: Optional[str] = None,
    ) -> Subscription:
        """Cancel a subscription.

        Args:
            subscription_id: Internal subscription ID.
            cancel_immediately: If True, cancel now. If False, cancel at period end.
            reason: Optional cancellation reason for tracking.

        Returns:
            Updated Subscription with cancellation info.

        Raises:
            BillingProviderError: If subscription not found or cancellation fails.
        """
        ...

    @abstractmethod
    async def reactivate_subscription(self, subscription_id: str) -> Subscription:
        """Reactivate a subscription scheduled for cancellation.

        Only works for subscriptions where cancel_at_period_end is True
        and the subscription hasn't actually ended yet.

        Args:
            subscription_id: Internal subscription ID.

        Returns:
            Reactivated Subscription.

        Raises:
            BillingProviderError: If reactivation fails.
        """
        ...

    # =========================================================================
    # Payment Method Operations
    # =========================================================================

    @abstractmethod
    async def attach_payment_method(
        self,
        request: CreatePaymentMethodRequest,
    ) -> PaymentMethod:
        """Attach a payment method to a customer.

        The payment method should already be created client-side
        (e.g., via Stripe Elements or PayPal JS SDK).

        Args:
            request: Contains customer_id and provider_payment_method_id.

        Returns:
            Attached PaymentMethod.

        Raises:
            BillingProviderError: If attachment fails.
        """
        ...

    @abstractmethod
    async def get_payment_methods(self, customer_id: str) -> List[PaymentMethod]:
        """Get all payment methods for a customer.

        Args:
            customer_id: Internal customer ID.

        Returns:
            List of payment methods, may be empty.
        """
        ...

    @abstractmethod
    async def set_default_payment_method(
        self,
        customer_id: str,
        payment_method_id: str,
    ) -> PaymentMethod:
        """Set a payment method as the default for a customer.

        Args:
            customer_id: Internal customer ID.
            payment_method_id: Internal payment method ID.

        Returns:
            Updated PaymentMethod.

        Raises:
            BillingProviderError: If not found or update fails.
        """
        ...

    @abstractmethod
    async def detach_payment_method(self, payment_method_id: str) -> bool:
        """Remove a payment method from a customer.

        Args:
            payment_method_id: Internal payment method ID.

        Returns:
            True if detached, False if not found.

        Raises:
            BillingProviderError: If detachment fails.
        """
        ...

    # =========================================================================
    # Invoice Operations
    # =========================================================================

    @abstractmethod
    async def get_invoice(self, invoice_id: str) -> Optional[Invoice]:
        """Retrieve an invoice by ID.

        Args:
            invoice_id: Internal invoice ID.

        Returns:
            Invoice if found, None otherwise.
        """
        ...

    @abstractmethod
    async def get_invoices_for_customer(
        self,
        customer_id: str,
        limit: int = 10,
        starting_after: Optional[str] = None,
    ) -> List[Invoice]:
        """Get invoices for a customer.

        Args:
            customer_id: Internal customer ID.
            limit: Maximum number of invoices to return.
            starting_after: Invoice ID for pagination.

        Returns:
            List of invoices, ordered by date descending.
        """
        ...

    @abstractmethod
    async def get_upcoming_invoice(self, subscription_id: str) -> Optional[Invoice]:
        """Preview the next invoice for a subscription.

        Args:
            subscription_id: Internal subscription ID.

        Returns:
            Preview Invoice (not yet finalized), or None if no upcoming invoice.
        """
        ...

    # =========================================================================
    # Usage Operations
    # =========================================================================

    @abstractmethod
    async def record_usage(self, request: RecordUsageRequest) -> None:
        """Record metered usage for a subscription.

        For high-volume usage, implementations should batch writes
        and use idempotency keys to prevent duplicates.

        Args:
            request: Usage record with subscription_id, metric, and quantity.

        Raises:
            BillingProviderError: If recording fails.
        """
        ...

    @abstractmethod
    async def get_usage(
        self,
        subscription_id: str,
        metric: UsageMetric,
    ) -> UsageAggregate:
        """Get usage aggregate for a metric in the current period.

        Args:
            subscription_id: Internal subscription ID.
            metric: Usage metric to query.

        Returns:
            UsageAggregate with totals and limits.
        """
        ...

    @abstractmethod
    async def get_all_usage(self, subscription_id: str) -> Dict[UsageMetric, UsageAggregate]:
        """Get all usage aggregates for a subscription's current period.

        Args:
            subscription_id: Internal subscription ID.

        Returns:
            Dictionary mapping metrics to their aggregates.
        """
        ...

    # =========================================================================
    # Checkout Operations
    # =========================================================================

    @abstractmethod
    async def create_checkout_session(
        self,
        request: CreateCheckoutRequest,
    ) -> CheckoutSession:
        """Create a checkout session for collecting payment.

        Args:
            request: Checkout configuration with plan and URLs.

        Returns:
            CheckoutSession with hosted checkout URL.

        Raises:
            BillingProviderError: If creation fails.
        """
        ...

    @abstractmethod
    async def get_checkout_session(
        self,
        session_id: str,
    ) -> Optional[CheckoutSession]:
        """Retrieve a checkout session by ID.

        Args:
            session_id: Internal checkout session ID.

        Returns:
            CheckoutSession if found, None otherwise.
        """
        ...

    # =========================================================================
    # Portal Operations
    # =========================================================================

    @abstractmethod
    async def create_portal_session(
        self,
        request: CreatePortalSessionRequest,
    ) -> BillingPortalSession:
        """Create a billing portal session for customer self-service.

        The portal allows customers to:
        - Update payment methods
        - View invoices
        - Change subscription plans
        - Cancel subscriptions

        Args:
            request: Portal configuration with customer_id and return_url.

        Returns:
            BillingPortalSession with portal URL.

        Raises:
            BillingProviderError: If creation fails.
        """
        ...

    # =========================================================================
    # Webhook Operations
    # =========================================================================

    @abstractmethod
    async def verify_webhook(
        self,
        payload: bytes,
        signature: str,
    ) -> WebhookEvent:
        """Verify and parse a webhook from the provider.

        Args:
            payload: Raw webhook payload bytes.
            signature: Webhook signature header value.

        Returns:
            Parsed and verified WebhookEvent.

        Raises:
            BillingProviderError: If signature verification fails.
        """
        ...

    @abstractmethod
    async def process_webhook(self, event: WebhookEvent) -> WebhookEventResult:
        """Process a verified webhook event.

        This method should handle all supported webhook event types
        and update local state accordingly.

        Args:
            event: Verified webhook event.

        Returns:
            WebhookEventResult indicating success/failure.
        """
        ...

    # =========================================================================
    # Utility Methods
    # =========================================================================

    async def sync_customer(self, customer_id: str) -> Customer:
        """Sync customer data from provider.

        Fetches the latest customer data from the billing provider
        and updates local storage.

        Default implementation just returns the current customer.
        Override for providers that need explicit sync.
        """
        customer = await self.get_customer(customer_id)
        if not customer:
            raise ValueError(f"Customer not found: {customer_id}")
        return customer

    async def sync_subscription(self, subscription_id: str) -> Subscription:
        """Sync subscription data from provider.

        Default implementation just returns the current subscription.
        Override for providers that need explicit sync.
        """
        subscription = await self.get_subscription(subscription_id)
        if not subscription:
            raise ValueError(f"Subscription not found: {subscription_id}")
        return subscription

    def get_price_id_for_plan(
        self,
        plan: BillingPlan,
        interval: str = "monthly",
    ) -> Optional[str]:
        """Get the provider's price ID for a plan.

        Override to return provider-specific price IDs.

        Args:
            plan: Billing plan.
            interval: 'monthly' or 'yearly'.

        Returns:
            Provider price ID, or None if not applicable.
        """
        return None


class BillingProviderError(Exception):
    """Base exception for billing provider errors."""

    def __init__(
        self,
        message: str,
        code: Optional[str] = None,
        provider: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.provider = provider
        self.details = details or {}

    def __str__(self) -> str:
        parts = [self.message]
        if self.code:
            parts.append(f"[{self.code}]")
        if self.provider:
            parts.append(f"(provider: {self.provider})")
        return " ".join(parts)


class CustomerNotFoundError(BillingProviderError):
    """Customer not found in billing provider."""
    pass


class SubscriptionNotFoundError(BillingProviderError):
    """Subscription not found in billing provider."""
    pass


class PaymentMethodError(BillingProviderError):
    """Payment method operation failed."""
    pass


class WebhookVerificationError(BillingProviderError):
    """Webhook signature verification failed."""
    pass


class UsageLimitExceededError(BillingProviderError):
    """Usage limit exceeded for a metric."""

    def __init__(
        self,
        message: str,
        metric: UsageMetric,
        current: int,
        limit: int,
        **kwargs: Any,
    ):
        super().__init__(message, **kwargs)
        self.metric = metric
        self.current = current
        self.limit = limit


__all__ = [
    "BillingProvider",
    "BillingProviderError",
    "CustomerNotFoundError",
    "SubscriptionNotFoundError",
    "PaymentMethodError",
    "WebhookVerificationError",
    "UsageLimitExceededError",
]
