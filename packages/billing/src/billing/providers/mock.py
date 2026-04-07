"""
Mock billing provider for testing.

Provides an in-memory implementation of the BillingProvider protocol
that can be used for unit tests, local development, and demos without
requiring external services.

Usage:
    from billing.providers.mock import MockBillingProvider

    provider = MockBillingProvider()

    # Create customer
    customer = await provider.create_customer(
        CreateCustomerRequest(org_id="org_123", email="test@example.com")
    )

    # Provider stores all data in-memory
    assert provider.customers[customer.id] == customer

    # Reset state for test isolation
    provider.reset()
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import uuid

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
    InvoiceLineItem,
    InvoiceStatus,
    PaymentMethod,
    PaymentMethodType,
    CardDetails,
    RecordUsageRequest,
    Subscription,
    SubscriptionStatus,
    UpdateCustomerRequest,
    UpdateSubscriptionRequest,
    UsageAggregate,
    UsageMetric,
    UsageRecord,
    WebhookEvent,
    WebhookEventResult,
    WebhookEventType,
    get_plan_limits,
    get_plan_price,
)
from billing.providers.base import (
    BillingProvider,
    BillingProviderError,
    CustomerNotFoundError,
    SubscriptionNotFoundError,
    PaymentMethodError,
    WebhookVerificationError,
    UsageLimitExceededError,
)


def _generate_id(prefix: str) -> str:
    """Generate a mock provider ID."""
    return f"mock_{prefix}_{uuid.uuid4().hex[:12]}"


class MockBillingProvider(BillingProvider):
    """In-memory mock implementation of BillingProvider.

    All data is stored in dictionaries and can be directly accessed
    for test assertions. Use reset() to clear all data between tests.

    Attributes:
        customers: Dictionary of customer_id -> Customer
        subscriptions: Dictionary of subscription_id -> Subscription
        payment_methods: Dictionary of payment_method_id -> PaymentMethod
        invoices: Dictionary of invoice_id -> Invoice
        usage_records: List of all usage records
        webhook_events: List of processed webhook events
        checkout_sessions: Dictionary of session_id -> CheckoutSession
        enforce_limits: If True, usage operations respect plan limits
    """

    def __init__(
        self,
        *,
        test_mode: bool = True,
        enforce_limits: bool = True,
        simulate_errors: bool = False,
    ):
        """Initialize mock provider.

        Args:
            test_mode: Whether provider is in test mode (always True for mock).
            enforce_limits: Whether to enforce usage limits.
            simulate_errors: Whether to simulate random errors for chaos testing.
        """
        self._test_mode = test_mode
        self.enforce_limits = enforce_limits
        self.simulate_errors = simulate_errors

        # Storage
        self.customers: Dict[str, Customer] = {}
        self.subscriptions: Dict[str, Subscription] = {}
        self.payment_methods: Dict[str, PaymentMethod] = {}
        self.invoices: Dict[str, Invoice] = {}
        self.usage_records: List[UsageRecord] = []
        self.webhook_events: List[WebhookEvent] = []
        self.checkout_sessions: Dict[str, CheckoutSession] = {}
        self.portal_sessions: Dict[str, BillingPortalSession] = {}

        # Index mappings for efficient lookups
        self._provider_customer_ids: Dict[str, str] = {}  # provider_id -> internal_id
        self._org_customer_ids: Dict[str, str] = {}  # org_id -> customer_id
        self._user_customer_ids: Dict[str, str] = {}  # user_id -> customer_id

    @property
    def name(self) -> str:
        return "mock"

    @property
    def is_test_mode(self) -> bool:
        return self._test_mode

    def reset(self) -> None:
        """Clear all stored data. Call between tests for isolation."""
        self.customers.clear()
        self.subscriptions.clear()
        self.payment_methods.clear()
        self.invoices.clear()
        self.usage_records.clear()
        self.webhook_events.clear()
        self.checkout_sessions.clear()
        self.portal_sessions.clear()
        self._provider_customer_ids.clear()
        self._org_customer_ids.clear()
        self._user_customer_ids.clear()

    # =========================================================================
    # Customer Operations
    # =========================================================================

    async def create_customer(self, request: CreateCustomerRequest) -> Customer:
        provider_id = _generate_id("cus")

        customer = Customer(
            org_id=request.org_id,
            user_id=request.user_id,
            email=request.email,
            name=request.name,
            provider_customer_id=provider_id,
            tax_id=request.tax_id,
            address_line1=request.address_line1,
            address_line2=request.address_line2,
            city=request.city,
            state=request.state,
            postal_code=request.postal_code,
            country=request.country,
            metadata=request.metadata,
        )

        # Store customer
        self.customers[customer.id] = customer
        self._provider_customer_ids[provider_id] = customer.id

        # Update indexes
        if customer.org_id:
            self._org_customer_ids[customer.org_id] = customer.id
        if customer.user_id:
            self._user_customer_ids[customer.user_id] = customer.id

        return customer

    async def get_customer(self, customer_id: str) -> Optional[Customer]:
        return self.customers.get(customer_id)

    async def get_customer_by_provider_id(self, provider_customer_id: str) -> Optional[Customer]:
        internal_id = self._provider_customer_ids.get(provider_customer_id)
        if internal_id:
            return self.customers.get(internal_id)
        return None

    async def get_customer_by_org(self, org_id: str) -> Optional[Customer]:
        customer_id = self._org_customer_ids.get(org_id)
        if customer_id:
            return self.customers.get(customer_id)
        return None

    async def get_customer_by_user(self, user_id: str) -> Optional[Customer]:
        customer_id = self._user_customer_ids.get(user_id)
        if customer_id:
            return self.customers.get(customer_id)
        return None

    async def update_customer(
        self,
        customer_id: str,
        request: UpdateCustomerRequest,
    ) -> Customer:
        customer = self.customers.get(customer_id)
        if not customer:
            raise CustomerNotFoundError(
                f"Customer not found: {customer_id}",
                code="customer_not_found",
                provider=self.name,
            )

        # Update fields
        update_data = request.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if value is not None:
                setattr(customer, field, value)

        customer.updated_at = datetime.utcnow()
        return customer

    async def delete_customer(self, customer_id: str) -> bool:
        customer = self.customers.get(customer_id)
        if not customer:
            return False

        # Check for active subscriptions
        active_subs = [
            s for s in self.subscriptions.values()
            if s.customer_id == customer_id and s.is_active
        ]
        if active_subs:
            raise BillingProviderError(
                "Cannot delete customer with active subscriptions",
                code="customer_has_subscriptions",
                provider=self.name,
            )

        # Remove from indexes
        if customer.provider_customer_id:
            self._provider_customer_ids.pop(customer.provider_customer_id, None)
        if customer.org_id:
            self._org_customer_ids.pop(customer.org_id, None)
        if customer.user_id:
            self._user_customer_ids.pop(customer.user_id, None)

        del self.customers[customer_id]
        return True

    # =========================================================================
    # Subscription Operations
    # =========================================================================

    async def create_subscription(
        self,
        request: CreateSubscriptionRequest,
    ) -> Subscription:
        customer = self.customers.get(request.customer_id)
        if not customer:
            raise CustomerNotFoundError(
                f"Customer not found: {request.customer_id}",
                code="customer_not_found",
                provider=self.name,
            )

        provider_id = _generate_id("sub")
        now = datetime.utcnow()

        # Calculate trial period
        trial_start = None
        trial_end = None
        status = SubscriptionStatus.ACTIVE

        if request.trial_days and request.trial_days > 0:
            trial_start = now
            trial_end = now + timedelta(days=request.trial_days)
            status = SubscriptionStatus.TRIALING

        # Calculate billing period
        if request.billing_interval == "yearly":
            period_end = now + timedelta(days=365)
        else:
            period_end = now + timedelta(days=30)

        subscription = Subscription(
            customer_id=request.customer_id,
            provider_subscription_id=provider_id,
            plan=request.plan,
            status=status,
            billing_interval=request.billing_interval,
            unit_amount=get_plan_price(request.plan, request.billing_interval),
            current_period_start=now,
            current_period_end=period_end,
            trial_start=trial_start,
            trial_end=trial_end,
            metadata=request.metadata,
        )

        self.subscriptions[subscription.id] = subscription
        return subscription

    async def get_subscription(self, subscription_id: str) -> Optional[Subscription]:
        return self.subscriptions.get(subscription_id)

    async def get_subscriptions_for_customer(
        self,
        customer_id: str,
        include_canceled: bool = False,
    ) -> List[Subscription]:
        result = []
        for sub in self.subscriptions.values():
            if sub.customer_id != customer_id:
                continue
            if not include_canceled and sub.status == SubscriptionStatus.CANCELED:
                continue
            result.append(sub)
        return sorted(result, key=lambda s: s.created_at, reverse=True)

    async def update_subscription(
        self,
        subscription_id: str,
        request: UpdateSubscriptionRequest,
    ) -> Subscription:
        subscription = self.subscriptions.get(subscription_id)
        if not subscription:
            raise SubscriptionNotFoundError(
                f"Subscription not found: {subscription_id}",
                code="subscription_not_found",
                provider=self.name,
            )

        # Update fields
        if request.plan is not None:
            subscription.plan = request.plan
            subscription.unit_amount = get_plan_price(
                request.plan,
                request.billing_interval or subscription.billing_interval,
            )

        if request.billing_interval is not None:
            subscription.billing_interval = request.billing_interval
            subscription.unit_amount = get_plan_price(
                subscription.plan,
                request.billing_interval,
            )

        if request.cancel_at_period_end is not None:
            subscription.cancel_at_period_end = request.cancel_at_period_end

        if request.metadata is not None:
            subscription.metadata.update(request.metadata)

        subscription.updated_at = datetime.utcnow()
        return subscription

    async def cancel_subscription(
        self,
        subscription_id: str,
        cancel_immediately: bool = False,
        reason: Optional[str] = None,
    ) -> Subscription:
        subscription = self.subscriptions.get(subscription_id)
        if not subscription:
            raise SubscriptionNotFoundError(
                f"Subscription not found: {subscription_id}",
                code="subscription_not_found",
                provider=self.name,
            )

        now = datetime.utcnow()
        subscription.canceled_at = now
        subscription.cancellation_reason = reason

        if cancel_immediately:
            subscription.status = SubscriptionStatus.CANCELED
            subscription.ended_at = now
        else:
            subscription.cancel_at_period_end = True

        subscription.updated_at = now
        return subscription

    async def reactivate_subscription(self, subscription_id: str) -> Subscription:
        subscription = self.subscriptions.get(subscription_id)
        if not subscription:
            raise SubscriptionNotFoundError(
                f"Subscription not found: {subscription_id}",
                code="subscription_not_found",
                provider=self.name,
            )

        if subscription.status == SubscriptionStatus.CANCELED:
            raise BillingProviderError(
                "Cannot reactivate a canceled subscription",
                code="subscription_canceled",
                provider=self.name,
            )

        subscription.cancel_at_period_end = False
        subscription.canceled_at = None
        subscription.cancellation_reason = None
        subscription.updated_at = datetime.utcnow()
        return subscription

    # =========================================================================
    # Payment Method Operations
    # =========================================================================

    async def attach_payment_method(
        self,
        request: CreatePaymentMethodRequest,
    ) -> PaymentMethod:
        customer = self.customers.get(request.customer_id)
        if not customer:
            raise CustomerNotFoundError(
                f"Customer not found: {request.customer_id}",
                code="customer_not_found",
                provider=self.name,
            )

        # Create mock card details
        payment_method = PaymentMethod(
            customer_id=request.customer_id,
            provider_payment_method_id=request.provider_payment_method_id,
            type=PaymentMethodType.CARD,
            is_default=request.set_as_default,
            card=CardDetails(
                brand="visa",
                last4="4242",
                exp_month=12,
                exp_year=2030,
                funding="credit",
                country="US",
            ),
            billing_email=customer.email,
        )

        # If setting as default, unset other defaults
        if request.set_as_default:
            for pm in self.payment_methods.values():
                if pm.customer_id == request.customer_id:
                    pm.is_default = False

        self.payment_methods[payment_method.id] = payment_method
        return payment_method

    async def get_payment_methods(self, customer_id: str) -> List[PaymentMethod]:
        return [
            pm for pm in self.payment_methods.values()
            if pm.customer_id == customer_id
        ]

    async def set_default_payment_method(
        self,
        customer_id: str,
        payment_method_id: str,
    ) -> PaymentMethod:
        pm = self.payment_methods.get(payment_method_id)
        if not pm or pm.customer_id != customer_id:
            raise PaymentMethodError(
                f"Payment method not found: {payment_method_id}",
                code="payment_method_not_found",
                provider=self.name,
            )

        # Unset other defaults
        for other in self.payment_methods.values():
            if other.customer_id == customer_id:
                other.is_default = False

        pm.is_default = True
        pm.updated_at = datetime.utcnow()
        return pm

    async def detach_payment_method(self, payment_method_id: str) -> bool:
        if payment_method_id in self.payment_methods:
            del self.payment_methods[payment_method_id]
            return True
        return False

    # =========================================================================
    # Invoice Operations
    # =========================================================================

    async def get_invoice(self, invoice_id: str) -> Optional[Invoice]:
        return self.invoices.get(invoice_id)

    async def get_invoices_for_customer(
        self,
        customer_id: str,
        limit: int = 10,
        starting_after: Optional[str] = None,
    ) -> List[Invoice]:
        invoices = [
            inv for inv in self.invoices.values()
            if inv.customer_id == customer_id
        ]
        invoices.sort(key=lambda i: i.created_at, reverse=True)

        # Handle pagination
        if starting_after:
            found = False
            filtered = []
            for inv in invoices:
                if found:
                    filtered.append(inv)
                elif inv.id == starting_after:
                    found = True
            invoices = filtered

        return invoices[:limit]

    async def get_upcoming_invoice(self, subscription_id: str) -> Optional[Invoice]:
        subscription = self.subscriptions.get(subscription_id)
        if not subscription or not subscription.is_active:
            return None

        # Create preview invoice
        customer = self.customers.get(subscription.customer_id)
        if not customer:
            return None

        invoice = Invoice(
            customer_id=subscription.customer_id,
            subscription_id=subscription_id,
            status=InvoiceStatus.DRAFT,
            subtotal=subscription.unit_amount,
            total=subscription.unit_amount,
            amount_due=subscription.unit_amount,
            period_start=subscription.current_period_end,
            period_end=subscription.current_period_end + timedelta(days=30),
            due_date=subscription.current_period_end,
            line_items=[
                InvoiceLineItem(
                    description=f"{subscription.plan.value.title()} Plan ({subscription.billing_interval})",
                    quantity=1,
                    unit_amount=subscription.unit_amount,
                    amount=subscription.unit_amount,
                )
            ],
        )

        return invoice

    # =========================================================================
    # Usage Operations
    # =========================================================================

    async def record_usage(self, request: RecordUsageRequest) -> None:
        subscription = self.subscriptions.get(request.subscription_id)
        if not subscription:
            raise SubscriptionNotFoundError(
                f"Subscription not found: {request.subscription_id}",
                code="subscription_not_found",
                provider=self.name,
            )

        # Check idempotency
        if request.idempotency_key:
            for record in self.usage_records:
                if record.idempotency_key == request.idempotency_key:
                    return  # Already recorded

        # Check limits if enforcing
        if self.enforce_limits:
            limits = subscription.get_limits()
            current = await self.get_usage(subscription.id, request.metric)
            limit = self._get_metric_limit(limits, request.metric)

            if limit > 0 and current.total_quantity + request.quantity > limit:
                raise UsageLimitExceededError(
                    f"Usage limit exceeded for {request.metric.value}",
                    metric=request.metric,
                    current=current.total_quantity,
                    limit=limit,
                    code="usage_limit_exceeded",
                    provider=self.name,
                )

        # Record usage
        record = UsageRecord(
            subscription_id=request.subscription_id,
            metric=request.metric,
            quantity=request.quantity,
            timestamp=request.timestamp or datetime.utcnow(),
            action_id=request.action_id,
            run_id=request.run_id,
            idempotency_key=request.idempotency_key,
            metadata=request.metadata,
        )

        self.usage_records.append(record)

    def _get_metric_limit(self, limits: Any, metric: UsageMetric) -> int:
        """Get the limit value for a usage metric from plan limits."""
        mapping = {
            UsageMetric.TOKENS: limits.monthly_tokens,
            UsageMetric.API_CALLS: limits.monthly_api_calls,
            UsageMetric.STORAGE_BYTES: limits.storage_bytes,
            UsageMetric.PROJECTS: limits.max_projects,
            UsageMetric.MEMBERS: limits.max_members,
            UsageMetric.AGENTS: limits.max_agents,
        }
        return mapping.get(metric, -1)

    async def get_usage(
        self,
        subscription_id: str,
        metric: UsageMetric,
    ) -> UsageAggregate:
        subscription = self.subscriptions.get(subscription_id)
        if not subscription:
            raise SubscriptionNotFoundError(
                f"Subscription not found: {subscription_id}",
                code="subscription_not_found",
                provider=self.name,
            )

        # Filter records for this subscription/metric in current period
        period_start = subscription.current_period_start
        period_end = subscription.current_period_end

        matching = [
            r for r in self.usage_records
            if r.subscription_id == subscription_id
            and r.metric == metric
            and period_start <= r.timestamp <= period_end
        ]

        total = sum(r.quantity for r in matching)
        limits = subscription.get_limits()
        limit = self._get_metric_limit(limits, metric)

        remaining = max(0, limit - total) if limit > 0 else -1
        percentage = (total / limit * 100) if limit > 0 else 0.0

        return UsageAggregate(
            subscription_id=subscription_id,
            metric=metric,
            period_start=period_start,
            period_end=period_end,
            total_quantity=total,
            record_count=len(matching),
            limit=limit,
            remaining=remaining,
            percentage_used=min(100.0, percentage),
            first_usage_at=min((r.timestamp for r in matching), default=None),
            last_usage_at=max((r.timestamp for r in matching), default=None),
        )

    async def get_all_usage(
        self,
        subscription_id: str,
    ) -> Dict[UsageMetric, UsageAggregate]:
        result = {}
        for metric in UsageMetric:
            result[metric] = await self.get_usage(subscription_id, metric)
        return result

    # =========================================================================
    # Checkout Operations
    # =========================================================================

    async def create_checkout_session(
        self,
        request: CreateCheckoutRequest,
    ) -> CheckoutSession:
        session = CheckoutSession(
            customer_id=request.customer_id,
            provider_session_id=_generate_id("cs"),
            mode="subscription",
            status="open",
            success_url=request.success_url,
            cancel_url=request.cancel_url,
            url=f"https://mock-checkout.example.com/{_generate_id('checkout')}",
            plan=request.plan,
            billing_interval=request.billing_interval,
        )

        self.checkout_sessions[session.id] = session
        return session

    async def get_checkout_session(self, session_id: str) -> Optional[CheckoutSession]:
        return self.checkout_sessions.get(session_id)

    # =========================================================================
    # Portal Operations
    # =========================================================================

    async def create_portal_session(
        self,
        request: CreatePortalSessionRequest,
    ) -> BillingPortalSession:
        customer = self.customers.get(request.customer_id)
        if not customer:
            raise CustomerNotFoundError(
                f"Customer not found: {request.customer_id}",
                code="customer_not_found",
                provider=self.name,
            )

        session = BillingPortalSession(
            customer_id=request.customer_id,
            provider_session_id=_generate_id("bps"),
            url=f"https://mock-portal.example.com/{_generate_id('portal')}",
            return_url=request.return_url,
        )

        self.portal_sessions[session.id] = session
        return session

    # =========================================================================
    # Webhook Operations
    # =========================================================================

    async def verify_webhook(
        self,
        payload: bytes,
        signature: str,
    ) -> WebhookEvent:
        # Mock verification - accept any signature starting with "mock_"
        if not signature.startswith("mock_"):
            raise WebhookVerificationError(
                "Invalid webhook signature",
                code="invalid_signature",
                provider=self.name,
            )

        import json
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as e:
            raise WebhookVerificationError(
                f"Invalid webhook payload: {e}",
                code="invalid_payload",
                provider=self.name,
            )

        event = WebhookEvent(
            provider=self.name,
            provider_event_id=data.get("id", _generate_id("evt")),
            type=WebhookEventType(data.get("type", "customer.created")),
            data=data.get("data", {}),
        )

        return event

    async def process_webhook(self, event: WebhookEvent) -> WebhookEventResult:
        self.webhook_events.append(event)

        actions = []

        # Process based on event type
        if event.type == WebhookEventType.SUBSCRIPTION_UPDATED:
            actions.append("Updated subscription status")
        elif event.type == WebhookEventType.INVOICE_PAID:
            actions.append("Marked invoice as paid")
        elif event.type == WebhookEventType.PAYMENT_INTENT_FAILED:
            actions.append("Logged payment failure")

        event.processed = True
        event.processed_at = datetime.utcnow()

        return WebhookEventResult(
            event_id=event.id,
            success=True,
            message="Webhook processed successfully",
            actions_taken=actions,
        )

    # =========================================================================
    # Test Helpers
    # =========================================================================

    def simulate_payment_success(self, subscription_id: str) -> None:
        """Simulate a successful payment for testing."""
        subscription = self.subscriptions.get(subscription_id)
        if subscription:
            subscription.status = SubscriptionStatus.ACTIVE
            subscription.updated_at = datetime.utcnow()

    def simulate_payment_failure(self, subscription_id: str) -> None:
        """Simulate a failed payment for testing."""
        subscription = self.subscriptions.get(subscription_id)
        if subscription:
            subscription.status = SubscriptionStatus.PAST_DUE
            subscription.updated_at = datetime.utcnow()

    def advance_time(self, days: int) -> None:
        """Advance subscription periods for time-based testing."""
        delta = timedelta(days=days)
        for subscription in self.subscriptions.values():
            subscription.current_period_start += delta
            subscription.current_period_end += delta
            if subscription.trial_end:
                subscription.trial_end += delta


__all__ = ["MockBillingProvider"]
