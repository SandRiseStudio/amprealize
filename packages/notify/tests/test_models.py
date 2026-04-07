"""
Tests for notify models.
"""

import pytest
from datetime import datetime
from notify.models import (
    Channel,
    NotificationStatus,
    Priority,
    Recipient,
    NotificationRequest,
    NotificationResult,
    BatchNotificationResult,
)


class TestChannel:
    """Tests for Channel enum."""

    def test_channel_values(self):
        """Test all expected channel values exist."""
        assert Channel.EMAIL.value == "email"
        assert Channel.SLACK.value == "slack"
        assert Channel.SMS.value == "sms"
        assert Channel.COPY_LINK.value == "copy_link"
        assert Channel.CONSOLE.value == "console"

    def test_channel_from_string(self):
        """Test creating channel from string value."""
        assert Channel("email") == Channel.EMAIL
        assert Channel("slack") == Channel.SLACK
        assert Channel("sms") == Channel.SMS


class TestNotificationStatus:
    """Tests for NotificationStatus enum."""

    def test_status_values(self):
        """Test all expected status values exist."""
        assert NotificationStatus.PENDING.value == "pending"
        assert NotificationStatus.SENT.value == "sent"
        assert NotificationStatus.DELIVERED.value == "delivered"
        assert NotificationStatus.FAILED.value == "failed"
        assert NotificationStatus.BOUNCED.value == "bounced"


class TestPriority:
    """Tests for Priority enum."""

    def test_priority_values(self):
        """Test all expected priority values exist."""
        assert Priority.LOW.value == "low"
        assert Priority.NORMAL.value == "normal"
        assert Priority.HIGH.value == "high"
        assert Priority.URGENT.value == "urgent"


class TestRecipient:
    """Tests for Recipient dataclass."""

    def test_recipient_with_email(self):
        """Test creating recipient with email."""
        recipient = Recipient(email="test@example.com")
        assert recipient.email == "test@example.com"
        assert recipient.phone is None
        assert recipient.slack_id is None
        assert recipient.name is None

    def test_recipient_with_all_fields(self):
        """Test creating recipient with all fields."""
        recipient = Recipient(
            email="test@example.com",
            phone="+15551234567",
            slack_id="U12345678",
            name="Test User",
            metadata={"department": "Engineering"},
        )
        assert recipient.email == "test@example.com"
        assert recipient.phone == "+15551234567"
        assert recipient.slack_id == "U12345678"
        assert recipient.name == "Test User"
        assert recipient.metadata == {"department": "Engineering"}

    def test_recipient_validation_no_contact(self):
        """Test that recipient requires at least one contact method."""
        with pytest.raises(ValueError, match="at least one contact"):
            Recipient()

    def test_recipient_to_dict(self):
        """Test recipient serialization."""
        recipient = Recipient(
            email="test@example.com",
            name="Test User",
        )
        data = recipient.to_dict()
        assert data["email"] == "test@example.com"
        assert data["name"] == "Test User"
        assert data["phone"] is None


class TestNotificationRequest:
    """Tests for NotificationRequest dataclass."""

    def test_simple_request(self):
        """Test creating a simple notification request."""
        recipient = Recipient(email="test@example.com")
        request = NotificationRequest(
            notification_type="invite",
            channel=Channel.EMAIL,
            recipient=recipient,
            context={"org_name": "Acme Corp"},
        )
        assert request.notification_type == "invite"
        assert request.channel == Channel.EMAIL
        assert request.recipient == recipient
        assert request.context == {"org_name": "Acme Corp"}
        assert request.priority == Priority.NORMAL

    def test_request_with_all_fields(self):
        """Test request with all optional fields."""
        recipient = Recipient(email="test@example.com")
        request = NotificationRequest(
            notification_type="alert",
            channel=Channel.EMAIL,
            recipient=recipient,
            context={"message": "System alert"},
            priority=Priority.URGENT,
            idempotency_key="alert-123",
            metadata={"source": "monitoring"},
        )
        assert request.priority == Priority.URGENT
        assert request.idempotency_key == "alert-123"
        assert request.metadata == {"source": "monitoring"}

    def test_request_id_generated(self):
        """Test that request ID is auto-generated."""
        recipient = Recipient(email="test@example.com")
        request = NotificationRequest(
            notification_type="invite",
            channel=Channel.EMAIL,
            recipient=recipient,
            context={},
        )
        assert request.id is not None
        assert len(request.id) > 0


