"""
Slack notification provider supporting webhooks and Slack API.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from notify.models import (
    Channel,
    NotificationRequest,
    NotificationResult,
    NotificationStatus,
)
from notify.providers.base import NotificationProvider


class SlackProvider(NotificationProvider):
    """
    Slack notification provider.

    Supports multiple backends:
    - webhook: Incoming webhook URL
    - api: Slack Web API with OAuth token
    """

    def __init__(
        self,
        backend: str = "webhook",
        webhook_url: Optional[str] = None,
        api_token: Optional[str] = None,
        default_channel: Optional[str] = None,
    ):
        """
        Initialize Slack provider.

        Args:
            backend: "webhook" or "api".
            webhook_url: Incoming webhook URL (for webhook backend).
            api_token: Slack Bot OAuth token (for api backend).
            default_channel: Default channel ID for api backend.
        """
        self._backend = backend
        self._webhook_url = webhook_url
        self._api_token = api_token
        self._default_channel = default_channel

    @property
    def channel(self) -> Channel:
        """Return the Slack channel."""
        return Channel.SLACK

    def is_configured(self) -> bool:
        """Check if provider is configured."""
        if self._backend == "webhook":
            return bool(self._webhook_url)
        elif self._backend == "api":
            return bool(self._api_token)
        return False

    async def send(
        self,
        request: NotificationRequest,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        html_body: Optional[str] = None,
        blocks: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> NotificationResult:
        """
        Send a Slack notification.

        Args:
            request: The notification request.
            subject: Used as the message header/title.
            body: Plain text message content.
            html_body: Not used for Slack.
            blocks: Slack Block Kit blocks for rich formatting.
        """
        if self._backend == "webhook":
            return await self._send_webhook(request, subject, body, blocks)
        elif self._backend == "api":
            return await self._send_api(request, subject, body, blocks)
        else:
            return NotificationResult(
                request_id=request.id,
                channel=self.channel,
                status=NotificationStatus.FAILED,
                provider=self._backend,
                error_message=f"Unknown Slack backend: {self._backend}",
            )

    async def _send_webhook(
        self,
        request: NotificationRequest,
        subject: Optional[str],
        body: Optional[str],
        blocks: Optional[List[Dict[str, Any]]],
    ) -> NotificationResult:
        """Send via incoming webhook."""
        try:
            import httpx
        except ImportError:
            return NotificationResult(
                request_id=request.id,
                channel=self.channel,
                status=NotificationStatus.FAILED,
                provider="slack_webhook",
                error_message="httpx not installed",
            )

        try:
            payload: Dict[str, Any] = {}

            if blocks:
                payload["blocks"] = blocks

            # Build text content
            text_parts = []
            if subject:
                text_parts.append(f"*{subject}*")
            if body:
                text_parts.append(body)

            if text_parts:
                payload["text"] = "\n".join(text_parts)

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self._webhook_url,
                    json=payload,
                )

            if response.status_code == 200:
                return NotificationResult(
                    request_id=request.id,
                    channel=self.channel,
                    status=NotificationStatus.SENT,
                    provider="slack_webhook",
                    sent_at=datetime.utcnow(),
                )
            else:
                return NotificationResult(
                    request_id=request.id,
                    channel=self.channel,
                    status=NotificationStatus.FAILED,
                    provider="slack_webhook",
                    error_message=f"Webhook returned {response.status_code}: {response.text}",
                )
        except Exception as e:
            return NotificationResult(
                request_id=request.id,
                channel=self.channel,
                status=NotificationStatus.FAILED,
                provider="slack_webhook",
                error_message=str(e),
            )

    async def _send_api(
        self,
        request: NotificationRequest,
        subject: Optional[str],
        body: Optional[str],
        blocks: Optional[List[Dict[str, Any]]],
    ) -> NotificationResult:
        """Send via Slack Web API."""
        try:
            import httpx
        except ImportError:
            return NotificationResult(
                request_id=request.id,
                channel=self.channel,
                status=NotificationStatus.FAILED,
                provider="slack_api",
                error_message="httpx not installed",
            )

        try:
            # Determine channel - use recipient slack_id or default
            channel_id = request.recipient.slack_id or self._default_channel
            if not channel_id:
                return NotificationResult(
                    request_id=request.id,
                    channel=self.channel,
                    status=NotificationStatus.FAILED,
                    provider="slack_api",
                    error_message="No Slack channel or user ID specified",
                )

            payload: Dict[str, Any] = {
                "channel": channel_id,
            }

            if blocks:
                payload["blocks"] = blocks

            # Build text content
            text_parts = []
            if subject:
                text_parts.append(f"*{subject}*")
            if body:
                text_parts.append(body)

            if text_parts:
                payload["text"] = "\n".join(text_parts)

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://slack.com/api/chat.postMessage",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._api_token}",
                        "Content-Type": "application/json",
                    },
                )

            data = response.json()
            if data.get("ok"):
                return NotificationResult(
                    request_id=request.id,
                    channel=self.channel,
                    status=NotificationStatus.SENT,
                    provider="slack_api",
                    sent_at=datetime.utcnow(),
                    provider_message_id=data.get("ts"),
                )
            else:
                return NotificationResult(
                    request_id=request.id,
                    channel=self.channel,
                    status=NotificationStatus.FAILED,
                    provider="slack_api",
                    error_message=data.get("error", "Unknown Slack API error"),
                )
        except Exception as e:
            return NotificationResult(
                request_id=request.id,
                channel=self.channel,
                status=NotificationStatus.FAILED,
                provider="slack_api",
                error_message=str(e),
            )

    async def health_check(self) -> Dict[str, Any]:
        """Check provider health."""
        return {
            "healthy": self.is_configured(),
            "channel": self.channel.value,
            "provider": self._backend,
            "configured": self.is_configured(),
        }
