"""
Copy-link notification provider.

Generates shareable links for notifications that can be copied and shared manually.
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


class CopyLinkProvider(NotificationProvider):
    """
    Copy-link provider for generating shareable notification links.

    Instead of actively sending a notification, this provider generates
    a unique link that can be shared manually (e.g., in a UI for copy/paste).
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        path_template: str = "/invite/{token}",
    ):
        """
        Initialize copy-link provider.

        Args:
            base_url: Base URL for generated links (e.g., "https://app.example.com").
            path_template: URL path template with {token} placeholder.
        """
        self._base_url = base_url
        self._path_template = path_template

    @property
    def channel(self) -> Channel:
        """Return the copy_link channel."""
        return Channel.COPY_LINK

    def is_configured(self) -> bool:
        """Check if base_url is configured."""
        return self._base_url is not None

    async def send(
        self,
        request: NotificationRequest,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        html_body: Optional[str] = None,
        **kwargs: Any,
    ) -> NotificationResult:
        """
        Generate a shareable link for the notification.

        The link is returned in the result metadata under the 'url' key.
        """
        # Check if invite_url is already in context
        invite_url = request.context.get("invite_url")

        if not invite_url:
            # Generate URL from base_url and token
            token = request.context.get("token")
            if self._base_url and token:
                path = self._path_template.format(token=token)
                invite_url = f"{self._base_url}{path}"
            else:
                return NotificationResult(
                    request_id=request.id,
                    channel=self.channel,
                    status=NotificationStatus.FAILED,
                    provider="copy_link",
                    error_message="No invite URL available. Provide 'invite_url' in context or configure base_url with 'token'.",
                )

        return NotificationResult(
            request_id=request.id,
            channel=self.channel,
            status=NotificationStatus.SENT,
            provider="copy_link",
            sent_at=datetime.utcnow(),
            metadata={"url": invite_url},
        )

    async def health_check(self) -> Dict[str, Any]:
        """Check provider health."""
        return {
            "healthy": True,  # Copy-link is always functional
            "channel": self.channel.value,
            "provider": "copy_link",
            "configured": self.is_configured(),
        }
