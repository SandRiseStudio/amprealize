"""
Notify - Multi-channel notification library for Amprealize.

A standalone notification package supporting Email, Slack, SMS, Copy-Link, and Console channels.
"""

from notify.models import (
    BatchNotificationResult,
    Channel,
    NotificationRequest,
    NotificationResult,
    NotificationStatus,
    Priority,
    Recipient,
)
from notify.service import NotifyService, create_service
from notify.templates import NotificationTemplate, TemplateEngine

__all__ = [
    # Models
    "BatchNotificationResult",
    "Channel",
    "NotificationRequest",
    "NotificationResult",
    "NotificationStatus",
    "Priority",
    "Recipient",
    # Service
    "NotifyService",
    "create_service",
    # Templates
    "NotificationTemplate",
    "TemplateEngine",
]

__version__ = "0.1.0"
