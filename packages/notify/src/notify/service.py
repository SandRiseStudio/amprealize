"""
Main NotifyService for orchestrating notifications.
"""

from typing import Any, Dict, List, Optional

from notify.models import (
    BatchNotificationResult,
    Channel,
    NotificationRequest,
    NotificationResult,
    NotificationStatus,
    Recipient,
)
from notify.providers.base import NotificationProvider
from notify.templates import TemplateEngine


class NotifyService:
    """
    Central notification service that coordinates providers and templates.

    Usage:
        service = NotifyService()
        service.register_provider(EmailProvider(...))
        service.register_provider(SlackProvider(...))

        # Direct content
        result = await service.send(request, subject="Hello", body="Message")

        # Template-based
        result = await service.send_with_template(request, template_name="invite")
    """

    def __init__(
        self,
        template_engine: Optional[TemplateEngine] = None,
    ):
        """
        Initialize the notification service.

        Args:
            template_engine: Optional template engine for rendering templates.
        """
        self._providers: Dict[Channel, NotificationProvider] = {}
        self._template_engine = template_engine or TemplateEngine()

    def register_provider(self, provider: NotificationProvider) -> None:
        """
        Register a notification provider for a channel.

        Args:
            provider: The provider to register.
        """
        self._providers[provider.channel] = provider

    def get_provider(self, channel: Channel) -> Optional[NotificationProvider]:
        """
        Get the provider for a channel.

        Args:
            channel: The channel to get the provider for.

        Returns:
            The provider or None if not registered.
        """
        return self._providers.get(channel)

    @property
    def template_engine(self) -> TemplateEngine:
        """Get the template engine."""
        return self._template_engine

    async def send(
        self,
        request: NotificationRequest,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        html_body: Optional[str] = None,
        **kwargs: Any,
    ) -> NotificationResult:
        """
        Send a notification with direct content.

        Args:
            request: The notification request.
            subject: Subject line (for email).
            body: Plain text body.
            html_body: Optional HTML body.
            **kwargs: Additional provider-specific args.

        Returns:
            NotificationResult with delivery status.
        """
        # Get provider for the channel
        provider = self._providers.get(request.channel)
        if not provider:
            return NotificationResult(
                request_id=request.id,
                channel=request.channel,
                status=NotificationStatus.FAILED,
                provider="none",
                error_message=f"No provider registered for channel: {request.channel.value}",
            )

        # Check if provider is configured
        if not provider.is_configured():
            return NotificationResult(
                request_id=request.id,
                channel=request.channel,
                status=NotificationStatus.FAILED,
                provider=provider.__class__.__name__,
                error_message=f"Provider not configured for channel: {request.channel.value}",
            )

        # Send via provider
        return await provider.send(
            request,
            subject=subject,
            body=body,
            html_body=html_body,
            **kwargs,
        )

    async def send_with_template(
        self,
        request: NotificationRequest,
        template_name: Optional[str] = None,
    ) -> NotificationResult:
        """
        Send a notification using templates.

        Args:
            request: The notification request.
            template_name: Template name to use. Defaults to request.notification_type.

        Returns:
            NotificationResult with delivery status.
        """
        # Get provider for the channel
        provider = self._providers.get(request.channel)
        if not provider:
            return NotificationResult(
                request_id=request.id,
                channel=request.channel,
                status=NotificationStatus.FAILED,
                provider="none",
                error_message=f"No provider registered for channel: {request.channel.value}",
            )

        # Check if provider is configured
        if not provider.is_configured():
            return NotificationResult(
                request_id=request.id,
                channel=request.channel,
                status=NotificationStatus.FAILED,
                provider=provider.__class__.__name__,
                error_message=f"Provider not configured for channel: {request.channel.value}",
            )

        # Render templates
        try:
            rendered = self._template_engine.render(
                template_name or request.notification_type,
                request.context,
            )
        except Exception as e:
            return NotificationResult(
                request_id=request.id,
                channel=request.channel,
                status=NotificationStatus.FAILED,
                provider=provider.__class__.__name__,
                error_message=f"Template rendering failed: {str(e)}",
            )

        # Send via provider
        return await provider.send(
            request,
            subject=rendered.get("subject"),
            body=rendered.get("body"),
            html_body=rendered.get("html_body"),
        )

    async def send_multi_channel(
        self,
        notification_type: str,
        recipient: Recipient,
        channels: List[Channel],
        context: Optional[Dict[str, Any]] = None,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        html_body: Optional[str] = None,
        **kwargs: Any,
    ) -> BatchNotificationResult:
        """
        Send a notification to multiple channels at once.

        Args:
            notification_type: Type of notification.
            recipient: The recipient.
            channels: List of channels to send to.
            context: Template context variables.
            subject: Subject line (for email).
            body: Plain text body.
            html_body: Optional HTML body.
            **kwargs: Additional arguments.

        Returns:
            BatchNotificationResult with results for each channel.
        """
        results: List[NotificationResult] = []

        for channel in channels:
            request = NotificationRequest(
                notification_type=notification_type,
                channel=channel,
                recipient=recipient,
                context=context or {},
            )
            result = await self.send(
                request,
                subject=subject,
                body=body,
                html_body=html_body,
                **kwargs,
            )
            results.append(result)

        return BatchNotificationResult(results=results)

    async def health_check(self) -> Dict[str, Any]:
        """
        Check health of all registered providers.

        Returns:
            Dict with overall health and individual provider statuses.
        """
        provider_health = {}
        all_healthy = True

        for channel, provider in self._providers.items():
            health = await provider.health_check()
            provider_health[channel.value] = health
            if not health.get("healthy", False):
                all_healthy = False

        return {
            "healthy": all_healthy,
            "providers": provider_health,
        }


def create_service(
    enable_console: bool = True,
    template_engine: Optional[TemplateEngine] = None,
) -> NotifyService:
    """
    Factory function to create a NotifyService with default providers.

    Args:
        enable_console: Whether to enable console logging (for debugging).
        template_engine: Optional template engine.

    Returns:
        Configured NotifyService.
    """
    service = NotifyService(template_engine=template_engine)

    if enable_console:
        from notify.providers.console import ConsoleProvider
        service.register_provider(ConsoleProvider())

    return service
