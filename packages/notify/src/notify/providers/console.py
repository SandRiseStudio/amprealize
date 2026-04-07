"""
Console notification provider for development and testing.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from notify.models import (
    Channel,
    NotificationRequest,
    NotificationResult,
    NotificationStatus,
)
from notify.providers.base import NotificationProvider


class ConsoleProvider(NotificationProvider):
    """
    Console-based notification provider for development and testing.

    Prints notifications to stdout instead of sending them.
    """

    def __init__(self, prefix: str = "[NOTIFY]"):
        """
        Initialize console provider.

        Args:
            prefix: Prefix for console output.
        """
        self._prefix = prefix

    @property
    def channel(self) -> Channel:
        """Return the console channel."""
        return Channel.CONSOLE

    def is_configured(self) -> bool:
        """Console provider is always configured."""
        return True

    async def send(
        self,
        request: NotificationRequest,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        html_body: Optional[str] = None,
        **kwargs: Any,
    ) -> NotificationResult:
        """
        Print notification to console.
        """
        print(f"\n{self._prefix} ===== NOTIFICATION =====")
        print(f"{self._prefix} Type: {request.notification_type}")
        print(f"{self._prefix} To: {request.recipient.email or request.recipient.phone or request.recipient.slack_id}")
        if request.recipient.name:
            print(f"{self._prefix} Name: {request.recipient.name}")
        if subject:
            print(f"{self._prefix} Subject: {subject}")
        if body:
            print(f"{self._prefix} Body:")
            for line in body.split('\n'):
                print(f"{self._prefix}   {line}")
        print(f"{self._prefix} ========================\n")

        return NotificationResult(
            request_id=request.id,
            channel=self.channel,
            status=NotificationStatus.SENT,
            provider="console",
            sent_at=datetime.utcnow(),
        )

    async def health_check(self) -> Dict[str, Any]:
        """Console provider is always healthy."""
        return {
            "healthy": True,
            "channel": self.channel.value,
            "provider": "console",
        }
