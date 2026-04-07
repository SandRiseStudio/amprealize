"""Amprealize Notify integration.

This module provides a thin wrapper around the standalone notify package,
wiring it to amprealize services (ActionService, ComplianceService, MetricsService).

For standalone usage without amprealize, use the notify package directly:
    pip install notify
    from notify import NotifyService, Channel, NotificationRequest

NOTE: The standalone notify package is REQUIRED. Install with:
    pip install -e ./packages/notify
"""

# Re-export models from standalone package
from notify import (
    # Channel types
    Channel,
    NotificationStatus,
    Priority,
    # Data models
    Recipient,
    NotificationRequest,
    NotificationResult,
    BatchNotificationResult,
    # Service and factory
    create_service,
    # Providers
    NotificationProvider,
    ConsoleProvider,
    CopyLinkProvider,
)

# Conditionally import providers that have dependencies
try:
    from notify import EmailProvider
except ImportError:
    EmailProvider = None  # type: ignore[misc,assignment]

try:
    from notify import SlackProvider
except ImportError:
    SlackProvider = None  # type: ignore[misc,assignment]

try:
    from notify import SMSProvider
except ImportError:
    SMSProvider = None  # type: ignore[misc,assignment]

# Template engine
from notify import NotificationTemplate, TemplateEngine

# Import the amprealize-integrated service wrapper
from .service import AmprealizeNotifyService as NotifyService

__all__ = [
    # Channel types
    "Channel",
    "NotificationStatus",
    "Priority",
    # Data models
    "Recipient",
    "NotificationRequest",
    "NotificationResult",
    "BatchNotificationResult",
    # Templates
    "NotificationTemplate",
    "TemplateEngine",
    # Provider base
    "NotificationProvider",
    "ConsoleProvider",
    "CopyLinkProvider",
    "EmailProvider",
    "SlackProvider",
    "SMSProvider",
    # Factory
    "create_service",
    # Service (amprealize-integrated wrapper)
    "NotifyService",
]
