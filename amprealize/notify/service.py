"""Amprealize Notify Service wrapper.

This module provides a thin wrapper around the standalone notify.NotifyService,
wiring hooks to amprealize services for action tracking, compliance, and metrics.

The standalone package handles all notification logic; this wrapper only provides
the integration glue to amprealize.s infrastructure.

NOTE: The standalone notify package is REQUIRED. Install with:
    pip install -e ./packages/notify
"""

from typing import Optional, Dict, Any, List
from pathlib import Path
import uuid
from datetime import datetime, UTC

# Import from standalone notify package (required)
from notify import (
    NotifyService as StandaloneNotifyService,
    NotificationRequest,
    NotificationResult,
    BatchNotificationResult,
    Channel,
    NotificationStatus,
    Recipient,
    NotificationProvider,
    TemplateEngine,
    create_service as standalone_create_service,
)

# amprealize services
from amprealize.action_service import ActionService
from amprealize.action_contracts import ActionCreateRequest, Actor, Action
from amprealize.compliance_service import ComplianceService, RecordStepRequest
from amprealize.metrics_service import MetricsService


class AmprealizeNotifyService:
    """Notify service integrated with amprealize infrastructure.

    This wrapper wires the standalone notify package to amprealize services:
    - ActionService: Track notification sends for audit and replay
    - ComplianceService: Record compliance gates for sensitive notifications
    - MetricsService: Emit telemetry events for notification metrics

    Usage:
        from amprealize.notify import NotifyService
        from amprealize.action_service import ActionService
        from amprealize.compliance_service import ComplianceService

        service = NotifyService(
            action_service=action_service,
            compliance_service=compliance_service,
            metrics_service=metrics_service,
        )

        result = await service.send(
            NotificationRequest(...),
            subject="Welcome!",
            body="You've been invited...",
        )
    """

    def __init__(
        self,
        action_service: ActionService,
        compliance_service: Optional[ComplianceService] = None,
        metrics_service: Optional[MetricsService] = None,
        template_engine: Optional[TemplateEngine] = None,
        enable_console: bool = False,
    ):
        """Initialize the Amprealize Notify service wrapper.

        Args:
            action_service: Amprealize ActionService for audit tracking.
            compliance_service: Amprealize ComplianceService for compliance gates.
            metrics_service: Amprealize MetricsService for telemetry.
            template_engine: Optional template engine for rendering notifications.
            enable_console: Whether to enable console provider for debugging.
        """
        self.action_service = action_service
        self.compliance_service = compliance_service
        self.metrics_service = metrics_service
        self.template_engine = template_engine

        # Default actor for service-initiated actions
        self._default_actor = Actor(
            id="notify-service",
            role="system",
            surface="api",
        )
        # Current actor for tracking (can be overridden per-call)
        self._current_actor: Optional[Actor] = None

        # Create the standalone service
        self._service = standalone_create_service(
            enable_console=enable_console,
            template_engine=template_engine,
        )

    # =========================================================================
    # Provider Management
    # =========================================================================

    def register_provider(self, provider: NotificationProvider) -> None:
        """Register a notification provider.

        Args:
            provider: Provider instance to register.
        """
        self._service.register_provider(provider)

    def get_provider(self, channel: Channel) -> Optional[NotificationProvider]:
        """Get a provider by channel.

        Args:
            channel: Channel to get provider for.

        Returns:
            Provider instance or None if not registered.
        """
        return self._service.get_provider(channel)

    # =========================================================================
    # Notification Sending
    # =========================================================================

    async def send(
        self,
        request: NotificationRequest,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        html_body: Optional[str] = None,
        actor: Optional[Actor] = None,
        run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> NotificationResult:
        """Send a notification with action tracking.

        Args:
            request: Notification request with recipient and channel.
            subject: Notification subject/title.
            body: Plain text body.
            html_body: HTML body (for email).
            actor: Actor initiating the notification (for audit).
            run_id: Associated run ID (for linking actions).
            **kwargs: Additional provider-specific parameters.

        Returns:
            NotificationResult with status and metadata.
        """
        actor = actor or self._current_actor or self._default_actor
        action_id = str(uuid.uuid4())

        # Record action start
        await self._record_action_start(
            action_id=action_id,
            actor=actor,
            run_id=run_id,
            notification_type=request.notification_type,
            channel=request.channel.value,
            recipient_email=request.recipient.email,
        )

        try:
            # Send via standalone service
            result = await self._service.send(
                request=request,
                subject=subject,
                body=body,
                html_body=html_body,
                **kwargs,
            )

            # Record action completion
            await self._record_action_complete(
                action_id=action_id,
                success=result.success,
                provider=result.provider,
                error_message=result.error_message,
            )

            # Emit metrics
            await self._emit_metrics(
                notification_type=request.notification_type,
                channel=request.channel.value,
                success=result.success,
                provider=result.provider,
            )

            return result

        except Exception as e:
            # Record action failure
            await self._record_action_complete(
                action_id=action_id,
                success=False,
                error_message=str(e),
            )
            raise

    async def send_with_template(
        self,
        request: NotificationRequest,
        template_name: str,
        actor: Optional[Actor] = None,
        run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> NotificationResult:
        """Send a notification using a template.

        Args:
            request: Notification request with recipient, channel, and context.
            template_name: Name of template to render.
            actor: Actor initiating the notification.
            run_id: Associated run ID.
            **kwargs: Additional provider-specific parameters.

        Returns:
            NotificationResult with status and metadata.
        """
        actor = actor or self._current_actor or self._default_actor
        action_id = str(uuid.uuid4())

        # Record action start
        await self._record_action_start(
            action_id=action_id,
            actor=actor,
            run_id=run_id,
            notification_type=request.notification_type,
            channel=request.channel.value,
            recipient_email=request.recipient.email,
            template_name=template_name,
        )

        try:
            # Send via standalone service
            result = await self._service.send_with_template(
                request=request,
                template_name=template_name,
                **kwargs,
            )

            # Record action completion
            await self._record_action_complete(
                action_id=action_id,
                success=result.success,
                provider=result.provider,
                error_message=result.error_message,
            )

            # Emit metrics
            await self._emit_metrics(
                notification_type=request.notification_type,
                channel=request.channel.value,
                success=result.success,
                provider=result.provider,
                template_name=template_name,
            )

            return result

        except Exception as e:
            # Record action failure
            await self._record_action_complete(
                action_id=action_id,
                success=False,
                error_message=str(e),
            )
            raise

    async def send_multi_channel(
        self,
        notification_type: str,
        recipient: Recipient,
        channels: List[Channel],
        context: Optional[Dict[str, Any]] = None,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        html_body: Optional[str] = None,
        actor: Optional[Actor] = None,
        run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> BatchNotificationResult:
        """Send to multiple channels with action tracking.

        Args:
            notification_type: Type of notification.
            recipient: Recipient information.
            channels: List of channels to send to.
            context: Template context.
            subject: Notification subject.
            body: Plain text body.
            html_body: HTML body.
            actor: Actor initiating the notification.
            run_id: Associated run ID.
            **kwargs: Additional provider-specific parameters.

        Returns:
            BatchNotificationResult with per-channel results.
        """
        actor = actor or self._current_actor or self._default_actor
        action_id = str(uuid.uuid4())

        # Record action start
        await self._record_action_start(
            action_id=action_id,
            actor=actor,
            run_id=run_id,
            notification_type=notification_type,
            channels=[c.value for c in channels],
            recipient_email=recipient.email,
        )

        try:
            # Send via standalone service
            result = await self._service.send_multi_channel(
                notification_type=notification_type,
                recipient=recipient,
                channels=channels,
                context=context,
                subject=subject,
                body=body,
                html_body=html_body,
                **kwargs,
            )

            # Record action completion
            await self._record_action_complete(
                action_id=action_id,
                success=result.all_successful,
                total_count=result.total_count,
                success_count=result.success_count,
                failure_count=result.failure_count,
            )

            # Emit metrics for each channel
            for channel_result in result.results:
                await self._emit_metrics(
                    notification_type=notification_type,
                    channel=channel_result.channel.value,
                    success=channel_result.success,
                    provider=channel_result.provider,
                )

            return result

        except Exception as e:
            # Record action failure
            await self._record_action_complete(
                action_id=action_id,
                success=False,
                error_message=str(e),
            )
            raise

    async def health_check(self) -> Dict[str, Any]:
        """Check health of all registered providers.

        Returns:
            Health status dictionary.
        """
        return await self._service.health_check()

    # =========================================================================
    # Action Tracking
    # =========================================================================

    async def _record_action_start(
        self,
        action_id: str,
        actor: Actor,
        run_id: Optional[str] = None,
        **details: Any,
    ) -> None:
        """Record notification action start."""
        try:
            await self.action_service.create(
                ActionCreateRequest(
                    action_id=action_id,
                    action_type="notification.send",
                    actor=actor,
                    run_id=run_id,
                    input_data=details,
                    metadata={
                        "service": "notify",
                        "started_at": datetime.now(UTC).isoformat(),
                    },
                )
            )
        except Exception:
            # Don't fail notification if action tracking fails
            pass

    async def _record_action_complete(
        self,
        action_id: str,
        success: bool,
        **details: Any,
    ) -> None:
        """Record notification action completion."""
        try:
            await self.action_service.complete(
                action_id=action_id,
                success=success,
                output_data=details,
            )
        except Exception:
            # Don't fail notification if action tracking fails
            pass

    # =========================================================================
    # Metrics
    # =========================================================================

    async def _emit_metrics(
        self,
        notification_type: str,
        channel: str,
        success: bool,
        provider: Optional[str] = None,
        template_name: Optional[str] = None,
    ) -> None:
        """Emit notification metrics."""
        if not self.metrics_service:
            return

        try:
            await self.metrics_service.emit_event(
                event_type="notification.sent",
                data={
                    "notification_type": notification_type,
                    "channel": channel,
                    "success": success,
                    "provider": provider,
                    "template_name": template_name,
                },
            )
        except Exception:
            # Don't fail notification if metrics fail
            pass

    # =========================================================================
    # Context Management
    # =========================================================================

    def set_actor(self, actor: Actor) -> None:
        """Set the current actor for subsequent operations.

        Args:
            actor: Actor to use for action tracking.
        """
        self._current_actor = actor

    def clear_actor(self) -> None:
        """Clear the current actor."""
        self._current_actor = None


def create_amprealize_service(
    action_service: ActionService,
    compliance_service: Optional[ComplianceService] = None,
    metrics_service: Optional[MetricsService] = None,
    template_engine: Optional[TemplateEngine] = None,
    enable_console: bool = False,
) -> AmprealizeNotifyService:
    """Create an Amprealize-integrated notify service.

    Args:
        action_service: Amprealize ActionService for audit tracking.
        compliance_service: Amprealize ComplianceService for compliance gates.
        metrics_service: Amprealize MetricsService for telemetry.
        template_engine: Optional template engine for rendering notifications.
        enable_console: Whether to enable console provider for debugging.

    Returns:
        AmprealizeNotifyService instance.
    """
    return AmprealizeNotifyService(
        action_service=action_service,
        compliance_service=compliance_service,
        metrics_service=metrics_service,
        template_engine=template_engine,
        enable_console=enable_console,
    )
