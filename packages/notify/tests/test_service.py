"""
Tests for NotifyService.
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch

from notify.models import (
    Channel,
    NotificationStatus,
    Recipient,
    NotificationRequest,
)
from notify.service import NotifyService, create_service
from notify.providers.console import ConsoleProvider


class TestNotifyService:
    """Tests for NotifyService."""

    @pytest.fixture
    def service(self):
        """Create a NotifyService."""
        return NotifyService()

    @pytest.fixture
    def notification_request(self):
        """Create a notification request."""
        return NotificationRequest(
            notification_type="invite",
            channel=Channel.EMAIL,
            recipient=Recipient(email="test@example.com", name="Test User"),
            context={"org_name": "Acme Corp"},
        )

    def test_register_provider(self, service):
        """Test registering a provider."""
        provider = ConsoleProvider()
        service.register_provider(provider)

        assert Channel.CONSOLE in service._providers
        assert service.get_provider(Channel.CONSOLE) == provider

    def test_get_provider_not_found(self, service):
        """Test getting a provider that doesn't exist."""
        assert service.get_provider(Channel.EMAIL) is None

    @pytest.mark.asyncio
    async def test_send_no_provider(self, service, notification_request):
        """Test sending when no provider is registered."""
        result = await service.send(notification_request, body="Test")

        assert result.status == NotificationStatus.FAILED
        assert "no provider" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_send_success(self, service):
        """Test successful send."""
        console = ConsoleProvider()
        service.register_provider(console)

        req = NotificationRequest(
            notification_type="test",
            channel=Channel.CONSOLE,
            recipient=Recipient(email="test@example.com"),
            context={},
        )

        result = await service.send(req, subject="Test", body="Test message")

        assert result.status == NotificationStatus.SENT
        assert result.success is True

    @pytest.mark.asyncio
    async def test_send_multi_channel(self, service):
        """Test sending to multiple channels."""
        console = ConsoleProvider()
        service.register_provider(console)

        recipient = Recipient(email="test@example.com")

        result = await service.send_multi_channel(
            notification_type="test",
            recipient=recipient,
            channels=[Channel.CONSOLE],
            context={},
            subject="Multi Test",
            body="Test message",
        )

        assert result.total_count == 1
        assert result.success_count == 1
        assert result.failure_count == 0

    @pytest.mark.asyncio
    async def test_health_check(self, service):
        """Test health check."""
        console = ConsoleProvider()
        service.register_provider(console)

        health = await service.health_check()

        assert health["healthy"] is True
        assert "providers" in health
        assert "console" in health["providers"]


class TestCreateService:
    """Tests for create_service factory function."""

    def test_create_default_service(self):
        """Test creating default service."""
        service = create_service()

        assert isinstance(service, NotifyService)
        # Console provider should be registered by default
        assert service.get_provider(Channel.CONSOLE) is not None

    def test_create_service_with_console(self):
        """Test creating service with console enabled."""
        service = create_service(enable_console=True)

        assert service.get_provider(Channel.CONSOLE) is not None

    def test_create_service_without_console(self):
        """Test creating service without console."""
        service = create_service(enable_console=False)

        assert service.get_provider(Channel.CONSOLE) is None
