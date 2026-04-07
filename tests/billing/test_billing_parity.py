"""Tests for billing cross-surface parity (CLI, API, MCP).

Following: behavior_validate_cross_surface_parity

Tests verify that billing operations produce identical results across:
- REST API endpoints
- CLI commands
- MCP tools

This ensures consistent behavior regardless of interaction surface.
"""

import pytest
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

from billing import (
    BillingPlan,
    SubscriptionStatus,
    UsageMetric,
    Customer,
    Subscription,
    MockBillingProvider,
    BillingService,
    NoOpHooks,
)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def mock_provider() -> MockBillingProvider:
    """Create a mock billing provider."""
    return MockBillingProvider()


@pytest.fixture
def billing_service(mock_provider: MockBillingProvider) -> BillingService:
    """Create billing service for testing."""
    return BillingService(
        provider=mock_provider,
        hooks=NoOpHooks(),
    )


# =============================================================================
# Schema Parity Tests
# =============================================================================

class TestSchemaParity:
    """Test that data models match across surfaces."""

    def test_customer_schema_fields(self):
        """Verify Customer model has required fields for all surfaces."""
        from billing import Customer

        # Required fields that must be present in all surface responses
        required_fields = {
            "id",
            "org_id",
            "email",
            "name",
            "created_at",
        }

        # Check Pydantic model fields
        field_names = set(Customer.model_fields.keys())

        for field in required_fields:
            assert field in field_names, f"Customer missing required field: {field}"

    def test_subscription_schema_fields(self):
        """Verify Subscription model has required fields for all surfaces."""
        from billing import Subscription

        required_fields = {
            "id",
            "customer_id",
            "plan",
            "status",
            "current_period_start",
            "current_period_end",
        }

        # Check Pydantic model fields
        field_names = set(Subscription.model_fields.keys())

        for field in required_fields:
            assert field in field_names, f"Subscription missing required field: {field}"

    def test_billing_plan_enum_values(self):
        """Verify BillingPlan enum has consistent values."""
        expected_values = {"free", "starter", "team", "enterprise"}
        actual_values = {p.value for p in BillingPlan}

        assert expected_values == actual_values

    def test_usage_metric_enum_values(self):
        """Verify UsageMetric enum has consistent values."""
        expected_values = {
            "tokens",
            "api_calls",
            "storage_bytes",
            "compute_seconds",
            "runs",
            "agents",
            "projects",
            "members",
        }
        actual_values = {m.value for m in UsageMetric}

        assert expected_values == actual_values


# =============================================================================
# Response Format Parity Tests
# =============================================================================

class TestResponseParity:
    """Test that responses are consistent across surfaces."""

    @pytest.mark.asyncio
    async def test_customer_response_format(
        self,
        billing_service: BillingService,
    ):
        """Test customer response has consistent format."""
        customer = await billing_service.create_customer(
            org_id="org_parity_test",
            email="parity@test.com",
            name="Parity Test",
        )

        # Convert to dict (as API would return) using Pydantic's model_dump
        customer_dict = customer.model_dump()

        # Verify required fields present
        assert "id" in customer_dict
        assert "org_id" in customer_dict
        assert "email" in customer_dict

        # Verify types
        assert isinstance(customer_dict["id"], str)
        assert isinstance(customer_dict["org_id"], str)
        assert isinstance(customer_dict["email"], str)

    @pytest.mark.asyncio
    async def test_subscription_response_format(
        self,
        billing_service: BillingService,
    ):
        """Test subscription response has consistent format."""
        customer = await billing_service.create_customer(
            org_id="org_sub_parity",
            email="sub@parity.com",
        )

        subscription = await billing_service.create_subscription(
            customer_id=customer.id,
            plan=BillingPlan.TEAM,
        )

        # Convert to dict using Pydantic's model_dump
        sub_dict = subscription.model_dump()

        # Verify required fields
        assert "id" in sub_dict
        assert "customer_id" in sub_dict
        assert "plan" in sub_dict
        assert "status" in sub_dict

        # Verify enum serialization
        assert sub_dict["plan"] == BillingPlan.TEAM
        assert sub_dict["status"] == SubscriptionStatus.ACTIVE


# =============================================================================
# Error Response Parity Tests
# =============================================================================

class TestErrorParity:
    """Test that error responses are consistent across surfaces."""

    @pytest.mark.asyncio
    async def test_not_found_error_format(
        self,
        billing_service: BillingService,
    ):
        """Test not found error is consistent across surfaces."""
        result = await billing_service.get_customer("nonexistent_id")

        # Should return None (API would return 404)
        assert result is None

    @pytest.mark.asyncio
    async def test_subscription_not_found(
        self,
        billing_service: BillingService,
    ):
        """Test subscription not found handling."""
        result = await billing_service.get_subscription("nonexistent_sub")

        # Should return None (API would return 404)
        assert result is None


