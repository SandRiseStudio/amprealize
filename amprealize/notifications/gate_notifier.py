"""Gate event notifier for execution pipeline.

Coordinates notifications across channels (SSE, webhook, Slack) when
gate events occur during agent execution.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class GateEventType(str, Enum):
    """Types of gate-related events."""
    GATE_WAITING = "gate.waiting"
    CLARIFICATION_NEEDED = "gate.clarification_needed"
    GATE_APPROVED = "gate.approved"
    GATE_SOFT_PASSED = "gate.soft_passed"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"


@dataclass
class GateEvent:
    """A gate event to be dispatched to notification channels."""
    event_type: GateEventType
    run_id: str
    work_item_id: str
    phase: str
    gate_type: Optional[str] = None  # "STRICT" | "SOFT" | "NONE"
    agent_id: Optional[str] = None
    org_id: Optional[str] = None
    project_id: Optional[str] = None
    work_item_title: Optional[str] = None
    clarification_questions: Optional[List[Dict[str, Any]]] = None
    approval_notes: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> Dict[str, Any]:
        """Convert to notification payload dict."""
        payload = {
            "run_id": self.run_id,
            "work_item_id": self.work_item_id,
            "phase": self.phase,
            "gate_type": self.gate_type,
            "agent_id": self.agent_id,
            "org_id": self.org_id,
            "project_id": self.project_id,
            "work_item_title": self.work_item_title,
        }
        if self.clarification_questions:
            payload["clarification_questions"] = self.clarification_questions
        if self.approval_notes:
            payload["approval_notes"] = self.approval_notes
        if self.error:
            payload["error"] = self.error

        # Add actionable URLs
        base_url = os.environ.get("AMPREALIZE_API_BASE_URL", "http://localhost:8000")
        payload["links"] = {
            "approve_url": (
                f"{base_url}/api/v1/work-items/{self.work_item_id}:approve-gate"
                f"?project_id={self.project_id or ''}"
            ),
            "clarify_url": (
                f"{base_url}/api/v1/work-items/{self.work_item_id}:clarify"
                f"?project_id={self.project_id or ''}"
            ),
            "status_url": (
                f"{base_url}/api/v1/work-items/{self.work_item_id}/execution"
                f"?project_id={self.project_id or ''}"
            ),
            "run_events_url": (
                f"{base_url}/api/v1/runs/{self.run_id}/events"
            ),
        }
        return payload

    def to_slack_blocks(self) -> List[Dict[str, Any]]:
        """Build Slack Block Kit blocks for this gate event."""
        emoji = {
            GateEventType.GATE_WAITING: "🚧",
            GateEventType.CLARIFICATION_NEEDED: "❓",
            GateEventType.GATE_APPROVED: "✅",
            GateEventType.GATE_SOFT_PASSED: "⏩",
            GateEventType.RUN_COMPLETED: "🎉",
            GateEventType.RUN_FAILED: "❌",
        }.get(self.event_type, "📋")

        title = self.work_item_title or self.work_item_id
        phase_display = self.phase.upper() if self.phase else "UNKNOWN"

        blocks: List[Dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} {self.event_type.value}",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Work Item:*\n{title}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Phase:*\n{phase_display}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Gate:*\n{self.gate_type or 'N/A'}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Run:*\n`{self.run_id[:12]}...`",
                    },
                ],
            },
        ]

        # Add clarification questions if present
        if self.clarification_questions:
            q_text = "\n".join(
                f"• {q.get('question', q.get('text', str(q)))}"
                for q in self.clarification_questions
            )
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Clarification Questions:*\n{q_text}",
                },
            })

        # Add error if present
        if self.error:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Error:*\n```{self.error}```",
                },
            })

        # Add approval notes if present
        if self.approval_notes:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Notes:*\n{self.approval_notes}",
                },
            })

        # Add context with run details
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"Agent: `{self.agent_id or 'N/A'}` | "
                        f"Project: `{self.project_id or 'N/A'}`"
                    ),
                },
            ],
        })

        return blocks


class GateNotifier:
    """Coordinates gate event notifications across channels.

    Dispatches events to:
    - ExecutionEventHub (SSE/WebSocket subscribers)
    - Webhook callbacks (per-run callback_url)
    - Slack (via packages/notify SlackProvider)
    """

    def __init__(
        self,
        event_hub: Optional[Any] = None,
        webhook_dispatcher: Optional[Any] = None,
        slack_webhook_url: Optional[str] = None,
    ):
        self._event_hub = event_hub
        self._webhook_dispatcher = webhook_dispatcher
        self._slack_webhook_url = slack_webhook_url or os.environ.get(
            "AMPREALIZE_SLACK_WEBHOOK_URL"
        )
        self._notify_service = None

        # Initialize Slack provider if URL configured
        if self._slack_webhook_url:
            self._init_slack()

    def _init_slack(self) -> None:
        """Initialize the Slack notification provider."""
        try:
            from notify.service import NotifyService
            from notify.providers.slack import SlackProvider
            from notify.models import Channel

            self._notify_service = NotifyService()
            provider = SlackProvider(
                backend="webhook",
                webhook_url=self._slack_webhook_url,
            )
            self._notify_service.register_provider(provider)
            logger.info("Slack gate notifications enabled")
        except ImportError:
            logger.debug("notify package not available — Slack notifications disabled")
        except Exception as exc:
            logger.warning(f"Failed to initialize Slack notifications: {exc}")

    async def notify(
        self,
        event: GateEvent,
        callback_urls: Optional[List[str]] = None,
    ) -> None:
        """Dispatch a gate event to all configured channels.

        Args:
            event: The gate event to dispatch.
            callback_urls: Optional webhook URLs for this specific run.
        """
        payload = event.to_payload()

        # Fire-and-forget all notifications concurrently
        tasks = []

        # 1. Publish to EventHub (SSE/WebSocket)
        if self._event_hub:
            tasks.append(self._notify_event_hub(event, payload))

        # 2. Dispatch webhooks
        if callback_urls and self._webhook_dispatcher:
            tasks.append(
                self._notify_webhooks(event, payload, callback_urls)
            )

        # 3. Send Slack notification
        if self._notify_service and self._slack_webhook_url:
            tasks.append(self._notify_slack(event))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _notify_event_hub(
        self, event: GateEvent, payload: Dict[str, Any]
    ) -> None:
        """Publish gate event to ExecutionEventHub."""
        try:
            self._event_hub.publish_gate_event(event.event_type.value, payload)
        except Exception as exc:
            logger.warning(f"Failed to publish gate event to hub: {exc}")

    async def _notify_webhooks(
        self,
        event: GateEvent,
        payload: Dict[str, Any],
        callback_urls: List[str],
    ) -> None:
        """Send webhook callbacks."""
        try:
            await self._webhook_dispatcher.dispatch_many(
                urls=callback_urls,
                event=event.event_type.value,
                payload=payload,
            )
        except Exception as exc:
            logger.warning(f"Webhook dispatch failed: {exc}")

    async def _notify_slack(self, event: GateEvent) -> None:
        """Send Slack notification."""
        try:
            from notify.models import (
                NotificationRequest,
                Recipient,
                Channel,
                Priority as NotifyPriority,
            )

            blocks = event.to_slack_blocks()
            title = event.work_item_title or event.work_item_id

            # Map event type to notification priority
            priority = NotifyPriority.NORMAL
            if event.event_type in (
                GateEventType.GATE_WAITING,
                GateEventType.CLARIFICATION_NEEDED,
            ):
                priority = NotifyPriority.HIGH
            elif event.event_type == GateEventType.RUN_FAILED:
                priority = NotifyPriority.URGENT

            request = NotificationRequest(
                notification_type=f"execution.{event.event_type.value}",
                channel=Channel.SLACK,
                recipient=Recipient(
                    slack_id="channel",  # Webhook posts to configured channel
                ),
                context={
                    "run_id": event.run_id,
                    "work_item_id": event.work_item_id,
                    "phase": event.phase,
                },
                priority=priority,
            )

            emoji = {
                GateEventType.GATE_WAITING: "🚧",
                GateEventType.CLARIFICATION_NEEDED: "❓",
                GateEventType.GATE_APPROVED: "✅",
                GateEventType.RUN_COMPLETED: "🎉",
                GateEventType.RUN_FAILED: "❌",
            }.get(event.event_type, "📋")

            result = await self._notify_service.send(
                request,
                subject=f"{emoji} {event.event_type.value}: {title}",
                body=f"Phase: {event.phase}, Gate: {event.gate_type or 'N/A'}",
                blocks=blocks,
            )

            if result.status.value == "failed":
                logger.warning(
                    f"Slack notification failed: {result.error_message}"
                )
            else:
                logger.info(f"Slack notification sent for {event.event_type.value}")

        except ImportError:
            pass
        except Exception as exc:
            logger.warning(f"Slack notification failed: {exc}")