class TestNotificationResult:
    """Tests for NotificationResult dataclass."""

    def test_success_result(self):
        """Test creating a success result."""
        result = NotificationResult(
            request_id="req-123",
            channel=Channel.EMAIL,
            status=NotificationStatus.SENT,
            provider="sendgrid",
        )
        assert result.request_id == "req-123"
        assert result.channel == Channel.EMAIL
        assert result.status == NotificationStatus.SENT
        assert result.success is True
        assert result.error_message is None

    def test_failure_result(self):
        """Test creating a failure result."""
        result = NotificationResult(
            request_id="req-123",
            channel=Channel.EMAIL,
            status=NotificationStatus.FAILED,
            provider="smtp",
            error_message="Connection refused",
        )
        assert result.success is False
        assert result.error_message == "Connection refused"

    def test_result_with_metadata(self):
        """Test result with provider metadata."""
        result = NotificationResult(
            request_id="req-123",
            channel=Channel.EMAIL,
            status=NotificationStatus.SENT,
            provider="sendgrid",
            provider_message_id="sg-msg-456",
            metadata={"batch_id": "batch-789"},
        )
        assert result.provider_message_id == "sg-msg-456"
        assert result.metadata == {"batch_id": "batch-789"}

    def test_result_to_dict(self):
        """Test result serialization."""
        result = NotificationResult(
            request_id="req-123",
            channel=Channel.EMAIL,
            status=NotificationStatus.SENT,
            provider="sendgrid",
        )
        data = result.to_dict()
        assert data["request_id"] == "req-123"
        assert data["channel"] == "email"
        assert data["status"] == "sent"
        assert data["success"] is True


class TestBatchNotificationResult:
    """Tests for BatchNotificationResult dataclass."""

    def test_empty_batch(self):
        """Test empty batch result."""
        batch = BatchNotificationResult(results=[])
        assert batch.total_count == 0
        assert batch.success_count == 0
        assert batch.failure_count == 0
        assert batch.success_rate == 0.0

    def test_all_success_batch(self):
        """Test batch with all successful results."""
        results = [
            NotificationResult(
                request_id=f"req-{i}",
                channel=Channel.EMAIL,
                status=NotificationStatus.SENT,
                provider="sendgrid",
            )
            for i in range(3)
        ]
        batch = BatchNotificationResult(results=results)
        assert batch.total_count == 3
        assert batch.success_count == 3
        assert batch.failure_count == 0
        assert batch.success_rate == 100.0

    def test_mixed_batch(self):
        """Test batch with mixed success/failure."""
        results = [
            NotificationResult(
                request_id="req-1",
                channel=Channel.EMAIL,
                status=NotificationStatus.SENT,
                provider="sendgrid",
            ),
            NotificationResult(
                request_id="req-2",
                channel=Channel.EMAIL,
                status=NotificationStatus.FAILED,
                provider="sendgrid",
                error_message="Invalid email",
            ),
            NotificationResult(
                request_id="req-3",
                channel=Channel.SMS,
                status=NotificationStatus.SENT,
                provider="twilio",
            ),
        ]
        batch = BatchNotificationResult(results=results)
        assert batch.total_count == 3
        assert batch.success_count == 2
        assert batch.failure_count == 1
        assert batch.success_rate == pytest.approx(66.67, rel=0.01)

    def test_batch_to_dict(self):
        """Test batch serialization."""
        results = [
            NotificationResult(
                request_id="req-1",
                channel=Channel.EMAIL,
                status=NotificationStatus.SENT,
                provider="sendgrid",
            ),
        ]
        batch = BatchNotificationResult(results=results)
        data = batch.to_dict()
        assert data["total_count"] == 1
        assert data["success_count"] == 1
        assert data["failure_count"] == 0
        assert len(data["results"]) == 1
