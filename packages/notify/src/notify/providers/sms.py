"""
SMS notification provider supporting Twilio.
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


class SMSProvider(NotificationProvider):
    """
    SMS notification provider.

    Supports:
    - Twilio: Twilio Messaging API
    """

    def __init__(
        self,
        backend: str = "twilio",
        # Twilio settings
        account_sid: Optional[str] = None,
        auth_token: Optional[str] = None,
        from_number: Optional[str] = None,
    ):
        """
        Initialize SMS provider.

        Args:
            backend: Currently only "twilio" is supported.
            account_sid: Twilio Account SID.
            auth_token: Twilio Auth Token.
            from_number: Twilio phone number to send from.
        """
        self._backend = backend
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._from_number = from_number

    @property
    def channel(self) -> Channel:
        """Return the SMS channel."""
        return Channel.SMS

    def is_configured(self) -> bool:
        """Check if provider is configured."""
        if self._backend == "twilio":
            return bool(
                self._account_sid
                and self._auth_token
                and self._from_number
            )
        return False

    async def send(
        self,
        request: NotificationRequest,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        html_body: Optional[str] = None,
        **kwargs: Any,
    ) -> NotificationResult:
        """
        Send an SMS notification.

        Args:
            request: The notification request.
            subject: Not used for SMS.
            body: The SMS message body.
            html_body: Not used for SMS.
        """
        # Validate recipient
        if not request.recipient.phone:
            return NotificationResult(
                request_id=request.id,
                channel=self.channel,
                status=NotificationStatus.FAILED,
                provider=self._backend,
                error_message="Recipient phone number is required.",
            )

        # Validate content
        if not body:
            return NotificationResult(
                request_id=request.id,
                channel=self.channel,
                status=NotificationStatus.FAILED,
                provider=self._backend,
                error_message="SMS body is required.",
            )

        if self._backend == "twilio":
            return await self._send_twilio(request, body)
        else:
            return NotificationResult(
                request_id=request.id,
                channel=self.channel,
                status=NotificationStatus.FAILED,
                provider=self._backend,
                error_message=f"Unknown SMS backend: {self._backend}",
            )

    async def _send_twilio(
        self,
        request: NotificationRequest,
        body: str,
    ) -> NotificationResult:
        """Send SMS via Twilio API."""
        try:
            import httpx
        except ImportError:
            return NotificationResult(
                request_id=request.id,
                channel=self.channel,
                status=NotificationStatus.FAILED,
                provider="twilio",
                error_message="httpx not installed",
            )

        try:
            url = f"https://api.twilio.com/2010-04-01/Accounts/{self._account_sid}/Messages.json"

            payload = {
                "To": request.recipient.phone,
                "From": self._from_number,
                "Body": body,
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    data=payload,
                    auth=(self._account_sid, self._auth_token),
                )

            data = response.json()

            if response.status_code == 201:
                return NotificationResult(
                    request_id=request.id,
                    channel=self.channel,
                    status=NotificationStatus.SENT,
                    provider="twilio",
                    sent_at=datetime.utcnow(),
                    provider_message_id=data.get("sid"),
                )
            else:
                return NotificationResult(
                    request_id=request.id,
                    channel=self.channel,
                    status=NotificationStatus.FAILED,
                    provider="twilio",
                    error_code=str(data.get("code")),
                    error_message=data.get("message", "Unknown Twilio error"),
                )
        except Exception as e:
            return NotificationResult(
                request_id=request.id,
                channel=self.channel,
                status=NotificationStatus.FAILED,
                provider="twilio",
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
