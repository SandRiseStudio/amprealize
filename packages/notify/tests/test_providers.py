"""
Tests for notify providers.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock

from notify.models import (
    Channel,
    NotificationStatus,
    Recipient,
    NotificationRequest,
)
from notify.providers.base import NotificationProvider
from notify.providers.console import ConsoleProvider
from notify.providers.copy_link import CopyLinkProvider
from notify.providers.email import EmailProvider
from notify.providers.slack import SlackProvider
from notify.providers.sms import SMSProvider


class TestNotificationProviderBase:
    """Tests for base NotificationProvider."""

    def test_cannot_instantiate_abstract(self):
        """Test that base class cannot be instantiated."""
        with pytest.raises(TypeError):
            NotificationProvider()  # type: ignore


class TestConsoleProvider:
    """Tests for ConsoleProvider."""

    @pytest.fixture
    def provider(self):
        """Create a console provider."""
        return ConsoleProvider()

    @pytest.fixture
    def notification_request(self):
        """Create a notification request."""
        return NotificationRequest(
            notification_type="invite",
            channel=Channel.CONSOLE,
            recipient=Recipient(email="test@example.com", name="Test User"),
            context={"org_name": "Acme Corp", "invite_url": "https://example.com/invite"},
        )

    def test_channel(self, provider):
        """Test provider channel."""
        assert provider.channel == Channel.CONSOLE

    def test_is_configured(self, provider):
        """Test console provider is always configured."""
        assert provider.is_configured() is True

    @pytest.mark.asyncio
    async def test_send_success(self, provider, notification_request, capsys):
        """Test sending console notification."""
        result = await provider.send(notification_request, subject="Test Subject", body="Test Body")

        assert result.status == NotificationStatus.SENT
        assert result.success is True
        assert result.provider == "console"

        captured = capsys.readouterr()
        assert "Test Subject" in captured.out
        assert "Test Body" in captured.out

    @pytest.mark.asyncio
    async def test_health_check(self, provider):
        """Test console provider health check."""
        health = await provider.health_check()
        assert health["healthy"] is True


class TestCopyLinkProvider:
    """Tests for CopyLinkProvider."""

    @pytest.fixture
    def provider(self):
        """Create a copy link provider."""
        return CopyLinkProvider(base_url="https://example.com")

    @pytest.fixture
    def notification_request(self):
        """Create a notification request."""
        return NotificationRequest(
            notification_type="invite",
            channel=Channel.COPY_LINK,
            recipient=Recipient(email="test@example.com"),
            context={"org_name": "Acme Corp", "token": "abc123"},
        )

    def test_channel(self, provider):
        """Test provider channel."""
        assert provider.channel == Channel.COPY_LINK

    def test_is_configured(self, provider):
        """Test provider is configured with base_url."""
        assert provider.is_configured() is True

    def test_is_not_configured(self):
        """Test provider is not configured without base_url."""
        provider = CopyLinkProvider()
        assert provider.is_configured() is False

    @pytest.mark.asyncio
    async def test_send_with_invite_url_in_context(self, provider):
        """Test sending with invite_url in context uses it directly."""
        req = NotificationRequest(
            notification_type="invite",
            channel=Channel.COPY_LINK,
            recipient=Recipient(email="test@example.com"),
            context={"invite_url": "https://custom.com/invite/xyz"},
        )
        result = await provider.send(req, body="test")

        assert result.status == NotificationStatus.SENT
        assert result.metadata["url"] == "https://custom.com/invite/xyz"

    @pytest.mark.asyncio
    async def test_send_generates_url(self, provider, notification_request):
        """Test sending generates URL from token."""
        result = await provider.send(notification_request, body="test")

        assert result.status == NotificationStatus.SENT
        assert "url" in result.metadata
        assert "abc123" in result.metadata["url"]

    @pytest.mark.asyncio
    async def test_send_without_url_or_token(self, provider):
        """Test sending without invite_url or token fails."""
        req = NotificationRequest(
            notification_type="invite",
            channel=Channel.COPY_LINK,
            recipient=Recipient(email="test@example.com"),
            context={},
        )
        result = await provider.send(req, body="test")

        assert result.status == NotificationStatus.FAILED

    @pytest.mark.asyncio
    async def test_health_check(self, provider):
        """Test copy link provider health check."""
        health = await provider.health_check()
        assert health["healthy"] is True


class TestEmailProvider:
    """Tests for EmailProvider."""

    @pytest.fixture
    def smtp_provider(self):
        """Create an SMTP email provider."""
        return EmailProvider(
            backend="smtp",
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_username="user@example.com",
            smtp_password="password",
            from_email="noreply@example.com",
            from_name="Test App",
        )

    @pytest.fixture
    def sendgrid_provider(self):
        """Create a SendGrid email provider."""
        return EmailProvider(
            backend="sendgrid",
            sendgrid_api_key="SG.test-api-key",
            from_email="noreply@example.com",
        )

    @pytest.fixture
    def notification_request(self):
        """Create a notification request."""
        return NotificationRequest(
            notification_type="invite",
            channel=Channel.EMAIL,
            recipient=Recipient(email="test@example.com", name="Test User"),
            context={"org_name": "Acme Corp"},
        )

    def test_channel(self, smtp_provider):
        """Test provider channel."""
        assert smtp_provider.channel == Channel.EMAIL

    def test_smtp_is_configured(self, smtp_provider):
        """Test SMTP provider is configured."""
        assert smtp_provider.is_configured() is True

    def test_smtp_not_configured(self):
        """Test SMTP provider without host is not configured."""
        provider = EmailProvider(backend="smtp", from_email="test@example.com")
        assert provider.is_configured() is False

    def test_sendgrid_is_configured(self, sendgrid_provider):
        """Test SendGrid provider is configured."""
        assert sendgrid_provider.is_configured() is True

    def test_sendgrid_not_configured(self):
        """Test SendGrid provider without API key is not configured."""
        provider = EmailProvider(backend="sendgrid", from_email="test@example.com")
        assert provider.is_configured() is False

    @pytest.mark.asyncio
    async def test_send_requires_email(self, smtp_provider):
        """Test sending requires recipient email."""
        req = NotificationRequest(
            notification_type="invite",
            channel=Channel.EMAIL,
            recipient=Recipient(phone="+15551234567"),  # No email
            context={},
        )
        result = await smtp_provider.send(
            req,
            subject="Test Subject",
            body="Test body",
        )

        assert result.status == NotificationStatus.FAILED
        assert "email" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_send_requires_subject(self, smtp_provider, notification_request):
        """Test sending requires subject."""
        result = await smtp_provider.send(
            notification_request,
            body="Test body",
        )

        assert result.status == NotificationStatus.FAILED
        assert "subject" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_smtp_send_success(self, smtp_provider, notification_request):
        """Test successful SMTP send."""
        pytest.importorskip("aiosmtplib")
        with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            result = await smtp_provider.send(
                notification_request,
                subject="Test Subject",
                body="Test Body",
            )

            assert result.status == NotificationStatus.SENT
            assert result.success is True
            assert result.provider == "smtp"
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_smtp_send_failure(self, smtp_provider, notification_request):
        """Test SMTP send failure."""
        pytest.importorskip("aiosmtplib")
        with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = Exception("Auth failed")

            result = await smtp_provider.send(
                notification_request,
                subject="Test Subject",
                body="Test Body",
            )

            assert result.status == NotificationStatus.FAILED
            assert result.success is False
            assert "Auth failed" in result.error_message


class TestSlackProvider:
    """Tests for SlackProvider."""

    @pytest.fixture
    def webhook_provider(self):
        """Create a webhook-based Slack provider."""
        return SlackProvider(
            backend="webhook",
            webhook_url="https://hooks.slack.com/services/T00/B00/XXX"
        )

    @pytest.fixture
    def api_provider(self):
        """Create an API-based Slack provider."""
        return SlackProvider(
            backend="api",
            api_token="xoxb-test-token"
        )

    @pytest.fixture
    def notification_request(self):
        """Create a notification request."""
        return NotificationRequest(
            notification_type="invite",
            channel=Channel.SLACK,
            recipient=Recipient(slack_id="U12345678"),
            context={"org_name": "Acme Corp"},
        )

    def test_channel(self, webhook_provider):
        """Test provider channel."""
        assert webhook_provider.channel == Channel.SLACK

    def test_webhook_is_configured(self, webhook_provider):
        """Test webhook provider is configured."""
        assert webhook_provider.is_configured() is True

    def test_api_is_configured(self, api_provider):
        """Test API provider is configured."""
        assert api_provider.is_configured() is True

    def test_not_configured(self):
        """Test provider without credentials."""
        provider = SlackProvider()
        assert provider.is_configured() is False

    @pytest.mark.asyncio
    async def test_webhook_send_success(self, webhook_provider, notification_request):
        """Test successful webhook send."""
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = "ok"
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = mock_client

            result = await webhook_provider.send(
                notification_request,
                body="You've been invited to Acme Corp!",
            )

            assert result.status == NotificationStatus.SENT
            assert result.success is True
            assert result.provider == "slack_webhook"

    @pytest.mark.asyncio
    async def test_api_requires_slack_id(self, api_provider):
        """Test API send requires slack_id."""
        req = NotificationRequest(
            notification_type="invite",
            channel=Channel.SLACK,
            recipient=Recipient(email="test@example.com"),  # No slack_id
            context={},
        )
        result = await api_provider.send(req, body="Test")

        assert result.status == NotificationStatus.FAILED
        assert "slack" in result.error_message.lower()


class TestSMSProvider:
    """Tests for SMSProvider."""

    @pytest.fixture
    def provider(self):
        """Create a Twilio SMS provider."""
        return SMSProvider(
            account_sid="ACtest123",
            auth_token="auth_token_test",
            from_number="+15551234567",
        )

    @pytest.fixture
    def notification_request(self):
        """Create a notification request."""
        return NotificationRequest(
            notification_type="alert",
            channel=Channel.SMS,
            recipient=Recipient(phone="+15559876543"),
            context={"message": "System alert"},
        )

    def test_channel(self, provider):
        """Test provider channel."""
        assert provider.channel == Channel.SMS

    def test_is_configured(self, provider):
        """Test provider is configured."""
        assert provider.is_configured() is True

    def test_not_configured(self):
        """Test provider without credentials."""
        provider = SMSProvider()
        assert provider.is_configured() is False

    def test_partial_config(self):
        """Test provider with partial credentials."""
        provider = SMSProvider(account_sid="ACtest123")
        assert provider.is_configured() is False

    @pytest.mark.asyncio
    async def test_send_requires_phone(self, provider):
        """Test sending requires recipient phone."""
        req = NotificationRequest(
            notification_type="alert",
            channel=Channel.SMS,
            recipient=Recipient(email="test@example.com"),  # No phone
            context={},
        )
        result = await provider.send(req, body="Test alert")

        assert result.status == NotificationStatus.FAILED
        assert "phone" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_send_requires_body(self, provider, notification_request):
        """Test sending requires body."""
        result = await provider.send(notification_request)

        assert result.status == NotificationStatus.FAILED
        assert "body" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_send_success(self, provider, notification_request):
        """Test successful SMS send."""
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_response = Mock()
            mock_response.status_code = 201
            mock_response.json.return_value = {"sid": "SM123"}
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = mock_client

            result = await provider.send(
                notification_request,
                body="System alert: Check server status",
            )

            assert result.status == NotificationStatus.SENT
            assert result.success is True
            assert result.provider == "twilio"
            assert result.provider_message_id == "SM123"

    @pytest.mark.asyncio
    async def test_send_failure(self, provider, notification_request):
        """Test SMS send failure."""
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_response = Mock()
            mock_response.status_code = 400
            mock_response.json.return_value = {"message": "Invalid phone number"}
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = mock_client

            result = await provider.send(
                notification_request,
                body="System alert",
            )

            assert result.status == NotificationStatus.FAILED
            assert result.success is False
