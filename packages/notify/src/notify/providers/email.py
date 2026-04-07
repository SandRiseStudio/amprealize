"""
Email notification provider supporting SMTP and SendGrid backends.
"""

from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, Optional

from notify.models import (
    Channel,
    NotificationRequest,
    NotificationResult,
    NotificationStatus,
)
from notify.providers.base import NotificationProvider


class EmailProvider(NotificationProvider):
    """
    Email notification provider.

    Supports multiple backends:
    - SMTP: Direct SMTP server connection
    - SendGrid: SendGrid API
    """

    def __init__(
        self,
        backend: str = "smtp",
        # SMTP settings
        smtp_host: Optional[str] = None,
        smtp_port: int = 587,
        smtp_username: Optional[str] = None,
        smtp_password: Optional[str] = None,
        smtp_use_tls: bool = True,
        # SendGrid settings
        sendgrid_api_key: Optional[str] = None,
        # Common settings
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
    ):
        """
        Initialize email provider.

        Args:
            backend: "smtp" or "sendgrid".
            smtp_host: SMTP server hostname.
            smtp_port: SMTP server port (default 587).
            smtp_username: SMTP authentication username.
            smtp_password: SMTP authentication password.
            smtp_use_tls: Use TLS for SMTP connection.
            sendgrid_api_key: SendGrid API key.
            from_email: Default sender email address.
            from_name: Default sender display name.
        """
        self._backend = backend
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._smtp_username = smtp_username
        self._smtp_password = smtp_password
        self._smtp_use_tls = smtp_use_tls
        self._sendgrid_api_key = sendgrid_api_key
        self._from_email = from_email
        self._from_name = from_name

    @property
    def channel(self) -> Channel:
        """Return the email channel."""
        return Channel.EMAIL

    def is_configured(self) -> bool:
        """Check if provider is configured."""
        if self._backend == "smtp":
            return bool(
                self._smtp_host
                and self._smtp_username
                and self._smtp_password
                and self._from_email
            )
        elif self._backend == "sendgrid":
            return bool(self._sendgrid_api_key and self._from_email)
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
        Send an email notification.
        """
        # Validate recipient
        if not request.recipient.email:
            return NotificationResult(
                request_id=request.id,
                channel=self.channel,
                status=NotificationStatus.FAILED,
                provider=self._backend,
                error_message="Recipient email address is required.",
            )

        # Validate content
        if not subject:
            return NotificationResult(
                request_id=request.id,
                channel=self.channel,
                status=NotificationStatus.FAILED,
                provider=self._backend,
                error_message="Email subject is required.",
            )

        if self._backend == "smtp":
            return await self._send_smtp(request, subject, body, html_body)
        elif self._backend == "sendgrid":
            return await self._send_sendgrid(request, subject, body, html_body)
        else:
            return NotificationResult(
                request_id=request.id,
                channel=self.channel,
                status=NotificationStatus.FAILED,
                provider=self._backend,
                error_message=f"Unknown email backend: {self._backend}",
            )

    async def _send_smtp(
        self,
        request: NotificationRequest,
        subject: str,
        body: Optional[str],
        html_body: Optional[str],
    ) -> NotificationResult:
        """Send email via SMTP."""
        try:
            import aiosmtplib
        except ImportError:
            return NotificationResult(
                request_id=request.id,
                channel=self.channel,
                status=NotificationStatus.FAILED,
                provider="smtp",
                error_message="aiosmtplib not installed. Install with: pip install notify[email]",
            )

        try:
            # Build message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = (
                f"{self._from_name} <{self._from_email}>"
                if self._from_name
                else self._from_email
            )
            msg["To"] = (
                f"{request.recipient.name} <{request.recipient.email}>"
                if request.recipient.name
                else request.recipient.email
            )

            if body:
                msg.attach(MIMEText(body, "plain"))
            if html_body:
                msg.attach(MIMEText(html_body, "html"))

            # Send via SMTP
            await aiosmtplib.send(
                msg,
                hostname=self._smtp_host,
                port=self._smtp_port,
                username=self._smtp_username,
                password=self._smtp_password,
                use_tls=self._smtp_use_tls,
            )

            return NotificationResult(
                request_id=request.id,
                channel=self.channel,
                status=NotificationStatus.SENT,
                provider="smtp",
                sent_at=datetime.utcnow(),
            )
        except Exception as e:
            return NotificationResult(
                request_id=request.id,
                channel=self.channel,
                status=NotificationStatus.FAILED,
                provider="smtp",
                error_message=str(e),
            )

    async def _send_sendgrid(
        self,
        request: NotificationRequest,
        subject: str,
        body: Optional[str],
        html_body: Optional[str],
    ) -> NotificationResult:
        """Send email via SendGrid API."""
        try:
            import httpx
        except ImportError:
            return NotificationResult(
                request_id=request.id,
                channel=self.channel,
                status=NotificationStatus.FAILED,
                provider="sendgrid",
                error_message="httpx not installed",
            )

        try:
            payload = {
                "personalizations": [
                    {
                        "to": [{"email": request.recipient.email}],
                    }
                ],
                "from": {"email": self._from_email},
                "subject": subject,
                "content": [],
            }

            if request.recipient.name:
                payload["personalizations"][0]["to"][0]["name"] = request.recipient.name
            if self._from_name:
                payload["from"]["name"] = self._from_name

            if body:
                payload["content"].append({"type": "text/plain", "value": body})
            if html_body:
                payload["content"].append({"type": "text/html", "value": html_body})

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.sendgrid.com/v3/mail/send",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._sendgrid_api_key}",
                        "Content-Type": "application/json",
                    },
                )

            if response.status_code in (200, 201, 202):
                return NotificationResult(
                    request_id=request.id,
                    channel=self.channel,
                    status=NotificationStatus.SENT,
                    provider="sendgrid",
                    sent_at=datetime.utcnow(),
                    provider_message_id=response.headers.get("X-Message-Id"),
                )
            else:
                return NotificationResult(
                    request_id=request.id,
                    channel=self.channel,
                    status=NotificationStatus.FAILED,
                    provider="sendgrid",
                    error_message=response.text,
                )
        except Exception as e:
            return NotificationResult(
                request_id=request.id,
                channel=self.channel,
                status=NotificationStatus.FAILED,
                provider="sendgrid",
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