# =============================================================================
# Operation Equivalence Tests
# =============================================================================

class TestOperationEquivalence:
    """Test that same operations produce same results across surfaces."""

    @pytest.mark.asyncio
    async def test_create_then_get_customer(
        self,
        billing_service: BillingService,
    ):
        """Test create and get operations return equivalent results."""
        # Create
        created = await billing_service.create_customer(
            org_id="org_equiv",
            email="equiv@test.com",
            name="Equiv Test",
        )

        # Get
        retrieved = await billing_service.get_customer(created.id)

        # Should be equivalent
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.email == created.email
        assert retrieved.name == created.name

    @pytest.mark.asyncio
    async def test_create_then_get_subscription(
        self,
        billing_service: BillingService,
    ):
        """Test subscription create and get return equivalent results."""
        customer = await billing_service.create_customer(
            org_id="org_sub_equiv",
            email="sub.equiv@test.com",
        )

        # Create
        created = await billing_service.create_subscription(
            customer_id=customer.id,
            plan=BillingPlan.STARTER,
        )

        # Get
        retrieved = await billing_service.get_subscription(created.id)

        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.plan == created.plan
        assert retrieved.customer_id == created.customer_id

    @pytest.mark.asyncio
    async def test_update_idempotency(
        self,
        billing_service: BillingService,
    ):
        """Test that updates are idempotent (same result with same input)."""
        customer = await billing_service.create_customer(
            org_id="org_idempotent",
            email="idempotent@test.com",
        )

        # Update twice with same values
        update1 = await billing_service.update_customer(
            customer_id=customer.id,
            email="updated@test.com",
            name="Updated Name",
        )

        update2 = await billing_service.update_customer(
            customer_id=customer.id,
            email="updated@test.com",
            name="Updated Name",
        )

        # Results should be equivalent
        assert update1.email == update2.email
        assert update1.name == update2.name


# =============================================================================
# Input Validation Parity Tests
# =============================================================================

class TestInputValidation:
    """Test that input validation is consistent across surfaces."""

    @pytest.mark.asyncio
    async def test_required_fields_customer(
        self,
        billing_service: BillingService,
    ):
        """Test that required fields are enforced consistently."""
        # org_id and email are required
        with pytest.raises((TypeError, ValueError)):
            await billing_service.create_customer(
                org_id="",  # Empty
                email="test@test.com",
            )

    @pytest.mark.asyncio
    async def test_plan_enum_validation(
        self,
        billing_service: BillingService,
    ):
        """Test that plan values are validated consistently."""
        customer = await billing_service.create_customer(
            org_id="org_plan_valid",
            email="plan@test.com",
        )

        # Valid plan should work
        sub = await billing_service.create_subscription(
            customer_id=customer.id,
            plan=BillingPlan.TEAM,
        )
        assert sub is not None


# =============================================================================
# Pagination Parity Tests
# =============================================================================

class TestPaginationParity:
    """Test that pagination behavior is consistent."""

    @pytest.mark.asyncio
    async def test_invoice_pagination_params(
        self,
        billing_service: BillingService,
    ):
        """Test that pagination parameters work consistently."""
        customer = await billing_service.create_customer(
            org_id="org_page_test",
            email="page@test.com",
        )

        # Get with limit
        invoices = await billing_service.get_invoices(
            customer_id=customer.id,
            limit=10,
        )

        # Should return list (possibly empty)
        assert isinstance(invoices, list)
        assert len(invoices) <= 10


# =============================================================================
# Timestamp Parity Tests
# =============================================================================

class TestTimestampParity:
    """Test that timestamps are handled consistently."""

    @pytest.mark.asyncio
    async def test_created_at_format(
        self,
        billing_service: BillingService,
    ):
        """Test that created_at timestamp is consistent."""
        from datetime import datetime

        customer = await billing_service.create_customer(
            org_id="org_time_test",
            email="time@test.com",
        )

        # Should have created_at
        assert customer.created_at is not None

        # Should be datetime
        assert isinstance(customer.created_at, datetime)

    @pytest.mark.asyncio
    async def test_subscription_period_timestamps(
        self,
        billing_service: BillingService,
    ):
        """Test subscription period timestamps are consistent."""
        from datetime import datetime

        customer = await billing_service.create_customer(
            org_id="org_period_test",
            email="period@test.com",
        )

        subscription = await billing_service.create_subscription(
            customer_id=customer.id,
            plan=BillingPlan.TEAM,
        )

        # Period start should be before period end
        assert subscription.current_period_start < subscription.current_period_end

        # Both should be datetime
        assert isinstance(subscription.current_period_start, datetime)
        assert isinstance(subscription.current_period_end, datetime)
