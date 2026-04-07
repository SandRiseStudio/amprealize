"""
Base notification provider interface.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from notify.models import Channel, NotificationRequest, NotificationResult


class NotificationProvider(ABC):
    """
    Abstract base class for notification providers.

    Each provider implements sending notifications through a specific channel
    (e.g., email, Slack, SMS).
    """

    @property
    @abstractmethod
    def channel(self) -> Channel:
        """Return the channel this provider handles."""
        pass

    @abstractmethod
    def is_configured(self) -> bool:
        """
        Check if the provider is properly configured.

        Returns:
            True if the provider has all required configuration.
        """
        pass

    @abstractmethod
    async def send(
        self,
        request: NotificationRequest,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        html_body: Optional[str] = None,
        **kwargs: Any,
    ) -> NotificationResult:
        """
        Send a notification.

        Args:
            request: The notification request with recipient and context.
            subject: Pre-rendered subject line (for email).
            body: Pre-rendered plain text body.
            html_body: Pre-rendered HTML body (for email).
            **kwargs: Additional provider-specific arguments.

        Returns:
            NotificationResult with delivery status.
        """
        pass

    async def health_check(self) -> Dict[str, Any]:
        """
        Perform a health check on the provider.

        Returns:
            Dict with 'healthy' boolean and optional details.
        """
        return {
            "healthy": self.is_configured(),
            "channel": self.channel.value,
            "provider": self.__class__.__name__,
        }
