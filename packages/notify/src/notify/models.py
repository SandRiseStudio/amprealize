"""
Core data models for the notification system.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4


class Channel(str, Enum):
    """Supported notification channels."""
    EMAIL = "email"
    SLACK = "slack"
    SMS = "sms"
    COPY_LINK = "copy_link"
    CONSOLE = "console"  # For testing/development


class NotificationStatus(str, Enum):
    """Status of a notification delivery."""
    PENDING = "pending"
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    BOUNCED = "bounced"
    EXPIRED = "expired"


class Priority(str, Enum):
    """Priority levels for notifications."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


@dataclass
class Recipient:
    """
    Represents a notification recipient.

    At least one of email, phone, or slack_id must be provided.
    """
    email: Optional[str] = None
    phone: Optional[str] = None
    slack_id: Optional[str] = None
    name: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate that at least one contact method is provided."""
        if not self.email and not self.phone and not self.slack_id:
            raise ValueError("Recipient must have at least one contact method (email, phone, or slack_id)")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "email": self.email,
            "phone": self.phone,
            "slack_id": self.slack_id,
            "name": self.name,
            "metadata": self.metadata,
        }


@dataclass
class NotificationRequest:
    """
    Request to send a notification.
    """
    notification_type: str  # e.g., "invite", "alert", "project_update"
    channel: Channel
    recipient: Recipient
    context: Dict[str, Any] = field(default_factory=dict)  # Template variables

    # Optional fields
    id: str = field(default_factory=lambda: str(uuid4()))
    priority: Priority = Priority.NORMAL
    idempotency_key: Optional[str] = None  # For deduplication
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "notification_type": self.notification_type,
            "channel": self.channel.value,
            "recipient": self.recipient.to_dict(),
            "context": self.context,
            "priority": self.priority.value,
            "idempotency_key": self.idempotency_key,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class NotificationResult:
    """
    Result of a notification send attempt.
    """
    request_id: str
    channel: Channel
    status: NotificationStatus
    provider: str  # e.g., "smtp", "sendgrid", "twilio", "slack_webhook"

    # Optional fields
    provider_message_id: Optional[str] = None  # ID from the provider
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    sent_at: Optional[datetime] = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Check if the notification was sent successfully."""
        return self.status in (NotificationStatus.SENT, NotificationStatus.DELIVERED)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "request_id": self.request_id,
            "channel": self.channel.value,
            "status": self.status.value,
            "provider": self.provider,
            "provider_message_id": self.provider_message_id,
            "success": self.success,
            "error_message": self.error_message,
            "error_code": self.error_code,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "metadata": self.metadata,
        }


@dataclass
class BatchNotificationResult:
    """
    Result of sending notifications to multiple recipients or channels.
    """
    results: List[NotificationResult] = field(default_factory=list)

    @property
    def total_count(self) -> int:
        """Total number of notifications attempted."""
        return len(self.results)

    @property
    def success_count(self) -> int:
        """Number of successful notifications."""
        return sum(1 for r in self.results if r.success)

    @property
    def failure_count(self) -> int:
        """Number of failed notifications."""
        return sum(1 for r in self.results if not r.success)

    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        if self.total_count == 0:
            return 0.0
        return round((self.success_count / self.total_count) * 100, 2)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_count": self.total_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": self.success_rate,
            "results": [r.to_dict() for r in self.results],
        }


# Legacy compatibility - used by original models
@dataclass
class NotificationTemplate:
    """
    Defines a notification template.

    Templates support multiple formats per channel and use Jinja2 syntax.
    """
    name: str
    description: Optional[str] = None
    subject_template: Optional[str] = None  # For email
    body_template: str = ""
    html_template: Optional[str] = None  # For email HTML
    slack_blocks_template: Optional[str] = None  # For Slack Block Kit
    metadata: Dict[str, Any] = field(default_factory=dict)
